// The 8 agreed checks, copied from catalog.py (same as GET /checks).
// Used only for display names. Later this can be loaded from GET /checks instead.
export const CHECKS = [
  { check_id: 'CHK-NONTEXT', name: 'Non-text Content', wcag_criterion: '1.1.1', wcag_level: 'A', classification: 'human_review' },
  { check_id: 'CHK-STRUCTURE', name: 'Info and Relationships', wcag_criterion: '1.3.1', wcag_level: 'A', classification: 'human_review' },
  { check_id: 'CHK-SENSORY', name: 'Sensory Characteristics', wcag_criterion: '1.3.3', wcag_level: 'A', classification: 'human_review' },
  { check_id: 'CHK-COLOR', name: 'Use of Color', wcag_criterion: '1.4.1', wcag_level: 'A', classification: 'human_review' },
  { check_id: 'CHK-TITLE', name: 'Page Titled', wcag_criterion: '2.4.2', wcag_level: 'A', classification: 'auto_fixable' },
  { check_id: 'CHK-LINK', name: 'Link Purpose (In Context)', wcag_criterion: '2.4.4', wcag_level: 'A', classification: 'human_review' },
  { check_id: 'CHK-HEADINGS', name: 'Headings and Labels', wcag_criterion: '2.4.6', wcag_level: 'AA', classification: 'human_review' },
  { check_id: 'CHK-LANG', name: 'Language of Page', wcag_criterion: '3.1.1', wcag_level: 'A', classification: 'auto_fixable' },
]

export const CHECKS_BY_ID = Object.fromEntries(CHECKS.map((c) => [c.check_id, c]))
