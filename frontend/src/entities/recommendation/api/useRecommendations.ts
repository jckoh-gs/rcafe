import { useCallback, useEffect, useState } from 'react'
import { ApiError, fetchRecommendations } from '../../../shared/api'
import type { GeoPoint, Recommendations } from '../../../shared/api'

export type RecommendationState =
  | { status: 'loading'; data: Recommendations | null }
  | { status: 'ready'; data: Recommendations }
  | { status: 'error'; data: Recommendations | null; message: string }

interface Outcome {
  key: string
  data: Recommendations | null
  error: string | null
}

const FALLBACK_ERROR = '추천을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'

/**
 * Loads recommendations for a point. Earlier results stay on screen while a new area loads, so the
 * page does not flash empty when the user moves the pin.
 */
export function useRecommendations(point: GeoPoint, radiusM: number) {
  const { lat, lng } = point
  const [attempt, setAttempt] = useState(0)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [lastData, setLastData] = useState<Recommendations | null>(null)
  const key = `${lat}|${lng}|${radiusM}|${attempt}`

  useEffect(() => {
    const controller = new AbortController()
    fetchRecommendations({ lat, lng }, radiusM, controller.signal)
      .then((data) => {
        setLastData(data)
        setOutcome({ key, data, error: null })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const message = error instanceof ApiError ? error.message : FALLBACK_ERROR
        setOutcome({ key, data: null, error: message })
      })
    return () => controller.abort()
  }, [key, lat, lng, radiusM])

  const settled = outcome !== null && outcome.key === key
  let state: RecommendationState
  if (!settled) state = { status: 'loading', data: lastData }
  else if (outcome.error !== null) state = { status: 'error', data: lastData, message: outcome.error }
  else state = { status: 'ready', data: outcome.data as Recommendations }

  const retry = useCallback(() => setAttempt((n) => n + 1), [])
  return { state, retry }
}
