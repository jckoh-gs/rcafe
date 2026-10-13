import { useState } from 'react'
import type { AdminRequest, AdminStatus } from '../../../shared/api'
import { formatDateTime } from '../../../shared/lib'
import { useAdminRequests } from '../model/useAdminRequests'
import './AdminRequests.css'

const LABEL: Record<AdminStatus, string> = {
  pending: '대기 중',
  running: '수집 중',
  done: '완료',
  failed: '실패',
}
const FILTERS: readonly (AdminStatus | 'all')[] = ['all', 'pending', 'running', 'failed', 'done']

function mapLink(request: AdminRequest): string {
  const { lat, lng } = request
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=15/${lat}/${lng}`
}

interface Props {
  onSessionExpired: () => void
}

/** The collection request queue: see every request, run one now, requeue or delete it. */
export function AdminRequests({ onSessionExpired }: Props) {
  const { overview, loading, busyId, notice, error, reload, remove, requeue, runNow } =
    useAdminRequests(onSessionExpired)
  const [filter, setFilter] = useState<AdminStatus | 'all'>('all')
  const [confirming, setConfirming] = useState<number | null>(null)

  if (loading && !overview) return <p className="admin-requests__empty">불러오는 중…</p>

  const items = (overview?.items ?? []).filter((r) => filter === 'all' || r.status === filter)
  const collectorRunning = overview?.collector_running ?? false
  const total = overview ? Object.values(overview.counts).reduce((a, b) => a + b, 0) : 0

  return (
    <section className="admin-requests" aria-label="수집 요청 관리">
      <div className="admin-requests__bar">
        <div className="admin-requests__filters" role="group" aria-label="상태로 거르기">
          {FILTERS.map((key) => (
            <button
              key={key}
              type="button"
              className="admin-requests__chip"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {key === 'all' ? '전체' : LABEL[key]}{' '}
              <strong>{key === 'all' ? total : (overview?.counts[key] ?? 0)}</strong>
            </button>
          ))}
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void reload()}>
          새로고침
        </button>
      </div>

      <p className="admin-requests__collector" data-running={collectorRunning}>
        {collectorRunning
          ? '수집기가 일하는 중이에요. 끝나기 전에는 다른 요청을 지금 실행할 수 없어요.'
          : '수집기는 쉬는 중이에요. 대기 중인 요청은 매일 새벽 3시 30분에 처리돼요.'}
      </p>
      {notice && (
        <p className="admin-requests__notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="admin-requests__error" role="alert">
          {error}
        </p>
      )}

      {items.length === 0 ? (
        <p className="admin-requests__empty">
          {total === 0 ? '아직 들어온 수집 요청이 없어요.' : '이 상태의 요청이 없어요.'}
        </p>
      ) : (
        <table className="admin-requests__table">
          <caption className="admin-requests__caption">수집 요청 {items.length}건</caption>
          <thead>
            <tr>
              <th scope="col">지역</th>
              <th scope="col">상태</th>
              <th scope="col">요청</th>
              <th scope="col">카페</th>
              <th scope="col">시간</th>
              <th scope="col">처리</th>
            </tr>
          </thead>
          <tbody>
            {items.map((request) => {
              const running = request.status === 'running'
              const busy = busyId === request.id
              const locked = busyId !== null
              return (
                <tr key={request.id} data-status={request.status}>
                  <td data-label="지역">
                    <a href={mapLink(request)} target="_blank" rel="noopener noreferrer">
                      {request.lat.toFixed(3)}, {request.lng.toFixed(3)}
                    </a>
                    <small>
                      {request.cell_key} · 반경 {request.radius_m}m
                    </small>
                  </td>
                  <td data-label="상태">
                    <span className="admin-requests__status" data-status={request.status}>
                      {LABEL[request.status]}
                    </span>
                    {request.note && <small>{request.note}</small>}
                  </td>
                  <td data-label="요청">{request.request_count}번</td>
                  <td data-label="카페">
                    주변 {request.cafes_nearby}곳
                    {request.cafes_found !== null && <small>수집 {request.cafes_found}곳</small>}
                  </td>
                  <td data-label="시간">
                    <span>요청 {formatDateTime(request.last_requested_at)}</span>
                    {request.finished_at && <small>끝 {formatDateTime(request.finished_at)}</small>}
                  </td>
                  <td data-label="처리">
                    <div className="admin-requests__actions">
                    {confirming === request.id ? (
                      <>
                        <span className="admin-requests__ask">정말 삭제할까요?</span>
                        <button
                          type="button"
                          className="btn btn--danger"
                          disabled={locked}
                          onClick={() => {
                            setConfirming(null)
                            void remove(request.id)
                          }}
                        >
                          삭제 확정
                        </button>
                        <button type="button" className="btn btn--ghost" onClick={() => setConfirming(null)}>
                          취소
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn btn--primary"
                          disabled={running || collectorRunning || locked}
                          onClick={() => void runNow(request.id)}
                          aria-label={`${request.cell_key} 지금 실행`}
                        >
                          {busy ? '요청 중…' : '지금 실행'}
                        </button>
                        {(request.status === 'failed' || request.status === 'done') && (
                          <button
                            type="button"
                            className="btn btn--ghost"
                            disabled={locked}
                            onClick={() => void requeue(request.id)}
                            aria-label={`${request.cell_key} 대기열로`}
                          >
                            대기열로
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn--ghost"
                          disabled={running || locked}
                          onClick={() => setConfirming(request.id)}
                          aria-label={`${request.cell_key} 삭제`}
                        >
                          삭제
                        </button>
                      </>
                    )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
