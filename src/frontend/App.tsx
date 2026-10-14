import { useEffect, useState } from 'react'
import { useWorkspaceFiles, type FilePreview } from './hooks/useWorkspaceFiles'
import { useWorkspace } from './hooks/useWorkspace'
import { useSettings } from './hooks/useSettings'
import { useProjects } from './hooks/useProjects'
import { useStats } from './hooks/useStats'
import { DocumentSidebar } from './components/DocumentSidebar'
import { SearchPanel } from './components/SearchPanel'
import { ChatPanel } from './components/ChatPanel'
import { ProjectSidebar } from './components/ProjectSidebar'
import { NewConversationPage } from './components/NewConversationPage'
import { BrandMark } from './components/BrandMark'
import { Icon } from './components/Icon'
import { AuthProvider, useAuth } from './auth/useAuth'
import { AuthGuard } from './auth/AuthGuard'
import { AuthAPI, type ApiKeyStatus } from './auth/AuthClient'
import { apiRequest } from './api/client'
import type { ProjectSummary } from './api/types'

type AppArea = 'files' | 'workspace'

function App() {
  const workspace = useWorkspace()
  const { roots, count, loading, error, fetchDetail, refresh: refreshDocs } = useWorkspaceFiles(workspace.info?.path)
  const settings = useSettings()
  const projects = useProjects()
  const stats = useStats(workspace.info?.path)
  const { user, accessToken, logout, localMode } = useAuth()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<FilePreview | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [area, setArea] = useState<AppArea>('files')
  const [toast, setToast] = useState<string | null>(null)
  const [showProfile, setShowProfile] = useState(false)
  const [showSearch, setShowSearch] = useState(false)
  const [showApiKeyDialog, setShowApiKeyDialog] = useState(false)
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [apiProvider, setApiProvider] = useState<'siliconflow' | 'deepseek'>('siliconflow')
  const [apiKeySaving, setApiKeySaving] = useState(false)
  const [apiKeyError, setApiKeyError] = useState<string | null>(null)
  const [apiKeyStatuses, setApiKeyStatuses] = useState<ApiKeyStatus[]>([
    { provider: 'siliconflow', configured: false, last4: null },
    { provider: 'deepseek', configured: false, last4: null },
  ])
  const [agentName, setAgentName] = useState('DocuMate Agent')
  const [newSessionRequest, setNewSessionRequest] = useState(0)
  const [requestedThreadId, setRequestedThreadId] = useState<string | null>(null)
  const [showNewConversation, setShowNewConversation] = useState(false)
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)

  useEffect(() => {
    refreshDocs()
    setSelectedId(null)
    if (workspace.info?.path && window.documate?.watchWorkspace) window.documate.watchWorkspace(workspace.info.path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.info?.path])

  useEffect(() => {
    if (!window.documate?.onWorkspaceChanged) return
    return window.documate.onWorkspaceChanged(() => refreshDocs())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshDocs])

  useEffect(() => {
    if (activeProjectId || !projects.projects.length) return
    const active = projects.projects.find((project) => project.is_active) || projects.projects[0]
    setActiveProjectId(active.id)
  }, [activeProjectId, projects.projects])

  useEffect(() => {
    setDetail(null)
    setDetailError(null)
    if (!selectedId) { setDetailLoading(false); return }
    let cancelled = false
    let busy = false
    let version: string | undefined
    const load = async () => {
      if (busy) return
      busy = true
      try {
        const doc = await fetchDetail(selectedId, version)
        if (!cancelled && doc) { version = doc.version; setDetail(doc); setDetailError(null) }
      } catch (reason) {
        if (!cancelled) { version = undefined; setDetail(null); setDetailError(reason instanceof Error ? reason.message : String(reason)) }
      } finally {
        busy = false
        if (!cancelled) setDetailLoading(false)
      }
    }
    setDetailLoading(true)
    void load()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [selectedId, fetchDetail])

  const notify = (text: string) => {
    setToast(text)
    window.setTimeout(() => setToast(null), 3600)
  }

  const handleJumpToDoc = (docId: string) => {
    setArea('files')
    setShowSearch(false)
    setSelectedId(docId)
  }

  const openAgent = (name: string, newSession = false) => {
    setAgentName(name)
    setArea('workspace')
    if (newSession) {
      setRequestedThreadId(null)
      setNewSessionRequest((value) => value + 1)
    }
  }

  const openThread = async (project: ProjectSummary, threadId: string, title: string) => {
    await projects.activate(project.id)
    if (workspace.info?.path !== project.primary_path) await workspace.switchTo(project.primary_path)
    setActiveProjectId(project.id)
    setAgentName(title || '新对话')
    setRequestedThreadId(threadId)
    setArea('workspace')
    setShowNewConversation(false)
  }

  const createThreadForProject = async (project: ProjectSummary) => {
    await projects.activate(project.id)
    if (workspace.info?.path !== project.primary_path) await workspace.switchTo(project.primary_path)
    const result = await apiRequest<{ thread_id: string }>('/api/threads', {
      method: 'POST',
      body: JSON.stringify({ workspace_path: project.primary_path, project_id: project.id }),
    })
    setActiveProjectId(project.id)
    setAgentName('新对话')
    setRequestedThreadId(result.thread_id)
    setArea('workspace')
    setShowNewConversation(false)
    window.dispatchEvent(new Event('documate:threads-changed'))
  }

  const refreshApiKeyStatuses = async () => {
    if (!accessToken) return
    try { setApiKeyStatuses(await AuthAPI.getApiKeys(accessToken)) } catch { /* 状态读取失败不阻塞个人中心 */ }
  }

  const openProfile = () => {
    void stats.refresh()
    void refreshApiKeyStatuses()
    setShowProfile(true)
  }

  const openApiKeyDialog = (provider: 'siliconflow' | 'deepseek') => {
    setApiKeyInput('')
    setApiKeyError(null)
    setApiProvider(provider)
    setShowApiKeyDialog(true)
  }

  const saveApiKey = async () => {
    const key = apiKeyInput.trim()
    if (!key || !accessToken) return
    setApiKeySaving(true)
    setApiKeyError(null)
    try {
      const status = await AuthAPI.setApiKey(key, accessToken, apiProvider)
      setApiKeyStatuses((items) => items.map((item) => item.provider === status.provider ? status : item))
      setShowApiKeyDialog(false)
      setApiKeyInput('')
      notify('API Key 已安全保存')
    } catch (error) {
      setApiKeyError(error instanceof Error ? error.message : 'API Key 保存失败，请稍后重试')
    } finally {
      setApiKeySaving(false)
    }
  }

  if (workspace.loading || !workspace.info) return <LoadingWorkspace />

  const workspaceName = workspace.info.path.split('/').filter(Boolean).at(-1) || '我的工作区'
  const activeProject = projects.projects.find((project) => project.id === activeProjectId) || projects.projects.find((project) => project.is_active) || projects.projects[0]
  const displayName = user?.display_name || user?.username || '用户'

  return (
    <div className={`dm-app${window.documate?.platform === 'darwin' ? ' is-macos' : ''}`}>
      <div className="dm-window-drag" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties} />
      {toast && <div className="dm-toast"><Icon name="check" size={16} />{toast}</div>}

      <header className="dm-topbar" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
        <div className="dm-brand">
          <BrandMark size={32} />
          <span>DocuMate</span>
        </div>
        <div className="dm-breadcrumb"><Icon name="folder" size={16} /><span>{activeProject?.name || workspaceName}</span><Icon name="chevron" size={14} /><span className="dm-breadcrumb-muted">{showNewConversation ? '新对话' : area === 'files' ? '文件区' : '工作区'}</span></div>
        <div className="dm-header-actions" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
          <button className="dm-icon-button" onClick={() => notify('当前没有新的公告')} title="公告"><Icon name="sparkle" /></button>
          <button className="dm-icon-button" onClick={openProfile} title="个人中心"><Icon name="settings" /></button>
          <button className="dm-avatar" onClick={openProfile} title="个人中心">{displayName.slice(0, 1).toUpperCase()}</button>
          <button className="dm-icon-button" onClick={() => void logout()} title="退出登录"><Icon name="logout" /></button>
        </div>
      </header>

      <div className="dm-shell">
        <aside className="dm-sidebar">
          <div className="dm-workspace-switcher"><button className="dm-new-chat-primary" onClick={() => { setShowNewConversation(true); setArea('workspace') }}><Icon name="plus" size={17} />新对话</button></div>

          <nav className="dm-area-tabs">
            <button className={area === 'files' ? 'is-active' : ''} onClick={() => setArea('files')}><Icon name="folder" size={17} />文件区</button>
            <button className={area === 'workspace' ? 'is-active' : ''} onClick={() => setArea('workspace')}><Icon name="message" size={17} />工作区</button>
          </nav>

          <div className="dm-sidebar-content">
            {area === 'files' ? (
              <DocumentSidebar roots={roots} count={count} selectedId={selectedId} onSelect={setSelectedId} loading={loading} />
            ) : (
              <ProjectSidebar projects={projects.projects} activeThreadId={requestedThreadId} resetKey={showNewConversation ? 'new-conversation' : requestedThreadId || 'none'} onOpenThread={(project, threadId, title) => void openThread(project, threadId, title)} onNewThread={(project) => void createThreadForProject(project)} onDeleteThread={(threadId) => { if (threadId === requestedThreadId) { setRequestedThreadId(null); setAgentName('DocuMate Agent') } }} />
            )}
          </div>

          <div className="dm-sidebar-footer">
            {area === 'files' && <button className="dm-quiet-button" onClick={() => void refreshDocs()}>刷新目录</button>}
            {error && <div className="dm-inline-error">{error}</div>}
            <button className="dm-quiet-button" onClick={() => window.documate?.openFolder ? workspace.openInFinder() : notify('浏览器预览模式不支持打开访达；Electron 版可直接打开工作区。')}><Icon name="external" size={15} />在访达中打开</button>
          </div>
        </aside>

        <main className="dm-main">
          {showNewConversation ? <NewConversationPage onCancel={() => setShowNewConversation(false)} onCreateProject={async (name, folders) => { const project = await projects.create(name, folders); await createThreadForProject(project) }} /> : area === 'files' ? (
            selectedId && detailLoading ? <LoadingWorkspace /> : selectedId && detail ? <DocumentViewer doc={detail} onChat={() => openAgent(`${detail.filename} Agent`, true)} onMore={() => notify(detail.saved_path)} /> : <FileEmptyState count={count} error={detailError} />
          ) : (
            <WorkspaceView documentsCount={count} workspacePath={activeProject?.primary_path || workspace.info.path} projectId={activeProject?.id} agentName={agentName} newSessionRequest={newSessionRequest} requestedThreadId={requestedThreadId} trustAgent={settings.settings.trust_agent} provider={settings.settings.provider} modelName={settings.settings.model_name} models={settings.models} settingsLoading={settings.loading} onSettingsChange={(patch) => void settings.update(patch)} onJumpToDoc={handleJumpToDoc} />
          )}
        </main>
      </div>

      {showSearch && <div className="dm-search-overlay"><button className="dm-scrim" aria-label="关闭搜索" onClick={() => setShowSearch(false)} /><section className="dm-search-sheet"><div className="dm-sheet-title"><div><Icon name="search" size={19} />搜索资料</div><button className="dm-icon-button" onClick={() => setShowSearch(false)}><Icon name="close" /></button></div><SearchPanel onJumpToDoc={handleJumpToDoc} /></section></div>}
      {showApiKeyDialog && <ApiKeyDialog value={apiKeyInput} provider={apiProvider} error={apiKeyError} saving={apiKeySaving} onChange={setApiKeyInput} onCancel={() => setShowApiKeyDialog(false)} onSave={() => void saveApiKey()} />}
      {showProfile && <ProfileDrawer name={displayName} account={user?.email || user?.username || ''} localMode={localMode} apiKeys={apiKeyStatuses} stats={stats.stats} onClose={() => setShowProfile(false)} onLogout={logout} onNotice={notify} onConfigureApiKey={(provider) => openApiKeyDialog(provider)} onDeleteApiKey={async (provider) => {
        if (!accessToken || !window.confirm(`删除已保存的 ${provider === 'deepseek' ? 'DeepSeek' : 'SiliconFlow'} API Key？`)) return
        try { await AuthAPI.deleteApiKey(provider, accessToken); setApiKeyStatuses((items) => items.map((item) => item.provider === provider ? { ...item, configured: false, last4: null } : item)); notify('API Key 已删除') } catch (error) { notify(error instanceof Error ? error.message : 'API Key 删除失败') }
      }} />}
    </div>
  )
}

function FileEmptyState({ count, error }: { count: number; error: string | null }) {
  return <section className="dm-empty-state"><div className="dm-empty-mark"><Icon name="folder" size={35} /></div><h1>{error ? '无法预览此文件' : count ? '选择一份资料继续阅读' : '浏览你的工作区文件'}</h1><p>{error || (count ? `当前项目有 ${count.toLocaleString()} 份可解析资料，展开左侧目录选择原文件。` : '将资料保存到当前项目文件夹，文件区会自动更新。')}</p><div className="dm-empty-note">直接使用本地原文件 · 支持 PDF / DOCX / XLSX / TXT / Markdown</div></section>
}

function WorkspaceView({ documentsCount, workspacePath, projectId, agentName, newSessionRequest, requestedThreadId, trustAgent, provider, modelName, models, settingsLoading, onSettingsChange, onJumpToDoc }: { documentsCount: number; workspacePath: string; projectId?: string; agentName: string; newSessionRequest: number; requestedThreadId: string | null; trustAgent: boolean; provider: 'siliconflow' | 'deepseek'; modelName: string; models: Array<{ provider: 'siliconflow' | 'deepseek'; model_name: string; display_name: string }>; settingsLoading: boolean; onSettingsChange: (patch: { trust_agent?: boolean; provider?: 'siliconflow' | 'deepseek'; model_name?: string }) => void; onJumpToDoc: (id: string) => void }) {
  return <section className="dm-workspace-view"><header className="dm-workspace-header"><div className="dm-session-title"><span>{agentName}</span><span className="dm-session-chevron">⌄</span></div><div className="dm-session-context"><Icon name="file" size={14} />对话 · 关联当前项目</div><div className="dm-workspace-meta"><span><Icon name="folder" size={15} />{documentsCount} 份资料</span><span><i className="dm-status online" />已就绪</span></div></header><div className="dm-chat-surface"><ChatPanel workspacePath={workspacePath} projectId={projectId} onJumpToDoc={onJumpToDoc} newSessionRequest={newSessionRequest} requestedThreadId={requestedThreadId} trustAgent={trustAgent} provider={provider} modelName={modelName} models={models} settingsLoading={settingsLoading} onSettingsChange={onSettingsChange} /></div></section>
}

function DocumentViewer({ doc, onChat, onMore }: { doc: FilePreview; onChat: () => void; onMore: () => void }) {
  const date = new Date(doc.uploaded_at).toLocaleDateString('zh-CN')
  return <section className="dm-document-viewer"><header className="dm-document-header"><div className="dm-document-title"><div className="dm-file-icon"><Icon name="file" size={26} /></div><div><p className="dm-eyebrow">文件区 / 原文件</p><h1>{doc.filename}</h1><p>{doc.char_count.toLocaleString()} 字 · {(doc.size_bytes / 1024).toFixed(1)} KB · {date}</p></div></div><div className="dm-document-actions"><button onClick={onChat}><Icon name="message" size={16} />进入工作区</button><button onClick={onMore} title="更多操作"><Icon name="more" /></button></div></header><div className="dm-document-body"><p className="dm-empty-note">{doc.saved_path}{doc.truncated ? ' · 预览仅显示前 20 万字，索引不受此限制' : ''}</p>{doc.text ? <pre>{doc.text}</pre> : <div className="dm-no-text"><Icon name="file" size={28} /><h2>暂时没有可预览的文本</h2><p>该文件可能是扫描件，后续可在工作区让 Agent 协助识别与整理。</p><button onClick={onChat}>进入工作区</button></div>}</div></section>
}

function ProfileDrawer({ name, account, localMode, apiKeys, stats, onClose, onLogout, onNotice, onConfigureApiKey, onDeleteApiKey }: { name: string; account: string; localMode: boolean; apiKeys: ApiKeyStatus[]; stats: { document_count: number; thread_count: number; total_tokens: number }; onClose: () => void; onLogout: () => Promise<void>; onNotice: (message: string) => void; onConfigureApiKey: (provider: 'siliconflow' | 'deepseek') => void; onDeleteApiKey: (provider: 'siliconflow' | 'deepseek') => Promise<void> }) {
  const initials = name.slice(0, 1).toUpperCase()
  const keyStatus = (provider: 'siliconflow' | 'deepseek') => apiKeys.find((item) => item.provider === provider) || { provider, configured: false, last4: null }
  return <div className="dm-profile-overlay"><button className="dm-profile-scrim" aria-label="关闭个人中心" onClick={onClose} /><aside className="dm-profile-drawer"><div className="dm-profile-hero"><header><button className="dm-icon-button" onClick={onClose}><Icon name="close" /></button></header><section className="dm-user-card"><div className="dm-user-avatar">{initials}</div><div><h2>{name}</h2><p>{account}</p><span>{localMode ? 'DocuMate 本地模式' : 'DocuMate 成员'}</span></div></section><section className="dm-profile-stats"><div><strong>{stats.document_count}</strong><span>文档</span></div><div><strong>{stats.thread_count}</strong><span>对话</span></div><div><strong>{stats.total_tokens.toLocaleString()}</strong><span>tokens</span></div></section></div><div className="dm-profile-scroll">{!localMode && <section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="settings" size={17} />账号</span></div><button className="dm-profile-row" onClick={() => onNotice('账号和密码编辑将跟随账户管理模块开放。')}>修改账号 <span>›</span></button><button className="dm-profile-row" onClick={() => onNotice('账号和密码编辑将跟随账户管理模块开放。')}>修改密码 <span>›</span></button></section>}<section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="database" size={17} />API Key</span><em>本机保存</em></div><p className="dm-profile-copy">分别配置模型供应商；密钥仅保存到本机应用数据目录。</p><ApiKeyProviderRow label="SiliconFlow" status={keyStatus('siliconflow')} onConfigure={() => onConfigureApiKey('siliconflow')} onDelete={() => void onDeleteApiKey('siliconflow')} /><ApiKeyProviderRow label="DeepSeek" status={keyStatus('deepseek')} onConfigure={() => onConfigureApiKey('deepseek')} onDelete={() => void onDeleteApiKey('deepseek')} /></section><section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="database" size={17} />关于</span></div><div className="dm-profile-row is-static">版本 <span>v{window.documate?.version || '开发版'}</span></div><button className="dm-profile-row" onClick={() => onNotice('开发者文档会随首个公开版本一起提供。')}>开发者文档 <span>↗</span></button></section></div>{!localMode && <footer><button className="dm-logout" onClick={onLogout}><Icon name="logout" size={17} />退出登录</button></footer>}</aside></div>
}

function ApiKeyProviderRow({ label, status, onConfigure, onDelete }: { label: string; status: ApiKeyStatus; onConfigure: () => void; onDelete: () => void }) {
  return <div className="dm-api-provider-row"><div><strong>{label}</strong><span className={status.configured ? 'is-ready' : ''}>{status.configured ? `已配置 · ••••${status.last4}` : '未配置'}</span></div><div><button className="dm-outline-button" onClick={onConfigure}>{status.configured ? '更换' : '填写'}</button>{status.configured && <button className="dm-danger-button" onClick={onDelete}>删除</button>}</div></div>
}

function ApiKeyDialog({ value, provider, error, saving, onChange, onCancel, onSave }: { value: string; provider: 'siliconflow' | 'deepseek'; error: string | null; saving: boolean; onChange: (value: string) => void; onCancel: () => void; onSave: () => void }) {
  const label = provider === 'deepseek' ? 'DeepSeek' : 'SiliconFlow'
  return <div className="dm-dialog-overlay"><button className="dm-dialog-scrim" aria-label="关闭 API Key 配置" onClick={onCancel} /><form className="dm-dialog" onSubmit={(event) => { event.preventDefault(); onSave() }}><h2>配置 {label}</h2><p>填写后会先验证，再保存到本机 DocuMate 配置。</p><label className="dm-api-key-input">{label} API Key<input autoFocus type="password" autoComplete="off" value={value} onChange={(event) => onChange(event.target.value)} placeholder="sk-..." /></label>{provider === 'deepseek' && <p className="dm-provider-note">用于 DeepSeek V4.1 Flash 和 DeepSeek V4 Pro。</p>}{provider === 'siliconflow' && <p className="dm-provider-note">用于 Qwen 3.5 4B 和图片识别；资料向量检索使用本地模型。</p>}{error && <p className="dm-dialog-error">{error}</p>}<div><button type="button" className="dm-outline-button" onClick={onCancel} disabled={saving}>取消</button><button type="submit" className="dm-dialog-primary" disabled={!value.trim() || saving}>{saving ? '验证并保存中…' : '验证并保存'}</button></div></form></div>
}

function LoadingWorkspace() { return <div className="dm-loading"><BrandMark size={50} /><span>正在准备你的工作区…</span></div> }

export default function AppWithAuth() {
  return (
    <AuthProvider>
      <div className="dm-global-window-drag" aria-hidden="true" />
      <AuthGuard><App /></AuthGuard>
    </AuthProvider>
  )
}
