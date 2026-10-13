import { useState } from 'react'
import type { FormEvent } from 'react'
import type { GeoPoint } from '../../../shared/api'
import { hasAllDefaults, MAX_FAVORITES, MAX_NAME_LENGTH } from '../model/favorites'
import type { AddFailure } from '../model/favorites'
import { samePoint } from '../model/location'
import type { Favorites } from '../model/useFavorites'
import './FavoritePlaces.css'

interface Props {
  applied: GeoPoint
  favorites: Favorites
  onApplyPoint: (point: GeoPoint) => void
}

const FAILURE: Record<AddFailure, string> = {
  empty: '이름을 입력해 주세요.',
  duplicate: '이 위치는 이미 즐겨찾기에 있어요.',
  full: `즐겨찾기는 ${MAX_FAVORITES}곳까지 저장할 수 있어요.`,
  outside: '서비스 지역(대한민국) 밖이에요.',
}

/** Saved places as one-tap chips; add the area on screen, or delete chips in edit mode. */
export function FavoritePlaces({ applied, favorites, onApplyPoint }: Props) {
  const { items, add, remove, restore } = favorites
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const alreadySaved = items.some((f) => samePoint(f.point, applied))
  const full = items.length >= MAX_FAVORITES

  function startAdding() {
    setNotice(null)
    setError(null)
    setEditing(false)
    setAdding(true)
  }

  function cancelAdding() {
    setAdding(false)
    setName('')
    setError(null)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const failure = add(name, applied)
    if (failure) {
      setError(FAILURE[failure])
      return
    }
    setNotice(`'${name.trim()}'을(를) 즐겨찾기에 추가했어요.`)
    cancelAdding()
  }

  return (
    <div className="favorites" role="group" aria-label="즐겨찾기 지역">
      {items.length === 0 ? (
        <p className="favorites__empty">저장한 지역이 없어요. 지금 보는 지역을 추가해 보세요.</p>
      ) : (
        <ul className="favorites__chips">
          {items.map((favorite) => (
            <li key={favorite.id} className="favorites__chip">
              <button
                type="button"
                className="location-bar__preset"
                aria-pressed={samePoint(applied, favorite.point)}
                onClick={() => onApplyPoint(favorite.point)}
              >
                {favorite.name}
              </button>
              {editing && (
                <button
                  type="button"
                  className="favorites__remove"
                  aria-label={`${favorite.name} 즐겨찾기 삭제`}
                  onClick={() => {
                    setNotice(`'${favorite.name}'을(를) 삭제했어요.`)
                    remove(favorite.id)
                  }}
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <form className="favorites__form" onSubmit={submit}>
          <input
            className="favorites__input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={MAX_NAME_LENGTH}
            placeholder="이름 (예: 회사, 우리 집)"
            aria-label="즐겨찾기 이름"
            autoComplete="off"
            autoFocus
          />
          <button type="submit" className="btn btn--primary">
            저장
          </button>
          <button type="button" className="btn btn--ghost" onClick={cancelAdding}>
            취소
          </button>
        </form>
      ) : (
        <div className="favorites__tools">
          <button
            type="button"
            className="favorites__tool"
            onClick={startAdding}
            disabled={alreadySaved || full}
            title={alreadySaved ? '이 지역은 이미 즐겨찾기에 있어요' : full ? FAILURE.full : undefined}
          >
            ＋ 이 지역 즐겨찾기
          </button>
          {items.length > 0 && (
            <button
              type="button"
              className="favorites__tool"
              aria-pressed={editing}
              onClick={() => {
                setNotice(null)
                setEditing((value) => !value)
              }}
            >
              {editing ? '편집 끝' : '편집'}
            </button>
          )}
          {!hasAllDefaults(items) && (
            <button
              type="button"
              className="favorites__tool"
              onClick={() => {
                restore()
                setNotice('기본 지역을 되돌렸어요.')
              }}
            >
              기본 지역 되돌리기
            </button>
          )}
        </div>
      )}

      {error && (
        <p className="favorites__note favorites__note--error" role="alert">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="favorites__note" role="status">
          {notice}
        </p>
      )}
    </div>
  )
}
