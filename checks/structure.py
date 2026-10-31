"""CHK-STRUCTURE: WCAG 1.3.1 Info and Relationships (human_review).

The detection is Person 1's tag inspector in pdf_checks.py: a nonempty structure
tree, the tagged-document marker, malformed relationships, and tagged tables with
data cells but no headers. Missing/empty structure is ``fail``; the rest is
``needs_review``.
"""

from __future__ import annotations

from checks.base import CheckContext, Issue

CHECK_ID = "CHK-STRUCTURE"


def check(ctx: CheckContext) -> list[Issue]:
    return [i for i in ctx.tag_issues if i.check_id == CHECK_ID]
