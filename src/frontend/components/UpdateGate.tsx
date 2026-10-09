import { useEffect, useState, type ReactNode } from 'react'
import { BrandMark } from './BrandMark'

export interface UpdateState {
  status: 'idle' | 'checking' | 'allowed' | 'available' | 'downloading' | 'installing' | 'error'
  version: string
  notes: string
  percent: number
  message?: string
}

export function UpdateGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UpdateState>({ status: 'checking', version: '', notes: '', percent: 0 })
  useEffect(() => {
    const desktop = window.documate
    if (!desktop || !['win32', 'darwin'].includes(desktop.platform)) {
      setState((value) => ({ ...value, status: 'allowed' }))
      return
    }
    let active = true
    const receive = (value: UpdateState) => { if (active) setState(value) }
    const unsubscribe = desktop.onUpdateState(receive)
    void desktop.checkForUpdates().then(receive).catch(() => {
      if (desktop.platform === 'darwin') {
        if (active) setState((value) => ({ ...value, status: 'allowed' }))
        return
      }
      // IPC failure is not evidence that no update exists; do not bypass the gate.
      if (active) setState((value) => ({ ...value, status: 'error', message: '更新服务未响应，请关闭应用后重新打开。' }))
    })
    return () => { active = false; unsubscribe() }
  }, [])

  if (state.status === 'allowed') return <>{children}</>
  const checking = state.status === 'checking' || state.status === 'idle'
  const busy = state.status === 'downloading' || state.status === 'installing'
  const start = async () => {
    try { setState(await window.documate!.startUpdate()) }
    catch { setState((value) => ({ ...value, status: 'error', message: '无法启动更新，请重试。' })) }
  }
  return <main className="h-screen w-screen flex items-center justify-center bg-slate-50 p-6">
    <section role="dialog" aria-modal="true" aria-labelledby="update-title" className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl border border-slate-200">
      <BrandMark size={52} />
      <h1 id="update-title" className="text-xl font-semibold text-slate-900 mt-5">{checking ? '正在检查更新…' : !state.version ? '更新检查未完成' : state.status === 'installing' ? '正在启动安装…' : '发现新版本'}</h1>
      <p className="text-sm text-slate-500 mt-3">当前版本 v{window.documate?.version}{state.version && ` → v${state.version}`}</p>
      {state.version && <p className="text-sm text-slate-600 mt-4">请更新后继续使用。点击立即更新后开始下载，完成后将关闭应用并启动安装。</p>}
      {state.notes && <pre className="whitespace-pre-wrap text-sm text-slate-600 mt-4 max-h-48 overflow-auto font-sans">{state.notes}</pre>}
      {busy && <div className="mt-5" aria-live="polite"><progress className="w-full" max={100} value={state.percent} /><p className="text-sm text-slate-500 mt-2">{state.status === 'installing' ? '下载完成，正在重启安装…' : `正在下载 ${Math.floor(state.percent)}%`}</p></div>}
      {state.message && <p role="alert" className="text-sm text-red-600 mt-4">{state.message}</p>}
      {!checking && !busy && state.version && <button className="w-full mt-6 rounded-lg bg-blue-900 text-white py-3 font-semibold" onClick={() => void start()}>{state.status === 'error' ? '重试更新' : '立即更新'}</button>}
    </section>
  </main>
}
