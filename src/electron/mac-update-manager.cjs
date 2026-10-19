const { EventEmitter } = require('node:events')

const MAC_VERSION_URL = 'https://documate.store/documate/mac-version.json'
const DOWNLOAD_PAGE_URL = 'https://documate.store/documate/#downloads'

function isNewerRelease(latest, current) {
  const parse = (version) => {
    if (typeof version !== 'string' || !/^\d+\.\d+\.\d+$/.test(version)) throw new Error('无效的正式版本号')
    const parts = version.split('.').map(Number)
    if (!parts.every(Number.isSafeInteger)) throw new Error('无效的正式版本号')
    return parts
  }
  const next = parse(latest)
  const installed = parse(current)
  for (let index = 0; index < next.length; index++) {
    if (next[index] !== installed[index]) return next[index] > installed[index]
  }
  return false
}

class MacUpdateManager extends EventEmitter {
  constructor({ version, showPrompt, openDownloadPage, fetchImpl = fetch, checkTimeoutMs = 15000 }) {
    super()
    this.version = version
    this.showPrompt = showPrompt
    this.openDownloadPage = openDownloadPage
    this.fetchImpl = fetchImpl
    this.checkTimeoutMs = checkTimeoutMs
    this.checkPromise = null
    this.state = { status: 'allowed', version: '', notes: '', percent: 0 }
  }

  check() {
    if (this.checkPromise) return this.checkPromise
    this.checkPromise = this.performCheck().finally(() => { this.checkPromise = null })
    return this.checkPromise
  }

  async performCheck() {
    try {
      const response = await this.fetchImpl(MAC_VERSION_URL, {
        cache: 'no-store', signal: AbortSignal.timeout(this.checkTimeoutMs),
      })
      if (!response.ok) throw new Error(`版本清单 HTTP ${response.status}`)
      const manifest = await response.json()
      if (isNewerRelease(manifest.version, this.version)) {
        const update = { version: manifest.version, notes: typeof manifest.notes === 'string' ? manifest.notes : '' }
        if (await this.showPrompt(update)) await this.openDownloadPage(DOWNLOAD_PAGE_URL)
      }
    } catch (error) {
      console.warn('[mac-updater] check failed; allowing current version:', error.message)
    }
    return this.state
  }

  start() { return Promise.resolve(this.state) }
}

module.exports = { MacUpdateManager, isNewerRelease, MAC_VERSION_URL, DOWNLOAD_PAGE_URL }
