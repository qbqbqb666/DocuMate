import { createContext, useContext, useEffect, useRef, useState } from 'react'
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
  onRemove: (path: string, name: string) => void
  projectName?: string
  onRemoveMany: (paths: string[]) => Promise<boolean>
}

const BatchContext = createContext<{ active: boolean; selected: Set<string>; toggle: (path: string) => void; busy: boolean }>({ active: false, selected: new Set(), toggle: () => {}, busy: false })
const normalizedPath = (path: string) => path.replaceAll('\\', '/').replace(/\/$/, '')
const within = (path: string, parent: string) => normalizedPath(path).startsWith(`${normalizedPath(parent)}/`)

function SelectionBox({ path, name }: { path: string; name: string }) {
  const batch = useContext(BatchContext)
  if (!batch.active) return null
  const inherited = [...batch.selected].some(parent => within(path, parent))
  return <input className="dm-tree-select" type="checkbox" aria-label={`选择 ${name}`} checked={inherited || batch.selected.has(path)} disabled={batch.busy || inherited} onChange={() => batch.toggle(path)} />
}

function Folder({ folder, depth, selectedId, onSelect, statuses, onRemove }: { folder: WorkspaceFile; depth: number; selectedId: string | null; onSelect: (id: string) => void; statuses: Map<string, FileIndexStatus>; onRemove: Props['onRemove'] }) {
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
    <div className="dm-tree-item"><SelectionBox path={folder.saved_path} name={folder.filename} /><button className="dm-folder-row dm-directory-row" style={{ paddingLeft: 8 + Math.min(depth, 8) * 14 }} onClick={() => setExpanded(!expanded)} aria-expanded={expanded} title={folder.saved_path}>
      <span className={`dm-directory-caret${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={12} /></span><Icon name="folder" size={16} /><span className="dm-directory-name">{folder.filename}</span>
    </button><DocumentMenu path={folder.saved_path} name={folder.filename} onRemove={onRemove} /></div>
    {expanded && <div>
      {error && <div className="dm-inline-error">{error}</div>}
      {loading && entries.length === 0 && <div className="dm-doc-empty">正在读取…</div>}
      {!loading && !error && total === 0 && <div className="dm-doc-empty">文件夹为空</div>}
      {entries.map(item => item.kind === 'directory'
        ? <Folder key={item.id} folder={item} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} statuses={statuses} onRemove={onRemove} />
        : <FileRow key={item.id} file={item} depth={depth} selectedId={selectedId} onSelect={onSelect} status={statuses.get(item.id)} onRemove={onRemove} />)}
      {entries.length < total && <button className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>加载更多（已显示 {entries.length} / {total}）</button>}
    </div>}
  </div>
}

function FileRow({ file, depth, selectedId, onSelect, status, onRemove }: { file: WorkspaceFile; depth: number; selectedId: string | null; onSelect: (id: string) => void; status?: FileIndexStatus; onRemove: Props['onRemove'] }) {
  const state = file.missing ? 'missing' : status?.status || 'pending'
  const label = { ready: '已索引', pending: '等待索引', indexing: '索引中', error: '索引失败', missing: '原文件已移除' }[state]
  const failed = state === 'error' || state === 'missing'
  const description = status?.error || (file.missing ? '原文件已移除或路径已改变' : !file.previewable ? '暂不支持此文件格式' : label)
  return <div className="dm-tree-item"><SelectionBox path={file.saved_path} name={file.filename} /><button className={`dm-document-row ${selectedId === file.id ? 'is-selected' : ''}`} disabled={file.missing} style={{ paddingLeft: depth < 0 ? 8 : 28 + Math.min(depth, 8) * 14 }} aria-current={selectedId === file.id ? 'true' : undefined} onClick={() => onSelect(file.id)} title={`${file.saved_path}\n${description}`}>
    <span className="file-type" data-file-type={file.filename.split('.').at(-1)?.toLowerCase()}><Icon name="file" size={18} /></span><span className="min-w-0 flex-1"><span className="filename">{file.filename}</span><span className="metadata">{(file.size_bytes / 1024).toFixed(1)} KB</span></span>
    {(file.previewable || file.missing) && <span className={`dm-index-icon ${state}`} role="img" aria-label={label} title={description}>{state === 'ready' ? <Icon name="check" size={15} /> : failed ? <Icon name="close" size={15} /> : <svg className="dm-index-spinner" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="8" opacity=".2" /><path d="M12 4a8 8 0 0 1 8 8" strokeLinecap="round" /></svg>}</span>}
  </button><DocumentMenu path={file.saved_path} name={file.filename} onRemove={onRemove} /></div>
}

export function DocumentSidebar({ roots, selectedId, onSelect, loading, refreshing, index, indexError, onAdd, onRefresh, onRemove, onRemoveMany, projectName }: Props) {
  const [rootLimit, setRootLimit] = useState(100)
  const [expanded, setExpanded] = useState(true)
  const [batch, setBatch] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [removing, setRemoving] = useState(false)
  useEffect(() => { setSelected(new Set()); setBatch(false); setExpanded(true) }, [projectName])
  const toggle = (path: string) => setSelected(current => {
    const next = new Set([...current].filter(item => !within(item, path)))
    if (next.has(path)) next.delete(path); else next.add(path)
    return next
  })
  const removeSelected = async () => {
    setRemoving(true)
    try { if (await onRemoveMany([...selected])) { setSelected(new Set()); setBatch(false) } }
    finally { setRemoving(false) }
  }
  useEffect(() => { setRootLimit(100) }, [roots[0]?.id])
  const statuses = new Map(index?.files.map(file => [file.path, file]) || [])
  const grouped = new Map<string, WorkspaceFile[]>()
  for (const root of roots.filter(root => root.kind === 'file')) {
    const parent = root.group_path || root.saved_path.replaceAll('\\', '/').replace(/\/[^/]+$/, '') || '/'
    grouped.set(parent, [...(grouped.get(parent) || []), root])
  }
  const treeRoots = [...roots.filter(root => root.kind === 'directory'), ...[...grouped].map(([path, files]) => ({ ...files[0], id: `group:${path}`, saved_path: path, filename: path.split('/').at(-1) || path, kind: 'directory' as const, members: files }))]
  const indexMessage = index?.worker_error || indexError
  return <BatchContext.Provider value={{ active: batch, selected, toggle, busy: removing }}><div className="dm-doc-sidebar">
    <div className="dm-file-toolbar"><button type="button" onClick={onAdd} title="添加资料" aria-label="添加资料"><Icon name="plus" size={18} /></button><button type="button" className="dm-file-batch-toggle" aria-pressed={batch} disabled={removing} onClick={() => { setBatch(value => !value); setSelected(new Set()) }}>{batch ? '完成' : '批量管理'}</button><button type="button" disabled={refreshing} onClick={onRefresh} title="刷新文件与索引状态" aria-label="刷新文件"><svg className={refreshing ? 'is-refreshing' : ''} width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1" /></svg></button></div>
    {batch && <div className="dm-file-batch-actions"><span>已选 {selected.size} 项</span><button type="button" disabled={removing || !treeRoots.length} onClick={() => setSelected(new Set(treeRoots.map(root => root.saved_path)))}>全选分组</button><button type="button" className="is-danger" disabled={removing || !selected.size} onClick={() => void removeSelected()}>{removing ? '移除中…' : '移除所选'}</button></div>}
    {indexMessage && <p className="dm-inline-error" role="alert">索引暂不可用：{indexMessage}</p>}
    <div className="dm-document-list">
      {loading && <div className="dm-doc-empty">正在读取文件区…</div>}
      {projectName && <button type="button" className="dm-file-project-heading" aria-expanded={expanded} title={projectName} onClick={() => setExpanded(value => !value)}><span className={`dm-directory-caret${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={12} /></span><Icon name="folder" size={17} /><b>{projectName}</b></button>}
      {expanded && <div className="dm-file-project-children">
      {treeRoots.slice(0, rootLimit).map(root => 'members' in root
        ? <FileGroup key={root.id} path={root.saved_path} name={root.filename} files={root.members as WorkspaceFile[]} selectedId={selectedId} onSelect={onSelect} statuses={statuses} onRemove={onRemove} />
        : root.missing ? <div key={root.id} className="dm-tree-item"><span className="dm-doc-empty" title={root.saved_path}>{root.filename} · 原文件夹已移除</span><DocumentMenu path={root.saved_path} name={root.filename} onRemove={onRemove} /></div>
        : <Folder key={root.id} folder={root} depth={0} selectedId={selectedId} onSelect={onSelect} statuses={statuses} onRemove={onRemove} />)}
      {rootLimit < treeRoots.length && <button type="button" className="dm-quiet-button" onClick={() => setRootLimit(value => value + 100)}>加载更多（已显示 {rootLimit} / {treeRoots.length}）</button>}</div>}
    </div>
  </div></BatchContext.Provider>
}

function DocumentMenu({ path, name, onRemove }: { path: string; name: string; onRemove: Props['onRemove'] }) {
  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  const batch = useContext(BatchContext)
  useEffect(() => {
    if (!open) return
    const outside = (event: MouseEvent) => { if (!menu.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  if (batch.active) return null
  return <div ref={menu} className="dm-tree-menu-anchor"><button type="button" className="dm-thread-more" aria-label={`资料操作 ${name}`} aria-expanded={open} onClick={() => setOpen(value => !value)}><Icon name="more" size={16} /></button>{open && <div className="dm-thread-menu" role="menu"><button type="button" role="menuitem" className="is-danger" onClick={() => { setOpen(false); onRemove(path, name) }}>删除</button></div>}</div>
}

function FileGroup({ path, name, files, selectedId, onSelect, statuses, onRemove, depth = 0 }: { path: string; name: string; files: WorkspaceFile[]; selectedId: string | null; onSelect: Props['onSelect']; statuses: Map<string, FileIndexStatus>; onRemove: Props['onRemove']; depth?: number }) {
  const [expanded, setExpanded] = useState(true)
  const [limit, setLimit] = useState(100)
  const groups = new Map<string, WorkspaceFile[]>()
  const direct: WorkspaceFile[] = []
  for (const file of files) {
    const relative = normalizedPath(file.saved_path).slice(normalizedPath(path).length + 1)
    if (!relative.includes('/')) direct.push(file)
    else {
      const child = `${normalizedPath(path)}/${relative.split('/')[0]}`
      groups.set(child, [...(groups.get(child) || []), file])
    }
  }
  const rows = [...groups.keys(), ...direct.map(file => file.saved_path)]
  return <div><div className="dm-tree-item"><SelectionBox path={path} name={name} /><button className="dm-folder-row dm-directory-row" style={{ paddingLeft: 8 + Math.min(depth, 8) * 14 }} onClick={() => setExpanded(value => !value)} aria-expanded={expanded} title={path}><span className={`dm-directory-caret${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={12} /></span><Icon name="folder" size={16} /><span className="dm-directory-name">{name}</span></button><DocumentMenu path={path} name={name} onRemove={onRemove} /></div>{expanded && <div>{rows.slice(0, limit).map(key => groups.has(key)
    ? <FileGroup key={key} path={key} name={key.split('/').at(-1) || key} files={groups.get(key)!} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} statuses={statuses} onRemove={onRemove} />
    : <FileRow key={key} file={direct.find(file => file.saved_path === key)!} depth={depth} selectedId={selectedId} onSelect={onSelect} status={statuses.get(key)} onRemove={onRemove} />)}{rows.length > limit && <button className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>加载更多（已显示 {limit} / {rows.length}）</button>}</div>}</div>
}
