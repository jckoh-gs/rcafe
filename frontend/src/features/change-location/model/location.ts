import { DEFAULT_LOCATION, PRESETS } from '../../../shared/config'
import type { GeoPoint } from '../../../shared/api'
import { distanceMeters } from '../../../shared/lib'

const KOREA = { latMin: 33, latMax: 39, lngMin: 124, lngMax: 132 }
const PRESET_SNAP_M = 250

export function isInsideKorea(point: GeoPoint): boolean {
  return (
    point.lat >= KOREA.latMin &&
    point.lat <= KOREA.latMax &&
    point.lng >= KOREA.lngMin &&
    point.lng <= KOREA.lngMax
  )
}

/** `?lat=..&lng=..` -> point; anything missing, malformed, or outside Korea gives the default. */
export function parseLocation(search: string): GeoPoint {
  const params = new URLSearchParams(search)
  const lat = Number(params.get('lat'))
  const lng = Number(params.get('lng'))
  const point = { lat, lng }
  if (params.get('lat') === null || params.get('lng') === null) return DEFAULT_LOCATION
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || !isInsideKorea(point)) return DEFAULT_LOCATION
  return point
}

export function toSearch(point: GeoPoint): string {
  return `?lat=${point.lat.toFixed(5)}&lng=${point.lng.toFixed(5)}`
}

export function samePoint(a: GeoPoint, b: GeoPoint): boolean {
  return distanceMeters(a, b) < 15
}

interface NamedPoint {
  name: string
  point: GeoPoint
}

/**
 * "회사 주변" near a saved place, "역삼역 주변" near a well-known station (even if its shortcut was
 * deleted), otherwise "선택한 위치 주변". Saved places win a tie.
 */
export function labelFor(point: GeoPoint, favorites: readonly NamedPoint[] = []): string {
  const known: NamedPoint[] = [...favorites, ...PRESETS]
  const near = known
    .map((place) => ({ place, d: distanceMeters(point, place.point) }))
    .filter(({ d }) => d <= PRESET_SNAP_M)
    .sort((a, b) => a.d - b.d)[0]
  return near ? `${near.place.name} 주변` : '선택한 위치 주변'
}
