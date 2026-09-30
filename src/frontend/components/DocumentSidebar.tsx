import type { DocumentMeta } from '../hooks/useDocuments'
import { Icon } from './Icon'

interface Props {
  documents: DocumentMeta[]
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
  recentOnly: boolean
  onShowAll: () => void
  onToggleRecent: () => void
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return '刚刚导入'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

export function DocumentSidebar({ documents, selectedId, onSelect, loading, recentOnly, onShowAll, onToggleRecent }: Props) {
  const visibleDocuments = recentOnly
    ? [...documents].sort((a, b) => +new Date(b.uploaded_at) - +new Date(a.uploaded_at)).slice(0, 5)
    : documents

  return (
    <div className="dm-doc-sidebar">
      <div className="dm-doc-heading"><span>文件</span></div>
      <button className={`dm-folder-row ${!recentOnly ? 'is-active' : ''}`} onClick={onShowAll}><Icon name="folder" size={19} /><span>全部文件</span><span className="count">{loading ? '…' : documents.length}</span></button>
      <div className="dm-document-list">
        {loading && <div className="dm-doc-empty">正在读取文件区…</div>}
        {!loading && visibleDocuments.length === 0 && <div className="dm-doc-empty">{recentOnly ? '还没有最近导入的资料' : <>文件夹还是空的<br />拖入一份资料开始吧</>}</div>}
        {visibleDocuments.length > 0 && <div className="dm-tree-folder-title"><span>›</span><Icon name="folder" size={16} />{recentOnly ? '最近导入' : '学习资料'}<span className="dm-tree-count">{visibleDocuments.length}</span></div>}
        <div className="dm-tree-files">{visibleDocuments.map((doc) => (
          <button key={doc.id} onClick={() => onSelect(doc.id)} className={`dm-document-row ${selectedId === doc.id ? 'is-selected' : ''}`}>
            <span className="file-type"><Icon name="file" size={20} /></span>
            <span className="min-w-0 flex-1"><span className="filename">{doc.filename}</span><span className="metadata">{doc.char_count.toLocaleString()} 字 · {formatTime(doc.uploaded_at)}</span></span>
          </button>
        ))}</div>
        {documents.length > 0 && <button className={`dm-recent-row ${recentOnly ? 'is-active' : ''}`} onClick={onToggleRecent}><Icon name="clock" size={16} />{recentOnly ? '查看全部文件' : '最近导入'}</button>}
      </div>
    </div>
  )
}
