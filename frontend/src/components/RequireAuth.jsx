import { Navigate } from 'react-router-dom'
import { TOKEN_STORAGE_KEY } from '../api/client'

export function RequireAuth({ children }) {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)

  if (!token) {
    return <Navigate to="/" replace />
  }

  return children
}
