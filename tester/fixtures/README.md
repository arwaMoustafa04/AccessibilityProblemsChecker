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
