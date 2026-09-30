import { useState } from 'react'
import { useWorkspace } from '../hooks/useWorkspace'

interface Props {
  onPicked: () => void
}

export function WorkspacePicker({ onPicked }: Props) {
  const { pickAndSwitch, switchTo, error } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')
  const hasFolderPicker = Boolean(window.documate?.pickFolder)

  const handlePick = async () => {
    setBusy(true)
    const ok = await pickAndSwitch()
    setBusy(false)
    if (ok) onPicked()
  }

  const handlePath = async () => {
    if (!path.trim()) return
    setBusy(true)
    const ok = await switchTo(path.trim())
    setBusy(false)
    if (ok) onPicked()
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-200">
      <div className="max-w-md text-center space-y-6 px-8">
        <div className="text-7xl">📂</div>
        <div className="space-y-2">
          <h1 className="text-3xl font-bold text-slate-800">欢迎使用 DocuMate</h1>
          <p className="text-slate-600 leading-relaxed">
            选一个文件夹作为你的工作区<br />
            AI 上传的文档、生成的新文档、知识库都会放在这里
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4 text-left text-xs text-slate-600 space-y-1">
          <div className="font-semibold text-slate-700 mb-1">工作区结构：</div>
          <div className="font-mono">
            <div>📁 你选的文件夹/</div>
            <div className="pl-4">📄 你的原文件（PDF / DOCX 保留原名）</div>
            <div className="pl-4">✨ AI 生成的新文件（直接放这里）</div>
            <div className="pl-4 text-slate-400">.documate/ — 内部数据（系统隐藏）</div>
          </div>
          <div className="text-[10px] text-slate-400 mt-2">
            像 Cursor / Claude Code 一样直接在你的文件夹工作，不会乱放杂物
          </div>
        </div>

        {hasFolderPicker ? (
          <button
            onClick={handlePick}
            disabled={busy}
            className="w-full px-6 py-3 bg-slate-800 hover:bg-slate-900 disabled:bg-slate-400 text-white font-medium rounded-lg shadow-sm transition-colors"
          >
            {busy ? '处理中...' : '📁 选择工作区文件夹'}
          </button>
        ) : (
          <div className="space-y-2 text-left">
            <label className="block text-xs font-semibold text-slate-600" htmlFor="workspace-path">
              工作区绝对路径
            </label>
            <div className="flex gap-2">
              <input
                id="workspace-path"
                value={path}
                onChange={(event) => setPath(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void handlePath() }}
                placeholder="/Users/name/Documents/DocuMate"
                className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-600"
              />
              <button
                onClick={handlePath}
                disabled={busy || !path.trim()}
                className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
              >
                {busy ? '处理中' : '使用'}
              </button>
            </div>
            <p className="text-[11px] text-slate-400">浏览器无法直接读取本地文件夹，请输入后端所在电脑上的路径。</p>
          </div>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3 text-left">
            ❌ {error}
          </div>
        )}

        <div className="text-xs text-slate-400">
          💡 推荐：在桌面新建一个 &quot;DocuMate 工作区&quot; 文件夹，专门放工作内容
        </div>
      </div>
    </div>
  )
}
