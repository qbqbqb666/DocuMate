const fs = require('node:fs')
const path = require('node:path')

class SecureTokenStore {
  constructor(filePath, safeStorage) {
    this.filePath = filePath
    this.safeStorage = safeStorage
  }

  load() {
    if (!this.safeStorage.isEncryptionAvailable() || !fs.existsSync(this.filePath)) return null
    try {
      const encrypted = Buffer.from(fs.readFileSync(this.filePath, 'utf8'), 'base64')
      return this.safeStorage.decryptString(encrypted)
    } catch {
      return null
    }
  }

  save(token) {
    if (!this.safeStorage.isEncryptionAvailable()) throw new Error('系统安全存储不可用')
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
    const temporary = `${this.filePath}.tmp`
    fs.writeFileSync(temporary, this.safeStorage.encryptString(token).toString('base64'), { mode: 0o600 })
    fs.renameSync(temporary, this.filePath)
    return true
  }

  clear() {
    if (fs.existsSync(this.filePath)) fs.unlinkSync(this.filePath)
    return true
  }
}

module.exports = { SecureTokenStore }

