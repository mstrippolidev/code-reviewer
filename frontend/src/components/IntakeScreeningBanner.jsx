import { useEffect, useState } from 'react'

const SCREENING_STEPS = [
  'Checking every file is real, reviewable source code',
  'Scanning for prompt-injection attempts',
  'This can take a minute or two on a larger submission',
]

const STEP_INTERVAL_MS = 3000

export function IntakeScreeningBanner() {
  const [stepIndex, setStepIndex] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      setStepIndex((previous) => (previous + 1) % SCREENING_STEPS.length)
    }, STEP_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [])

  return (
    <section className="intake-screening-banner" role="status" aria-live="polite">
      <span className="intake-screening-spinner" aria-hidden="true" />
      <div className="intake-screening-copy">
        <p className="intake-screening-title">Review started — screening your files before the agents begin</p>
        <p className="note intake-screening-step">{SCREENING_STEPS[stepIndex]}</p>
        <span className="intake-screening-progress" aria-hidden="true" />
        <p className="note intake-screening-patience">No action needed — thanks for your patience while this runs.</p>
      </div>
    </section>
  )
}
