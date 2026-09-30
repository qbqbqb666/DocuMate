const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('documate', {
  version: ipcRenderer.sendSync('app:get-version'),
  platform: process.platform,
  pickFolder: (options) => ipcRenderer.invoke('workspace:pick-folder', options),
  openFolder: (folderPath) => ipcRenderer.invoke('shell:open-folder', folderPath),
  openFile: (filePath) => ipcRenderer.invoke('shell:open-file', filePath),
  revealInFinder: (filePath) => ipcRenderer.invoke('shell:reveal-file', filePath),
  watchWorkspace: (workspacePath) => ipcRenderer.invoke('workspace:watch', workspacePath),
  loadRefreshToken: () => ipcRenderer.invoke('auth:load-refresh-token'),
  saveRefreshToken: (token) => ipcRenderer.invoke('auth:save-refresh-token', token),
  clearRefreshToken: () => ipcRenderer.invoke('auth:clear-refresh-token'),
  onWorkspaceChanged: (callback) => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('workspace:changed', listener)
    return () => ipcRenderer.removeListener('workspace:changed', listener)
  },
})
