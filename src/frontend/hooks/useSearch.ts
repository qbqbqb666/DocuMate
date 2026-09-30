import { useCallback, useState } from 'react'
import { apiRequest } from '../api/client'

export interface SearchHit {
  chunk_id: string
  text: string
  doc_id: string
  doc_filename: string
  chunk_index: number
}

export function useSearch() {
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const search = useCallback(async (q: string, topK = 5) => {
    if (!q.trim()) {
      setHits([])
      return
    }
    setQuery(q)
    setLoading(true)
    setError(null)
    try {
      const json = await apiRequest<{ hits: SearchHit[] }>('/api/search', {
        method: 'POST',
        body: JSON.stringify({ query: q, top_k: topK }),
      })
      setHits(json.hits || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setHits([])
    } finally {
      setLoading(false)
    }
  }, [])

  const clear = useCallback(() => {
    setHits([])
    setQuery('')
    setError(null)
  }, [])

  return { hits, loading, error, query, search, clear }
}
