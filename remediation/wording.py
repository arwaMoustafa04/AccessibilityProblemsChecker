"""CHK-COLOR and CHK-SENSORY: AI-rewritten instructions (suggestions only).

These checks are human_review and the PDF's visible text is never edited, so this is
not a registered repair and produces no Repair record. The checks already attach a
rule-based draft as suggested_text ("Select the [button label]."); when an LLM is
available, suggest_rewrites() replaces it with a rewritten sentence
(suggestion_source "llm") that the author can copy.

The pipeline calls it after every real repair, inside the same per-PDF LLM budget,
so title, alt-text and link-label repairs get the model first. At most
MAX_AI_REWRITES sentences per document are sent.
"""

from __future__ import annotations

from checks.base import Issue
from remediation import RepairContext, ai

MAX_AI_REWRITES = 3
_PROBLEMS = {"CHK-COLOR": "color", "CHK-SENSORY": "sensory"}


def suggest_rewrites(issues: list[Issue], rctx: RepairContext) -> int:
    """Set AI rewrites as suggested_text on flagged sentences; returns how many were set."""
    if not ai.available():
        return 0
    wanted = [i for i in issues if i.check_id in _PROBLEMS and i.evidence][:MAX_AI_REWRITES]
    if wanted and ai.sends_data():
        rctx.note("CHK-COLOR/CHK-SENSORY: flagged sentences were sent to the configured external "
                  "model provider for suggested rewrites. Rewrites are suggestions only and "
                  "are not written into the PDF.")
    done = 0
    for issue in wanted:
        text = ai.rewrite_sentence(issue.evidence or "", _PROBLEMS[issue.check_id])
        if text:
            issue.suggested_text, issue.suggestion_source = text, "llm"
            done += 1
    return done
