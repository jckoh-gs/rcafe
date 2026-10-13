import type { GeoPoint } from '../../../shared/api'
import { useCollectionRequest } from '../model/useCollectionRequest'
import './RequestCollection.css'

interface Props {
  point: GeoPoint
  /** Shown above the button, e.g. why the request is offered. */
  intro?: string
}

/** "이 지역 수집 요청하기": the visitor asks for an area without data to be collected overnight. */
export function RequestCollection({ point, intro }: Props) {
  const { phase, result, error, send } = useCollectionRequest(point)
  const status = result?.status ?? 'none'
  const asked = status === 'queued' || status === 'already_queued' || status === 'collecting'
  const canAsk = status === 'none' || status === 'done'

  return (
    <section className="request-collection" aria-label="수집 요청">
      {intro && <p className="request-collection__intro">{intro}</p>}

      {result && status !== 'none' && (
        <p className="request-collection__result" role="status" data-status={status}>
          {result.message}
        </p>
      )}
      {error && (
        <p className="request-collection__error" role="alert">
          {error}
        </p>
      )}

      {canAsk && status !== 'done' && (
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void send()}
          disabled={phase !== 'ready'}
        >
          {phase === 'sending' ? '요청을 보내는 중…' : '이 지역 수집 요청하기'}
        </button>
      )}
      {asked && (
        <p className="request-collection__hint">
          요청은 서비스가 한가한 새벽에 모아서 처리해요. 다시 들러서 확인해 주세요.
        </p>
      )}
    </section>
  )
}
