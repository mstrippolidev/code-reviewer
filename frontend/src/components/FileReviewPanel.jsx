import { useState } from 'react'
import { AgentInfoButton } from './AgentInfoButton'
import { IncidentCard } from './IncidentCard'
import { RatingBadge } from './RatingBadge'
import { FILE_STATUS } from '../utils/buildFileReports'
import { ratingTone } from '../utils/reviewScore'

export function FileReviewPanel({ report, catalog, onOpenAnnotated }) {
  // Keyed by file so switching files drops the previous file's agent selection
  // without an effect that would re-render just to reset it.
  const [selection, setSelection] = useState({ filePath: null, codeKey: null })
  const selectedCodeKey = selection.filePath === report.filePath ? selection.codeKey : null

  const agents = buildRoster(report.agents, catalog.order)
  const selectedAgent = agents.find((agent) => agent.codeKey === selectedCodeKey) ?? null

  return (
    <section className="file-panel">
      <header className="file-panel-head">
        <div className="file-panel-title">
          <h2 title={report.filePath}>{report.filePath}</h2>
          <p className="note">
            {report.fileLines ? `Lines ${report.fileLines} · ` : ''}
            {report.incidentCounts.total} incidents across {agents.filter((a) => a.incidents.length > 0).length} agents
          </p>
        </div>
        <div className="file-panel-actions">
          <RatingBadge rating={report.rating} size="large" label="File score" />
          <button type="button" className="button" onClick={() => onOpenAnnotated(report.filePath)}>
            Open annotated file ↗
          </button>
        </div>
      </header>

      {report.status === FILE_STATUS.FAILED ? (
        <p className="note error">{report.skipReason ?? 'This file’s review failed and was dropped.'}</p>
      ) : null}

      <h3 className="file-panel-section-title">Agents</h3>
      <ul className="agent-grid">
        {agents.map((agent) => (
          <AgentChip
            key={agent.codeKey}
            agent={agent}
            catalogEntry={catalog.agentsByCodeKey[agent.codeKey]}
            isSelected={agent.codeKey === selectedCodeKey}
            onSelect={() =>
              setSelection({
                filePath: report.filePath,
                codeKey: selectedCodeKey === agent.codeKey ? null : agent.codeKey,
              })
            }
          />
        ))}
      </ul>

      {selectedAgent ? (
        <AgentIncidents
          agent={selectedAgent}
          catalogEntry={catalog.agentsByCodeKey[selectedAgent.codeKey]}
          onOpenInFile={(incident) => onOpenAnnotated(report.filePath, incident)}
        />
      ) : (
        <p className="note file-panel-hint">Pick an agent above to read what it found.</p>
      )}
    </section>
  )
}

function AgentChip({ agent, catalogEntry, isSelected, onSelect }) {
  const hasIncidents = agent.incidents.length > 0
  const tone = agentTone(agent)
  return (
    <li className={`agent-chip agent-chip-${tone}${isSelected ? ' agent-chip-selected' : ''}`} onClick={onSelect}>
      <span className="agent-chip-key">{agent.codeKey}</span>
      <AgentInfoButton agent={catalogEntry} />
      <span className={`agent-chip-score rating-${tone}`}>
        {agent.pending ? <span className="spinner" /> : scoreGlyph(agent)}
      </span>
      <span className="agent-chip-caption">
        {agent.pending
          ? 'running'
          : agent.failed
            ? 'failed to process'
            : hasIncidents
              ? `${agent.incidents.length} incident${agent.incidents.length === 1 ? '' : 's'}`
              : 'clean'}
      </span>
    </li>
  )
}

function agentTone(agent) {
  if (agent.pending || agent.failed) {
    return 'unknown'
  }
  if (typeof agent.rating === 'number') {
    return ratingTone(agent.rating)
  }
  return agent.incidents.length > 0 ? 'warn' : 'good'
}

function scoreGlyph(agent) {
  if (agent.failed) {
    return '⚠'
  }
  if (typeof agent.rating === 'number') {
    return agent.rating
  }
  return agent.incidents.length > 0 ? agent.incidents.length : '✓'
}

function AgentIncidents({ agent, catalogEntry, onOpenInFile }) {
  return (
    <div className="agent-incidents">
      <div className="agent-incidents-head">
        <h3>
          {agent.codeKey}
          {catalogEntry ? ` · ${catalogEntry.name}` : ''}
        </h3>
        {catalogEntry ? <p className="note">{catalogEntry.summary}</p> : null}
      </div>
      {agent.failed ? (
        <p className="note error">{agent.failureReason ?? 'This agent failed to process the file.'}</p>
      ) : agent.incidents.length === 0 ? (
        <p className="note">No issues found by this agent.</p>
      ) : (
        <ul className="incident-list">
          {agent.incidents.map((incident, index) => (
            <IncidentCard key={`${incident.line_position}-${index}`} incident={incident} onOpenInFile={onOpenInFile} />
          ))}
        </ul>
      )}
    </div>
  )
}

/** Renders the whole roster, not just who has reported: an agent still working is
 *  the most useful thing to show while a file is mid-review. */
function buildRoster(reportedAgents, catalogOrder) {
  const byCodeKey = new Map(reportedAgents.map((agent) => [agent.codeKey, agent]))
  const rosterKeys = catalogOrder.length > 0 ? catalogOrder : [...byCodeKey.keys()]
  const roster = rosterKeys.map(
    (codeKey) => byCodeKey.get(codeKey) ?? { codeKey, rating: null, incidents: [], pending: true }
  )
  const unlisted = reportedAgents.filter((agent) => !rosterKeys.includes(agent.codeKey))
  return [...roster, ...unlisted]
}
