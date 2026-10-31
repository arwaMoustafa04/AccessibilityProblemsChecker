"""Where on its page a finding is (Location.bbox), so the UI can highlight it.

Best effort, and it never raises: a box is [x0, y0, x1, y1] in PDF user space
(points, origin at the bottom left of the page, before /Rotate), or None when only
the page is known. It reuses what the checks already record:

- ``N G R`` object refs that have a /Rect (link annotations, form fields)
- ``Page[n]/Contents/op[i]`` image draws from pdf_checks.py, nested forms included
- ``Catalog/StructTreeRoot/K[..]`` Figures: the images drawn in their marked content
- ``Page[n]/TextBlock[i]`` text blocks and ``Page[n]/Drawings`` (review_text.py, color.py)
- otherwise, the first quoted phrase in the description, searched on the page
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pikepdf
import pymupdf

from checks.base import CheckContext, Issue

log = logging.getLogger("pdf_accessibility.locate")

_OBJECT_REF = re.compile(r"^(\d+) (\d+) R$")
_PAGE_REF = re.compile(r"^Page\[(\d+)\]/")
_TEXT_BLOCK = re.compile(r"^Page\[\d+\]/TextBlock\[(\d+)\]$")
_STRUCT_PATH = re.compile(r"^Catalog/StructTreeRoot((?:/K\[\d+\])+)$")
_QUOTE = re.compile(r'"([^"]{3,})"')
_UNIT = pymupdf.Rect(0, 0, 1, 1)  # images are drawn into the unit square
MAX_FORM_DEPTH = 64


class _Draws:
    """Image placements on one page: by content-stream ref and by marked-content ID."""

    def __init__(self) -> None:
        self.by_ref: dict[str, pymupdf.Rect] = {}
        self.by_mcid: dict[int, list[pymupdf.Rect]] = {}

    def add(self, ref: str, rect: pymupdf.Rect, mcids: list[int | None]) -> None:
        self.by_ref[ref] = rect
        for mcid in mcids:
            if mcid is not None:
                self.by_mcid.setdefault(mcid, []).append(rect)


class Locator:
    def __init__(self, ctx: CheckContext):
        self.ctx = ctx
        self._draws: dict[int, _Draws] = {}

    def bbox(self, issue: Issue) -> list[float] | None:
        if issue.bbox is not None:
            return issue.bbox
        if issue.page is None or not 1 <= issue.page <= len(self.ctx.pdf.pages):
            return None
        try:
            rect = self._from_ref(issue) or self._from_quote(issue)
        except Exception:  # a display aid only: never fail the request over it
            log.debug("could not locate %s %s", issue.check_id, issue.object_ref, exc_info=True)
            return None
        if rect is None or rect.is_empty or rect.is_infinite:
            return None
        return [round(v, 1) for v in (rect.x0, rect.y0, rect.x1, rect.y1)]

    # --- by object reference ------------------------------------------------

    def _from_ref(self, issue: Issue) -> pymupdf.Rect | None:
        ref = issue.object_ref or ""
        page = issue.page or 0
        if m := _OBJECT_REF.match(ref):
            obj = self.ctx.pdf.get_object((int(m[1]), int(m[2])))
            rect = obj.get("/Rect") if isinstance(obj, pikepdf.Dictionary) else None
            return pymupdf.Rect([float(v) for v in rect]).normalize() if rect is not None else None
        if m := _PAGE_REF.match(ref):
            if int(m[1]) != page:
                return None
            if ref.startswith(f"Page[{page}]/Contents/op["):
                return self._page_draws(page).by_ref.get(ref)
            if m := _TEXT_BLOCK.match(ref):
                mu_page = self.ctx.doc[page - 1]
                block = mu_page.get_text("blocks")[int(m[1])]
                return self._to_pdf(page, pymupdf.Rect(block[:4]))
            if ref == f"Page[{page}]/Drawings":
                return self._colored_drawings(page)
            return None
        if m := _STRUCT_PATH.match(ref):
            mcids = _mcids(_struct_node(self.ctx.pdf, m[1]))
            by_mcid = self._page_draws(page).by_mcid
            return _union([r for mcid in mcids for r in by_mcid.get(mcid, [])])
        return None

    def _page_draws(self, page: int) -> _Draws:
        if page not in self._draws:
            draws = _Draws()
            pdf_page = self.ctx.pdf.pages[page - 1]
            _walk(pdf_page, pdf_page.resources, pymupdf.Matrix(1, 1), f"Page[{page}]/Contents",
                  [], draws, top_level=True, depth=0)
            self._draws[page] = draws
        return self._draws[page]

    def _colored_drawings(self, page: int) -> pymupdf.Rect | None:
        from checks.color import _chromatic

        mu_page = self.ctx.doc[page - 1]
        rects = [d["rect"] for d in mu_page.get_drawings()
                 if _chromatic(d.get("fill")) or _chromatic(d.get("color"))]
        union = _union(rects)
        return self._to_pdf(page, union) if union else None

    # --- by quoted text -----------------------------------------------------

    def _from_quote(self, issue: Issue) -> pymupdf.Rect | None:
        m = _QUOTE.search(issue.description)
        if not m:
            return None
        phrase = m[1].removesuffix("...")[:80]  # excerpt() shortens long text with "..."
        page = issue.page or 1
        hits = self.ctx.doc[page - 1].search_for(phrase)
        return self._to_pdf(page, hits[0]) if hits else None  # the first line it is on

    def _to_pdf(self, page: int, rect: pymupdf.Rect) -> pymupdf.Rect:
        """PyMuPDF page coordinates (top left of the CropBox, y down, unrotated) -> PDF
        user space. Done by hand: transformation_matrix drops the box offset on rotated pages."""
        x0, _, _, y1 = (float(v) for v in self.ctx.pdf.pages[page - 1].cropbox)
        return pymupdf.Rect(rect.x0 + x0, y1 - rect.y1, rect.x1 + x0, y1 - rect.y0)


def _walk(source: Any, resources: Any, ctm: pymupdf.Matrix, path: str,
          outer_mcids: list[int | None], draws: _Draws, top_level: bool, depth: int) -> None:
    """Follow q/Q/cm through a content stream (and the forms it draws), recording
    where each image lands. Refs are numbered like pdf_checks.Inspector.scan."""
    if depth > MAX_FORM_DEPTH:
        return
    saved: list[pymupdf.Matrix] = []
    marks: list[int | None] = []  # marked-content IDs open in this stream
    for index, instruction in enumerate(pikepdf.parse_content_stream(source)):
        ref = f"{path}/op[{index}]"
        mcids = outer_mcids + (marks if top_level else [])
        if isinstance(instruction, pikepdf.ContentStreamInlineImage):
            draws.add(ref, _UNIT * ctm, mcids)
            continue
        op, operands = str(instruction.operator), instruction.operands
        if op == "q":
            saved.append(ctm)
        elif op == "Q" and saved:
            ctm = saved.pop()
        elif op == "cm" and len(operands) == 6:
            ctm = pymupdf.Matrix(*(float(v) for v in operands)) * ctm
        elif op in ("BDC", "BMC"):
            mcid = None
            if op == "BDC" and len(operands) == 2:
                props = operands[1]
                if isinstance(props, pikepdf.Name):
                    props = resources.get("/Properties", {}).get(str(props))
                if isinstance(props, pikepdf.Dictionary):
                    value = props.get("/MCID")
                    mcid = int(value) if isinstance(value, int) else None
            marks.append(mcid)
        elif op == "EMC" and marks:
            marks.pop()
        elif op == "Do" and operands:
            obj = resources.get("/XObject", {}).get(str(operands[0]))
            if not isinstance(obj, pikepdf.Stream):
                continue
            subtype = str(obj.get("/Subtype", ""))
            if subtype == "/Image":
                draws.add(ref, _UNIT * ctm, mcids)
            elif subtype == "/Form":
                matrix = obj.get("/Matrix")
                form_ctm = (pymupdf.Matrix(*(float(v) for v in matrix)) if matrix is not None
                            else pymupdf.Matrix(1, 1)) * ctm
                _walk(obj, obj.get("/Resources", resources), form_ctm, ref, mcids, draws,
                      top_level=False, depth=depth + 1)


def _struct_node(pdf: pikepdf.Pdf, path: str) -> Any:
    node: Any = pdf.Root.StructTreeRoot
    for index in re.findall(r"\[(\d+)\]", path):
        kids = node.get("/K")
        kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
        node = kids[int(index)]
    return node


def _mcids(node: Any, depth: int = 0) -> set[int]:
    """Marked-content IDs of a structure element and its descendants."""
    found: set[int] = set()
    if depth > 128 or not isinstance(node, pikepdf.Dictionary):
        return found
    kids = node.get("/K")
    for kid in list(kids) if isinstance(kids, pikepdf.Array) else [kids]:
        if isinstance(kid, int):
            found.add(int(kid))
        elif isinstance(kid, pikepdf.Dictionary):
            if isinstance(kid.get("/MCID"), int):
                found.add(int(kid.MCID))
            elif "/S" in kid:
                found |= _mcids(kid, depth + 1)
    return found


def _union(rects: list[pymupdf.Rect]) -> pymupdf.Rect | None:
    if not rects:
        return None
    out = pymupdf.Rect(rects[0])
    for rect in rects[1:]:
        out |= rect
    return out
