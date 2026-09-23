export function ReviewSelectionZone({ selectedPaths, max, onRemove, onDropFile, onSubmit, submitting }) {
  function handleDragOver(event) {
    event.preventDefault()
  }

  function handleDrop(event) {
    event.preventDefault()
    const path = event.dataTransfer.getData('text/plain')
    if (path) {
      onDropFile(path)
    }
  }

  return (
    <div className="review-selection-zone" onDragOver={handleDragOver} onDrop={handleDrop}>
      <div className="review-selection-header">
        <span className="review-selection-count">
          {selectedPaths.size}/{max} Python files selected
        </span>
        <button
          type="button"
          className={`button${selectedPaths.size > 0 && !submitting ? '' : ' disabled'}`}
          disabled={selectedPaths.size === 0 || submitting}
          onClick={onSubmit}
        >
          {submitting ? 'Submitting…' : 'Submit for review'}
        </button>
      </div>
      {selectedPaths.size === 0 ? (
        <p className="note review-selection-empty">
          Check a Python file above, or drag one here, to add it to this review.
        </p>
      ) : (
        <ul className="review-selection-list">
          {[...selectedPaths].map((path) => (
            <li key={path} className="review-selection-item">
              <span className="review-selection-path">{path}</span>
              <button
                type="button"
                className="file-tree-info-button"
                aria-label={`Remove ${path}`}
                onClick={() => onRemove(path)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
