import { DEFAULT_LOCATION } from '../../../shared/config'
import {
  addFavorite,
  defaultFavorites,
  hasAllDefaults,
  loadFavorites,
  MAX_FAVORITES,
  MAX_NAME_LENGTH,
  newId,
  removeFavorite,
  restoreDefaults,
  saveFavorites,
  STORAGE_KEY,
} from './favorites'

const HOME = { lat: 37.4878, lng: 126.7886 }

describe('loading and saving', () => {
  it('starts a first-time visitor with the four stations', () => {
    expect(loadFavorites().map((f) => f.name)).toEqual(['역삼역', '강남역', '선릉역', '논현역'])
  })

  it('keeps what was saved, including a list the visitor emptied on purpose', () => {
    const [first, second] = defaultFavorites()
    saveFavorites([first, second])
    expect(loadFavorites().map((f) => f.name)).toEqual(['역삼역', '강남역'])
    saveFavorites([])
    expect(loadFavorites()).toEqual([]) // not re-filled with the stations
  })

  it('falls back to the stations when the saved text is unusable', () => {
    for (const broken of ['not json', '{"v":1}', '{"v":1,"items":"x"}', 'null', '[]']) {
      localStorage.setItem(STORAGE_KEY, broken)
      expect(loadFavorites()).toHaveLength(4)
    }
  })

  it('drops damaged entries and places outside Korea but keeps the good ones', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        v: 1,
        items: [
          { id: 'a', name: '회사', point: HOME },
          { id: 'b', name: '', point: HOME },
          { id: 'c', name: '도쿄', point: { lat: 35.68, lng: 139.69 } },
          { id: 'd', name: '나쁜 좌표', point: { lat: 'x', lng: 127 } },
          { name: 'id가 없음', point: HOME },
          null,
        ],
      }),
    )
    expect(loadFavorites().map((f) => f.name)).toEqual(['회사'])
  })

  it('still works when the browser refuses storage', () => {
    const blocked = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const failingSave = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(loadFavorites()).toHaveLength(4)
    expect(() => saveFavorites(defaultFavorites())).not.toThrow()
    blocked.mockRestore()
    failingSave.mockRestore()
  })
})

describe('adding', () => {
  it('saves a trimmed, single-spaced name at the given place', () => {
    const result = addFavorite([], '  우리   집  ', HOME, () => 'id-1')
    expect(result).toEqual({ ok: true, items: [{ id: 'id-1', name: '우리 집', point: HOME }] })
  })

  it('cuts overlong names', () => {
    const result = addFavorite([], 'ㅁ'.repeat(MAX_NAME_LENGTH + 10), HOME)
    expect(result.ok && result.items[0].name).toHaveLength(MAX_NAME_LENGTH)
  })

  it('refuses an empty name, a place outside Korea, and a place that is already saved', () => {
    expect(addFavorite([], '   ', HOME)).toEqual({ ok: false, reason: 'empty' })
    expect(addFavorite([], '도쿄', { lat: 35.68, lng: 139.69 })).toEqual({ ok: false, reason: 'outside' })
    const saved = defaultFavorites()
    expect(addFavorite(saved, '또 역삼', { lat: DEFAULT_LOCATION.lat + 0.00005, lng: DEFAULT_LOCATION.lng })).toEqual({
      ok: false,
      reason: 'duplicate',
    })
  })

  it('stops at the limit', () => {
    let items = [] as ReturnType<typeof defaultFavorites>
    for (let i = 0; i < MAX_FAVORITES; i++) {
      const result = addFavorite(items, `장소${i}`, { lat: 36 + i * 0.01, lng: 127 })
      if (!result.ok) throw new Error(result.reason)
      items = result.items
    }
    expect(addFavorite(items, '하나 더', HOME)).toEqual({ ok: false, reason: 'full' })
  })

  it('makes different ids without crypto.randomUUID (plain HTTP pages do not have it)', () => {
    expect(newId()).not.toBe(newId())
  })
})

describe('removing and restoring', () => {
  it('removes one place and leaves the rest in order', () => {
    const items = defaultFavorites()
    expect(removeFavorite(items, items[1].id).map((f) => f.name)).toEqual(['역삼역', '선릉역', '논현역'])
  })

  it('brings the stations back in front of the places the visitor added', () => {
    const mine = addFavorite([], '회사', HOME, () => 'mine')
    if (!mine.ok) throw new Error('setup')
    const afterDelete = removeFavorite([...defaultFavorites(), ...mine.items], 'default:강남역')
    expect(hasAllDefaults(afterDelete)).toBe(false)
    const restored = restoreDefaults(afterDelete)
    expect(restored.map((f) => f.name)).toEqual(['역삼역', '강남역', '선릉역', '논현역', '회사'])
    expect(hasAllDefaults(restored)).toBe(true)
  })

  it('does not duplicate a station the visitor already saved under another name', () => {
    const mine = addFavorite([], '우리 동네', DEFAULT_LOCATION, () => 'mine')
    if (!mine.ok) throw new Error('setup')
    const restored = restoreDefaults(mine.items)
    expect(restored.filter((f) => f.point.lat === DEFAULT_LOCATION.lat)).toHaveLength(1)
    expect(restored.map((f) => f.name)).toEqual(['강남역', '선릉역', '논현역', '우리 동네'])
  })
})
