# Pod test set (from Team 3)

These PDFs were made by Team 3 for our pod and shared with us unchanged. Each
`wcag-*.pdf` has one intended accessibility issue (the WCAG 2.1 success criterion is in
the file name); `ocr-unreadable-scan.pdf` is a simulated faded scan with no text layer.
The other files Team 3 shared (`goodAccessible.pdf`, `accessibilityIssues.pdf`,
`NonPDF.docx`, `encrypted.pdf`, `passwordprotected.pdf`, `BiggerThan20MB.pdf`) are
copies of the shared set already in `tester/fixtures/`, so they are not repeated here.

| File | Intended issue (Team 3's description) | Our expected finding | Test |
|---|---|---|---|
| wcag-1.1.1-missing-alt.pdf | The route map Figure has no /Alt and the text does not describe the route | CHK-NONTEXT, human_review | T-26 |
| wcag-1.3.1-heading-tagged-as-paragraph.pdf | "Weekday hours" is H2; "Weekend hours" looks the same but is tagged P | CHK-STRUCTURE, human_review | T-27 |
| wcag-1.3.3-location-only-instruction.pdf | "Choose from the list on the right" never names the wing | CHK-SENSORY, human_review | T-28 |
| wcag-1.4.1-color-only-status.pdf | Key maps navy to confirmed and maroon to pending; rows have no text status | CHK-COLOR, human_review | T-29 |
| wcag-2.4.2-missing-title.pdf | No Info or XMP title | CHK-TITLE, auto_fixable | T-30 |
| wcag-2.4.4-ambiguous-link-purpose.pdf | "Click here" link that names neither service | CHK-LINK, human_review | T-31 |
| wcag-2.4.6-vague-heading.pdf | H2 "Miscellaneous" for a section about lost badges | CHK-HEADINGS, human_review | T-32 |
| wcag-3.1.1-missing-language.pdf | No /Lang in the catalog and no override in the tags | CHK-LANG, auto_fixable | T-33 |
| ocr-unreadable-scan.pdf | No text layer; OCR would give no usable text | 422 `NO_TEXT_LAYER` (we do not run OCR) | T-34 |
