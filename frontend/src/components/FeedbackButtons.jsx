import { useState } from 'react'
import { useFeedback } from '../feedback/useFeedback'

const REASONS = [
  { value: 'not_true', label: 'The finding is wrong' },
  { value: 'wrong_lines', label: 'Wrong lines' },
  { value: 'not_actionable', label: 'The fix is not actionable' },
  { value: 'wrong_severity', label: 'Wrong severity' },
  { value: 'other', label: 'Something else' },
]
const MAX_NOTE_LENGTH = 500

export function FeedbackButtons({ incidentId }) {
  const feedback = useFeedback()
  const [isAskingWhy, setIsAskingWhy] = useState(false)
  const [reason, setReason] = useState(null)
  const [note, setNote] = useState('')
  const [status, setStatus] = useState('idle')

  if (feedback === null || incidentId === null || incidentId === undefined) {
    return null
  }
  const current = feedback.ratingOf(incidentId)

  async function send(rating) {
    setStatus('saving')
    try {
      await feedback.rate(incidentId, rating)
      setIsAskingWhy(false)
      setStatus('idle')
    } catch {
      setStatus('error')
    }
  }

  function startThumbsDown() {
    setReason(current?.reason ?? null)
    setNote(current?.note ?? '')
    setIsAskingWhy(true)
  }

  return (
    <div className="feedback">
      <div className="feedback-buttons">
        <span className="feedback-label">Was this finding right?</span>
        <button
          type="button"
          className={`feedback-button${current?.verdict === 'up' ? ' feedback-button-active' : ''}`}
          aria-label="Thumbs up"
          aria-pressed={current?.verdict === 'up'}
          disabled={status === 'saving'}
          onClick={() => send({ verdict: 'up' })}
        >
          👍
        </button>
        <button
          type="button"
          className={`feedback-button${current?.verdict === 'down' ? ' feedback-button-active' : ''}`}
          aria-label="Thumbs down"
          aria-pressed={current?.verdict === 'down'}
          disabled={status === 'saving'}
          onClick={startThumbsDown}
        >
          👎
        </button>
        {status === 'error' ? <span className="note error">Could not save. Try again.</span> : null}
      </div>
      {isAskingWhy ? (
        <form
          className="feedback-form"
          onSubmit={(event) => {
            event.preventDefault()
            send({ verdict: 'down', reason, note })
          }}
        >
          <fieldset className="feedback-reasons">
            <legend>What was wrong?</legend>
            {REASONS.map((option) => (
              <label key={option.value} className="feedback-reason">
                <input
                  type="radio"
                  name={`reason-${incidentId}`}
                  checked={reason === option.value}
                  onChange={() => setReason(option.value)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          <textarea
            className="feedback-note"
            rows={2}
            maxLength={MAX_NOTE_LENGTH}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Not in the list? Tell us what was wrong (optional)."
          />
          <div className="feedback-actions">
            <button type="button" className="feedback-cancel" onClick={() => setIsAskingWhy(false)}>
              Cancel
            </button>
            <button type="submit" className="feedback-send" disabled={status === 'saving'}>
              Send
            </button>
          </div>
        </form>
      ) : null}
    </div>
  )
}
