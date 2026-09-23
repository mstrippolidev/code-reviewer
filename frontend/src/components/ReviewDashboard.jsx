import { useState } from 'react'
import { FileReviewPanel } from './FileReviewPanel'
import { ReviewFileList } from './ReviewFileList'
import { ReviewSummary } from './ReviewSummary'
import { FILE_STATUS } from '../utils/buildFileReports'

export function ReviewDashboard({ job, reports, catalog, onOpenAnnotated }) {
  const [pickedFilePath, setPickedFilePath] = useState(null)
  const selectedReport = reports.find((report) => report.filePath === pickedFilePath) ?? defaultReport(reports)
  const agentCount = catalog.order.length || 14

  return (
    <div className="page review-dashboard">
      <div className="review-dashboard-head">
        <h1>Review</h1>
        {job.status === 'failed' && job.status_reason ? <p className="note error">{job.status_reason}</p> : null}
      </div>

      <ReviewSummary job={job} reports={reports} />

      <div className="review-dashboard-body">
        <aside className="review-dashboard-files">
          <h2 className="review-dashboard-pane-title">Files</h2>
          <ReviewFileList
            reports={reports}
            agentCount={agentCount}
            selectedFilePath={selectedReport?.filePath ?? null}
            onSelect={setPickedFilePath}
          />
        </aside>

        <main className="review-dashboard-detail">
          {selectedReport ? (
            <FileReviewPanel report={selectedReport} catalog={catalog} onOpenAnnotated={onOpenAnnotated} />
          ) : (
            <p className="note review-dashboard-empty">
              No file has been reviewed yet. Pick one on the left as soon as it starts.
            </p>
          )}
        </main>
      </div>
    </div>
  )
}

function defaultReport(reports) {
  return (
    reports.find((report) => report.status === FILE_STATUS.RUNNING) ??
    reports.find((report) => report.incidentCounts.total > 0) ??
    reports.find((report) => report.status === FILE_STATUS.REVIEWED) ??
    null
  )
}
