import { useState, type FormEvent } from 'react'
import { useAuth } from './useAuth'
import { AuthError } from './AuthClient'
import { AuthHero, type RobotMood } from './AuthHero'
import { BrandMark } from '../components/BrandMark'

export function LoginPage({ onSwitchToRegister }: { onSwitchToRegister: () => void }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [forgot, setForgot] = useState(false)
  const [robotMood, setRobotMood] = useState<RobotMood>('idle')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null)
    if (!username || !password) return setError('请填写账号和密码')
    setLoading(true)
    try { await login(username.trim(), password, remember) } catch (reason) { setError(reason instanceof AuthError ? reason.detail : '登录失败，请检查认证服务是否已启动'); setLoading(false) }
  }
  return <div className="auth-page"><AuthHero mood={robotMood} /><main className="auth-panel"><div className="auth-mobile-brand"><BrandMark size={42} /><b>DocuMate</b></div><div className="auth-form-wrap"><p className="auth-kicker">欢迎回来</p><h2>登录你的工作区</h2><p className="auth-subtitle">继续你上一次未完成的资料工作。</p><form onSubmit={submit} className="auth-form"><label>账号<input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="至少 8 位账号" minLength={8} maxLength={32} autoComplete="username" disabled={loading} /></label><label><span>密码<button type="button" onClick={() => setForgot(true)}>忘记密码？</button></span><input type="password" value={password} onFocus={() => setRobotMood('peek')} onBlur={() => setRobotMood('idle')} onChange={(e) => setPassword(e.target.value)} placeholder="输入密码" autoComplete="current-password" disabled={loading} /></label><label className="auth-check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />记住登录</label>{error && <div className="auth-error">{error}</div>}<button className="auth-primary" disabled={loading}>{loading ? '正在登录…' : '登录 DocuMate'}</button></form><p className="auth-switch">还没有账号？<button onClick={onSwitchToRegister}>创建一个账号</button></p></div></main>{forgot && <div className="auth-modal-overlay" role="presentation" onMouseDown={() => setForgot(false)}><div className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="forgot-title" onMouseDown={(event) => event.stopPropagation()}><h3 id="forgot-title">忘记密码</h3><p>此功能未完善，如果您忘记了密码请重新创建一个。</p><button type="button" onClick={() => setForgot(false)}>我知道了</button></div></div>}</div>
}
