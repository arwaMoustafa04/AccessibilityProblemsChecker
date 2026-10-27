import { CHECKS_BY_ID } from '../data/checks.js'
import { CLASSIFICATION_LABELS, STATUS_LABELS, issueLabel, label } from '../format.js'

export default function FindingCard({ finding }) {
  const check = CHECKS_BY_ID[finding.check_id]
  const humanReview = finding.classification === 'human_review'
  const { page, description } = finding.location
  const location = page != null && !description.toLowerCase().startsWith('page')
    ? `Page ${page} — ${description}`
    : description

  return (
    <article className={`finding ${humanReview ? 'is-review' : 'is-fixable'}`}>
      <header className="finding-header">
        <h3>
          WCAG {finding.wcag_criterion} — {check ? check.name : finding.check_id}
        </h3>
        <span className={`pill ${humanReview ? 'pill-review' : 'pill-fixable'}`}>
          <span aria-hidden="true">{humanReview ? '⚠' : '✓'}</span>{' '}
          {label(CLASSIFICATION_LABELS, finding.classification)}
        </span>
      </header>

      <dl className="finding-fields">
        <div><dt>Issue</dt><dd>{issueLabel(finding.issue_type)}</dd></div>
        <div><dt>Location</dt><dd>{location}</dd></div>
        <div><dt>Check</dt><dd><code>{finding.check_id}</code> · Level {finding.wcag_level}</dd></div>
        <div><dt>Status</dt><dd>{label(STATUS_LABELS, finding.status)}</dd></div>
        {finding.fix_description && (
          <div className="full"><dt>Details</dt><dd>{finding.fix_description}</dd></div>
        )}
      </dl>
    </article>
  )
}
