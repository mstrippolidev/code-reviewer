import { Navigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY } from '../api/client'
import { useAuth } from '../auth/useAuth'

export function RequireAuth({ children, allowGuest = false }) {
  const { status } = useAuth()
  const isGuest = allowGuest && localStorage.getItem(GUEST_STORAGE_KEY) !== null

  if (status === 'authenticated' || isGuest) {
    return children
  }
  if (status === 'loading') {
    return <p className="page centered">Loading…</p>
  }
  if (status === 'error') {
    return <p className="page centered note error">Could not reach the server.</p>
  }
  return <Navigate to="/" replace />
}
