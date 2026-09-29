import { useRef } from 'react'
import { MAX_GUEST_FILE_LINES } from '../utils/guestFiles'

export function GuestUploadButton({ onFileChosen, message, isError }) {
  const inputRef = useRef(null)

  function handleChange(event) {
    const [file] = event.target.files
    // Cleared so choosing the same file again (e.g. after editing it) still fires onChange.
    event.target.value = ''
    if (file) {
      onFileChosen(file)
    }
  }

  return (
    <div className="guest-upload">
      <input ref={inputRef} type="file" accept=".py" hidden onChange={handleChange} />
      <button type="button" className="repo-control-button" onClick={() => inputRef.current.click()}>
        Upload your own .py file
      </button>
      <p className={`note${isError ? ' error' : ''}`}>
        {message ?? `Python files only, up to ${MAX_GUEST_FILE_LINES.toLocaleString()} lines.`}
      </p>
    </div>
  )
}
