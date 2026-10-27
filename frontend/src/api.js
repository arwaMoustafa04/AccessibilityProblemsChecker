// Client for the system API (openapi.yaml, v0.4.0).
// In `npm run dev`, /api is proxied to the backend (see vite.config.js), so no CORS is needed.
// Set VITE_API_URL to call a different base URL directly (that server must allow CORS).
const API_BASE = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')

// Friendly wording for each Error.error_code. Unknown codes fall back to the API's message.
const ERROR_TITLES = {
  MISSING_FILE: 'No file was received',
  INVALID_FILE_TYPE: 'This file is not a PDF',
  FILE_TOO_LARGE: 'This file is too large',
  CORRUPTED_PDF: 'This PDF is corrupted',
  UNREADABLE_PDF: 'This PDF cannot be read',
  ENCRYPTED_PDF: 'This PDF is encrypted',
  PASSWORD_PROTECTED_PDF: 'This PDF is password-protected',
  PROCESSING_ERROR: 'The analysis could not be completed',
  INVALID_REQUEST: 'The request was invalid',
  EXTERNAL_SERVICE_UNAVAILABLE: 'The service is temporarily unavailable',
}

const ERROR_HINTS = {
  MISSING_FILE: 'Choose a PDF and try again.',
  INVALID_FILE_TYPE: 'Only PDF files can be analyzed.',
  FILE_TOO_LARGE: 'The limit is 20 MiB. Try a smaller PDF.',
  CORRUPTED_PDF: 'Try re-exporting or re-saving the PDF, then upload it again.',
  UNREADABLE_PDF: 'Try re-exporting or re-saving the PDF, then upload it again.',
  ENCRYPTED_PDF: 'Remove the encryption and try again.',
  PASSWORD_PROTECTED_PDF: 'Remove the password and try again.',
  EXTERNAL_SERVICE_UNAVAILABLE: 'Please try again in a few minutes.',
}

// Thrown for any failed request; `title` and `message` are ready to show on the upload screen.
export class ApiError extends Error {
  constructor(title, message, code = null) {
    super(message)
    this.title = title
    this.code = code
  }
}

// POST /process with the PDF. Resolves to the EvaluationResult; rejects with ApiError.
export async function processPdf(file) {
  const body = new FormData()
  body.append('file', file, file.name)

  let response
  try {
    response = await fetch(`${API_BASE}/process`, { method: 'POST', body })
  } catch {
    throw new ApiError(
      'Could not reach the server',
      'Check your connection and that the API is running, then try again.',
    )
  }

  const data = await response.json().catch(() => null)
  if (response.ok && data) return data

  if (data?.status === 'error' && data.error_code) {
    const hint = ERROR_HINTS[data.error_code]
    throw new ApiError(
      ERROR_TITLES[data.error_code] ?? 'The PDF was rejected',
      hint ? `${data.message} ${hint}` : data.message,
      data.error_code,
    )
  }
  throw new ApiError(
    'Something went wrong',
    `The server returned an unexpected response (HTTP ${response.status}).`,
  )
}

// Saves one of the result's PDFs (output_pdf / report_pdf: Base64 content) as a file.
export function downloadPdf({ file_name, media_type, content_base64 }) {
  const bytes = Uint8Array.from(atob(content_base64), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: media_type }))
  const a = document.createElement('a')
  a.href = url
  a.download = file_name
  a.click()
  URL.revokeObjectURL(url)
}
