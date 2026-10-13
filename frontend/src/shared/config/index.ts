import type { GeoPoint } from '../api/types'

/** Empty by default: the API is served from the same origin (ingress `/api`). */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

/** Yeoksam Station: where the collected cafe data is centered. */
export const DEFAULT_LOCATION: GeoPoint = { lat: 37.5006431, lng: 127.0363766 }
export const DEFAULT_RADIUS_M = 1000

export interface Preset {
  name: string
  point: GeoPoint
}

/** Quick "other area" shortcuts, all inside the collected area. */
export const PRESETS: readonly Preset[] = [
  { name: '역삼역', point: { lat: 37.5006431, lng: 127.0363766 } },
  { name: '강남역', point: { lat: 37.4979, lng: 127.0276 } },
  { name: '선릉역', point: { lat: 37.5045, lng: 127.049 } },
  { name: '논현역', point: { lat: 37.5111, lng: 127.0215 } },
]

export const MAP_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const MAP_ATTRIBUTION = '© OpenStreetMap contributors'
