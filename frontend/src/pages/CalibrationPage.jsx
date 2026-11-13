import { useEffect, useState } from 'react'
import { exportCalibrationLabels } from '../api/client'
import { CodePane } from '../components/CodePane'
import { useCalibration } from '../hooks/useCalibration'

async function downloadLabels() {
  const labels = await exportCalibrationLabels()
  const blob = new Blob([JSON.stringify(labels, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'labels.json'
  link.click()
  URL.revokeObjectURL(url)
}

function LabelingForm({ pair, canGoBack, onAnswer, onBack }) {
  const [note, setNote] = useState(pair.note ?? '')

  useEffect(() => {
    function onKeyDown(event) {
      if (event.target instanceof HTMLTextAreaElement) {
        return
      }
      if (event.key === 'd') {
        onAnswer(true, note)
      } else if (event.key === 'n') {
        onAnswer(false, note)
      } else if (event.key === 'ArrowLeft') {
        onBack()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onAnswer, onBack, note])

  return (
    <>
      <div className="calibration-panes">
        <CodePane side={pair.left} title="A" />
        <CodePane side={pair.right} title="B" />
      </div>
      <textarea
        className="calibration-note"
        placeholder="Optional note: why?"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={2}
      />
      <div className="calibration-actions">
        <button type="button" className="button" onClick={onBack} disabled={!canGoBack}>
          Back (←)
        </button>
        <button type="button" className="button button-danger" onClick={() => onAnswer(false, note)}>
          Not a duplicate (n)
        </button>
        <button type="button" className="button" onClick={() => onAnswer(true, note)}>
          Duplicate (d)
        </button>
      </div>
      {pair.is_duplicate !== null ? (
        <p className="note">
          You answered: {pair.is_duplicate ? 'duplicate' : 'not a duplicate'}. Choose again to change it.
        </p>
      ) : null}
    </>
  )
}

export function CalibrationPage() {
  const { pair, progress, status, answer, goBack, canGoBack } = useCalibration()

  if (status === 'loading') {
    return <p className="page centered">Loading…</p>
  }
  if (status === 'error') {
    return <p className="page centered note error">Could not load the pairs. Is CALIBRATION_ENABLED on?</p>
  }

  const percent = progress.total === 0 ? 0 : Math.round((progress.labeled / progress.total) * 100)

  return (
    <div className="calibration-page">
      <header className="calibration-header">
        <div>
          <h1>Are these the same logic?</h1>
          <p className="calibration-rule">
            Duplicate means the same logic that should change together. Code that only looks alike, or changes for
            different reasons, is not a duplicate.
          </p>
        </div>
        <div className="calibration-progress">
          <span>
            {progress.labeled} of {progress.total}
          </span>
          <div className="calibration-bar">
            <div className="calibration-bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <button type="button" className="button" onClick={downloadLabels}>
            Export labels
          </button>
        </div>
      </header>

      {status === 'done' ? (
        <p className="note">Every pair is labeled. Export the labels to finish.</p>
      ) : (
        <LabelingForm key={pair.pair_id} pair={pair} canGoBack={canGoBack} onAnswer={answer} onBack={goBack} />
      )}
    </div>
  )
}
