import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY } from '../api/client'
import { useAuth } from '../auth/useAuth'

export function useUnauthorizedHandler() {
  const navigate = useNavigate()
  const { markSignedOut } = useAuth()

  return useCallback(() => {
    localStorage.removeItem(GUEST_STORAGE_KEY)
    markSignedOut()
    navigate('/', { replace: true })
  }, [navigate, markSignedOut])
}
