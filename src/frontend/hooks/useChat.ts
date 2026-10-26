import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, apiRequest } from '../api/client'
import { consumeSse } from '../api/sse'
import type { ApprovalPayload, SseEvent, ThreadArtifact, ThreadMessage, ToolEventPayload, TurnResultPayload } from '../api/types'

export interface ToolCallView {
  id: string
  name: string
  arguments_str: string
  result?: any
}

export type ProgressState = 'running' | 'pending' | 'completed' | 'failed' | 'denied' | 'awaiting_approval' | 'cancelled' | 'interrupted'

export interface ProgressStep {
  id: string
  kind: 'stage' | 'model' | 'tool'
  title: string
  state: ProgressState
  content?: string
  message_id?: string
  tool?: ToolCallView
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
  progress?: ProgressStep[]
  status?: 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled' | 'stopped'
  run_id?: string
  answer_step_id?: string
}

export interface PendingTool extends ApprovalPayload {}
export type PermissionDecision = 'deny' | 'allow'

interface UseChatResult {
  messages: ChatMessage[]
  loading: boolean
  threadId: string | null
  pendingTool: PendingTool | null
  statusMessage: string | null
  send: (text: string, onSubmitted?: () => void) => Promise<boolean>
  cancel: () => void
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
  const generation = useRef(0)
  const sendingRef = useRef(false)
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
      void apiRequest<{ cancelled: boolean }>(
        `/api/threads/${encodeURIComponent(activeRun.threadId)}/runs/${encodeURIComponent(activeRun.runId)}/cancel`,
        { method: 'POST' },
      ).then(result => {
        if (result.cancelled) setMessages(previous => previous.map(message => message.run_id === activeRun.runId && message.status !== 'completed'
          ? finishProgress(message, 'cancelled') : message))
      }).catch(() => {
        setMessages(previous => previous.map(message => message.run_id === activeRun.runId && message.status !== 'completed'
          ? { ...message, error: '取消请求未获确认，后台执行状态待核实。' } : message))
      }).finally(() => {
        window.clearTimeout(fallback)
        abortStream()
      })
    } else {
      controller?.abort()
    }
    abortRef.current = null
    activeRunRef.current = null
    if (activeRun) {
      setMessages(previous => previous.map(message => message.run_id === activeRun.runId && message.status !== 'completed'
        ? finishProgress(message, 'stopped') : message))
    }
    setLoading(false)
    setStatusMessage(null)
  }, [])

  useEffect(() => () => {
    generation.current += 1
    cancel()
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
    const currentGeneration = generation.current
    setConfigError(null)
    try {
      const query = new URLSearchParams({ workspace_path: workspacePath })
      const basePath = `/api/threads/${encodeURIComponent(id)}`
      const [data, detail, artifactData] = await Promise.all([
        apiRequest<{ messages: ThreadMessage[] }>(`${basePath}/messages?${query}`),
        apiRequest<{ pending_approval: ApprovalPayload | null }>(`${basePath}?${query}`),
        apiRequest<{ artifacts: ThreadArtifact[] }>(`${basePath}/artifacts?${query}`),
      ])
      if (generation.current !== currentGeneration) return
      setMessages(historyMessages(data.messages, artifactData.artifacts, detail.pending_approval))
      setThreadId(id)
      setPendingTool(detail.pending_approval)
    } catch (reason) {
      setConfigError(reason instanceof Error ? reason.message : String(reason))
    }
  }, [cancel, workspacePath])

  const startNewThread = useCallback(async (): Promise<string | null> => {
    if (!workspacePath) return null
    cancel()
    const currentGeneration = generation.current
    setConfigError(null)
    try {
      const result = await apiRequest<{ thread_id: string }>('/api/threads', {
        method: 'POST',
        body: JSON.stringify({ workspace_path: workspacePath, project_id: projectId }),
      })
      if (generation.current !== currentGeneration) return null
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
    setMessages(previous => updateLastAssistant(previous, message => reduceChatEvent(message, event)))
    if (event.event === 'status') {
      setStatusMessage(typeof payload.message === 'string' ? payload.message : null)
    } else if (event.event === 'approval') {
      setPendingTool(payload.approval as ApprovalPayload)
      setStatusMessage(null)
    } else if (event.event === 'result') {
      setPendingTool(null)
      setStatusMessage(null)
    } else if (event.event === 'error') {
      setPendingTool(null)
      setStatusMessage(null)
    }
  }, [])

  const runStream = useCallback(async (
    activeThreadId: string,
    path: string,
    body: Record<string, unknown>,
    onSubmitted?: () => void,
  ) => {
    const controller = new AbortController()
    const runId = crypto.randomUUID()
    abortRef.current = controller
    activeRunRef.current = { threadId: activeThreadId, runId }
    setMessages(previous => updateLastAssistant(previous, message => ({ ...message, run_id: runId, status: 'running', error: undefined })))
    setLoading(true)
    let submitted = false
    let accepted = false
    let failed = false
    try {
      const response = await apiFetch(path, {
        method: 'POST',
        body: JSON.stringify({ ...body, run_id: runId }),
        signal: controller.signal,
      })
      await consumeSse(response, event => {
        if (activeRunRef.current?.runId !== runId) return
        if (!submitted && ['status', 'model_chunk', 'tool', 'result', 'approval'].includes(event.event)) {
          submitted = true
          onSubmitted?.()
        }
        if (event.event === 'result' || event.event === 'approval') accepted = true
        if (event.event === 'error') {
          const error = event.data as Record<string, unknown>
          if (error.error_type === 'RunCancelledError') accepted = true
          else failed = true
        }
        handleEvent(event)
      })
      if (activeRunRef.current?.runId !== runId) return true
      if (!accepted && !failed) throw new Error('对话连接已中断，请检查会话记录后重试')
      return accepted && !failed
    } catch (reason) {
      if (activeRunRef.current?.runId !== runId) return true
      const message = reason instanceof Error ? reason.message : String(reason)
      setMessages(previous => previous.map(item => item.run_id === runId
        ? { ...finishProgress(item, 'failed'), error: message } : item))
      return false
    } finally {
      if (activeRunRef.current?.runId === runId) {
        activeRunRef.current = null
        setLoading(false)
        setStatusMessage(null)
      }
      if (abortRef.current === controller) abortRef.current = null
      window.dispatchEvent(new Event('documate:threads-changed'))
    }
  }, [handleEvent])

  const send = useCallback(async (text: string, onSubmitted?: () => void): Promise<boolean> => {
    if (!workspacePath || !text.trim() || loading || sendingRef.current) return false
    const currentGeneration = generation.current
    sendingRef.current = true
    setLoading(true)
    setConfigError(null)
    try {
      let activeThreadId = threadId
      if (!activeThreadId) activeThreadId = await startNewThread()
      if (!activeThreadId || currentGeneration !== generation.current) return false
      setMessages((previous) => [
        ...previous,
        { role: 'user', content: text.trim() },
        { role: 'assistant', content: '', status: 'running', progress: [] },
      ])
      return await runStream(activeThreadId, `/api/threads/${encodeURIComponent(activeThreadId)}/turns/stream`, {
        workspace_path: workspacePath,
        project_id: projectId,
        content: text.trim(),
        permission,
        provider,
        model_name: modelName,
      }, onSubmitted)
    } finally {
      sendingRef.current = false
      setLoading(false)
    }
  }, [loading, modelName, permission, projectId, provider, runStream, startNewThread, threadId, workspacePath])

  const submitPermission = useCallback(async (decision: PermissionDecision) => {
    if (!workspacePath || !threadId || !pendingTool || loading) return
    const approval = pendingTool
    setPendingTool(null)
    setMessages(previous => updateLastAssistant(previous, message => ({
      ...message,
      progress: (message.progress || []).map(step => step.id === `tool:${approval.tool_call_id}`
        ? { ...step, state: 'pending', content: `已提交${decision === 'allow' ? '允许' : '拒绝'}请求，等待后端处理。` } : step),
    })))
    await runStream(
      threadId,
      `/api/threads/${encodeURIComponent(threadId)}/approvals/${encodeURIComponent(approval.approval_id)}/stream`,
      { workspace_path: workspacePath, project_id: projectId, tool_call_id: approval.tool_call_id, decision },
    )
  }, [loading, pendingTool, projectId, runStream, threadId, workspacePath])

  return {
    messages, loading, threadId, pendingTool, statusMessage, send, cancel,
    loadThread, startNewThread, submitPermission, configError,
  }
}

export function finishProgress(message: ChatMessage, status: ChatMessage['status']): ChatMessage {
  return {
    ...message,
    status,
    progress: (message.progress || []).map(step => {
      if (!['running', 'pending', 'awaiting_approval'].includes(step.state)) return step
      const state: ProgressState = status === 'cancelled' ? 'cancelled'
        : status === 'completed' && step.kind !== 'tool' ? 'completed' : 'interrupted'
      return { ...step, state }
    }),
  }
}

function closeStages(steps: ProgressStep[]): ProgressStep[] {
  return steps.map(step => step.kind !== 'tool' && step.state === 'running'
    ? { ...step, state: 'completed' } : step)
}

function toolStep(event: ToolEventPayload): ProgressStep {
  return {
    id: `tool:${event.tool_call_id}`, kind: 'tool', title: event.name,
    state: event.status === 'success' ? 'completed' : event.status === 'error' ? 'failed' : event.status,
    tool: { id: event.tool_call_id, name: event.name, arguments_str: JSON.stringify(event.args, null, 2),
      result: event.status === 'running' ? undefined : event.result },
  }
}

export function reduceChatEvent(message: ChatMessage, event: SseEvent): ChatMessage {
  const payload = event.data as Record<string, any>
  const steps = message.progress || []
  if (event.event === 'status') {
    if (payload.tool_call_id || payload.stage === 'tool') return message
    const previous = steps[steps.length - 1]
    if (previous?.state === 'running' && previous.title === payload.message) return message
    return { ...message, status: 'running', progress: [...closeStages(steps), {
      id: `stage:${steps.length}`, kind: payload.stage === 'model' ? 'model' : 'stage',
      title: payload.stage === 'model' ? '正在分析与生成回复' : payload.message, state: 'running',
    }] }
  }
  if (event.event === 'model_chunk') {
    if (payload.node !== 'model' || typeof payload.text !== 'string' || !payload.text) return message
    const index = steps.reduce((found, step, i) => step.kind === 'model' && step.state === 'running'
      && (!step.message_id || !payload.message_id || step.message_id === payload.message_id) ? i : found, -1)
    if (index < 0) return { ...message, progress: [...closeStages(steps), {
      id: `model:${payload.message_id || steps.length}`, kind: 'model', title: '正在分析与生成回复',
      state: 'running', message_id: payload.message_id, content: payload.text,
    }] }
    return { ...message, progress: steps.map((step, i) => i === index
      ? { ...step, message_id: payload.message_id || step.message_id, content: (step.content || '') + payload.text } : step) }
  }
  if (event.event === 'tool') {
    const step = toolStep(payload as ToolEventPayload)
    const exists = steps.some(item => item.id === step.id)
    const progress = closeStages(steps)
    return { ...message, progress: exists ? progress.map(item => item.id === step.id ? step : item) : [...progress, step] }
  }
  if (event.event === 'approval') {
    const approval = payload.approval as ApprovalPayload
    const step = toolStep({ tool_call_id: approval.tool_call_id, name: approval.name, args: approval.args, status: 'running' })
    step.state = 'awaiting_approval'
    const progress = closeStages(steps).map(item => item.kind === 'tool' && item.state === 'running'
      ? { ...item, state: 'interrupted' as const } : item)
    return { ...message, status: 'awaiting_approval', progress: progress.some(item => item.id === step.id)
      ? progress.map(item => item.id === step.id ? step : item) : [...progress, step] }
  }
  if (event.event === 'result') {
    const result = payload as TurnResultPayload
    if (!result.finalization) return { ...finishProgress(message, 'failed'), error: '本轮缺少最终回答，请检查会话记录。' }
    const finalContent = result.finalization.message.content
    const lastModel = steps.reduce((found, step, i) => step.kind === 'model' ? i : found, -1)
    const candidate = steps[lastModel]
    const reuse = candidate && (candidate.message_id === result.finalization.message.message_id
      || candidate.content === finalContent || (candidate.state === 'running' && !candidate.message_id))
    const answer: ProgressStep = {
      id: reuse ? candidate.id : `model:${result.finalization.message.message_id}`,
      kind: 'model', title: '回答', state: 'completed', content: finalContent,
      message_id: result.finalization.message.message_id,
    }
    const progress = reuse ? steps.map((step, index) => index === lastModel ? answer : step) : [...steps, answer]
    return finishProgress({ ...message, progress, answer_step_id: answer.id, content: finalContent, error: undefined,
      artifact_ids: result.finalization.artifact_ids }, 'completed')
  }
  if (event.event === 'error') {
    const cancelled = payload.error_type === 'RunCancelledError'
    return { ...finishProgress(message, cancelled ? 'cancelled' : 'failed'),
      error: cancelled ? undefined : typeof payload.message === 'string' ? payload.message : '后端运行失败' }
  }
  return message
}

export function historyMessages(records: ThreadMessage[], artifacts: ThreadArtifact[], approval: ApprovalPayload | null = null): ChatMessage[] {
  const toolResults = new Map<string, unknown>()
  for (const message of records) {
    if (message.role !== 'tool' || !message.tool_call_id) continue
    try { toolResults.set(message.tool_call_id, JSON.parse(message.content)) }
    catch { toolResults.set(message.tool_call_id, message.content) }
  }
  const result: ChatMessage[] = []
  const turns = new Map<number, ChatMessage>()
  for (const record of records) {
    if (record.role === 'user') {
      result.push({ role: 'user', content: record.content })
      continue
    }
    if (record.role !== 'assistant') continue
    let message = turns.get(record.turn_number)
    if (!message) {
      message = { role: 'assistant', content: '', progress: [], status: 'stopped' }
      turns.set(record.turn_number, message)
      result.push(message)
    }
    if (record.tool_calls?.length) {
      if (record.content) message.progress!.push({
        id: `model:${record.message_id}`, kind: 'model', title: '执行说明', state: 'completed', content: record.content,
      })
      for (const call of record.tool_calls) {
        const id = String(call.id || '')
        const rawArgs = call.args ?? call.arguments ?? {}
        const toolResult = toolResults.get(id) as Record<string, any> | undefined
        message.progress!.push({
          id: `tool:${id}`, kind: 'tool', title: String(call.name || ''),
          state: !toolResult ? 'interrupted' : toolResult.status === 'denied' ? 'denied'
            : toolResult.ok === false || toolResult.status === 'error' ? 'failed' : 'completed',
          tool: { id, name: String(call.name || ''),
            arguments_str: typeof rawArgs === 'string' ? rawArgs : JSON.stringify(rawArgs, null, 2), result: toolResult },
        })
      }
    } else {
      message.content = record.content
      message.status = 'completed'
      message.answer_step_id = `model:${record.message_id}`
      message.progress!.push({
        id: message.answer_step_id, kind: 'model', title: '回答', state: 'completed',
        content: record.content, message_id: record.message_id,
      })
    }
  }
  for (const [turn, message] of turns) {
    message.artifact_ids = artifacts.filter(artifact => artifact.turn_number === turn).map(artifact => artifact.artifact_id)
  }
  if (approval) {
    const last = result.reduce((found, item, i) => item.role === 'assistant' ? i : found, -1)
    if (last >= 0) result[last] = reduceChatEvent(result[last], { event: 'approval', data: { approval } })
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
