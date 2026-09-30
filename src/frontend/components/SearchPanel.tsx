import { useState, type KeyboardEvent } from 'react'
import { useSearch, type SearchHit } from '../hooks/useSearch'

interface Props {
  onJumpToDoc: (docId: string) => void
}

export function SearchPanel({ onJumpToDoc }: Props) {
  const [input, setInput] = useState('')
  const { hits, loading, error, query, search, clear } = useSearch()

  const submit = () => {
    if (input.trim()) search(input.trim())
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') submit()
    if (e.key === 'Escape') {
      setInput('')
      clear()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* 输入栏 */}
      <div className="px-4 py-3 border-b border-slate-200">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
          🔍 文档关键词搜索
        </div>
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="问点什么... (回车搜索)"
            className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-slate-500"
          />
          <button
            onClick={submit}
            disabled={loading || !input.trim()}
            className="px-3 py-2 text-sm bg-slate-800 hover:bg-slate-900 disabled:bg-slate-300 text-white rounded-md transition-colors"
          >
            {loading ? '...' : 'Go'}
          </button>
        </div>
      </div>

      {/* 结果列表 */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="m-3 p-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded">
            {error.includes('loading')
              ? '⏳ AI 模型正在加载，首次约 5-10 分钟...'
              : `❌ ${error}`}
          </div>
        )}

        {!loading && !error && hits.length === 0 && query && (
          <div className="text-center py-8 px-4 text-sm text-slate-400">
            没有找到匹配的内容
          </div>
        )}

        {!query && hits.length === 0 && (
          <div className="text-center py-8 px-4 text-xs text-slate-400">
            在已上传的文档文本中查找关键词
          </div>
        )}

        {hits.map((hit) => (
          <HitCard key={hit.chunk_id} hit={hit} onJump={onJumpToDoc} />
        ))}
      </div>
    </div>
  )
}

function HitCard({ hit, onJump }: { hit: SearchHit; onJump: (id: string) => void }) {
  return (
    <button
      onClick={() => onJump(hit.doc_id)}
      className="w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-slate-100 transition-colors"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-medium text-slate-700 truncate flex-1">
          📄 {hit.doc_filename}
        </span>
        <span className="text-xs text-slate-500 font-mono">匹配 {hit.chunk_index + 1}</span>
      </div>
      <div className="text-xs text-slate-600 line-clamp-3 leading-relaxed">
        {hit.text}
      </div>
    </button>
  )
}
