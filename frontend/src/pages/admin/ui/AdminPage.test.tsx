import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AdminRequest, AdminStatus } from '../../../shared/api'
import { AdminPage } from './AdminPage'

function request(id: number, status: AdminStatus, extra: Partial<AdminRequest> = {}): AdminRequest {
  return {
    id,
    cell_key: `3748:1267${id}`,
    lat: 37.48 + id / 100,
    lng: 126.78,
    radius_m: 1500,
    status,
    request_count: id + 1,
    requested_at: '2026-10-10T04:00:00+00:00',
    last_requested_at: '2026-10-10T05:00:00+00:00',
    started_at: null,
    finished_at: null,
    cafes_found: null,
    cafes_nearby: 0,
    note: null,
    ...extra,
  }
}

interface Fake {
  signedIn: boolean
  adminOff: boolean
  collectorRunning: boolean
  items: AdminRequest[]
  calls: string[]
  noGuard: string[]
}

function startServer(partial: Partial<Fake> = {}) {
  const state: Fake = {
    signedIn: false,
    adminOff: false,
    collectorRunning: false,
    items: [
      request(1, 'pending', { note: '시간이 부족해서 다음에 이어서 해요' }),
      request(2, 'failed', { note: 'boom' }),
      request(3, 'done', { cafes_found: 84, cafes_nearby: 84, finished_at: '2026-10-10T06:00:00+00:00' }),
    ],
    calls: [],
    noGuard: [],
    ...partial,
  }
  const reply = (status: number, body?: unknown) =>
    Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status }))

  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = url.replace('/api/v1/admin', '')
      state.calls.push(`${method} ${path}`)
      if ((init?.headers as Record<string, string>)['X-Admin-Request'] !== '1') state.noGuard.push(path)
      if (state.adminOff) return reply(404, { detail: 'Not Found' })

      if (method === 'POST' && path === '/login') {
        const { password } = JSON.parse(String(init?.body)) as { password: string }
        if (password !== 'right-password') {
          return reply(401, { detail: '아이디 또는 비밀번호가 맞지 않아요.' })
        }
        state.signedIn = true
        return reply(200, { user: 'admin' })
      }
      if (!state.signedIn) return reply(401, { detail: '로그인이 필요해요.' })
      if (path === '/session') return reply(200, { user: 'admin' })
      if (method === 'POST' && path === '/logout') {
        state.signedIn = false
        return reply(204)
      }
      if (method === 'GET' && path === '/collection-requests') {
        const counts = { pending: 0, running: 0, done: 0, failed: 0 }
        state.items.forEach((r) => (counts[r.status] += 1))
        return reply(200, { collector_running: state.collectorRunning, counts, items: state.items })
      }
      const id = Number(/\/collection-requests\/(\d+)/.exec(path)?.[1])
      if (method === 'DELETE') {
        state.items = state.items.filter((r) => r.id !== id)
        return reply(204)
      }
      if (method === 'POST' && path.endsWith('/requeue')) {
        state.items = state.items.map((r) => (r.id === id ? { ...r, status: 'pending' } : r))
        return reply(204)
      }
      if (method === 'POST' && path.endsWith('/run')) {
        state.collectorRunning = true
        state.items = state.items.map((r) => (r.id === id ? { ...r, status: 'running' } : r))
        return reply(202, { job: 'aicafe-collect-now-1-1010' })
      }
      return reply(404, { detail: 'unknown' })
    }),
  )
  return state
}

afterEach(() => vi.unstubAllGlobals())

describe('AdminPage', () => {
  it('asks for a sign-in, refuses a wrong password, and then shows the queue', async () => {
    const server = startServer()
    render(<AdminPage />)

    await screen.findByRole('heading', { name: '관리자 로그인' })
    await userEvent.type(screen.getByLabelText('아이디'), 'admin')
    await userEvent.type(screen.getByLabelText('비밀번호'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: '로그인' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('아이디 또는 비밀번호가 맞지 않아요.')
    expect(screen.getByLabelText('비밀번호')).toHaveValue('') // the wrong password is not kept

    await userEvent.type(screen.getByLabelText('비밀번호'), 'right-password')
    await userEvent.click(screen.getByRole('button', { name: '로그인' }))

    expect(await screen.findByText('수집 요청 3건')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()
    expect(server.noGuard).toEqual([]) // every call carried the admin header
  })

  it('lists the requests with their state and filters by status', async () => {
    startServer({ signedIn: true })
    render(<AdminPage />)

    expect(await screen.findByText('수집 요청 3건')).toBeInTheDocument()
    expect(screen.getByText('시간이 부족해서 다음에 이어서 해요')).toBeInTheDocument()
    expect(screen.getByText('수집 84곳')).toBeInTheDocument()
    expect(screen.getByText(/매일 새벽 3시 30분에 처리돼요/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /실패/ }))
    expect(screen.getByText('수집 요청 1건')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(screen.queryByText('수집 84곳')).not.toBeInTheDocument()
  })

  it('deletes a request only after a second confirmation', async () => {
    const server = startServer({ signedIn: true })
    render(<AdminPage />)
    await screen.findByText('수집 요청 3건')

    await userEvent.click(screen.getByRole('button', { name: '3748:12671 삭제' }))
    expect(server.calls.some((c) => c.startsWith('DELETE'))).toBe(false) // not yet
    await userEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(screen.getByText('수집 요청 3건')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '3748:12671 삭제' }))
    await userEvent.click(screen.getByRole('button', { name: '삭제 확정' }))

    expect(await screen.findByText('수집 요청 2건')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('요청을 삭제했어요.')
    expect(server.calls).toContain('DELETE /collection-requests/1')
  })

  it('runs a request now, then holds the other runs while the collector works', async () => {
    const server = startServer({ signedIn: true })
    render(<AdminPage />)
    await screen.findByText('수집 요청 3건')

    await userEvent.click(screen.getByRole('button', { name: '3748:12671 지금 실행' }))

    expect(await screen.findByRole('status')).toHaveTextContent('수집을 시작했어요 (aicafe-collect-now-1-1010)')
    expect(server.calls).toContain('POST /collection-requests/1/run')
    expect(await screen.findByText(/수집기가 일하는 중이에요/)).toBeInTheDocument()
    for (const key of ['3748:12672', '3748:12673']) {
      expect(screen.getByRole('button', { name: `${key} 지금 실행` })).toBeDisabled()
    }
    // the running request itself cannot be run again or deleted
    const row = screen.getByRole('row', { name: /3748:12671/ })
    expect(within(row).getByRole('button', { name: /지금 실행/ })).toBeDisabled()
    expect(within(row).getByRole('button', { name: /삭제/ })).toBeDisabled()
  })

  it('puts a failed request back in the queue', async () => {
    const server = startServer({ signedIn: true })
    render(<AdminPage />)
    await screen.findByText('수집 요청 3건')

    await userEvent.click(screen.getByRole('button', { name: '3748:12672 대기열로' }))

    expect(await screen.findByRole('status')).toHaveTextContent('다시 대기열에 넣었어요')
    expect(server.calls).toContain('POST /collection-requests/2/requeue')
    expect(screen.queryByRole('button', { name: '3748:12672 대기열로' })).not.toBeInTheDocument()
  })

  it('goes back to the sign-in when the session runs out or on sign-out', async () => {
    const server = startServer({ signedIn: true })
    render(<AdminPage />)
    await screen.findByText('수집 요청 3건')

    server.signedIn = false // the cookie expired on the server
    await userEvent.click(screen.getByRole('button', { name: '새로고침' }))
    expect(await screen.findByRole('heading', { name: '관리자 로그인' })).toBeInTheDocument()
  })

  it('signs out', async () => {
    const server = startServer({ signedIn: true })
    render(<AdminPage />)
    await screen.findByText('수집 요청 3건')
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    expect(await screen.findByRole('heading', { name: '관리자 로그인' })).toBeInTheDocument()
    expect(server.calls).toContain('POST /logout')
  })

  it('says so when the admin is switched off on the server', async () => {
    startServer({ adminOff: true })
    render(<AdminPage />)
    expect(await screen.findByText('관리자 기능이 꺼져 있어요.')).toBeInTheDocument()
    expect(screen.queryByLabelText('아이디')).not.toBeInTheDocument()
  })

  it('marks the page as not for search engines while it is open', async () => {
    startServer({ adminOff: true })
    const { unmount } = render(<AdminPage />)
    await screen.findByText('관리자 기능이 꺼져 있어요.')
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
      'content',
      'noindex, nofollow',
    )
    unmount()
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull()
  })
})
