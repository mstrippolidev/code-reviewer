import { FILE_STATUS } from '../utils/buildFileReports'
import { ratingTone } from '../utils/reviewScore'

const STATUS_LABELS = {
  [FILE_STATUS.REVIEWED]: 'Reviewed',
  [FILE_STATUS.FAILED]: 'Failed',
  [FILE_STATUS.RUNNING]: 'Reviewing',
  [FILE_STATUS.PENDING]: 'Queued',
  [FILE_STATUS.EXCLUDED]: 'Not reviewed',
}

export function ReviewFileList({ reports, agentCount, selectedFilePath, onSelect }) {
  return (
    <ul className="review-file-cards">
      {reports.map((report) => (
        <FileCard
          key={report.filePath}
          report={report}
          agentCount={agentCount}
          isSelected={report.filePath === selectedFilePath}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}

function FileCard({ report, agentCount, isSelected, onSelect }) {
  const isOpenable = report.status !== FILE_STATUS.PENDING && report.status !== FILE_STATUS.EXCLUDED
  return (
    <li
      className={`file-card file-card-${report.status}${isSelected ? ' file-card-selected' : ''}${
        isOpenable ? ' clickable' : ''
      }`}
      onClick={() => isOpenable && onSelect(report.filePath)}
    >
      <div className="file-card-head">
        <StatusGlyph status={report.status} />
        <span className="file-card-path" title={report.filePath}>
          {report.filePath}
        </span>
        {typeof report.rating === 'number' ? (
          <span className={`file-card-score rating-${ratingTone(report.rating)}`}>{report.rating}</span>
        ) : null}
      </div>
      <div className="file-card-meta">
        <span className="file-card-status">{STATUS_LABELS[report.status]}</span>
        {report.status === FILE_STATUS.RUNNING ? (
          <span className="file-card-agents">
            {report.agentsReported}/{agentCount} agents in
          </span>
        ) : null}
        {report.incidentCounts.total > 0 ? (
          <span className="file-card-incidents">{report.incidentCounts.total} incidents</span>
        ) : null}
      </div>
      {report.skipReason ? <p className="file-card-reason">{report.skipReason}</p> : null}
      <IncidentStrip counts={report.incidentCounts} />
    </li>
  )
}

function StatusGlyph({ status }) {
  if (status === FILE_STATUS.RUNNING) {
    return <span className="spinner" />
  }
  const glyph = {
    [FILE_STATUS.REVIEWED]: '✓',
    [FILE_STATUS.FAILED]: '✗',
    [FILE_STATUS.EXCLUDED]: '—',
    [FILE_STATUS.PENDING]: '⏳',
  }[status]
  return <span className={`file-card-glyph file-card-glyph-${status}`}>{glyph}</span>
}

function IncidentStrip({ counts }) {
  if (counts.total === 0) {
    return null
  }
  return (
    <div className="incident-strip">
      {['critical', 'high', 'medium', 'low'].map((priority) =>
        counts[priority] > 0 ? (
          <span
            key={priority}
            className={`incident-strip-segment priority-tag-${priority}`}
            style={{ flexGrow: counts[priority] }}
            title={`${counts[priority]} ${priority}`}
          />
        ) : null
      )}
    </div>
  )
}
