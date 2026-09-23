export function parseLineRange(linePosition) {
  const [rawStart, rawEnd] = String(linePosition ?? '').split('-')
  const start = Number.parseInt(rawStart, 10)
  if (!Number.isInteger(start)) {
    return null
  }
  const end = Number.parseInt(rawEnd, 10)
  return { start, end: Number.isInteger(end) ? Math.max(start, end) : start }
}

export function formatLineRange(linePosition) {
  const range = parseLineRange(linePosition)
  if (range === null) {
    return 'Location unknown'
  }
  return range.start === range.end ? `Line ${range.start}` : `Lines ${range.start}–${range.end}`
}
