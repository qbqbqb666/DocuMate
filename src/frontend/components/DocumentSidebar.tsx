import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import type { WorkspaceFile, FileIndexStatus, IndexSummary } from '../hooks/useWorkspaceFiles'
import { Icon } from './Icon'

interface Props {
  roots: WorkspaceFile[]
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
  refreshing: boolean
  index: IndexSummary | null
  indexError: string | null
  onAdd: () => void
  onRefresh: () => void
}

function Folder({ folder, depth, selectedId, onSelect, statuses }: { folder: WorkspaceFile; depth: number; selectedId: string | null; onSelect: (id: string) => void; statuses: Map<string, FileIndexStatus> }) {
  const [expanded, setExpanded] = useState(depth === 0)
  const [entries, setEntries] = useState<WorkspaceFile[]>([])
  const [limit, setLimit] = useState(100)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!expanded) return
    let cancelled = false
    let busy = false
    const load = async () => {
      if (busy) return
      busy = true
      try {
        const result = await apiRequest<{ entries: WorkspaceFile[]; total: number }>(`/api/workspace-files/children?path=${encodeURIComponent(folder.id)}&limit=${Math.min(200, limit)}&offset=0`)
        let items = result.entries
        for (let offset = 200; offset < Math.min(limit, result.total); offset += 200) {
          if (cancelled) return
          const page = await apiRequest<{ entries: WorkspaceFile[] }>(`/api/workspace-files/children?path=${encodeURIComponent(folder.id)}&limit=${Math.min(200, limit - offset)}&offset=${offset}`)
          items = [...items, ...page.entries]
        }
        if (!cancelled) { setEntries(items.slice(0, limit)); setTotal(result.total); setError(null) }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason))
      } finally {
        busy = false
        if (!cancelled) setLoading(false)
      }
    }
    setLoading(true)
    void load()
    const refresh = () => { void load() }
    window.addEventListener('documate:files-refreshed', refresh)
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener('documate:files-refreshed', refresh) }
  }, [expanded, folder.id, limit])

  return <div>
    <button className="dm-folder-row dm-directory-row" style={{ paddingLeft: 8 + Math.min(depth, 8) * 14 }} onClick={() => setExpanded(!expanded)} aria-expanded={expanded} title={folder.saved_path}>
      <span className={`dm-directory-caret${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={12} /></span><Icon name="folder" size={16} /><span className="dm-directory-name">{folder.filename}</span>
    </button>
    {expanded && <div>
      {error && <div className="dm-inline-error">{error}</div>}
      {loading && entries.length === 0 && <div className="dm-doc-empty">正在读取…</div>}
      {!loading && !error && total === 0 && <div className="dm-doc-empty">文件夹为空</div>}
      {entries.map(item => item.kind === 'directory'
        ? <Folder key={item.id} folder={item} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} statuses={statuses} />
        : <FileRow key={item.id} file={item} depth={depth} selectedId={selectedId} onSelect={onSelect} status={statuses.get(item.id)} />)}
      {entries.length < total && <button className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>加载更多（已显示 {entries.length} / {total}）</button>}
    </div>}
  </div>
}

function FileRow({ file, depth, selectedId, onSelect, status }: { file: WorkspaceFile; depth: number; selectedId: string | null; onSelect: (id: string) => void; status?: FileIndexStatus }) {
  const labels = { ready: '已索引', pending: '待索引', indexing: '索引中', error: '索引失败', missing: '原文件已移除' }
  return <button className={`dm-document-row ${selectedId === file.id ? 'is-selected' : ''}`} disabled={file.missing} style={{ paddingLeft: depth < 0 ? 8 : 28 + Math.min(depth, 8) * 14 }} aria-current={selectedId === file.id ? 'true' : undefined} onClick={() => onSelect(file.id)} title={status?.error ? `${file.saved_path}\n${status.error}` : file.saved_path}>
    <span className="file-type" data-file-type={file.filename.split('.').at(-1)?.toLowerCase()}><Icon name="file" size={18} /></span><span className="min-w-0 flex-1"><span className="filename">{file.filename}</span><span className={`metadata dm-file-index-state ${status?.status || ''}`}>{(file.size_bytes / 1024).toFixed(1)} KB · {file.missing ? '原文件已移除' : !file.previewable ? '暂不支持预览' : status ? labels[status.status] : '待索引'}</span></span>
  </button>
}

export function DocumentSidebar({ roots, selectedId, onSelect, loading, refreshing, index, indexError, onAdd, onRefresh }: Props) {
  const [rootLimit, setRootLimit] = useState(100)
  useEffect(() => { setRootLimit(100) }, [roots[0]?.id])
  const statuses = new Map(index?.files.map(file => [file.path, file]) || [])
  const indexMessage = index?.worker_error || indexError
  return <div className="dm-doc-sidebar">
    <div className="dm-file-toolbar"><button type="button" onClick={onAdd} title="添加资料" aria-label="添加资料"><Icon name="plus" size={18} /></button><button type="button" disabled={refreshing} onClick={onRefresh} title="刷新文件与索引状态" aria-label="刷新文件"><svg className={refreshing ? 'is-refreshing' : ''} width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1" /></svg></button></div>
    {indexMessage && <p className="dm-inline-error" role="alert">索引暂不可用：{indexMessage}</p>}
    <div className="dm-document-list">
      {loading && <div className="dm-doc-empty">正在读取文件区…</div>}
      {roots.slice(0, rootLimit).map(root => root.kind === 'file' ? <FileRow key={root.id} file={root} depth={-1} selectedId={selectedId} onSelect={onSelect} status={statuses.get(root.id)} /> : root.missing ? <div key={root.id} className="dm-doc-empty" title={root.saved_path}>{root.filename} · 原文件夹已移除</div> : <Folder key={root.id} folder={root} depth={0} selectedId={selectedId} onSelect={onSelect} statuses={statuses} />)}
      {rootLimit < roots.length && <button type="button" className="dm-quiet-button" onClick={() => setRootLimit(value => value + 100)}>加载更多（已显示 {rootLimit} / {roots.length}）</button>}
    </div>
  </div>
}
