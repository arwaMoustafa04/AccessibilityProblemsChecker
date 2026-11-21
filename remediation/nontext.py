"""Bounded AI image repairs. Semantic correctness always remains human review.

Use the detector's MCID/OBJR associations, never guess a Figure from image order.
Shared forms and ambiguous/multi-image figures are left for manual tagging.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import pikepdf

from checks.base import Issue
from pdf_checks import Inspector, is_generic_alt
from remediation import RepairAction, RepairContext, ai, repairer

MAX_IMAGES_PER_PDF = 8
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
N, D, A = pikepdf.Name, pikepdf.Dictionary, pikepdf.Array


@dataclass
class Source:
    obj: Any
    instructions: list
    replacements: dict[int, list] = field(default_factory=dict)


@dataclass
class ImageUse:
    page: int
    ref: str
    source: Source
    index: int
    image: Any
    figure: str | None
    contexts: list


class Inventory(Inspector):
    """Reuse detector traversal, including role maps, nested forms and inline images."""

    def __init__(self, pdf):
        super().__init__(pdf)
        self.sources: dict[str, Source] = {}
        self.uses: list[ImageUse] = []
        self.active_sources: list[Source] = []
        self.attempted = 0

    def scan(self, source, resources, page, path, stream=(0, 0), contexts=None, active=frozenset(), depth=0):
        state = Source(source, list(pikepdf.parse_content_stream(source)))
        self.sources[path] = state
        self.active_sources.append(state)
        try:
            super().scan(source, resources, page, path, stream, contexts, active, depth)
        finally:
            self.active_sources.pop()

    def image(self, page, ref, contexts, obj):
        if any(artifact for artifact, _ in contexts):
            return
        figure = next((f for _, f in reversed(contexts) if f), None)
        if not figure and obj is not None:
            figure = self.objects.get((page, obj.objgen))
        source = self.active_sources[-1]
        index = int(ref.rsplit("/op[", 1)[1][:-1])
        inst = source.instructions[index]
        image = inst.iimage if isinstance(inst, pikepdf.ContentStreamInlineImage) else obj
        self.uses.append(ImageUse(page, ref, source, index, image, figure, list(contexts)))
        super().image(page, ref, contexts, obj)

    def flush(self, rctx: RepairContext):
        for state in self.sources.values():
            if not state.replacements:
                continue
            ops = [
                op for n, inst in enumerate(state.instructions) for op in state.replacements.get(n, [inst])
            ]
            data = pikepdf.unparse_content_stream(ops)
            if isinstance(state.obj, pikepdf.Page):
                state.obj.Contents = self.pdf.make_stream(data)
            else:
                state.obj.write(data)
        # Content operator positions change when wrappers are inserted. Preserve
        # before/after identity for unrepaired findings (including nested paths).
        for path, state in self.sources.items():
            offset = 0
            new_path = path
            for old, new in sorted(rctx.content_refs.items(), key=lambda pair: -len(pair[0])):
                if path.startswith(old + "/"):
                    new_path = new + path[len(old) :]
                    break
            for n in range(len(state.instructions)):
                rctx.content_refs[f"{path}/op[{n}]"] = f"{new_path}/op[{n + offset}]"
                offset += len(state.replacements.get(n, [state.instructions[n]])) - 1


def _inventory(rctx):
    if "images" not in rctx.shared:
        inventory = Inventory(rctx.pdf)
        inventory.run()
        rctx.shared["images"] = inventory
    return rctx.shared["images"]


def _image_bytes(use: ImageUse) -> bytes:
    image = use.image
    if isinstance(image, pikepdf.Stream):
        if image.get("/ImageMask", False) or "/SMask" in image or "/Mask" in image:
            raise ValueError("masked image needs manual review")
        image = pikepdf.PdfImage(image)
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ValueError("image pixel limit exceeded")
    # pikepdf's inline-image conversion cannot create a page smaller than 3pt.
    # Externalize on a disposable copy, retaining the source color-space resources.
    temporary = None
    if isinstance(image, pikepdf.PdfInlineImage):
        temporary = pikepdf.new()
        source: Any
        if isinstance(use.source.obj, pikepdf.Page):
            temporary.pages.append(use.source.obj)
            source = temporary.pages[0]
            source.Contents = temporary.make_stream(
                pikepdf.unparse_content_stream([use.source.instructions[use.index]])
            )
            source.externalize_inline_images()
        else:
            source = temporary.copy_foreign(use.source.obj)
            source.write(pikepdf.unparse_content_stream([use.source.instructions[use.index]]))
            page = temporary.add_blank_page()
            page.Resources = D(XObject=D(Fm=source))
            page.Contents = temporary.make_stream(b"/Fm Do")
            page.externalize_inline_images()
        instruction = next(op for op in pikepdf.parse_content_stream(source) if str(op.operator) == "Do")
        resources = source.resources if isinstance(source, pikepdf.Page) else source.Resources
        image_obj = resources.XObject[str(instruction.operands[0])]
        if not isinstance(image_obj, pikepdf.Stream):
            raise ValueError("Inline image extraction failed")
        image = pikepdf.PdfImage(image_obj)
    with image.as_pil_image() as pixels:
        pixels.thumbnail((1600, 1600))
        output = io.BytesIO()
        pixels.convert("RGB").save(output, format="PNG")
    if temporary is not None:
        temporary.close()
    data = output.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image byte limit exceeded")
    return data


def _parent_entries(node, seen=None):
    """Read an existing number tree without silently discarding any branches."""
    seen = set() if seen is None else seen
    if not isinstance(node, pikepdf.Dictionary) or node.objgen in seen:
        raise ValueError("invalid parent number tree")
    if node.is_indirect:
        seen.add(node.objgen)
    entries = {}
    nums = node.get("/Nums", A())
    if len(nums) % 2:
        raise ValueError("invalid parent number tree")
    for i in range(0, len(nums), 2):
        key = int(nums[i])
        if key in entries:
            raise ValueError("duplicate parent number")
        entries[key] = nums[i + 1]
    for kid in node.get("/Kids", A()):
        for key, value in _parent_entries(kid, seen).items():
            if key in entries:
                raise ValueError("duplicate parent number")
            entries[key] = value
    return entries


def _instruction(operands, op):
    return pikepdf.ContentStreamInstruction(operands, pikepdf.Operator(op))


def _new_figure(use: ImageUse, rctx: RepairContext, text: str):
    # New tagging is local to a page. Shared form streams and existing marked
    # content need a richer tagging editor; do not create conflicting MCIDs.
    if not isinstance(use.source.obj, pikepdf.Page) or use.contexts:
        raise ValueError("image is inside existing marked content or a Form")
    pdf = rctx.pdf
    tree = pdf.Root.get("/StructTreeRoot")
    if tree is None:
        tree = pdf.make_indirect(D(Type=N.StructTreeRoot, K=A()))
    if not isinstance(tree, pikepdf.Dictionary):
        raise ValueError("invalid structure tree")
    entries = _parent_entries(tree.ParentTree) if "/ParentTree" in tree else {}
    page = use.source.obj
    key: Any = page.obj.get("/StructParents")
    if key is None:
        reserved = [int(p.obj.StructParents) for p in pdf.pages if "/StructParents" in p.obj]
        key = max([*entries, *reserved, int(tree.get("/ParentTreeNextKey", 0)) - 1], default=-1) + 1
    parents = entries.get(int(key), A())
    if not isinstance(parents, pikepdf.Array):
        raise ValueError("page parent entry is not an array")
    parents = A(list(parents))
    # Existing MCIDs may be present even if the parent tree is incomplete.
    ids = [
        int(m) for m in re.findall(rb"/MCID\s+(\d+)", pikepdf.unparse_content_stream(use.source.instructions))
    ]
    mcid = max([len(parents) - 1, *ids], default=-1) + 1
    while len(parents) <= mcid:
        parents.append(None)
    figure = pdf.make_indirect(D(Type=N.StructElem, S=N.Figure, P=tree, Pg=page.obj, K=mcid, Alt=text))
    parents[mcid] = figure
    entries[int(key)] = parents
    nums = A()
    for k, value in sorted(entries.items()):
        nums.extend([k, value])
    kids = tree.get("/K")
    kids = A(list(kids)) if isinstance(kids, pikepdf.Array) else A([] if kids is None else [kids])
    kids.append(figure)
    tree.K = kids
    tree.ParentTree = pdf.make_indirect(D(Nums=nums))
    tree.ParentTreeNextKey = max(entries) + 1
    pdf.Root.StructTreeRoot = tree
    # Do not claim the whole document is fully tagged merely by tagging one image.
    page.obj.StructParents = int(key)
    use.source.replacements[use.index] = [
        _instruction([N.Figure, D(MCID=mcid)], "BDC"),
        use.source.instructions[use.index],
        _instruction([], "EMC"),
    ]
    return figure


def _artifact(use: ImageUse, figure, inventory: Inventory):
    if not isinstance(use.source.obj, pikepdf.Page):
        raise ValueError("decorative image in a shared Form requires manual review")
    if figure is not None:
        # Only convert a complete, image-only Figure scope. Never artifact text or
        # other meaningful content merely because one contained image is decorative.
        kids = figure.get("/K")
        if not isinstance(kids, int):
            raise ValueError("complex Figure scope requires manual review")
        start = end = None
        depth = 0
        for n, inst in enumerate(use.source.instructions):
            if isinstance(inst, pikepdf.ContentStreamInlineImage):
                continue
            op = str(inst.operator)
            if (
                op == "BDC"
                and isinstance(inst.operands[1], pikepdf.Dictionary)
                and inst.operands[1].get("/MCID") == kids
            ):
                if start is not None:
                    raise ValueError("ambiguous Figure MCID")
                start, depth = n, 1
            elif start is not None and end is None:
                if op in ("BDC", "BMC"):
                    depth += 1
                elif op == "EMC":
                    depth -= 1
                    if depth == 0:
                        end = n
        if start is None or end is None or not start < use.index < end:
            raise ValueError("Figure content scope unavailable")
        for n in range(start + 1, end):
            inst = use.source.instructions[n]
            if n != use.index and (
                isinstance(inst, pikepdf.ContentStreamInlineImage)
                or str(inst.operator) not in {"q", "Q", "cm"}
            ):
                raise ValueError("Figure contains more than one image or meaningful content")
        tree = inventory.pdf.Root.StructTreeRoot
        entries = _parent_entries(tree.ParentTree) if "/ParentTree" in tree else {}
        key = use.source.obj.obj.get("/StructParents")
        parents = entries.get(key)
        if parents is not None and not isinstance(parents, pikepdf.Array):
            raise ValueError("invalid Figure parent entry")
        # Retain an empty structural container so sibling paths remain stable.
        figure.S = N.Div
        figure.K = A()
        if "/Alt" in figure:
            del figure.Alt
        if parents is not None and kids < len(parents):
            parents[kids] = None
        use.source.replacements[start] = [_instruction([N.Artifact], "BMC")]
    else:
        if use.contexts:
            raise ValueError("image already belongs to marked content")
        use.source.replacements[use.index] = [
            _instruction([N.Artifact], "BMC"),
            use.source.instructions[use.index],
            _instruction([], "EMC"),
        ]


@repairer("CHK-NONTEXT", "missing_figure_alt", "generic_figure_alt", "image_without_text_alternative")
def repair_image(issue: Issue, rctx: RepairContext) -> RepairAction | None:
    inventory = _inventory(rctx)
    uses = [
        u
        for u in inventory.uses
        if (
            u.figure == issue.object_ref
            if issue.issue_type != "image_without_text_alternative"
            else u.ref == issue.object_ref
        )
    ]
    if len(uses) != 1:
        rctx.note(f"CHK-NONTEXT: {issue.object_ref} has no unambiguous single image; review it manually.")
        return None
    use = uses[0]
    figure = inventory.figures.get(use.figure)
    if inventory.attempted >= MAX_IMAGES_PER_PDF:
        rctx.note(
            f"CHK-NONTEXT: image limit ({MAX_IMAGES_PER_PDF} per PDF) reached; "
            "remaining images require human review."
        )
        return None
    inventory.attempted += 1
    try:
        data = _image_bytes(use)
    except Exception:
        rctx.note(
            f"CHK-NONTEXT: image on page {use.page} could not be extracted "
            "within image limits; review it manually."
        )
        return None
    if ai.sends_data():
        rctx.note(
            
                "CHK-NONTEXT: image content and page text were sent to the "
                "configured external model provider. AI-generated descriptions and"
                " decorative decisions require human review."
            
        )
    nearby = rctx.check.doc[use.page - 1].get_text("text")[:2000]
    text = ai.describe_image(data, nearby, "image/png")
    if not text or is_generic_alt(text):
        rctx.note(
            
                "CHK-NONTEXT: AI alt text was unavailable or unusable; rule-based "
                "suggestions are provided and images remain for human review."
            
        )
        return None
    if not ai.writes_human_review_fixes():
        # REQ-06 / AC-04: a human-review issue is not changed automatically. The AI draft
        # is offered as the finding's suggestion; a person decides whether to apply it.
        issue.suggested_text = text  # ai.DECORATIVE: "mark it as an artifact" (UI label)
        issue.suggestion_source = "llm"
        rctx.note("CHK-NONTEXT: AI-drafted alt text is given as a suggestion only "
                  "(AI-generated, please verify); human-review issues are not changed "
                  "automatically, so a person must review and apply it.")
        return None
    try:
        if text == ai.DECORATIVE:
            _artifact(use, figure, inventory)
            action = "Marked image content as an Artifact (AI-generated decorative decision, please verify)"
        else:
            written = text + " [AI-generated, please verify]"
            if figure is None:
                _new_figure(use, rctx, written)
            else:
                figure.Alt = pikepdf.String(written)
            action = "Wrote Figure alt text (AI-generated, please verify)"
            text = written
        inventory.flush(rctx)
    except (ValueError, TypeError, pikepdf.PdfError):
        rctx.note(
            f"CHK-NONTEXT: image on page {use.page} needs manual tag editing; AI suggestion was not applied."
        )
        issue.suggested_text, issue.suggestion_source = text, "llm"
        return None
    rctx.note(
        
            "CHK-NONTEXT: AI-generated image repairs require human "
            "verification; tagging an image does not establish complete "
            "document structure."
        
    )
    return RepairAction(action, applied_text=text, method="llm")
