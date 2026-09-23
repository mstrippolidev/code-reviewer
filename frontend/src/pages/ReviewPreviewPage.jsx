import { AnnotatedSource, CODE_LINE_HEIGHT } from '../components/AnnotatedSource'
import { ReviewDashboard } from '../components/ReviewDashboard'
import { buildFileReports } from '../utils/buildFileReports'
import { PREVIEW_AGENT_CATALOG, PREVIEW_JOB, PREVIEW_PROGRESS, PREVIEW_SOURCE } from '../preview/reviewFixture'

export function ReviewPreviewPage() {
  const reports = buildFileReports({
    job: PREVIEW_JOB,
    agentProgress: PREVIEW_PROGRESS,
    reviewedFiles: new Set(['api/routers/repos.py', 'api/services/billing.py']),
    failedFiles: new Set(['api/services/legacy_sync.py']),
  })
  const annotated = PREVIEW_JOB.result.review[0]

  return (
    <>
      <ReviewDashboard
        job={PREVIEW_JOB}
        reports={reports}
        catalog={PREVIEW_AGENT_CATALOG}
        onOpenAnnotated={() => {}}
      />
      <div className="page annotated-page" style={{ '--code-line-height': `${CODE_LINE_HEIGHT}px` }}>
        <header className="annotated-header">
          <div>
            <h1 className="annotated-title">{annotated.file_path}</h1>
            <p className="note">Annotated file view — preview</p>
          </div>
        </header>
        <AnnotatedSource
          content={PREVIEW_SOURCE}
          incidents={annotated.incidents}
          focusedPosition={null}
          agentNamesByCodeKey={Object.fromEntries(
            Object.values(PREVIEW_AGENT_CATALOG.agentsByCodeKey).map((agent) => [agent.code_key, agent.name])
          )}
        />
      </div>
    </>
  )
}
