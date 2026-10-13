import { useCallback, useEffect, useState } from 'react'
import type { GeoPoint } from '../../../shared/api'
import {
  addFavorite,
  loadFavorites,
  removeFavorite,
  restoreDefaults,
  saveFavorites,
  STORAGE_KEY,
} from './favorites'
import type { AddFailure, Favorite } from './favorites'

/** The visitor's saved places: read from this browser, changed here, and kept in step across tabs. */
export function useFavorites() {
  const [items, setItems] = useState<Favorite[]>(() => loadFavorites())

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === STORAGE_KEY) setItems(loadFavorites())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const commit = useCallback((next: Favorite[]) => {
    saveFavorites(next)
    setItems(next)
  }, [])

  /** Resolves with why it was refused, or null when saved. */
  const add = useCallback(
    (name: string, point: GeoPoint): AddFailure | null => {
      const result = addFavorite(items, name, point)
      if (!result.ok) return result.reason
      commit(result.items)
      return null
    },
    [commit, items],
  )

  const remove = useCallback((id: string) => commit(removeFavorite(items, id)), [commit, items])
  const restore = useCallback(() => commit(restoreDefaults(items)), [commit, items])

  return { items, add, remove, restore }
}

export type Favorites = ReturnType<typeof useFavorites>
