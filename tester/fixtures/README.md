# Shared test set

Files made by Team 1 with known properties. Each one's expected result (the test
oracle) is fixed here and checked by the tester (`tester/suite.py`).

| File | Built-in property | Expected `/process` result | Tests |
|---|---|---|---|
| `goodAccessible.pdf` | Tagged, title, `en-US` language, DisplayDocTitle, alt text | 200; no CHK-TITLE/CHK-LANG findings; no repairs; no compliance claim | T-03, T-05 |
| `accessibilityIssues.pdf` | 7 known issues (below) | 200, contract-conforming result | T-04 |
| `NonPDF.docx` | Word document, not a PDF | 415 `INVALID_FILE_TYPE` | T-06 |
| `encrypted.pdf` | Opens without a password; printing/copying/editing locked | 422 `ENCRYPTED_PDF` | T-09 |
| `passwordProtected.pdf` | Needs password `test1234` to open | 422 `PASSWORD_PROTECTED_PDF` | T-10 |

`accessibilityIssues.pdf` issues and expected findings once checks exist:

| Issue | WCAG | Agreed check | Classification | Tests |
|---|---|---|---|---|
| No tags / structure tree | 1.3.1 | CHK-STRUCTURE | human_review | T-13 (Phase 4) |
| Table without header cells | 1.3.1 | CHK-STRUCTURE | human_review | T-13 (Phase 4) |
| No document language | 3.1.1 | CHK-LANG | auto_fixable → fixed | T-13 (Phase 4), T-14 (Phase 5) |
| Empty document title | 2.4.2 | CHK-TITLE | auto_fixable → fixed | T-13 (Phase 4), T-14 (Phase 5) |
| Image without alt text | 1.1.1 | CHK-NONTEXT | human_review | T-13 (Phase 4) |
| "Click here" link | 2.4.4 | CHK-LINK | human_review | T-13 (Phase 4) |
| Low-contrast text (~1.6:1) | 1.4.3 | — not one of the 8 agreed checks | not evaluated | — |

Focused detection PDFs (Phase 4). Issue type names differ between teams, so these
tests check the check_id, classification (human_review findings stay
`needs_human_review`; auto_fixable ones are `detected` or `fixed`), a location
description, the page, and that human-review findings are in `human_review_items`:

| File | Built-in issues | Expected findings | Test |
|---|---|---|---|
| `pdf_checks/combined.pdf` | Figure without Alt; table without TH cells | CHK-NONTEXT and CHK-STRUCTURE on page 1, human_review | T-15 |
| `pdf_checks/inline_image.pdf` | Inline image with no text alternative | CHK-NONTEXT on page 1, human_review | T-16 |
| `person2/combined_review.pdf` | Sensory instruction, color-only cue, generic link (page 2) | CHK-SENSORY, CHK-COLOR, CHK-LINK on page 2, human_review | T-17 |
| `person2/link_empty.pdf` | Link with no label | CHK-LINK on page 1, human_review | T-18 |
| generated in `suite.py` (`tagged_problems_pdf`) | Title "Untitled"; `/Lang` "en_US"; headings H2, H4, empty H3; form field without /TU | CHK-TITLE and CHK-LANG auto_fixable; CHK-HEADINGS human_review | T-19 |
| `accessibilityIssues.pdf` with `output=zip` | — | 200 zip: `original.pdf` identical to the upload, output PDF, report PDF, `result.json` matching | T-20 |
| `goodAccessible.pdf` with `output=xml` | — | 400 `INVALID_REQUEST` | T-21 |

Pod test set from Team 3 (`pod/`, see `pod/README.md`; Phase 5). Each file has one
intended issue; the tests require that check with that classification (other findings
are allowed, since the pod has not agreed that each file must produce only one):

| File | Intended issue | Expected finding | Test |
|---|---|---|---|
| `pod/wcag-1.1.1-missing-alt.pdf` | Route map Figure without /Alt | CHK-NONTEXT, human_review | T-26 |
| `pod/wcag-1.3.1-heading-tagged-as-paragraph.pdf` | "Weekend hours" styled like the H2 above it but tagged P | CHK-STRUCTURE, human_review | T-27 |
| `pod/wcag-1.3.3-location-only-instruction.pdf` | "choose from the list on the right" | CHK-SENSORY, human_review | T-28 |
| `pod/wcag-1.4.1-color-only-status.pdf` | Booking status shown only by navy/maroon text | CHK-COLOR, human_review | T-29 |
| `pod/wcag-2.4.2-missing-title.pdf` | No Info or XMP title | CHK-TITLE, auto_fixable | T-30 |
| `pod/wcag-2.4.4-ambiguous-link-purpose.pdf` | "Click here" link | CHK-LINK, human_review | T-31 |
| `pod/wcag-2.4.6-vague-heading.pdf` | H2 "Miscellaneous" | CHK-HEADINGS, human_review | T-32 |
| `pod/wcag-3.1.1-missing-language.pdf` | No /Lang in the catalog or tags | CHK-LANG, auto_fixable | T-33 |
| `pod/ocr-unreadable-scan.pdf` | Faded scan, no text layer | 422 `NO_TEXT_LAYER` | T-34 |

`person2/` holds copies of Person 2's fixtures from `test_fixtures/person2/`
(see that folder's README for how they were made); `pdf_checks/` is Person 1's set.

Generated in code instead of stored as files: no file at all (T-07), a corrupted PDF
(T-08), and the 20 MB boundary at exactly 20,971,521 bytes (T-11, rejected) and
20,971,520 bytes (T-12, accepted).

## Implemented image and structure checks

Focused, reproducible fixtures and exact expected results are in
[`pdf_checks/README.md`](pdf_checks/README.md). Existing shared PDFs are unchanged.
With default settings, `goodAccessible.pdf` produces no findings from these two
checks; `accessibilityIssues.pdf` produces `missing_document_structure` and
`image_without_text_alternative` (page 1). Its visually drawn, untagged table is
not inferred as a separate table finding. These observations do not establish
accessibility or cover the other six catalog checks.
