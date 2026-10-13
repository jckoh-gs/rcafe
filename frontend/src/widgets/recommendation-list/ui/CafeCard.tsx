import type { RecommendationItem } from '../../../shared/api'
import { formatDistance, formatPrice, formatRating } from '../../../shared/lib'
import { CafeImage, OpenBadge, OpeningHours } from '../../../entities/cafe'
import { TasteChips } from '../../../entities/taste'
import './CafeCard.css'

interface Props {
  item: RecommendationItem
  /** The smaller row used in the "show more" list: small photo, no taste chips. */
  compact?: boolean
}

export function CafeCard({ item, compact = false }: Props) {
  const { cafe, menu } = item
  const price = formatPrice(menu.price)
  const rating = formatRating(cafe.rating)
  return (
    <article
      className={compact ? 'cafe-card cafe-card--compact' : 'cafe-card'}
      data-rank={item.rank}
      aria-labelledby={`cafe-${cafe.place_id}`}
    >
      <div className="cafe-card__photo">
        <CafeImage src={menu.image_url ?? cafe.image_url} alt={`${cafe.name}의 ${menu.name}`} />
        <span className="cafe-card__rank" aria-label={`${item.rank}순위`}>
          {item.rank}
        </span>
      </div>

      <div className="cafe-card__content">
        <header className="cafe-card__head">
          <h3 id={`cafe-${cafe.place_id}`} className="cafe-card__name">
            {cafe.name}
          </h3>
          <OpenBadge state={cafe.open_state} />
        </header>

        <OpeningHours today={cafe.today_hours} weekly={cafe.weekly_hours} />

        <p className="cafe-card__menu">
          <span className="cafe-card__menu-label">추천 메뉴</span>
          <strong>{menu.name}</strong>
          {price && <span className="cafe-card__price">{price}</span>}
        </p>

        {!compact && <TasteChips chips={item.taste_chips} label={`${cafe.name}의 입맛`} />}

        <p className="cafe-card__message">{item.headline}</p>

        <footer className="cafe-card__meta">
          <span>도보 {cafe.walking_minutes}분 · {formatDistance(cafe.distance_m)}</span>
          {rating && (
            <span>
              ★ {rating} <small>({cafe.review_count.toLocaleString('ko-KR')})</small>
            </span>
          )}
          <a href={cafe.naver_map_url} target="_blank" rel="noopener noreferrer" className="cafe-card__link">
            네이버 지도에서 보기 ↗
          </a>
        </footer>
      </div>
    </article>
  )
}
