"""CHK-TITLE: WCAG 2.4.2 Page Titled (auto_fixable).

A PDF passes when it has a descriptive title (Info /Title and XMP dc:title) and
tells viewers to show that title instead of the file name
(ViewerPreferences/DisplayDocTitle = true, required by PDF/UA-1 clause 7.1).
"""

from __future__ import annotations

import re
import warnings
from pathlib import PurePath

from checks.base import CheckContext, Issue
from checks.verapdf import RuleFailure

CHECK_ID = "CHK-TITLE"
_PLACEHOLDERS = {"untitled", "untitled document", "document", "title", "new document",
                 "slide 1", "page 1", "pdf", "none", "null", "-"}
_FILE_EXT = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|odt|rtf|txt|indd)$", re.IGNORECASE)


def info_title(ctx: CheckContext) -> str:
    try:
        return str(ctx.pdf.docinfo.get("/Title", "")).strip()
    except Exception:
        return ""


def xmp_title(ctx: CheckContext) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pikepdf warns about odd dates in XMP
            with ctx.pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                return str(meta.get("dc:title", "") or "").strip()
    except Exception:
        return ""


def document_title(ctx: CheckContext) -> str:
    return info_title(ctx) or xmp_title(ctx) or str(ctx.doc.metadata.get("title") or "").strip()


def _looks_like_placeholder(title: str, file_name: str) -> bool:
    t = title.strip().lower()
    stem = PurePath(file_name).stem.lower()
    return (t in _PLACEHOLDERS or bool(_FILE_EXT.search(t)) or t == stem
            or t.startswith("microsoft word -") or t.startswith("microsoft powerpoint -"))


def _cite(issue: Issue, rule: RuleFailure) -> None:
    if "veraPDF" not in issue.sources:
        issue.sources.append("veraPDF")
    issue.suggestion = (issue.suggestion or "") + f" (veraPDF PDF/UA-1 rule {rule.rule_id})"


def check(ctx: CheckContext) -> list[Issue]:
    issues: list[Issue] = []
    title = document_title(ctx)
    by_type: dict[str, Issue] = {}

    if not title:
        by_type["missing_document_title"] = Issue(
            CHECK_ID, "missing_document_title",
            "Document title is missing (no Info /Title or XMP dc:title).",
            object_ref="Info/Title, Metadata/dc:title",
            suggestion="Set a title that describes the document's topic or purpose.",
            sources=["pikepdf"])
    else:
        if info_title(ctx) and not xmp_title(ctx):
            by_type["title_missing_from_xmp"] = Issue(
                CHECK_ID, "title_missing_from_xmp",
                "Title is set in the Info dictionary but not in the XMP metadata (dc:title).",
                object_ref="Metadata/dc:title",
                suggestion="Copy the title into the XMP metadata, as PDF/UA-1 requires.",
                sources=["pikepdf"])
        if _looks_like_placeholder(title, ctx.file_name):
            by_type["title_not_descriptive"] = Issue(
                CHECK_ID, "title_not_descriptive",
                f'Document title "{title}" looks like a file name or placeholder.',
                evaluation_result="needs_review", object_ref="Info/Title",
                suggestion="Replace it with a title that describes the document.",
                sources=["pikepdf"])

    prefs = ctx.pdf.Root.get("/ViewerPreferences")
    display = prefs.get("/DisplayDocTitle") if prefs is not None else None
    if display is not True:
        by_type["display_doc_title_not_set"] = Issue(
            CHECK_ID, "display_doc_title_not_set",
            "Viewers are not told to show the document title (DisplayDocTitle is not true), "
            "so the file name is shown instead.",
            object_ref="Catalog/ViewerPreferences/DisplayDocTitle",
            suggestion="Set ViewerPreferences/DisplayDocTitle to true.",
            sources=["pikepdf"])

    # veraPDF confirms these, and adds any title rule our own checks did not catch.
    for rule in ctx.verapdf.matching("7.1", "DisplayDocTitle", "dc:title", "title"):
        text = rule.description.lower()
        key = ("display_doc_title_not_set" if "displaydoctitle" in text
               else "missing_document_title" if not title
               else "title_missing_from_xmp")
        if key in by_type:
            _cite(by_type[key], rule)
        else:
            by_type[key] = Issue(CHECK_ID, key, rule.description,
                                 object_ref=f"PDF/UA-1 {rule.rule_id}",
                                 suggestion=f"(veraPDF PDF/UA-1 rule {rule.rule_id})",
                                 sources=["veraPDF"])
    issues.extend(by_type.values())
    return issues
