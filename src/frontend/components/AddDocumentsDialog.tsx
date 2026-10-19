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

export function AddDocumentsDialog({ workspacePath, projectId, onClose, onAdded }: Props) {
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [folder, setFolder] = useState<string | null>(null)
  const [wholeFolder, setWholeFolder] = useState(false)
  const [limit, setLimit] = useState(100)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const alive = useRef(true)

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
        if (!window.documate?.pickFolder) throw new Error('请在桌面版 DocuMate 中选择文件夹。')
        const path = await window.documate.pickFolder({ title: '选择要加入的资料文件夹', buttonLabel: '选择文件夹' })
        paths = path ? [path] : []
      } else {
        if (!window.documate?.pickFiles) throw new Error('请重启 DocuMate 后再选择文件。')
        paths = await window.documate.pickFiles()
      }
      if (!paths.length || !alive.current) return
      const data = await apiRequest<{ files: WorkspaceFile[] }>('/api/workspace-files/candidates', { method: 'POST', body: JSON.stringify({ paths, recursive: directory }) })
      if (!alive.current) return
      setFiles(data.files)
      setSelected(new Set(data.files.map(file => file.id)))
      setFolder(directory ? paths[0] : null)
      setWholeFolder(directory)
      setLimit(100)
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { if (alive.current) setBusy(false) }
  }
  const submit = async () => {
    if (busy || (!wholeFolder && !selected.size)) return
    setBusy(true); setError(null)
    try {
      const sources = wholeFolder && folder ? [{ path: folder, kind: 'directory' }] : files.filter(file => selected.has(file.id)).map(file => ({ path: file.saved_path, kind: 'file' }))
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
      {folder && <div className="dm-add-folder-selection"><p title={folder}>{folder}</p><label><input type="checkbox" disabled={busy} checked={wholeFolder} onChange={event => { setWholeFolder(event.target.checked); setSelected(new Set(event.target.checked ? files.map(file => file.id) : [])) }} />加入整个文件夹，包含后续新增资料</label></div>}
      <div className="dm-add-selection-heading"><span>{busy ? '正在处理…' : `${selected.size} / ${files.length} 个文件`}</span><button type="button" disabled={busy || !files.length} onClick={() => { setWholeFolder(false); setSelected(new Set(selected.size === files.length ? [] : files.map(file => file.id))) }}>{selected.size === files.length && files.length ? '取消全选' : '全选文件'}</button></div>
      <div className="dm-add-file-list">{!files.length ? <div className="dm-add-file-empty"><Icon name="folder" size={28} /><p>{folder ? '当前文件夹没有支持的文件' : '选择要加入的文件或文件夹'}</p><span>PDF / DOCX / XLSX / TXT / Markdown</span></div> : files.slice(0, limit).map(file => <label key={file.id} title={file.saved_path}><input type="checkbox" checked={selected.has(file.id)} disabled={busy} onChange={() => { setWholeFolder(false); setSelected(current => { const next = new Set(current); if (next.has(file.id)) next.delete(file.id); else next.add(file.id); return next }) }} /><span className="dm-add-file-symbol" data-file-type={file.doc_type}><Icon name="file" size={20} /></span><span className="dm-add-file-copy"><b>{file.filename}</b><small>{folder ? file.saved_path.slice(folder.length + 1) : file.saved_path}</small></span></label>)}{limit < files.length && <button type="button" disabled={busy} className="dm-quiet-button" onClick={() => setLimit(value => value + 100)}>显示更多（{limit} / {files.length}）</button>}</div>
      {error && <p className="dm-inline-error" role="alert">{error}</p>}
      <footer><button type="button" className="dm-outline-button" disabled={busy} onClick={onClose}>取消</button><button type="button" className="dm-dialog-primary" disabled={busy || (!wholeFolder && !selected.size)} onClick={() => void submit()}>{busy ? '正在处理…' : '加入并建立索引'}</button></footer>
    </section>
  </div>
}
