import { Link } from 'react-router-dom'

export function LoginPage() {
  return (
    <div className="page centered">
      <div className="auth-card">
        <h2>Sign in to get started</h2>
        <p className="auth-card-subtitle">Connect your GitHub account to register a repo for review.</p>
        <div className="button-stack">
          <Link className="button" to="/login">
            Log in to GitHub
          </Link>
          <button className="button disabled" type="button" disabled>
            Continue as Guest
          </button>
          <p className="note">Guest mode isn't built yet</p>
        </div>
      </div>
    </div>
  )
}
