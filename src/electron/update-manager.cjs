const { EventEmitter } = require('node:events')

// Keep download/install decisions in the main process, not in the renderer.
class UpdateManager extends EventEmitter {
  constructor({ updater, beforeInstall = async () => {}, checkTimeoutMs = 15000 }) {
    super()
    this.updater = updater
    this.beforeInstall = beforeInstall
    this.checkTimeoutMs = checkTimeoutMs
    this.state = { status: updater ? 'idle' : 'allowed', version: '', notes: '', percent: 0 }
    this.checkPromise = null
    this.actionPromise = null
    this.downloaded = false
    if (!updater) return
    updater.autoDownload = false
    updater.autoInstallOnAppQuit = false
    updater.allowDowngrade = false
    updater.allowPrerelease = false
    updater.on('download-progress', ({ percent }) => {
      if (this.state.status === 'downloading') this.set({ percent: Math.max(0, Math.min(100, percent || 0)) })
    })
    updater.on('error', (error) => {
      console.error('[updater]', error)
      // Check/download errors are handled by their promises. Installation errors
      // can arrive after quitAndInstall returns.
      if (this.state.status === 'installing') this.fail('安装未能启动，请点击重试。')
    })
  }

  set(patch) {
    this.state = { ...this.state, ...patch }
    this.emit('state', this.state)
    return this.state
  }

  fail(message) { return this.set({ status: 'error', message }) }

  check() {
    if (!this.updater || this.state.version) return Promise.resolve(this.state)
    if (this.checkPromise) return this.checkPromise
    this.set({ status: 'checking', message: '' })
    this.checkPromise = this.performCheck().finally(() => { this.checkPromise = null })
    return this.checkPromise
  }

  async performCheck() {
    let timer
    try {
      const result = await Promise.race([
        this.updater.checkForUpdates(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('更新检查超时')), this.checkTimeoutMs) }),
      ])
      if (!result?.isUpdateAvailable) return this.set({ status: 'allowed' })
      const info = result.updateInfo
      const notes = Array.isArray(info.releaseNotes)
        ? info.releaseNotes.map((item) => item.note || '').join('\n')
        : String(info.releaseNotes || '')
      return this.set({ status: 'available', version: info.version, notes })
    } catch (error) {
      console.warn('[updater] check failed; allowing current version:', error.message)
      return this.set({ status: 'allowed' })
    } finally {
      clearTimeout(timer)
    }
  }

  start() {
    if (this.actionPromise) return this.actionPromise
    if (!this.updater || !this.state.version || !['available', 'error'].includes(this.state.status)) {
      return Promise.resolve(this.state)
    }
    this.actionPromise = this.performUpdate().finally(() => { this.actionPromise = null })
    return this.actionPromise
  }

  async performUpdate() {
    try {
      if (!this.downloaded) {
        this.set({ status: 'downloading', percent: 0, message: '' })
        await this.updater.downloadUpdate()
        this.downloaded = true
      }
      this.set({ status: 'installing', percent: 100, message: '' })
      await this.beforeInstall()
      this.updater.quitAndInstall(false, true)
    } catch (error) {
      console.error('[updater] update failed:', error)
      this.fail(this.downloaded ? '安装未能启动，请点击重试。' : '下载或校验失败，请检查网络后重试。')
    }
    return this.state
  }
}

module.exports = { UpdateManager }
