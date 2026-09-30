import { useState } from 'react'
import { Icon } from './Icon'

interface Props {
  onCancel: () => void
  onCreateProject: (name: string, folders: string[]) => Promise<void>
}

export function NewConversationPage({ onCancel, onCreateProject }: Props) {
  const [name, setName] = useState('')
  const [folders, setFolders] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const addFolder = async () => {
    const path = await window.documate?.pickFolder({ title: '选择项目可访问文件夹', buttonLabel: '添加文件夹' })
    if (path) setFolders((items) => items.includes(path) ? items : [...items, path])
  }
  const submit = async () => {
    setError(null); setBusy(true)
    try {
      if (!name.trim()) throw new Error('请输入项目名称')
      if (!folders.length) throw new Error('请至少添加一个可访问文件夹')
      await onCreateProject(name.trim(), folders)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false) }
  }
  return <section className="dm-new-conversation-page">
    <aside className="dm-new-conversation-form"><header><button className="dm-icon-button" onClick={onCancel}><Icon name="chevron" size={18} /></button><div><p>创建新对话</p><h1>创建项目与工作区</h1></div></header>
      <div className="dm-new-project-fields"><label>项目名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：毕业论文" autoFocus /></label><div className="dm-folder-picker-title"><span>默认可访问文件夹</span><button onClick={addFolder}><Icon name="plus" size={14} />添加</button></div><p className="dm-folder-help">第一个文件夹为默认输出位置，Agent 可访问下列全部文件夹。</p><div className="dm-selected-folders">{folders.map((folder, index) => <div key={folder}><Icon name="folder" size={16} /><span><b>{index === 0 ? '默认 · ' : ''}</b>{folder}</span><button onClick={() => setFolders((items) => items.filter((item) => item !== folder))}><Icon name="close" size={14} /></button></div>)}{!folders.length && <button className="dm-add-folder-empty" onClick={addFolder}><Icon name="folder" size={22} />添加第一个文件夹</button>}</div></div>
      {error && <p className="dm-inline-error">{error}</p>}
      <footer><button className="dm-outline-button" onClick={onCancel}>取消</button><button className="dm-dialog-primary" disabled={busy} onClick={submit}>{busy ? '正在创建…' : '确认并开始对话'}</button></footer>
    </aside>
    <div className="dm-new-conversation-hero"><div className="dm-workspace-glyph"><Icon name="folder" size={42} /></div><h2>请选择合适的工作区</h2><p>项目将帮助你隔离对话与文件上下文，让每项任务保持清晰。</p></div>
  </section>
}
