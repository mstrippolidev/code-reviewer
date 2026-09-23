import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { TOKEN_STORAGE_KEY, fetchIndexedFileContent, fetchReview } from '../api/client'
import { AnnotatedSource, CODE_LINE_HEIGHT } from '../components/AnnotatedSource'
import { RatingBadge } from '../components/RatingBadge'
import { useAgentCatalog } from '../hooks/useAgentCatalog'
import { parseLineRange } from '../utils/lineRange'
import { countIncidentsByPriority } from '../utils/reviewScore'

export function AnnotatedFilePage() {
  const { reviewId } = useParams()
  const [searchParams] = useSearchParams()
  const filePath = searchParams.get('path')
  const repoId = searchParams.get('repo_id')
  const focusedPosition = searchParams.get('focus')
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const catalog = useAgentCatalog(token)
  const { content, review, loadState } = useAnnotatedFile(token, { reviewId, repoId, filePath })

  useEffect(() => {
    const range = parseLineRange(focusedPosition)
    if (range === null || loadState !== 'ready') {
      return
    }
    document.getElementById(`code-line-${range.start}`)?.scrollIntoView({ block: 'center' })
  }, [focusedPosition, loadState])

  if (loadState === 'loading') {
    return <p className="page centered">Loading file…</p>
  }
  if (loadState === 'error') {
    return <p className="page centered note error">Could not load this file’s source.</p>
  }

  const incidents = review?.incidents ?? []
  const counts = countIncidentsByPriority(incidents)
  const agentNamesByCodeKey = Object.fromEntries(
    Object.values(catalog.agentsByCodeKey).map((agent) => [agent.code_key, agent.name])
  )

  return (
    <div className="page annotated-page" style={{ '--code-line-height': `${CODE_LINE_HEIGHT}px` }}>
      <header className="annotated-header">
        <div>
          <h1 className="annotated-title">{filePath}</h1>
          <p className="note">
            {counts.total} incidents · {counts.critical} critical · {counts.high} high · {counts.medium} medium ·{' '}
            {counts.low} low
          </p>
        </div>
        <RatingBadge rating={review?.rating ?? null} size="large" label="File score" />
      </header>
      {review === null ? (
        <p className="note annotated-pending">
          This review has not finished yet, so no annotations are attached to this file.
        </p>
      ) : null}
      <AnnotatedSource
        content={content}
        incidents={incidents}
        focusedPosition={focusedPosition}
        agentNamesByCodeKey={agentNamesByCodeKey}
      />
    </div>
  )
}

function useAnnotatedFile(token, { reviewId, repoId, filePath }) {
  const [content, setContent] = useState('')
  const [review, setReview] = useState(null)
  const [loadState, setLoadState] = useState('loading')

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const [job, file] = await Promise.all([
          fetchReview(token, reviewId),
          fetchIndexedFileContent(token, repoId, filePath),
        ])
        if (!active) {
          return
        }
        setContent(file.content)
        setReview((job.result?.review ?? []).find((entry) => entry.file_path === filePath) ?? null)
        setLoadState('ready')
      } catch {
        if (active) {
          setLoadState('error')
        }
      }
    }

    load()
    return () => {
      active = false
    }
  }, [token, reviewId, repoId, filePath])

  return { content, review, loadState }
}
