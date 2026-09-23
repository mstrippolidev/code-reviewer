export const RATING_GOOD_FLOOR = 70
export const RATING_WARN_FLOOR = 50

export function ratingTone(rating) {
  if (typeof rating !== 'number') {
    return 'unknown'
  }
  if (rating >= RATING_GOOD_FLOOR) {
    return 'good'
  }
  if (rating >= RATING_WARN_FLOOR) {
    return 'warn'
  }
  return 'bad'
}

export function countIncidentsByPriority(incidents) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0, total: incidents.length }
  for (const incident of incidents) {
    if (incident.priority in counts) {
      counts[incident.priority] += 1
    }
  }
  return counts
}
