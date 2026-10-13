import type { Weather } from '../../../shared/api'
import { THEME_LABEL, themeFor } from '../../../entities/weather'
import { TasteChips } from '../../../entities/taste'
import './WeatherHero.css'

interface Props {
  weather: Weather | null
  summary: string | null
  loading: boolean
}

export function WeatherHero({ weather, summary, loading }: Props) {
  if (weather === null) {
    return (
      <section className="weather-hero weather-hero--empty" aria-busy={loading} aria-label="오늘의 날씨">
        <div className="weather-hero__fx" aria-hidden="true" />
        <div className="weather-hero__body">
          <p className="weather-hero__kicker">오늘의 날씨가 고른 한 잔</p>
          {loading ? (
            <>
              <div className="skeleton skeleton--temp" />
              <div className="skeleton skeleton--line" />
            </>
          ) : (
            <p className="weather-hero__summary">지금은 날씨 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>
          )}
        </div>
      </section>
    )
  }

  const theme = themeFor(weather)
  return (
    <section className="weather-hero" aria-busy={loading} aria-label="오늘의 날씨" data-hero={theme}>
      <div className="weather-hero__fx" aria-hidden="true">
        <span /> <span /> <span /> <span /> <span /> <span />
      </div>
      <div className="weather-hero__body">
        <p className="weather-hero__kicker">오늘의 날씨가 고른 한 잔</p>
        <div className="weather-hero__temp">
          <span className="weather-hero__degrees">{Math.round(weather.feels_like_c)}</span>
          <span className="weather-hero__unit">°C</span>
          <span className="weather-hero__feels">체감</span>
        </div>
        <p className="weather-hero__desc">
          {weather.description} · {THEME_LABEL[theme]} · 습도 {weather.humidity_pct}%
        </p>
        {summary && <p className="weather-hero__summary">{summary}</p>}
        <div className="weather-hero__taste">
          <span className="weather-hero__taste-title">오늘의 입맛</span>
          <TasteChips chips={weather.wanted_taste} label="오늘 어울리는 입맛" limit={4} />
        </div>
      </div>
    </section>
  )
}
