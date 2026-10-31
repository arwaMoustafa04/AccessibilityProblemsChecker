"""checks/locate.py: where on the page each finding is (Location.bbox)."""
import io
from pathlib import Path

import pikepdf
import pytest
from fastapi.testclient import TestClient

from checks.base import CheckContext, Issue
from checks.locate import Locator
from main import app
from tester.fixtures.pdf_checks.generate import make_fixture

IMAGE_BOX = [320.0, 150.0, 375.0, 205.0]  # "q 55 0 0 55 320 150 cm /Im Do Q" in generate.py
PERSON2 = Path(__file__).parent / "test_fixtures/person2"


def located(data: bytes, issue: Issue):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        ctx = CheckContext(data, "t.pdf", pdf)
        try:
            return Locator(ctx).bbox(issue)
        finally:
            ctx.close()


def text_pdf(rotate: int = 0, mediabox=(0, 0, 612, 792), cropbox=None) -> tuple[bytes, float, float]:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0]
    page.MediaBox = list(mediabox)
    page.Rotate = rotate
    if cropbox:
        page.CropBox = list(cropbox)
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
    x, y = mediabox[0] + 200, mediabox[1] + 300
    page.Contents = pdf.make_stream(f"BT /F 20 Tf {x} {y} Td (Hello target) Tj ET".encode())
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue(), x, y


@pytest.mark.parametrize("case,ref", [
    ("untagged_image", "Page[1]/Contents/op[0]"),
    ("inline_image", "Page[1]/Contents/op[0]"),
])
def test_image_draw_is_located(case, ref):
    data = make_fixture(case)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        from pdf_checks import detect_pdf_issues
        refs = [i.object_ref for i in detect_pdf_issues(pdf)]
    issue = Issue("CHK-NONTEXT", "image_without_text_alternative", "Image", page=1, object_ref=refs[0])
    assert located(data, issue) == IMAGE_BOX


@pytest.mark.parametrize("case", ["missing_alt", "blank_alt", "combined"])
def test_figure_is_located_through_its_marked_content(case):
    issue = Issue("CHK-NONTEXT", "missing_figure_alt", "Figure", page=1,
                  object_ref="Catalog/StructTreeRoot/K[0]/K[0]")
    assert located(make_fixture(case), issue) == IMAGE_BOX


def test_link_annotation_uses_its_rect():
    data = (PERSON2 / "link_generic.pdf").read_bytes()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        annot = pdf.pages[0].Annots[0]
        num, gen = annot.objgen
        expected = sorted(float(v) for v in annot.Rect[::2]), sorted(float(v) for v in annot.Rect[1::2])
    box = located(data, Issue("CHK-LINK", "link_purpose_unclear", "Link", page=1,
                              object_ref=f"{num} {gen} R"))
    assert box == [expected[0][0], expected[1][0], expected[0][1], expected[1][1]]


@pytest.mark.parametrize("rotate,mediabox,cropbox", [
    (0, (0, 0, 612, 792), None),
    (90, (0, 0, 612, 792), None),
    (270, (100, 50, 712, 842), None),
    (90, (100, 50, 712, 842), (150, 80, 600, 800)),
])
def test_quoted_text_is_found_in_pdf_coordinates(rotate, mediabox, cropbox):
    data, x, y = text_pdf(rotate, mediabox, cropbox)
    box = located(data, Issue("CHK-HEADINGS", "headings_not_tagged",
                              'e.g. "Hello target" (page 1).', page=1))
    assert box is not None
    assert abs(box[0] - x) < 1 and box[1] < y < box[3]


def test_unknown_or_broken_refs_give_no_box():
    data = make_fixture("untagged_image")
    assert located(data, Issue("CHK-STRUCTURE", "x", "No quote here", page=1,
                               object_ref="Catalog/StructTreeRoot")) is None
    assert located(data, Issue("CHK-NONTEXT", "x", "x", page=1,
                               object_ref="Page[1]/Contents/op[99]")) is None
    assert located(data, Issue("CHK-STRUCTURE", "x", "x", page=1,
                               object_ref="Catalog/StructTreeRoot/K[7]/K[3]")) is None
    assert located(data, Issue("CHK-TITLE", "x", "x", page=None, object_ref="Info/Title")) is None
    assert located(data, Issue("CHK-LINK", "x", "x", page=5, object_ref="5 0 R")) is None


def test_check_supplied_box_is_kept():
    issue = Issue("CHK-LINK", "x", "x", page=1, bbox=[1.0, 2.0, 3.0, 4.0])
    assert located(make_fixture("untagged_image"), issue) == [1.0, 2.0, 3.0, 4.0]


def test_process_returns_bbox_and_report_name():
    data = make_fixture("combined")
    body = TestClient(app).post(
        "/process", files={"file": ("Budget 2026.pdf", data, "application/pdf")}).json()
    figure = next(f for f in body["findings"] if f["issue_type"] == "missing_figure_alt")
    assert figure["location"]["bbox"] == IMAGE_BOX
    for f in body["findings"]:
        if f["location"]["page"] is None:
            assert f["location"]["bbox"] is None
    assert body["report_pdf"]["file_name"] == "Budget 2026_AccessibilityReport.pdf"
