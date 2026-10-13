import { DEFAULT_LOCATION } from '../../../shared/config'
import { isInsideKorea, labelFor, parseLocation, samePoint, toSearch } from './location'

describe('parseLocation', () => {
  it('reads valid coordinates from the URL', () => {
    expect(parseLocation('?lat=37.4979&lng=127.0276')).toEqual({ lat: 37.4979, lng: 127.0276 })
  })

  it('falls back to Yeoksam for missing, broken, or out-of-country values', () => {
    expect(parseLocation('')).toEqual(DEFAULT_LOCATION)
    expect(parseLocation('?lat=abc&lng=127')).toEqual(DEFAULT_LOCATION)
    expect(parseLocation('?lat=37.5')).toEqual(DEFAULT_LOCATION)
    expect(parseLocation('?lat=10&lng=20')).toEqual(DEFAULT_LOCATION)
  })

  it('round-trips through toSearch', () => {
    const point = { lat: 37.49871, lng: 127.03104 }
    expect(parseLocation(toSearch(point))).toEqual(point)
  })
})

describe('labels and comparisons', () => {
  it('names the area near a preset station', () => {
    expect(labelFor(DEFAULT_LOCATION)).toBe('역삼역 주변')
    expect(labelFor({ lat: 37.4981, lng: 127.0278 })).toBe('강남역 주변')
    expect(labelFor({ lat: 37.56, lng: 127.1 })).toBe('선택한 위치 주변')
  })

  it('prefers the name of a saved place and falls back to the station names', () => {
    const near = { lat: 37.50066, lng: 127.03638 }
    expect(labelFor(near, [{ name: '회사', point: near }])).toBe('회사 주변')
    expect(labelFor(DEFAULT_LOCATION, [])).toBe('역삼역 주변') // a deleted shortcut still names the place
    expect(labelFor({ lat: 37.56, lng: 127.1 }, [{ name: '회사', point: near }])).toBe('선택한 위치 주변')
  })

  it('treats nearly identical pins as the same point', () => {
    expect(samePoint(DEFAULT_LOCATION, { lat: 37.50065, lng: 127.03638 })).toBe(true)
    expect(samePoint(DEFAULT_LOCATION, { lat: 37.51, lng: 127.04 })).toBe(false)
  })

  it('knows the service area', () => {
    expect(isInsideKorea(DEFAULT_LOCATION)).toBe(true)
    expect(isInsideKorea({ lat: 35.68, lng: 139.69 })).toBe(false)
  })
})
