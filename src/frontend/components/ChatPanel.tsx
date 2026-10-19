import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useChat, type ChatMessage, type ToolCallView } from '../hooks/useChat'
import { useChatDraft } from '../hooks/useChatDraft'
import { useSessions } from '../hooks/useSessions'
import { apiUrl } from '../api/client'
import type { ApprovalPayload } from '../api/types'
import { FileReferencePicker } from './FileReferencePicker'
import { Icon } from './Icon'

interface Props {
  onJumpToDoc?: (docId: string) => void
  onTitleChange?: (title: string) => void
  workspacePath?: string
  newSessionRequest?: number
  trustAgent?: boolean
  provider?: 'siliconflow' | 'deepseek'
  modelName?: string
  requestedThreadId?: string | null
  projectId?: string
  models?: Array<{ provider: 'siliconflow' | 'deepseek'; model_name: string; display_name: string }>
  settingsLoading?: boolean
  onSettingsChange?: (patch: { trust_agent?: boolean; provider?: 'siliconflow' | 'deepseek'; model_name?: string }) => void
}

export function ChatPanel(props: Props) {
  const identity = JSON.stringify([props.workspacePath, props.projectId, props.requestedThreadId, props.newSessionRequest || 0])
  return <ConversationPanel key={identity} {...props} />
}

function ConversationPanel({ onJumpToDoc, onTitleChange, workspacePath, projectId, newSessionRequest = 0, trustAgent = false, provider = 'siliconflow', modelName = 'Qwen/Qwen3.5-4B', requestedThreadId = null, models = [], settingsLoading = false, onSettingsChange }: Props) {
  const {
    messages, loading, threadId, pendingTool, statusMessage, send, cancel,
    loadThread, startNewThread, submitPermission, configError,
  } = useChat(workspacePath, projectId, trustAgent ? 'full_access' : 'request_approval', provider, modelName)
  const sessions = useSessions(workspacePath, projectId)
  const conversationId = requestedThreadId || threadId
  const { input, setInput, referencedFiles, setReferencedFiles, clearSubmittedDraft } = useChatDraft(workspacePath, projectId, conversationId || `new:${newSessionRequest}`, !conversationId)
  const historyLoading = Boolean(requestedThreadId && requestedThreadId !== threadId)
  const [showFilePicker, setShowFilePicker] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastNewSessionRequest = useRef(0)
  const submitBusyRef = useRef(false)
  const isComposingRef = useRef(false)

  useEffect(() => {
    if (requestedThreadId && requestedThreadId !== threadId) void loadThread(requestedThreadId)
  }, [loadThread, requestedThreadId, threadId])

  useEffect(() => {
    if (requestedThreadId || !newSessionRequest || newSessionRequest === lastNewSessionRequest.current) return
    lastNewSessionRequest.current = newSessionRequest
    void startNewThread()
  }, [newSessionRequest, requestedThreadId, startNewThread])

  // 自动滚到底
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // session 变化（新建 / 切换 / send 自动建）→ 刷新会话列表
  useEffect(() => {
    if (threadId) sessions.refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId])

  // 对话进行中本会话的 message_count 变化 → 偶尔刷一下列表预览
  // (节流: 只在第一条 user 消息发完时刷, 避免 delta 期间频繁拉)
  useEffect(() => {
    if (!threadId) return
    if (loading) return
    if (messages.length > 0 && messages.length % 2 === 0) {
      sessions.refresh()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading])

  const submit = async () => {
    if (!input.trim() || loading || historyLoading || submitBusyRef.current) return
    submitBusyRef.current = true
    const references = referencedFiles.length ? '\n\n本轮引用的本地原文件（JSON 路径列表）：\n' + JSON.stringify(referencedFiles.map(file => file.saved_path), null, 2) + '\n请直接读取这些指定文件，再按上述需求处理；这些路径已明确，无需用向量检索定位。若文件不存在或读取失败，请明确说明，不要猜测文件内容。' : ''
    const text = input.trim() + references
    try {
      await send(text, clearSubmittedDraft)
    } finally { submitBusyRef.current = false }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return

    // Enter 发送，Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  useEffect(() => {
    const activeThread = sessions.threads.find(item => item.thread_id === threadId)
    if (activeThread) onTitleChange?.(activeThread.title || '新对话')
  }, [threadId, sessions.threads, onTitleChange])

  return (
    <div className="flex flex-col h-full">
      {/* 消息列表 */}
      <div ref={scrollRef} className="dm-message-list">
        {configError && (
          <div className="text-xs p-3 bg-yellow-50 border border-yellow-200 rounded text-yellow-800">
            ⚠️ {configError}
            <br />
            请前往个人中心，填写当前模型供应商对应的 API Key。
          </div>
        )}

        {messages.map((m, i) => (
          <MessageBubble key={i} msg={m} onJump={onJumpToDoc} />
        ))}
        {loading && statusMessage && (
          <div className="px-1 text-xs text-slate-400">{statusMessage}</div>
        )}
      </div>

      {/* 输入区 */}
      <div className="dm-chat-composer">
        <div className="dm-chat-controls">
          <ComposerSelect className="dm-chat-model-control" label="模型" icon={<Icon name="bot" size={15} />} value={`${provider}|${modelName}`} disabled={settingsLoading} options={models.map(model => ({ value: `${model.provider}|${model.model_name}`, label: `${model.provider === 'deepseek' ? 'DeepSeek' : 'SiliconFlow'} · ${model.display_name}` }))} onChange={value => { const [nextProvider, nextModel] = value.split('|') as ['siliconflow' | 'deepseek', string]; onSettingsChange?.({ provider: nextProvider, model_name: nextModel }) }} />
          <button type="button" className="dm-file-reference-button" disabled={loading || !workspacePath} onClick={() => setShowFilePicker(true)} title="选择文件区文件"><Icon name="plus" size={15} />引用文件</button>
          <div className="dm-chat-access-control"><span className="dm-chat-access-caption">权限模式</span><ComposerSelect className="dm-chat-access-field" label="权限模式" icon={<Icon name={trustAgent ? 'check' : 'clock'} size={14} />} value={trustAgent ? 'full_access' : 'request_approval'} disabled={settingsLoading} options={[{ value: 'request_approval', label: '请求批准' }, { value: 'full_access', label: '完全访问' }]} onChange={value => onSettingsChange?.({ trust_agent: value === 'full_access' })} /></div>
        </div>
        {referencedFiles.length > 0 && <div className="max-w-3xl mx-auto mb-2 flex flex-wrap items-center gap-2">
          {referencedFiles.map(file => <button type="button" key={file.id} disabled={loading} title={file.saved_path} aria-label={`移除引用 ${file.filename}`} className="dm-reference-chip" data-file-type={file.filename.split('.').at(-1)?.toLowerCase()} onClick={() => setReferencedFiles(current => current.filter(item => item.id !== file.id))}>{file.filename} ×</button>)}
        </div>}
        <div className="dm-chat-composer-row">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onCompositionStart={() => { isComposingRef.current = true }}
            onCompositionEnd={() => { isComposingRef.current = false }}
            onKeyDown={onKey}
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
            rows={2}
            className="dm-chat-textarea"
          />
          {loading ? (
            <button
              type="button"
              onClick={cancel}
              className="dm-chat-stop"
              aria-label="停止生成"
              title="停止生成"
            >
              <Icon name="stop" size={18} />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              aria-label="发送消息"
              title="发送消息"
              disabled={!input.trim() || historyLoading}
              className="dm-chat-send"
            >
              <Icon name="send" size={18} />
            </button>
          )}
        </div>
      </div>

      {showFilePicker && <FileReferencePicker workspacePath={workspacePath} selected={referencedFiles} onClose={() => setShowFilePicker(false)} onConfirm={files => { setReferencedFiles(files); setShowFilePicker(false) }} />}

      {/* Permission 确认对话框 */}
      {pendingTool && (
        <PermissionDialog
          pending={pendingTool}
          onDecide={submitPermission}
        />
      )}
    </div>
  )
}


function ComposerSelect({ className, label, icon, value, disabled, options, onChange }: {
  className: string
  label: string
  icon: ReactNode
  value: string
  disabled: boolean
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const selected = options.findIndex(option => option.value === value)
  const expanded = open && !disabled && options.length > 0

  useEffect(() => {
    if (!expanded) return
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [expanded])

  useEffect(() => {
    if (expanded) document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: 'nearest' })
  }, [expanded, active, id])

  const choose = (index: number) => {
    if (options[index] && options[index].value !== value) onChange(options[index].value)
    setOpen(false)
    trigger.current?.focus()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false); return }
    if (event.key === 'Tab') { setOpen(false); return }
    if (!options.length) return
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown' || event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      if (!expanded) { setActive(Math.max(0, selected)); setOpen(true); return }
      setActive(current => event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length)
    } else if (expanded && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault()
      choose(active)
    }
  }

  return (
    <div ref={root} className={`dm-composer-select ${className}`} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false) }}>
      <button ref={trigger} type="button" className="dm-composer-select-trigger" role="combobox" aria-label={label} aria-haspopup="listbox" aria-expanded={expanded} aria-controls={expanded ? id : undefined} aria-activedescendant={expanded ? `${id}-${active}` : undefined} disabled={disabled || !options.length} onKeyDown={onKeyDown} onClick={() => { setActive(Math.max(0, selected)); setOpen(!expanded) }}>
        {icon}<span className="dm-composer-select-value">{options[selected]?.label || value}</span><span className={`dm-composer-select-arrow${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={12} /></span>
      </button>
      {expanded && <div id={id} role="listbox" aria-label={label} className="dm-composer-select-menu">
        {options.map((option, index) => <div key={option.value} id={`${id}-${index}`} role="option" aria-selected={option.value === value} className={`dm-composer-select-option${active === index ? ' is-active' : ''}`} onPointerMove={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(index)}><span>{option.label}</span><span className="dm-composer-select-check">{option.value === value && <Icon name="check" size={15} />}</span></div>)}
      </div>}
    </div>
  )
}


// ============== Permission 确认对话框 ==============

function PermissionDialog({
  pending,
  onDecide,
}: {
  pending: ApprovalPayload
  onDecide: (decision: 'deny' | 'allow') => Promise<void>
}) {
  const { name, args, reason, paths = [] } = pending
  const arguments_str = JSON.stringify(args)
  const icon = TOOL_ICONS[name] || '⚠️'

  // 参数解析展示
  let argsPretty = arguments_str
  try {
    argsPretty = JSON.stringify(JSON.parse(arguments_str || '{}'), null, 2)
  } catch {
    // 保持原样
  }

  // 描述 (按工具名定制)
  const descriptions: Record<string, string> = {
    write_file: '✏️ 写新文件到工作区',
    add_to_kb: '📥 把文件加入知识库',
    delete_file: '🗑️ 从工作区删除文件 (不可撤销!)',
  }
  const description = descriptions[name] || `执行 ${name}`
  const accessLabels = { read: '读取', write: '写入', delete: '删除' }

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-lg shadow-2xl border border-slate-200 max-w-md w-full mx-4 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2">
            <span className="text-lg">{icon}</span>
            <div className="font-semibold text-slate-800">
              {reason === 'external_path' ? 'Agent 请求访问项目外路径' : 'AI 想要执行操作'}
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-1">{description}</div>
        </div>

        <div className="px-4 py-3 space-y-2">
          <div className="text-xs font-semibold text-slate-600">工具: <code className="font-mono text-slate-800">{name}</code></div>
          {paths.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-slate-600 mb-1">
                {reason === 'external_path' ? '需要授权的目标路径:' : '操作路径:'}
              </div>
              <div className="space-y-1">
                {paths.map((item, index) => (
                  <div key={`${item.argument}-${item.path}-${index}`} className="bg-amber-50 border border-amber-200 rounded p-2">
                    <div className="text-xs font-medium text-amber-800">{accessLabels[item.access]}</div>
                    <code className="block mt-1 text-xs text-slate-800 break-all">{item.path}</code>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <div className="text-xs font-semibold text-slate-600 mb-1">参数:</div>
            <pre className="bg-slate-50 border border-slate-200 rounded p-2 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-words max-h-40">
              {argsPretty || '(无)'}
            </pre>
          </div>
          {name === 'delete_file' && (
            <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
              ⚠️ 删除操作不可撤销，请确认文件名正确。
            </div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 space-y-1.5">
          <button
            onClick={() => onDecide('allow')}
            className="w-full px-3 py-2 text-sm bg-slate-800 hover:bg-slate-900 text-white rounded-md font-medium"
          >
            ✓ 允许这次
          </button>
          <button
            onClick={() => onDecide('deny')}
            className="w-full px-3 py-2 text-sm bg-white hover:bg-red-50 text-red-700 border border-red-200 rounded-md"
          >
            ✗ 拒绝
          </button>
        </div>
      </div>
    </div>
  )
}


function MessageBubble({
  msg,
  onJump,
}: {
  msg: ChatMessage
  onJump?: (id: string) => void
}) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] px-3 py-2 bg-slate-800 text-white rounded-lg text-sm whitespace-pre-wrap">
          {msg.content}
        </div>
      </div>
    )
  }

  const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0
  const hasContent = msg.content && msg.content.trim().length > 0
  const isEmpty = !hasContent && !hasToolCalls && !msg.error

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-2 w-full">
        {/* 工具气泡 (Agent 调用工具的可视化) */}
        {hasToolCalls && msg.tool_calls!.map((tc) => (
          <ToolCallBubble key={tc.id} tc={tc} onJumpToDoc={onJump} />
        ))}

        {/* 文本内容气泡 */}
        {hasContent && (
          <div className="px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
            {msg.content}
          </div>
        )}

        {/* 空状态 (LLM 还没开始输出, 也没调工具) */}
        {isEmpty && (
          <div className="px-3 py-2 text-xs text-slate-400 italic">
            思考中...
          </div>
        )}

        {/* 错误 */}
        {msg.error && (
          <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
            ❌ {msg.error}
          </div>
        )}

        {msg.artifact_ids && msg.artifact_ids.length > 0 && (
          <div className="space-y-1">
            {msg.artifact_ids.map((artifactId) => (
              <a
                key={artifactId}
                href={apiUrl(`/api/artifacts/${encodeURIComponent(artifactId)}/download`)}
                className="block px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-md text-xs text-emerald-800"
              >
                ↓ 下载 Agent 生成文件
              </a>
            ))}
          </div>
        )}

        {/* 兼容: 旧 session 持久化的 citations (阶段 2 RAG 引用), 新 session 通过 tool_call 展示 */}
        {msg.citations && msg.citations.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs text-slate-400 px-1">引用来源:</div>
            {msg.citations.map((c, i) => (
              <button
                key={c.doc_id + c.chunk_index}
                onClick={() => onJump?.(c.doc_id)}
                className="block w-full text-left px-3 py-1.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md text-xs text-slate-600"
              >
                <span className="font-medium text-slate-700">
                  [来源 {i + 1}]
                </span>{' '}
                <span className="text-slate-500">📄 {c.doc_filename}</span>
                <span className="ml-1 text-slate-400">
                  · 第 {c.chunk_index + 1} 段
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


// ============== 工具调用可视化 ==============

const TOOL_ICONS: Record<string, string> = {
  list_workspace_files: '📚',
  read_file: '📖',
  search_kb: '🔍',
  get_workspace_info: 'ℹ️',
  list_directory: '📂',
}

function summarizeArgs(argsStr: string): string {
  if (!argsStr || !argsStr.trim()) return '()'
  try {
    const parsed = JSON.parse(argsStr)
    const entries = Object.entries(parsed)
    if (entries.length === 0) return '()'
    return (
      '(' +
      entries
        .map(([k, v]) => {
          const vstr = typeof v === 'string' ? `"${v.length > 30 ? v.slice(0, 30) + '…' : v}"` : String(v)
          return `${k}: ${vstr}`
        })
        .join(', ') +
      ')'
    )
  } catch {
    return argsStr.length > 40 ? argsStr.slice(0, 40) + '…' : argsStr
  }
}

function summarizeResult(name: string, result: any): string {
  if (result === undefined) return '⏳ 执行中…'
  if (!result || result.ok === false) {
    return `❌ ${result?.error || 'error'}`
  }
  switch (name) {
    case 'list_workspace_files':
      return `✅ ${result.count} 个文件`
    case 'read_file':
      return `✅ ${result.total_chars} 字${result.truncated ? ' (截断)' : ''}`
    case 'search_kb':
      return `✅ ${result.count} 个片段`
    case 'get_workspace_info':
      return `✅ ${result.indexed_files_count} 个已入库`
    case 'list_directory':
      return `✅ ${result.count} 项`
    default:
      return '✅'
  }
}

function ToolCallBubble({
  tc,
  onJumpToDoc,
}: {
  tc: ToolCallView
  onJumpToDoc?: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const pending = tc.result === undefined
  const failed = !pending && tc.result?.ok === false

  const icon = TOOL_ICONS[tc.name] || '🔧'
  const argsPreview = summarizeArgs(tc.arguments_str)
  const resultPreview = summarizeResult(tc.name, tc.result)

  const borderClass = pending
    ? 'border-slate-200 bg-slate-50/50'
    : failed
      ? 'border-red-200 bg-red-50/40'
      : 'border-emerald-200 bg-emerald-50/40'

  return (
    <div className={`text-xs border rounded-md ${borderClass}`}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-2.5 py-1.5 flex items-start gap-2 hover:bg-black/[0.03] transition-colors"
      >
        <span className="shrink-0 mt-0.5">{icon}</span>
        <div className="flex-1 min-w-0 font-mono leading-snug">
          <span className="font-semibold text-slate-700">{tc.name}</span>
          <span className="text-slate-500">{argsPreview}</span>
          {' '}
          <span className="text-slate-400">→</span>{' '}
          <span
            className={
              pending
                ? 'text-slate-400'
                : failed
                  ? 'text-red-700'
                  : 'text-emerald-700'
            }
          >
            {resultPreview}
          </span>
        </div>
        <span className="shrink-0 text-slate-400 text-[10px] mt-1">
          {expanded ? '▼' : '▶'}
        </span>
      </button>

      {expanded && (
        <div className="px-2.5 pb-2 border-t border-slate-100 pt-2 space-y-2 font-mono text-[11px]">
          <div>
            <div className="text-slate-400 mb-0.5">arguments:</div>
            <pre className="bg-white border border-slate-200 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-words">
              {tc.arguments_str || '{}'}
            </pre>
          </div>
          {tc.result !== undefined && (
            <div>
              <div className="text-slate-400 mb-0.5">result:</div>
              <pre className="bg-white border border-slate-200 rounded p-1.5 overflow-auto max-h-64 whitespace-pre-wrap break-words">
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          )}
          {/* search_kb 命中时, 提供文档跳转 */}
          {tc.name === 'search_kb' &&
            tc.result?.ok &&
            Array.isArray(tc.result.hits) &&
            tc.result.hits.length > 0 && (
              <div className="pt-1 border-t border-slate-100">
                <div className="text-slate-400 mb-1">跳转到原文档:</div>
                {tc.result.hits.map((h: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => h.doc_id && onJumpToDoc?.(h.doc_id)}
                    className="block w-full text-left px-2 py-1 mb-0.5 bg-white hover:bg-slate-100 border border-slate-200 rounded text-[11px]"
                    disabled={!h.doc_id}
                  >
                    📄 {h.doc_filename} · {Math.round((h.similarity || 0) * 100)}% · 第 {(h.chunk_index ?? 0) + 1} 段
                  </button>
                ))}
              </div>
            )}
        </div>
      )}
    </div>
  )
}
