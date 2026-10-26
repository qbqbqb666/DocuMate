import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import type { WorkspaceFile } from '../hooks/useWorkspaceFiles'
import { Icon } from './Icon'

interface Props {
  workspacePath: string
  projectId?: string
  onClose: () => void
  onAdded: () => void
}

interface PendingSource {
  path: string
  kind: 'file' | 'directory'
  files: WorkspaceFile[]
  originalFiles: WorkspaceFile[]
  wholeFolder: boolean
}

function withinFolder(path: string, folder: string) {
  return path.replaceAll('\\', '/').startsWith(`${folder.replaceAll('\\', '/').replace(/\/$/, '')}/`)
}

export function AddDocumentsDialog({ workspacePath, projectId, onClose, onAdded }: Props) {
  const [pending, setPending] = useState<PendingSource[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [limit, setLimit] = useState(100)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const alive = useRef(true)
  const files = [...new Map(pending.flatMap(source => source.files).map(file => [file.saved_path, file])).values()]
  const folders = pending.filter(source => source.kind === 'directory')
  const selectedFiles = files.filter(file => selected.has(file.saved_path))
  const hasSelection = selectedFiles.length > 0 || folders.some(source => source.wholeFolder)

  const removeFile = (path: string) => {
    setPending(current => current.filter(source => source.kind !== 'file' || source.path !== path).map(source =>
      source.files.some(file => file.saved_path === path)
        ? { ...source, wholeFolder: false, files: source.files.filter(file => file.saved_path !== path) } : source))
    setSelected(current => { const next = new Set(current); next.delete(path); return next })
  }
  const toggleFile = (path: string) => {
    setPending(current => current.map(source => source.files.some(file => file.saved_path === path) ? { ...source, wholeFolder: false } : source))
    setSelected(current => { const next = new Set(current); if (next.has(path)) next.delete(path); else next.add(path); return next })
  }

  useEffect(() => {
    alive.current = true
    const previousFocus = document.activeElement as HTMLElement | null
    closeButton.current?.focus()
    return () => { alive.current = false; if (previousFocus?.isConnected) previousFocus.focus() }
  }, [])

  const choose = async (directory: boolean) => {
    setError(null)
    setBusy(true)
    try {
      let paths: string[]
      if (directory) {
        if (!window.documate?.pickFolders) throw new Error('请重启 DocuMate 后再选择多个文件夹。')
        paths = await window.documate.pickFolders()
      } else {
        if (!window.documate?.pickFiles) throw new Error('请重启 DocuMate 后再选择文件。')
        paths = await window.documate.pickFiles()
      }
      if (!paths.length || !alive.current) return
      const data = await apiRequest<{ files: WorkspaceFile[] }>('/api/workspace-files/candidates', { method: 'POST', body: JSON.stringify({ paths, recursive: directory }) })
      if (!alive.current) return
      const additions: PendingSource[] = directory
        ? paths.map(path => {
          const folderFiles = data.files.filter(file => withinFolder(file.saved_path, path))
          return { path, kind: 'directory', wholeFolder: true, files: folderFiles, originalFiles: folderFiles }
        })
        : data.files.map(file => ({ path: file.saved_path, kind: 'file', wholeFolder: false, files: [file], originalFiles: [file] }))
      setPending(current => [...current, ...additions.filter(source => !current.some(item => item.path === source.path))])
      setSelected(current => new Set([...current, ...data.files.map(file => file.saved_path)]))
      setLimit(100)
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { if (alive.current) setBusy(false) }
  }
  const submit = async () => {
    if (busy || !hasSelection) return
    setBusy(true); setError(null)
    try {
      const directories = folders.filter(source => source.wholeFolder).map(source => ({ path: source.path, kind: 'directory' }))
      const sources = [...directories, ...selectedFiles.filter(file => !directories.some(source => withinFolder(file.saved_path, source.path))).map(file => ({ path: file.saved_path, kind: 'file', group_path: folders.find(folder => folder.files.some(item => item.saved_path === file.saved_path))?.path }))]
      await apiRequest('/api/workspace-files/register', { method: 'POST', body: JSON.stringify({ workspace_path: workspacePath, project_id: projectId, sources }) })
      if (alive.current) onAdded()
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { if (alive.current) setBusy(false) }
  }

  return <div className="dm-dialog-overlay">
    <button className="dm-dialog-scrim" aria-label="取消添加资料" disabled={busy} onClick={onClose} />
    <section role="dialog" aria-modal="true" aria-labelledby="add-documents-title" className="dm-add-documents" onKeyDown={event => {
      if (event.key === 'Escape' && !busy) { event.preventDefault(); onClose() }
      if (event.key === 'Tab') {
        const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),[tabindex="0"]'))
        const first = elements[0], last = elements.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}>
      <header><h2 id="add-documents-title">添加资料</h2><button ref={closeButton} type="button" className="dm-icon-button" disabled={busy} aria-label="关闭添加资料" onClick={onClose}><Icon name="close" size={18} /></button></header>
      <p className="dm-add-source-note">保留原文件位置，加入当前项目并建立本地检索索引。</p>
      <div className="dm-add-source-actions"><button type="button" disabled={busy} onClick={() => void choose(false)}><Icon name="file" size={18} />选择文件</button><button type="button" disabled={busy} onClick={() => void choose(true)}><Icon name="folder" size={18} />选择文件夹</button></div>
      {folders.length > 0 && <div className="dm-add-pending-folders">{folders.map(folder => <div className="dm-add-folder-selection" key={folder.path}>
        <div className="dm-add-pending-heading"><Icon name="folder" size={18} /><p title={folder.path}>{folder.path}</p><button type="button" className="dm-icon-button" disabled={busy} aria-label={`移除文件夹 ${folder.path}`} title="移除待加入文件夹" onClick={() => setPending(current => current.filter(source => source.path !== folder.path))}><Icon name="close" size={16} /></button></div>
        <label><input type="checkbox" disabled={busy} checked={folder.wholeFolder} onChange={event => {
          const checked = event.target.checked
          setPending(current => current.map(source => source.path === folder.path ? { ...source, wholeFolder: checked, files: checked ? source.originalFiles : source.files } : source))
          if (checked) setSelected(current => new Set([...current, ...folder.originalFiles.map(file => file.saved_path)]))
        }} />加入整个文件夹，包含后续新增资料</label>
        {!folder.wholeFolder && <small>仅加入下方勾选的文件</small>}
      </div>)}</div>}
      <div className="dm-add-selection-heading"><span>{busy ? '正在处理…' : `${selectedFiles.length} / ${files.length} 个文件${folders.length ? ` · ${folders.length} 个文件夹` : ''}`}</span><button type="button" disabled={busy || !files.length} onClick={() => {
        setPending(current => current.map(source => ({ ...source, wholeFolder: false })))
        setSelected(new Set(selectedFiles.length === files.length ? [] : files.map(file => file.saved_path)))
      }}>{selectedFiles.length === files.length && files.length ? '取消全选' : '全选文件'}</button></div>
      <div className="dm-add-file-list">{!files.length ? <div className="dm-add-file-empty"><Icon name="folder" size={28} /><p>{folders.length ? '当前文件夹没有支持的文件' : '选择要加入的文件或文件夹'}</p><span>PDF / DOCX / XLSX / TXT / Markdown</span></div> : files.slice(0, limit).map(file => <div className="dm-add-file-row" key={file.saved_path}>
        <label title={file.saved_path}><input type="checkbox" checked={selected.has(file.saved_path)} disabled={busy} onChange={() => toggleFile(file.saved_path)} /><span className="dm-add-file-symbol" data-file-type={file.doc_type}><Icon name="file" size={20} /></span><span className="dm-add-file-copy"><b>{file.filename}</b><small>{file.saved_path}</small></span></label>
        <button type="button" className="dm-icon-button" disabled={busy} aria-label={`移除文件 ${file.filename}`} title="移除待加入文件" onClick={() => removeFile(file.saved_path)}><Icon name="close" size={16} /></button>
      </div>)}{limit < files.length && <button type="button" disabled={busy} className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>显示更多（{limit} / {files.length}）</button>}</div>
      {error && <p className="dm-inline-error" role="alert">{error}</p>}
      <footer><button type="button" className="dm-outline-button" disabled={busy} onClick={onClose}>取消</button><button type="button" className="dm-dialog-primary" disabled={busy || !hasSelection} onClick={() => void submit()}>{busy ? '正在处理…' : '加入并建立索引'}</button></footer>
    </section>
  </div>
}
