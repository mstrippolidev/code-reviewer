import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

export function CallbackPage() {
  const navigate = useNavigate()
  const { refresh } = useAuth()

  useEffect(() => {
    refresh().then(() => navigate('/repos', { replace: true }))
  }, [refresh, navigate])

  return <p className="page centered">Signing you in...</p>
}
