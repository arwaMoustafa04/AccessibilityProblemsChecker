# Model coverage: design requirements and tests (Phase 5)

The course testing interface asks a tester to report `coverage.model` when it tests
its own team's system: how many of the design requirements listed for the current
milestone the suite evaluated. Our tester reports it only for our own system
(`OWN_SYSTEM_URLS`, default `http://3.15.117.84/system`) and leaves it out of
cross-team reports.

- **Design version:** Phase 2 design (requirements REQ-01 to REQ-17), Phase 5 milestone subset.
- **total** = 11 requirements below; **covered** = those with at least
  one listed test that received a response from the system in that run.
- **Source of truth:** `MODEL_REQUIREMENTS` in `tester/suite.py`. `tester/test_tester.py`
  fails if this page and the code disagree, so update both together.

| Requirement | What it requires | Tests that evaluate it |
|---|---|---|
| REQ-02 | Reject unsupported input with a reason, including scanned PDFs | T-06, T-07, T-08, T-09, T-10, T-21, T-22 |
| REQ-06 | Never auto-fix issues that need human judgment | T-13, T-15, T-16, T-17, T-18, T-24 |
| REQ-07 | Automatically repair auto-fixable issues | T-14, T-25 |
| REQ-08 | Re-validate after repair | T-14, T-24, T-25 |
| REQ-09 | Report each repair's result and new issues | T-14, T-24 |
| REQ-10 | Keep human-review items unresolved, with enough information to locate and understand them | T-15, T-16, T-17, T-18, T-24 |
| REQ-11 | Produce the output PDF and the report PDF | T-03, T-04, T-20 |
| REQ-12 | Report lists checks, issues, repairs, review items and limitations | T-13, T-20, T-23 |
| REQ-13 | Tie findings, repairs and validation results to the exact PDF version | T-03, T-04, T-14, T-20 |
| REQ-16 | Never crash; always a result or an explicit error | T-08, T-11, T-12 |
| REQ-17 | Repair a copy, never the original | T-14, T-20 |

The tests themselves are described in the README (Tester section) and in
`tester/fixtures/README.md`.
