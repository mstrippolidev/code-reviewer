import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY, startGuestSession } from '../api/client'

export function LoginPage() {
  const navigate = useNavigate()
  const [startingGuest, setStartingGuest] = useState(false)
  const [guestError, setGuestError] = useState(null)

  async function handleContinueAsGuest() {
    setGuestError(null)
    setStartingGuest(true)
    try {
      await startGuestSession()
      localStorage.setItem(GUEST_STORAGE_KEY, 'true')
      navigate('/guest')
    } catch {
      setGuestError('Could not start a guest session. Please try again.')
    } finally {
      setStartingGuest(false)
    }
  }

  return (
    <div className="page centered">
      <div className="auth-card">
        <h2>Sign in to get started</h2>
        <p className="auth-card-subtitle">Connect your GitHub account to register a repo for review.</p>
        <div className="button-stack">
          <Link className="button" to="/login">
            Log in to GitHub
          </Link>
          <button
            className={`button${startingGuest ? ' disabled' : ''}`}
            type="button"
            disabled={startingGuest}
            onClick={handleContinueAsGuest}
          >
            {startingGuest ? 'Starting…' : 'Continue as Guest'}
          </button>
          {guestError ? (
            <p className="note error">{guestError}</p>
          ) : (
            <p className="note">Try it on example files or your own — no GitHub account needed.</p>
          )}
        </div>
      </div>
    </div>
  )
}
