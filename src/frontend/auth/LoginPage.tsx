import { useState, type FormEvent } from 'react'
import { useAuth } from './useAuth'
import { AuthAPI, AuthError } from './AuthClient'
import { AuthHero, type RobotMood } from './AuthHero'
import { BrandMark } from '../components/BrandMark'
import { EmailVerificationForm } from './EmailVerificationForm'
import { PasswordInput } from './PasswordInput'

export function LoginPage({ onSwitchToRegister }: { onSwitchToRegister: () => void }) {
  const { login } = useAuth()
  const [forgot, setForgot] = useState(false)
  const [resetDone, setResetDone] = useState(false)
  const [robotMood, setRobotMood] = useState<RobotMood>('idle')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try { await login({ email: email.trim().toLowerCase(), password }, remember) }
    catch (reason) { setError(reason instanceof AuthError ? reason.detail : '登录过程中发生异常，请稍后重试') }
    finally { setBusy(false) }
  }
  return <div className="auth-page"><AuthHero mood={robotMood} /><main className="auth-panel">
    <div className="auth-mobile-brand"><BrandMark size={42} /><b>DocuMate</b></div>
    <div className="auth-form-wrap"><p className="auth-kicker">欢迎回来</p><h2>登录你的工作区</h2>
      <p className="auth-subtitle">使用邮箱和密码登录。</p>
      <form className="auth-form" onSubmit={submit}>
        <label>邮箱<input type="email" autoComplete="username" required maxLength={254} value={email}
          placeholder="输入邮箱地址" disabled={busy} onChange={event => setEmail(event.target.value)} /></label>
        <label><span>密码<button type="button" onClick={() => { setResetDone(false); setForgot(true) }}>忘记密码？</button></span>
          <PasswordInput autoComplete="current-password" required minLength={6} maxLength={128}
            value={password} placeholder="输入密码" disabled={busy} onChange={event => setPassword(event.target.value)}
            onFocus={() => setRobotMood('peek')} onBlur={() => setRobotMood('idle')} /></label>
        <label className="auth-check"><input type="checkbox" checked={remember} disabled={busy}
          onChange={event => setRemember(event.target.checked)} />记住登录</label>
        {error && <div role="alert" className="auth-error">{error}</div>}
        <button className="auth-primary" disabled={busy}>{busy ? '正在登录…' : '登录 DocuMate'}</button>
      </form>
      <p className="auth-switch">还没有账号？<button onClick={onSwitchToRegister}>创建一个账号</button></p>
    </div></main><span className="auth-version">v{window.documate?.version || __APP_VERSION__}</span>{forgot && <div className="auth-modal-overlay" role="presentation" onMouseDown={() => setForgot(false)}>
      <div className="auth-modal auth-reset-modal" role="dialog" aria-modal="true" aria-labelledby="forgot-title"
        onMouseDown={event => event.stopPropagation()}><h3 id="forgot-title">找回密码</h3>
        {resetDone ? <p role="status">密码已重设，请使用新密码登录。</p> : <>
          <p>验证注册邮箱后设置新密码。</p><EmailVerificationForm purpose="reset" onSubmit={async payload => {
            await AuthAPI.resetPassword(payload); setResetDone(true)
          }} /></>}
        <button type="button" className="auth-reset-close" onClick={() => setForgot(false)}>关闭</button>
      </div></div>}</div>
}
