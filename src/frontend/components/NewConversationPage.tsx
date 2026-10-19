import { useEffect, useId, useRef, useState } from 'react'
import type { ProjectSummary } from '../api/types'
import { Icon } from './Icon'

interface Props {
  projects: ProjectSummary[]
  projectsLoading: boolean
  projectsError: string | null
  onCancel: () => void
  onUseProject: (project: ProjectSummary) => Promise<void>
  onCreateProject: (name: string, folders: string[]) => Promise<void>
}

export function NewConversationPage({ projects, projectsLoading, projectsError, onCancel, onUseProject, onCreateProject }: Props) {
  const [creating, setCreating] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [folders, setFolders] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const picker = useRef<HTMLDivElement>(null)
  const pickerButton = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const selected = projects.find(project => project.id === selectedId)
  const filtered = projects.filter(project => `${project.name} ${project.primary_path}`.toLowerCase().includes(query.trim().toLowerCase()))

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: PointerEvent) => { if (!picker.current?.contains(event.target as Node)) setMenuOpen(false) }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menuOpen])

  const addFolder = async () => {
    const path = await window.documate?.pickFolder({ title: '选择项目可访问文件夹', buttonLabel: '添加文件夹' })
    if (path) setFolders((items) => items.includes(path) ? items : [...items, path])
  }
  const submit = async () => {
    if (busy) return
    setError(null); setBusy(true)
    try {
      if (creating) {
        if (!name.trim()) throw new Error('请输入项目名称')
        if (!folders.length) throw new Error('请至少添加一个可访问文件夹')
        await onCreateProject(name.trim(), folders)
      } else {
        if (!selected) throw new Error('请选择项目')
        await onUseProject(selected)
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false) }
  }
  return <section className="dm-new-conversation-page">
    <div className="dm-new-conversation-form">
      <header><button type="button" className="dm-icon-button" aria-label={creating ? '返回项目选择' : '取消新对话'} disabled={busy} onClick={() => { if (creating) { setCreating(false); setError(null) } else onCancel() }}><Icon name="chevron" size={18} /></button><div><h1>{creating ? '新建项目' : '新建对话'}</h1></div></header>
      {creating ? <div className="dm-new-project-fields"><label>项目名称<input value={name} disabled={busy} onChange={(event) => setName(event.target.value)} placeholder="输入项目名称" autoFocus /></label><div className="dm-folder-picker-title"><span>默认可访问文件夹</span><button type="button" disabled={busy} onClick={addFolder}><Icon name="plus" size={14} />添加</button></div><p className="dm-folder-help">第一个文件夹为默认输出位置，Agent 可访问下列全部文件夹。</p><div className="dm-selected-folders">{folders.map((folder, index) => <div key={folder}><Icon name="folder" size={16} /><span title={folder}><b>{index === 0 ? '默认 · ' : ''}</b>{folder}</span><button type="button" disabled={busy} aria-label={`移除文件夹 ${folder}`} onClick={() => setFolders((items) => items.filter((item) => item !== folder))}><Icon name="close" size={14} /></button></div>)}{!folders.length && <button type="button" disabled={busy} className="dm-add-folder-empty" onClick={addFolder}><Icon name="folder" size={22} />添加第一个文件夹</button>}</div></div> : <div className="dm-new-project-choice">
        <div ref={picker} className="dm-project-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setMenuOpen(false) }} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); setMenuOpen(false); pickerButton.current?.focus() } }}>
          <button ref={pickerButton} type="button" className="dm-project-picker-trigger" aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls={menuOpen ? menuId : undefined} disabled={busy} onClick={() => { setQuery(''); setMenuOpen(!menuOpen) }}><Icon name="folder" size={20} /><span>{selected?.name || '选择项目'}</span><span className="dm-project-picker-arrow"><Icon name="chevron" size={14} /></span></button>
          {menuOpen && <div id={menuId} role="dialog" aria-label="选择项目" className="dm-project-picker-menu">
            <label className="dm-project-picker-search"><Icon name="search" size={16} /><input aria-label="搜索项目" placeholder="搜索项目" value={query} onChange={event => setQuery(event.target.value)} autoFocus /></label>
            <div className="dm-project-picker-list">{projectsLoading ? <p>正在加载项目…</p> : projectsError ? <p role="alert">{projectsError}</p> : filtered.length ? filtered.map(project => <button type="button" key={project.id} aria-pressed={project.id === selectedId} title={project.primary_path} onClick={() => { setSelectedId(project.id); setMenuOpen(false); setError(null); pickerButton.current?.focus() }}><Icon name="folder" size={18} /><span><b>{project.name}</b><small>{project.primary_path}</small></span>{project.id === selectedId && <Icon name="check" size={16} />}</button>) : <p>{query ? '未找到匹配项目' : '暂无项目'}</p>}</div>
            <button type="button" className="dm-project-picker-create" onClick={() => { setCreating(true); setMenuOpen(false); setError(null) }}><Icon name="plus" size={18} />新建项目</button>
          </div>}
        </div>
        {selected && <div className="dm-project-choice-detail"><span>可访问文件夹</span>{selected.folder_paths.map(folder => <p key={folder} title={folder}><Icon name="folder" size={15} />{folder}</p>)}</div>}
      </div>}
      {error && <p className="dm-inline-error" role="alert">{error}</p>}
      <footer><button type="button" className="dm-outline-button" disabled={busy} onClick={onCancel}>取消</button><button type="button" className="dm-dialog-primary" disabled={busy || (!creating && !selected)} onClick={submit}>{busy ? (creating ? '正在创建…' : '正在开始…') : creating ? '创建并开始对话' : '开始对话'}</button></footer>
    </div>
  </section>
}
