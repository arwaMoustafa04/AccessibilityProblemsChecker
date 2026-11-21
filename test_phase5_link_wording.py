"""Phase 5: CHK-LINK accessible-label repair and CHK-COLOR / CHK-SENSORY rewrites.

Ported from Steven's language_checks.py / wording_ai.py tests onto the shared
checks/ + remediation/ framework (AI through remediation/ai.py and llm.py).
"""

import base64
import io

import pikepdf
import pymupdf
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from checks.link import destination_hint, fallback_label
from checks.review_text import COLOR_CUE, SENSORY_CUE, rewrite_draft
from main import app
from remediation import ai, wording

SENTENCES = ("Select the green button.", "Choose the option on the right.",
             "Select the green button labeled Continue.", "The field is green.")


def fixture(*, links=False, sentences=(), tagged=True):
    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=True)
    if links:
        for n, (purpose, text, target) in enumerate([
            ("To apply for financial aid, ", "click here", "aid"),
            ("To register for orientation, ", "click here", "orientation"),
            ("", "Visit the library", "library"),
        ]):
            y = 730 - 30 * n
            canvas.drawString(40, y, purpose + text)
            x = 40 + canvas.stringWidth(purpose)
            canvas.linkURL(f"https://school.edu/{target}?secret=xyz",
                           (x, y - 2, x + canvas.stringWidth(text), y + 12))
    for n, line in enumerate(sentences):
        canvas.drawString(40, 600 - 30 * n, line)
    canvas.showPage()
    canvas.save()
    if not (links and tagged):
        return buffer.getvalue()
    with pikepdf.open(buffer) as pdf:  # tag only the first link
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        tag = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link, P=root, Pg=page.obj,
            K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=page.Annots[0])))
        root.K = pikepdf.Array([tag])
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        out = io.BytesIO()
        pdf.save(out)
    return out.getvalue()


def process(data):
    response = TestClient(app).post(
        "/process", files={"file": ("example.pdf", data, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()


def artifact(result, key):
    return base64.b64decode(result[key]["content_base64"])


def page_text(data):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "".join(page.get_text() for page in doc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("VERAPDF_ENABLED", "false")
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setattr("pipeline.ENABLE_REPAIRS", True)


def links_of(result):
    return [f for f in result["findings"] if f["check_id"] == "CHK-LINK"]


def test_rule_labels_written_per_link_and_revalidated():
    original = fixture(links=True)
    result = process(original)
    output = artifact(result, "output_pdf")
    assert page_text(output) == page_text(original)  # visible text unchanged
    links = links_of(result)
    assert [f["suggested_text"] for f in links] == ["Apply for financial aid",
                                                   "Register for orientation"]
    assert all(f["status"] == "needs_human_review" and f["suggestion_source"] == "rule"
               for f in links)
    assert all(f["finding_id"] in result["human_review_items"] for f in links)
    link_repairs = [r for r in result["repairs"]
                    if r["finding_id"] in {f["finding_id"] for f in links}]
    assert len(link_repairs) == 2
    assert all(r["validation_result"] == "passed" and r["method"] == "rule" for r in link_repairs)
    assert "Link tag (/Alt)" in link_repairs[0]["action"]
    assert "not tagged" in link_repairs[1]["action"]
    assert not any(f["check_id"] == "CHK-LINK" for f in result["new_issues_after_repair"])
    with pikepdf.open(io.BytesIO(output)) as pdf:
        first, second, third = pdf.pages[0].Annots
        assert first.Contents == pdf.Root.StructTreeRoot.K[0].Alt == "Apply for financial aid"
        assert second.Contents == "Register for orientation"
        assert "/Contents" not in third  # "Visit the library" is already descriptive
        assert first.A.URI == "https://school.edu/aid?secret=xyz"  # target unchanged


def test_second_upload_of_repaired_pdf_needs_no_link_repair():
    output = artifact(process(fixture(links=True)), "output_pdf")
    again = process(output)
    assert links_of(again) == []


def test_descriptive_accessible_labels_are_preserved():
    with pikepdf.open(io.BytesIO(fixture(links=True))) as pdf:
        pdf.Root.StructTreeRoot.K[0].Alt = "Apply for aid"
        pdf.pages[0].Annots[1].Contents = "Register for orientation"
        out = io.BytesIO()
        pdf.save(out)
    assert links_of(process(out.getvalue())) == []


def test_repairs_off_keeps_suggestion_and_pdf(monkeypatch):
    monkeypatch.setattr("pipeline.ENABLE_REPAIRS", False)
    data = fixture(links=True)
    result = process(data)
    assert result["repairs"] == [] and artifact(result, "output_pdf") == data
    assert links_of(result)[0]["suggested_text"] == "Apply for financial aid"


def test_ai_link_label_used_and_query_string_not_sent(monkeypatch):
    sent = []

    def suggest(context, url):
        sent.append((context, url))
        return "Financial aid application"
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "sends_data", lambda: True)
    monkeypatch.setattr(ai, "suggest_link_text", suggest)
    monkeypatch.setattr(ai, "rewrite_sentence", lambda s, p: None)
    monkeypatch.setattr(ai, "suggest_title", lambda *a: None)
    result = process(fixture(links=True))
    assert sent and all("secret" not in url and url.startswith("school.edu/") for _, url in sent)
    assert "To apply for financial aid, click here" in sent[0][0]
    first = links_of(result)[0]
    assert first["suggested_text"] == "Financial aid application"
    assert first["suggestion_source"] == "llm" and first["status"] == "needs_human_review"
    assert any("external model provider" in line for line in result["limitations"])


@pytest.mark.parametrize("bad", [None, "click here", "[link name]", "x" * 200])
def test_unusable_ai_link_label_falls_back(monkeypatch, bad):
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "sends_data", lambda: False)
    monkeypatch.setattr(ai, "suggest_link_text", lambda c, u: bad)
    monkeypatch.setattr(ai, "rewrite_sentence", lambda s, p: None)
    monkeypatch.setattr(ai, "suggest_title", lambda *a: None)
    first = links_of(process(fixture(links=True)))[0]
    assert first["suggested_text"] == "Apply for financial aid"
    assert first["suggestion_source"] == "rule"


def test_rule_rewrites_are_suggestions_only():
    data = fixture(sentences=SENTENCES)
    result = process(data)
    wording_findings = [f for f in result["findings"]
                        if f["check_id"] in {"CHK-COLOR", "CHK-SENSORY"}]
    drafts = {f["suggested_text"] for f in wording_findings}
    assert "Select the [button label]." in drafts
    assert "Choose the [option label]." in drafts
    assert all(f["status"] == "needs_human_review" for f in wording_findings)
    assert not any(r["finding_id"] in {f["finding_id"] for f in wording_findings}
                   for r in result["repairs"])
    assert page_text(artifact(result, "output_pdf")) == page_text(data)
    report = " ".join(page_text(artifact(result, "report_pdf")).split())
    assert "[button label]" in report


def test_ai_rewrites_capped_and_marked(monkeypatch):
    calls = []

    def rewrite(sentence, problem):
        calls.append((sentence, problem))
        return f"Select the Continue button ({problem})."
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "sends_data", lambda: False)
    monkeypatch.setattr(ai, "rewrite_sentence", rewrite)
    monkeypatch.setattr(ai, "suggest_title", lambda *a: None)
    result = process(fixture(sentences=SENTENCES * 3))
    assert 0 < len(calls) <= wording.MAX_AI_REWRITES
    ai_findings = [f for f in result["findings"] if f["suggestion_source"] == "llm"]
    assert len(ai_findings) == len(calls)
    assert all(f["check_id"] in {"CHK-COLOR", "CHK-SENSORY"} for f in ai_findings)


def test_rewrite_draft_and_named_controls():
    assert rewrite_draft("Select the green button.", COLOR_CUE) == (
        "Select the green button.", "Select the [button label].")
    assert rewrite_draft("Choose the option on the right.", SENSORY_CUE) == (
        "Choose the option on the right.", "Choose the [option label].")
    assert rewrite_draft("Select the green button labeled Continue.", COLOR_CUE) is None
    assert rewrite_draft("The red button is part of the illustration.", COLOR_CUE) is None


def test_fallback_labels_and_destination_hints():
    assert fallback_label("To apply for financial aid, click here", "") == "Apply for financial aid"
    assert fallback_label("", "page 3") == "Go to page 3"
    assert fallback_label("", "school.edu/campus-map") == "Open campus map on school.edu"
    assert fallback_label("", "school.edu/") == "Open link to school.edu"
    assert fallback_label("", "") == "Open linked destination"
    with pikepdf.open(io.BytesIO(fixture(links=True))) as pdf:
        annot = pdf.pages[0].Annots[0]
        assert destination_hint(annot, {}) == "school.edu/aid"
