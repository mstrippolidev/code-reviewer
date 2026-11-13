export function CodePane({ side, title }) {
  const lines = side.code.split('\n')

  return (
    <section className="code-pane">
      <header className="code-pane-header">
        <span className="code-pane-title">{title}</span>
        <span className="code-pane-name">{side.chunk_name}</span>
        <span className="code-pane-path">
          {side.file_path}:{side.start_line}-{side.end_line}
        </span>
      </header>
      <pre className="code-pane-body">
        {lines.map((line, index) => (
          <div className="code-line" key={index}>
            <span className="code-line-number">{side.start_line + index}</span>
            <span className="code-line-text">{line || ' '}</span>
          </div>
        ))}
      </pre>
    </section>
  )
}
