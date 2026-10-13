import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeRecommendations } from '../../../shared/lib/fixtures'
import { HomePage } from './HomePage'

// Leaflet needs a real browser; the map is covered by manual/browser checks.
vi.mock('../../../widgets/location-map', () => ({ LocationMap: () => <div data-testid="map" /> }))

function mockFetch(...responses: Array<{ status: number; body: unknown }>) {
  const fn = vi.fn()
  for (const r of responses) fn.mockResolvedValueOnce(new Response(JSON.stringify(r.body), { status: r.status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  document.documentElement.removeAttribute('data-theme')
})
afterEach(() => vi.unstubAllGlobals())

describe('HomePage', () => {
  it('loads Yeoksam by default and shows the weather, summary, and three cafes', async () => {
    const fetchMock = mockFetch({ status: 200, body: makeRecommendations() })
    render(<HomePage />)

    expect(await screen.findAllByRole('article')).toHaveLength(3)
    expect(screen.getByText('지내기 좋은 선선한 날씨예요 🍃 오늘은 쌉싸름한 맛이 어울려요.')).toBeInTheDocument()
    expect(screen.getByText(/선선한 맑은 아침/)).toBeInTheDocument()
    expect(screen.getByText('역삼역 주변')).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toContain('lat=37.500643')
    // the theme is applied in an effect, so wait for it instead of racing it
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('mild'))
    expect(document.documentElement.dataset.night).toBe('false')
  })

  it('uses the coordinates from the URL so a link can be shared', async () => {
    window.history.replaceState(null, '', '/?lat=37.4979&lng=127.0276')
    const fetchMock = mockFetch({ status: 200, body: makeRecommendations() })
    render(<HomePage />)
    await screen.findAllByRole('article')
    expect(fetchMock.mock.calls[0][0]).toContain('lat=37.497900&lng=127.027600')
    expect(screen.getByText('강남역 주변')).toBeInTheDocument()
  })

  it('searches the chosen station and updates the address bar', async () => {
    const fetchMock = mockFetch(
      { status: 200, body: makeRecommendations() },
      { status: 200, body: makeRecommendations({ summary: '선릉역 결과예요.' }) },
    )
    render(<HomePage />)
    await screen.findAllByRole('article')

    await userEvent.click(screen.getByRole('button', { name: '선릉역' }))

    expect(await screen.findByText('선릉역 결과예요.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[1][0])).toContain('lat=37.504500')
    expect(window.location.search).toBe('?lat=37.50450&lng=127.04900')
  })

  it('shows a friendly error and recovers on retry', async () => {
    mockFetch(
      { status: 503, body: { detail: '이 지역의 날씨 정보를 아직 가져올 수 없어요.' } },
      { status: 200, body: makeRecommendations() },
    )
    render(<HomePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('날씨 정보를 아직 가져올 수 없어요')

    expect(screen.getByText(/날씨 정보를 불러오지 못했어요/)).toBeInTheDocument() // hero is not stuck loading
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(3))
  })

  it('disables "내 위치" on insecure origins and explains why', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    mockFetch({ status: 200, body: makeRecommendations() })
    render(<HomePage />)
    await screen.findAllByRole('article')
    expect(screen.getByRole('button', { name: '내 위치' })).toBeDisabled()
    expect(screen.getByText(/이 주소에서는 내 위치를 쓸 수 없어요/)).toBeInTheDocument()
  })

  it('offers to collect an area that has no cafes yet', async () => {
    window.history.replaceState(null, '', '/?lat=37.48780&lng=126.78860')
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const body = url.includes('/collection-requests')
          ? { status: 'none', request_count: 0, cafes_found: null, message: '', next_run_at: null }
          : makeRecommendations({ items: [] })
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
      }),
    )
    render(<HomePage />)
    expect(await screen.findByText(/아직 준비 중/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '이 지역 수집 요청하기' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /역삼역 주변으로 돌아가기/ })).toBeInTheDocument()
  })

  it('does not ask for collection where there are three recommendations', async () => {
    mockFetch({ status: 200, body: makeRecommendations() })
    render(<HomePage />)
    await screen.findAllByRole('article')
    expect(screen.queryByRole('button', { name: '이 지역 수집 요청하기' })).not.toBeInTheDocument()
  })
})
