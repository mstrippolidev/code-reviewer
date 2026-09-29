import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY, SubmitReviewError, UnauthorizedError, submitGuestReview } from '../api/client'
import { ConfirmModal } from '../components/ConfirmModal'
import { FileTree } from '../components/FileTree'
import { GuestUploadButton } from '../components/GuestUploadButton'
import { ReviewSelectionZone } from '../components/ReviewSelectionZone'
import { useFileSelection } from '../hooks/useFileSelection'
import { buildFileTree } from '../utils/buildFileTree'
import {
  GUEST_EXAMPLE_FILES,
  GuestUploadError,
  MAX_GUEST_FILES,
  guestTreeFiles,
  readGuestUpload,
} from '../utils/guestFiles'

const GUEST_SELECTION_KEY = 'guest'
const GUEST_EMPTY_MESSAGE = 'Check an example file on the right, or upload your own, to add it to this review.'

export function GuestReviewPage() {
  const navigate = useNavigate()
  const [contentByPath, setContentByPath] = useState(() =>
    Object.fromEntries(GUEST_EXAMPLE_FILES.map((file) => [file.path, file.content]))
  )
  const [uploadNotice, setUploadNotice] = useState(null)
  const [reviewError, setReviewError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [pendingSubmit, setPendingSubmit] = useState(false)
  const { selectedFiles, toggleNode, addPath, removePath } = useFileSelection(GUEST_SELECTION_KEY, MAX_GUEST_FILES)

  const treeNodes = useMemo(() => buildFileTree(guestTreeFiles(Object.keys(contentByPath))), [contentByPath])
  // FileTree only expands the folders it mounts with, so the first upload remounts it to show uploads/.
  const treeKey = treeNodes.length > 1 ? 'with-uploads' : 'examples-only'

  async function handleFileChosen(file) {
    setUploadNotice(null)
    try {
      const upload = await readGuestUpload(file)
      const isFull = !selectedFiles.has(upload.path) && selectedFiles.size >= MAX_GUEST_FILES
      setContentByPath((previous) => ({ ...previous, [upload.path]: upload.content }))
      if (isFull) {
        setUploadNotice({
          text: `Added ${file.name} to the list — deselect a file to include it (${MAX_GUEST_FILES}-file limit).`,
          isError: false,
        })
        return
      }
      addPath(upload.path)
    } catch (error) {
      const text = error instanceof GuestUploadError ? error.message : `Could not read ${file.name}.`
      setUploadNotice({ text, isError: true })
    }
  }

  async function handleSubmitReview() {
    setReviewError(null)
    setSubmitting(true)
    try {
      const files = [...selectedFiles].map((path) => ({ file_path: path, content: contentByPath[path] }))
      const job = await submitGuestReview(files)
      navigate(`/reviews/${job.review_id}`)
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        localStorage.removeItem(GUEST_STORAGE_KEY)
        navigate('/', { replace: true })
        return
      }
      setReviewError(error instanceof SubmitReviewError ? error.message : 'Could not submit this review.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="repo-browser">
      <div className="guest-intro">
        <h1>Review Python files as a guest</h1>
        <p className="note">
          Pick up to {MAX_GUEST_FILES} files. Duplication checks (DRY) compare against a registered repository, so
          they're only available when you connect GitHub.
        </p>
        {reviewError ? <p className="note error">{reviewError}</p> : null}
      </div>
      <div className="repo-browser-top">
        <div className="guest-selection-column">
          <ReviewSelectionZone
            selectedPaths={selectedFiles}
            max={MAX_GUEST_FILES}
            submitting={submitting}
            onRemove={removePath}
            onDropFile={addPath}
            onSubmit={() => setPendingSubmit(true)}
            emptyMessage={GUEST_EMPTY_MESSAGE}
          >
            <GuestUploadButton
              onFileChosen={handleFileChosen}
              message={uploadNotice?.text}
              isError={uploadNotice?.isError}
            />
          </ReviewSelectionZone>
        </div>
        <div className="repo-browser-pane repo-browser-right">
          <h2 className="repo-browser-right-title">Files</h2>
          <div className="file-tree-scroll">
            <FileTree key={treeKey} nodes={treeNodes} selectedPaths={selectedFiles} onToggleSelect={toggleNode} />
          </div>
        </div>
      </div>
      {pendingSubmit ? (
        <ConfirmModal
          confirmLabel="Start review"
          onConfirm={() => {
            setPendingSubmit(false)
            handleSubmitReview()
          }}
          onCancel={() => setPendingSubmit(false)}
        >
          <p>
            Reviewing <strong>{selectedFiles.size}</strong> file(s) can take several minutes — 13 agents run against
            each file (DRY is skipped for guest reviews).
          </p>
        </ConfirmModal>
      ) : null}
    </div>
  )
}
