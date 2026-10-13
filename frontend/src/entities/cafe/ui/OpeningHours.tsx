import type { HoursRow } from '../../../shared/api'
import './OpeningHours.css'

interface Props {
  today: string | null
  weekly: HoursRow[]
}

/** Today's hours at a glance, with the whole week one tap away. Renders nothing without data. */
export function OpeningHours({ today, weekly }: Props) {
  if (today === null && weekly.length === 0) return null
  const summary = (
    <span className="opening-hours__today">
      <span aria-hidden="true">🕒</span> 오늘 {today ?? '정보 없음'}
    </span>
  )
  if (weekly.length <= 1) return <p className="opening-hours opening-hours--plain">{summary}</p>

  return (
    <details className="opening-hours">
      <summary>
        {summary}
        <span className="opening-hours__more">전체 보기</span>
      </summary>
      <dl className="opening-hours__list">
        {weekly.map((row) => (
          <div key={row.days} className="opening-hours__row" data-today={row.is_today}>
            <dt>{row.days}</dt>
            <dd>{row.text}</dd>
          </div>
        ))}
      </dl>
      <p className="opening-hours__note">휴게시간·라스트오더는 매장 사정에 따라 달라질 수 있어요.</p>
    </details>
  )
}
