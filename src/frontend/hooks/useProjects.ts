import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import type { ProjectSummary } from '../api/types'

export function useProjects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try { setProjects(await apiRequest<ProjectSummary[]>('/api/projects')) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setLoading(false) }
  }, [])

  const create = useCallback(async (name: string, folderPaths: string[]) => {
    const project = await apiRequest<ProjectSummary>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name, folder_paths: folderPaths }),
    })
    await refresh()
    return project
  }, [refresh])

  const activate = useCallback(async (projectId: string) => {
    const project = await apiRequest<ProjectSummary>(`/api/projects/${encodeURIComponent(projectId)}/activate`, { method: 'POST' })
    setProjects((items) => items.map((item) => ({ ...item, is_active: item.id === project.id })))
    return project
  }, [])

  const remove = useCallback(async (projectId: string) => {
    await apiRequest(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' })
    const remaining = await apiRequest<ProjectSummary[]>('/api/projects')
    setProjects(remaining)
    return remaining
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  return { projects, loading, error, refresh, create, activate, remove }
}
