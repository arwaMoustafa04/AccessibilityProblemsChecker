// SAMPLE DATA ONLY, used by the dev preview bar (Results (sample)).
// Real POST /process output for "test set/accessibilityIssues.pdf", plus the CHK-SENSORY
// and CHK-COLOR findings from test_fixtures/person2/combined_review.pdf (renumbered),
// so every kind of finding appears. output_pdf / report_pdf are left out (null).
export const MOCK_RESULT = {
  "evaluation_id": "63286b3a-360e-4b0a-bb84-b34aa551dcb8",
  "status": "completed",
  "input": {
    "file_name": "accessibilityIssues.pdf",
    "sha256": "6de47fe270175071e15c4d9be3b50a220991872fe98c12d3dd03c3591a2138b0",
    "size_bytes": 5584
  },
  "outcome": "completed_no_repairs",
  "checks_performed": [
    "CHK-SENSORY",
    "CHK-COLOR",
    "CHK-TITLE",
    "CHK-LINK",
    "CHK-HEADINGS",
    "CHK-LANG"
  ],
  "findings": [
    {
      "finding_id": "F-1",
      "check_id": "CHK-TITLE",
      "issue_type": "missing_document_title",
      "wcag_criterion": "2.4.2",
      "wcag_level": "A",
      "location": {
        "page": null,
        "object_ref": "Info/Title, Metadata/dc:title",
        "description": "Document metadata"
      },
      "evaluation_result": "fail",
      "classification": "auto_fixable",
      "status": "detected",
      "fix_description": "Document title is missing (no Info /Title or XMP dc:title). Suggested fix: Set a title that describes the document's topic or purpose."
    },
    {
      "finding_id": "F-2",
      "check_id": "CHK-TITLE",
      "issue_type": "display_doc_title_not_set",
      "wcag_criterion": "2.4.2",
      "wcag_level": "A",
      "location": {
        "page": null,
        "object_ref": "Catalog/ViewerPreferences/DisplayDocTitle",
        "description": "Document viewer preferences"
      },
      "evaluation_result": "fail",
      "classification": "auto_fixable",
      "status": "detected",
      "fix_description": "Viewers are not told to show the document title (DisplayDocTitle is not true), so the file name is shown instead. Suggested fix: Set ViewerPreferences/DisplayDocTitle to true."
    },
    {
      "finding_id": "F-3",
      "check_id": "CHK-LINK",
      "issue_type": "link_purpose_unclear",
      "wcag_criterion": "2.4.4",
      "wcag_level": "A",
      "location": {
        "page": 1,
        "object_ref": "5 0 R",
        "description": "Page 1"
      },
      "evaluation_result": "needs_review",
      "classification": "human_review",
      "status": "needs_human_review",
      "fix_description": "Link label \"Click here\" is generic. Programmatically associated context may explain its purpose; check that context before deciding it fails. Suggested fix: Provide meaningful link text or a tagged alternative description that identifies its purpose, and verify the associated context."
    },
    {
      "finding_id": "F-4",
      "check_id": "CHK-HEADINGS",
      "issue_type": "headings_not_tagged",
      "wcag_criterion": "2.4.6",
      "wcag_level": "AA",
      "location": {
        "page": 1,
        "object_ref": null,
        "description": "Page 1"
      },
      "evaluation_result": "needs_review",
      "classification": "human_review",
      "status": "needs_human_review",
      "fix_description": "1 line(s) look like headings but are not tagged as headings, e.g. \"Campus Library Hours and Services\" (page 1). Suggested fix: Tag real headings as H1-H6 in order, and check that each one describes the section that follows."
    },
    {
      "finding_id": "F-5",
      "check_id": "CHK-LANG",
      "issue_type": "missing_document_language",
      "wcag_criterion": "3.1.1",
      "wcag_level": "A",
      "location": {
        "page": null,
        "object_ref": "Catalog/Lang",
        "description": "Document catalog (language)"
      },
      "evaluation_result": "fail",
      "classification": "auto_fixable",
      "status": "detected",
      "fix_description": "Document language is missing (no /Lang in the catalog); 1 page(s) contain text. Suggested fix: Set the document language, e.g. en-US, so screen readers use the right pronunciation."
    },
    {
      "finding_id": "F-6",
      "check_id": "CHK-SENSORY",
      "issue_type": "sensory_instruction_needs_review",
      "wcag_criterion": "1.3.3",
      "wcag_level": "A",
      "location": {
        "page": 2,
        "object_ref": "Page[2]/TextBlock[0]",
        "description": "Page 2"
      },
      "evaluation_result": "needs_review",
      "classification": "human_review",
      "status": "needs_human_review",
      "fix_description": "Instruction may rely on a sensory cue: \"Select the round button on the right. Errors are shown in red.\". A label or other context may already provide an alternative; verify it manually. Suggested fix: Identify the control or content by a meaningful name as well as its color, shape, size, position or sound."
    },
    {
      "finding_id": "F-7",
      "check_id": "CHK-COLOR",
      "issue_type": "color_cue_needs_review",
      "wcag_criterion": "1.4.1",
      "wcag_level": "A",
      "location": {
        "page": 2,
        "object_ref": "Page[2]/TextBlock[0]",
        "description": "Page 2"
      },
      "evaluation_result": "needs_review",
      "classification": "human_review",
      "status": "needs_human_review",
      "fix_description": "Color may convey information in \"Select the round button on the right. Errors are shown in red.\". Check whether labels, symbols or patterns convey the same information. Suggested fix: Provide a non-color cue for each status, instruction or category."
    },
    {
      "finding_id": "F-8",
      "check_id": "CHK-COLOR",
      "issue_type": "multicolor_graphic_needs_review",
      "wcag_criterion": "1.4.1",
      "wcag_level": "A",
      "location": {
        "page": 2,
        "object_ref": "Page[2]/Drawings",
        "description": "Page 2"
      },
      "evaluation_result": "needs_review",
      "classification": "human_review",
      "status": "needs_human_review",
      "fix_description": "Multiple colors occur in vector graphics. Determine whether they encode information and whether equivalent labels or patterns are present; decorative color is not a violation. Suggested fix: Label data directly or use patterns in addition to color."
    }
  ],
  "repairs": [],
  "new_issues_after_repair": [],
  "human_review_items": [
    "F-3",
    "F-4",
    "F-6",
    "F-7",
    "F-8"
  ],
  "summary": {
    "total_issues": 8,
    "fixed_count": 0,
    "human_review_count": 5
  },
  "limitations": [
    "Checks CHK-NONTEXT, CHK-STRUCTURE are not implemented yet and were not performed.",
    "PDF/UA-1 validation with veraPDF was not used (veraPDF is not installed on this server); checks used pikepdf and PyMuPDF only.",
    "Automatic repair is not enabled in this version (planned for Phase 5): auto-fixable findings are reported as detected and the PDF is returned unchanged.",
    "CHK-SENSORY and CHK-COLOR use English text cues; CHK-COLOR also flags multicolor vector graphics. No OCR or raster-image color analysis is performed. CHK-LINK inspects annotations and labels without visiting destinations. These heuristics can miss issues and flag acceptable content; no finding does not establish conformance. Human review of context is required.",
    "Human-review findings are never repaired automatically.",
    "Automated checks cannot confirm every WCAG 2.1 requirement; a person should review the document."
  ],
  "compliance_statement": "This report does not certify ADA Title II or WCAG 2.1 conformance.",
  "output_pdf": null,
  "report_pdf": null
}
