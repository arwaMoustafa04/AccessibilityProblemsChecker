"""CHK-LINK / WCAG 2.4.4: review annotation labels without visiting targets."""

import re
from urllib.parse import unquote, urlsplit

import pikepdf
import pymupdf

from checks.base import CheckContext, Issue
from checks.structure_tree import iter_elements

CHECK_ID = "CHK-LINK"
GENERIC = {"click here", "here", "read more", "more", "learn more", "link", "download", "go", "continue"}
URL = re.compile(r"^(?:https?://|www\.|mailto:|tel:)", re.I)


def _label(obj) -> str:
    return next((str(obj.get(k, "")).strip() for k in ("/ActualText", "/Alt", "/Contents")
                 if str(obj.get(k, "")).strip()), "")


def link_tags(ctx: CheckContext) -> dict[tuple[int, int], pikepdf.Dictionary]:
    """Annotation (objgen) -> the Link structure element that references it via OBJR."""
    tags = {}
    for elem in iter_elements(ctx):
        if elem.tag != "/Link":
            continue
        kids = elem.obj.get("/K")
        for child in kids if isinstance(kids, pikepdf.Array) else [kids]:
            if isinstance(child, pikepdf.Dictionary) and child.get("/Type") == pikepdf.Name.OBJR:
                obj = child.get("/Obj")
                if isinstance(obj, pikepdf.Dictionary) and obj.objgen != (0, 0):
                    tags[obj.objgen] = elem.obj
    return tags


def _tag_labels(ctx: CheckContext) -> dict[tuple[int, int], str]:
    """Associate explicit Link alternative text only with its referenced annotation."""
    return {objgen: _label(tag) for objgen, tag in link_tags(ctx).items() if _label(tag)}


# --- Context and rule-based labels (suggested_text, and the CHK-LINK repair) ---------

_PURPOSE = re.compile(r"\b[Tt]o ([\w '-]{3,70}),\s*(?:please\s+)?(?:click|tap|select)(?: here)?\b")


def link_rect(page: pymupdf.Page, annot: pikepdf.Dictionary) -> pymupdf.Rect:
    """The annotation rectangle in PyMuPDF page coordinates (raises if unreadable)."""
    rect = pymupdf.Rect([float(v) for v in annot["/Rect"]]) * page.transformation_matrix
    if rect.is_empty or rect.is_infinite:
        raise ValueError("invalid rectangle")
    return rect


def link_context(page: pymupdf.Page, rect: pymupdf.Rect, visible: str) -> str:
    """The sentence around a link (else its text block), so a label can state its purpose."""
    area = pymupdf.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2)
    needle = visible.casefold().strip()
    for block in page.get_text("blocks"):
        if (len(block) > 6 and block[6] != 0) or not pymupdf.Rect(block[:4]).intersects(area):
            continue
        text = " ".join(str(block[4]).split())
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if needle and needle in sentence.casefold():
                return sentence[:400]
        return text[:400]
    return ""


def destination_hint(annot: pikepdf.Dictionary, page_numbers: dict) -> str:
    """Where the link goes, without query strings: "host/path", "page N", or ""."""
    action = annot.get("/A")
    dest = annot.get("/Dest")
    if isinstance(action, pikepdf.Dictionary):
        dest = action.get("/D", dest)
        if action.get("/S") == pikepdf.Name.URI:
            try:
                uri = urlsplit(str(action.get("/URI", "")))
                if uri.scheme.lower() in {"http", "https"} and uri.hostname:
                    return (uri.hostname + uri.path)[:160]
            except ValueError:
                pass
    if isinstance(dest, pikepdf.Array) and len(dest) and isinstance(dest[0], pikepdf.Dictionary):
        number = page_numbers.get(dest[0].objgen)
        if number:
            return f"page {number}"
    return ""


def fallback_label(context: str, hint: str) -> str:
    """A rule-based accessible label: the stated purpose, else the destination."""
    purpose = _PURPOSE.search(context or "")
    if purpose:
        return purpose[1][:1].upper() + purpose[1][1:]
    if hint.startswith("page "):
        return f"Go to {hint}"
    if hint:
        host, _, path = hint.partition("/")
        name = re.sub(r"[-_]+", " ", unquote(path.rstrip("/").split("/")[-1]))
        if name and re.fullmatch(r"[\w ]{2,64}", name):
            return f"Open {name} on {host}"
        return f"Open link to {host}"
    return "Open linked destination"


def is_generic(label: str) -> bool:
    return " ".join(label.casefold().split()).strip(" .:!?") in GENERIC


def check(ctx: CheckContext) -> list[Issue]:
    issues = []
    tag_labels = _tag_labels(ctx)
    for number, pdf_page in enumerate(ctx.pdf.pages, 1):
        page = ctx.doc[number - 1]
        for index, annot in enumerate(pdf_page.obj.get("/Annots", [])):
            if not isinstance(annot, pikepdf.Dictionary) or annot.get("/Subtype") != pikepdf.Name.Link:
                continue
            ref = f"{annot.objgen[0]} {annot.objgen[1]} R" if annot.objgen != (0, 0) else (
                f"Page[{number}]/Annots[{index}]"
            )
            label = tag_labels.get(annot.objgen) or _label(annot)
            malformed = False
            rect = None
            try:
                rect = link_rect(page, annot)
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
            if not label:
                if rect is None:
                    malformed = True
                else:
                    label = " ".join(page.get_textbox(rect).split())
            normalized = " ".join(label.casefold().split()).strip(" .:!?")
            if malformed:
                kind = "link_location_unreadable"
                description = ("The link rectangle could not be read, so its visible label "
                               "needs manual review.")
            elif not normalized:
                kind = "link_label_missing"
                description = "No text label or explicit alternative description was found for this link."
            elif normalized in GENERIC:
                kind = "link_purpose_unclear"
                description = f'Link label "{label}" is generic. Programmatically associated context '
                description += "may explain its purpose; check that context before deciding it fails."
            elif URL.match(normalized):
                kind = "link_url_needs_review"
                description = "This link is labelled with an address. Confirm the address and associated "
                description += "context explain the link purpose."
            else:
                continue
            issue = Issue(
                CHECK_ID, kind, description, evaluation_result="needs_review",
                page=number, object_ref=ref,
                suggestion="Provide meaningful link text or a tagged alternative description that "
                           "identifies its purpose, and verify the associated context.",
                sources=["pikepdf", "PyMuPDF"],
            )
            if kind in ("link_purpose_unclear", "link_label_missing") and rect is not None:
                # Proposed accessible label; remediation/link.py writes it (or an AI one).
                visible = " ".join(page.get_textbox(rect).split()) or label
                issue.evidence = link_context(page, rect, visible) or visible
                issue.suggested_text = fallback_label(
                    issue.evidence, destination_hint(annot, ctx.page_numbers))
                issue.suggestion_source = "rule"
            issues.append(issue)
    # Only the link-specific PDF/UA-1 rules, not generic annotation rules
    # (7.18.1 can concern unrelated annotations). These are supporting machine
    # findings, not a verdict on contextual WCAG 2.4.4 conformance.
    report = ctx.verapdf  # cached by CheckContext; shared with Person 3 checks
    if report.available:
        seen = set()
        for rule in report.matching("7.18.5"):
            locations: list[int | None] = list(rule.pages) if rule.pages else [None]
            for page_number in locations:
                key = (rule.rule_id, page_number)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(Issue(
                    CHECK_ID, "link_pdfua_rule_needs_review",
                    f"veraPDF reported PDF/UA-1 rule {rule.rule_id}: {rule.description} "
                    "Review the link tagging/alternative description and contextual purpose; "
                    "this PDF/UA result alone does not establish a WCAG 2.4.4 failure.",
                    evaluation_result="needs_review", page=page_number,
                    object_ref=f"PDF/UA-1 {rule.rule_id}",
                    suggestion="Inspect the reported link annotations in an accessibility editor "
                               "and provide correct Link tagging and meaningful alternative descriptions.",
                    sources=["veraPDF"],
                ))
    return issues
