import { useCallback, useEffect, useState } from 'react'
import { ApiError, fetchCollectionStatus, requestCollection } from '../../../shared/api'
import type { CollectionRequestResult, GeoPoint } from '../../../shared/api'

export type RequestPhase = 'checking' | 'ready' | 'sending'

interface Outcome {
  key: string
  result: CollectionRequestResult | null
}

/**
 * State of "please collect this area": looks up an earlier request for the point (so a reload
 * shows "already waiting") and sends a new one on demand.
 */
export function useCollectionRequest(point: GeoPoint) {
  const { lat, lng } = point
  const key = `${lat}|${lng}`
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchCollectionStatus({ lat, lng }, controller.signal)
      .then((result) => setOutcome({ key, result }))
      .catch(() => {
        if (!controller.signal.aborted) setOutcome({ key, result: null }) // not knowing is fine
      })
    return () => controller.abort()
  }, [key, lat, lng])

  const send = useCallback(async () => {
    setSending(true)
    setError(null)
    try {
      setOutcome({ key, result: await requestCollection({ lat, lng }) })
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : '요청을 보내지 못했어요.'
      setError({ key, message })
    } finally {
      setSending(false)
    }
  }, [key, lat, lng])

  const checking = outcome === null || outcome.key !== key
  const result = checking ? null : outcome.result
  const phase: RequestPhase = sending ? 'sending' : checking ? 'checking' : 'ready'
  return { phase, result, error: error?.key === key ? error.message : null, send }
}
