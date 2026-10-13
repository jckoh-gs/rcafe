import type { GeoPoint } from '../../../shared/api'
import { PRESETS } from '../../../shared/config'
import { isInsideKorea, samePoint } from './location'

/** A place the visitor saved to come back to; kept in this browser only (there are no accounts). */
export interface Favorite {
  id: string
  name: string
  point: GeoPoint
}

export const STORAGE_KEY = 'rcafe.favorites.v1'
export const MAX_FAVORITES = 20
export const MAX_NAME_LENGTH = 20
const DEFAULT_PREFIX = 'default:'

/** The stations everyone starts with. They are ordinary favorites: they can be deleted too. */
export function defaultFavorites(): Favorite[] {
  return PRESETS.map((preset) => ({ id: `${DEFAULT_PREFIX}${preset.name}`, name: preset.name, point: preset.point }))
}

function isFavorite(value: unknown): value is Favorite {
  if (typeof value !== 'object' || value === null) return false
  const { id, name, point } = value as Partial<Favorite>
  return (
    typeof id === 'string' &&
    typeof name === 'string' &&
    name.trim().length > 0 &&
    typeof point?.lat === 'number' &&
    typeof point?.lng === 'number' &&
    Number.isFinite(point.lat) &&
    Number.isFinite(point.lng) &&
    isInsideKorea(point)
  )
}

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null // blocked (private window, strict settings): favorites then last until the page closes
  }
}

/** What this browser saved, or the starting stations when nothing was ever saved. */
export function loadFavorites(): Favorite[] {
  try {
    const raw = storage()?.getItem(STORAGE_KEY)
    if (!raw) return defaultFavorites()
    const parsed: unknown = JSON.parse(raw)
    const items = (parsed as { items?: unknown } | null)?.items
    if (!Array.isArray(items)) return defaultFavorites()
    return items.filter(isFavorite).slice(0, MAX_FAVORITES) // an empty list is a real choice: keep it
  } catch {
    return defaultFavorites()
  }
}

export function saveFavorites(items: readonly Favorite[]): void {
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify({ v: 1, items }))
  } catch {
    // storage full or blocked: the list still works for this visit
  }
}

export type AddFailure = 'empty' | 'duplicate' | 'full' | 'outside'

export type AddResult = { ok: true; items: Favorite[] } | { ok: false; reason: AddFailure }

/** HTTP pages have no `crypto.randomUUID`, so ids come from the clock and a random part. */
export function newId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export function addFavorite(
  items: readonly Favorite[],
  name: string,
  point: GeoPoint,
  makeId: () => string = newId,
): AddResult {
  const clean = name.trim().replace(/\s+/g, ' ').slice(0, MAX_NAME_LENGTH)
  if (!clean) return { ok: false, reason: 'empty' }
  if (!isInsideKorea(point)) return { ok: false, reason: 'outside' }
  if (items.some((f) => samePoint(f.point, point))) return { ok: false, reason: 'duplicate' }
  if (items.length >= MAX_FAVORITES) return { ok: false, reason: 'full' }
  return { ok: true, items: [...items, { id: makeId(), name: clean, point }] }
}

export function removeFavorite(items: readonly Favorite[], id: string): Favorite[] {
  return items.filter((f) => f.id !== id)
}

/** Brings the starting stations back (first), keeping the places the visitor added. */
export function restoreDefaults(items: readonly Favorite[]): Favorite[] {
  const mine = items.filter((f) => !f.id.startsWith(DEFAULT_PREFIX))
  const missing = defaultFavorites().filter((d) => !mine.some((m) => samePoint(m.point, d.point)))
  return [...missing, ...mine].slice(0, MAX_FAVORITES)
}

export function hasAllDefaults(items: readonly Favorite[]): boolean {
  return defaultFavorites().every((d) => items.some((f) => samePoint(f.point, d.point)))
}
