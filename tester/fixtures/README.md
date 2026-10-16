# Shared test set

Files made by Team 1 with known properties. Each one's expected result (the test
oracle) is fixed here and checked by the tester (`tester/suite.py`, T-12 to T-18).

| File | Built-in property | Expected `/process` result | Test |
|---|---|---|---|
| `goodAccessible.pdf` | Tagged, title, `en-US` language, DisplayDocTitle, alt text | 200; no CHK-TITLE/CHK-LANG findings; no repairs | T-12 |
| `accessibilityIssues.pdf` | 7 known issues (below) | 200, contract-conforming result (Phase 3) | T-13 |
| `NonPDF.docx` | Word document, not a PDF | 415 `INVALID_FILE_TYPE` | T-14 |
| `encrypted.pdf` | Opens without a password; printing/copying/editing locked | 422 `ENCRYPTED_PDF` | T-15 |
| `passwordProtected.pdf` | Needs password `test1234` to open | 422 `PASSWORD_PROTECTED_PDF` | T-16 |

`accessibilityIssues.pdf` issues and expected findings once checks exist:

| Issue | WCAG | Agreed check | Classification | Test |
|---|---|---|---|---|
| No tags / structure tree | 1.3.1 | CHK-STRUCTURE | human_review | T-17 (Phase 4) |
| Table without header cells | 1.3.1 | CHK-STRUCTURE | human_review | T-17 (Phase 4) |
| No document language | 3.1.1 | CHK-LANG | auto_fixable → fixed | T-17, T-18 (Phase 5) |
| Empty document title | 2.4.2 | CHK-TITLE | auto_fixable → fixed | T-17, T-18 (Phase 5) |
| Image without alt text | 1.1.1 | CHK-NONTEXT | human_review | T-17 (Phase 4) |
| "Click here" link | 2.4.4 | CHK-LINK | human_review | T-17 (Phase 4) |
| Low-contrast text (~1.6:1) | 1.4.3 | — not one of the 8 agreed checks | not evaluated | — |

The over-20 MB case is generated in code (exactly 20,971,521 bytes, T-10), together
with the exactly-20 MB boundary (T-11), instead of storing a large file in the repo.
