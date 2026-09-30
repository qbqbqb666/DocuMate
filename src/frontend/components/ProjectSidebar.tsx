import { useEffect, useState } from 'react'
import type { ProjectSummary } from '../api/types'
import { useSessions } from '../hooks/useSessions'
import { Icon } from './Icon'

interface Props {
  projects: ProjectSummary[]
  activeThreadId: string | null
  resetKey: string
  onOpenThread: (project: ProjectSummary, threadId: string, title: string) => void
  onNewThread: (project: ProjectSummary) => void
  onDeleteThread: (threadId: string) => void
}

export function ProjectSidebar({ projects, activeThreadId, resetKey, onOpenThread, onNewThread, onDeleteThread }: Props) {
  return <div className="dm-project-tree"><div className="dm-project-tree-label">项目</div>{projects.map((project) => <ProjectGroup key={project.id} project={project} activeThreadId={activeThreadId} resetKey={resetKey} onOpenThread={onOpenThread} onNewThread={onNewThread} onDeleteThread={onDeleteThread} />)}</div>
}

function ProjectGroup({ project, activeThreadId, resetKey, onOpenThread, onNewThread, onDeleteThread }: Omit<Props, 'projects'> & { project: ProjectSummary }) {
  const sessions = useSessions(project.primary_path, project.id)
  const [collapsed, setCollapsed] = useState(false)
  const [menuId, setMenuId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    setMenuId(null)
    setEditingId(null)
  }, [resetKey])

  return <section className="dm-project-group">
    <div className="dm-project-row">
      <button className="dm-project-toggle" onClick={() => setCollapsed((value) => !value)} title={collapsed ? '展开项目' : '折叠项目'}><span className={collapsed ? '' : 'is-open'}>›</span><Icon name="folder" size={17} /><b>{project.name}</b></button>
      <button className="dm-project-add" onClick={() => onNewThread(project)} title={`在 ${project.name} 中新建对话`}><Icon name="plus" size={15} /></button>
    </div>
    {!collapsed && <div className="dm-project-threads">
      {sessions.loading && <p>正在读取…</p>}
      {!sessions.loading && sessions.threads.length === 0 && <p>暂无对话</p>}
      {sessions.threads.map((thread) => <div key={thread.thread_id} className={`dm-project-thread${activeThreadId === thread.thread_id ? ' is-active' : ''}`}>
        {editingId === thread.thread_id ? <form onSubmit={async (event) => { event.preventDefault(); if (await sessions.rename(thread.thread_id, draft)) setEditingId(null) }}><input autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => setEditingId(null)} /></form> : <button className="dm-project-thread-main" onClick={() => onOpenThread(project, thread.thread_id, thread.title)}><Icon name="message" size={14} /><span>{thread.title}</span></button>}
        <button className="dm-thread-more" onClick={() => setMenuId(menuId === thread.thread_id ? null : thread.thread_id)} title="对话操作"><Icon name="more" size={15} /></button>
        {menuId === thread.thread_id && <div className="dm-thread-menu"><button onClick={() => { setDraft(thread.title); setEditingId(thread.thread_id); setMenuId(null) }}>重命名</button><button className="is-danger" onClick={async () => { setMenuId(null); if (window.confirm(`删除对话“${thread.title}”？\n删除后将从列表隐藏。`) && await sessions.remove(thread.thread_id)) onDeleteThread(thread.thread_id) }}>删除</button></div>}
      </div>)}
      {sessions.error && <p className="dm-inline-error">{sessions.error}</p>}
    </div>}
  </section>
}
