import { formatLineRange } from '../utils/lineRange'

export function IncidentCard({ incident, agentName, onOpenInFile }) {
  return (
    <li className={`incident-card priority-${incident.priority}`}>
      <div className="incident-card-head">
        <span className={`priority-tag priority-tag-${incident.priority}`}>{incident.priority}</span>
        <span className="incident-lines" title="Location in the file">
          {formatLineRange(incident.line_position)}
        </span>
        {agentName ? <span className="incident-agent">{agentName}</span> : null}
        {onOpenInFile ? (
          <button type="button" className="incident-open-button" onClick={() => onOpenInFile(incident)}>
            View in file ↗
          </button>
        ) : null}
      </div>
      <p className="incident-description">{incident.description}</p>
      <p className="incident-advice">
        <span className="incident-advice-label">Fix</span>
        {incident.advice}
      </p>
    </li>
  )
}
