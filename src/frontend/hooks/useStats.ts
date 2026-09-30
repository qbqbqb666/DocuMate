import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

export interface WorkspaceStats {
  document_count: number
  thread_count: number
  total_tokens: number
}

const EMPTY_STATS: WorkspaceStats = {
  document_count: 0,
  thread_count: 0,
  total_tokens: 0,
}

export function useStats(workspacePath?: string) {
  const [stats, setStats] = useState<WorkspaceStats>(EMPTY_STATS)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!workspacePath) return
    try {
      setStats(await apiRequest<WorkspaceStats>('/api/stats'))
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }, [workspacePath])

  useEffect(() => { void refresh() }, [refresh])
  return { stats, error, refresh }
}
