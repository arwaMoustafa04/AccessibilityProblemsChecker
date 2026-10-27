"""Independent expected findings, real PDFs, and /process integration."""

import base64
import io
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from fastapi.testclient import TestClient

from checks import color, link, sensory
from checks.base import CheckContext
from main import app
from test_fixtures.person2.generate import make_pdf

FIXTURES = Path(__file__).parent / "test_fixtures" / "person2"


def detect(fn, data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        ctx = CheckContext(data, "fixture.pdf", pdf)
        try:
            return fn(ctx)
        finally:
            ctx.close()


@pytest.fixture(autouse=True)
def local_checks(monkeypatch):
    monkeypatch.setenv("VERAPDF_ENABLED", "false")
    monkeypatch.setattr("pipeline.ENABLE_REPAIRS", False)


@pytest.mark.parametrize("name,fn,expected", [
    ("sensory_review.pdf", sensory.check, {"sensory_instruction_needs_review"}),
    ("sensory_named_control.pdf", sensory.check, set()),
    ("color_review.pdf", color.check, {"color_cue_needs_review", "multicolor_graphic_needs_review"}),
    ("color_text_alternative.pdf", color.check, set()),
    ("link_generic.pdf", link.check, {"link_purpose_unclear"}),
    ("link_descriptive.pdf", link.check, set()),
    ("link_empty.pdf", link.check, {"link_label_missing"}),
])
def test_committed_fixtures(name, fn, expected):
    found = detect(fn, (FIXTURES / name).read_bytes())
    assert {i.issue_type for i in found} == expected
    assert all(i.page == 1 and i.object_ref and i.suggestion for i in found)
    assert all(i.evaluation_result == "needs_review" for i in found)


@pytest.mark.parametrize("fn,text", [
    (sensory.check, "The square was built in 1900. The right answer is forty."),
    (color.check, "The sky is blue. Roses are red."),
])
def test_incidental_words_are_not_findings(fn, text):
    assert detect(fn, make_pdf(text)) == []


def test_wrapped_instruction_and_page_location():
    found = detect(sensory.check, make_pdf("Select the\nround button.", page_number=3))
    assert len(found) == 1 and found[0].page == 3


def test_no_silent_page_limit():
    found = detect(sensory.check, make_pdf("Press the round button.", page_number=301))
    assert len(found) == 1 and found[0].page == 301


def test_redundant_label_is_review_not_confirmed_failure():
    found = detect(sensory.check, make_pdf('Press the round button labelled "Submit".'))
    assert len(found) == 1 and found[0].evaluation_result == "needs_review"


@pytest.mark.parametrize("rotated", [False, True])
def test_generic_link_on_rotated_page(rotated):
    found = detect(link.check, make_pdf("Services", label="Click here", rotated=rotated))
    assert len(found) == 1 and found[0].issue_type == "link_purpose_unclear"


def test_explicit_link_alternative_is_used():
    assert detect(link.check, make_pdf("Services", label="", alt="Apply for a library card")) == []


def test_url_label_is_reviewed_not_fetched():
    found = detect(link.check, make_pdf("Services", label="https://example.org/services"))
    assert [i.issue_type for i in found] == ["link_url_needs_review"]


def test_non_link_annotations_are_ignored():
    data = make_pdf("Services", label="Click here")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.pages[0].obj.Annots[0].Subtype = pikepdf.Name.Text
        out = io.BytesIO()
        pdf.save(out)
    assert detect(link.check, out.getvalue()) == []


def test_malformed_rect_is_reviewed_without_crashing():
    data = make_pdf("Services", label="")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        del pdf.pages[0].obj.Annots[0].Rect
        out = io.BytesIO()
        pdf.save(out)
    found = detect(link.check, out.getvalue())
    assert found[0].issue_type == "link_location_unreadable"


def test_structure_link_alt_is_associated_with_annotation():
    data = make_pdf("Services", label="Click here")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        annot = pdf.pages[0].obj.Annots[0]
        elem = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link,
            Alt=pikepdf.String("Library membership application"),
            K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annot),
        ))
        pdf.Root.StructTreeRoot = pdf.make_indirect(pikepdf.Dictionary(K=elem))
        out = io.BytesIO()
        pdf.save(out)
    assert detect(link.check, out.getvalue()) == []


def test_process_integration_and_report():
    data = (FIXTURES / "combined_review.pdf").read_bytes()
    with TestClient(app) as client:
        response = client.post("/process", files={"file": ("combined.pdf", data, "application/pdf")})
    assert response.status_code == 200
    result = response.json()
    assert result["checks_performed"] == [
        "CHK-SENSORY", "CHK-COLOR", "CHK-TITLE", "CHK-LINK", "CHK-HEADINGS", "CHK-LANG"]
    mine = [f for f in result["findings"] if f["check_id"] in {"CHK-SENSORY", "CHK-COLOR", "CHK-LINK"}]
    assert {f["check_id"] for f in mine} == {"CHK-SENSORY", "CHK-COLOR", "CHK-LINK"}
    assert all(f["location"]["page"] == 2 for f in mine)
    assert all(f["classification"] == "human_review" and f["status"] == "needs_human_review"
               and f["evaluation_result"] == "needs_review" for f in mine)
    assert {f["wcag_criterion"] for f in mine} == {"1.3.3", "1.4.1", "2.4.4"}
    ids = {f["finding_id"] for f in result["findings"] if f["classification"] == "human_review"}
    assert set(result["human_review_items"]) == ids
    assert result["summary"]["human_review_count"] == len(ids)
    assert result["repairs"] == [] and not result["output_pdf"]["modified"]
    assert base64.b64decode(result["output_pdf"]["content_base64"]) == data
    assert any("No OCR" in line for line in result["limitations"])
    with pymupdf.open(stream=base64.b64decode(result["report_pdf"]["content_base64"]), filetype="pdf") as pdf:
        text = " ".join(page.get_text() for page in pdf)
    for check_id in ("CHK-SENSORY", "CHK-COLOR", "CHK-LINK"):
        assert check_id in text
    assert "Suggested fix" in text and "generic" in text


def test_one_failed_person2_check_does_not_hide_other_findings(monkeypatch):
    def broken(ctx):
        raise RuntimeError("test failure")
    monkeypatch.setitem(__import__("checks").CHECK_FUNCTIONS, "CHK-COLOR", broken)
    with TestClient(app) as client:
        body = client.post("/process", files={"file": ("a.pdf", make_pdf(
            "Select the round button.", label="Click here"), "application/pdf")}).json()
    assert "CHK-COLOR" not in body["checks_performed"]
    assert {"CHK-SENSORY", "CHK-LINK"} <= {f["check_id"] for f in body["findings"]}
    assert any("CHK-COLOR could not be completed" in line for line in body["limitations"])
