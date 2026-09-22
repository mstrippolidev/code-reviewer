import { useState } from 'react'
import { githubLoginUrl } from '../api/client'

const ACCESS_LEVELS = [
  { value: 'all', label: 'All repositories' },
  { value: 'public', label: 'Public repositories only' },
]

export function GitHubAccessLevelPage() {
  const [accessLevel, setAccessLevel] = useState('all')

  return (
    <div className="page centered">
      <div className="auth-card">
        <h2>Choose repository access</h2>
        <p className="auth-card-subtitle">You can change this later by logging in again.</p>
        <div className="button-stack">
          <fieldset className="access-level-choices">
            <legend>What should this app be able to see?</legend>
            {ACCESS_LEVELS.map(({ value, label }) => (
              <label key={value} className="radio-option">
                <input
                  type="radio"
                  name="access_level"
                  value={value}
                  checked={accessLevel === value}
                  onChange={() => setAccessLevel(value)}
                />
                {label}
              </label>
            ))}
          </fieldset>
          <a className="button" href={githubLoginUrl(accessLevel)}>
            Enter to GitHub
          </a>
        </div>
      </div>
    </div>
  )
}
