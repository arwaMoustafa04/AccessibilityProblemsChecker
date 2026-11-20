"""CHK-LINK / WCAG 2.4.4: review annotation labels without visiting targets."""

import re

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


def _tag_labels(ctx: CheckContext) -> dict[tuple[int, int], str]:
    """Associate explicit Link alternative text only with its referenced annotation."""
    labels = {}
    for elem in iter_elements(ctx):
        if elem.tag != "/Link" or not _label(elem.obj):
            continue
        kids = elem.obj.get("/K")
        for child in kids if isinstance(kids, pikepdf.Array) else [kids]:
            if isinstance(child, pikepdf.Dictionary) and child.get("/Type") == pikepdf.Name.OBJR:
                obj = child.get("/Obj")
                if isinstance(obj, pikepdf.Dictionary) and obj.objgen != (0, 0):
                    labels[obj.objgen] = _label(elem.obj)
    return labels


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
            if not label:
                try:
                    rect = pymupdf.Rect([float(v) for v in annot["/Rect"]])
                    rect = rect * page.transformation_matrix
                    if rect.is_empty or rect.is_infinite:
                        raise ValueError("invalid rectangle")
                    label = " ".join(page.get_textbox(rect).split())
                except (KeyError, TypeError, ValueError, OverflowError):
                    malformed = True
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
            issues.append(Issue(
                CHECK_ID, kind, description, evaluation_result="needs_review",
                page=number, object_ref=ref,
                suggestion="Provide meaningful link text or a tagged alternative description that "
                           "identifies its purpose, and verify the associated context.",
                sources=["pikepdf", "PyMuPDF"],
            ))
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
