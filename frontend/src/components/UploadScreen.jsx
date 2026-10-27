import { useId, useRef, useState } from 'react'
import { formatBytes } from '../format.js'

export default function UploadScreen({ file, onFileChange, error, onAnalyze }) {
  const inputRef = useRef(null)
  const inputId = useId()
  const [dragging, setDragging] = useState(false)

  const pick = (files) => {
    if (files && files[0]) onFileChange(files[0])
  }

  return (
    <section className="card upload" aria-labelledby="upload-title">
      <header className="screen-header">
        <h1 id="upload-title">PDF Accessibility Checker</h1>
        <p className="subtitle">
          Upload a PDF to check it against the WCAG 2.1 criteria used for ADA Title II.
        </p>
      </header>

      <div
        className={`dropzone${dragging ? ' is-dragging' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files) }}
      >
        <svg className="dropzone-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6M12 18v-6M9 15l3-3 3 3" />
        </svg>
        <p className="dropzone-text">Drag and drop a PDF here, or</p>
        <label htmlFor={inputId} className="button button-secondary">Choose file</label>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="visually-hidden"
          onChange={(e) => pick(e.target.files)}
        />
        <p className="hint">PDF only, max 20 MiB</p>
      </div>

      {file && (
        <div className="selected-file">
          <span className="file-badge" aria-hidden="true">PDF</span>
          <div>
            <p className="file-name">{file.name}</p>
            <p className="file-size">{formatBytes(file.size)}</p>
          </div>
          <button
            type="button"
            className="link-button"
            onClick={() => { onFileChange(null); if (inputRef.current) inputRef.current.value = '' }}
          >
            Remove
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error" role="alert">
          <p className="alert-title">{error.title}</p>
          <p>{error.message}</p>
        </div>
      )}

      <button type="button" className="button button-primary button-wide" disabled={!file} onClick={onAnalyze}>
        Analyze PDF
      </button>
    </section>
  )
}
