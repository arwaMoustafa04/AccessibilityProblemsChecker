import { CHECKS_BY_ID } from '../data/checks.js'
import {
  CLASSIFICATION_LABELS, EVALUATION_LABELS, STATUS_LABELS, issueLabel, label, splitSuggestion,
} from '../format.js'

export default function FindingCard({ finding }) {
  const check = CHECKS_BY_ID[finding.check_id]
  const humanReview = finding.classification === 'human_review'
  const { page, object_ref, description } = finding.location
  const location = page != null && !description.toLowerCase().startsWith('page')
    ? `Page ${page} — ${description}`
    : description
  const { details, suggestion } = splitSuggestion(finding.fix_description)

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
        <div>
          <dt>Result</dt>
          <dd className={`result result-${finding.evaluation_result}`}>
            {label(EVALUATION_LABELS, finding.evaluation_result)}
          </dd>
        </div>
        <div><dt>Location</dt><dd>{location}</dd></div>
        <div><dt>Check</dt><dd><code>{finding.check_id}</code> · Level {finding.wcag_level}</dd></div>
        <div><dt>Status</dt><dd>{label(STATUS_LABELS, finding.status)}</dd></div>
        {object_ref && (
          <div><dt>PDF object</dt><dd><code className="object-ref">{object_ref}</code></dd></div>
        )}
        {details && (
          <div className="full"><dt>Details</dt><dd>{details}</dd></div>
        )}
        {suggestion && (
          <div className="full"><dt>Suggested fix</dt><dd>{suggestion}</dd></div>
        )}
      </dl>
    </article>
  )
}
