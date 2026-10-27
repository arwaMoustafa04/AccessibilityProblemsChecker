import { useRef, useState } from 'react'
import UploadScreen from './components/UploadScreen.jsx'
import ProcessingScreen from './components/ProcessingScreen.jsx'
import ResultsScreen from './components/ResultsScreen.jsx'
import { MOCK_RESULT } from './data/mockResult.js'
import { ApiError, processPdf } from './api.js'

// Sends the chosen PDF to POST /process. A rejected file (error response) goes back
// to the upload screen with the API's error; a completed evaluation shows the results.
export default function App() {
  const [screen, setScreen] = useState('upload') // 'upload' | 'processing' | 'results'
  const [file, setFile] = useState(null)
  const [error, setError] = useState(null) // { title, message } shown on the upload screen
  const [result, setResult] = useState(null) // EvaluationResult from POST /process
  const requestId = useRef(0) // ignores a response that arrives after the user restarted

  const restart = () => {
    requestId.current += 1
    setFile(null)
    setError(null)
    setResult(null)
    setScreen('upload')
  }

  const analyze = async () => {
    if (!file) return
    const id = ++requestId.current
    setError(null)
    setScreen('processing')
    try {
      const data = await processPdf(file)
      if (id !== requestId.current) return
      setResult(data)
      setScreen('results')
    } catch (err) {
      if (id !== requestId.current) return
      setError(err instanceof ApiError
        ? { title: err.title, message: err.message }
        : { title: 'Something went wrong', message: 'The PDF could not be analyzed. Please try again.' })
      setScreen('upload')
    }
  }

  return (
    <>
      {import.meta.env.DEV && (
        <DevPreview screen={screen} setScreen={setScreen} setError={setError} setResult={setResult} />
      )}
      <main className="page">
        {screen === 'upload' && (
          <UploadScreen
            file={file}
            onFileChange={(f) => { setFile(f); setError(null) }}
            error={error}
            onAnalyze={analyze}
          />
        )}
        {screen === 'processing' && <ProcessingScreen fileName={file?.name} />}
        {screen === 'results' && result && <ResultsScreen result={result} onRestart={restart} />}
      </main>
    </>
  )
}

// Development-only bar for viewing every screen while building. Not in the production build.
// "Results" shows the sample data in src/data/mockResult.js.
function DevPreview({ screen, setScreen, setError, setResult }) {
  const show = (name, err = null) => { setError(err); setScreen(name) }
  return (
    <nav className="dev-preview" aria-label="Screen preview (development only)">
      <span>Preview:</span>
      <button onClick={() => show('upload')} aria-pressed={screen === 'upload'}>Upload</button>
      <button
        onClick={() => show('upload', {
          title: 'This PDF is encrypted',
          message: 'PDF is encrypted and cannot be processed. Remove the encryption and try again.',
        })}
      >
        Upload + error
      </button>
      <button onClick={() => show('processing')} aria-pressed={screen === 'processing'}>Processing</button>
      <button
        onClick={() => { setResult(MOCK_RESULT); show('results') }}
        aria-pressed={screen === 'results'}
      >
        Results (sample)
      </button>
    </nav>
  )
}
