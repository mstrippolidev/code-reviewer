import { useParams } from 'react-router-dom'
import { TOKEN_STORAGE_KEY } from '../api/client'
import { ReviewDashboard } from '../components/ReviewDashboard'
import { useAgentCatalog } from '../hooks/useAgentCatalog'
import { useReviewStream } from '../hooks/useReviewStream'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'
import { buildFileReports } from '../utils/buildFileReports'

export function ReviewPage() {
  const { reviewId } = useParams()
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const handleUnauthorized = useUnauthorizedHandler()
  const { job, reviewedFiles, failedFiles, agentProgress, connectionStatus } = useReviewStream(
    token,
    reviewId,
    handleUnauthorized
  )
  const catalog = useAgentCatalog(token)

  if (connectionStatus === 'error') {
    return <p className="page centered note error">Could not connect to this review.</p>
  }
  if (!job) {
    return <p className="page centered">Loading review…</p>
  }

  const reports = buildFileReports({ job, agentProgress, reviewedFiles, failedFiles, catalog })

  return (
    <ReviewDashboard
      job={job}
      reports={reports}
      catalog={catalog}
      onOpenAnnotated={(filePath, incident) => openAnnotatedFile(reviewId, job.repo_id, filePath, incident)}
    />
  )
}

function openAnnotatedFile(reviewId, repoId, filePath, incident) {
  const params = new URLSearchParams({ path: filePath })
  if (repoId !== null) {
    params.set('repo_id', String(repoId))
  }
  if (incident) {
    params.set('focus', incident.line_position)
  }
  window.open(`/reviews/${reviewId}/file?${params.toString()}`, '_blank', 'noopener')
}
