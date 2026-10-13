import { useCallback, useEffect, useState } from 'react'
import { adminLogin, adminLogout, ApiError, fetchAdminSession } from '../../../shared/api'

export type AdminSession =
  | { phase: 'checking' }
  | { phase: 'anonymous' }
  | { phase: 'signed-in'; user: string }
  /** The server has no admin account configured (it answers 404), or could not be reached. */
  | { phase: 'unavailable'; message: string }

/** Who is signed in as the administrator: checked on load, changed by `signIn` / `signOut`. */
export function useAdminSession() {
  const [session, setSession] = useState<AdminSession>({ phase: 'checking' })

  useEffect(() => {
    let alive = true
    fetchAdminSession()
      .then(({ user }) => alive && setSession({ phase: 'signed-in', user }))
      .catch((error: unknown) => {
        if (!alive) return
        if (error instanceof ApiError && error.status === 401) setSession({ phase: 'anonymous' })
        else if (error instanceof ApiError && error.status === 404)
          setSession({ phase: 'unavailable', message: '관리자 기능이 꺼져 있어요.' })
        else setSession({ phase: 'unavailable', message: '서버에 연결하지 못했어요.' })
      })
    return () => {
      alive = false
    }
  }, [])

  /** Resolves with an error message to show, or null when signed in. */
  const signIn = useCallback(async (username: string, password: string): Promise<string | null> => {
    try {
      const { user } = await adminLogin(username, password)
      setSession({ phase: 'signed-in', user })
      return null
    } catch (error) {
      return error instanceof ApiError ? error.message : '로그인하지 못했어요.'
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await adminLogout()
    } finally {
      setSession({ phase: 'anonymous' }) // the cookie is gone or the server is; either way, leave
    }
  }, [])

  const expire = useCallback(() => setSession({ phase: 'anonymous' }), [])

  return { session, signIn, signOut, expire }
}
