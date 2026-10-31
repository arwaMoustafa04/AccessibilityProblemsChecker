"""CHK-SENSORY / WCAG 1.3.3: flag instructions for contextual human review."""

import re

from checks.base import CheckContext, Issue
from checks.review_text import ACTION, COLOR_WORD, blocks, excerpt

CHECK_ID = "CHK-SENSORY"
SENSORY = re.compile(
    r"\b(?:round|square|triangular|circular|large|small|big|little|upper|lower|"
    r"left|right|above|below|top|bottom|beep|tone|sound|arrow)\b", re.I,
)


def check(ctx: CheckContext) -> list[Issue]:
    issues = []
    for page, index, text in blocks(ctx):
        if ACTION.search(text) and (SENSORY.search(text) or COLOR_WORD.search(text)):
            issues.append(Issue(
                CHECK_ID, "sensory_instruction_needs_review",
                f'Instruction may rely on a sensory cue: "{excerpt(text)}". '
                "A label or other context may already provide an alternative; verify it manually.",
                evaluation_result="needs_review", page=page,
                object_ref=f"Page[{page}]/TextBlock[{index}]",
                suggestion="Identify the control or content by a meaningful name as well as its "
                           "color, shape, size, position or sound.",
                sources=["PyMuPDF"],
            ))
    return issues
