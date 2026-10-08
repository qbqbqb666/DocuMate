/**
 * AuthGuard - 根据登录状态切换显示什么
 *
 * status='loading'        → 显示加载页 (自动用 refresh_token 换 access 时)
 * status='unauthenticated' → 显示 LoginPage / RegisterPage (2 个之间切换)
 * status='authenticated'   → 显示子内容 (主界面)
 *
 * 阶段 B 会扩展: 已认证但未填 API Key 时显示公告 + Key 输入
 */
import { useState, ReactNode } from 'react'
import { useAuth } from './useAuth'
import { LoginPage } from './LoginPage'
import { RegisterPage } from './RegisterPage'
import { BrandMark } from '../components/BrandMark'
import { AuthAPI, AuthError } from './AuthClient'
import { UpdateGate } from '../components/UpdateGate'

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status, user, accessToken, refreshUser } = useAuth()
  const [view, setView] = useState<'login' | 'register'>('login')

  if (status === 'loading') {
    return <LoadingScreen />
  }

  if (status === 'unauthenticated') {
    return view === 'login' ? (
      <LoginPage onSwitchToRegister={() => setView('register')} />
    ) : (
      <RegisterPage onSwitchToLogin={() => setView('login')} />
    )
  }

  return <UpdateGate>{children}<Onboarding user={user} accessToken={accessToken} onRefresh={refreshUser} /></UpdateGate>
}


function LoadingScreen() {
  return (
    <div className="h-screen w-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="text-center space-y-4">
        <BrandMark size={52} className="mx-auto animate-pulse" />
        <div className="text-slate-500 text-sm">DocuMate 正在启动…</div>
        <div className="w-32 h-1 mx-auto bg-slate-200 rounded-full overflow-hidden">
          <div className="h-full w-1/2 rounded-full animate-pulse"
               style={{ background: 'linear-gradient(135deg, #1e3a8a, #4f85cc)' }} />
        </div>
      </div>
    </div>
  )
}

function Onboarding({ user, accessToken, onRefresh }: { user: ReturnType<typeof useAuth>['user']; accessToken: string | null; onRefresh: () => Promise<void> }) {
  const [step, setStep] = useState<'welcome' | 'key' | null>(() => user && !user.seen_welcome ? 'welcome' : user && !user.has_api_key ? 'key' : null)
  const [key, setKey] = useState('')
  const [provider, setProvider] = useState<'siliconflow' | 'deepseek'>('siliconflow')
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!step || !user || !accessToken) return null
  const saveKey = async () => { setError(null); if (!key.trim()) return setError('请输入 API Key'); setSaving(true); try { await AuthAPI.setApiKey(key.trim(), accessToken, provider); await onRefresh(); setStep(null) } catch (reason) { setError(reason instanceof AuthError ? reason.detail : '保存失败，请稍后重试') } finally { setSaving(false) } }
  const continueWelcome = async () => { try { await AuthAPI.markSeenWelcome(accessToken); await onRefresh() } finally { setStep(user.has_api_key ? null : 'key') } }
  const providerLabel = provider === 'deepseek' ? 'DeepSeek' : 'SiliconFlow'
  return <div className="onboarding-overlay"><div className="onboarding-card">{step === 'welcome' ? <><div className="onboarding-illustration"><BrandMark size={76} /></div><p className="onboarding-kicker">欢迎来到 DocuMate</p><h2>让 AI 成为你的<br />文档搭档</h2><p className="onboarding-copy">资料留在你的工作区，需要时再让 Agent 阅读、检索、整理或生成内容。</p><div className="onboarding-points"><span>本地文件优先</span><span>按需调用 AI</span><span>任务始终可确认</span></div><div className="onboarding-actions"><button className="onboarding-secondary" onClick={continueWelcome}>稍后再说</button><button className="onboarding-primary" onClick={continueWelcome}>配置 API Key</button></div></> : <><div className="onboarding-illustration is-key"><BrandMark size={58} /></div><p className="onboarding-kicker">最后一步</p><h2>连接你的 AI 服务</h2><p className="onboarding-copy">选择 SiliconFlow 或 DeepSeek，密钥可随时在个人中心更换。</p><div className="dm-provider-choice"><button type="button" className={provider === 'siliconflow' ? 'is-selected' : ''} onClick={() => setProvider('siliconflow')}>SiliconFlow</button><button type="button" className={provider === 'deepseek' ? 'is-selected' : ''} onClick={() => setProvider('deepseek')}>DeepSeek</button></div><label className="onboarding-input">{providerLabel} API Key<div><input type={showKey ? 'text' : 'password'} value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-..." autoFocus /><button type="button" onClick={() => setShowKey(!showKey)}>{showKey ? '隐藏' : '显示'}</button></div></label>{provider === 'deepseek' && <p className="dm-provider-note">DeepSeek 用于聊天 Agent；向量检索与图片识别仍需 SiliconFlow。</p>}{error && <p className="onboarding-error">{error}</p>}<div className="onboarding-actions"><button className="onboarding-secondary" onClick={() => setStep(null)}>暂时跳过</button><button className="onboarding-primary" disabled={saving} onClick={saveKey}>{saving ? '验证中…' : '验证并保存'}</button></div></>}</div></div>
}
