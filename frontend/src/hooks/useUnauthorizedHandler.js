import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { GUEST_STORAGE_KEY, TOKEN_STORAGE_KEY } from '../api/client'

export function useUnauthorizedHandler() {
  const navigate = useNavigate()

  return useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    localStorage.removeItem(GUEST_STORAGE_KEY)
    navigate('/', { replace: true })
  }, [navigate])
}
