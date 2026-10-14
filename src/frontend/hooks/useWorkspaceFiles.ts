import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'

export interface WorkspaceFile {
  id: string
  filename: string
  saved_path: string
  kind: 'directory' | 'file'
  doc_type: string
  size_bytes: number
  uploaded_at: string
  previewable: boolean
}

export interface FilePreview extends WorkspaceFile {
  text: string
  char_count: number
  truncated: boolean
  version: string
}

export function useWorkspaceFiles(workspacePath?: string) {
  const [roots, setRoots] = useState<WorkspaceFile[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
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

  useEffect(() => {
    generation.current += 1
    setRoots([])
    setCount(0)
    setLoading(true)
    void refresh()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 5000)
    return () => { generation.current += 1; window.clearInterval(timer) }
  }, [refresh])

  const fetchDetail = useCallback(async (path: string, knownVersion?: string): Promise<FilePreview | null> => {
    const params = new URLSearchParams({ path })
    if (knownVersion) params.set('known_version', knownVersion)
    const result = await apiRequest<FilePreview | { unchanged: true }>(`/api/workspace-files/preview?${params}`)
    return 'unchanged' in result ? null : result
  }, [])
  return { roots, count, loading, error, refresh, fetchDetail }
}
