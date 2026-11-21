"""Person 2 Phase 5: independent saved-PDF, rendering and endpoint assertions."""

import base64
import io

import pikepdf
import pymupdf
import pytest
from fastapi.testclient import TestClient

import pipeline
from checks.base import CheckContext
from checks.verapdf import VeraReport
from main import app
from remediation import ai, nontext
from tester.fixtures.pdf_checks.generate import make_fixture

REAL_DESCRIBE_IMAGE = ai.describe_image


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    # These tests cover writing AI text into the PDF (needs instructor sign-off on REQ-06);
    # the default, suggestion-only behaviour has its own test below.
    monkeypatch.setenv("AI_WRITE_HUMAN_REVIEW_FIXES", "true")
    monkeypatch.setattr(ai, "describe_image", lambda *args: None)
    monkeypatch.setattr(ai, "suggest_title", lambda *args: None)
    monkeypatch.setattr(ai, "sends_data", lambda: False)
    monkeypatch.setattr(CheckContext, "verapdf", property(lambda self: VeraReport(available=False)))


def save(pdf):
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def pages(kinds):
    doc = pymupdf.open()
    pixel = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 20, 20), False)
    pixel.clear_with(180)
    for kind in kinds:
        page = doc.new_page(width=300, height=400)
        if kind in ("scan", "ocr"):
            page.insert_image(page.rect, pixmap=pixel)
        if kind in ("text", "ocr"):
            page.insert_text((30, 30), "Sample document text", render_mode=3 if kind == "ocr" else 0)
        if kind == "whitespace":
            page.insert_text((30, 30), "   ")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.parametrize("kinds", [["scan"], ["blank"], ["whitespace"], ["blank", "scan"]])
@pytest.mark.parametrize("output", ["json", "zip"])
def test_no_text_layer_error(kinds, output):
    response = TestClient(app).post(
        "/process", files={"file": ("scan.pdf", pages(kinds))}, data={"output": output}
    )
    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "error_code": "NO_TEXT_LAYER",
        "message": "PDF has no extractable text layer. OCR is not supported.",
    }


def test_health_and_openapi_expose_version_and_error():
    client = TestClient(app)
    assert client.get("/health").json()["spec_version"] == "0.5.0"
    schema = client.get("/openapi.json").json()
    assert "NO_TEXT_LAYER" in schema["components"]["schemas"]["Error"]["properties"]["error_code"]["enum"]
    assert (
        "no_text_layer"
        in schema["paths"]["/process"]["post"]["responses"]["422"]["content"]["application/json"]["examples"]
    )


def test_mixed_pages_list_scans_not_blank_pages():
    result = pipeline.run_pipeline(pages(["text", "scan", "blank", "scan"]), "mixed.pdf")
    note = next(n for n in result.limitations if "are scanned" in n)
    assert note.startswith("Pages 2, 4 are scanned")
    assert any(f.check_id == "CHK-NONTEXT" and f.location.page == 2 for f in result.findings)
    assert not any(
        f.check_id in {"CHK-SENSORY", "CHK-COLOR", "CHK-LINK"} and f.location.page in {2, 4}
        for f in result.findings
    )


def test_invisible_ocr_text_is_accepted():
    result = pipeline.run_pipeline(pages(["ocr"]), "ocr.pdf")
    assert not any("are scanned" in n for n in result.limitations)


def test_textless_encryption_precedes_scanned_error():
    with pikepdf.open(io.BytesIO(pages(["scan"]))) as pdf:
        buf = io.BytesIO()
        pdf.save(buf, encryption=pikepdf.Encryption(owner="secret", user="secret"))
    response = TestClient(app).post("/process", files={"file": ("locked.pdf", buf.getvalue())})
    assert response.json()["error_code"] == "PASSWORD_PROTECTED_PDF"


def repaired(data):
    result = pipeline.run_pipeline(data, "image-fixture.pdf")
    return result, base64.b64decode(result.output_pdf.content_base64)


@pytest.mark.parametrize(
    "case", ["missing_alt", "blank_alt", "untagged_image", "inline_image", "nested_form"]
)
def test_alt_written_to_correct_figure_and_render_unchanged(case, monkeypatch):
    data = make_fixture(case)
    if case == "nested_form":
        with pikepdf.open(io.BytesIO(data)) as pdf:
            del pdf.Root.StructTreeRoot.K[0].K[0].Alt
            data = save(pdf)
    calls = []

    def describe(image, nearby, mime):
        calls.append((image, nearby, mime))
        assert image.startswith(b"\x89PNG") and mime == "image/png"
        return "Blue square showing the sample graphic"

    monkeypatch.setattr(ai, "describe_image", describe)
    result, out = repaired(data)
    assert len(calls) == 1
    image_findings = [f for f in result.findings if f.check_id == "CHK-NONTEXT"]
    repairs = [r for r in result.repairs if r.finding_id in {f.finding_id for f in image_findings}]
    assert len(repairs) == 1 and repairs[0].validation_result == "passed"
    assert repairs[0].method == "llm"
    assert image_findings[0].suggestion_source == "llm"
    assert image_findings[0].status == "needs_human_review"
    assert image_findings[0].finding_id in result.human_review_items
    with pikepdf.open(io.BytesIO(out)) as pdf:
        figures = [
            o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and o.get("/S") == pikepdf.Name.Figure
        ]
        assert any(str(o.get("/Alt", "")).endswith("[AI-generated, please verify]") for o in figures)
    with pymupdf.open(stream=data) as before, pymupdf.open(stream=out) as after:
        assert before[0].get_pixmap().samples == after[0].get_pixmap().samples
    assert not any(f.check_id == "CHK-NONTEXT" for f in result.new_issues_after_repair)


@pytest.mark.parametrize("case", ["missing_alt", "untagged_image", "inline_image"])
def test_decorative_content_is_artifact(case, monkeypatch):
    monkeypatch.setattr(ai, "describe_image", lambda *args: ai.DECORATIVE)
    data = make_fixture(case)
    result, out = repaired(data)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        ops = pikepdf.parse_content_stream(pdf.pages[0])
        assert any(
            not isinstance(op, pikepdf.ContentStreamInlineImage)
            and str(op.operator) == "BMC"
            and op.operands[0] == pikepdf.Name.Artifact
            for op in ops
        )
        from pdf_checks import detect_pdf_issues

        assert not any(i.check_id == "CHK-NONTEXT" for i in detect_pdf_issues(pdf))
    image_repair = next(r for r in result.repairs if "Artifact" in r.action)
    assert image_repair.method == "llm" and image_repair.validation_result == "passed"
    assert (
        next(f for f in result.findings if f.finding_id == image_repair.finding_id).status
        == "needs_human_review"
    )
    with pymupdf.open(stream=data) as before, pymupdf.open(stream=out) as after:
        assert before[0].get_pixmap().samples == after[0].get_pixmap().samples


@pytest.mark.parametrize("answer", [None, "image1"])
def test_unavailable_or_generic_ai_keeps_manual_suggestion(answer, monkeypatch):
    monkeypatch.setattr(ai, "describe_image", lambda *args: answer)
    result, _ = repaired(make_fixture("missing_alt"))
    finding = next(f for f in result.findings if f.check_id == "CHK-NONTEXT")
    assert finding.suggestion_source == "rule"
    assert not any(r.finding_id == finding.finding_id for r in result.repairs)
    assert any("AI alt text was unavailable" in n for n in result.limitations)


def test_image_cap_and_unrepaired_location_identity(monkeypatch):
    monkeypatch.setattr(nontext, "MAX_IMAGES_PER_PDF", 2)
    calls = []
    monkeypatch.setattr(ai, "describe_image", lambda *args: calls.append(1) or "Blue square example")
    with pikepdf.open(io.BytesIO(make_fixture("untagged_image"))) as pdf:
        pdf.pages[0].contents_add(pdf.make_stream(b"/Im Do /Im Do /Im Do"))
        data = save(pdf)
    result, out = repaired(data)
    assert len(calls) == 2
    assert any("image limit (2 per PDF)" in n for n in result.limitations)
    assert not any(f.check_id == "CHK-NONTEXT" for f in result.new_issues_after_repair)
    assert len([r for r in result.repairs if r.method == "llm"]) == 2
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert len(pdf.Root.StructTreeRoot.ParentTree.Nums[1]) >= 2


def test_existing_alt_and_artifact_never_sent(monkeypatch):
    def unexpected(*args):
        pytest.fail("Existing good alternative/artifact should not be sent")

    monkeypatch.setattr(ai, "describe_image", unexpected)
    for case in ["tagged_image", "artifact_image"]:
        repaired(make_fixture(case))


def test_structure_suggestion_is_rule_only():
    result, out = repaired(make_fixture("table_no_headers"))
    finding = next(f for f in result.findings if f.issue_type == "table_missing_headers")
    assert finding.suggestion_source == "rule" and "first row" in finding.suggested_text
    assert finding.status == "needs_human_review"
    assert not any(r.finding_id == finding.finding_id for r in result.repairs)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert pdf.Root.StructTreeRoot.K[0].K[0].K[0].K[0].S == pikepdf.Name.TD


def test_external_image_disclosure_even_when_ai_returns_nothing(monkeypatch):
    monkeypatch.setattr(ai, "sends_data", lambda: True)
    result, _ = repaired(make_fixture("missing_alt"))
    assert any("image content and page text were sent" in n for n in result.limitations)


def test_image_pixel_limit_is_reported(monkeypatch):
    monkeypatch.setattr(nontext, "MAX_IMAGE_PIXELS", 1)
    monkeypatch.setattr(ai, "describe_image", lambda *args: pytest.fail("Must skip oversized images"))
    result, _ = repaired(make_fixture("missing_alt"))
    assert any("within image limits" in n for n in result.limitations)
    assert not any(r.method == "llm" for r in result.repairs)


def test_repairs_disabled_does_not_call_image_ai(monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", False)
    monkeypatch.setattr(ai, "describe_image", lambda *args: pytest.fail("Repairs are disabled"))
    original = make_fixture("missing_alt")
    result, out = repaired(original)
    assert result.repairs == [] and out == original


def test_decorative_decision_cannot_hide_figure_text(monkeypatch):
    monkeypatch.setattr(ai, "describe_image", lambda *args: ai.DECORATIVE)
    with pikepdf.open(io.BytesIO(make_fixture("missing_alt"))) as pdf:
        page = pdf.pages[0]
        page.contents_add(pdf.make_stream(b"/Figure <</MCID 0>> BDC BT /F1 10 Tf (Important) Tj ET EMC"))
        original = save(pdf)
    result, out = repaired(original)
    assert any("manual tag editing" in n for n in result.limitations)
    assert not any(r.method == "llm" for r in result.repairs)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert pdf.Root.StructTreeRoot.K[0].K[0].S == pikepdf.Name.Figure


def test_model_exception_degrades_to_manual_review(monkeypatch):
    import sys
    import types

    module = types.ModuleType("llm")

    def broken(*args):
        raise TimeoutError("offline")

    module.describe_image = broken
    monkeypatch.setitem(sys.modules, "llm", module)
    # Use the real, exception-isolating shared AI adapter.
    monkeypatch.setattr(ai, "describe_image", REAL_DESCRIBE_IMAGE)
    result, _ = repaired(make_fixture("missing_alt"))
    assert any("AI alt text was unavailable" in n for n in result.limitations)
    assert not any(r.method == "llm" for r in result.repairs)


def test_two_distinct_figures_receive_their_own_descriptions(monkeypatch):
    answers = iter(["Blue square first illustration", "Red square second illustration"])
    monkeypatch.setattr(ai, "describe_image", lambda *args: next(answers))
    with pikepdf.open(io.BytesIO(make_fixture("missing_alt"))) as pdf:
        doc = pdf.Root.StructTreeRoot.K[0]
        second = pdf.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Figure, P=doc, K=1)
        )
        doc.K.append(second)
        pdf.Root.StructTreeRoot.ParentTree.Nums[1].append(second)
        image = pdf.make_stream(bytes([220, 40, 40] * 4))
        for key, value in pdf.pages[0].Resources.XObject.Im.items():
            if key not in ("/Length", "/Filter", "/DecodeParms"):
                image[key] = value
        pdf.pages[0].Resources.XObject.Second = image
        pdf.pages[0].contents_add(pdf.make_stream(b"/Figure <</MCID 1>> BDC /Second Do EMC"))
        original = save(pdf)
    result, out = repaired(original)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        first, second = pdf.Root.StructTreeRoot.K[0].K
        assert str(first.Alt).startswith("Blue square first")
        assert str(second.Alt).startswith("Red square second")
    assert len([r for r in result.repairs if r.method == "llm"]) == 2


def test_check_failing_before_and_after_does_not_discard_repairs(monkeypatch) -> None:
    """A check that crashes on the original too must not throw away the other repairs."""
    from pathlib import Path

    import checks
    import pipeline

    def broken(ctx):
        raise RuntimeError("bug in one check")

    monkeypatch.setitem(checks.CHECK_FUNCTIONS, "CHK-COLOR", broken)
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    data = (Path(__file__).parent / "tester/fixtures/accessibilityIssues.pdf").read_bytes()
    result = pipeline.run_pipeline(data, "accessibilityIssues.pdf")
    assert result.repairs and result.output_pdf.modified
    assert not any("repairs were discarded" in n for n in result.limitations)
    assert any("CHK-COLOR" in n for n in result.limitations)  # the crash is still reported


def test_check_broken_only_by_repair_discards_repairs(monkeypatch) -> None:
    from pathlib import Path

    import checks
    import pipeline

    real = checks.CHECK_FUNCTIONS["CHK-COLOR"]
    seen = {"n": 0}

    def breaks_second_time(ctx):
        seen["n"] += 1
        if seen["n"] > 1:
            raise RuntimeError("repaired file broke this check")
        return real(ctx)

    monkeypatch.setitem(checks.CHECK_FUNCTIONS, "CHK-COLOR", breaks_second_time)
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    data = (Path(__file__).parent / "tester/fixtures/accessibilityIssues.pdf").read_bytes()
    result = pipeline.run_pipeline(data, "accessibilityIssues.pdf")
    assert result.repairs == [] and not result.output_pdf.modified
    assert any("repairs were discarded" in n for n in result.limitations)


def test_untagged_pdf_image_repair_is_not_a_new_structure_issue(monkeypatch):
    # No structure tree at all: the image repair adds a lone Figure tag, so the
    # re-check says "not marked" instead of "no structure tree". Same problem, not new.
    monkeypatch.setattr(ai, "describe_image", lambda *args: "Blue square example")
    with pikepdf.open(io.BytesIO(make_fixture("untagged_image"))) as pdf:
        for key in ("/StructTreeRoot", "/MarkInfo"):
            del pdf.Root[key]
        for page in pdf.pages:
            if "/StructParents" in page.obj:
                del page.obj.StructParents
        data = save(pdf)
    result, out = repaired(data)
    assert any(r.method == "llm" and r.validation_result == "passed" for r in result.repairs)
    assert not any(f.issue_type == "document_not_marked" for f in result.new_issues_after_repair)
    structure = [f for f in result.findings if f.issue_type == "missing_document_structure"]
    assert structure and structure[0].status == "needs_human_review"
    assert any("still not fully tagged" in n for n in result.limitations)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert "/StructTreeRoot" in pdf.Root and "/MarkInfo" not in pdf.Root  # never claims tagged


@pytest.mark.parametrize("answer", ["A blue square used as an example figure.", ai.DECORATIVE])
def test_default_ai_alt_text_is_a_suggestion_only(answer, monkeypatch) -> None:
    """REQ-06 / AC-04: human-review issues are not changed automatically (the default)."""
    monkeypatch.delenv("AI_WRITE_HUMAN_REVIEW_FIXES")
    monkeypatch.setattr(ai, "describe_image", lambda *args: answer)
    data = make_fixture("missing_alt")
    result = pipeline.run_pipeline(data, "missing_alt.pdf")
    nontext = [f for f in result.findings if f.check_id == "CHK-NONTEXT"]
    assert nontext and all(f.status == "needs_human_review" for f in nontext)
    assert not [r for r in result.repairs if r.finding_id in {f.finding_id for f in nontext}]
    suggestion = nontext[0]
    assert suggestion.suggestion_source == "llm"
    assert suggestion.suggested_text == answer
    assert any("suggestion only" in n for n in result.limitations)
    # The image itself is untouched: no alt text, no artifact, in the returned PDF.
    with pikepdf.open(io.BytesIO(base64.b64decode(result.output_pdf.content_base64))) as pdf:
        figures = [o for o in pdf.objects
                   if isinstance(o, pikepdf.Dictionary) and o.get("/S") == "/Figure"]
        assert figures and all("/Alt" not in f for f in figures)
