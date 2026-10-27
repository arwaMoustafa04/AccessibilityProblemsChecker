import { downloadPdf } from '../api.js'
import { CHECKS } from '../data/checks.js'
import { formatBytes } from '../format.js'
import FindingCard from './FindingCard.jsx'

// Displays the POST /process response as-is; it does not judge accessibility itself.
export default function ResultsScreen({ result, onRestart }) {
  const { input, checks_performed, findings, summary, limitations, compliance_statement } = result
  const performed = new Set(checks_performed)
  const autoFixable = findings.filter((f) => f.classification === 'auto_fixable').length
  const humanReview = findings.filter((f) => f.classification === 'human_review').length

  return (
    <div className="results">
      <section className="card" aria-labelledby="results-title">
        <header className="screen-header">
          <p className="eyebrow">Analysis complete</p>
          <h1 id="results-title">{input.file_name}</h1>
          <p className="subtitle">{formatBytes(input.size_bytes)}</p>
        </header>

        <dl className="stats">
          <Stat label="Checks performed" value={`${checks_performed.length} / ${CHECKS.length}`} />
          <Stat label="Total findings" value={summary.total_issues} />
          <Stat label="Auto-fixable" value={autoFixable} tone="fixable" />
          <Stat label="Human review" value={humanReview} tone="review" />
        </dl>

        {checks_performed.length === 0 && (
          <div className="alert alert-warning" role="note">
            <p className="alert-title">No checks were performed</p>
            <p>An empty findings list here does not mean the PDF is accessible.</p>
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="findings-title">
        <h2 id="findings-title">Findings</h2>
        {findings.length === 0 ? (
          <p className="muted">
            No findings were reported by the checks that ran. See Checks Performed and Limitations below.
          </p>
        ) : (
          <div className="finding-list">
            {findings.map((f) => <FindingCard key={f.finding_id} finding={f} />)}
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="card" aria-labelledby="checks-title">
          <h2 id="checks-title">Checks Performed</h2>
          <ul className="check-list">
            {CHECKS.map((c) => {
              const ran = performed.has(c.check_id)
              return (
                <li key={c.check_id} className={ran ? 'ran' : 'not-ran'}>
                  <span className="check-mark" aria-hidden="true">{ran ? '✓' : '–'}</span>
                  <span>
                    {c.name} <span className="muted">({c.wcag_criterion})</span>
                    {!ran && <span className="not-ran-label"> — not performed</span>}
                  </span>
                </li>
              )
            })}
          </ul>
        </section>

        <section className="card" aria-labelledby="limitations-title">
          <h2 id="limitations-title">Limitations</h2>
          {limitations.length ? (
            <ul className="bullets">{limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          ) : (
            <p className="muted">None reported.</p>
          )}
        </section>
      </div>

      <footer className="disclaimer">
        <p>{compliance_statement}</p>
      </footer>

      <div className="actions">
        {result.report_pdf && (
          <button type="button" className="button button-secondary" onClick={() => downloadPdf(result.report_pdf)}>
            Download Report PDF
          </button>
        )}
        {result.output_pdf && (
          <button type="button" className="button button-secondary" onClick={() => downloadPdf(result.output_pdf)}>
            {result.output_pdf.modified ? 'Download Repaired PDF' : 'Download PDF'}
          </button>
        )}
        <button type="button" className="button button-primary" onClick={onRestart}>
          Analyze Another PDF
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ''}`}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
