import { useContext } from 'react'
import { FeedbackContext } from './FeedbackContext'

/** The ratings of the review being shown, or null on a page that offers no rating. */
export function useFeedback() {
  return useContext(FeedbackContext)
}
