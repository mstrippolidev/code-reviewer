export function IntakeScreeningBanner() {
  return (
    <section className="intake-screening-banner" role="status" aria-live="polite">
      <span className="intake-screening-spinner" aria-hidden="true" />
      <div>
        <p className="intake-screening-title">Reviewing your files…</p>
        <p className="note">
          Screening for safety before the agents begin. This starts automatically — no action needed.
        </p>
      </div>
    </section>
  )
}
