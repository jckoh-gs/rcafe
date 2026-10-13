import { useCallback, useEffect, useState } from 'react'
import type { GeoPoint } from '../../../shared/api'
import { DEFAULT_LOCATION } from '../../../shared/config'
import { parseLocation, samePoint, toSearch } from './location'

/**
 * The area the user is looking at.
 * - `applied`: what recommendations are shown for (mirrored in the URL so it can be shared)
 * - `pending`: a pin the user moved on the map but has not confirmed yet
 */
export function useLocation() {
  const [applied, setApplied] = useState<GeoPoint>(() => parseLocation(window.location.search))
  const [pending, setPending] = useState<GeoPoint | null>(null)

  useEffect(() => {
    const onPop = () => {
      setApplied(parseLocation(window.location.search))
      setPending(null)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const apply = useCallback((point: GeoPoint) => {
    setApplied(point)
    setPending(null)
    window.history.pushState(null, '', toSearch(point))
  }, [])

  const move = useCallback((point: GeoPoint) => setPending(point), [])

  const confirm = useCallback(() => {
    if (pending) apply(pending)
  }, [apply, pending])

  const reset = useCallback(() => apply(DEFAULT_LOCATION), [apply])

  const hasPending = pending !== null && !samePoint(pending, applied)
  return { applied, pending: hasPending ? pending : null, apply, move, confirm, reset }
}
