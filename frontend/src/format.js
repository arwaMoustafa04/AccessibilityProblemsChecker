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

export const label = (map, value) => map[value] ?? value

// The API's issue_type is snake_case (e.g. "title_missing"); show it as words.
export const issueLabel = (issueType) => {
  const words = issueType.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
