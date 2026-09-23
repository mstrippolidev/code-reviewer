import { RatingBadge } from './RatingBadge'

const PRIORITIES = ['critical', 'high', 'medium', 'low']

const RECOMMENDATION_TONE = {
  APPROVED: 'good',
  NEEDS_WORK: 'warn',
  REJECTED: 'bad',
}

export function ReviewSummary({ job, reports }) {
  const meta = job.result?.meta
  const settledCount = reports.filter((report) => report.status !== 'pending' && report.status !== 'running').length
  const progressPercent = reports.length ? Math.round((settledCount / reports.length) * 100) : 0
  const counts = meta
    ? {
        critical: meta.critical_incidents,
        high: meta.high_incidents,
        medium: meta.medium_incidents,
        low: meta.low_incidents,
      }
    : liveCounts(reports)

  return (
    <section className="review-summary">
      <div className="review-summary-score">
        <RatingBadge rating={meta ? Math.round(meta.overall_rating) : null} size="large" label="Overall score" />
        <div className="review-summary-score-text">
          <span className="review-summary-label">Overall score</span>
          {meta ? (
            <span className={`recommendation-tag rating-${RECOMMENDATION_TONE[meta.pr_recommendation]}`}>
              {meta.pr_recommendation.replace('_', ' ')}
            </span>
          ) : (
            <span className="note">Scoring once every file is in</span>
          )}
        </div>
      </div>

      <div className="review-summary-counts">
        <span className="review-summary-label">Incidents found</span>
        <ul className="incident-count-row">
          {PRIORITIES.map((priority) => (
            <li key={priority} className={`incident-count priority-tag-${priority}`}>
              <span className="incident-count-value">{counts[priority]}</span>
              <span className="incident-count-label">{priority}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="review-summary-progress">
        <span className="review-summary-label">
          {settledCount} of {reports.length} files · {job.status}
        </span>
        <div className="rating-bar">
          <div
            className={`rating-bar-fill ${job.status === 'failed' ? 'rating-bad' : 'rating-progress'}`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>
    </section>
  )
}

function liveCounts(reports) {
  const totals = { critical: 0, high: 0, medium: 0, low: 0 }
  for (const report of reports) {
    for (const priority of PRIORITIES) {
      totals[priority] += report.incidentCounts[priority]
    }
  }
  return totals
}
