import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChat, type ChatMessage, type ProgressStep } from '../hooks/useChat'
import type { WorkspaceFile } from '../hooks/useWorkspaceFiles'
import { useChatDraft } from '../hooks/useChatDraft'
import { useSessions } from '../hooks/useSessions'
import { apiUrl } from '../api/client'
import type { ApprovalPayload } from '../api/types'
import { FileReferencePicker } from './FileReferencePicker'
import { Icon } from './Icon'

interface Props {
  initialReference?: WorkspaceFile
  onReferenceApplied?: () => void
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

function ConversationPanel({ initialReference, onReferenceApplied, onJumpToDoc, onTitleChange, workspacePath, projectId, newSessionRequest = 0, trustAgent = false, provider = 'siliconflow', modelName = 'Qwen/Qwen3.5-4B', requestedThreadId = null, models = [], settingsLoading = false, onSettingsChange }: Props) {
  const {
    messages, loading, threadId, pendingTool, send, cancel,
    loadThread, startNewThread, submitPermission, configError,
  } = useChat(workspacePath, projectId, trustAgent ? 'full_access' : 'request_approval', provider, modelName)
  const sessions = useSessions(workspacePath, projectId)
  const conversationId = requestedThreadId || threadId
  const { input, setInput, referencedFiles, setReferencedFiles, clearSubmittedDraft } = useChatDraft(workspacePath, projectId, conversationId || `new:${newSessionRequest}`, !conversationId)
  const referenceApplied = useRef(false)
  useEffect(() => {
    if (!initialReference || referenceApplied.current) return
    referenceApplied.current = true
    setReferencedFiles(current => current.some(file => file.saved_path === initialReference.saved_path) ? current : [...current, initialReference])
    onReferenceApplied?.()
  }, [initialReference, onReferenceApplied, setReferencedFiles])
  const historyLoading = Boolean(requestedThreadId && requestedThreadId !== threadId)
  const [showFilePicker, setShowFilePicker] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const followBottomRef = useRef(true)
  const lastScrollTop = useRef(0)
  const [showLatest, setShowLatest] = useState(false)
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

  const scrollToLatest = () => {
    followBottomRef.current = true
    setShowLatest(false)
    const list = scrollRef.current
    if (list) {
      list.scrollTop = list.scrollHeight
      lastScrollTop.current = list.scrollTop
    }
  }

  useLayoutEffect(() => {
    if (followBottomRef.current) scrollToLatest()
  }, [messages])

  useEffect(() => {
    const content = contentRef.current
    if (!content) return
    const observer = new ResizeObserver(() => {
      if (followBottomRef.current) scrollToLatest()
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [])

  const pauseFollowing = () => {
    followBottomRef.current = false
    setShowLatest(true)
  }

  const onMessageScroll = () => {
    const list = scrollRef.current
    if (!list) return
    if (list.scrollTop < lastScrollTop.current - 1) pauseFollowing()
    else if (list.scrollHeight - list.scrollTop - list.clientHeight <= 24 && list.scrollTop > lastScrollTop.current) {
      followBottomRef.current = true
      setShowLatest(false)
    }
    lastScrollTop.current = list.scrollTop
  }

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
    scrollToLatest()
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
      <div ref={scrollRef} className="dm-message-list" onScroll={onMessageScroll}
        onWheelCapture={event => { if (event.deltaY < 0) pauseFollowing() }}
        onClickCapture={event => {
          if ((event.target as HTMLElement).closest('summary,.dm-agent-progress-toggle')) pauseFollowing()
        }}>
        <div ref={contentRef} className="dm-message-content">
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
        </div>
      </div>
      {showLatest && <div className="dm-chat-scroll-tools"><button type="button" onClick={scrollToLatest}>回到最新内容</button></div>}

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
    delete_file: '将文件或文件夹移入项目回收目录',
  }
  const description = descriptions[name] || `执行 ${name}`
  const accessLabels = { read: '读取', write: '写入', delete: '删除' }

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-lg shadow-2xl border border-slate-200 max-w-md w-full mx-4 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2">
            <Icon name="bot" size={18} />
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
              目标将移入项目回收目录，可恢复；请确认目标路径。
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


const markdownComponents: Components = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: ({ node: _node, ...props }) => (
    <div className="dm-markdown-table" role="region" aria-label="表格" tabIndex={0}>
      <table {...props} />
    </div>
  ),
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

  const hasProgress = Boolean(msg.progress?.length || msg.tool_calls?.length || msg.status)
  const hasContent = msg.content && msg.content.trim().length > 0
  const hasInlineAnswer = msg.progress?.some(step => step.id === msg.answer_step_id)
  const isEmpty = !hasContent && !hasProgress && !msg.error

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] min-w-0 space-y-2 w-full">
        {hasProgress && <ExecutionProgress msg={msg} onJump={onJump} />}

        {/* 文本内容气泡 */}
        {hasContent && !hasInlineAnswer && (
          <div className="dm-markdown px-3 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {msg.content}
            </ReactMarkdown>
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
            {msg.error}
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


const TOOL_LABELS: Record<string, string> = {
  list_workspace_files: '扫描目录', search_workspace_files: '按名称查找文件',
  get_workspace_file_info: '检查文件信息', read_text_file: '读取文本',
  search_text_in_files: '搜索文件内容', search_workspace_documents: '检索相关资料',
  write_text_file: '写入文本', replace_text_in_file: '替换文本',
  create_folder: '创建文件夹', copy_file: '复制文件', move_file: '移动文件',
  rename_file: '重命名文件', delete_file: '移入回收目录',
  read_docx: '读取 Word 文档', read_pdf: '读取 PDF', read_xlsx: '读取 Excel',
  create_docx: '生成 Word 文档', create_pdf: '生成 PDF', create_xlsx: '生成 Excel',
  edit_docx: '编辑 Word 文档', edit_pdf_pages: '编辑 PDF 页面', edit_xlsx: '编辑 Excel',
  convert_docx: '转换 Word 文档', convert_xlsx: '转换 Excel',
  render_docx: '渲染 Word 文档', validate_docx: '验证 Word 文档', validate_xlsx: '验证 Excel',
  extract_pdf_images: '提取 PDF 图片', extract_pdf_tables: '提取 PDF 表格',
}

function progressLabel(step: ProgressStep): string {
  const action = step.tool ? TOOL_LABELS[step.tool.name] || step.tool.name : step.title.replace(/^正在/, '')
  const prefixes = { running: '正在', pending: '等待处理：', completed: '已结束：', failed: '失败：', denied: '未获批准：',
    awaiting_approval: '等待审批：', cancelled: '已取消：', interrupted: '结果待核实：' }
  let target = ''
  if (step.tool) {
    try {
      const args = JSON.parse(step.tool.arguments_str)
      const path = args.relative_path || args.output_path || args.source_path
      if (typeof path === 'string' && path !== '.') target = path.split(/[\\/]/).filter(Boolean).pop() || path
    } catch { /* 参数原文仍可在详情中查看。 */ }
  }
  return `${prefixes[step.state]}${action}${target ? ` · ${target}` : ''}`
}

function resultSummary(step: ProgressStep): string {
  const result = step.tool?.result
  if (!result) return ''
  if (result.status === 'denied' || result.ok === false) {
    return typeof result.error === 'string' ? result.error : result.error?.message || '工具未完成'
  }
  const data = result.data ?? result
  if (Array.isArray(data)) return `${data.length} 项`
  if (Array.isArray(data.files)) return `${data.files.length} 个候选文件`
  if (data.truncated) return '已返回部分内容'
  return ''
}

function ExecutionProgress({ msg, onJump }: { msg: ChatMessage; onJump?: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const terminal = Boolean(msg.status && !['running', 'awaiting_approval'].includes(msg.status))
  useLayoutEffect(() => { if (terminal) setExpanded(false) }, [terminal])
  const detailsId = useId()
  const steps: ProgressStep[] = msg.progress || (msg.tool_calls || []).map(tool => ({
    id: `tool:${tool.id}`, kind: 'tool', title: tool.name, tool,
    state: tool.result === undefined ? 'interrupted' : tool.result.status === 'denied' ? 'denied'
      : tool.result.ok === false ? 'failed' : 'completed',
  }))
  const active = [...steps].reverse().find(step => step.state === 'running' || step.state === 'awaiting_approval')
  const tools = steps.filter(step => step.kind === 'tool')
  const failed = tools.filter(step => step.state === 'failed').length
  const denied = tools.filter(step => step.state === 'denied').length
  const waiting = msg.status === 'awaiting_approval'
  const running = msg.status === 'running'
  const hasHistory = tools.length > 0 || steps.some(step => step.kind === 'model' && step.content && step.id !== msg.answer_step_id)
  const showHeading = running || waiting || msg.status !== 'completed' || hasHistory
  const title = waiting ? '等待你的审批' : running ? expanded ? '正在处理' : active ? progressLabel(active) : '正在处理请求'
    : msg.status === 'cancelled' ? '本轮已取消' : msg.status === 'failed' ? '本轮执行出错'
      : msg.status === 'stopped' ? '已停止接收，执行结果待核实' : '执行记录'
  const summary = [tools.length ? `${tools.length} 项工具调用` : '', failed ? `${failed} 项失败` : '',
    denied ? `${denied} 项未获批准` : ''].filter(Boolean).join(' · ')
  return (
    <div className="dm-agent-progress" data-state={msg.status || 'completed'}>
      {showHeading && <button type="button" className="dm-agent-progress-toggle" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded(value => !value)}>
        <span className={`dm-agent-progress-chevron${expanded ? ' is-open' : ''}`}><Icon name="chevron" size={13} /></span>
        <span className="dm-agent-progress-heading">
          <span className={running ? 'dm-agent-shimmer' : undefined} role="status">{title}</span>
          {summary && <span className="dm-agent-progress-count">{summary}</span>}
        </span>
      </button>}
      <div id={detailsId} className="dm-agent-timeline">
        {steps.map(step => {
          const answer = step.id === msg.answer_step_id
          const liveText = step.kind === 'model' && step.state === 'running'
          const visible = answer || liveText || (expanded && (step.kind === 'tool' || (step.kind === 'model' && Boolean(step.content))))
          return <div key={step.id} hidden={!visible} data-part-id={step.id} data-final={answer || undefined}>
            {step.kind === 'model' ? <div className="dm-agent-model-part">
              {step.content ? <div className="dm-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{step.content}</ReactMarkdown></div>
                : <span className={step.state === 'running' ? 'dm-agent-shimmer' : undefined}>{progressLabel(step)}</span>}
              {!answer && ['interrupted', 'cancelled'].includes(step.state) && <div className="dm-agent-draft-state">输出已中断，内容未完成。</div>}
            </div> : step.kind === 'tool' ? <ProgressStepDetail step={step} onJump={onJump} /> : null}
          </div>
        })}
      </div>
    </div>
  )
}

function ProgressStepDetail({ step, onJump }: { step: ProgressStep; onJump?: (id: string) => void }) {
  const label = progressLabel(step)
  const summary = resultSummary(step)
  const hasDetails = Boolean(step.content || step.tool)
  return (
    <details className="dm-agent-step" data-state={step.state}>
      <summary>
        <span className={step.state === 'running' ? 'dm-agent-shimmer' : undefined}>{label}</span>
        {summary && <span className="dm-agent-step-summary">{summary}</span>}
      </summary>
      {hasDetails && <div className="dm-agent-step-body">
        {step.content && <div className="dm-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{step.content}</ReactMarkdown></div>}
        {step.tool && <>
          <div className="dm-agent-step-caption">工具：{step.tool.name}</div>
          <div className="dm-agent-step-caption">调用参数</div>
          <pre>{step.tool.arguments_str || '{}'}</pre>
          {step.tool.result !== undefined && <>
            <div className="dm-agent-step-caption">实际返回</div>
            <pre>{JSON.stringify(step.tool.result, null, 2)}</pre>
          </>}
          {step.tool.name === 'search_kb' && Array.isArray(step.tool.result?.hits) && step.tool.result.hits.map((hit: any, i: number) => (
            <button key={i} type="button" disabled={!hit.doc_id} onClick={() => onJump?.(hit.doc_id)}>{hit.doc_filename} · 第 {(hit.chunk_index ?? 0) + 1} 段</button>
          ))}
        </>}
      </div>}
    </details>
  )
}
