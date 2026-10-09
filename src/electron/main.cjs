const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { BackendProcessManager } = require('./backend-process.cjs')
const { SecureTokenStore } = require('./secure-token-store.cjs')
const { UpdateManager } = require('./update-manager.cjs')
const { MacUpdateManager } = require('./mac-update-manager.cjs')

const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8765
const isDev = !app.isPackaged
let mainWindow = null
let backend = null
let workspaceWatcher = null
let watchedWorkspace = null
let debounceTimer = null
let quitAfterBackendStops = false
let refreshTokens = null
let updates = null

function projectRoot() {
  return path.resolve(__dirname, '..', '..')
}

function backendLaunch() {
  const dataRoot = path.join(app.getPath('userData'), 'backend-data')
  const appEnv = path.join(app.getPath('userData'), '.env')
  const defaultWorkspace = path.join(app.getPath('documents'), 'DocuMate Workspace')
  fs.mkdirSync(dataRoot, { recursive: true })
  fs.mkdirSync(defaultWorkspace, { recursive: true })

  if (isDev) {
    const root = projectRoot()
    const python = path.join(
      root,
      '.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    )
    if (!fs.existsSync(python)) {
      throw new Error(`找不到 Python 环境：${python}，请先执行 uv sync`)
    }
    return { command: python, args: ['-m', 'src.backend'], cwd: root, dataRoot, defaultWorkspace, appEnv: path.join(root, '.env') }
  }

  const executable = path.join(
    process.resourcesPath,
    'backend',
    'documate-backend',
    process.platform === 'win32' ? 'documate-backend.exe' : 'documate-backend',
  )
  return {
    command: executable,
    args: [],
    cwd: app.getPath('userData'),
    dataRoot,
    defaultWorkspace,
    appEnv,
  }
}

function createBackendManager() {
  const launch = backendLaunch()
  return new BackendProcessManager({
    host: BACKEND_HOST,
    port: BACKEND_PORT,
    command: launch.command,
    args: launch.args,
    cwd: launch.cwd,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      DOCUMATE_BACKEND_HOST: BACKEND_HOST,
      DOCUMATE_BACKEND_PORT: String(BACKEND_PORT),
      DOCUMATE_DATA_DIR: launch.dataRoot,
      DOCUMATE_DEFAULT_WORKSPACE: launch.defaultWorkspace,
      DOCUMATE_APP_ENV: launch.appEnv,
      DOCUMATE_PARENT_PID: String(process.pid),
      DOCUMATE_AUTH_SERVICE_URL: 'http://1.14.67.230/documate-auth',
    },
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'DocuMate',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#f8fbff',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  if (isDev) {
    mainWindow.loadURL(process.env.DOCUMATE_RENDERER_URL || 'http://127.0.0.1:5173')
    if (process.env.DOCUMATE_DEBUG === '1') mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(app.getAppPath(), 'dist', 'index.html'))
  }
}

function createErrorWindow(error) {
  if (!mainWindow) createWindow()
  const message = String(error?.message || error).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character])
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html><meta charset="utf-8"><style>body{font:14px -apple-system;padding:48px;color:#172554}pre{white-space:pre-wrap;background:#fff1f2;padding:16px;border-radius:10px}</style><h1>DocuMate 后端启动失败</h1><pre>${message}</pre><p>关闭应用后检查日志或重新启动。</p>`)}`)
}

function stopWorkspaceWatcher() {
  workspaceWatcher?.close()
  workspaceWatcher = null
  watchedWorkspace = null
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = null
}

function watchWorkspace(workspacePath) {
  if (workspacePath === watchedWorkspace) return
  stopWorkspaceWatcher()
  if (!workspacePath || !fs.existsSync(workspacePath)) return
  workspaceWatcher = fs.watch(workspacePath, { recursive: true, persistent: false }, (eventType, filename) => {
    const relative = String(filename || '')
    if (!relative || relative.split(path.sep).some((part) => part.startsWith('.'))) return
    if (!/\.(pdf|docx|xlsx)$/i.test(relative)) return
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      mainWindow?.webContents.send('workspace:changed', { reason: `${eventType}:${relative}`, ts: Date.now() })
    }, 800)
  })
  watchedWorkspace = workspacePath
}

ipcMain.handle('workspace:pick-folder', async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options.title || '选择 DocuMate 工作区',
    buttonLabel: options.buttonLabel || '使用此文件夹',
    defaultPath: options.defaultPath || app.getPath('documents'),
    properties: ['openDirectory', 'createDirectory'],
  })
  return result.canceled ? null : result.filePaths[0] || null
})
ipcMain.handle('shell:open-folder', async (_event, target) => !target ? false : (await shell.openPath(target)) === '')
ipcMain.handle('shell:open-file', async (_event, target) => !target ? false : (await shell.openPath(target)) === '')
ipcMain.handle('shell:reveal-file', (_event, target) => { if (!target) return false; shell.showItemInFolder(target); return true })
ipcMain.handle('workspace:watch', (_event, target) => { watchWorkspace(target); return true })
ipcMain.handle('auth:load-refresh-token', () => refreshTokens?.load() || null)
ipcMain.handle('auth:save-refresh-token', (_event, token) => refreshTokens?.save(String(token || '')) || false)
ipcMain.handle('auth:clear-refresh-token', () => refreshTokens?.clear() || false)
ipcMain.on('app:get-version', (event) => { event.returnValue = app.getVersion() })
for (const [channel, method] of [['updates:check', 'check'], ['updates:start', 'start']]) {
  ipcMain.handle(channel, (event) => {
    if (event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) {
      throw new Error('无效的更新请求')
    }
    return updates[method]()
  })
}

app.whenReady().then(async () => {
  refreshTokens = new SecureTokenStore(path.join(app.getPath('userData'), 'auth', 'refresh-token'), safeStorage)
  backend = createBackendManager()
  updates = process.platform === 'darwin' && app.isPackaged ? new MacUpdateManager({
    version: app.getVersion(),
    showPrompt: async ({ version, notes }) => {
      const result = await dialog.showMessageBox(mainWindow, {
        type: 'info', title: 'DocuMate 更新',
        message: `发现新版本 v${version}`,
        detail: `当前版本 v${app.getVersion()}。点击“更新”打开下载网页。下载新版 ZIP 后，请退出 DocuMate，将新应用拖到“应用程序”文件夹并选择“替换”。${notes ? '\n\n' + notes : ''}`,
        buttons: ['更新', '稍后'], defaultId: 0, cancelId: 1, noLink: true,
      })
      return result.response === 0
    },
    openDownloadPage: async (url) => {
      try { await shell.openExternal(url) }
      catch (error) {
        dialog.showErrorBox('无法打开下载页面', `请在浏览器中访问 ${url}\n${error.message}`)
      }
    },
  }) : new UpdateManager({
    updater: process.platform === 'win32' && app.isPackaged ? require('electron-updater').autoUpdater : null,
    beforeInstall: async () => {
      stopWorkspaceWatcher()
      await backend.stop()
      quitAfterBackendStops = true
    },
  })
  updates.on('state', (state) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('updates:state', state)
  })
  try {
    await backend.start()
    createWindow()
  } catch (error) {
    console.error('[electron] startup failed', error)
    createErrorWindow(error)
  }
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
})

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('before-quit', (event) => {
  if (quitAfterBackendStops || !backend?.ownsProcess) return
  event.preventDefault()
  quitAfterBackendStops = true
  stopWorkspaceWatcher()
  backend.stop().finally(() => app.quit())
})
app.on('will-quit', stopWorkspaceWatcher)
