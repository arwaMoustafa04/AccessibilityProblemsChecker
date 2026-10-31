"""CHK-STRUCTURE: WCAG 1.3.1 Info and Relationships (human_review).

The detection is Person 1's tag inspector in pdf_checks.py: a nonempty structure
tree, the tagged-document marker, malformed relationships, and tagged tables with
data cells but no headers. Missing/empty structure is ``fail``; the rest is
``needs_review``.

veraPDF (PDF/UA-1 clause 7.1 tagging rules and clause 7.5 tables) confirms those
findings, and any structure rule it fails that the inspector did not report is
added for review.
"""

from __future__ import annotations

from checks.base import CheckContext, Issue
from checks.verapdf import RuleFailure, cite_rule

CHECK_ID = "CHK-STRUCTURE"
MAX_RULE_ISSUES = 20
# 7.1 also holds title/metadata rules (CHK-TITLE); only its tagging rules belong here.
_TAGGING_WORDS = ("tagged", "artifact", "structtreeroot", "structure", "marked")


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
    return issues
