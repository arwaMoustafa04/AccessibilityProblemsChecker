import { CHECKS_BY_ID } from '../data/checks.js'
import {
  CLASSIFICATION_LABELS, EVALUATION_LABELS, STATUS_LABELS, issueLabel, label, splitSuggestion,
} from '../format.js'

// Clicking anywhere on the card (or its "Show in PDF" button) selects it for the viewer.
export default function FindingCard({ finding, repair, selected, onSelect }) {
  const check = CHECKS_BY_ID[finding.check_id]
  const humanReview = finding.classification === 'human_review'
  const { page, object_ref, description } = finding.location
  const location = page != null && !description.toLowerCase().startsWith('page')
    ? `Page ${page} — ${description}`
    : description
  const { details, suggestion } = splitSuggestion(finding.fix_description)

  return (
    <article
      className={`finding ${humanReview ? 'is-review' : 'is-fixable'}${selected ? ' is-selected' : ''}`}
      onClick={onSelect}
    >
      <header className="finding-header">
        <h3>
          WCAG {finding.wcag_criterion} — {check ? check.name : finding.check_id}
        </h3>
        <div className="finding-actions">
          <span className={`pill ${humanReview ? 'pill-review' : 'pill-fixable'}`}>
            <span aria-hidden="true">{humanReview ? '⚠' : '✓'}</span>{' '}
            {label(CLASSIFICATION_LABELS, finding.classification)}
          </span>
          {/* No handler of its own: the click reaches the card's onClick. */}
          <button type="button" className="link-button" data-show-finding={finding.finding_id}
            aria-pressed={selected}>
            Show in PDF
          </button>
        </div>
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
        {finding.suggested_text && (
          <div className="full">
            <dt>Suggested text</dt>
            <dd>
              <q>{finding.suggested_text}</q>
              {finding.suggestion_source === 'llm' && <AiBadge />}
            </dd>
          </div>
        )}
        {repair && (
          <div className="full">
            <dt>Automatic repair</dt>
            <dd>
              {repair.action}{' '}
              <span className={`validation validation-${repair.validation_result}`}>
                Re-check {repair.validation_result}
              </span>
              {repair.method === 'llm' && <AiBadge />}
              {humanReview && (
                <span className="muted repair-note"> A person still needs to verify this.</span>
              )}
            </dd>
          </div>
        )}
      </dl>
    </article>
  )
}

export function AiBadge() {
  return <span className="ai-badge">AI-generated, please verify</span>
}
