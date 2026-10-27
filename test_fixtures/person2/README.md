# Person 2: sensory, color and link checks

These fixtures exercise **review triggers**, not complete WCAG conformance.
Even the negative controls are not certified accessible PDFs. They deliberately
isolate Person 2's checks; other check owners may legitimately report other issues.

## Scope and contract

Phase 2 REQ-03 through REQ-06 and REQ-10 require detecting, locating, classifying
and preserving issues needing human judgment. Phase 3 established `/process`
and snake_case response fields. This work uses Person 3's `Arwa/phase4` registry,
models and pipeline without changing their contract. Person 1 is left untouched.

| Check | Criterion | Detection |
|---|---|---|
| CHK-SENSORY | 1.3.3, A | English action words with position, shape, size, color or sound cues in the same text block |
| CHK-COLOR | 1.4.1, A | English color words with instruction/status cues, or two or more chromatic colors in vector graphics on a page |
| CHK-LINK | 2.4.4, A | Missing, generic or address-only link labels; unreadable annotation rectangles |

All resulting findings have `evaluation_result: needs_review`,
`classification: human_review`, and `status: needs_human_review`. They carry a
1-based page number, object reference, explanation and suggested human action.
The pipeline includes their IDs in `human_review_items`, updates summary counts,
and prints explanations in the report PDF. The uploaded PDF is returned unchanged
when repairs are disabled; these checks never repair anything, even in repair mode.

## Library integration

- **PyMuPDF** supplies extracted text, vector drawings and visible link labels.
- **pikepdf** supplies link annotations and tagged alternative text. The common
  pipeline also uses it for PDF validation and safe object access.
- **veraPDF** supplies PDF/UA-1 link rule failures (clause 7.18.5), with one review
  finding per rule/page. Its report is cached by `CheckContext` and reused by
  title/language/headings, so the executable runs at most once per evaluation.
  Generic annotation rules are not attributed to links. PDF/UA rule failures
  are supporting evidence, not automatic WCAG 2.4.4 verdicts. Semantic sensory
  meaning and color-only information cannot be certified by these machine rules.

Install veraPDF using the project's deployment instructions or set
`VERAPDF_PATH` to your local executable. `VERAPDF_ENABLED=false` disables it;
missing tools, timeouts and unreadable reports retain the local detectors and
are disclosed in response limitations. Unit tests use controlled XML/command
results, including exit code 1 (noncompliance); they do not require a Java install.

## Fixed fixture expectations (local heuristics, veraPDF disabled)

| PDF | Expected issue types |
|---|---|
| sensory_review.pdf | sensory_instruction_needs_review |
| sensory_named_control.pdf | none for CHK-SENSORY |
| color_review.pdf | color_cue_needs_review; multicolor_graphic_needs_review |
| color_text_alternative.pdf | none for CHK-COLOR |
| link_generic.pdf | link_purpose_unclear |
| link_descriptive.pdf | none for CHK-LINK |
| link_empty.pdf | link_label_missing |
| combined_review.pdf | all three checks produce review findings on page 2 |

## Run locally

From the repository root, after installing `requirements-dev.txt`:

```sh
VERAPDF_ENABLED=false python -m pytest test_person2_checks.py -v
python -m pytest -q
python -m test_fixtures.person2.generate
uvicorn main:app --port 8000
```

The generator rebuilds the eight committed PDFs; no external services are used.
In a second terminal:

```sh
curl -sS -F 'file=@test_fixtures/person2/combined_review.pdf' \
  http://localhost:8000/process > result.json
```

Or open `/docs`, expand POST `/process`, and upload `combined_review.pdf`.
These PDFs can also be submitted to either team's base URL plus `/process`.
The existing tester's T-13 expects all eight checks and must remain skipped until
Person 1's implementation is integrated; this contribution does not claim 8/8.

## Important limitations

- Text rules are English heuristics. No OCR, language understanding or raster
  image/color analysis is performed. Vector color detection may flag decoration.
- An instruction with a sensory cue can be valid when it also names a control.
  It is a review candidate, not an automatic WCAG failure.
- CHK-COLOR concerns **color as the sole means of information**, not contrast
  ratios (1.4.3). Colored text by itself is not labelled a failure.
- Link labels come from explicit Link structure `/Alt` or `/ActualText` tied to
  an annotation through OBJR, annotation descriptions, or visible text inside
  the annotation rectangle. Arbitrary nearby text is not assumed to be
  programmatically associated. Nested/complex tagging, image-only links and
  meaningfulness of descriptive text still require manual review.
- Link targets are never fetched. Generic text can be acceptable in context;
  address-only labels can also be meaningful. Both require human judgment.
- No findings means no implemented heuristic matched, not that the PDF passed
  all of WCAG. The response limitations and fixed non-certification statement
  remain in place. All pages are inspected; no silent 300-page cutoff is used.

## References used to define review behavior

- https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFUA-Part-1-rules
- https://www.w3.org/WAI/WCAG21/Understanding/sensory-characteristics.html
- https://www.w3.org/WAI/WCAG21/Understanding/use-of-color.html
- https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html
