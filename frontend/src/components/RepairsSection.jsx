import { STATUS_LABELS, issueLabel, label } from '../format.js'
import { AiBadge } from './FindingCard.jsx'

// Before/after summary of the automatic repairs (Phase 5). Every repair was re-checked
// by running all checks again on the repaired PDF; the API reports the result.
export default function RepairsSection({ result }) {
  const { findings } = result
  const repairs = result.repairs ?? []
  const newIssues = result.new_issues_after_repair ?? []
  if (findings.length === 0) return null

  const count = (status) => findings.filter((f) => f.status === status).length
  const findingById = Object.fromEntries(findings.map((f) => [f.finding_id, f]))
  const aiRepairs = repairs.filter((r) => r.method === 'llm').length

  return (
    <section className="card" aria-labelledby="repairs-title">
      <h2 id="repairs-title">Automatic Repairs</h2>
      <ul className="before-after" aria-label="Before and after repair">
        <li><strong>{findings.length}</strong> found before repair</li>
        <li className="ba-fixed"><strong>{count('fixed')}</strong> fixed and re-checked</li>
        <li className="ba-failed"><strong>{count('repair_failed')}</strong> repair failed</li>
        <li className="ba-review"><strong>{count('needs_human_review')}</strong> need human review</li>
        <li><strong>{newIssues.length}</strong> new after repair</li>
      </ul>

      {repairs.length === 0 ? (
        <p className="muted">
          No repairs were applied, so the PDF you download is the original, unchanged.
        </p>
      ) : (
        <>
          <p className="muted">
            {repairs.length} repair{repairs.length === 1 ? '' : 's'} applied to a copy of your PDF
            {aiRepairs > 0 && `, ${aiRepairs} using AI-generated text`}. Download the repaired PDF below.
          </p>
          <ol className="repair-list">
            {repairs.map((r) => {
              const f = findingById[r.finding_id]
              return (
                <li key={r.repair_id}>
                  <span className={`validation validation-${r.validation_result}`}>
                    Re-check {r.validation_result}
                  </span>{' '}
                  <span>{r.action}</span>
                  {r.method === 'llm' && <AiBadge />}
                  {f && (
                    <span className="muted"> — {f.check_id}, {label(STATUS_LABELS, f.status)}</span>
                  )}
                </li>
              )
            })}
          </ol>
        </>
      )}

      {newIssues.length > 0 && (
        <div className="alert alert-warning" role="note">
          <p className="alert-title">New issues after repair</p>
          <ul className="bullets">
            {newIssues.map((f) => (
              <li key={f.finding_id}>
                {f.check_id}: {issueLabel(f.issue_type)} ({f.location.description})
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
