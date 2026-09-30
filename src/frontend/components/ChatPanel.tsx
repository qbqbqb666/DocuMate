import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useChat, type ChatMessage, type ToolCallView } from '../hooks/useChat'
import { useSessions } from '../hooks/useSessions'
import { apiUrl } from '../api/client'
import type { ApprovalPayload } from '../api/types'

interface Props {
  onJumpToDoc?: (docId: string) => void
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

function formatRelativeTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffMin < 60 * 24) return `${Math.floor(diffMin / 60)} 小时前`
  return d.toLocaleDateString('zh-CN')
}

export function ChatPanel({ onJumpToDoc, workspacePath, projectId, newSessionRequest = 0, trustAgent = false, provider = 'siliconflow', modelName = 'Qwen/Qwen3.5-4B', requestedThreadId = null, models = [], settingsLoading = false, onSettingsChange }: Props) {
  const {
    messages, loading, threadId, pendingTool, statusMessage, send, cancel, clear,
    loadThread, startNewThread, submitPermission, configError,
  } = useChat(workspacePath, projectId, trustAgent ? 'full_access' : 'request_approval', provider, modelName)
  const sessions = useSessions(workspacePath, projectId)
  const [input, setInput] = useState('')
  const [showSessionMenu, setShowSessionMenu] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastNewSessionRequest = useRef(0)
  const isComposingRef = useRef(false)

  useEffect(() => {
    if (requestedThreadId && requestedThreadId !== threadId) void loadThread(requestedThreadId)
  }, [loadThread, requestedThreadId, threadId])

  useEffect(() => {
    if (!newSessionRequest || newSessionRequest === lastNewSessionRequest.current) return
    lastNewSessionRequest.current = newSessionRequest
    void startNewThread()
  }, [newSessionRequest, startNewThread])

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

  const submit = () => {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    send(text)
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return

    // Enter 发送，Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const handleSwitchSession = async (id: string) => {
    setShowSessionMenu(false)
    if (id === threadId) return
    await loadThread(id)
  }

  const handleNewSession = async () => {
    setShowSessionMenu(false)
    await startNewThread()
  }

  const currentSessionLabel = threadId
    ? (sessions.threads.find((item) => item.thread_id === threadId)?.preview || `会话 ${threadId.slice(0, 6)}`)
    : '未开始'

  return (
    <div className="flex flex-col h-full">
      {/* 顶部：标题 + 会话切换 + clear */}
      <div className="dm-chat-panel-header relative">
        <div className="flex items-center justify-between mb-1">
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              💬 Agent 对话
            </div>
            <div className="text-xs text-slate-400 mt-0.5 truncate" title={currentSessionLabel}>
              {threadId
                ? `📑 ${currentSessionLabel}`
                : 'LLM 自主调用工具读写工作区'}
            </div>
          </div>
          <div className="flex items-center gap-1 ml-2 shrink-0">
            <button
              onClick={() => setShowSessionMenu((v) => !v)}
              className="text-xs text-slate-500 hover:text-slate-700 px-2 py-1 border border-slate-200 rounded hover:bg-slate-50"
              title="切换会话"
            >
              📑 ▾
            </button>
            {messages.length > 0 && (
              <button
                onClick={clear}
                className="text-xs text-slate-500 hover:text-slate-700 px-1"
                title="清空当前对话视图（不删除会话存档）"
              >
                清空
              </button>
            )}
          </div>
        </div>

        {/* 会话切换下拉菜单 */}
        {showSessionMenu && (
          <>
            <div
              className="fixed inset-0 z-30"
              onClick={() => setShowSessionMenu(false)}
            />
            <div className="absolute left-3 right-3 top-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-40 overflow-hidden">
              <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                <span>历史会话 ({sessions.threads.length})</span>
                <button
                  onClick={handleNewSession}
                  className="text-[11px] font-medium text-slate-700 hover:text-slate-900 normal-case tracking-normal"
                >
                  ＋ 新会话
                </button>
              </div>
              <div className="max-h-72 overflow-y-auto">
                {sessions.threads.length === 0 ? (
                  <div className="px-3 py-3 text-xs text-slate-400 text-center">
                    暂无历史<br />
                    <span className="text-[10px]">发送第一条消息会自动创建会话</span>
                  </div>
                ) : (
                  sessions.threads.map((s) => (
                    <div
                      key={s.thread_id}
                      className={`
                        w-full text-left px-3 py-2 text-xs border-b border-slate-50 transition-colors flex items-start gap-2 cursor-pointer
                        ${threadId === s.thread_id
                          ? 'bg-slate-100'
                          : 'hover:bg-slate-50'}
                      `}
                      onClick={() => handleSwitchSession(s.thread_id)}
                    >
                      <span className="w-3 text-slate-400 mt-0.5 shrink-0">
                        {threadId === s.thread_id ? '✓' : ''}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-slate-700 truncate" title={s.preview}>
                          {s.preview || '(空对话)'}
                        </div>
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {s.message_count} 条 · {formatRelativeTime(s.updated_at)}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* 消息列表 */}
      <div ref={scrollRef} className="dm-message-list">
        {configError && (
          <div className="text-xs p-3 bg-yellow-50 border border-yellow-200 rounded text-yellow-800">
            ⚠️ {configError}
            <br />
            请前往个人中心，填写当前模型供应商对应的 API Key。
          </div>
        )}

        {!configError && messages.length === 0 && (
          <div className="text-center py-8 px-2 text-xs text-slate-400 leading-relaxed">
            问点跟你文档相关的问题
            <br />
            比如：&quot;这份合同的违约责任写在哪？&quot;
            <br />
            &quot;这周报里 Q3 的目标是什么？&quot;
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
          <label><span>模型</span><select value={`${provider}|${modelName}`} disabled={settingsLoading} onChange={(event) => { const [nextProvider, nextModel] = event.target.value.split('|') as ['siliconflow' | 'deepseek', string]; onSettingsChange?.({ provider: nextProvider, model_name: nextModel }) }}>{models.map((model) => <option key={`${model.provider}|${model.model_name}`} value={`${model.provider}|${model.model_name}`}>{model.provider === 'deepseek' ? 'DeepSeek' : 'SiliconFlow'} · {model.display_name}</option>)}</select></label>
          <label className="dm-chat-access-control"><span>权限模式</span><select value={trustAgent ? 'full_access' : 'request_approval'} disabled={settingsLoading} onChange={(event) => onSettingsChange?.({ trust_agent: event.target.value === 'full_access' })}><option value="request_approval">请求批准</option><option value="full_access">完全访问</option></select></label>
        </div>
        <div className="flex gap-2 max-w-3xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onCompositionStart={() => { isComposingRef.current = true }}
            onCompositionEnd={() => { isComposingRef.current = false }}
            onKeyDown={onKey}
            placeholder="问点什么... (Enter 发送，Shift+Enter 换行)"
            rows={2}
            className="dm-chat-textarea"
          />
          {loading ? (
            <button
              onClick={cancel}
              className="dm-chat-stop"
            >
              停
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!input.trim()}
              className="dm-chat-send"
            >
              发送
            </button>
          )}
        </div>
      </div>

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
