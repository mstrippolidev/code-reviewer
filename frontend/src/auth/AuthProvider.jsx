import { useCallback, useEffect, useMemo, useState } from 'react'
import { UnauthorizedError, fetchCurrentUser, logout } from '../api/client'
import { AuthContext } from './AuthContext'

const SIGNED_OUT = { status: 'anonymous', user: null }

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', user: null })

  const refresh = useCallback(async () => {
    try {
      setState({ status: 'authenticated', user: await fetchCurrentUser() })
    } catch (error) {
      setState(error instanceof UnauthorizedError ? SIGNED_OUT : { status: 'error', user: null })
    }
  }, [])

  const markSignedOut = useCallback(() => setState(SIGNED_OUT), [])

  const signOut = useCallback(async () => {
    await logout()
    setState(SIGNED_OUT)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const value = useMemo(
    () => ({ ...state, refresh, markSignedOut, signOut }),
    [state, refresh, markSignedOut, signOut]
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
