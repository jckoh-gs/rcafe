import { ApiError, fetchRecommendations } from './client'

const point = { lat: 37.5006, lng: 127.0364 }

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('fetchRecommendations', () => {
  it('requests the API with rounded coordinates and the radius', async () => {
    respond(200, { items: [] })
    await fetchRecommendations(point, 1000)
    const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(url).toBe('/api/v1/recommendations?lat=37.500600&lng=127.036400&radius_m=1000')
  })

  it('shows the server message for 503 responses', async () => {
    respond(503, { detail: '이 지역의 날씨 정보를 아직 가져올 수 없어요.' })
    await expect(fetchRecommendations(point, 1000)).rejects.toMatchObject({
      status: 503,
      message: '이 지역의 날씨 정보를 아직 가져올 수 없어요.',
    })
  })

  it('explains 422 as an area problem and falls back for unreadable errors', async () => {
    respond(422, { detail: [{ msg: 'x' }] })
    await expect(fetchRecommendations(point, 1000)).rejects.toThrow('서비스 지역')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('boom', { status: 500 })))
    await expect(fetchRecommendations(point, 1000)).rejects.toBeInstanceOf(ApiError)
  })

  it('reports network failures in plain language and lets aborts through', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(fetchRecommendations(point, 1000)).rejects.toMatchObject({ status: 0 })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')))
    await expect(fetchRecommendations(point, 1000)).rejects.toMatchObject({ name: 'AbortError' })
  })
})
