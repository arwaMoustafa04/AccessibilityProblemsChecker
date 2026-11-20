# remediation/: automatic repairs (Phase 5)

The pipeline (`pipeline.py`) runs the checks, then calls every registered repair on a
copy of the PDF, saves it, and runs **all checks again** on the result. You only write
the repair; re-validation, statuses, `repairs[]`, the report and the limitations are
handled for you.

## Adding a repair

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

## Getting AI text (remediation/ai.py)

Call these from your repair or check; each returns cleaned text, or None (then use
your rule-based text). They never raise.

| Function | For | Returns |
|---|---|---|
| `ai.suggest_title(page_text, file_name)` | CHK-TITLE | a title (used by title.py) |
| `ai.describe_image(image_bytes, nearby_text, mime_type)` | CHK-NONTEXT | alt text, or `ai.DECORATIVE` (then mark the image as an artifact instead) |
| `ai.suggest_link_text(sentence, url)` | CHK-LINK | 2-8 words of link text |
| `ai.rewrite_sentence(sentence, "color" or "sensory")` | CHK-COLOR, CHK-SENSORY | a rewritten sentence (suggestion only: put it in `Issue.suggested_text` with `suggestion_source="llm"`) |

`describe_image` accepts PNG, JPEG, WebP and GIF up to 4 MB; convert other images
(e.g. with PyMuPDF: `pymupdf.Pixmap(doc, xref).tobytes("png")`) first.

- Behind these is `llm.py` (settings at its top): no `LLM_API_KEY` means every call
  returns None, so tests and CI never need an LLM. `LLM_MOCK=true` gives fixed fake
  answers for trying your code without a key.
- Each uploaded PDF gets at most 8 model calls and 25 s of model time; after that the
  functions return None. Ask for the most important items first (e.g. the first images).
- For tests, put a fake module in `sys.modules["llm"]` (see `test_remediation.py`) or
  fake the HTTP call (see `test_llm.py`).


`nontext.py` now registers image repairs for missing/generic Figure alternatives
and untagged page images. It writes AI-labeled alt text, or isolates decorative
content as an artifact, while retaining human-review status. The cap is
`MAX_IMAGES_PER_PDF = 8`, with pixel/byte bounds before AI submission. Ambiguous
associations and unsafe content scopes remain manual; see the root README.
