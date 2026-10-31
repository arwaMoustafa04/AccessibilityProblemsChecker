"""Reproducible Person 2 PDFs. Run: python -m test_fixtures.person2.generate."""

import io
from pathlib import Path
from typing import NotRequired, TypedDict

import pikepdf
from reportlab.lib.colors import black, green, red
from reportlab.pdfgen import canvas


def make_pdf(text: str, *, label: str | None = None, graphic: bool = False,
             page_number: int = 1, alt: str | None = None, rotated: bool = False) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792), invariant=True)
    c.setTitle("Person 2 test document")
    for _ in range(page_number - 1):
        c.showPage()
    c.setFont("Helvetica", 12)
    for n, line in enumerate(text.splitlines()):
        c.drawString(60, 730 - n * 17, line)
    if graphic:
        for x, color in [(60, red), (120, green)]:
            c.setFillColor(color)
            c.rect(x, 570, 40, 70, fill=1, stroke=0)
        c.setFillColor(black)
    if label is not None:
        c.drawString(60, 500, label)
        width = max(c.stringWidth(label, "Helvetica", 12), 60)
        c.linkURL("https://example.org/services", (60, 497, 60 + width, 514), relative=0)
    c.save()
    with pikepdf.open(io.BytesIO(buf.getvalue())) as pdf:
        pdf.Root.Lang = pikepdf.String("en-US")
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["dc:title"] = "Person 2 test document"
        if alt is not None:
            pdf.pages[-1].obj.Annots[0].Contents = pikepdf.String(alt)
        if rotated:
            pdf.pages[-1].obj.Rotate = 90
        out = io.BytesIO()
        pdf.save(out, deterministic_id=True)
    return out.getvalue()


class FixtureOptions(TypedDict):
    text: str
    label: NotRequired[str]
    graphic: NotRequired[bool]
    page_number: NotRequired[int]


CASES: dict[str, FixtureOptions] = {
    "sensory_review.pdf": dict(text="Press the round button on the right to continue."),
    "sensory_named_control.pdf": dict(text='Press the button labelled "Submit application".'),
    "color_review.pdf": dict(text="Required fields are marked in red.", graphic=True),
    "color_text_alternative.pdf": dict(text="Required fields are marked with an asterisk (*)."),
    "link_generic.pdf": dict(text="Service information", label="Click here"),
    "link_descriptive.pdf": dict(text="Service information", label="Apply for a library card"),
    "link_empty.pdf": dict(text="Service information", label=""),
    "combined_review.pdf": dict(text="Select the round button on the right.\nErrors are shown in red.",
                                label="Click here", graphic=True, page_number=2),
}


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, options in CASES.items():
        (destination / name).write_bytes(make_pdf(**options))


if __name__ == "__main__":
    generate(Path(__file__).parent)
