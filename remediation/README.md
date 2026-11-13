# remediation/: automatic repairs (Phase 5)

The pipeline (`pipeline.py`) runs the checks, then calls every registered repair on a
copy of the PDF, saves it, and runs **all checks again** on the result. You only write
the repair; re-validation, statuses, `repairs[]`, the report and the limitations are
handled for you.

## Adding a repair (Person 1: alt text; Person 2: link labels)

1. Create `remediation/<name>.py`:

   ```python
   from checks.base import Issue
   from remediation import RepairAction, RepairContext, repairer

   @repairer("CHK-NONTEXT", "missing_figure_alt", "generic_figure_alt")
   def write_alt_text(issue: Issue, rctx: RepairContext) -> RepairAction | None:
       elem = ...  # find the Figure in rctx.pdf from issue.object_ref / issue.page
       text = ...  # AI draft through remediation/ai.py (add a function there), else None
       if not text:
           return None  # nothing written: the finding is simply not repaired
       elem.Alt = pikepdf.String(text)
       return RepairAction(f'Wrote AI-drafted alt text to {issue.object_ref}; '
                           "AI-generated, please verify",
                           applied_text=text, method="llm")
   ```

2. Import it at the bottom of `remediation/__init__.py`:
   `from remediation import lang, nontext, title  # noqa: E402,F401`

3. Add tests to `test_remediation.py`.

Rules:

- Change only `rctx.pdf` (the copy). Read the original document from `rctx.check`
  (`rctx.check.doc` is PyMuPDF, `rctx.check.pdf` is pikepdf).
- Return `None` when you cannot fix the issue; never raise on purpose. If a repair does
  crash, the pipeline skips it and notes it in `limitations`.
- Values several repairs need once per document can be cached in `rctx.shared`.
- Notes for `limitations` (e.g. "AI unavailable, used the template text") go through
  `rctx.note("...")`.
- For a **human_review** check (NONTEXT, LINK), the repair is recorded in `repairs[]`,
  but the finding stays `needs_human_review` and is not counted as fixed (spec v0.5.0).
  Its `validation_result` says whether the text was written correctly (the issue is
  gone on re-check), not whether the text is accurate.
- Never rewrite visible page text (CHK-COLOR / CHK-SENSORY are suggestions only:
  set `Issue.suggested_text` and `suggestion_source` in the check instead).

## The AI hook (Person 4: llm.py)

Every LLM call goes through `remediation/ai.py`, which imports a top-level `llm.py`
module if it exists. `llm.py` should provide, for now:

```python
def suggest_title(page_text: str, file_name: str) -> str | None:
    """A short descriptive title for a document whose first page reads `page_text`."""
```

Each function returns plain text, or None. It may raise; `ai.py` catches every
exception, logs it, and the caller uses its rule-based fallback, so an LLM problem never
fails a request. `ai.py` also cleans the answer (one line, no quotes or "Title:" prefix,
3-120 characters). Add new functions to `llm.py` (e.g. `describe_image`,
`suggest_link_text`) and a matching wrapper in `ai.py` the same way.

- Until `llm.py` exists, or with `LLM_ENABLED=false`, every AI call returns None and
  the rule-based fallbacks are used, so tests and CI never need an LLM.
- Batching (one call per PDF), caching by file hash, retries, timeouts and rate limits
  belong inside `llm.py`; LLM time counts toward the 60 s per-request limit.
