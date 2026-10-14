import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import type { WorkspaceFile } from '../hooks/useWorkspaceFiles'
import { Icon } from './Icon'

interface Props {
  roots: WorkspaceFile[]
  count: number
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
}

function Folder({ folder, depth, selectedId, onSelect }: { folder: WorkspaceFile; depth: number; selectedId: string | null; onSelect: (id: string) => void }) {
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
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [expanded, folder.id, limit])

  return <div>
    <button className="dm-folder-row" style={{ paddingLeft: 12 + depth * 14, width: 'calc(100% - 24px)', border: 0, textAlign: 'left' }} onClick={() => setExpanded(!expanded)} aria-expanded={expanded} title={folder.saved_path}>
      <span>{expanded ? '⌄' : '›'}</span><Icon name="folder" size={16} /><span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{folder.filename}</span>
    </button>
    {expanded && <div>
      {error && <div className="dm-inline-error">{error}</div>}
      {loading && entries.length === 0 && <div className="dm-doc-empty">正在读取…</div>}
      {!loading && !error && total === 0 && <div className="dm-doc-empty">文件夹为空</div>}
      {entries.map(item => item.kind === 'directory'
        ? <Folder key={item.id} folder={item} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
        : <button key={item.id} className={`dm-document-row ${selectedId === item.id ? 'is-selected' : ''}`} style={{ paddingLeft: 26 + depth * 14 }} onClick={() => onSelect(item.id)} title={item.saved_path}>
          <span className="file-type"><Icon name="file" size={18} /></span><span className="min-w-0 flex-1"><span className="filename">{item.filename}</span><span className="metadata">{(item.size_bytes / 1024).toFixed(1)} KB · {item.previewable ? '原文件' : '暂不支持预览'}</span></span>
        </button>)}
      {entries.length < total && <button className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>加载更多（已显示 {entries.length} / {total}）</button>}
    </div>}
  </div>
}

export function DocumentSidebar({ roots, count, selectedId, onSelect, loading }: Props) {
  return <div className="dm-doc-sidebar">
    <div className="dm-doc-heading"><span>原文件目录</span></div>
    <div className="dm-folder-row is-active"><Icon name="folder" size={19} /><span>可解析资料</span><span className="count">{loading ? '…' : count}</span></div>
    <div className="dm-document-list">
      {loading && <div className="dm-doc-empty">正在读取文件区…</div>}
      {roots.map(root => <Folder key={root.id} folder={root} depth={0} selectedId={selectedId} onSelect={onSelect} />)}
    </div>
  </div>
}
