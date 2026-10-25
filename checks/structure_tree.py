"""Walk the tagged-PDF structure tree with pikepdf (shared by several checks)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pikepdf

from checks.base import CheckContext

STANDARD_HEADINGS = {"/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6"}


@dataclass
class StructElem:
    tag: str  # standard tag after RoleMap, e.g. "/H1"
    raw_tag: str  # tag as written in the file, e.g. "/Heading1"
    obj: pikepdf.Dictionary
    page: int | None  # 1-based, from the element's /Pg (or the nearest parent's)
    depth: int

    @property
    def ref(self) -> str:
        try:
            num, gen = self.obj.objgen
            return f"{num} {gen} R" if num else "StructTreeRoot"
        except Exception:
            return "StructTreeRoot"

    def has_content(self) -> bool:
        """True if the element has kids, /ActualText or /Alt."""
        for key in ("/ActualText", "/Alt"):
            if str(self.obj.get(key, "")).strip():
                return True
        kids = self.obj.get("/K")
        if kids is None:
            return False
        if isinstance(kids, pikepdf.Array):
            return len(kids) > 0
        return True


def is_tagged(ctx: CheckContext) -> bool:
    root = ctx.pdf.Root
    mark_info = root.get("/MarkInfo")
    marked = bool(mark_info.get("/Marked", False)) if mark_info is not None else False
    return "/StructTreeRoot" in root and marked


def _resolve_role(tag: str, role_map: object) -> str:
    if not isinstance(role_map, pikepdf.Dictionary):
        return tag  # no RoleMap (or a malformed one): the tag is used as written
    seen = set()
    while tag in role_map and tag not in seen:
        seen.add(tag)
        mapped = role_map[tag]
        if not isinstance(mapped, pikepdf.Name):
            break
        tag = str(mapped)
    return tag


def iter_elements(ctx: CheckContext, max_elements: int = 50_000) -> Iterator[StructElem]:
    """Yield structure elements in document (reading) order."""
    tree = ctx.pdf.Root.get("/StructTreeRoot")
    if tree is None:
        return
    role_map = tree.get("/RoleMap")
    seen: set[tuple[int, int]] = set()
    count = 0

    def walk(node: object, page: int | None, depth: int) -> Iterator[StructElem]:
        nonlocal count
        if count >= max_elements or depth > 200:
            return
        if isinstance(node, pikepdf.Array):
            for kid in node:
                yield from walk(kid, page, depth)
            return
        if not isinstance(node, pikepdf.Dictionary):
            return  # an MCID integer: marked content, not an element
        objgen = node.objgen
        if objgen != (0, 0):
            if objgen in seen:
                return
            seen.add(objgen)
        if node.get("/Type") in (pikepdf.Name.MCR, pikepdf.Name.OBJR):
            return
        tag = node.get("/S")
        pg = ctx.page_of(node.get("/Pg")) or page
        if isinstance(tag, pikepdf.Name):
            count += 1
            raw = str(tag)
            yield StructElem(_resolve_role(raw, role_map), raw, node, pg, depth)
        kids = node.get("/K")
        if kids is not None:
            yield from walk(kids, pg, depth + 1)

    yield from walk(tree.get("/K"), None, 0)
