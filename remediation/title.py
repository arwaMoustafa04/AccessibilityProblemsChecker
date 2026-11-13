"""Repairs for CHK-TITLE (WCAG 2.4.2 Page Titled, auto_fixable).

The title is written to the Info dictionary (/Title) and the XMP metadata
(dc:title), and viewers are told to show it (ViewerPreferences/DisplayDocTitle).

When the document has no usable title, one is chosen once per document, in order:
  1. an AI suggestion from the text of page 1 (remediation/ai.py, if an LLM is set up)
  2. the largest heading-like line on page 1 (rule-based)
  3. the file name, cleaned up ("annual_report.pdf" -> "Annual report")
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

import pikepdf

from checks.base import Issue
from checks.text_layout import lines, probable_headings
from checks.title import _looks_like_placeholder
from remediation import RepairAction, RepairContext, ai, repairer

CHECK_ID = "CHK-TITLE"


@dataclass(frozen=True)
class ChosenTitle:
    text: str
    source: str  # how it was chosen, in plain words (goes into the repair action)
    method: Literal["rule", "llm"]


def _info_title(pdf: pikepdf.Pdf) -> str:
    try:
        return str(pdf.docinfo.get("/Title", "")).strip()
    except Exception:
        return ""


def _xmp_title(pdf: pikepdf.Pdf) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            meta = pdf.open_metadata(set_pikepdf_as_editor=False)  # read only, no write-back
            return str(meta.get("dc:title", "") or "").strip()
    except Exception:
        return ""


def _write_title(pdf: pikepdf.Pdf, title: str, info: bool = True, xmp: bool = True) -> None:
    if info:
        pdf.docinfo["/Title"] = title
    if xmp:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # update_docinfo=False: only dc:title changes; other Info fields are kept.
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
                meta["dc:title"] = title


def _usable(title: str | None, file_name: str) -> str | None:
    title = ai.clean_title(title)
    if title is None or _looks_like_placeholder(title, file_name):
        return None
    return title


def _page_one_text(rctx: RepairContext) -> str:
    try:
        doc = rctx.check.doc
        return doc[0].get_text("text") if len(doc) else ""
    except Exception:
        return ""


def _heading_on_page_one(rctx: RepairContext) -> str | None:
    """The largest heading-like line on page 1 (first one if several are as large)."""
    try:
        all_lines = lines(rctx.check.doc)
    except Exception:
        return None
    first_page = [ln for ln in all_lines if ln.page == 1]
    candidates = [ln for ln in probable_headings(all_lines) if ln.page == 1] or first_page
    best = None
    for ln in candidates:  # in reading order; keep the first of the largest
        if _usable(ln.text, rctx.file_name) and (best is None or ln.size > best.size):
            best = ln
    return _usable(best.text, rctx.file_name) if best else None


def title_from_file_name(file_name: str) -> str:
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", PurePath(file_name).name)  # drop ".pdf"
    stem = re.sub(r"[_\-.]+", " ", name)
    stem = re.sub(r"\s+", " ", stem).strip()
    return (stem[:1].upper() + stem[1:]) if stem else "Document"


def choose_title(rctx: RepairContext) -> ChosenTitle:
    """Pick the new title once per document (cached in rctx.shared)."""
    cached = rctx.shared.get("title")
    if isinstance(cached, ChosenTitle):
        return cached
    suggestion = _usable(ai.suggest_title(_page_one_text(rctx), rctx.file_name), rctx.file_name)
    if suggestion:
        chosen = ChosenTitle(suggestion, "AI suggestion from the text of page 1", "llm")
        rctx.note("CHK-TITLE: the new title was suggested by an AI model from the text of "
                  "page 1 (AI-generated, please verify)."
                  + (" That text was sent to an external language model provider."
                     if ai.sends_data() else " (LLM mock mode: nothing was sent.)"))
    else:
        if ai.available():
            rctx.note("CHK-TITLE: the AI title suggestion was not available, so a rule-based "
                      "title was used instead (largest heading on page 1, else the file name).")
        heading = _heading_on_page_one(rctx)
        if heading:
            chosen = ChosenTitle(heading, "largest heading on page 1", "rule")
        else:
            chosen = ChosenTitle(title_from_file_name(rctx.file_name), "file name", "rule")
    rctx.shared["title"] = chosen
    return chosen


def _original_title(rctx: RepairContext) -> str:
    """The title before any title repair ran (read once, before the first write)."""
    if "original_title" not in rctx.shared:
        rctx.shared["original_title"] = _info_title(rctx.pdf) or _xmp_title(rctx.pdf)
    return str(rctx.shared["original_title"])


def _needs_new_title(rctx: RepairContext) -> bool:
    current = _original_title(rctx)
    return not current or _looks_like_placeholder(current, rctx.file_name)


def _ai_label(chosen: ChosenTitle) -> str:
    return "; AI-generated, please verify" if chosen.method == "llm" else ""


@repairer(CHECK_ID, "missing_document_title", "title_not_descriptive")
def set_title(issue: Issue, rctx: RepairContext) -> RepairAction:
    old = _original_title(rctx)
    chosen = choose_title(rctx)
    _write_title(rctx.pdf, chosen.text)
    if issue.issue_type == "title_not_descriptive" and old:
        action = f'Replaced the title "{old}" with "{chosen.text}" ({chosen.source})'
    else:
        action = f'Set the document title to "{chosen.text}" ({chosen.source})'
    return RepairAction(action + _ai_label(chosen), applied_text=chosen.text,
                        method=chosen.method)


@repairer(CHECK_ID, "title_missing_from_xmp")
def copy_title_to_xmp(issue: Issue, rctx: RepairContext) -> RepairAction:
    if _needs_new_title(rctx):  # the Info title is a placeholder too: use the new title
        chosen = choose_title(rctx)
        _write_title(rctx.pdf, chosen.text)
        return RepairAction(f'Set the XMP title (dc:title) to "{chosen.text}" ({chosen.source})'
                            + _ai_label(chosen), applied_text=chosen.text, method=chosen.method)
    title = _original_title(rctx)
    _write_title(rctx.pdf, title, info=False)
    return RepairAction(f'Copied the document title "{title}" into the XMP metadata (dc:title)',
                        applied_text=title)


@repairer(CHECK_ID, "display_doc_title_not_set")
def display_doc_title(issue: Issue, rctx: RepairContext) -> RepairAction:
    root = rctx.pdf.Root
    if not isinstance(root.get("/ViewerPreferences"), pikepdf.Dictionary):
        root.ViewerPreferences = pikepdf.Dictionary()
    root.ViewerPreferences.DisplayDocTitle = True
    return RepairAction("Set ViewerPreferences/DisplayDocTitle to true, so viewers show the "
                        "document title instead of the file name")
