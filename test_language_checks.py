import base64
import io
import json

import httpx
import pikepdf
import pytest
from fastapi.testclient import TestClient
from pdfminer.high_level import extract_text
from reportlab.pdfgen.canvas import Canvas

import wording_ai
from language_checks import sentence_candidates
from main import app


def fixture(*, links=False, sentences=()):
    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=True)
    if links:
        for n, (purpose, text, target) in enumerate([
            ("To apply for financial aid, ", "click here", "aid"),
            ("To register for orientation, ", "click here", "orientation"),
            ("", "Visit the library", "library"),
        ]):
            y = 730 - 30*n
            canvas.drawString(40, y, purpose + text)
            x = 40 + canvas.stringWidth(purpose)
            rect = (x, y-2, x+canvas.stringWidth(text), y+12)
            canvas.linkURL(f"https://school.edu/{target}?secret=xyz", rect)
    for n, line in enumerate(sentences):
        canvas.drawString(40, 600 - 30*n, line)
    canvas.showPage()
    canvas.save()
    if not links:
        return buffer.getvalue()
    with pikepdf.open(buffer) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        annotation = page.Annots[0]
        tag = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link, P=root, Pg=page.obj,
            K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annotation)))
        root.K = pikepdf.Array([tag])
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        out = io.BytesIO()
        pdf.save(out)
    return out.getvalue()


def process(data):
    response = TestClient(app).post("/process", files={"file": ("example.pdf", data, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()


def artifact(result, key):
    return base64.b64decode(result[key]["content_base64"])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_labels_applied_to_individual_links_and_preserved_on_second_upload():
    original = fixture(links=True)
    result = process(original)
    output = artifact(result, "output_pdf")
    assert extract_text(io.BytesIO(output)) == extract_text(io.BytesIO(original))
    links = [f for f in result["findings"] if f["check_id"] == "CHK-LINK"]
    assert len(links) == 2 and all(f["status"] == "needs_human_review" for f in links)
    assert {r["finding_id"] for r in result["repairs"]} == {f["finding_id"] for f in links}
    assert all(r["validation_result"] == "passed" for r in result["repairs"])
    assert result["summary"]["fixed_count"] == 0
    assert result["outcome"] == "completed_with_repairs"
    with pikepdf.open(io.BytesIO(output)) as pdf:
        first, second, third = pdf.pages[0].Annots
        assert first.Contents == pdf.Root.StructTreeRoot.K[0].Alt == "Apply for financial aid"
        assert second.Contents == "Register for orientation"
        assert "/Contents" not in third
        assert first.A.URI == "https://school.edu/aid?secret=xyz"
    assert "annotation only" in links[1]["fix_description"]
    again = process(output)
    assert not again["repairs"] and artifact(again, "output_pdf") == output


def test_descriptive_accessible_labels_are_preserved():
    with pikepdf.open(io.BytesIO(fixture(links=True))) as pdf:
        pdf.Root.StructTreeRoot.K[0].Alt = "Apply for aid"
        pdf.pages[0].Annots[1].Contents = "Register for orientation"
        out = io.BytesIO()
        pdf.save(out)
    assert artifact(process(out.getvalue()), "output_pdf") == out.getvalue()


SENTENCES = ("Select the green button.", "Choose the option on the right.",
             'Select the green button labeled Continue.', "The field is green.")


def test_fallback_rewrites_change_only_the_report():
    data = fixture(sentences=SENTENCES)
    result = process(data)
    wording = [f for f in result["findings"] if f["check_id"] in {"CHK-COLOR", "CHK-SENSORY"}]
    assert [f["check_id"] for f in wording] == ["CHK-COLOR", "CHK-SENSORY"]
    assert "[button label]" in wording[0]["fix_description"]
    assert "[option label]" in wording[1]["fix_description"]
    assert all("fallback draft" in f["fix_description"] for f in wording)
    assert result["repairs"] == [] and artifact(result, "output_pdf") == data
    report = " ".join(extract_text(io.BytesIO(artifact(result, "report_pdf"))).split())
    assert all(f["fix_description"] in report for f in wording)


def ai_response(values):
    part = {"type": "output_text", "text": json.dumps({"suggestions": values})}
    body = {"status": "completed", "output": [{"type": "message", "content": [part]}]}
    return httpx.Response(200, json=body,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"))


def test_ai_labels_and_rewrites_batched_once(monkeypatch):
    data = fixture(links=True, sentences=SENTENCES)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []
    def provider(url, **kwargs):
        payload = kwargs["json"]
        items = json.loads(payload["input"])
        assert "secret=xyz" not in payload["input"]
        assert payload["store"] is False
        calls.append(items)
        return ai_response({i["id"]: {"CHK-LINK": "Open " + i["destination"].split("/")[-1],
                                      "CHK-COLOR": "Select [button name].",
                                      "CHK-SENSORY": "Choose [option name]."}[i["check"]]
                            for i in items})
    monkeypatch.setattr(wording_ai.httpx, "post", provider)
    result = process(data)
    assert len(calls) == 1 and len(calls[0]) == 4
    assert sum("(AI" in (f["fix_description"] or "") for f in result["findings"]) == 4
    with pikepdf.open(io.BytesIO(artifact(result, "output_pdf"))) as pdf:
        assert pdf.pages[0].Annots[0].Contents == pdf.Root.StructTreeRoot.K[0].Alt == "Open aid"
        assert pdf.pages[0].Annots[1].Contents == "Open orientation"


@pytest.mark.parametrize("failure", ["timeout", "malformed", "partial", "unusable"])
def test_ai_falls_back_per_candidate(monkeypatch, failure):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    def provider(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out")
        if failure == "malformed":
            return httpx.Response(200, content=b"{", request=httpx.Request("POST", args[0]))
        return ai_response({"0": "Choose [named button].", "1": []} if failure == "partial" else {"0": " "})
    monkeypatch.setattr(wording_ai.httpx, "post", provider)
    result = process(fixture(sentences=SENTENCES))
    details = [f["fix_description"] for f in result["findings"] if f["fix_description"]]
    assert len(details) == 2
    assert sum("fallback" in s for s in details) == (1 if failure == "partial" else 2)


def test_scanned_page_and_independent_cues():
    result = process(fixture())
    assert any("Page 1" in msg and "extractable" in msg for msg in result["limitations"])
    assert not list(sentence_candidates("The red button is part of the illustration.", 1, 0))


def test_ai_batches_keep_distinct_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    batches = []
    def provider(url, **kwargs):
        items = json.loads(kwargs["json"]["input"])
        batches.append(len(items))
        return ai_response({i["id"]: "Select [control name]." for i in items})
    monkeypatch.setattr(wording_ai.httpx, "post", provider)
    cases = list(sentence_candidates("Select the button marked in green.", 1, 0))
    assert len(cases) == 1
    suggestions = wording_ai.generate(cases * 33)
    assert batches == [32, 1] and set(suggestions) == {str(n) for n in range(33)}
