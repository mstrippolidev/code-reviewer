import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { TOKEN_STORAGE_KEY, fetchIndexedFileContent, fetchReviewFileContent } from '../api/client'
import { AnnotatedSource, CODE_LINE_HEIGHT } from '../components/AnnotatedSource'
import { RatingBadge } from '../components/RatingBadge'
import { useAgentCatalog } from '../hooks/useAgentCatalog'
import { useReviewStream } from '../hooks/useReviewStream'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'
import { buildFileReports, FILE_STATUS } from '../utils/buildFileReports'
import { parseLineRange } from '../utils/lineRange'

export function AnnotatedFilePage() {
  const { reviewId } = useParams()
  const [searchParams] = useSearchParams()
  const filePath = searchParams.get('path')
  const repoId = searchParams.get('repo_id')
  const focusedPosition = searchParams.get('focus')
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const catalog = useAgentCatalog(token)
  const handleUnauthorized = useUnauthorizedHandler()
  // The same live stream ReviewPage uses, not a one-shot fetch: a file's
  // own incidents should appear the instant each agent reports, not only
  // once the whole file's dispatch (let alone the whole PR) has settled.
  const { job, reviewedFiles, failedFiles, agentProgress, connectionStatus } = useReviewStream(
    token,
    reviewId,
    handleUnauthorized
  )
  const { content, loadState: contentLoadState } = useFileContent(token, { reviewId, repoId, filePath })
  const report = job
    ? buildFileReports({ job, agentProgress, reviewedFiles, failedFiles, catalog }).find(
        (entry) => entry.filePath === filePath
      )
    : null

  useEffect(() => {
    const range = parseLineRange(focusedPosition)
    if (range === null || contentLoadState !== 'ready') {
      return
    }
    document.getElementById(`code-line-${range.start}`)?.scrollIntoView({ block: 'center' })
  }, [focusedPosition, contentLoadState])

  if (connectionStatus === 'error' && !job) {
    return <p className="page centered note error">Could not connect to this review.</p>
  }
  if (!job || contentLoadState === 'loading') {
    return <p className="page centered">Loading file…</p>
  }
  if (contentLoadState === 'error') {
    return <p className="page centered note error">Could not load this file’s source.</p>
  }

  // buildFileReports has no flat `.incidents` field of its own — only
  // `.agents` (each carrying its own `.incidents`, already code_key-tagged)
  // and `.incidentCounts`. Flatten here rather than adding a field to that
  // shared shape just for this one caller.
  const incidents = report?.agents?.flatMap((agent) => agent.incidents) ?? []
  const counts = report?.incidentCounts ?? { total: 0, critical: 0, high: 0, medium: 0, low: 0 }
  const agentNamesByCodeKey = Object.fromEntries(
    Object.values(catalog.agentsByCodeKey).map((agent) => [agent.code_key, agent.name])
  )
  const pendingMessage = annotationsPendingMessage(report)

  return (
    <div className="page annotated-page" style={{ '--code-line-height': `${CODE_LINE_HEIGHT}px` }}>
      <header className="annotated-header">
        <div>
          <Link className="annotated-back-link" to={`/reviews/${reviewId}`}>
            ← Back to dashboard
          </Link>
          <h1 className="annotated-title">{filePath}</h1>
          <p className="note">
            {counts.total} incidents · {counts.critical} critical · {counts.high} high · {counts.medium} medium ·{' '}
            {counts.low} low
          </p>
        </div>
        <RatingBadge rating={report?.rating ?? null} size="large" label="File score" />
      </header>
      {connectionStatus === 'error' ? (
        <p className="note annotated-pending">
          Live updates disconnected — showing the last known state. Reload to reconnect.
        </p>
      ) : null}
      {pendingMessage ? <p className="note annotated-pending">{pendingMessage}</p> : null}
      <AnnotatedSource
        content={content}
        incidents={incidents}
        focusedPosition={focusedPosition}
        agentNamesByCodeKey={agentNamesByCodeKey}
      />
    </div>
  )
}

function useFileContent(token, { reviewId, repoId, filePath }) {
  const [content, setContent] = useState('')
  const [loadState, setLoadState] = useState('loading')

  useEffect(() => {
    const controller = new AbortController()
    // A guest review has no repo: its source was stored with the review itself.
    const request = repoId
      ? fetchIndexedFileContent(token, repoId, filePath, controller.signal)
      : fetchReviewFileContent(token, reviewId, filePath, controller.signal)

    request
      .then((file) => {
        setContent(file.content)
        setLoadState('ready')
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setLoadState('error')
        }
      })

    return () => {
      controller.abort()
    }
  }, [token, reviewId, repoId, filePath])

  return { content, loadState }
}

/**
 * Distinguishes "nothing to show yet" from "genuinely clean" — a REVIEWED
 * file with zero incidents needs no banner at all, but PENDING/RUNNING
 * needs to say so explicitly rather than look indistinguishable from a
 * clean file (the exact confusion that prompted this rewrite).
 */
function annotationsPendingMessage(report) {
  if (!report || report.status === FILE_STATUS.PENDING) {
    return 'This file hasn’t started its review yet, so no annotations are attached to it.'
  }
  if (report.status === FILE_STATUS.RUNNING) {
    const agentCount = report.agentsReported
    return `This file’s review is still in progress — ${agentCount} agent${
      agentCount === 1 ? '' : 's'
    } reported so far. Annotations will appear as more finish.`
  }
  if (report.status === FILE_STATUS.EXCLUDED) {
    return report.skipReason ?? 'This file was not reviewed.'
  }
  return null
}
