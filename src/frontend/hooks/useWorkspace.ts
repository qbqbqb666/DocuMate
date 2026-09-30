import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

export interface WorkspaceInfo {
  path: string
  is_user_set: boolean
  is_dev_default: boolean
  documents_dir: string
  generated_dir: string
  vectors_dir: string
  config_file: string
}

export interface RecentWorkspace {
  path: string
  name: string
  exists: boolean
  is_current: boolean
}

interface UseWorkspaceResult {
  info: WorkspaceInfo | null
  recent: RecentWorkspace[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  switchTo: (path: string) => Promise<boolean>
  pickAndSwitch: () => Promise<boolean>
  openInFinder: () => Promise<void>
}

export function useWorkspace(): UseWorkspaceResult {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null)
  const [recent, setRecent] = useState<RecentWorkspace[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchRecent = useCallback(async () => {
    try {
      setRecent(await apiRequest<RecentWorkspace[]>('/api/workspace/recent'))
    } catch {
      // ignore - recent 不是关键路径
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setInfo(await apiRequest<WorkspaceInfo>('/api/workspace'))
      await fetchRecent()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [fetchRecent])

  const switchTo = useCallback(async (path: string) => {
    setError(null)
    try {
      const data = await apiRequest<{ info: WorkspaceInfo }>('/api/workspace/switch', {
        method: 'POST',
        body: JSON.stringify({ path }),
      })
      setInfo(data.info)
      await fetchRecent()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }, [fetchRecent])

  const pickAndSwitch = useCallback(async () => {
    if (!window.documate?.pickFolder) {
      setError('Electron API 不可用——请用 npm run dev 启动')
      return false
    }
    const picked = await window.documate.pickFolder({
      title: '选择 DocuMate 工作区',
      buttonLabel: '使用此文件夹',
    })
    if (!picked) return false
    return switchTo(picked)
  }, [switchTo])

  const openInFinder = useCallback(async () => {
    if (info && window.documate?.openFolder) {
      await window.documate.openFolder(info.path)
    }
  }, [info])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { info, recent, loading, error, refresh, switchTo, pickAndSwitch, openInFinder }
}
