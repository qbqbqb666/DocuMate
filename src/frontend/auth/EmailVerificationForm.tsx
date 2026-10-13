import { useEffect, useState, type FormEvent } from 'react'
import { AuthAPI, AuthError, type EmailCredentials } from './AuthClient'
import type { RobotMood } from './AuthHero'

interface Props {
  purpose: 'register' | 'reset'
  onSubmit: (payload: EmailCredentials, remember: boolean) => Promise<void>
  onPasswordFocus?: (mood: RobotMood) => void
}

export function EmailVerificationForm({ purpose, onSubmit, onPasswordFocus }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [verification, setVerification] = useState<{ id: string; email: string; expiresAt: number } | null>(null)
  const [retryAt, setRetryAt] = useState(0)
  const [seconds, setSeconds] = useState(0)
  const [busy, setBusy] = useState<'send' | 'submit' | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [ready, setReady] = useState<boolean | null>(null)
  const normalized = email.trim().toLowerCase()

  useEffect(() => {
    let alive = true
    AuthAPI.health().then(result => { if (alive) setReady(result.email_ready) })
      .catch(() => { if (alive) setError('无法连接邮箱认证服务，请稍后重试') })
    return () => { alive = false }
  }, [])
  useEffect(() => {
    setRetryAt(Number(sessionStorage.getItem(`email-retry:${normalized}`)) || 0)
  }, [normalized])
  useEffect(() => {
    const update = () => setSeconds(Math.max(0, Math.ceil((retryAt - Date.now()) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [retryAt])

  const send = async () => {
    setError(''); setMessage('')
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) return setError('请输入有效邮箱地址')
    setBusy('send')
    try {
      const result = await AuthAPI.sendEmailCode(normalized, purpose, password)
      setVerification({ id: result.verification_id, email: normalized, expiresAt: Date.now() + result.expires_in * 1000 })
      const until = Date.now() + result.retry_after * 1000
      if (result.retry_after > 0) sessionStorage.setItem(`email-retry:${normalized}`, String(until))
      setRetryAt(until); setCode(''); setMessage(result.message)
    } catch (reason) {
      setError(reason instanceof AuthError ? reason.detail : '发送失败，请检查网络后重试')
      if (reason instanceof AuthError && reason.status === 429) setRetryAt(Date.now() + reason.retryAfter * 1000)
    } finally { setBusy(null) }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setMessage('')
    if (!verification || verification.email !== normalized) return setError('请先获取该邮箱的验证码')
    if (verification.expiresAt <= Date.now()) return setError('验证码已过期，请重新获取')
    if (!/^[0-9]{6}$/.test(code)) return setError('请输入6位数字验证码')
    if (password.length < 6) return setError('密码至少需要6位')
    if (password !== confirm) return setError('两次密码输入不一致')
    setBusy('submit')
    try { await onSubmit({ email: normalized, password, verification_id: verification.id, code }, true) }
    catch (reason) { setError(reason instanceof AuthError ? reason.detail : '操作失败，请检查网络后重试') }
    finally { setBusy(null) }
  }

  const passwordField = <label><span>{purpose === 'reset' ? '新密码' : '密码'}</span>
    <input type="password" minLength={6} maxLength={128} required value={password} disabled={busy !== null}
      autoComplete="new-password" placeholder="至少6位"
      onFocus={() => onPasswordFocus?.('peek')} onBlur={() => onPasswordFocus?.('idle')}
      onChange={event => setPassword(event.target.value)} /></label>
  const codeField = <label>邮箱验证码<div className="auth-code-row">
    <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required
      value={code} onChange={event => setCode(event.target.value)} disabled={busy !== null} placeholder="输入6位验证码" />
    <button className="auth-code-send" type="button" onClick={() => void send()} disabled={busy !== null || seconds > 0 || ready === false}>
      {busy === 'send' ? '发送中…' : seconds > 0 ? `${seconds}秒后重发` : '获取验证码'}</button>
  </div></label>
  return <form onSubmit={submit} className="auth-form">
    <label>邮箱<input type="email" maxLength={254} required value={email} autoComplete="username"
      placeholder="输入邮箱地址" disabled={busy !== null} onChange={event => {
        setEmail(event.target.value); setVerification(null); setCode(''); setMessage(''); setError('')
      }} /></label>
    {codeField}{passwordField}
      <label>确认密码<input type="password" autoComplete="new-password" maxLength={128} required value={confirm}
        placeholder="再输入一次密码" disabled={busy !== null} onChange={event => setConfirm(event.target.value)}
        onFocus={() => onPasswordFocus?.('peek')} onBlur={() => onPasswordFocus?.('idle')} /></label>
    {ready === false && <div className="auth-error">邮箱认证服务尚未配置完成。</div>}
    {message && <p role="status" className="auth-email-message">{message}</p>}
    {error && <div role="alert" className="auth-error">{error}</div>}
    <button className="auth-primary" disabled={busy !== null || ready === false}>
      {busy === 'submit' ? '正在验证…' : purpose === 'register' ? '验证邮箱并创建账号' : '重设密码'}
    </button>
  </form>
}
