import { Link } from 'react-router-dom'

export function LoginPage() {
  return (
    <div className="page centered">
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
  )
}
