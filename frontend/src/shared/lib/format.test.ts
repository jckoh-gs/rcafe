import { distanceMeters, formatDateTime, formatDistance, formatPrice, formatRating } from './format'

describe('format', () => {
  it('formats prices with thousands separators', () => {
    expect(formatPrice(5500)).toBe('5,500원')
    expect(formatPrice(null)).toBeNull()
  })

  it('switches from meters to kilometers at 1 km', () => {
    expect(formatDistance(845.4)).toBe('845m')
    expect(formatDistance(1234)).toBe('1.2km')
  })

  it('formats ratings to one decimal', () => {
    expect(formatRating(4.92)).toBe('4.9')
    expect(formatRating(null)).toBeNull()
  })

  it('measures great-circle distance', () => {
    const yeoksam = { lat: 37.5006431, lng: 127.0363766 }
    const gangnam = { lat: 37.4979, lng: 127.0276 }
    expect(distanceMeters(yeoksam, yeoksam)).toBe(0)
    expect(distanceMeters(yeoksam, gangnam)).toBeGreaterThan(750)
    expect(distanceMeters(yeoksam, gangnam)).toBeLessThan(850)
  })
})

describe('formatDateTime', () => {
  it('shows Korean time as month, day and 24-hour clock', () => {
    expect(formatDateTime('2026-10-10T18:30:00+00:00')).toBe('10월 11일 03:30')
    expect(formatDateTime('2026-10-10T04:05:00Z')).toBe('10월 10일 13:05')
  })

  it('shows a dash when there is no usable time', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('not a date')).toBe('-')
  })
})
