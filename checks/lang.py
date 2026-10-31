"""CHK-LANG: WCAG 3.1.1 Language of Page (auto_fixable).

A PDF passes when the catalog declares a valid default language (/Lang, a BCP 47
tag such as "en-US"), and any language set on structure elements is valid too.
"""

from __future__ import annotations

import re

from checks.base import CheckContext, Issue
from checks.structure_tree import iter_elements
from checks.text_layout import pages_with_text

CHECK_ID = "CHK-LANG"
# BCP 47 shape: primary language (2-3 letters, or i-/x- forms) plus optional subtags.
_BCP47 = re.compile(r"^(?:[A-Za-z]{2,3}|[ix])(?:-[A-Za-z0-9]{1,8})*$")
_NOT_A_LANGUAGE = {"und", "zxx", "mul", "unknown", "x-unknown", "none"}


def is_valid_language(tag: str) -> bool:
    return bool(_BCP47.match(tag)) and tag.lower() not in _NOT_A_LANGUAGE


def check(ctx: CheckContext) -> list[Issue]:
    issues: list[Issue] = []
    lang = str(ctx.pdf.Root.get("/Lang", "")).strip()
    text_pages = pages_with_text(ctx.doc)

    if not lang:
        where = f"; {text_pages} page(s) contain text" if text_pages else ""
        issues.append(Issue(
            CHECK_ID, "missing_document_language",
            f"Document language is missing (no /Lang in the catalog){where}.",
            object_ref="Catalog/Lang",
            suggestion="Set the document language, e.g. en-US, so screen readers "
                       "use the right pronunciation.",
            sources=["pikepdf", "PyMuPDF"]))
    elif not is_valid_language(lang):
        issues.append(Issue(
            CHECK_ID, "invalid_document_language",
            f'Document language "{lang}" is not a valid language tag.',
            object_ref="Catalog/Lang",
            suggestion="Use a BCP 47 language tag such as en, en-US or es-MX.",
            sources=["pikepdf"]))

    for elem in iter_elements(ctx):
        elem_lang = str(elem.obj.get("/Lang", "")).strip()
        if "/Lang" in elem.obj and not is_valid_language(elem_lang):
            issues.append(Issue(
                CHECK_ID, "invalid_element_language",
                f'A {elem.tag[1:]} element has an invalid language "{elem_lang}".',
                page=elem.page, object_ref=elem.ref,
                suggestion="Use a valid BCP 47 language tag for this passage.",
                sources=["pikepdf"]))

    # veraPDF: text whose language cannot be determined. Only adds something when the
    # document language is set (otherwise it is the same problem as the one above).
    if lang and is_valid_language(lang):
        for rule in ctx.verapdf.matching("7.2", "natural language", "Lang"):
            issues.append(Issue(
                CHECK_ID, "text_language_not_determinable", rule.description,
                page=rule.pages[0] if rule.pages else None,
                object_ref=f"PDF/UA-1 {rule.rule_id}",
                suggestion=f"Set /Lang on the affected text (veraPDF PDF/UA-1 rule {rule.rule_id}).",
                sources=["veraPDF"]))
    return issues
