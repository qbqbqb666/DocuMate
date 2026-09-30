import type { ApiErrorEnvelope } from './types'

export const API_BASE_URL =
  import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8765'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(apiUrl(path), { ...options, headers })
  if (!response.ok) throw await responseError(response)
  return response
}

async function responseError(response: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `HTTP ${response.status}`
  try {
    const payload = (await response.json()) as Partial<ApiErrorEnvelope> & { detail?: unknown }
    if (payload.error) {
      code = payload.error.code || code
      message = payload.error.message || message
    } else if (typeof payload.detail === 'string') {
      message = payload.detail
    }
  } catch {
    // 非 JSON 错误保留统一 HTTP 描述。
  }
  return new ApiError(response.status, code, message)
}
