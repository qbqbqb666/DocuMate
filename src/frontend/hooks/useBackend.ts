import { useState, useCallback } from 'react'
import { apiRequest } from '../api/client'

export interface HealthResponse {
  status: string
  service: string
}

export function useBackend() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<HealthResponse | null>(null)

  const callHello = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await apiRequest<HealthResponse>('/api/health'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { loading, error, data, callHello }
}
