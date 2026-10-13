import { isNight, themeFor } from './theme'

describe('themeFor', () => {
  it('lets rain win, then temperature decides', () => {
    expect(themeFor({ raining: true, feels_like_c: 30 })).toBe('rain')
    expect(themeFor({ raining: false, feels_like_c: 31 })).toBe('hot')
    expect(themeFor({ raining: false, feels_like_c: 26 })).toBe('hot')
    expect(themeFor({ raining: false, feels_like_c: 9 })).toBe('cold')
    expect(themeFor({ raining: false, feels_like_c: 15 })).toBe('mild')
  })
})

describe('isNight', () => {
  it('uses Korean time, not the browser time zone', () => {
    expect(isNight('2026-10-10T08:00:00+09:00')).toBe(false)
    expect(isNight('2026-10-10T19:00:00+09:00')).toBe(true)
    expect(isNight('2026-10-10T03:00:00+09:00')).toBe(true)
    expect(isNight('2026-10-09T23:30:00Z')).toBe(false) // 08:30 KST
  })
})
