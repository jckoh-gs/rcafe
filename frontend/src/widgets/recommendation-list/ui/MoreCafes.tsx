import { useId, useRef, useState } from 'react'
import type { RecommendationItem } from '../../../shared/api'
import { CafeCard } from './CafeCard'
import './MoreCafes.css'

/**
 * The cafes after the podium, folded away until asked for. While folded nothing of them is
 * rendered, so their photos are not even requested.
 */
export function MoreCafes({ items }: { items: RecommendationItem[] }) {
  const [open, setOpen] = useState(false)
  const listId = useId()
  const toggle = useRef<HTMLButtonElement>(null)

  if (items.length === 0) return null

  function close() {
    setOpen(false)
    // the list was long: bring the button back into view instead of leaving the reader far below
    toggle.current?.scrollIntoView?.({ block: 'nearest' })
  }

  return (
    <section className="more-cafes" aria-label="추천 더보기">
      <button
        ref={toggle}
        type="button"
        className="btn btn--ghost more-cafes__toggle"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => (open ? close() : setOpen(true))}
      >
        {open ? '추천 접기' : `추천 더보기 · ${items.length}곳`}
        <span className="more-cafes__chevron" aria-hidden="true" data-open={open}>
          ▾
        </span>
      </button>

      {open && (
        <div id={listId} className="more-cafes__panel">
          <ol className="more-cafes__items">
            {items.map((item) => (
              <li key={item.cafe.place_id}>
                <CafeCard item={item} compact />
              </li>
            ))}
          </ol>
          <button type="button" className="btn btn--ghost more-cafes__toggle" onClick={close}>
            접기
          </button>
        </div>
      )}
    </section>
  )
}
