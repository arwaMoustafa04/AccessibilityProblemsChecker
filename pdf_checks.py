"""Conservative PDF tag/image checks; findings require human review, never repair.

Uses WCAG PDF1, PDF4 and PDF6 techniques. Presence of tags is not a claim
that their meaning, reading order, or coverage is correct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pikepdf


@dataclass
class Issue:
    check_id: str
    issue_type: str
    object_ref: str
    description: str
    page: int | None = None
    evaluation_result: Literal["fail", "needs_review"] = "fail"

    @property
    def key(self) -> tuple:
        # Tree/content paths remain stable when pikepdf renumbers saved objects.
        return self.check_id, self.issue_type, self.page, self.object_ref


def _dict(obj: Any) -> bool:
    return isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream))


def _identity(obj: Any) -> tuple[int, int]:
    return obj.objgen if isinstance(obj, pikepdf.Object) else (0, 0)


def _children(obj: Any) -> list:
    if obj is None:
        return []
    return list(obj) if isinstance(obj, pikepdf.Array) else [obj]


class Inspector:
    def __init__(self, pdf: pikepdf.Pdf):
        self.pdf = pdf
        self.issues: list[Issue] = []
        self.pages = {_identity(page.obj): n for n, page in enumerate(pdf.pages, 1)}
        self.roles: Any = pikepdf.Dictionary()
        self.content: dict[tuple, str] = {}
        self.objects: dict[tuple, str] = {}
        self.figures: dict[str, Any] = {}
        self.seen: set[tuple] = set()
        self.nodes = 0
        self.issue_keys: set[tuple] = set()

    def add(self, check: str, kind: str, ref: str, description: str,
            page: int | None = None, result: Literal["fail", "needs_review"] = "needs_review"):
        issue = Issue(check, kind, ref, description, page, result)
        if issue.key not in self.issue_keys:
            self.issue_keys.add(issue.key)
            self.issues.append(issue)

    def malformed(self, ref: str, page: int | None = None):
        self.add("CHK-STRUCTURE", "malformed_structure", ref,
                 "Structure relationships could not be fully inspected; review document tags", page)

    def role(self, node: Any) -> str:
        value = node.get("/S", "")
        if not isinstance(value, pikepdf.Name):
            raise ValueError("Structure element has no valid role")
        role = str(value)
        visited = set()
        while role in self.roles:
            if role in visited:
                raise ValueError("Cyclic role map")
            visited.add(role)
            target = self.roles[role]
            if not isinstance(target, pikepdf.Name):
                raise ValueError("Invalid role map target")
            role = str(target)
        return role

    def walk(self, node: Any, path: str, page: int | None, figure: str | None,
             stream: tuple = (0, 0), table: dict | None = None,
             parent: Any = None, depth: int = 0):
        self.nodes += 1
        if depth > 128 or self.nodes > 100_000:
            self.malformed(path, page)
            return
        if isinstance(node, int) and not isinstance(node, bool):
            if node < 0 or page is None:
                self.malformed(path, page)
            elif figure:
                self.content[page, stream, node] = figure
            return
        if not _dict(node):
            self.malformed(path, page)
            return
        identity = _identity(node)
        if identity != (0, 0):
            if identity in self.seen:
                self.malformed(path, page)
                return
            self.seen.add(identity)
        if "/Pg" in node:
            page = self.pages.get(_identity(node.Pg))
            if page is None:
                self.malformed(path, page)
        if "/Stm" in node:
            stream = _identity(node.Stm)
        kind = str(node.get("/Type", ""))
        if kind == "/MCR":
            mcid = node.get("/MCID")
            if not isinstance(mcid, int) or mcid < 0 or page is None:
                self.malformed(path, page)
            elif figure:
                self.content[page, stream, mcid] = figure
            return
        if kind == "/OBJR":
            if not _dict(node.get("/Obj")):
                self.malformed(path, page)
            elif figure:
                self.objects[page, _identity(node.Obj)] = figure
            return
        role = self.role(node)
        if not role or (parent is not None and _identity(node.get("/P")) != _identity(parent)):
            self.malformed(path, page)
        parent_role = self.role(parent) if _dict(parent) and "/S" in parent else ""
        if ((role in ("/TH", "/TD") and parent_role != "/TR")
                or (role == "/TR" and parent_role not in ("/Table", "/THead", "/TBody", "/TFoot"))
                or (parent_role == "/Table" and role not in ("/TR", "/THead", "/TBody", "/TFoot"))):
            self.malformed(path, page)
        if role == "/Figure":
            figure = path
            self.figures[path] = node
            alt = node.get("/Alt")
            if not isinstance(alt, pikepdf.String) or not str(alt).strip():
                self.add("CHK-NONTEXT", "missing_figure_alt", path,
                         "Figure has no nonempty alternative description", page, "fail")
        if role == "/Table":
            table = {"data": 0, "headers": 0}
        if table is not None:
            if role == "/TD":
                table["data"] += 1
            elif role == "/TH":
                table["headers"] += 1
        children = _children(node.get("/K"))
        for n, child in enumerate(children):
            self.walk(child, f"{path}/K[{n}]", page, figure, stream, table, node, depth + 1)
        if role == "/Table" and table and table["data"] and not table["headers"]:
            self.add("CHK-STRUCTURE", "table_missing_headers", path,
                     "Tagged table contains data cells but no header cells; review table relationships", page)

    def structure(self):
        root = self.pdf.Root.get("/StructTreeRoot")
        if not _dict(root) or not _children(root.get("/K")):
            self.add("CHK-STRUCTURE", "missing_document_structure", "Catalog/StructTreeRoot",
                     "Document has no usable structure tree", result="fail")
            if root is not None and not _dict(root):
                self.malformed("Catalog/StructTreeRoot")
            return
        mark = self.pdf.Root.get("/MarkInfo")
        if not _dict(mark) or mark.get("/Marked") is not True:
            self.add("CHK-STRUCTURE", "document_not_marked", "Catalog/MarkInfo/Marked",
                     "Document has structure tags but is not marked as tagged")
        roles = root.get("/RoleMap", pikepdf.Dictionary())
        if _dict(roles):
            self.roles = roles
        else:
            self.malformed("Catalog/StructTreeRoot/RoleMap")
        for n, child in enumerate(_children(root.get("/K"))):
            path = f"Catalog/StructTreeRoot/K[{n}]"
            try:
                self.walk(child, path, None, None, parent=root)
            except (ValueError, TypeError, AttributeError, pikepdf.PdfError, RuntimeError):
                self.malformed(path)

    def scan(self, source: Any, resources: Any, page: int, path: str,
             stream: tuple = (0, 0), contexts: list | None = None,
             active: frozenset = frozenset(), depth: int = 0):
        if depth > 64:
            raise ValueError("Form nesting exceeds inspection limit")
        contexts = list(contexts or [])
        initial = len(contexts)
        for index, instruction in enumerate(pikepdf.parse_content_stream(source)):
            ref = f"{path}/op[{index}]"
            if isinstance(instruction, pikepdf.ContentStreamInlineImage):
                self.image(page, ref, contexts, None)
                continue
            operands, operator = instruction.operands, instruction.operator
            op = str(operator)
            if op in ("BDC", "BMC"):
                artifact = str(operands[0]) == "/Artifact"
                figure = None
                if op == "BDC":
                    props = operands[1]
                    if isinstance(props, pikepdf.Name):
                        props = resources.get("/Properties", {}).get(str(props))
                    if _dict(props):
                        mcid = props.get("/MCID")
                        figure = self.content.get((page, stream, mcid)) if isinstance(mcid, int) else None
                contexts.append((artifact, figure))
            elif op == "EMC":
                if len(contexts) <= initial:
                    raise ValueError("Unbalanced marked content")
                contexts.pop()
            elif op == "Do":
                obj = resources.get("/XObject", {}).get(str(operands[0]))
                if not isinstance(obj, pikepdf.Stream):
                    raise ValueError("Unresolved XObject")
                subtype = str(obj.get("/Subtype", ""))
                if subtype == "/Image":
                    self.image(page, ref, contexts, obj)
                elif subtype == "/Form":
                    identity = _identity(obj)
                    if identity in active:
                        raise ValueError("Cyclic Form XObject")
                    self.scan(obj, obj.get("/Resources", resources), page, ref,
                              identity, contexts, active | {identity}, depth + 1)
        if len(contexts) != initial:
            raise ValueError("Unclosed marked content")

    def image(self, page: int, ref: str, contexts: list, obj: Any):
        if any(artifact for artifact, _ in contexts):
            return
        figure = next((fig for _, fig in reversed(contexts) if fig), None)
        if not figure and obj is not None:
            figure = self.objects.get((page, _identity(obj)))
        # A mapped Figure already has one missing-alt finding, or a usable Alt.
        if figure:
            return
        self.add("CHK-NONTEXT", "image_without_text_alternative", ref,
                 "Drawn image has no resolvable Figure alternative; "
                 "review its purpose and text alternative", page)

    def run(self) -> list[Issue]:
        self.structure()
        for n, page in enumerate(self.pdf.pages, 1):
            try:
                self.scan(page, page.resources, n, f"Page[{n}]/Contents")
            except (ValueError, TypeError, AttributeError, IndexError, KeyError,
                    pikepdf.PdfError, RuntimeError):
                self.add("CHK-NONTEXT", "image_inspection_incomplete", f"Page[{n}]/Contents",
                         "Image content could not be fully inspected; review this page manually", n)
        return self.issues


def detect_pdf_issues(pdf: pikepdf.Pdf) -> list[Issue]:
    return Inspector(pdf).run()
