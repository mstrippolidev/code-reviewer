import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { UnauthorizedError, fetchOAuthClient, submitOAuthDecision } from '../api/client'

const AUTHORIZE_PARAMETERS = [
  'response_type',
  'client_id',
  'redirect_uri',
  'code_challenge',
  'code_challenge_method',
  'state',
]

function readAuthorizeParams(searchParams) {
  return Object.fromEntries(
    AUTHORIZE_PARAMETERS.filter((name) => searchParams.has(name)).map((name) => [name, searchParams.get(name)]),
  )
}

export function OAuthConsentPage() {
  const [searchParams] = useSearchParams()
  const [authorizeParams] = useState(() => readAuthorizeParams(searchParams))
  const [clientName, setClientName] = useState(null)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchOAuthClient(authorizeParams.client_id)
      .then((client) => setClientName(client.client_name))
      .catch((fetchError) => setError(fetchError.message))
  }, [authorizeParams.client_id])

  async function decide(approve) {
    setSubmitting(true)
    try {
      window.location.assign(await submitOAuthDecision(authorizeParams, approve))
    } catch (decisionError) {
      setError(
        decisionError instanceof UnauthorizedError
          ? 'Your session expired. Log in again and retry the connection from your app.'
          : decisionError.message,
      )
      setSubmitting(false)
    }
  }

  if (error) {
    return (
      <div className="page centered">
        <div className="auth-card">
          <h2>Could not connect</h2>
          <p className="auth-card-subtitle">{error}</p>
          <Link className="button" to="/">
            Back to login
          </Link>
        </div>
      </div>
    )
  }

  if (clientName === null) {
    return <p className="page centered">Loading...</p>
  }

  return (
    <div className="page centered">
      <div className="auth-card">
        <h2>Allow access?</h2>
        <p className="auth-card-subtitle">
          <strong>{clientName}</strong> wants to use your Code Reviewer account: review code, and read the repos you
          registered.
        </p>
        <p className="auth-card-subtitle">After you decide, you will be sent back to {authorizeParams.redirect_uri}</p>
        <div className="button-stack">
          <button type="button" className="button" disabled={submitting} onClick={() => decide(true)}>
            Allow
          </button>
          <button type="button" className="repo-control-button" disabled={submitting} onClick={() => decide(false)}>
            Deny
          </button>
        </div>
      </div>
    </div>
  )
}
