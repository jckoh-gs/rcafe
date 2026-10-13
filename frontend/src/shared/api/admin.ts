import { API_BASE_URL } from '../config'
import { ApiError } from './client'
import type { AdminOverview } from './types'

const BASE = `${API_BASE_URL}/api/v1/admin`
const FALLBACK = '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.'

async function detail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const text = (body as { detail: unknown }).detail
      if (typeof text === 'string') return text
    }
  } catch {
    // not JSON; use the generic text
  }
  return FALLBACK
}

/** The admin API only answers calls that carry this header (see the server's guard). */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Request': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('네트워크에 연결할 수 없어요. 연결을 확인해 주세요.', 0)
  }
  if (!response.ok) throw new ApiError(await detail(response), response.status)
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

export function fetchAdminSession(): Promise<{ user: string }> {
  return call('GET', '/session')
}

export function adminLogin(username: string, password: string): Promise<{ user: string }> {
  return call('POST', '/login', { username, password })
}

export function adminLogout(): Promise<void> {
  return call('POST', '/logout')
}

export function fetchAdminOverview(): Promise<AdminOverview> {
  return call('GET', '/collection-requests')
}

export function deleteAdminRequest(id: number): Promise<void> {
  return call('DELETE', `/collection-requests/${id}`)
}

export function requeueAdminRequest(id: number): Promise<void> {
  return call('POST', `/collection-requests/${id}/requeue`)
}

/** Starts a collector for this request right now; resolves with the name of the cluster Job. */
export function runAdminRequest(id: number): Promise<{ job: string }> {
  return call('POST', `/collection-requests/${id}/run`)
}
