import { useLayoutEffect, useRef, useSyncExternalStore, type SetStateAction } from 'react'
import type { WorkspaceFile } from './useWorkspaceFiles'

type Draft = { text: string; files: WorkspaceFile[] }
const emptyDraft: Draft = { text: '', files: [] }
const drafts = new Map<string, Draft>()
const aliases = new Map<string, string>()
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
const resolve = (key: string): string => aliases.has(key) ? resolve(aliases.get(key)!) : key
const storageKey = (key: string) => `documate.chat-draft.v1:${key}`

function read(key: string): Draft {
  key = resolve(key)
  if (!drafts.has(key)) {
    let draft = emptyDraft
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey(key)) || 'null')
      if (stored && typeof stored.text === 'string' && Array.isArray(stored.files)) {
        draft = { text: stored.text, files: stored.files.filter((file: WorkspaceFile) => file && typeof file.id === 'string' && typeof file.filename === 'string' && typeof file.saved_path === 'string') }
      }
    } catch { /* Storage unavailable: retain drafts in memory. */ }
    drafts.set(key, draft)
  }
  return drafts.get(key)!
}

function write(key: string, draft: Draft) {
  key = resolve(key)
  drafts.set(key, draft)
  try {
    if (draft.text || draft.files.length) localStorage.setItem(storageKey(key), JSON.stringify(draft))
    else localStorage.removeItem(storageKey(key))
  } catch { /* Storage unavailable: retain drafts in memory. */ }
  listeners.forEach(listener => listener())
}

export function useChatDraft(workspacePath: string | undefined, projectId: string | undefined, conversationId: string, temporary: boolean) {
  const scope = JSON.stringify([workspacePath || '', projectId || ''])
  const key = JSON.stringify([scope, conversationId])
  const previous = useRef({ key, scope, temporary })
  const draft = useSyncExternalStore(subscribe, () => read(key))

  useLayoutEffect(() => {
    const old = previous.current
    if (old.key !== key && old.scope === scope && old.temporary && !temporary) {
      const pending = read(old.key)
      if (read(key) === emptyDraft) write(key, pending)
      aliases.set(old.key, key)
      drafts.delete(old.key)
      try { localStorage.removeItem(storageKey(old.key)) } catch { /* Memory cache remains available. */ }
      listeners.forEach(listener => listener())
    }
    previous.current = { key, scope, temporary }
  }, [key, scope, temporary])

  return {
    input: draft.text,
    referencedFiles: draft.files,
    setInput: (value: SetStateAction<string>) => { const current = read(key); write(key, { ...current, text: typeof value === 'function' ? value(current.text) : value }) },
    setReferencedFiles: (value: SetStateAction<WorkspaceFile[]>) => { const current = read(key); write(key, { ...current, files: typeof value === 'function' ? value(current.files) : value }) },
    clearSubmittedDraft: () => { if (read(key) === draft) write(key, emptyDraft) },
  }
}
