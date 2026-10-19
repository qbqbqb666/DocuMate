import { useState } from 'react'
import { useAuth } from './useAuth'
import { AuthHero, type RobotMood } from './AuthHero'
import { BrandMark } from '../components/BrandMark'
import { EmailVerificationForm } from './EmailVerificationForm'

export function RegisterPage({ onSwitchToLogin }: { onSwitchToLogin: () => void }) {
  const { register } = useAuth()
  const [robotMood, setRobotMood] = useState<RobotMood>('idle')
  return <div className="auth-page"><AuthHero mood={robotMood} /><main className="auth-panel auth-register-panel">
    <div className="auth-mobile-brand"><BrandMark size={42} /><b>DocuMate</b></div>
    <div className="auth-form-wrap"><p className="auth-kicker">创建账号</p><h2>开始使用 DocuMate</h2>
      <p className="auth-subtitle">验证邮箱并设置密码，创建你的账号。</p>
      <EmailVerificationForm purpose="register" onSubmit={register} onPasswordFocus={setRobotMood} />
      <p className="auth-switch">已经有账号？<button onClick={onSwitchToLogin}>返回登录</button></p>
    </div></main></div>
}
