"""CHK-COLOR / WCAG 1.4.1. Review color cues; this is not a contrast checker."""

import re

from checks.base import CheckContext, Issue
from checks.review_text import ACTION, COLOR_WORD, blocks, excerpt

CHECK_ID = "CHK-COLOR"
MEANING = re.compile(
    r"\b(?:indicat\w*|denot\w*|represent\w*|mean\w*|mark\w*|highlight\w*|"
    r"required|mandatory|error\w*|correct|incorrect|status|legend|key|shown|"
    r"positive|negative|pass|fail|available|unavailable)\b", re.I,
)


def _chromatic(rgb) -> bool:
    return rgb is not None and len(rgb) >= 3 and max(rgb[:3]) - min(rgb[:3]) > 0.08


def check(ctx: CheckContext) -> list[Issue]:
    issues = []
    for page_number, index, text in blocks(ctx):
        if COLOR_WORD.search(text) and (ACTION.search(text) or MEANING.search(text)):
            issues.append(Issue(
                CHECK_ID, "color_cue_needs_review",
                f'Color may convey information in "{excerpt(text)}". '
                "Check whether labels, symbols or patterns convey the same information.",
                evaluation_result="needs_review", page=page_number,
                object_ref=f"Page[{page_number}]/TextBlock[{index}]",
                suggestion="Provide a non-color cue for each status, instruction or category.",
                sources=["PyMuPDF"],
            ))
    # Colored text alone is not a failure. Multiple chromatic drawing colors can
    # indicate a chart/legend but can also be decorative: always needs_review.
    for page_index in range(len(ctx.doc)):
        page = ctx.doc[page_index]
        colors = {
            tuple(round(c, 2) for c in rgb[:3])
            for drawing in page.get_drawings()
            for rgb in (drawing.get("fill"), drawing.get("color"))
            if _chromatic(rgb)
        }
        if len(colors) >= 2:
            issues.append(Issue(
                CHECK_ID, "multicolor_graphic_needs_review",
                "Multiple colors occur in vector graphics. Determine whether they encode "
                "information and whether equivalent labels or patterns are present; "
                "decorative color is not a violation.",
                evaluation_result="needs_review", page=page.number + 1,
                object_ref=f"Page[{page.number + 1}]/Drawings",
                suggestion="Label data directly or use patterns in addition to color.",
                sources=["PyMuPDF"],
            ))
    return issues
