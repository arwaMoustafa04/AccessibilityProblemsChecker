"""CHK-LINK repair (human_review): write a descriptive accessible label for a link
whose text is generic ("click here") or missing.

The label goes into the link annotation's /Contents and, when the link is tagged,
the Link structure element's /Alt. The visible page text, the link target and the
annotation rectangle are not changed. The label is AI-written when an LLM is
available (remediation/ai.py) and otherwise rule-based: the purpose stated in the
sentence ("To apply for financial aid, click here" -> "Apply for financial aid"), or
the destination host/path or page. Only the host and path are sent to the model,
never the query string.

Re-validation re-runs CHK-LINK on the saved copy; the repair passes when the link no
longer has a generic or missing label. The finding stays needs_human_review: a
person must confirm the wording (spec v0.5.0).
"""

from __future__ import annotations

import re

import pikepdf

from checks.base import Issue
from checks.link import destination_hint, fallback_label, is_generic, link_tags
from remediation import RepairAction, RepairContext, ai, repairer

_OBJ_REF = re.compile(r"^(\d+) (\d+) R$")
_PAGE_REF = re.compile(r"^Page\[(\d+)\]/Annots\[(\d+)\]$")


def _annotation(pdf: pikepdf.Pdf, issue: Issue) -> pikepdf.Dictionary | None:
    ref = issue.object_ref or ""
    try:
        if m := _OBJ_REF.match(ref):
            annot = pdf.get_object(int(m[1]), int(m[2]))
        elif m := _PAGE_REF.match(ref):
            annot = pdf.pages[int(m[1]) - 1].obj.Annots[int(m[2])]
        else:
            return None
    except (IndexError, KeyError, ValueError, AttributeError, pikepdf.PdfError):
        return None
    if isinstance(annot, pikepdf.Dictionary) and annot.get("/Subtype") == pikepdf.Name.Link:
        return annot
    return None


def _usable(text: str | None, context: str) -> str | None:
    """An AI label is used only if it is specific, short and not a placeholder."""
    if not text or "[" in text or is_generic(text) or len(text) > ai.MAX_LINK_CHARS:
        return None
    return None if text.casefold() == context.strip().casefold() else text


@repairer("CHK-LINK", "link_purpose_unclear", "link_label_missing")
def label_link(issue: Issue, rctx: RepairContext) -> RepairAction | None:
    annot = _annotation(rctx.pdf, issue)
    if annot is None:
        return None
    context = issue.evidence or ""
    hint = destination_hint(annot, rctx.check.page_numbers)
    text, method = None, "rule"
    if context and ai.available():
        if ai.sends_data():
            rctx.note("CHK-LINK: the sentence around each unclear link and its destination "
                      "(host and path only) were sent to the configured external model "
                      "provider to draft link labels.")
        text = _usable(ai.suggest_link_text(context, hint or "unknown"), context)
        if text:
            method = "llm"
    if not text:
        text = issue.suggested_text or fallback_label(context, hint)

    if "link_tags" not in rctx.shared:
        rctx.shared["link_tags"] = link_tags(rctx.check)
    tag = rctx.shared["link_tags"].get(annot.objgen)  # type: ignore[union-attr]
    annot.Contents = pikepdf.String(text)
    if tag is not None:
        tag.Alt = pikepdf.String(text)
        where = "the link annotation (/Contents) and its Link tag (/Alt)"
    else:
        where = ("the link annotation (/Contents) only; the link is not tagged, "
                 "so check it with a screen reader")
    rctx.note("CHK-LINK: link labels were written as accessible names; the visible link text "
              "is unchanged. A person should confirm each label describes its destination.")
    # method="llm" is labelled "AI-generated, please verify" by the report and the UI.
    return RepairAction(f'Wrote link label "{text}" to {where}',
                        applied_text=text, method=method)  # type: ignore[arg-type]
