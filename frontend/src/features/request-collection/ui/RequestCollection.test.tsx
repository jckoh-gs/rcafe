import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RequestCollection } from './RequestCollection'

const point = { lat: 37.4878, lng: 126.7886 }

type Reply = { status: number; body: unknown }

function route(replies: { get?: Reply; post?: Reply }) {
  const fn = vi.fn((_url: string, init?: RequestInit) => {
    const reply = init?.method === 'POST' ? replies.post : replies.get
    const { status, body } = reply ?? { status: 200, body: {} }
    return Promise.resolve(new Response(JSON.stringify(body), { status }))
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

const none = { status: 200, body: { status: 'none', request_count: 0, cafes_found: null, message: '', next_run_at: null } }

afterEach(() => vi.unstubAllGlobals())

describe('RequestCollection', () => {
  it('offers the request, sends it, and explains when it will be collected', async () => {
    const fetchMock = route({
      get: none,
      post: {
        status: 200,
        body: {
          status: 'queued',
          request_count: 1,
          cafes_found: null,
          message: '요청을 받았어요! 서비스가 한가한 내일 새벽 3시 30분 무렵에 수집하고, 끝나면 추천해 드려요.',
          next_run_at: '2026-10-11T03:30:00+09:00',
        },
      },
    })
    render(<RequestCollection point={point} />)

    const button = await screen.findByRole('button', { name: '이 지역 수집 요청하기' })
    await userEvent.click(button)

    expect(await screen.findByRole('status')).toHaveTextContent('내일 새벽 3시 30분')
    expect(screen.queryByRole('button', { name: '이 지역 수집 요청하기' })).not.toBeInTheDocument()
    expect(screen.getByText(/한가한 새벽에 모아서 처리해요/)).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual(point)
  })

  it('shows an earlier request instead of the button after a reload', async () => {
    route({
      get: {
        status: 200,
        body: {
          status: 'already_queued',
          request_count: 3,
          cafes_found: null,
          message: '이미 수집 대기 중이에요 (지금까지 3번 요청됐어요). 오늘 새벽 3시 30분 무렵에 수집해요.',
          next_run_at: null,
        },
      },
    })
    render(<RequestCollection point={point} />)
    expect(await screen.findByRole('status')).toHaveTextContent('3번 요청')
    expect(screen.queryByRole('button', { name: '이 지역 수집 요청하기' })).not.toBeInTheDocument()
  })

  it('shows the outcome of a finished collection without offering the button again', async () => {
    route({
      get: {
        status: 200,
        body: { status: 'done', request_count: 2, cafes_found: 0, message: '이 지역을 확인해 봤지만 등록된 카페를 찾지 못했어요.', next_run_at: null },
      },
    })
    render(<RequestCollection point={point} />)
    expect(await screen.findByRole('status')).toHaveTextContent('찾지 못했어요')
    expect(screen.queryByRole('button', { name: '이 지역 수집 요청하기' })).not.toBeInTheDocument()
  })

  it('tells the visitor when the server refuses (too many requests)', async () => {
    route({ get: none, post: { status: 429, body: { detail: '요청이 너무 잦아요. 잠시 후에 다시 시도해 주세요.' } } })
    render(<RequestCollection point={point} />)
    await userEvent.click(await screen.findByRole('button', { name: '이 지역 수집 요청하기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('너무 잦아요')
    expect(screen.getByRole('button', { name: '이 지역 수집 요청하기' })).toBeEnabled() // can retry later
  })

  it('still works when the status lookup fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    render(<RequestCollection point={point} intro="이 지역은 아직 카페 정보가 적어요." />)
    expect(await screen.findByRole('button', { name: '이 지역 수집 요청하기' })).toBeInTheDocument()
    expect(screen.getByText('이 지역은 아직 카페 정보가 적어요.')).toBeInTheDocument()
  })
})
