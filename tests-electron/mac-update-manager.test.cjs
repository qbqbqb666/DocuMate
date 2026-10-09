const assert = require('node:assert/strict')
const { test } = require('node:test')
const { MacUpdateManager, isNewerRelease, MAC_VERSION_URL, DOWNLOAD_PAGE_URL } = require('../src/electron/mac-update-manager.cjs')

function fixture({ version = '0.4.2', update = true } = {}) {
  const calls = []
  const manager = new MacUpdateManager({
    version: '0.4.1',
    fetchImpl: async (url) => {
      calls.push(['check', url])
      return { ok: true, json: async () => ({ version, notes: '更新说明' }) }
    },
    showPrompt: async (info) => { calls.push(['prompt', info]); return update },
    openDownloadPage: async (url) => { calls.push(['open', url]) },
  })
  return { manager, calls }
}

test('Mac 按数字比较正式版本；同版、旧版不提示', async () => {
  assert.equal(isNewerRelease('0.4.10', '0.4.9'), true)
  assert.equal(isNewerRelease('1.0.0', '0.99.99'), true)
  assert.throws(() => isNewerRelease('0.4.2-beta.1', '0.4.1'))
  for (const version of ['0.4.1', '0.4.0']) {
    const { manager, calls } = fixture({ version })
    assert.equal((await manager.check()).status, 'allowed')
    assert.deepEqual(calls, [['check', MAC_VERSION_URL]])
  }
})

test('Mac 登录检查新版，点击更新才打开固定下载网页，不自动下载安装', async () => {
  const { manager, calls } = fixture()
  await Promise.all([manager.check(), manager.check()])
  assert.deepEqual(calls, [
    ['check', MAC_VERSION_URL],
    ['prompt', { version: '0.4.2', notes: '更新说明' }],
    ['open', DOWNLOAD_PAGE_URL],
  ])
  assert.equal(manager.state.status, 'allowed')
  await manager.start()
  assert.equal(calls.length, 3)
})

test('Mac 选择稍后继续使用，再次登录重新检查', async () => {
  const { manager, calls } = fixture({ update: false })
  await manager.check()
  await manager.check()
  assert.equal(calls.filter(([action]) => action === 'check').length, 2)
  assert.equal(calls.filter(([action]) => action === 'prompt').length, 2)
  assert.ok(calls.every(([action]) => action !== 'open'))
})

test('Mac 网络错误、404、损坏清单均放行，不提示假更新', async () => {
  for (const fetchImpl of [
    async () => { throw new Error('offline') },
    async () => ({ ok: false, status: 404 }),
    async () => ({ ok: true, json: async () => { throw new Error('invalid JSON') } }),
    async () => ({ ok: true, json: async () => ({ version: 'bad' }) }),
  ]) {
    const { manager, calls } = fixture()
    manager.fetchImpl = fetchImpl
    assert.equal((await manager.check()).status, 'allowed')
    assert.deepEqual(calls, [])
  }
})

test('Mac 真实 HTTP 清单检查超时放行，不弹窗或下载', async () => {
  const http = require('node:http')
  const server = http.createServer(() => {})
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  try {
    const { manager, calls } = fixture()
    manager.checkTimeoutMs = 30
    manager.fetchImpl = (_url, options) => fetch(`http://127.0.0.1:${server.address().port}/mac-version.json`, options)
    assert.equal((await manager.check()).status, 'allowed')
    assert.deepEqual(calls, [])
  } finally {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
  }
})
