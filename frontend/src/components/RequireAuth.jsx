import { Navigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY, TOKEN_STORAGE_KEY } from '../api/client'

export function RequireAuth({ children, allowGuest = false }) {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const isGuest = allowGuest && localStorage.getItem(GUEST_STORAGE_KEY) !== null

  if (!token && !isGuest) {
    return <Navigate to="/" replace />
  }

  return children
}
