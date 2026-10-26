import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiRequest } from '../api/client'

export interface WorkspaceFile {
  id: string
  filename: string
  saved_path: string
  kind: 'directory' | 'file'
  doc_type: string
  size_bytes: number
  uploaded_at: string
  previewable: boolean
  group_path?: string
  missing?: boolean
}

export interface FilePreview extends WorkspaceFile {
  text: string
  char_count: number
  truncated: boolean
  version: string
}

export interface FileIndexStatus { path: string; status: 'pending' | 'indexing' | 'ready' | 'error' | 'missing'; error: string | null }
export interface IndexSummary { files: FileIndexStatus[]; ready: number; pending: number; indexing: number; errors: FileIndexStatus[]; worker_error: string | null }

export function useWorkspaceFiles(workspacePath?: string) {
  const [roots, setRoots] = useState<WorkspaceFile[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [index, setIndex] = useState<IndexSummary | null>(null)
  const [indexError, setIndexError] = useState<string | null>(null)
  const generation = useRef(0)
  const refresh = useCallback(async () => {
    if (!workspacePath) return
    const current = generation.current
    try {
      const result = await apiRequest<{ roots: WorkspaceFile[]; total_files: number }>('/api/workspace-files')
      if (current !== generation.current) return
      setRoots(result.roots)
      setCount(result.total_files)
      setError(null)
    } catch (reason) {
      if (current === generation.current) setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      if (current === generation.current) setLoading(false)
    }
  }, [workspacePath])

  const refreshIndexStatus = useCallback(async () => {
    if (!workspacePath) return
    const current = generation.current
    try {
      const status = await apiRequest<IndexSummary>('/api/workspace-files/index-status')
      if (current === generation.current) { setIndex(status); setIndexError(null) }
    } catch (reason) {
      if (current === generation.current) setIndexError(reason instanceof ApiError && reason.status === 404 ? '请重启 DocuMate 以启用资料入库与索引状态。' : reason instanceof Error ? reason.message : String(reason))
    }
  }, [workspacePath])

  const remove = useCallback(async (path: string | string[], projectId?: string) => {
    if (!workspacePath) return
    await apiRequest('/api/workspace-files/remove', { method: 'POST', body: JSON.stringify({ workspace_path: workspacePath, project_id: projectId, paths: Array.isArray(path) ? path : [path] }) })
    await Promise.all([refresh(), refreshIndexStatus()])
    window.dispatchEvent(new Event('documate:files-refreshed'))
  }, [workspacePath, refresh, refreshIndexStatus])

  const refreshAll = useCallback(async () => {
    if (!workspacePath) return
    setRefreshing(true)
    try {
      await apiRequest('/api/workspace-files/refresh', { method: 'POST' })
      await Promise.all([refresh(), refreshIndexStatus()])
      window.dispatchEvent(new Event('documate:files-refreshed'))
    } finally { setRefreshing(false) }
  }, [workspacePath, refresh, refreshIndexStatus])

  useEffect(() => {
    generation.current += 1
    setRoots([])
    setCount(0)
    setIndex(null)
    setIndexError(null)
    setLoading(true)
    void refresh()
    void refreshIndexStatus()
    const statusTimer = window.setInterval(() => { if (document.visibilityState === 'visible') void refreshIndexStatus() }, 2000)
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 5000)
    return () => { generation.current += 1; window.clearInterval(timer); window.clearInterval(statusTimer) }
  }, [refresh, refreshIndexStatus])

  const fetchDetail = useCallback(async (path: string, knownVersion?: string): Promise<FilePreview | null> => {
    const params = new URLSearchParams({ path })
    if (knownVersion) params.set('known_version', knownVersion)
    const result = await apiRequest<FilePreview | { unchanged: true }>(`/api/workspace-files/preview?${params}`)
    return 'unchanged' in result ? null : result
  }, [])
  return { roots, count, loading, error, index, indexError, refreshing, refreshAll, remove, refresh, refreshIndexStatus, fetchDetail }
}
