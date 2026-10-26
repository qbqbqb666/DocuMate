/// <reference types="vite/client" />
import type { UpdateState } from './components/UpdateGate'

declare global {
  const __APP_VERSION__: string
}

interface ImportMetaEnv {
  readonly VITE_AUTH_SERVICE_URL?: string
  readonly VITE_BACKEND_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface DocuMateAPI {
  version: string
  platform: NodeJS.Platform
  checkForUpdates: () => Promise<UpdateState>
  startUpdate: () => Promise<UpdateState>
  onUpdateState: (callback: (state: UpdateState) => void) => () => void
  pickFiles: () => Promise<string[]>
  pickFolders: () => Promise<string[]>
  pickFolder: (options?: {
    title?: string
    buttonLabel?: string
    defaultPath?: string
  }) => Promise<string | null>
  openFolder: (folderPath: string) => Promise<boolean>
  openFile: (filePath: string) => Promise<boolean>
  revealInFinder: (filePath: string) => Promise<boolean>
  watchWorkspace: (workspacePath: string) => Promise<boolean>
  loadRefreshToken: () => Promise<string | null>
  saveRefreshToken: (token: string) => Promise<boolean>
  clearRefreshToken: () => Promise<boolean>
  onWorkspaceChanged: (callback: (payload: { reason: string; ts: number }) => void) => () => void
}

declare global {
  interface Window {
    documate?: DocuMateAPI
  }
}

export {}
