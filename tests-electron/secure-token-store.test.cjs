const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { afterEach, test } = require('node:test')
const { SecureTokenStore } = require('../src/electron/secure-token-store.cjs')

const directories = []

afterEach(() => {
  for (const directory of directories.splice(0)) fs.rmSync(directory, { recursive: true, force: true })
})

test('refresh token 使用系统安全存储加密后落盘', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'documate-token-'))
  directories.push(directory)
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(`encrypted:${value}`),
    decryptString: (value) => value.toString().replace(/^encrypted:/, ''),
  }
  const file = path.join(directory, 'auth', 'refresh-token')
  const store = new SecureTokenStore(file, safeStorage)
  store.save('refresh-secret')
  assert.equal(store.load(), 'refresh-secret')
  assert.equal(fs.readFileSync(file, 'utf8').includes('refresh-secret'), false)
  store.clear()
  assert.equal(store.load(), null)
})

