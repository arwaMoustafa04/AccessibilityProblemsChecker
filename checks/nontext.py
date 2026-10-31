"""CHK-NONTEXT: WCAG 1.1.1 Non-text Content (human_review).

The detection is Person 1's tag/image inspector in pdf_checks.py: Figure /Alt
descriptions and images drawn in page content, nested Form XObjects and inline
images. Missing Figure alternatives are ``fail``; images without a resolvable
alternative are ``needs_review``.

veraPDF (PDF/UA-1 clause 7.3, graphics) confirms those findings, and any figure
rule it fails that the inspector did not report is added for review.
"""

from __future__ import annotations

from checks.base import CheckContext, Issue
from checks.verapdf import cite_rule

CHECK_ID = "CHK-NONTEXT"
MAX_RULE_ISSUES = 20


def check(ctx: CheckContext) -> list[Issue]:
    issues = [i for i in ctx.tag_issues if i.check_id == CHECK_ID]
    by_type = {i.issue_type: i for i in issues}
    added = 0
    for rule in ctx.verapdf.matching("7.3"):
        same = by_type.get("missing_figure_alt") or by_type.get("image_without_text_alternative")
        if same is not None:
            cite_rule(same, rule)
            continue
        pages: list[int | None] = list(rule.pages) or [None]
        for page in pages:
            if added >= MAX_RULE_ISSUES:
                break
            added += 1
            issues.append(Issue(
                CHECK_ID, "figure_pdfua_rule_failed",
                f"veraPDF reported PDF/UA-1 rule {rule.rule_id}: {rule.description}",
                evaluation_result="needs_review", page=page,
                object_ref=f"PDF/UA-1 {rule.rule_id}",
                suggestion="Give each meaningful image an alternative description, or mark "
                           "decorative images as artifacts.",
                sources=["veraPDF"]))
    return issues
