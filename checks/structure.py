"""CHK-STRUCTURE: WCAG 1.3.1 Info and Relationships (human_review).

The detection is Person 1's tag inspector in pdf_checks.py: a nonempty structure
tree, the tagged-document marker, malformed relationships, and tagged tables with
data cells but no headers. Missing/empty structure is ``fail``; the rest is
``needs_review``.

veraPDF (PDF/UA-1 clause 7.1 tagging rules and clause 7.5 tables) confirms those
findings, and any structure rule it fails that the inspector did not report is
added for review.

In a tagged PDF, a paragraph (P) drawn in exactly the same font and size as a
tagged heading, short and without sentence punctuation, is reported as
"heading_tagged_as_paragraph" (needs_review): it looks like a heading but is
skipped by screen-reader heading navigation.
"""

from __future__ import annotations

from collections import Counter

from checks.base import CheckContext, Issue
from checks.marked_content import MarkedText, element_text
from checks.structure_tree import STANDARD_HEADINGS, is_tagged, iter_elements
from checks.verapdf import RuleFailure, add_advice, cite_rule

CHECK_ID = "CHK-STRUCTURE"
MAX_RULE_ISSUES = 20
# 7.1 also holds title/metadata rules (CHK-TITLE); only its tagging rules belong here.
_TAGGING_WORDS = ("tagged", "artifact", "structtreeroot", "structure", "marked")
MAX_HEADING_STYLE_ISSUES = 20
MAX_HEADING_WORDS = 12
MAX_HEADING_CHARS = 90


def _heading_tagged_as_paragraph(ctx: CheckContext) -> list[Issue]:
    """P elements drawn exactly like a tagged heading (same font and size)."""
    if not is_tagged(ctx):
        return []
    heading_style: dict[tuple[float, str], tuple[str, MarkedText]] = {}
    paragraphs = []
    for elem in iter_elements(ctx):
        if elem.tag in STANDARD_HEADINGS or elem.tag == "/P":
            text = element_text(ctx, elem)
            if text is None or not text.text.strip() or not text.size:
                continue
            if elem.tag == "/P":
                paragraphs.append((elem, text))
            else:
                heading_style.setdefault(text.style, (elem.tag.lstrip("/"), text))
    if not heading_style or not paragraphs:
        return []
    # The body style is the most-used paragraph style (by characters): never a heading.
    weights: Counter[tuple[float, str]] = Counter()
    for _, text in paragraphs:
        weights[text.style] += len(text.text)
    body = weights.most_common(1)[0][0]
    issues: list[Issue] = []
    for elem, text in paragraphs:
        words = text.text.split()
        if (text.style == body or text.style not in heading_style
                or len(words) > MAX_HEADING_WORDS or len(text.text) > MAX_HEADING_CHARS
                or text.text.rstrip().endswith((".", ",", ":", ";", "?", "!"))):
            continue
        level, heading = heading_style[text.style]
        issues.append(Issue(
            CHECK_ID, "heading_tagged_as_paragraph",
            f'"{text.text}" is drawn like a heading (the same {text.size:g} pt {text.font} '
            f'style as the {level} "{heading.text}") but is tagged as a paragraph (P), so '
            "screen-reader heading navigation skips it.",
            evaluation_result="needs_review", page=elem.page, object_ref=elem.ref,
            suggestion=f"If it is a heading, tag it as {level} (like the other headings in "
                       "this style); if not, give it a body-text style.",
            sources=["pikepdf"]))
        if len(issues) >= MAX_HEADING_STYLE_ISSUES:
            break
    return issues


def _same_issue(rule: RuleFailure, by_type: dict[str, Issue]) -> Issue | None:
    text = rule.description.lower()
    if rule.clause == "7.5" or rule.clause.startswith("7.5."):
        return by_type.get("table_missing_headers")
    if "marked" in text and "document_not_marked" in by_type:
        return by_type["document_not_marked"]
    return by_type.get("missing_document_structure")


def check(ctx: CheckContext) -> list[Issue]:
    issues = [i for i in ctx.tag_issues if i.check_id == CHECK_ID]
    by_type = {i.issue_type: i for i in issues}
    styled_headings = _heading_tagged_as_paragraph(ctx)
    rules = ctx.verapdf.matching("7.5") + ctx.verapdf.matching("7.1", *_TAGGING_WORDS)
    added = 0
    for rule in rules:
        same = _same_issue(rule, by_type)
        if same is not None:
            cite_rule(same, rule)
            continue
        is_table = rule.clause == "7.5" or rule.clause.startswith("7.5.")
        pages: list[int | None] = list(rule.pages) or [None]
        for page in pages:
            if added >= MAX_RULE_ISSUES:
                break
            added += 1
            issues.append(Issue(
                CHECK_ID, "table_pdfua_rule_failed" if is_table else "structure_pdfua_rule_failed",
                f"veraPDF reported PDF/UA-1 rule {rule.rule_id}: {rule.description}",
                evaluation_result="needs_review", page=page,
                object_ref=f"PDF/UA-1 {rule.rule_id}",
                suggestion="Review the document tags: tag real content in reading order, mark "
                           "decorative content as artifacts, and give tables header cells.",
                sources=["veraPDF"]))
    suggestions = {
        "missing_document_structure": (
            'Add document tags in logical reading order, including headings, '
            'paragraphs and tables.'
        ),
        "document_not_marked": "Verify the existing tags, then set MarkInfo/Marked to true.",
        "malformed_structure": "Repair broken parent/child tag relationships and verify the reading order.",
        "table_missing_headers": (
            'If the first row contains column labels, mark its cells as TH '
            'header cells and set Scope to Column; verify row headers '
            'separately.'
        ),
        "table_pdfua_rule_failed": (
            'Review table tags: use Table, TR, TH and TD, and associate data '
            'cells with the correct headers.'
        ),
    }
    for issue in issues:
        if issue.issue_type == "heading_tagged_as_paragraph":
            continue
        issue.suggested_text = suggestions.get(issue.issue_type,
            (
                'Review the document tags and reading order; tag meaningful '
                'content and mark decorative content as artifacts.'
            ))
        add_advice(issue, issue.suggested_text)
        issue.suggestion_source = "rule"
    for issue in styled_headings:  # the concrete fix: the heading tag to use
        issue.suggested_text = (issue.suggestion or "").split("tag it as ", 1)[-1].split(" ", 1)[0]
        issue.suggestion_source = "rule"
    return issues + styled_headings
