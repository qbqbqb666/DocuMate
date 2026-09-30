import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

export interface StyleProfile {
  id: string
  name: string
  description: string
  doc_ids: string[]
  created_at: string
  updated_at: string
}

interface UseStylesResult {
  profiles: StyleProfile[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  create: (name: string, description: string, doc_ids: string[]) => Promise<StyleProfile | null>
  remove: (id: string) => Promise<boolean>
}

export function useStyles(): UseStylesResult {
  const [profiles, setProfiles] = useState<StyleProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setProfiles(await apiRequest<StyleProfile[]>('/api/styles'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const create = useCallback(async (name: string, description: string, doc_ids: string[]) => {
    setError(null)
    try {
      const profile = await apiRequest<StyleProfile>('/api/styles', {
        method: 'POST',
        body: JSON.stringify({ name, description, doc_ids }),
      })
      setProfiles((prev) => [profile, ...prev])
      return profile
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [])

  const remove = useCallback(async (id: string) => {
    setError(null)
    try {
      await apiRequest<void>(`/api/styles/${encodeURIComponent(id)}`, { method: 'DELETE' })
      setProfiles((prev) => prev.filter((p) => p.id !== id))
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { profiles, loading, error, refresh, create, remove }
}
