import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { useWorkspaceFiles, type WorkspaceFile } from '../hooks/useWorkspaceFiles'

interface Props {
  workspacePath?: string
  selected: WorkspaceFile[]
  onConfirm: (files: WorkspaceFile[]) => void
  onClose: () => void
}

export function FileReferencePicker({ workspacePath, selected, onConfirm, onClose }: Props) {
  const { roots, loading: rootsLoading, error: rootsError } = useWorkspaceFiles(workspacePath)
  const [folder, setFolder] = useState<string | null>(null)
  const [parents, setParents] = useState<string[]>([])
  const [entries, setEntries] = useState<WorkspaceFile[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [chosen, setChosen] = useState(selected)

  useEffect(() => {
    if (!folder) return
    let cancelled = false
    setLoading(true)
    setError(null)
    apiRequest<{ entries: WorkspaceFile[]; total: number }>(`/api/workspace-files/children?path=${encodeURIComponent(folder)}&offset=${offset}&limit=100`)
      .then(result => { if (!cancelled) { setEntries(result.entries); setTotal(result.total) } })
      .catch(reason => { if (!cancelled) { setEntries([]); setError(reason instanceof Error ? reason.message : String(reason)) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [folder, offset])

  useEffect(() => {
    const escape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose])

  const toggle = (file: WorkspaceFile) => setChosen(current => current.some(item => item.id === file.id) ? current.filter(item => item.id !== file.id) : [...current, file])
  const navigate = (path: string) => { setParents(current => folder ? [...current, folder] : current); setFolder(path); setOffset(0); setEntries([]) }
  const back = () => { setFolder(parents.at(-1) || null); setParents(current => current.slice(0, -1)); setOffset(0); setEntries([]) }
  const visible = folder ? entries : roots
  return <div className="dm-dialog-overlay">
    <button className="dm-dialog-scrim" aria-label="关闭文件选择" onClick={onClose} />
    <section role="dialog" aria-modal="true" aria-label="选择文件区文件" className="dm-file-picker relative bg-white border border-slate-200 rounded-xl shadow-xl p-5 w-full max-w-xl mx-4">
      <div className="flex items-center justify-between mb-3"><h2 className="font-semibold text-slate-800">选择文件区文件</h2><button onClick={onClose} aria-label="关闭文件选择">✕</button></div>
      <p className="text-xs text-slate-500 mb-3">引用本地原文件，发送后由 Agent 直接读取。</p>
      {folder && <div className="flex items-center gap-2 mb-2 text-xs"><button onClick={back} className="dm-outline-button">返回上一级</button><span className="truncate text-slate-500" title={folder}>{folder}</span></div>}
      <div className="h-64 overflow-y-auto border border-slate-200 rounded-lg p-2">
        {(rootsError || error) && <div className="dm-inline-error">{rootsError || error}</div>}
        {(loading || rootsLoading) ? <p className="text-sm text-slate-500 p-3">正在读取…</p> : visible.length === 0 ? <p className="text-sm text-slate-500 p-3">文件夹为空，请先将资料保存到项目文件夹。</p> : visible.map(file => file.kind === 'directory'
          ? <button key={file.id} onClick={() => navigate(file.id)} className="w-full text-left text-sm p-2 rounded hover:bg-slate-50">📁 {file.filename} ›</button>
          : <label key={file.id} data-file-type={file.filename.split('.').at(-1)?.toLowerCase()} className="flex items-center gap-2 text-sm p-2 rounded hover:bg-slate-50" title={file.saved_path}><input type="checkbox" checked={chosen.some(item => item.id === file.id)} disabled={!file.previewable} onChange={() => toggle(file)} /><span className="truncate">{file.filename}</span>{!file.previewable && <span className="text-xs text-slate-400">暂不支持读取</span>}</label>)}
      </div>
      {folder && total > 100 && <div className="flex justify-between text-xs mt-2"><button disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 100))}>上一页</button><span>{offset + 1}–{Math.min(offset + 100, total)} / {total}</span><button disabled={loading || offset + 100 >= total} onClick={() => setOffset(value => value + 100)}>下一页</button></div>}
      <div className="flex flex-wrap gap-1 mt-3 max-h-24 overflow-y-auto">{chosen.map(file => <button key={file.id} onClick={() => toggle(file)} title={file.saved_path} className="dm-reference-chip" data-file-type={file.filename.split('.').at(-1)?.toLowerCase()}>{file.filename} ×</button>)}</div>
      <div className="flex items-center justify-between mt-4"><span className="text-xs text-slate-500">已选择 {chosen.length} 个文件</span><div className="flex gap-2"><button className="dm-outline-button" onClick={onClose}>取消</button><button className="dm-dialog-primary" onClick={() => onConfirm(chosen)}>加入对话</button></div></div>
    </section>
  </div>
}
