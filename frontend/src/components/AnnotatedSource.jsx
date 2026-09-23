import { useLayoutEffect, useRef, useState } from 'react'
import { formatLineRange, parseLineRange } from '../utils/lineRange'

export const CODE_LINE_HEIGHT = 22

const PRIORITY_RANK = { critical: 4, high: 3, medium: 2, low: 1 }
const CARD_GAP = 8

export function AnnotatedSource({ content, incidents, focusedPosition, agentNamesByCodeKey }) {
  const lines = content.split('\n')
  const annotations = buildAnnotations(incidents)
  const markers = buildLineMarkers(annotations)

  return (
    <div className="annotated-source">
      <div className="annotated-code">
        {lines.map((text, index) => {
          const lineNumber = index + 1
          const marker = markers.get(lineNumber)
          return (
            <div
              key={lineNumber}
              id={`code-line-${lineNumber}`}
              className={`code-line${marker ? ` code-line-flagged priority-line-${marker}` : ''}`}
            >
              <span className="code-line-number">{lineNumber}</span>
              <span className="code-line-text">{text === '' ? ' ' : text}</span>
            </div>
          )
        })}
      </div>
      <IncidentMargin
        annotations={annotations}
        focusedPosition={focusedPosition}
        agentNamesByCodeKey={agentNamesByCodeKey}
      />
    </div>
  )
}

function IncidentMargin({ annotations, focusedPosition, agentNamesByCodeKey }) {
  const cardRefs = useRef([])
  const [tops, setTops] = useState([])

  useLayoutEffect(() => {
    // Cards are anchored to their own start line, then pushed down just far enough
    // to clear the card above — the same behaviour as margin comments in a document.
    let cursor = 0
    const stacked = annotations.map((annotation, index) => {
      const anchor = (annotation.range.start - 1) * CODE_LINE_HEIGHT
      const top = Math.max(anchor, cursor)
      cursor = top + (cardRefs.current[index]?.offsetHeight ?? 0) + CARD_GAP
      return top
    })
    setTops(stacked)
  }, [annotations])

  return (
    <div className="annotated-margin">
      {annotations.map((annotation, index) => (
        <article
          key={`${annotation.incident.line_position}-${index}`}
          ref={(element) => {
            cardRefs.current[index] = element
          }}
          className={`margin-card priority-${annotation.incident.priority}${
            annotation.incident.line_position === focusedPosition ? ' margin-card-focused' : ''
          }`}
          style={{ top: `${tops[index] ?? (annotation.range.start - 1) * CODE_LINE_HEIGHT}px` }}
        >
          <div className="margin-card-head">
            <span className={`priority-tag priority-tag-${annotation.incident.priority}`}>
              {annotation.incident.priority}
            </span>
            <span className="margin-card-lines">{formatLineRange(annotation.incident.line_position)}</span>
          </div>
          {annotation.incident.code_key ? (
            <span className="margin-card-agent">
              {annotation.incident.code_key}
              {agentNamesByCodeKey[annotation.incident.code_key]
                ? ` · ${agentNamesByCodeKey[annotation.incident.code_key]}`
                : ''}
            </span>
          ) : null}
          <p className="margin-card-description">{annotation.incident.description}</p>
          <p className="margin-card-advice">{annotation.incident.advice}</p>
        </article>
      ))}
    </div>
  )
}

function buildAnnotations(incidents) {
  return incidents
    .map((incident) => ({ incident, range: parseLineRange(incident.line_position) }))
    .filter((annotation) => annotation.range !== null)
    .sort((left, right) => left.range.start - right.range.start)
}

function buildLineMarkers(annotations) {
  const markers = new Map()
  for (const { incident, range } of annotations) {
    for (let line = range.start; line <= range.end; line += 1) {
      const current = markers.get(line)
      if (!current || PRIORITY_RANK[incident.priority] > PRIORITY_RANK[current]) {
        markers.set(line, incident.priority)
      }
    }
  }
  return markers
}
