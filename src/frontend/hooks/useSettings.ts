import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'

export interface AppSettings {
  trust_agent: boolean
  provider: 'siliconflow' | 'deepseek'
  model_name: string
}

export interface ModelOption {
  provider: 'siliconflow' | 'deepseek'
  model_name: string
  display_name: string
  max_input_tokens: number
}

interface UseSettingsResult {
  settings: AppSettings
  loading: boolean
  error: string | null
  models: ModelOption[]
  refresh: () => Promise<void>
  update: (patch: Partial<AppSettings>) => Promise<void>
}

const DEFAULT_SETTINGS: AppSettings = {
  trust_agent: false,
  provider: 'siliconflow',
  model_name: 'Qwen/Qwen3.5-4B',
}

export function useSettings(): UseSettingsResult {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextSettings, nextModels] = await Promise.all([
        apiRequest<AppSettings>('/api/settings'),
        apiRequest<ModelOption[]>('/api/settings/models'),
      ])
      setSettings(nextSettings)
      setModels(nextModels)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const update = useCallback(async (patch: Partial<AppSettings>) => {
    setError(null)
    try {
      const updated = await apiRequest<AppSettings>('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
      setSettings(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { settings, models, loading, error, refresh, update }
}
