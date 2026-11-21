"""Text and text style of tagged content (marked-content sequences with an MCID).

Structure elements point at page content through MCIDs. This module reads each
page's content stream once and records, for every MCID, the text drawn inside it and
the font and size it was drawn with, so checks can compare an element's tag with how
it looks (e.g. a paragraph styled exactly like a heading).

Text is decoded simply (latin-1), which is right for standard fonts; for other
encodings it may be garbled, so checks use it for matching and display only, never
as proof of a failure on its own. Form XObjects are not followed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pikepdf

from checks.base import CheckContext
from checks.structure_tree import StructElem

MAX_OPERATORS = 200_000  # per page; bounds the work on very large pages


@dataclass
class MarkedText:
    text: str = ""
    size: float = 0.0  # font size in points (Tf size x text-matrix scale), first text run
    font: str = ""  # BaseFont of the first text run, e.g. "Helvetica-Bold"

    @property
    def style(self) -> tuple[float, str]:
        return round(self.size, 1), self.font


def _decode(obj: object) -> str:
    if isinstance(obj, pikepdf.String):
        return bytes(obj).decode("latin-1", "replace")
    if isinstance(obj, pikepdf.Array):  # TJ: strings and kerning numbers
        return "".join(_decode(x) for x in obj if isinstance(x, pikepdf.String))
    return ""


def _mcid(operands: list, resources: object) -> int | None:
    props = operands[1] if len(operands) > 1 else None
    if isinstance(props, pikepdf.Name) and isinstance(resources, pikepdf.Dictionary):
        named = resources.get("/Properties")
        props = named.get(props) if isinstance(named, pikepdf.Dictionary) else None
    if isinstance(props, pikepdf.Dictionary) and isinstance(props.get("/MCID"), int):
        return int(props.MCID)
    return None


def _base_font(resources: object, name: object) -> str:
    try:
        font = resources.Font[name]  # type: ignore[attr-defined]
        return str(font.get("/BaseFont", name)).lstrip("/")
    except Exception:
        return str(name).lstrip("/")


def _page_marked_text(page: pikepdf.Page) -> dict[int, MarkedText]:
    found: dict[int, MarkedText] = {}
    resources = page.obj.get("/Resources")
    stack: list[int | None] = []
    font, size, scale = "", 0.0, 1.0
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:
        return found
    for count, instruction in enumerate(instructions):
        operands, operator = instruction.operands, instruction.operator
        if count >= MAX_OPERATORS:
            break
        op = str(operator)
        if op == "BDC":
            stack.append(_mcid(list(operands), resources))
        elif op == "BMC":
            stack.append(None)
        elif op == "EMC":
            if stack:
                stack.pop()
        elif op == "BT":
            scale = 1.0
        elif op == "Tf" and len(operands) >= 2:
            font = _base_font(resources, operands[0])
            try:
                size = float(operands[1])
            except (TypeError, ValueError):
                size = 0.0
        elif op == "Tm" and len(operands) >= 4:
            try:
                scale = abs(float(operands[3])) or 1.0
            except (TypeError, ValueError):
                scale = 1.0
        elif op in ("Tj", "TJ", "'", '"') and operands:
            mcid = next((m for m in reversed(stack) if m is not None), None)
            if mcid is None:
                continue
            entry = found.setdefault(mcid, MarkedText())
            if not entry.text.strip():
                entry.size, entry.font = size * scale, font
            entry.text += _decode(operands[-1])
    return found


def marked_text(ctx: CheckContext) -> dict[tuple[int, int], MarkedText]:
    """(page number, MCID) -> text and style, for the whole document (cached on ctx)."""
    cached = ctx.__dict__.get("_marked_text")
    if cached is None:
        cached = {}
        for number, page in enumerate(ctx.pdf.pages, start=1):
            for mcid, entry in _page_marked_text(page).items():
                cached[(number, mcid)] = entry
        ctx.__dict__["_marked_text"] = cached
    return cached


def element_text(ctx: CheckContext, elem: StructElem) -> MarkedText | None:
    """Text and style of the content directly inside a structure element."""
    texts = marked_text(ctx)
    kids = elem.obj.get("/K")
    items = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
    parts: list[MarkedText] = []
    for kid in items:
        page, mcid = elem.page, None
        if isinstance(kid, int):
            mcid = int(kid)
        elif isinstance(kid, pikepdf.Dictionary) and kid.get("/Type") == pikepdf.Name.MCR:
            mcid = int(kid.MCID) if isinstance(kid.get("/MCID"), int) else None
            page = ctx.page_of(kid.get("/Pg")) or page
        if mcid is not None and page is not None and (page, mcid) in texts:
            parts.append(texts[(page, mcid)])
    if not parts:
        return None
    first = next((p for p in parts if p.text.strip()), parts[0])
    text = " ".join(" ".join(p.text.split()) for p in parts).strip()
    return MarkedText(text, first.size, first.font)
