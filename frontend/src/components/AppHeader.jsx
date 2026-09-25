import { Link } from 'react-router-dom'

export function AppHeader() {
  return (
    <header className="app-header">
      <div className="app-header-inner">
        <Link className="app-logo" to="/repos">
          <span className="app-logo-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
              <path
                d="M9 6 4 12l5 6M15 6l5 6-5 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <span className="app-logo-text">Code Reviewer</span>
        </Link>
        <a className="app-header-link" href="https://mstrippolidev.com" target="_blank" rel="noopener noreferrer">
          by mstrippoli <span aria-hidden="true">↗</span>
        </a>
      </div>
    </header>
  )
}
