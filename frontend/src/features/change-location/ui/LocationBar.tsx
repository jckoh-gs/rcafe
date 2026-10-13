import type { GeoPoint } from '../../../shared/api'
import { labelFor } from '../model/location'
import { canUseGeolocation, useGeolocation } from '../model/useGeolocation'
import { useFavorites } from '../model/useFavorites'
import { FavoritePlaces } from './FavoritePlaces'
import './LocationBar.css'

interface Props {
  applied: GeoPoint
  hasPending: boolean
  onApplyPoint: (point: GeoPoint) => void
  onConfirmPending: () => void
}

const GEO_MESSAGE = {
  idle: '',
  locating: '내 위치를 찾는 중이에요…',
  denied: '위치 권한이 꺼져 있어요. 지도에서 직접 골라 주세요.',
  unavailable: '지금은 내 위치를 가져올 수 없어요. 지도에서 직접 골라 주세요.',
  outside: '서비스 지역(대한민국) 밖이에요.',
} as const

export function LocationBar({ applied, hasPending, onApplyPoint, onConfirmPending }: Props) {
  const geo = useGeolocation(onApplyPoint)
  const geoSupported = canUseGeolocation()
  const favorites = useFavorites()

  return (
    <section className="location-bar" aria-label="추천 지역">
      <div className="location-bar__row">
        <p className="location-bar__label">
          <span aria-hidden="true">📍</span> <strong>{labelFor(applied, favorites.items)}</strong>
        </p>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={geo.locate}
          disabled={!geoSupported || geo.status === 'locating'}
          title={geoSupported ? undefined : '내 위치는 보안 연결(HTTPS)에서만 쓸 수 있어요'}
        >
          내 위치
        </button>
      </div>

      <FavoritePlaces applied={applied} favorites={favorites} onApplyPoint={onApplyPoint} />

      {geo.status !== 'idle' && (
        <p className="location-bar__note" role="status">
          {GEO_MESSAGE[geo.status]}
        </p>
      )}
      {!geoSupported && geo.status === 'idle' && (
        <p className="location-bar__note">
          이 주소에서는 내 위치를 쓸 수 없어요. 아래 지도에서 핀을 옮겨 지역을 골라 보세요.
        </p>
      )}

      {hasPending && (
        <button type="button" className="btn btn--primary location-bar__confirm" onClick={onConfirmPending}>
          이 위치에서 다시 추천받기
        </button>
      )}
    </section>
  )
}
