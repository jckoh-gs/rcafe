import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LocationBar } from './LocationBar'
import { STORAGE_KEY } from '../model/favorites'

const YEOKSAM = { lat: 37.5006431, lng: 127.0363766 }
const HOME = { lat: 37.4878, lng: 126.7886 }

function view(applied = YEOKSAM, onApplyPoint: (p: { lat: number; lng: number }) => void = () => undefined) {
  return render(<LocationBar applied={applied} hasPending={false} onApplyPoint={onApplyPoint} onConfirmPending={() => undefined} />)
}

const group = () => screen.getByRole('group', { name: '즐겨찾기 지역' })
const saved = () => (JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as { items: { name: string }[] } | null)?.items.map((f) => f.name)

describe('LocationBar favorites', () => {
  it('starts with the four stations as shortcuts and applies the tapped one', async () => {
    const onApplyPoint = vi.fn()
    view(YEOKSAM, onApplyPoint)
    const chips = within(group()).getAllByRole('button', { pressed: undefined }).filter((b) => /역$/.test(b.textContent ?? ''))
    expect(chips.map((b) => b.textContent)).toEqual(['역삼역', '강남역', '선릉역', '논현역'])
    expect(screen.getByRole('button', { name: '역삼역' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: '선릉역' }))
    expect(onApplyPoint).toHaveBeenCalledWith({ lat: 37.5045, lng: 127.049 })
  })

  it('shows no delete buttons until edit mode is on', async () => {
    view()
    expect(screen.queryByRole('button', { name: /즐겨찾기 삭제/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '편집' }))
    expect(screen.getAllByRole('button', { name: /즐겨찾기 삭제/ })).toHaveLength(4)
    await userEvent.click(screen.getByRole('button', { name: '편집 끝' }))
    expect(screen.queryByRole('button', { name: /즐겨찾기 삭제/ })).not.toBeInTheDocument()
  })

  it('deletes a station for good, even after a reload', async () => {
    const { unmount } = view()
    await userEvent.click(screen.getByRole('button', { name: '편집' }))
    await userEvent.click(screen.getByRole('button', { name: '강남역 즐겨찾기 삭제' }))

    expect(screen.queryByRole('button', { name: '강남역' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent("'강남역'을(를) 삭제했어요.")
    expect(saved()).toEqual(['역삼역', '선릉역', '논현역'])

    unmount()
    view()
    expect(screen.queryByRole('button', { name: '강남역' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '선릉역' })).toBeInTheDocument()
  })

  it('lets every shortcut go, then offers to bring the stations back', async () => {
    view()
    await userEvent.click(screen.getByRole('button', { name: '편집' }))
    for (const name of ['역삼역', '강남역', '선릉역', '논현역']) {
      await userEvent.click(screen.getByRole('button', { name: `${name} 즐겨찾기 삭제` }))
    }
    expect(screen.getByText(/저장한 지역이 없어요/)).toBeInTheDocument()
    expect(saved()).toEqual([]) // an empty list stays empty
    expect(screen.queryByRole('button', { name: '편집' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '기본 지역 되돌리기' }))
    expect(screen.getByRole('button', { name: '역삼역' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '기본 지역 되돌리기' })).not.toBeInTheDocument()
  })

  it('saves the area on screen under a name and shows that name above', async () => {
    const { rerender } = view(HOME)
    expect(screen.getByText('선택한 위치 주변')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '＋ 이 지역 즐겨찾기' }))
    await userEvent.type(screen.getByRole('textbox', { name: '즐겨찾기 이름' }), '우리 집{Enter}')

    expect(screen.getByRole('button', { name: '우리 집' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('status')).toHaveTextContent("'우리 집'을(를) 즐겨찾기에 추가했어요.")
    expect(screen.getByText('우리 집 주변')).toBeInTheDocument()
    expect(saved()).toEqual(['역삼역', '강남역', '선릉역', '논현역', '우리 집'])
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // the form closed

    rerender(<LocationBar applied={HOME} hasPending={false} onApplyPoint={() => undefined} onConfirmPending={() => undefined} />)
    expect(screen.getByRole('button', { name: '＋ 이 지역 즐겨찾기' })).toBeDisabled() // already saved
  })

  it('asks for a name and can be cancelled', async () => {
    view(HOME)
    await userEvent.click(screen.getByRole('button', { name: '＋ 이 지역 즐겨찾기' }))
    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(screen.getByRole('alert')).toHaveTextContent('이름을 입력해 주세요.')
    expect(saved()).toBeUndefined() // nothing was written yet

    await userEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not offer to save a station that is already a shortcut', () => {
    view(YEOKSAM)
    expect(screen.getByRole('button', { name: '＋ 이 지역 즐겨찾기' })).toBeDisabled()
  })

  it('keeps naming a deleted station on the label, and prefers a saved name for the same spot', async () => {
    const { rerender } = view(YEOKSAM)
    await userEvent.click(screen.getByRole('button', { name: '편집' }))
    await userEvent.click(screen.getByRole('button', { name: '역삼역 즐겨찾기 삭제' }))
    expect(screen.getByText('역삼역 주변')).toBeInTheDocument() // a place name, not a shortcut

    rerender(<LocationBar applied={HOME} hasPending={false} onApplyPoint={() => undefined} onConfirmPending={() => undefined} />)
    expect(screen.getByText('선택한 위치 주변')).toBeInTheDocument()
  })

  it('follows changes made in another tab', () => {
    view()
    expect(screen.getByRole('button', { name: '논현역' })).toBeInTheDocument()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ v: 1, items: [{ id: 'x', name: '회사', point: HOME }] }))
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }))
    return screen.findByRole('button', { name: '회사' }).then(() => {
      expect(screen.queryByRole('button', { name: '논현역' })).not.toBeInTheDocument()
    })
  })
})
