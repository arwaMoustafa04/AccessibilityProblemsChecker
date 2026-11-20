"""The accessibility checks behind POST /process.

HOW TO ADD A CHECK (teammates): write ``checks/<name>.py`` with a function
``check(ctx: CheckContext) -> list[Issue]`` and add one line to CHECK_FUNCTIONS
below. Use ``ctx.pdf`` (pikepdf), ``ctx.doc`` (PyMuPDF) and ``ctx.verapdf``
(veraPDF PDF/UA-1 results) as needed; see title.py, lang.py and headings.py.
Only detect: classification and WCAG data come from catalog.py automatically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from catalog import CHECKS
from checks import color, headings, lang, link, nontext, sensory, structure, title
from checks.base import CheckContext, Issue

log = logging.getLogger("pdf_accessibility.checks")

CheckFunction = Callable[[CheckContext], list[Issue]]

# check_id -> function. A check that is not listed here is reported as not performed.
CHECK_FUNCTIONS: dict[str, CheckFunction] = {
    "CHK-TITLE": title.check,
    "CHK-LANG": lang.check,
    "CHK-HEADINGS": headings.check,
    "CHK-NONTEXT": nontext.check,
    "CHK-STRUCTURE": structure.check,
    "CHK-SENSORY": sensory.check,
    "CHK-COLOR": color.check,
    "CHK-LINK": link.check,
}


@dataclass
class CheckRun:
    performed: list[str] = field(default_factory=list)  # in catalog order
    issues: list[Issue] = field(default_factory=list)
    not_implemented: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # check_id -> reason


def run_checks(ctx: CheckContext, functions: dict[str, CheckFunction] | None = None) -> CheckRun:
    """Run every registered check in catalog order. A check that crashes is reported
    as not performed (with the reason) instead of failing the whole request."""
    functions = CHECK_FUNCTIONS if functions is None else functions
    run = CheckRun()
    for spec in CHECKS:
        fn = functions.get(spec.check_id)
        if fn is None:
            run.not_implemented.append(spec.check_id)
            continue
        try:
            found = fn(ctx)
            wrong = {i.check_id for i in found} - {spec.check_id}
            if wrong:
                raise ValueError(f"returned issues for other checks: {sorted(wrong)}")
        except Exception as exc:  # one broken check must not hide the others' results
            log.exception("check crashed check_id=%s", spec.check_id)
            run.failed[spec.check_id] = f"{type(exc).__name__}: {exc}"[:200]
            continue
        run.performed.append(spec.check_id)
        run.issues.extend(found)
    return run


__all__ = ["CHECK_FUNCTIONS", "CheckContext", "CheckRun", "Issue", "run_checks"]
