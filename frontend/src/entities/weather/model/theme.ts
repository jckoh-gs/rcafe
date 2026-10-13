import type { Weather } from '../../../shared/api'

export type WeatherTheme = 'rain' | 'hot' | 'cold' | 'mild'

export const THEME_LABEL: Record<WeatherTheme, string> = {
  rain: '비 오는 날',
  hot: '더운 날',
  cold: '추운 날',
  mild: '선선한 날',
}

/** The visual mood follows what the weather asks for: rain first, then temperature. */
export function themeFor(weather: Pick<Weather, 'raining' | 'feels_like_c'>): WeatherTheme {
  if (weather.raining) return 'rain'
  if (weather.feels_like_c >= 26) return 'hot'
  if (weather.feels_like_c <= 9) return 'cold'
  return 'mild'
}

/** Evening and night (Korean time) get the lamp-lit variant of every theme. */
export function isNight(observedAt: string): boolean {
  const hour = Number(
    new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Asia/Seoul' }).format(
      new Date(observedAt),
    ),
  )
  return hour >= 19 || hour < 6
}

export function applyTheme(root: HTMLElement, theme: WeatherTheme, night: boolean): void {
  root.dataset.theme = theme
  root.dataset.night = night ? 'true' : 'false'
}
