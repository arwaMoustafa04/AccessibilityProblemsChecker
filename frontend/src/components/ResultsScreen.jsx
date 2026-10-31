import { useCallback, useEffect, useRef, useState } from 'react'
import { downloadPdf, downloadResultsZip } from '../api.js'
import { CHECKS } from '../data/checks.js'
import { formatBytes } from '../format.js'
import { openPdf } from '../pdf.js'
import FindingCard from './FindingCard.jsx'
import PdfViewer from './PdfViewer.jsx'

// Displays the POST /process response as-is; it does not judge accessibility itself.
// `file` is the uploaded PDF, shown in the side panel when a finding is selected.
export default function ResultsScreen({ result, file, onRestart }) {
  const { input, checks_performed, findings, summary, limitations, compliance_statement } = result
  const [selectedId, setSelectedId] = useState(null)
  const [zipping, setZipping] = useState(false)
  const selected = findings.find((f) => f.finding_id === selectedId)

  // The PDF is opened once, the first time a finding is selected.
  const documentRef = useRef(null)
  const loadDocument = useCallback(() => (documentRef.current ??= openPdf(file)), [file])
  useEffect(() => () => { documentRef.current?.then((d) => d.destroy(), () => {}) }, [])

  // Leave room for the side panel while it is open (see .viewer-open in styles.css).
  useEffect(() => {
    document.body.classList.toggle('viewer-open', Boolean(selected))
    return () => document.body.classList.remove('viewer-open')
  }, [selected])

  const closeViewer = useCallback(() => {
    const id = selectedId
    setSelectedId(null)
    document.querySelector(`[data-show-finding="${id}"]`)?.focus()
  }, [selectedId])

  const downloadZip = async () => {
    setZipping(true)
    try {
      await downloadResultsZip(result)
    } finally {
      setZipping(false)
    }
  }
  const performed = new Set(checks_performed)
  const findingCounts = {}
  for (const f of findings) findingCounts[f.check_id] = (findingCounts[f.check_id] ?? 0) + 1
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
        {findings.length > 0 && (
          <p className="muted findings-hint">Select a finding to see where it is in the PDF.</p>
        )}
        {findings.length === 0 ? (
          <p className="muted">
            No findings were reported by the checks that ran. See Checks Performed and Limitations below.
          </p>
        ) : (
          <div className="finding-list">
            {findings.map((f) => (
              <FindingCard
                key={f.finding_id}
                finding={f}
                selected={f.finding_id === selectedId}
                onSelect={() => setSelectedId(f.finding_id)}
              />
            ))}
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="card" aria-labelledby="checks-title">
          <h2 id="checks-title">Checks Performed</h2>
          <ul className="check-list">
            {CHECKS.map((c) => {
              const ran = performed.has(c.check_id)
              const count = findingCounts[c.check_id] ?? 0
              return (
                <li key={c.check_id} className={ran ? 'ran' : 'not-ran'}>
                  <span className="check-mark" aria-hidden="true">{ran ? '✓' : '–'}</span>
                  <span>
                    {c.name} <span className="muted">({c.wcag_criterion})</span>
                    {ran
                      ? <span className="muted"> — {count === 1 ? '1 finding' : `${count} findings`}</span>
                      : <span className="not-ran-label"> — not performed</span>}
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
        {result.output_pdf && result.report_pdf && (
          <button type="button" className="button button-secondary" onClick={downloadZip} disabled={zipping}>
            {zipping ? 'Preparing ZIP…' : 'Download Fixed PDF + Report (ZIP)'}
          </button>
        )}
        <button type="button" className="button button-primary" onClick={onRestart}>
          Analyze Another PDF
        </button>
      </div>

      {selected && (
        <PdfViewer
          key={selected.finding_id}
          finding={selected}
          loadDocument={loadDocument}
          onClose={closeViewer}
        />
      )}
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
