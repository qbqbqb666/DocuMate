import { useEffect, useRef, useState } from 'react'
import { useWorkspaceFiles, type FilePreview, type WorkspaceFile } from './hooks/useWorkspaceFiles'
import { useWorkspace } from './hooks/useWorkspace'
import { useSettings } from './hooks/useSettings'
import { useProjects } from './hooks/useProjects'
import { useStats } from './hooks/useStats'
import { AddDocumentsDialog } from './components/AddDocumentsDialog'
import { DocumentSidebar } from './components/DocumentSidebar'
import { SearchPanel } from './components/SearchPanel'
import { ChatPanel } from './components/ChatPanel'
import { ProjectSidebar } from './components/ProjectSidebar'
import { NewConversationPage } from './components/NewConversationPage'
import { BrandMark } from './components/BrandMark'
import { BrandWordmark } from './components/BrandWordmark'
import { ThemePicker } from './components/ThemePicker'
import { Icon } from './components/Icon'
import { AuthProvider, useAuth } from './auth/useAuth'
import { AuthGuard } from './auth/AuthGuard'
import { AuthAPI, type ApiKeyStatus } from './auth/AuthClient'
import { ApiError, apiRequest } from './api/client'
import type { ProjectSummary } from './api/types'

type AppArea = 'files' | 'workspace'
type RemovalRequest = {
  title: string
  description: string
  items: Array<{ name: string; path?: string }>
  run: () => Promise<void>
  resolve: (confirmed: boolean) => void
}

function App() {
  const workspace = useWorkspace()
  const { roots, count, loading, error, index, indexError, refreshing, refreshAll, refreshIndexStatus, fetchDetail, refresh: refreshDocs, remove: removeDocument } = useWorkspaceFiles(workspace.info?.path)
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
  const [showAddDocuments, setShowAddDocuments] = useState(false)
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
  const [agentName, setAgentName] = useState('新对话')
  const newSessionRequest = 0
  const [requestedThreadId, setRequestedThreadId] = useState<string | null>(null)
  const [showNewConversation, setShowNewConversation] = useState(false)
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [documentHandoff, setDocumentHandoff] = useState<{ threadId: string; file: WorkspaceFile } | null>(null)
  const [enteringDocument, setEnteringDocument] = useState(false)
  const [removal, setRemoval] = useState<RemovalRequest | null>(null)
  const [removalBusy, setRemovalBusy] = useState(false)
  const [removalError, setRemovalError] = useState<string | null>(null)
  const removalRef = useRef<RemovalRequest | null>(null)
  const removalRunning = useRef(false)

  useEffect(() => () => { removalRef.current?.resolve(false) }, [])
  const requestRemoval = (options: Omit<RemovalRequest, 'resolve'>) => {
    if (removalRef.current) return Promise.resolve(false)
    return new Promise<boolean>(resolve => {
      const request = { ...options, resolve }
      removalRef.current = request
      setRemovalError(null)
      setRemoval(request)
    })
  }
  const dismissRemoval = (confirmed = false) => {
    const request = removalRef.current
    removalRef.current = null
    setRemoval(null)
    request?.resolve(confirmed)
  }
  const confirmRemoval = async () => {
    const request = removalRef.current
    if (!request || removalRunning.current) return
    removalRunning.current = true
    setRemovalBusy(true); setRemovalError(null)
    try { await request.run(); dismissRemoval(true) }
    catch (reason) {
      setRemovalError(reason instanceof ApiError && reason.status === 404
        ? '当前后台未提供移除接口。请完整退出并重新启动 DocuMate 后重试；本次未移除资料。'
        : reason instanceof Error ? reason.message : String(reason))
    } finally { removalRunning.current = false; setRemovalBusy(false) }
  }

  useEffect(() => {
    refreshDocs()
    setSelectedId(null)
    setShowAddDocuments(false)
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
    const refreshPreview = () => { void load() }
    window.addEventListener('documate:files-refreshed', refreshPreview)
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener('documate:files-refreshed', refreshPreview) }
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

  const removeFile = async (path: string, name: string) => {
    await requestRemoval({ title: '移除此资料？', description: '从当前项目移除并清理不再使用的索引，本地原文件保留。', items: [{ name, path }], run: async () => {
      await removeDocument(path, activeProjectId || undefined)
      const normalized = selectedId?.replaceAll('\\', '/')
      const target = path.replaceAll('\\', '/').replace(/\/$/, '')
      if (normalized === target || normalized?.startsWith(`${target}/`)) setSelectedId(null)
      notify('资料已从当前项目移除')
    } })
  }

  const removeFiles = (paths: string[]) => {
    if (!paths.length) return Promise.resolve(false)
    return requestRemoval({ title: `移除选中的 ${paths.length} 项资料？`, description: '包含所选文件夹中的资料；本地原文件保留。', items: paths.map(path => ({ name: path.replaceAll('\\', '/').split('/').at(-1) || path, path })), run: async () => {
      await removeDocument(paths, activeProjectId || undefined)
      if (selectedId && paths.some(path => selectedId === path || selectedId.replaceAll('\\', '/').startsWith(`${path.replaceAll('\\', '/').replace(/\/$/, '')}/`))) setSelectedId(null)
      notify(`已移除 ${paths.length} 项资料`)
    } })
  }

  const removeProject = async (project: ProjectSummary) => {
    await requestRemoval({ title: '移除此项目？', description: '仅从 DocuMate 移除，保留本地原文件和已有对话。', items: [{ name: project.name, path: project.primary_path }], run: async () => {
      const remaining = await projects.remove(project.id)
      if (activeProjectId === project.id) {
        const next = remaining.find(item => item.is_active) || remaining[0]
        setActiveProjectId(next?.id || null)
        setRequestedThreadId(null)
        setDocumentHandoff(null)
        setAgentName('新对话')
        setSelectedId(null)
        setShowNewConversation(true)
        await workspace.refresh()
        await refreshDocs()
      }
      notify('项目已移除，原文件和对话保留')
    } })
  }

  const openThread = async (project: ProjectSummary, threadId: string, title: string) => {
    await projects.activate(project.id)
    if (workspace.info?.path !== project.primary_path && !await workspace.switchTo(project.primary_path)) throw new Error('无法切换到该项目文件夹')
    setActiveProjectId(project.id)
    setAgentName(title || '新对话')
    setRequestedThreadId(threadId)
    setArea('workspace')
    setShowNewConversation(false)
  }

  const createThreadForProject = async (project: ProjectSummary) => {
    await projects.activate(project.id)
    if (workspace.info?.path !== project.primary_path && !await workspace.switchTo(project.primary_path)) throw new Error('无法切换到该项目文件夹')
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
    return result.thread_id
  }

  const enterDocumentWorkspace = async (doc: FilePreview) => {
    if (enteringDocument) return
    setEnteringDocument(true)
    try {
      const result = await apiRequest<{ project: ProjectSummary; file: WorkspaceFile; index: { status: string; error: string | null } }>('/api/workspace-files/enter-workspace', { method: 'POST', body: JSON.stringify({ paths: [doc.saved_path] }) })
      const threadId = await createThreadForProject(result.project)
      setDocumentHandoff({ threadId, file: result.file })
      notify(result.index.status === 'ready' ? '已进入对应项目并引用此文件' : result.index.status === 'error' ? `已引用文件；索引失败：${result.index.error || '请稍后重试'}` : '已引用文件，正在建立本地索引')
    } catch (reason) { notify(reason instanceof Error ? reason.message : String(reason)) }
    finally { setEnteringDocument(false) }
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

  const activeProject = projects.projects.find((project) => project.id === activeProjectId) || projects.projects.find((project) => project.is_active) || projects.projects[0]
  const displayName = user?.display_name || user?.username || '用户'

  return (
    <div className={`dm-app${window.documate?.platform === 'darwin' ? ' is-macos' : ''}`}>
      <div className="dm-window-drag" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties} />
      {toast && <div className="dm-toast"><Icon name="check" size={16} />{toast}</div>}

      <header className="dm-topbar" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
        <div className="dm-brand">
          <BrandMark size={32} />
          <BrandWordmark />
        </div>
        {(area === 'workspace' || showNewConversation) && <div className="dm-task-heading"><Icon name="folder" size={18} /><span title={showNewConversation ? '新对话' : agentName}>{showNewConversation ? '新对话' : agentName}</span></div>}
        {area === 'files' && !showNewConversation && selectedId && detail?.id === selectedId && <div className="dm-task-heading"><Icon name="file" size={18} /><span title={detail.filename}>{detail.filename}</span></div>}
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
            <button className={area === 'files' ? 'is-active' : ''} aria-current={area === 'files' ? 'page' : undefined} onClick={() => setArea('files')}><Icon name="folder" size={17} />文件区</button>
            <button className={area === 'workspace' ? 'is-active' : ''} aria-current={area === 'workspace' ? 'page' : undefined} onClick={() => setArea('workspace')}><Icon name="message" size={17} />工作区</button>
          </nav>

          <div className="dm-sidebar-content">
            {area === 'files' ? (
              <DocumentSidebar key={activeProject?.id || workspace.info.path} onRemoveMany={removeFiles} roots={roots} selectedId={selectedId} onSelect={setSelectedId} loading={loading} refreshing={refreshing} index={index} indexError={indexError} projectName={activeProject?.name} onRemove={(path, name) => void removeFile(path, name)} onAdd={() => setShowAddDocuments(true)} onRefresh={() => { void refreshAll().catch(reason => notify(reason instanceof Error ? reason.message : String(reason))) }} />
            ) : (
              <ProjectSidebar onDeleteProject={project => void removeProject(project)} projects={projects.projects} activeThreadId={requestedThreadId} resetKey={showNewConversation ? 'new-conversation' : requestedThreadId || 'none'} onOpenThread={(project, threadId, title) => void openThread(project, threadId, title)} onNewThread={(project) => void createThreadForProject(project)} onDeleteThread={(threadId) => { if (threadId === requestedThreadId) { setRequestedThreadId(null); setAgentName('新对话') } }} />
            )}
          </div>

          <div className="dm-sidebar-footer">
            {error && <div className="dm-inline-error">{error}</div>}
            <button className="dm-quiet-button dm-open-folder-button" onClick={() => window.documate?.openFolder ? workspace.openInFinder() : notify('浏览器预览模式不支持打开访达；Electron 版可直接打开工作区。')}><Icon name="external" size={15} />在访达中打开</button>
          </div>
        </aside>

        <main className="dm-main">
          {showNewConversation ? <NewConversationPage projects={projects.projects} projectsLoading={projects.loading} projectsError={projects.error} onUseProject={async project => { await createThreadForProject(project) }} onCancel={() => setShowNewConversation(false)} onCreateProject={async (name, folders) => { const project = await projects.create(name, folders); await createThreadForProject(project) }} /> : area === 'files' ? (
            selectedId && detailLoading ? <LoadingWorkspace /> : selectedId && detail ? <DocumentViewer doc={detail} opening={enteringDocument} onChat={() => void enterDocumentWorkspace(detail)} /> : <FileEmptyState count={count} error={detailError} />
          ) : (
            <WorkspaceView onReferenceApplied={() => setDocumentHandoff(null)} initialReference={documentHandoff?.threadId === requestedThreadId ? documentHandoff.file : undefined} workspacePath={activeProject?.primary_path || workspace.info.path} projectId={activeProject?.id} onTitleChange={setAgentName} newSessionRequest={newSessionRequest} requestedThreadId={requestedThreadId} trustAgent={settings.settings.trust_agent} provider={settings.settings.provider} modelName={settings.settings.model_name} models={settings.models} settingsLoading={settings.loading} onSettingsChange={(patch) => void settings.update(patch)} onJumpToDoc={handleJumpToDoc} />
          )}
        </main>
      </div>

      {removal && <RemovalDialog request={removal} busy={removalBusy} error={removalError} onCancel={() => dismissRemoval(false)} onConfirm={() => void confirmRemoval()} />}
      {showAddDocuments && workspace.info && <AddDocumentsDialog key={workspace.info.path} workspacePath={workspace.info.path} projectId={activeProjectId || undefined} onClose={() => setShowAddDocuments(false)} onAdded={() => { setShowAddDocuments(false); void refreshDocs(); void refreshIndexStatus(); window.dispatchEvent(new Event('documate:files-refreshed')); notify('资料已加入，正在建立本地索引') }} />}
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

function RemovalDialog({ request, busy, error, onCancel, onConfirm }: { request: RemovalRequest; busy: boolean; error: string | null; onCancel: () => void; onConfirm: () => void }) {
  const cancelButton = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLElement>(null)
  useEffect(() => { if (busy) dialog.current?.focus(); else cancelButton.current?.focus() }, [busy])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    cancelButton.current?.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [])
  return <div className="dm-dialog-overlay dm-removal-overlay"><button className="dm-dialog-scrim" disabled={busy} aria-label="取消移除" onClick={onCancel} />
    <section ref={dialog} tabIndex={-1} className="dm-removal-dialog" role="alertdialog" aria-modal="true" aria-labelledby="removal-title" aria-describedby="removal-description" aria-busy={busy} onKeyDown={event => {
      if (event.key === 'Escape' && !busy) { event.preventDefault(); onCancel() }
      if (event.key === 'Tab') {
        if (busy) { event.preventDefault(); return }
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
        const first = buttons[0], last = buttons.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}>
      <div className="dm-removal-heading"><span className="dm-removal-mark"><Icon name="folder" size={23} /></span><div><h2 id="removal-title">{request.title}</h2><p id="removal-description">{request.description}</p></div></div>
      <ul className="dm-removal-items">{request.items.map((item, index) => <li key={`${item.path || item.name}:${index}`}><Icon name="file" size={17} /><span><b>{item.name}</b>{item.path && <small title={item.path}>{item.path}</small>}</span></li>)}</ul>
      {error && <p role="alert" className="dm-inline-error">{error}</p>}
      {busy && <p className="dm-removal-progress" role="status"><svg className="dm-index-spinner" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="8" opacity=".2" /><path d="M12 4a8 8 0 0 1 8 8" /></svg>正在移除并清理索引…</p>}
      <footer><button ref={cancelButton} type="button" className="dm-outline-button" disabled={busy} onClick={onCancel}>取消</button><button type="button" className="dm-dialog-primary" disabled={busy} onClick={onConfirm}>{busy ? '正在移除…' : error ? '重试移除' : '确认移除'}</button></footer>
    </section>
  </div>
}

function WorkspaceView({ initialReference, onReferenceApplied, workspacePath, projectId, onTitleChange, newSessionRequest, requestedThreadId, trustAgent, provider, modelName, models, settingsLoading, onSettingsChange, onJumpToDoc }: { initialReference?: WorkspaceFile; onReferenceApplied: () => void; workspacePath: string; projectId?: string; onTitleChange: (title: string) => void; newSessionRequest: number; requestedThreadId: string | null; trustAgent: boolean; provider: 'siliconflow' | 'deepseek'; modelName: string; models: Array<{ provider: 'siliconflow' | 'deepseek'; model_name: string; display_name: string }>; settingsLoading: boolean; onSettingsChange: (patch: { trust_agent?: boolean; provider?: 'siliconflow' | 'deepseek'; model_name?: string }) => void; onJumpToDoc: (id: string) => void }) {
  return <section className="dm-workspace-view"><div className="dm-chat-surface"><ChatPanel onReferenceApplied={onReferenceApplied} initialReference={initialReference} workspacePath={workspacePath} projectId={projectId} onTitleChange={onTitleChange} onJumpToDoc={onJumpToDoc} newSessionRequest={newSessionRequest} requestedThreadId={requestedThreadId} trustAgent={trustAgent} provider={provider} modelName={modelName} models={models} settingsLoading={settingsLoading} onSettingsChange={onSettingsChange} /></div></section>
}

function DocumentViewer({ doc, onChat, opening }: { doc: FilePreview; onChat: () => void; opening: boolean }) {
  const date = new Date(doc.uploaded_at).toLocaleDateString('zh-CN')
  return <section className="dm-document-viewer"><header className="dm-document-header"><div className="dm-document-title"><div className="dm-file-icon" data-file-type={doc.filename.split('.').at(-1)?.toLowerCase()}><Icon name="file" size={26} /></div><div className="dm-document-title-copy"><h1 title={doc.filename}>{doc.filename}</h1><p>{doc.char_count.toLocaleString()} 字 · {(doc.size_bytes / 1024).toFixed(1)} KB · {date}</p></div></div><div className="dm-document-actions"><button disabled={opening} onClick={onChat}><Icon name="message" size={16} />进入工作区</button></div></header><div className="dm-document-path"><Icon name="folder" size={15} /><span title={doc.saved_path}>{doc.saved_path}</span></div><div className="dm-document-body">{doc.truncated && <p className="dm-preview-note">预览仅显示前 20 万字，索引不受此限制</p>}{doc.text ? <pre>{doc.text}</pre> : <div className="dm-no-text"><Icon name="file" size={28} /><h2>暂时没有可预览的文本</h2><p>该文件可能是扫描件，后续可在工作区让 Agent 协助识别与整理。</p><button disabled={opening} onClick={onChat}>进入工作区</button></div>}</div></section>
}

function ProfileDrawer({ name, account, localMode, apiKeys, stats, onClose, onLogout, onNotice, onConfigureApiKey, onDeleteApiKey }: { name: string; account: string; localMode: boolean; apiKeys: ApiKeyStatus[]; stats: { document_count: number; thread_count: number; total_tokens: number }; onClose: () => void; onLogout: () => Promise<void>; onNotice: (message: string) => void; onConfigureApiKey: (provider: 'siliconflow' | 'deepseek') => void; onDeleteApiKey: (provider: 'siliconflow' | 'deepseek') => Promise<void> }) {
  const initials = name.slice(0, 1).toUpperCase()
  const keyStatus = (provider: 'siliconflow' | 'deepseek') => apiKeys.find((item) => item.provider === provider) || { provider, configured: false, last4: null }
  return <div className="dm-profile-overlay"><button className="dm-profile-scrim" aria-label="关闭个人中心" onClick={onClose} /><aside className="dm-profile-drawer"><div className="dm-profile-hero"><header><button className="dm-icon-button" onClick={onClose} aria-label="关闭个人中心"><Icon name="close" /></button></header><section className="dm-user-card"><div className="dm-user-avatar">{initials}</div><div><h2>{name}</h2><p>{account}</p><span>{localMode ? 'DocuMate 本地模式' : 'DocuMate 成员'}</span></div></section><section className="dm-profile-stats"><div><strong>{stats.document_count}</strong><span>文档</span></div><div><strong>{stats.thread_count}</strong><span>对话</span></div><div><strong>{stats.total_tokens.toLocaleString()}</strong><span>tokens</span></div></section></div><div className="dm-profile-scroll"><ThemePicker />{!localMode && <section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="settings" size={17} />账号</span></div><button className="dm-profile-row" onClick={() => onNotice('账号和密码编辑将跟随账户管理模块开放。')}>修改账号 <span>›</span></button><button className="dm-profile-row" onClick={() => onNotice('账号和密码编辑将跟随账户管理模块开放。')}>修改密码 <span>›</span></button></section>}<section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="database" size={17} />API Key</span><em>本机保存</em></div><p className="dm-profile-copy">分别配置模型供应商；密钥仅保存到本机应用数据目录。</p><ApiKeyProviderRow label="SiliconFlow" status={keyStatus('siliconflow')} onConfigure={() => onConfigureApiKey('siliconflow')} onDelete={() => void onDeleteApiKey('siliconflow')} /><ApiKeyProviderRow label="DeepSeek" status={keyStatus('deepseek')} onConfigure={() => onConfigureApiKey('deepseek')} onDelete={() => void onDeleteApiKey('deepseek')} /></section><section className="dm-profile-section"><div className="dm-profile-section-title"><span><Icon name="database" size={17} />关于</span></div><div className="dm-profile-row is-static">版本 <span>v{window.documate?.version || '开发版'}</span></div><button className="dm-profile-row" onClick={() => onNotice('开发者文档会随首个公开版本一起提供。')}>开发者文档 <span>↗</span></button></section></div>{!localMode && <footer><button className="dm-logout" onClick={onLogout}><Icon name="logout" size={17} />退出登录</button></footer>}</aside></div>
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
