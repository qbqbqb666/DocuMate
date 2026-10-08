const assert = require('node:assert/strict')
const { test } = require('node:test')
const { EventEmitter } = require('node:events')
const { UpdateManager } = require('../src/electron/update-manager.cjs')

function fixture(result = { isUpdateAvailable: true, updateInfo: { version: '0.4.2', releaseNotes: '修复问题' } }) {
  const updater = new EventEmitter()
  const calls = []
  updater.checkForUpdates = async () => { calls.push('check'); return result }
  updater.downloadUpdate = async () => { calls.push('download'); updater.emit('download-progress', { percent: 45 }); return ['setup.exe'] }
  updater.quitAndInstall = () => calls.push('install')
  const manager = new UpdateManager({ updater, beforeInstall: async () => { calls.push('stop-backend') } })
  return { updater, manager, calls }
}

test('发现新版仅显示界面，点击才下载，先关闭后端再安装', async () => {
  const { updater, manager, calls } = fixture()
  const states = []
  manager.on('state', (value) => states.push(value))
  assert.equal(updater.autoDownload, false)
  assert.equal(updater.autoInstallOnAppQuit, false)
  assert.equal((await manager.start()).status, 'idle')
  assert.equal((await manager.check()).status, 'available')
  assert.deepEqual(calls, ['check'])
  await manager.start()
  assert.deepEqual(calls, ['check', 'download', 'stop-backend', 'install'])
  assert.ok(states.some((value) => value.percent === 45))
})

test('没有新版放行；macOS/开发模式不检查', async () => {
  assert.equal((await fixture({ isUpdateAvailable: false }).manager.check()).status, 'allowed')
  assert.equal((await new UpdateManager({ updater: null }).check()).status, 'allowed')
})

test('检查失败或超时放行，不下载，超时后的迟到结果不阻塞', async () => {
  const { updater, manager, calls } = fixture()
  updater.checkForUpdates = async () => { throw new Error('offline') }
  assert.equal((await manager.check()).status, 'allowed')
  let finish
  updater.checkForUpdates = () => new Promise((resolve) => { finish = resolve })
  manager.checkTimeoutMs = 5
  assert.equal((await manager.check()).status, 'allowed')
  finish({ isUpdateAvailable: true, updateInfo: { version: '0.4.2' } })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(manager.state.status, 'allowed')
  assert.deepEqual(calls, [])
})

test('下载失败保持阻塞，重新检查不能绕过，重试成功后安装', async () => {
  const { updater, manager, calls } = fixture()
  await manager.check()
  updater.downloadUpdate = async () => { throw new Error('checksum mismatch') }
  assert.equal((await manager.start()).status, 'error')
  assert.equal((await manager.check()).status, 'error')
  assert.deepEqual(calls, ['check'])
  updater.downloadUpdate = async () => { calls.push('download') }
  await manager.start()
  assert.equal(manager.state.status, 'installing')
})

test('并发检查和重复点击不会重复下载或安装', async () => {
  const { manager, calls } = fixture()
  await Promise.all([manager.check(), manager.check()])
  await Promise.all([manager.start(), manager.start()])
  assert.deepEqual(calls, ['check', 'download', 'stop-backend', 'install'])
})

test('安装启动失败可重试，复用已下载文件', async () => {
  const { updater, manager, calls } = fixture()
  updater.quitAndInstall = () => updater.emit('error', new Error('installer launch failed'))
  await manager.check()
  assert.equal((await manager.start()).status, 'error')
  updater.quitAndInstall = () => calls.push('install')
  await manager.start()
  assert.equal(calls.filter((value) => value === 'download').length, 1)
  assert.equal(calls.at(-1), 'install')
})

test('更新说明作为纯文本传递', async () => {
  const { manager } = fixture({ isUpdateAvailable: true, updateInfo: { version: '0.4.2', releaseNotes: [{ note: '<script>text</script>' }, { note: '修复' }] } })
  assert.equal((await manager.check()).notes, '<script>text</script>\n修复')
})

test('真实 Generic 更新器读取 Windows latest.yml，按版本比较且不会预下载', async () => {
  const http = require('node:http')
  const fs = require('node:fs/promises')
  const os = require('node:os')
  const path = require('node:path')
  const { NsisUpdater } = require('electron-updater')
  const { NodeHttpExecutor } = require('builder-util/out/nodeHttpExecutor')
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'documate-updater-test-'))
  const requests = []
  let version = '0.4.2'
  const server = http.createServer((request, response) => {
    requests.push(request.url)
    response.end(`version: ${version}\nfiles:\n  - url: DocuMate-Setup-v${version}-windows-x64.exe\n    sha512: placeholder\n    size: 1\nreleaseNotes: 测试更新\n`)
  })
  try {
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
    const app = { version: '0.4.1', name: 'DocuMate', isPackaged: true, userDataPath: directory, whenReady: async () => {} }
    const updater = new NsisUpdater(null, app)
    updater.logger = { info() {}, warn() {}, error() {}, debug() {} }
    updater.httpExecutor = new NodeHttpExecutor()
    updater._testOnlyOptions = { platform: 'win32' }
    updater.setFeedURL({ provider: 'generic', url: `http://127.0.0.1:${server.address().port}/windows-x64/` })
    const manager = new UpdateManager({ updater })
    assert.equal((await manager.check()).status, 'available')
    assert.equal(manager.state.version, '0.4.2')
    assert.equal(requests.length, 1)
    assert.match(requests[0], /^\/windows-x64\/latest.yml/)
    for (version of ['0.4.1', '0.4.0']) {
      const result = await updater.checkForUpdates()
      assert.equal(result.isUpdateAvailable, false)
    }
    assert.ok(requests.every((url) => url.includes('latest.yml')))
  } finally {
    await new Promise((resolve) => server.close(resolve))
    await fs.rm(directory, { recursive: true, force: true })
  }
})
