import { useEffect, useState } from 'react'
import { fetchRepoBranches } from '../api/client'

export function BranchSelect({ token, fullName, value, onChange, disabled }) {
  const [branches, setBranches] = useState([])
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    fetchRepoBranches(token, fullName)
      .then((fetchedBranches) => {
        if (!cancelled) {
          setBranches(fetchedBranches)
          setStatus('ready')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus('error')
        }
      })
    return () => {
      cancelled = true
    }
  }, [token, fullName])

  if (status === 'loading') {
    return <p className="note">Loading branches…</p>
  }
  if (status === 'error') {
    return <p className="note error">Could not load branches for this repo.</p>
  }

  return (
    <select className="branch-select" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
      {branches.map((branch) => (
        <option key={branch} value={branch}>
          {branch}
        </option>
      ))}
    </select>
  )
}
