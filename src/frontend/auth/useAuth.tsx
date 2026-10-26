/**
 * useAuth - 全局认证 Context
 *
 * 状态:
 *   - user: 当前用户 (未登录 = null)
 *   - accessToken: 内存里的 access token (30min)
 *   - 状态: loading / authenticated / unauthenticated
 *
 * 持久化:
 *   - refresh_token 记住登录时由 Electron safeStorage 加密，否则仅存当前会话
 *   - access_token 只在内存 (重启 App 后用 refresh_token 自动换新的)
 *
 * 自动行为:
 *   - App 启动: 有 refresh_token → 调 /refresh 拿新 access → 调 /me 拿用户信息
 *   - access 30min 过期: API 调用 401 时, 自动 refresh 后重试
 *   - 登录 / 注册: 同时更新 user + tokens + 持久化
 *   - 登出: 调 /logout + 清空所有状态
 *   - access token 变化时: 自动 push 给本地 Python backend (B1 方案,
 *     让 backend 走 Auth Service 代理调 LLM/Embedding/Vision)
 */
import {
  createContext, useContext, useEffect, useState, ReactNode, useCallback,
} from 'react'
import { AuthAPI, AuthError, type UserInfo, type AuthResponse, type EmailCredentials, type EmailPasswordCredentials } from './AuthClient'

// 本地 Python backend 地址 (Electron 拉起的 FastAPI)
// 不通过 import.meta.env 配, 因为 backend 端口在 Electron 启动时定死 8765
const LOCAL_BACKEND = 'http://127.0.0.1:8765'

/** 把 access_token 推给本地 Python backend (内存里, backend 重启会丢) */
async function pushTokenToBackend(accessToken: string, username?: string): Promise<void> {
  try {
    await fetch(`${LOCAL_BACKEND}/__internal/set-token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: accessToken, username }),
    })
  } catch (err) {
    // 推送失败不阻塞 UI (用户可能离线 / backend 没起). backend 端只是会回退到直连模式.
    console.warn('[useAuth] push token to local backend failed:', err)
  }
}

/** 通知本地 backend 清空 token (退出登录时) */
async function clearTokenInBackend(): Promise<void> {
  try {
    await fetch(`${LOCAL_BACKEND}/__internal/set-token`, { method: 'DELETE' })
  } catch {
    // ignore
  }
}

interface AuthState {
  user: UserInfo | null
  accessToken: string | null
  status: 'loading' | 'authenticated' | 'unauthenticated'
}

interface AuthContextValue extends AuthState {
  localMode: boolean
  login: (payload: EmailPasswordCredentials, remember: boolean) => Promise<void>
  register: (payload: EmailCredentials) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

const REFRESH_KEY = 'documate.refresh_token'
const REMEMBER_KEY = 'documate.remember'

async function loadStoredRefresh(): Promise<string | null> {
  const secure = await window.documate?.loadRefreshToken?.()
  return secure || sessionStorage.getItem(REFRESH_KEY)
}

async function saveRefresh(token: string, remember: boolean): Promise<void> {
  if (remember) {
    if (window.documate?.saveRefreshToken) await window.documate.saveRefreshToken(token)
    else localStorage.setItem(REFRESH_KEY, token)
    sessionStorage.removeItem(REFRESH_KEY)
  } else {
    sessionStorage.setItem(REFRESH_KEY, token)
    localStorage.removeItem(REFRESH_KEY)
    await window.documate?.clearRefreshToken?.()
  }
  localStorage.setItem(REMEMBER_KEY, remember ? '1' : '0')
}

async function clearRefresh(): Promise<void> {
  localStorage.removeItem(REFRESH_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
  await window.documate?.clearRefreshToken?.()
}

function isRemembered(): boolean {
  return localStorage.getItem(REMEMBER_KEY) !== '0'
}


let restoringSession: Promise<AuthResponse | null> | null = null

function restoreSession(): Promise<AuthResponse | null> {
  if (!restoringSession) {
    restoringSession = (async () => {
      const stored = await loadStoredRefresh()
      if (!stored) return null
      const auth = await AuthAPI.refresh(stored)
      await saveRefresh(auth.refresh_token, isRemembered())
      return auth
    })().finally(() => { restoringSession = null })
  }
  return restoringSession
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    status: 'loading',
  })

  // StrictMode remounts share one refresh so a rotating token is not used twice.
  useEffect(() => {
    let active = true
    void restoreSession().then(auth => {
      if (active) setState(auth
        ? { user: auth.user, accessToken: auth.access_token, status: 'authenticated' }
        : { user: null, accessToken: null, status: 'unauthenticated' })
    }).catch(async reason => {
      if (!active) return
      const invalid = reason instanceof AuthError && (reason.status === 401 || reason.status === 403)
      if (invalid) await clearRefresh().catch(() => undefined)
      if (active) setState(current => !invalid && current.status === 'authenticated'
        ? current : { user: null, accessToken: null, status: 'unauthenticated' })
    })
    return () => { active = false }
  }, [])

  // token 变化时主动推送给本地 Python backend，供本机 API Key 接口验证会话。
  useEffect(() => {
    if (state.accessToken) {
      pushTokenToBackend(state.accessToken, state.user?.username)
    } else if (state.status === 'unauthenticated') {
      // 明确退出登录 (而非 loading 中) → 清掉 backend 的
      clearTokenInBackend()
    }
  }, [state.accessToken, state.status, state.user?.username])

  // 登录
  const login = useCallback(async (payload: EmailPasswordCredentials, remember: boolean) => {
    const auth = await AuthAPI.login(payload)
    await saveRefresh(auth.refresh_token, remember)
    setState({
      user: auth.user,
      accessToken: auth.access_token,
      status: 'authenticated',
    })
  }, [])

  // 注册 (注册成功直接登录)
  const register = useCallback(async (payload: EmailCredentials) => {
    const auth = await AuthAPI.register(payload)
    await saveRefresh(auth.refresh_token, true)
    setState({
      user: auth.user,
      accessToken: auth.access_token,
      status: 'authenticated',
    })
  }, [])

  // 登出
  const logout = useCallback(async () => {
    const stored = await loadStoredRefresh()
    if (state.accessToken && stored) {
      try {
        await AuthAPI.logout(stored || 'local', state.accessToken)
      } catch {
        // 登出失败也无所谓, 本地状态清掉即可
      }
    }
    await clearRefresh()
    setState({ user: null, accessToken: null, status: 'unauthenticated' })
  }, [state.accessToken])

  // 重新拉 /me (e.g. 设置 API Key 后)
  const refreshUser = useCallback(async () => {
    if (!state.accessToken) return
    try {
      const user = await AuthAPI.me(state.accessToken)
      setState((s) => ({ ...s, user }))
    } catch (e) {
      if (e instanceof AuthError && e.status === 401) {
        // token 过期 → 登出
        await logout()
      }
    }
  }, [state.accessToken, logout])

  return (
    <AuthContext.Provider value={{ ...state, localMode: false, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}


export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}
