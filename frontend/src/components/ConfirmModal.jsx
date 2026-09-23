export function ConfirmModal({ children, confirmLabel, cancelLabel = 'Cancel', danger, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" role="presentation" onClick={onCancel}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        {children}
        <div className="modal-actions">
          <button type="button" className="repo-control-button" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className={`button${danger ? ' button-danger' : ''}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
