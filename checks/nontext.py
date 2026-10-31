"""CHK-NONTEXT: WCAG 1.1.1 Non-text Content (human_review).

The detection is Person 1's tag/image inspector in pdf_checks.py: Figure /Alt
descriptions and images drawn in page content, nested Form XObjects and inline
images. Missing Figure alternatives are ``fail``; images without a resolvable
alternative are ``needs_review``.
"""

from __future__ import annotations

from checks.base import CheckContext, Issue

CHECK_ID = "CHK-NONTEXT"


def check(ctx: CheckContext) -> list[Issue]:
    return [i for i in ctx.tag_issues if i.check_id == CHECK_ID]
