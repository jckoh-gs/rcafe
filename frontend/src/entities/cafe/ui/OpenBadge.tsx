import type { OpenState } from '../../../shared/api'
import './OpenBadge.css'

export function OpenBadge({ state }: { state: OpenState }) {
  const kind = state.is_open === true ? 'open' : state.is_open === false ? 'closed' : 'unknown'
  const detail =
    state.changes_at === null
      ? ''
      : state.is_open
        ? ` · ${state.changes_at}까지`
        : ` · ${state.changes_tomorrow ? '내일 ' : ''}${state.changes_at} 오픈`
  return (
    <span className="open-badge" data-kind={kind}>
      <span className="open-badge__dot" aria-hidden="true" />
      {state.label}
      {detail}
    </span>
  )
}
