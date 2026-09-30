const assert = require('node:assert/strict')
const http = require('node:http')
const { afterEach, test } = require('node:test')
const { BackendProcessManager } = require('../src/electron/backend-process.cjs')

const servers = []

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise((resolve) => server.close(resolve))))
})

async function serve(handler) {
  const server = http.createServer(handler)
  servers.push(server)
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  return server.address().port
}

function manager(port) {
  return new BackendProcessManager({
    host: '127.0.0.1', port, command: 'unused', args: [], cwd: '.', env: {},
    spawnImpl: () => { throw new Error('不应启动新进程') },
  })
}

test('复用已就绪的 DocuMate 后端', async () => {
  const port = await serve((request, response) => {
    response.setHeader('Content-Type', 'application/json')
    if (request.url === '/api/health') response.end(JSON.stringify({ status: 'ok', service: 'documate-backend' }))
    else response.end(JSON.stringify({ status: 'ready', service: 'documate-backend' }))
  })
  const result = await manager(port).start()
  assert.deepEqual(result, { reused: true })
})

test('不会终止占用端口的其他服务', async () => {
  const port = await serve((_request, response) => {
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ service: 'another-service' }))
  })
  await assert.rejects(manager(port).start(), /其他服务占用/)
})

test('macOS 通过进程组信号终止后端', () => {
  if (process.platform === 'win32') return
  const instance = manager(8765)
  const originalKill = process.kill
  const calls = []
  process.kill = (pid, signal) => { calls.push([pid, signal]); return true }
  try {
    instance.signal({ pid: 4321, kill: () => { throw new Error('不应回退到单进程信号') } }, 'SIGTERM')
  } finally {
    process.kill = originalKill
  }
  assert.deepEqual(calls, [[-4321, 'SIGTERM']])
})
