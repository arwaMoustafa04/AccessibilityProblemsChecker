"""Automatic repairs behind POST /process (Phase 5, the REPAIRED stage).

HOW TO ADD A REPAIR (teammates): write ``remediation/<name>.py`` with a function
decorated with ``@repairer("CHK-XXX", "issue_type", ...)``. It receives the Issue
and a RepairContext, changes ``rctx.pdf`` (a copy of the upload, never the
original) and returns a RepairAction saying what it did, or None if it could not
fix this issue. Then import the module at the bottom of this file. See title.py
and lang.py.

- Use ``rctx.check`` (the CheckContext the checks used) to read the original
  document: ``rctx.check.doc`` (PyMuPDF text, images) and ``rctx.check.pdf``.
- AI text: set ``method="llm"`` on the RepairAction, and put the written text in
  ``applied_text``. Get it through remediation/ai.py, which falls back cleanly when
  no LLM is available.
- After every repair the pipeline re-runs all checks on the repaired PDF. A repair
  passes re-validation when its issue (same type, same place) is gone.
- auto_fixable findings become "fixed" or "repair_failed". For human_review
  findings (e.g. AI-drafted alt text) the repair is recorded, but the finding stays
  "needs_human_review": a person must still verify it (spec v0.5.0).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pikepdf

from checks.base import CheckContext, Issue

log = logging.getLogger("pdf_accessibility.remediation")


@dataclass
class RepairAction:
    """What one repair did (becomes one Repair in the response)."""

    action: str  # plain-words description, e.g. 'Set document language to "en-US"'
    applied_text: str | None = None  # the text written into the PDF, if any
    method: Literal["rule", "llm"] = "rule"  # "llm" when applied_text came from an LLM


@dataclass
class RepairContext:
    pdf: pikepdf.Pdf  # the copy being repaired (saved as output_pdf)
    check: CheckContext  # the original document, as the checks saw it
    file_name: str
    # Values shared between repairs of one document (e.g. the chosen title), so
    # several issues about the same thing are fixed consistently and computed once.
    shared: dict[str, object] = field(default_factory=dict)
    # Notes for EvaluationResult.limitations (e.g. "LLM unavailable, used fallback").
    notes: list[str] = field(default_factory=list)
    llm_used: bool = False
    content_refs: dict[str, str] = field(default_factory=dict)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


Repairer = Callable[[Issue, RepairContext], RepairAction | None]

# (check_id, issue_type) -> repair function
REPAIRERS: dict[tuple[str, str], Repairer] = {}


def repairer(check_id: str, *issue_types: str) -> Callable[[Repairer], Repairer]:
    """Register a repair function for one or more issue types of a check."""
    def register(fn: Repairer) -> Repairer:
        for issue_type in issue_types:
            REPAIRERS[(check_id, issue_type)] = fn
        return fn
    return register


def can_repair(issue: Issue) -> bool:
    return (issue.check_id, issue.issue_type) in REPAIRERS


def apply_repairs(issues: list[Issue], rctx: RepairContext) -> dict[tuple, RepairAction]:
    """Run the registered repair for each issue; return Issue.key -> RepairAction.

    A repair that crashes is skipped (its issue stays unrepaired) and noted in
    limitations, instead of failing the whole request.
    """
    done: dict[tuple, RepairAction] = {}
    for issue in issues:
        fn = REPAIRERS.get((issue.check_id, issue.issue_type))
        if fn is None or issue.key in done:
            continue
        try:
            action = fn(issue, rctx)
        except Exception as exc:  # one broken repair must not lose the others
            log.exception("repair crashed check_id=%s issue_type=%s",
                          issue.check_id, issue.issue_type)
            rctx.note(f"The automatic repair for {issue.check_id} ({issue.issue_type}) "
                      f"could not be completed ({type(exc).__name__}); that issue was "
                      "not repaired.")
            continue
        if action is not None:
            done[issue.key] = action
            rctx.llm_used = rctx.llm_used or action.method == "llm"
    return done


# Registered repairs (importing a module registers its @repairer functions).
from remediation import lang, link, nontext, title  # noqa: E402,F401

__all__ = ["REPAIRERS", "RepairAction", "RepairContext", "apply_repairs", "can_repair",
           "repairer"]
