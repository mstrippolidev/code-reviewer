import { Link, useLocation } from 'react-router-dom'
import { GUEST_STORAGE_KEY, TOKEN_STORAGE_KEY } from '../api/client'

function logoDestination() {
  if (localStorage.getItem(TOKEN_STORAGE_KEY)) {
    return '/repos'
  }
  if (localStorage.getItem(GUEST_STORAGE_KEY)) {
    return '/guest'
  }
  return '/'
}

export function AppHeader() {
  // Login/guest state lives in localStorage, which React doesn't observe — subscribing to
  // location re-renders this on every navigation, so the destination reflects the latest state.
  useLocation()
  return (
    <header className="app-header">
      <div className="app-header-inner">
        <Link className="app-logo" to={logoDestination()}>
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
