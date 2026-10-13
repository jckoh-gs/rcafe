import { useEffect } from 'react'
import { DEFAULT_RADIUS_M } from '../../../shared/config'
import { LocationBar, useLocation } from '../../../features/change-location'
import { RequestCollection } from '../../../features/request-collection'
import { applyTheme, isNight, themeFor } from '../../../entities/weather'
import { useRecommendations } from '../../../entities/recommendation'
import { LocationMap } from '../../../widgets/location-map'
import { RecommendationList } from '../../../widgets/recommendation-list'
import { WeatherHero } from '../../../widgets/weather-hero'
import './HomePage.css'

export function HomePage() {
  const location = useLocation()
  const { state, retry } = useRecommendations(location.applied, DEFAULT_RADIUS_M)
  const data = state.data

  // The page mood follows the weather that came with the latest results.
  useEffect(() => {
    if (data) applyTheme(document.documentElement, themeFor(data.weather), isNight(data.weather.observed_at))
  }, [data])

  return (
    <div className="home">
      <header className="home__brand">
        <span className="home__logo" aria-hidden="true">
          ☕
        </span>
        <span className="home__name">rcafe</span>
      </header>

      <main className="home__main">
        <WeatherHero weather={data?.weather ?? null} summary={data?.summary ?? null} loading={state.status === 'loading'} />

        <LocationBar
          applied={location.applied}
          hasPending={location.pending !== null}
          onApplyPoint={location.apply}
          onConfirmPending={location.confirm}
        />

        <h2 className="home__title">지금 가기 좋은 카페 TOP 3</h2>
        <RecommendationList
          data={data}
          loading={state.status === 'loading'}
          error={state.status === 'error' ? state.message : null}
          onRetry={retry}
          onResetArea={location.reset}
          emptyAction={<RequestCollection point={location.applied} />}
          sparseAction={
            <RequestCollection
              point={location.applied}
              intro="이 지역은 아직 카페 정보가 적어요. 더 모아 달라고 요청할 수 있어요."
            />
          }
        />

        <LocationMap
          applied={location.applied}
          pending={location.pending}
          items={data?.items ?? []}
          onPick={location.move}
        />
      </main>

      <footer className="home__footer">
        <p>
          날씨 정보는 기상청 관측 자료이고, 카페 정보는 네이버 지도의 공개 정보를 바탕으로 해요. 날씨와 입맛의
          관계는 연구마다 결과가 달라서, 오늘의 추천은 가볍게 참고해 주세요.
        </p>
      </footer>
    </div>
  )
}
