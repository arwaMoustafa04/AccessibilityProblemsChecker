"""Team 3's pod test PDFs (tester/fixtures/pod) and the detections added for them:
a paragraph styled like a heading, a vague heading, more color names, no "above/below"
sensory cue, and no XMP-only title finding."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest

from checks import CheckContext
from checks import color as color_check
from checks import headings as headings_check
from checks import sensory as sensory_check
from checks import structure as structure_check
from checks.marked_content import element_text
from checks.structure_tree import iter_elements

POD = Path(__file__).parent / "tester" / "fixtures" / "pod"


def _findings(fn, data: bytes) -> list:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return fn(CheckContext(data, "doc.pdf", pdf))


def tagged_pdf(items: list[tuple[str, str, str, int]]) -> bytes:
    """One page; each item is (tag, text, font resource F1/F2, size), one MCID each."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0]
    fonts = {name: pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name(base)))
        for name, base in (("F1", "/Helvetica"), ("F2", "/Helvetica-Bold"))}
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(**fonts))
    stream, y = b"", 740
    for mcid, (tag, text, font, size) in enumerate(items):
        stream += (f"{tag} <</MCID {mcid}>> BDC BT /{font} {size} Tf 72 {y} Td ({text}) Tj "
                   "ET EMC\n").encode("latin-1")
        y -= 30
    page.Contents = pdf.make_stream(stream)
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    doc = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
    kids = [pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructElem, S=pikepdf.Name(tag), P=doc, Pg=page.obj,
        K=pikepdf.Array([mcid]))) for mcid, (tag, *_rest) in enumerate(items)]
    doc.K = pikepdf.Array(kids)
    root.K = pikepdf.Array([doc])
    root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(
        [0, pikepdf.Array(kids)])))
    page.StructParents = 0
    pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


BODY = ("/P", "The branch is open to all card holders and visitors", "F1", 12)


# --- The pod PDFs: each gives its intended finding -----------------------------------

@pytest.mark.parametrize("name, fn, issue_type", [
    ("wcag-1.3.1-heading-tagged-as-paragraph.pdf", structure_check.check,
     "heading_tagged_as_paragraph"),
    ("wcag-2.4.6-vague-heading.pdf", headings_check.check, "heading_not_descriptive"),
    ("wcag-1.4.1-color-only-status.pdf", color_check.check, "color_cue_needs_review"),
])
def test_pod_pdf_intended_issue(name, fn, issue_type) -> None:
    found = _findings(fn, (POD / name).read_bytes())
    assert issue_type in {i.issue_type for i in found}
    assert all(i.evaluation_result == "needs_review" for i in found
               if i.issue_type == issue_type)


def test_pod_heading_as_paragraph_names_the_text_and_tag() -> None:
    data = (POD / "wcag-1.3.1-heading-tagged-as-paragraph.pdf").read_bytes()
    issue, = [i for i in _findings(structure_check.check, data)
              if i.issue_type == "heading_tagged_as_paragraph"]
    assert '"Weekend hours"' in issue.description and issue.suggested_text == "H2"
    assert issue.page == 1 and issue.object_ref


def test_above_is_not_a_sensory_cue() -> None:
    data = (POD / "wcag-1.3.1-heading-tagged-as-paragraph.pdf").read_bytes()
    assert _findings(sensory_check.check, data) == []  # "the hours shown above"


def test_element_text_reads_marked_content() -> None:
    data = tagged_pdf([("/H1", "Fees", "F2", 20), BODY])
    with pikepdf.open(io.BytesIO(data)) as pdf:
        ctx = CheckContext(data, "doc.pdf", pdf)
        texts = [element_text(ctx, e) for e in iter_elements(ctx)]
    found = [(t.text, t.size, t.font) for t in texts if t]
    assert found == [("Fees", 20, "Helvetica-Bold"), (BODY[1], 12, "Helvetica")]


# --- heading_tagged_as_paragraph: not flagged ----------------------------------------

@pytest.mark.parametrize("paragraph", [
    ("/P", "Weekend hours", "F2", 16),  # different size from the heading
    ("/P", "Weekend hours", "F1", 20),  # different font
    ("/P", "Saturday and Sunday the doors open at ten.", "F2", 20),  # a sentence
    ("/P", "one two three four five six seven eight nine ten eleven twelve thirteen",
     "F2", 20),  # too long for a heading
])
def test_paragraph_not_styled_like_a_heading(paragraph) -> None:
    data = tagged_pdf([("/H2", "Weekday hours", "F2", 20), BODY, paragraph, BODY])
    assert "heading_tagged_as_paragraph" not in {
        i.issue_type for i in _findings(structure_check.check, data)}


def test_body_style_is_never_a_heading() -> None:
    # Headings drawn in the body style (common in plain documents) do not make every
    # short paragraph a "heading".
    data = tagged_pdf([("/H1", "Hours", "F1", 12), BODY, ("/P", "Ask at the desk", "F1", 12),
                       BODY])
    assert "heading_tagged_as_paragraph" not in {
        i.issue_type for i in _findings(structure_check.check, data)}


# --- heading_not_descriptive ---------------------------------------------------------

@pytest.mark.parametrize("heading", ["Miscellaneous", "Other", "More information",
                                     "Section 3", "Untitled", "TBD:"])
def test_vague_heading_flagged(heading) -> None:
    data = tagged_pdf([("/H2", heading, "F2", 18), BODY])
    found = [i for i in _findings(headings_check.check, data)
             if i.issue_type == "heading_not_descriptive"]
    assert len(found) == 1 and found[0].evaluation_result == "needs_review"
    assert BODY[1] in found[0].suggestion  # hint from the section's first paragraph


@pytest.mark.parametrize("heading", ["Other services", "Section 3: Fees", "More ways to pay",
                                     "General admission", "Lost badges"])
def test_descriptive_heading_not_flagged(heading) -> None:
    data = tagged_pdf([("/H2", heading, "F2", 18), BODY])
    assert "heading_not_descriptive" not in {
        i.issue_type for i in _findings(headings_check.check, data)}
