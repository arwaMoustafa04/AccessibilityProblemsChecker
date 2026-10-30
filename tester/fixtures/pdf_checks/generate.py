"""Reproducible small PDFs for image/structure detection (not compliance examples).

Run from the repository root: python tester/fixtures/pdf_checks/generate.py
The builder is also used in tests to construct edge cases without stored binaries.
"""
from __future__ import annotations

import io
from pathlib import Path

import pikepdf
from reportlab.pdfgen import canvas

N = pikepdf.Name
D = pikepdf.Dictionary
A = pikepdf.Array

CASES = (
    "tagged_image", "missing_alt", "blank_alt", "untagged_image", "artifact_image",
    "nested_form", "inline_image", "missing_structure", "empty_structure",
    "table_headers", "table_no_headers", "combined",
)


def make_fixture(case: str) -> bytes:
    base = io.BytesIO()
    c = canvas.Canvas(base, pagesize=(450, 320), invariant=1)
    c.setTitle(f"PDF check fixture: {case}")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(28, 280, case.replace("_", " ").title())
    c.setFont("Helvetica", 11)
    c.drawString(28, 255, "Focused detector fixture - not an accessibility certification.")
    if case in ("table_headers", "table_no_headers", "combined"):
        c.drawString(28, 210, "Item")
        c.drawString(150, 210, "Count")
        c.drawString(28, 182, "Apples")
        c.drawString(150, 182, "3")
        for y in (225, 198, 170):
            c.line(25, y, 235, y)
    c.setFont("Helvetica", 9)
    c.drawString(28, 25, "Expected findings are documented in the fixture README.")
    c.showPage()
    c.save()
    with pikepdf.open(io.BytesIO(base.getvalue())) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(D(Type=N.StructTreeRoot, K=A()))
        doc = pdf.make_indirect(D(Type=N.StructElem, S=N.Document, P=root, Pg=page.obj, K=A()))
        root.K.append(doc)
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = D(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.Root.ViewerPreferences = D(DisplayDocTitle=True)
        page.obj.StructParents = 0
        parents = A()
        # Blank document structure still has a valid document-level element.
        image_cases = {"tagged_image", "missing_alt", "blank_alt", "untagged_image",
                       "artifact_image", "nested_form", "inline_image", "combined"}
        if case in image_cases:
            image = pdf.make_stream(bytes([40, 120, 220] * 4))
            image.Type = N.XObject
            image.Subtype = N.Image
            image.Width = 2
            image.Height = 2
            image.ColorSpace = N.DeviceRGB
            image.BitsPerComponent = 8
            page.resources.XObject = D(Im=image)
            figure = pdf.make_indirect(D(Type=N.StructElem, S=N.Figure, P=doc, K=0))
            if case not in ("missing_alt", "combined"):
                figure.Alt = "   " if case == "blank_alt" else "A blue square"
            drawing = b"q 55 0 0 55 320 150 cm /Im Do Q"
            if case == "nested_form":
                form = pdf.make_stream(b"/Figure <</MCID 0>> BDC " + drawing + b" EMC")
                form.Type = N.XObject
                form.Subtype = N.Form
                form.BBox = A([0, 0, 450, 320])
                form.Resources = D(XObject=D(Im=image))
                form.StructParents = 1
                figure.K = D(Type=N.MCR, MCID=0, Stm=form)
                page.resources.XObject = D(Fm=form)
                drawing = b"/Fm Do"
            elif case == "artifact_image":
                drawing = b"/Artifact BMC " + drawing + b" EMC"
            elif case == "inline_image":
                drawing = b"q 55 0 0 55 320 150 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x28\x78\xdc EI Q"
            elif case != "untagged_image":
                drawing = b"/Figure <</MCID 0>> BDC " + drawing + b" EMC"
            if case not in ("artifact_image", "untagged_image", "inline_image"):
                doc.K.append(figure)
                parents.append(figure)
            page.contents_add(pdf.make_stream(drawing))
        if case in ("table_headers", "table_no_headers", "combined"):
            table = pdf.make_indirect(D(Type=N.StructElem, S=N.Table, P=doc, K=A()))
            doc.K.append(table)
            for row_number in range(2):
                row = pdf.make_indirect(D(Type=N.StructElem, S=N.TR, P=table, K=A()))
                table.K.append(row)
                for _ in range(2):
                    role = N.TH if case == "table_headers" and row_number == 0 else N.TD
                    cell = pdf.make_indirect(D(Type=N.StructElem, S=role, P=row))
                    if role == N.TH:
                        cell.A = D(O=N.Table, Scope=N.Column)
                    row.K.append(cell)
        root.ParentTree = pdf.make_indirect(D(Nums=A([0, parents])))
        if case == "nested_form":
            root.ParentTree.Nums.extend([1, A([figure])])
        if case == "missing_structure":
            del pdf.Root.StructTreeRoot
            del pdf.Root.MarkInfo
        elif case == "empty_structure":
            root.K = A()
        result = io.BytesIO()
        pdf.save(result, deterministic_id=True)
        return result.getvalue()


if __name__ == "__main__":
    for name in CASES:
        Path(__file__).with_name(f"{name}.pdf").write_bytes(make_fixture(name))
