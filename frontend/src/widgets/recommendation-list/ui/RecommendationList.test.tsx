import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeMoreItems, makeRecommendations } from '../../../shared/lib/fixtures'
import { RecommendationList } from './RecommendationList'

const noop = () => undefined

describe('RecommendationList', () => {
  it('shows skeletons while the first results load', () => {
    const { container } = render(
      <RecommendationList data={null} loading error={null} onRetry={noop} onResetArea={noop} />,
    )
    expect(container.querySelectorAll('.reco-skeleton')).toHaveLength(3)
  })

  it('renders three ranked cards with menu, price, status, and an external map link', () => {
    render(
      <RecommendationList data={makeRecommendations()} loading={false} error={null} onRetry={noop} onResetArea={noop} />,
    )
    const cards = screen.getAllByRole('article')
    expect(cards).toHaveLength(3)
    const first = within(cards[0])
    expect(first.getByRole('heading', { name: '과일창고' })).toBeInTheDocument()
    expect(first.getByText('자몽에이드')).toBeInTheDocument()
    expect(first.getByText('5,500원')).toBeInTheDocument()
    expect(first.getByText(/영업 중 · 22:00까지/)).toBeInTheDocument()
    expect(first.getByText(/상큼한 맛이라 오늘 날씨에 잘 어울려요/)).toBeInTheDocument()
    const link = first.getByRole('link', { name: /네이버 지도에서 보기/ })
    expect(link).toHaveAttribute('href', 'https://map.naver.com/p/entry/place/1')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('shows opening time for closed cafes and a fallback when the photo is missing', () => {
    render(
      <RecommendationList data={makeRecommendations()} loading={false} error={null} onRetry={noop} onResetArea={noop} />,
    )
    expect(screen.getByText(/영업 종료 · 내일 09:00 오픈/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /로스터리원.*사진 없음/ })).toBeInTheDocument()
  })

  it('surfaces notices from the server', () => {
    const data = makeRecommendations({ notices: ['주변 1000m 안에 열린 곳이 적어 2000m까지 찾았어요.'] })
    render(<RecommendationList data={data} loading={false} error={null} onRetry={noop} onResetArea={noop} />)
    expect(screen.getByText(/2000m까지 찾았어요/)).toBeInTheDocument()
  })

  it('offers a retry when the first load fails', async () => {
    const onRetry = vi.fn()
    render(
      <RecommendationList data={null} loading={false} error="네트워크에 연결할 수 없어요." onRetry={onRetry} onResetArea={noop} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('네트워크에 연결할 수 없어요.')
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('keeps old results visible with an inline error when a refresh fails', () => {
    render(
      <RecommendationList data={makeRecommendations()} loading={false} error="잠시 후 다시 시도해 주세요." onRetry={noop} onResetArea={noop} />,
    )
    expect(screen.getAllByRole('article')).toHaveLength(3)
    expect(screen.getByRole('alert')).toHaveTextContent('잠시 후 다시 시도해 주세요.')
  })

  it('invites the user back to the covered area when nothing is found', async () => {
    const onResetArea = vi.fn()
    render(
      <RecommendationList data={makeRecommendations({ items: [] })} loading={false} error={null} onRetry={noop} onResetArea={onResetArea} />,
    )
    expect(screen.getByText(/아직 준비 중/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /역삼역 주변으로 돌아가기/ }))
    expect(onResetArea).toHaveBeenCalledOnce()
  })

  it('shows today\'s hours with the open status and the whole week on demand', async () => {
    render(
      <RecommendationList data={makeRecommendations()} loading={false} error={null} onRetry={noop} onResetArea={noop} />,
    )
    const first = within(screen.getAllByRole('article')[0])
    expect(first.getByText(/오늘 08:00 ~ 22:00/)).toBeInTheDocument()
    expect(first.getByText('월~금')).not.toBeVisible() // folded away until asked for
    await userEvent.click(first.getByText('전체 보기'))
    expect(first.getByText('월~금')).toBeVisible()
    expect(first.getByText('정기휴무')).toBeVisible()
    expect(first.getByText(/휴게시간·라스트오더/)).toBeVisible()
    // today's row is highlighted for the open cafe (a weekday), not the Saturday row
    expect(first.getByText('월~금').closest('[data-today]')).toHaveAttribute('data-today', 'true')
    expect(first.getByText('토').closest('[data-today]')).toHaveAttribute('data-today', 'false')
  })

  it('shows nothing about hours when the cafe has none on file', () => {
    render(
      <RecommendationList data={makeRecommendations()} loading={false} error={null} onRetry={noop} onResetArea={noop} />,
    )
    const third = within(screen.getAllByRole('article')[2]) // fixture cafe 3: unknown hours
    expect(third.queryByText(/오늘 \d{2}:\d{2}|오늘 정보 없음/)).not.toBeInTheDocument()
    expect(third.queryByText('전체 보기')).not.toBeInTheDocument()
  })

  it('shows a single line without a toggle when only today is known', () => {
    const data = makeRecommendations()
    data.items[0].cafe.weekly_hours = [{ days: '매일', text: '07:00 ~ 23:00', is_today: true }]
    data.items[0].cafe.today_hours = '07:00 ~ 23:00'
    render(<RecommendationList data={data} loading={false} error={null} onRetry={noop} onResetArea={noop} />)
    const first = within(screen.getAllByRole('article')[0])
    expect(first.getByText(/오늘 07:00 ~ 23:00/)).toBeInTheDocument()
    expect(first.queryByText('전체 보기')).not.toBeInTheDocument()
  })

  describe('show more', () => {
    const withMore = (n = 10) => makeRecommendations({ more_items: makeMoreItems(n) })
    const view = (data = withMore()) =>
      render(<RecommendationList data={data} loading={false} error={null} onRetry={noop} onResetArea={noop} />)

    it('keeps the ten extra cafes folded away until the button is pressed', () => {
      view()
      expect(screen.getAllByRole('article')).toHaveLength(3)
      const button = screen.getByRole('button', { name: /추천 더보기 · 10곳/ })
      expect(button).toHaveAttribute('aria-expanded', 'false')
      expect(screen.queryByText('더보기카페4')).not.toBeInTheDocument()
      expect(screen.queryByRole('img', { name: /더보기카페/ })).not.toBeInTheDocument() // no photos requested
    })

    it('shows the extra cafes in rank order when asked, and folds them again', async () => {
      view()
      await userEvent.click(screen.getByRole('button', { name: /추천 더보기/ }))

      const cards = screen.getAllByRole('article')
      expect(cards).toHaveLength(13)
      expect(within(cards[3]).getByRole('heading', { name: '더보기카페4' })).toBeInTheDocument()
      expect(within(cards[3]).getByText('더보기메뉴4')).toBeInTheDocument()
      expect(within(cards[3]).getByLabelText('4순위')).toBeInTheDocument()
      expect(within(cards[12]).getByLabelText('13순위')).toBeInTheDocument()
      expect(cards[3]).toHaveClass('cafe-card--compact')
      expect(cards[0]).not.toHaveClass('cafe-card--compact') // the podium keeps its big cards
      expect(screen.getByRole('button', { name: /추천 접기/ })).toHaveAttribute('aria-expanded', 'true')

      await userEvent.click(screen.getByRole('button', { name: '접기' })) // the one under the list
      expect(screen.getAllByRole('article')).toHaveLength(3)
      expect(screen.getByRole('button', { name: /추천 더보기 · 10곳/ })).toHaveAttribute('aria-expanded', 'false')
    })

    it('folds with the button on top as well', async () => {
      view()
      await userEvent.click(screen.getByRole('button', { name: /추천 더보기/ }))
      await userEvent.click(screen.getByRole('button', { name: /추천 접기/ }))
      expect(screen.getAllByRole('article')).toHaveLength(3)
    })

    it('has no button when there is nothing more to show', () => {
      view(makeRecommendations())
      expect(screen.queryByRole('button', { name: /추천 더보기/ })).not.toBeInTheDocument()
    })

    it('counts what it actually has when the area is small', () => {
      view(withMore(4))
      expect(screen.getByRole('button', { name: /추천 더보기 · 4곳/ })).toBeInTheDocument()
    })

    it('folds again when the area changes', async () => {
      const { rerender } = view()
      await userEvent.click(screen.getByRole('button', { name: /추천 더보기/ }))
      expect(screen.getAllByRole('article')).toHaveLength(13)

      const elsewhere = { ...withMore(), origin_lat: 37.55, origin_lng: 127.1 }
      rerender(<RecommendationList data={elsewhere} loading={false} error={null} onRetry={noop} onResetArea={noop} />)
      expect(screen.getAllByRole('article')).toHaveLength(3)
      expect(screen.getByRole('button', { name: /추천 더보기/ })).toHaveAttribute('aria-expanded', 'false')
    })

    it('stays folded while the same area refreshes', async () => {
      const { rerender } = view()
      await userEvent.click(screen.getByRole('button', { name: /추천 더보기/ }))
      rerender(<RecommendationList data={withMore()} loading error={null} onRetry={noop} onResetArea={noop} />)
      expect(screen.getAllByRole('article')).toHaveLength(13) // same place: the list stays open
    })
  })
})
