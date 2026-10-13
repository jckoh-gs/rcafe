import { useEffect } from 'react'
import { LoginForm, useAdminSession } from '../../../features/admin-session'
import { AdminRequests } from '../../../widgets/admin-requests'
import './AdminPage.css'

/** `/admin`: sign in, then manage the collection requests. Not linked from anywhere. */
export function AdminPage() {
  const { session, signIn, signOut, expire } = useAdminSession()

  useEffect(() => {
    const previous = document.title
    document.title = 'rcafe 관리자'
    const robots = document.createElement('meta')
    robots.name = 'robots'
    robots.content = 'noindex, nofollow'
    document.head.appendChild(robots)
    return () => {
      document.title = previous
      robots.remove()
    }
  }, [])

  return (
    <div className="admin">
      <header className="admin__header">
        <h1 className="admin__title">rcafe 관리자</h1>
        {session.phase === 'signed-in' && (
          <div className="admin__who">
            <span>{session.user}</span>
            <button type="button" className="btn btn--ghost" onClick={() => void signOut()}>
              로그아웃
            </button>
          </div>
        )}
      </header>
      <main>
        {session.phase === 'checking' && <p className="admin__message">확인하는 중…</p>}
        {session.phase === 'unavailable' && <p className="admin__message">{session.message}</p>}
        {session.phase === 'anonymous' && <LoginForm onSubmit={signIn} />}
        {session.phase === 'signed-in' && <AdminRequests onSessionExpired={expire} />}
      </main>
    </div>
  )
}
