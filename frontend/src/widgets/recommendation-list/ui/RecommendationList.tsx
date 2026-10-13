import type { ReactNode } from 'react'
import type { Recommendations } from '../../../shared/api'
import { CafeCard } from './CafeCard'
import { MoreCafes } from './MoreCafes'
import './RecommendationList.css'

interface Props {
  data: Recommendations | null
  loading: boolean
  error: string | null
  onRetry: () => void
  onResetArea: () => void
  /** Offered when the area has no cafes at all (e.g. a request-collection button). */
  emptyAction?: ReactNode
  /** Offered below the list when only one or two cafes were found. */
  sparseAction?: ReactNode
}

export function RecommendationList({
  data,
  loading,
  error,
  onRetry,
  onResetArea,
  emptyAction,
  sparseAction,
}: Props) {
  if (data === null && loading) {
    return (
      <div className="reco-list" aria-busy="true" aria-live="polite">
        {[1, 2, 3].map((n) => (
          <div key={n} className="reco-skeleton" />
        ))}
      </div>
    )
  }

  if (error !== null && data === null) {
    return (
      <div className="reco-state" role="alert">
        <p className="reco-state__title">잠시 쉬어가는 중이에요 ☕</p>
        <p>{error}</p>
        <button type="button" className="btn btn--primary" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    )
  }

  if (data === null) return null

  return (
    <div className="reco-list" aria-busy={loading} aria-live="polite">
      {error !== null && (
        <p className="reco-notice reco-notice--error" role="alert">
          {error}{' '}
          <button type="button" className="reco-link" onClick={onRetry}>
            다시 시도
          </button>
        </p>
      )}
      {data.notices.map((notice) => (
        <p key={notice} className="reco-notice">
          {notice}
        </p>
      ))}
      {data.items.length === 0 ? (
        <div className="reco-state">
          <p className="reco-state__title">이 근처는 아직 준비 중이에요 🌱</p>
          <p>지금은 역삼역 주변 카페를 중심으로 추천하고 있어요.</p>
          {emptyAction}
          <button type="button" className="btn btn--ghost" onClick={onResetArea}>
            역삼역 주변으로 돌아가기
          </button>
        </div>
      ) : (
        <ol className="reco-list__items" data-loading={loading}>
          {data.items.map((item) => (
            <li key={item.cafe.place_id}>
              <CafeCard item={item} />
            </li>
          ))}
        </ol>
      )}
      {/* keyed by place, so moving to another area folds the extra list again */}
      <MoreCafes key={`${data.origin_lat}:${data.origin_lng}`} items={data.more_items} />
      {data.items.length > 0 && data.items.length < 3 && sparseAction}
    </div>
  )
}
