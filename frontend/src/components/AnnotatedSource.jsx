import { useLayoutEffect, useRef, useState } from 'react'
import { formatLineRange, parseLineRange } from '../utils/lineRange'

export const CODE_LINE_HEIGHT = 22

const PRIORITY_RANK = { critical: 4, high: 3, medium: 2, low: 1 }
const CARD_GAP = 8

export function AnnotatedSource({ content, incidents, focusedPosition, agentNamesByCodeKey }) {
  const lines = content.split('\n')
  const annotations = buildAnnotations(incidents)
  const markers = buildLineMarkers(annotations)
  // Grouped here, not inside IncidentMargin: IncidentMargin has its own
  // paging state, so deriving groups from `annotations` inside its own body
  // would produce a new array reference on every one of ITS re-renders
  // (including the ones its own setState calls trigger) — a dependency
  // that never stabilizes, which is exactly what caused the infinite
  // render loop this shipped with the first time. Computed once per
  // AnnotatedSource render instead, the same way `annotations` itself
  // already stays stable across IncidentMargin's own re-renders.
  const groups = groupOverlappingAnnotations(annotations)

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
      <IncidentMargin groups={groups} focusedPosition={focusedPosition} agentNamesByCodeKey={agentNamesByCodeKey} />
    </div>
  )
}

function IncidentMargin({ groups, focusedPosition, agentNamesByCodeKey }) {
  const cardRefs = useRef([])
  const [tops, setTops] = useState([])
  const [pageByGroup, setPageByGroup] = useState({})

  useLayoutEffect(() => {
    // Cards are anchored to their own start line, then pushed down just far enough
    // to clear the card above — the same behaviour as margin comments in a document.
    // Depends on pageByGroup too: paging a grouped card to a longer/shorter
    // incident changes that card's own height, which can shift every card below it.
    let cursor = 0
    const stacked = groups.map((group, index) => {
      const anchor = (group.range.start - 1) * CODE_LINE_HEIGHT
      const top = Math.max(anchor, cursor)
      cursor = top + (cardRefs.current[index]?.offsetHeight ?? 0) + CARD_GAP
      return top
    })
    setTops(stacked)
  }, [groups, pageByGroup])

  return (
    <div className="annotated-margin">
      {groups.map((group, index) => {
        const pageIndex = Math.min(pageByGroup[index] ?? 0, group.annotations.length - 1)
        const { incident } = group.annotations[pageIndex]
        const isFocused = group.annotations.some((annotation) => annotation.incident.line_position === focusedPosition)
        const turnPage = (delta) =>
          setPageByGroup((previous) => ({
            ...previous,
            [index]: mod(pageIndex + delta, group.annotations.length),
          }))

        return (
          <article
            key={`${group.range.start}-${group.range.end}-${index}`}
            ref={(element) => {
              cardRefs.current[index] = element
            }}
            className={`margin-card priority-${incident.priority}${isFocused ? ' margin-card-focused' : ''}`}
            style={{ top: `${tops[index] ?? (group.range.start - 1) * CODE_LINE_HEIGHT}px` }}
          >
            <div className="margin-card-head">
              <span className={`priority-tag priority-tag-${incident.priority}`}>{incident.priority}</span>
              <span className="margin-card-lines">{formatLineRange(incident.line_position)}</span>
              {group.annotations.length > 1 ? (
                <div className="margin-card-pager">
                  <button
                    type="button"
                    className="margin-card-pager-button"
                    onClick={() => turnPage(-1)}
                    aria-label="Previous incident on this line"
                  >
                    ‹
                  </button>
                  <span className="margin-card-pager-count">
                    {pageIndex + 1} of {group.annotations.length}
                  </span>
                  <button
                    type="button"
                    className="margin-card-pager-button"
                    onClick={() => turnPage(1)}
                    aria-label="Next incident on this line"
                  >
                    ›
                  </button>
                </div>
              ) : null}
            </div>
            {incident.code_key ? (
              <span className="margin-card-agent">
                {incident.code_key}
                {agentNamesByCodeKey[incident.code_key] ? ` · ${agentNamesByCodeKey[incident.code_key]}` : ''}
              </span>
            ) : null}
            <p className="margin-card-description">{incident.description}</p>
            <p className="margin-card-advice">{incident.advice}</p>
          </article>
        )
      })}
    </div>
  )
}

function mod(value, size) {
  return ((value % size) + size) % size
}

// Same-range/overlapping incidents are a genuinely common case — a messy
// function often draws COH, COUP, CMPLX, and ERR all at once — and one card
// per incident then produces a long run of near-identical cards anchored at
// the same spot. annotations arrives sorted by range.start (buildAnnotations),
// so a single left-to-right merge pass groups any incident whose start falls
// within the running group's own range, the same way "40-50" and "45-45"
// merge but "46-50" next to "40-45" stays a separate card.
function groupOverlappingAnnotations(annotations) {
  const groups = []
  for (const annotation of annotations) {
    const last = groups[groups.length - 1]
    if (last && annotation.range.start <= last.range.end) {
      last.annotations.push(annotation)
      last.range.end = Math.max(last.range.end, annotation.range.end)
    } else {
      groups.push({ range: { ...annotation.range }, annotations: [annotation] })
    }
  }
  return groups
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
