const STEPS = ['Validating', 'Checking accessibility', 'Classifying findings']

export default function ProcessingScreen({ fileName }) {
  return (
    <section className="card processing" aria-labelledby="processing-title" aria-busy="true">
      <div className="spinner" aria-hidden="true" />
      <h1 id="processing-title" role="status">Analyzing PDF…</h1>
      {fileName && <p className="subtitle">{fileName}</p>}
      <ol className="steps" aria-label="Analysis steps">
        {STEPS.map((step, i) => (
          <li key={step}>
            {i > 0 && <span className="step-arrow" aria-hidden="true">→</span>}
            {step}
          </li>
        ))}
      </ol>
    </section>
  )
}
