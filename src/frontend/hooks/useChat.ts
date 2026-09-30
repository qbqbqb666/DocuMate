import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, apiRequest } from '../api/client'
import { consumeSse } from '../api/sse'
import type { ApprovalPayload, SseEvent, ThreadArtifact, ThreadMessage, TurnResultPayload } from '../api/types'

export interface ToolCallView {
  id: string
  name: string
  arguments_str: string
  result?: any
}

export interface ChatCitation {
  doc_id: string
  doc_filename: string
  chunk_index: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCallView[]
  citations?: ChatCitation[]
  error?: string
  artifact_ids?: string[]
}

export interface PendingTool extends ApprovalPayload {}
export type PermissionDecision = 'deny' | 'allow'

interface UseChatResult {
  messages: ChatMessage[]
  loading: boolean
  threadId: string | null
  pendingTool: PendingTool | null
  statusMessage: string | null
  send: (text: string) => Promise<void>
  cancel: () => void
  clear: () => void
  loadThread: (threadId: string) => Promise<void>
  startNewThread: () => Promise<string | null>
  submitPermission: (decision: PermissionDecision) => Promise<void>
  configError: string | null
}

export function useChat(
  workspacePath?: string,
  projectId?: string,
  permission: 'request_approval' | 'full_access' = 'request_approval',
  provider: 'siliconflow' | 'deepseek' = 'siliconflow',
  modelName = 'Qwen/Qwen3.5-4B',
): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [pendingTool, setPendingTool] = useState<PendingTool | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const activeRunRef = useRef<{ threadId: string; runId: string } | null>(null)

  const cancel = useCallback(() => {
    const activeRun = activeRunRef.current
    const controller = abortRef.current
    if (activeRun) {
      let aborted = false
      const abortStream = () => {
        if (aborted) return
        aborted = true
        controller?.abort()
      }
      const fallback = window.setTimeout(abortStream, 750)
      void apiRequest(
        `/api/threads/${encodeURIComponent(activeRun.threadId)}/runs/${encodeURIComponent(activeRun.runId)}/cancel`,
        { method: 'POST' },
      ).catch(() => undefined).finally(() => {
        window.clearTimeout(fallback)
        abortStream()
      })
    } else {
      controller?.abort()
    }
    abortRef.current = null
    activeRunRef.current = null
    if (activeRun) {
      setMessages((previous) => updateLastAssistant(previous, (message) => ({
        ...message,
        content: message.content || '已停止',
      })))
    }
    setLoading(false)
    setStatusMessage(null)
  }, [])

  const clear = useCallback(() => {
    cancel()
    setMessages([])
    setPendingTool(null)
    setConfigError(null)
  }, [cancel])

  useEffect(() => {
    cancel()
    setMessages([])
    setThreadId(null)
    setPendingTool(null)
    setConfigError(null)
  }, [workspacePath, projectId, cancel])

  const loadThread = useCallback(async (id: string) => {
    if (!workspacePath) return
    cancel()
    setConfigError(null)
    try {
      const query = new URLSearchParams({ workspace_path: workspacePath })
      const basePath = `/api/threads/${encodeURIComponent(id)}`
      const [data, detail, artifactData] = await Promise.all([
        apiRequest<{ messages: ThreadMessage[] }>(`${basePath}/messages?${query}`),
        apiRequest<{ pending_approval: ApprovalPayload | null }>(`${basePath}?${query}`),
        apiRequest<{ artifacts: ThreadArtifact[] }>(`${basePath}/artifacts?${query}`),
      ])
      setMessages(historyMessages(data.messages, artifactData.artifacts))
      setThreadId(id)
      setPendingTool(detail.pending_approval)
    } catch (reason) {
      setConfigError(reason instanceof Error ? reason.message : String(reason))
    }
  }, [cancel, workspacePath])

  const startNewThread = useCallback(async (): Promise<string | null> => {
    if (!workspacePath) return null
    cancel()
    setConfigError(null)
    try {
      const result = await apiRequest<{ thread_id: string }>('/api/threads', {
        method: 'POST',
        body: JSON.stringify({ workspace_path: workspacePath, project_id: projectId }),
      })
      setThreadId(result.thread_id)
      setMessages([])
      setPendingTool(null)
      window.dispatchEvent(new Event('documate:threads-changed'))
      return result.thread_id
    } catch (reason) {
      setConfigError(reason instanceof Error ? reason.message : String(reason))
      return null
    }
  }, [cancel, projectId, workspacePath])

  const handleEvent = useCallback((event: SseEvent) => {
    const payload = event.data as Record<string, any>
    if (event.event === 'status') {
      setStatusMessage(typeof payload.message === 'string' ? payload.message : null)
    } else if (event.event === 'model_chunk') {
      const text = typeof payload.text === 'string' ? payload.text : ''
      if (text) setMessages((previous) => updateLastAssistant(previous, (message) => ({
        ...message,
        content: message.content + text,
      })))
    } else if (event.event === 'approval') {
      setPendingTool(payload.approval as ApprovalPayload)
      setStatusMessage(null)
    } else if (event.event === 'result') {
      const result = payload as unknown as TurnResultPayload
      const finalContent = result.finalization?.message.content
      if (finalContent) setMessages((previous) => updateLastAssistant(previous, (message) => ({
        ...message,
        content: finalContent,
        artifact_ids: result.finalization?.artifact_ids || [],
      })))
      setStatusMessage(null)
    } else if (event.event === 'error') {
      const message = typeof payload.message === 'string' ? payload.message : '后端运行失败'
      if (payload.error_type === 'RunCancelledError') {
        setMessages((previous) => updateLastAssistant(previous, (item) => ({
          ...item,
          content: item.content || '已停止',
        })))
        setStatusMessage(null)
        return
      }
      setMessages((previous) => updateLastAssistant(previous, (item) => ({ ...item, error: message })))
      setConfigError(message)
      setStatusMessage(null)
    }
  }, [])

  const runStream = useCallback(async (
    activeThreadId: string,
    path: string,
    body: Record<string, unknown>,
  ) => {
    const controller = new AbortController()
    const runId = crypto.randomUUID()
    abortRef.current = controller
    activeRunRef.current = { threadId: activeThreadId, runId }
    setLoading(true)
    try {
      const response = await apiFetch(path, {
        method: 'POST',
        body: JSON.stringify({ ...body, run_id: runId }),
        signal: controller.signal,
      })
      await consumeSse(response, handleEvent)
    } catch (reason) {
      if (reason instanceof Error && reason.name === 'AbortError') return
      const message = reason instanceof Error ? reason.message : String(reason)
      setMessages((previous) => updateLastAssistant(previous, (item) => ({ ...item, error: message })))
      setConfigError(message)
    } finally {
      setLoading(false)
      setStatusMessage(null)
      if (activeRunRef.current?.runId === runId) activeRunRef.current = null
      if (abortRef.current === controller) abortRef.current = null
      window.dispatchEvent(new Event('documate:threads-changed'))
    }
  }, [handleEvent])

  const send = useCallback(async (text: string) => {
    if (!workspacePath || !text.trim() || loading) return
    setConfigError(null)
    let activeThreadId = threadId
    if (!activeThreadId) activeThreadId = await startNewThread()
    if (!activeThreadId) return
    setMessages((previous) => [
      ...previous,
      { role: 'user', content: text.trim() },
      { role: 'assistant', content: '' },
    ])
    await runStream(activeThreadId, `/api/threads/${encodeURIComponent(activeThreadId)}/turns/stream`, {
      workspace_path: workspacePath,
      project_id: projectId,
      content: text.trim(),
      permission,
      provider,
      model_name: modelName,
    })
  }, [loading, modelName, permission, projectId, provider, runStream, startNewThread, threadId, workspacePath])

  const submitPermission = useCallback(async (decision: PermissionDecision) => {
    if (!workspacePath || !threadId || !pendingTool || loading) return
    const approval = pendingTool
    setPendingTool(null)
    await runStream(
      threadId,
      `/api/threads/${encodeURIComponent(threadId)}/approvals/${encodeURIComponent(approval.approval_id)}/stream`,
      { workspace_path: workspacePath, project_id: projectId, tool_call_id: approval.tool_call_id, decision },
    )
  }, [loading, pendingTool, projectId, runStream, threadId, workspacePath])

  return {
    messages, loading, threadId, pendingTool, statusMessage, send, cancel, clear,
    loadThread, startNewThread, submitPermission, configError,
  }
}

function historyMessages(records: ThreadMessage[], artifacts: ThreadArtifact[]): ChatMessage[] {
  const toolResults = new Map<string, unknown>()
  const artifactIdsByTurn = new Map<number, string[]>()
  for (const artifact of artifacts) {
    const existing = artifactIdsByTurn.get(artifact.turn_number) || []
    existing.push(artifact.artifact_id)
    artifactIdsByTurn.set(artifact.turn_number, existing)
  }
  for (const message of records) {
    if (message.role !== 'tool' || !message.tool_call_id) continue
    try { toolResults.set(message.tool_call_id, JSON.parse(message.content)) }
    catch { toolResults.set(message.tool_call_id, message.content) }
  }
  const result: ChatMessage[] = []
  for (const message of records) {
    if (message.role === 'user') result.push({ role: 'user', content: message.content })
    if (message.role === 'assistant') {
      const calls = (message.tool_calls || []).map((call) => {
        const id = String(call.id || '')
        const args = call.args ?? call.arguments ?? {}
        return {
          id,
          name: String(call.name || ''),
          arguments_str: typeof args === 'string' ? args : JSON.stringify(args),
          result: toolResults.get(id),
        }
      })
      result.push({
        role: 'assistant', content: message.content,
        tool_calls: calls.length ? calls : undefined,
        artifact_ids: artifactIdsByTurn.get(message.turn_number),
      })
    }
  }
  return result
}

function updateLastAssistant(
  messages: ChatMessage[],
  update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const next = [...messages]
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index].role !== 'assistant') continue
    next[index] = update(next[index])
    return next
  }
  next.push(update({ role: 'assistant', content: '' }))
  return next
}
