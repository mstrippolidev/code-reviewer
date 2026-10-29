import { useContext } from 'react'
import { AuthContext } from './AuthContext'

export function useAuth() {
  const auth = useContext(AuthContext)
  if (auth === null) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return auth
}
