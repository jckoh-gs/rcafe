import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  deleteAdminRequest,
  fetchAdminOverview,
  requeueAdminRequest,
  runAdminRequest,
} from '../../../shared/api'
import type { AdminOverview } from '../../../shared/api'

const REFRESH_WHILE_COLLECTING_MS = 10_000

/**
 * The collection request queue and what the administrator can do with it. While a collector is
 * working the list refreshes by itself, so progress shows up without pressing anything.
 */
export function useAdminRequests(onSessionExpired: () => void) {
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const expired = useRef(onSessionExpired)
  useEffect(() => {
    expired.current = onSessionExpired
  }, [onSessionExpired])

  const fail = useCallback((caught: unknown) => {
    if (caught instanceof ApiError && caught.status === 401) expired.current()
    else setError(caught instanceof ApiError ? caught.message : '요청을 처리하지 못했어요.')
  }, [])

  const load = useCallback(async () => {
    try {
      setOverview(await fetchAdminOverview())
      setError(null)
    } catch (caught) {
      fail(caught)
    } finally {
      setLoading(false)
    }
  }, [fail])

  useEffect(() => {
    let alive = true
    fetchAdminOverview()
      .then((first) => {
        if (!alive) return
        setOverview(first)
        setError(null)
      })
      .catch((caught: unknown) => alive && fail(caught))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [fail])

  const collecting =
    overview !== null && (overview.collector_running || overview.counts.running > 0)
  useEffect(() => {
    if (!collecting) return
    const timer = setInterval(() => void load(), REFRESH_WHILE_COLLECTING_MS)
    return () => clearInterval(timer)
  }, [collecting, load])

  const act = useCallback(
    async (id: number, work: () => Promise<string>) => {
      setBusyId(id)
      setNotice(null)
      setError(null)
      try {
        setNotice(await work())
      } catch (caught) {
        fail(caught)
      } finally {
        setBusyId(null)
        await load()
      }
    },
    [fail, load],
  )

  const remove = useCallback(
    (id: number) =>
      act(id, async () => {
        await deleteAdminRequest(id)
        return '요청을 삭제했어요.'
      }),
    [act],
  )
  const requeue = useCallback(
    (id: number) =>
      act(id, async () => {
        await requeueAdminRequest(id)
        return '다시 대기열에 넣었어요. 다음 새벽 수집에서 처리돼요.'
      }),
    [act],
  )
  const runNow = useCallback(
    (id: number) =>
      act(id, async () => {
        const { job } = await runAdminRequest(id)
        return `수집을 시작했어요 (${job}). 몇 분 뒤 상태가 바뀌어요.`
      }),
    [act],
  )

  return { overview, loading, busyId, notice, error, reload: load, remove, requeue, runNow }
}
