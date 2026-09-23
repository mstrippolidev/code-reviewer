import { useEffect, useRef, useState } from 'react'

export function AgentInfoButton({ agent }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!open) {
      return undefined
    }
    function closeOnOutsideClick(event) {
      if (!containerRef.current?.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    return () => document.removeEventListener('mousedown', closeOnOutsideClick)
  }, [open])

  if (!agent) {
    return null
  }

  return (
    <span className="agent-info" ref={containerRef}>
      <button
        type="button"
        className="agent-info-button"
        aria-label={`What ${agent.code_key} checks`}
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation()
          setOpen((current) => !current)
        }}
      >
        i
      </button>
      {open ? (
        <span className="agent-info-popover" onClick={(event) => event.stopPropagation()}>
          <span className="agent-info-title">{agent.name}</span>
          <span className="agent-info-meta">
            weight {agent.weight} · {agent.category} agent
          </span>
          <span className="agent-info-summary">{agent.summary}</span>
          <span className="agent-info-checks-label">What it checks</span>
          <ul className="agent-info-checks">
            {agent.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </span>
      ) : null}
    </span>
  )
}
