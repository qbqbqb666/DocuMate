import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import type { ThreadSummary } from '../api/types'

interface UseThreadsResult {
  threads: ThreadSummary[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: () => Promise<string | null>
  rename: (threadId: string, title: string) => Promise<boolean>
  remove: (threadId: string) => Promise<boolean>
}

export function useSessions(workspacePath?: string, projectId?: string): UseThreadsResult {
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!workspacePath) {
      setThreads([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const query = new URLSearchParams({ workspace_path: workspacePath })
      if (projectId) query.set('project_id', projectId)
      setThreads(await apiRequest<ThreadSummary[]>(`/api/threads?${query}`))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
    }
  }, [projectId, workspacePath])

  const create = useCallback(async (): Promise<string | null> => {
    if (!workspacePath) return null
    setError(null)
    try {
      const result = await apiRequest<{ thread_id: string }>('/api/threads', {
        method: 'POST',
        body: JSON.stringify({ workspace_path: workspacePath, project_id: projectId }),
      })
      await refresh()
      return result.thread_id
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      return null
    }
  }, [projectId, refresh, workspacePath])

  const rename = useCallback(async (threadId: string, title: string) => {
    if (!workspacePath) return false
    try {
      const query = new URLSearchParams({ workspace_path: workspacePath })
      await apiRequest(`/api/threads/${encodeURIComponent(threadId)}?${query}`, {
        method: 'PATCH', body: JSON.stringify({ title }),
      })
      await refresh(); return true
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); return false }
  }, [refresh, workspacePath])

  const remove = useCallback(async (threadId: string) => {
    if (!workspacePath) return false
    try {
      const query = new URLSearchParams({ workspace_path: workspacePath })
      await apiRequest(`/api/threads/${encodeURIComponent(threadId)}?${query}`, { method: 'DELETE' })
      await refresh(); return true
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); return false }
  }, [refresh, workspacePath])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const handleThreadsChanged = () => { void refresh() }
    window.addEventListener('documate:threads-changed', handleThreadsChanged)
    return () => window.removeEventListener('documate:threads-changed', handleThreadsChanged)
  }, [refresh])

  return { threads, loading, error, refresh, create, rename, remove }
}
