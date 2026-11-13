import { useCallback, useEffect, useMemo, useState } from 'react'
import { UnauthorizedError, fetchReviewFeedback, submitFeedback } from '../api/client'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'
import { FeedbackContext } from './FeedbackContext'

export function FeedbackProvider({ reviewId, children }) {
  const [ratings, setRatings] = useState({})
  const handleUnauthorized = useUnauthorizedHandler()

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const stored = await fetchReviewFeedback(reviewId)
        if (active) {
          setRatings(Object.fromEntries(stored.map((rating) => [rating.incident_id, rating])))
        }
      } catch (error) {
        if (error instanceof UnauthorizedError) {
          handleUnauthorized()
        }
      }
    }

    load()
    return () => {
      active = false
    }
  }, [reviewId, handleUnauthorized])

  const rate = useCallback(
    async (incidentId, rating) => {
      try {
        const stored = await submitFeedback(reviewId, incidentId, rating)
        setRatings((previous) => ({ ...previous, [incidentId]: stored }))
      } catch (error) {
        if (error instanceof UnauthorizedError) {
          handleUnauthorized()
        }
        throw error
      }
    },
    [reviewId, handleUnauthorized],
  )

  const value = useMemo(() => ({ ratingOf: (incidentId) => ratings[incidentId] ?? null, rate }), [ratings, rate])

  return <FeedbackContext.Provider value={value}>{children}</FeedbackContext.Provider>
}
