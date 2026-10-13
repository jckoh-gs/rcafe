import { useState } from 'react'
import type { FormEvent } from 'react'
import './LoginForm.css'

interface Props {
  onSubmit: (username: string, password: string) => Promise<string | null>
}

export function LoginForm({ onSubmit }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setError(null)
    const failure = await onSubmit(username.trim(), password)
    setSending(false)
    if (failure) {
      setError(failure)
      setPassword('')
    }
  }

  return (
    <form className="login" onSubmit={(event) => void submit(event)} aria-labelledby="login-title">
      <h2 id="login-title" className="login__title">
        관리자 로그인
      </h2>
      <label className="login__field">
        <span>아이디</span>
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
        />
      </label>
      <label className="login__field">
        <span>비밀번호</span>
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      {error && (
        <p className="login__error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn--primary" disabled={sending}>
        {sending ? '확인하는 중…' : '로그인'}
      </button>
      <p className="login__note">
        아직 HTTPS가 아니라서 비밀번호가 암호화되지 않아요. 믿을 수 있는 네트워크에서만 로그인하세요.
      </p>
    </form>
  )
}
