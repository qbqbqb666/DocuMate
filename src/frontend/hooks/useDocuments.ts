import { useCallback, useEffect, useState } from 'react'
import { apiFetch, apiRequest } from '../api/client'

export interface DocumentMeta {
  id: string
  filename: string
  doc_type: 'docx' | 'pdf' | 'xlsx'
  mime_type: string
  size_bytes: number
  char_count: number
  uploaded_at: string
  saved_path: string
  used_ocr: boolean
}

export interface DocumentDetail extends DocumentMeta {
  text: string
}

interface UseDocumentsResult {
  documents: DocumentMeta[]
  loading: boolean
  uploading: boolean
  error: string | null
  refresh: () => Promise<void>
  upload: (file: File) => Promise<DocumentMeta | null>
  fetchDetail: (id: string) => Promise<DocumentDetail | null>
}

export function useDocuments(): UseDocumentsResult {
  const [documents, setDocuments] = useState<DocumentMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setDocuments(await apiRequest<DocumentMeta[]>('/api/documents'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const upload = useCallback(
    async (file: File): Promise<DocumentMeta | null> => {
      setUploading(true)
      setError(null)
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await apiFetch('/api/documents/upload', {
          method: 'POST',
          body: formData,
        })
        const meta = (await res.json()) as DocumentMeta
        setDocuments((prev) => [meta, ...prev])
        return meta
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      } finally {
        setUploading(false)
      }
    },
    [],
  )

  const fetchDetail = useCallback(
    async (id: string): Promise<DocumentDetail | null> => {
      try {
        return await apiRequest<DocumentDetail>(`/api/documents/${encodeURIComponent(id)}`)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [],
  )

  // 启动时自动拉一次列表
  useEffect(() => {
    refresh()
  }, [refresh])

  return { documents, loading, uploading, error, refresh, upload, fetchDetail }
}
