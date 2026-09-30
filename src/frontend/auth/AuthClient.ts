/**
 * AuthClient - 调 documate-auth-service 的 fetch 封装
 *
 * 自动处理:
 *   - Bearer JWT header
 *   - 401 时尝试 refresh
 *   - 业务错误 (4xx/5xx) 统一抛 AuthError
 */

const BASE = (import.meta.env.VITE_AUTH_SERVICE_URL || 'http://1.14.67.230/documate-auth').replace(/\/$/, '')
const LOCAL_BASE = (import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')

export interface UserInfo {
  id: number
  username: string
  display_name: string | null
  has_api_key: boolean
  sf_api_key_last4: string | null
  api_key_provider: 'siliconflow' | 'deepseek' | null
  seen_welcome: boolean
  status: 'active' | 'suspended' | 'banned'
  created_at: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: UserInfo
}

export interface ApiKeyStatus {
  provider: 'siliconflow' | 'deepseek'
  configured: boolean
  last4: string | null
}

export class AuthError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail)
    this.name = 'AuthError'
  }
}

function readableDetail(value: unknown, fallback: string): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    const data = value as Record<string, unknown>
    const title = typeof data.message === 'string' ? data.message : typeof data.error === 'string' ? data.error : null
    const explanation = typeof data.provider_error === 'string' ? data.provider_error : typeof data.siliconflow_error === 'string' ? data.siliconflow_error : null
    if (title && explanation) return `${title}：${explanation}`
    if (title) return title
    try { return JSON.stringify(data) } catch { return fallback }
  }
  return fallback
}

async function request<T>(
  path: string,
  opts: RequestInit & { auth?: string; base?: string } = {}
): Promise<T> {
  const { auth, base = BASE, headers, ...rest } = opts
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(headers as Record<string, string>),
  }
  if (auth) h['Authorization'] = `Bearer ${auth}`

  const resp = await fetch(`${base}${path}`, { ...rest, headers: h })
  const text = await resp.text()

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const j = JSON.parse(text)
      detail = readableDetail(j.detail ?? j.message ?? j.error, detail)
    } catch {
      if (text) detail = text.slice(0, 300)
    }
    throw new AuthError(resp.status, detail)
  }

  if (resp.status === 204 || !text) return undefined as T
  return JSON.parse(text) as T
}

// ============================================================
// Auth API
// ============================================================

export const AuthAPI = {
  health: () => request<{ ok: boolean }>('/health'),

  register: (username: string, password: string) =>
    request<AuthResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  login: (username: string, password: string) =>
    request<AuthResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  refresh: (refresh_token: string) =>
    request<AuthResponse>('/api/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token }),
    }),

  logout: (refresh_token: string, access_token: string) =>
    request<void>('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token }),
      auth: access_token,
    }),

  me: (access_token: string) =>
    request<UserInfo>('/api/user/me', { auth: access_token }),

  getApiKeys: (access_token: string) =>
    request<ApiKeyStatus[]>('/api/user/api-keys', { auth: access_token, base: LOCAL_BASE }),

  setApiKey: (api_key: string, access_token: string, provider: 'siliconflow' | 'deepseek' = 'siliconflow') =>
    request<ApiKeyStatus>(
      `/api/user/api-keys/${provider}`,
      {
        method: 'PUT',
        body: JSON.stringify({ api_key }),
        auth: access_token,
        base: LOCAL_BASE,
      }
    ),

  deleteApiKey: (provider: 'siliconflow' | 'deepseek', access_token: string) =>
    request<void>(`/api/user/api-keys/${provider}`, { method: 'DELETE', auth: access_token, base: LOCAL_BASE }),

  markSeenWelcome: (access_token: string) =>
    request<UserInfo>('/api/user/seen-welcome', {
      method: 'POST',
      auth: access_token,
    }),
}

export const AUTH_BASE_URL = BASE
