import { API_BASE_URL } from '../config'
import type { CollectionRequestResult, GeoPoint, Recommendations } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const GENERIC_ERROR = '추천을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
    }
  } catch {
    // body was not JSON; fall through to the generic text
  }
  return GENERIC_ERROR
}

export async function fetchRecommendations(
  point: GeoPoint,
  radiusM: number,
  signal?: AbortSignal,
): Promise<Recommendations> {
  const params = new URLSearchParams({
    lat: point.lat.toFixed(6),
    lng: point.lng.toFixed(6),
    radius_m: String(radiusM),
  })
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/recommendations?${params}`, { signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('네트워크에 연결할 수 없어요. 연결을 확인해 주세요.', 0)
  }
  if (!response.ok) {
    const message = response.status === 422 ? '이 위치는 서비스 지역이 아니에요.' : await errorMessage(response)
    throw new ApiError(message, response.status)
  }
  return (await response.json()) as Recommendations
}

const REQUEST_ERROR = '요청을 보내지 못했어요. 잠시 후 다시 시도해 주세요.'

async function collectionCall(
  init: RequestInit,
  query: string,
  signal?: AbortSignal,
): Promise<CollectionRequestResult> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/collection-requests${query}`, { ...init, signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('네트워크에 연결할 수 없어요. 연결을 확인해 주세요.', 0)
  }
  if (!response.ok) {
    const message = response.status === 422 ? '이 위치는 요청할 수 없어요.' : await errorMessage(response)
    throw new ApiError(message === GENERIC_ERROR ? REQUEST_ERROR : message, response.status)
  }
  return (await response.json()) as CollectionRequestResult
}

/** Asks for the area around a point to be collected in the next quiet-hours run. */
export function requestCollection(point: GeoPoint): Promise<CollectionRequestResult> {
  return collectionCall(
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: point.lat, lng: point.lng }),
    },
    '',
  )
}

/** What became of an earlier request for this area (status "none" if nobody asked). */
export function fetchCollectionStatus(
  point: GeoPoint,
  signal?: AbortSignal,
): Promise<CollectionRequestResult> {
  const params = new URLSearchParams({ lat: point.lat.toFixed(6), lng: point.lng.toFixed(6) })
  return collectionCall({}, `?${params}`, signal)
}
