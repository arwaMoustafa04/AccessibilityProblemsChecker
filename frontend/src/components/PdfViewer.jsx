import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { CHECKS_BY_ID } from '../data/checks.js'
import { issueLabel } from '../format.js'

const MARK_PADDING = 4 // px around the highlighted box

// Side panel: the page a finding is on, with Location.bbox (PDF user space) highlighted.
// The parent gives it key={finding_id}, so choosing another finding starts it fresh.
export default function PdfViewer({ finding, loadDocument, onClose }) {
  const { page: findingPage, bbox } = finding.location
  const check = CHECKS_BY_ID[finding.check_id]
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(findingPage ?? 1)
  const [width, setWidth] = useState(0)
  const [mark, setMark] = useState(null) // highlight position in CSS px on the rendered page
  const headingRef = useRef(null)
  const stageRef = useRef(null)
  const canvasRef = useRef(null)
  const markRef = useRef(null)

  useEffect(() => { headingRef.current?.focus() }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    let live = true
    loadDocument().then(
      (d) => { if (live) setDoc(d) },
      () => { if (live) setError('The PDF could not be displayed.') },
    )
    return () => { live = false }
  }, [loadDocument])

  // Render at the panel's width, and again when the panel is resized.
  useLayoutEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(stageRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!doc || !width) return undefined
    let task = null
    let cancelled = false
    doc.getPage(Math.min(page, doc.numPages)).then((pdfPage) => {
      if (cancelled) return undefined
      const viewport = pdfPage.getViewport({ scale: width / pdfPage.getViewport({ scale: 1 }).width })
      const canvas = canvasRef.current
      const ratio = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * ratio)
      canvas.height = Math.floor(viewport.height * ratio)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      task = pdfPage.render({
        canvasContext: canvas.getContext('2d'),
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      })
      if (bbox && page === findingPage) {
        const [x1, y1, x2, y2] = viewport.convertToViewportRectangle(bbox)
        setMark({
          left: Math.min(x1, x2) - MARK_PADDING,
          top: Math.min(y1, y2) - MARK_PADDING,
          width: Math.abs(x2 - x1) + 2 * MARK_PADDING,
          height: Math.abs(y2 - y1) + 2 * MARK_PADDING,
        })
      } else {
        setMark(null)
      }
      return task.promise
    }).catch((err) => {
      if (!cancelled && err?.name !== 'RenderingCancelledException') {
        setError('This page could not be displayed.')
      }
    })
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [doc, page, width, bbox, findingPage])

  useEffect(() => { markRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [mark])

  let note
  if (findingPage == null) note = 'This issue applies to the whole document, not one place on a page.'
  else if (!bbox) note = `The exact position is not available; the issue is on page ${findingPage}.`
  else if (page === findingPage) note = `Highlighted on page ${findingPage}.`
  else note = `The issue is on page ${findingPage}.`

  return (
    <aside className="viewer" aria-labelledby="viewer-title">
      <header className="viewer-header">
        <div>
          <h2 id="viewer-title" ref={headingRef} tabIndex={-1}>{issueLabel(finding.issue_type)}</h2>
          <p className="muted">
            WCAG {finding.wcag_criterion} — {check ? check.name : finding.check_id}
          </p>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close PDF view">
          <span aria-hidden="true">×</span>
        </button>
      </header>

      <p className="viewer-note" role="status">{note}</p>

      {doc && doc.numPages > 1 && (
        <div className="viewer-pager">
          <button type="button" className="button button-secondary button-small"
            disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ‹ Previous
          </button>
          <span>Page {page} of {doc.numPages}</span>
          <button type="button" className="button button-secondary button-small"
            disabled={page >= doc.numPages} onClick={() => setPage((p) => p + 1)}>
            Next ›
          </button>
        </div>
      )}

      <div className="viewer-stage" ref={stageRef}>
        {error ? (
          <div className="alert alert-error" role="alert"><p>{error}</p></div>
        ) : (
          <>
            {!doc && <p className="muted">Loading PDF…</p>}
            <div className="viewer-page" hidden={!doc}>
              <canvas ref={canvasRef} role="img" aria-label={`Page ${page} of the PDF`} />
              {mark && <div ref={markRef} className="viewer-mark" style={mark} />}
            </div>
          </>
        )}
      </div>
    </aside>
  )
}
