import { ratingTone } from '../utils/reviewScore'

export function RatingBadge({ rating, size = 'medium', label = 'Score' }) {
  const tone = ratingTone(rating)
  return (
    <div className={`rating-badge rating-badge-${size} rating-${tone}`} title={`${label}: ${rating ?? 'not rated'}/100`}>
      <span className="rating-badge-value">{typeof rating === 'number' ? rating : '—'}</span>
      <span className="rating-badge-scale">/100</span>
    </div>
  )
}

export function RatingBar({ rating }) {
  const tone = ratingTone(rating)
  return (
    <div className="rating-bar" role="presentation">
      <div className={`rating-bar-fill rating-${tone}`} style={{ width: `${typeof rating === 'number' ? rating : 0}%` }} />
    </div>
  )
}
