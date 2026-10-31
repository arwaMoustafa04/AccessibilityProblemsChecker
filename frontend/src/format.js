export const MAX_FILE_BYTES = 20 * 1024 * 1024 // 20 MiB, same limit as the API

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export const CLASSIFICATION_LABELS = {
  auto_fixable: 'Auto-fixable',
  human_review: 'Human Review',
}

// Unknown values are shown as-is, so a new status from the API is never hidden.
export const STATUS_LABELS = {
  detected: 'Detected',
  fixed: 'Fixed',
  repair_failed: 'Repair Failed',
  needs_human_review: 'Needs Human Review',
}

// Finding.evaluation_result: "fail" is a definite problem; "needs_review" means a
// person has to look (e.g. an image whose alternative text could not be resolved).
export const EVALUATION_LABELS = {
  fail: 'Fail',
  needs_review: 'Needs Review',
}

export const label = (map, value) => map[value] ?? value

// The API appends " Suggested fix: ..." to fix_description; show it as its own field.
export const splitSuggestion = (text) => {
  const marker = ' Suggested fix: '
  const at = (text ?? '').indexOf(marker)
  if (at === -1) return { details: text, suggestion: null }
  return { details: text.slice(0, at), suggestion: text.slice(at + marker.length) }
}

// The API's issue_type is snake_case (e.g. "title_missing"); show it as words.
export const issueLabel = (issueType) => {
  const words = issueType.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
