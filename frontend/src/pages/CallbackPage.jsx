import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { TOKEN_STORAGE_KEY } from '../api/client'

export function CallbackPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  useEffect(() => {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    }
    navigate('/repos', { replace: true })
  }, [token, navigate])

  return <p className="page centered">Signing you in...</p>
}
