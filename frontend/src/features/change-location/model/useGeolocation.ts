import { useCallback, useState } from 'react'
import type { GeoPoint } from '../../../shared/api'
import { isInsideKorea } from './location'

export type GeoStatus = 'idle' | 'locating' | 'denied' | 'unavailable' | 'outside'

/** Browsers only expose the position on HTTPS (or localhost). */
export function canUseGeolocation(): boolean {
  return typeof navigator !== 'undefined' && 'geolocation' in navigator && window.isSecureContext
}

export function useGeolocation(onFound: (point: GeoPoint) => void) {
  const [status, setStatus] = useState<GeoStatus>('idle')

  const locate = useCallback(() => {
    if (!canUseGeolocation()) {
      setStatus('unavailable')
      return
    }
    setStatus('locating')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const point = { lat: position.coords.latitude, lng: position.coords.longitude }
        if (!isInsideKorea(point)) {
          setStatus('outside')
          return
        }
        setStatus('idle')
        onFound(point)
      },
      (error) => setStatus(error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    )
  }, [onFound])

  return { status, locate }
}
