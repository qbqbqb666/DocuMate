const { spawn } = require('node:child_process')
const http = require('node:http')

function requestJson(url, timeoutMs = 1000) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => {
        try {
          resolve({
            statusCode: response.statusCode || 0,
            body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
          })
        } catch (error) {
          reject(new Error(`后端返回了无效 JSON：${error.message}`))
        }
      })
    })
    request.setTimeout(timeoutMs, () => request.destroy(new Error('请求后端超时')))
    request.on('error', reject)
  })
}

class BackendProcessManager {
  constructor({ host, port, command, args, cwd, env, spawnImpl = spawn }) {
    this.host = host
    this.port = port
    this.command = command
    this.args = args
    this.cwd = cwd
    this.env = env
    this.spawnImpl = spawnImpl
    this.child = null
    this.ownsProcess = false
  }

  get baseUrl() {
    return `http://${this.host}:${this.port}`
  }

  async start() {
    const existing = await this.probeExisting()
    if (existing) return { reused: true }

    this.child = this.spawnImpl(this.command, this.args, {
      cwd: this.cwd,
      env: this.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      detached: process.platform !== 'win32',
    })
    this.ownsProcess = true
    this.child.stdout?.on('data', (data) => console.log(`[backend] ${data.toString().trim()}`))
    this.child.stderr?.on('data', (data) => console.error(`[backend] ${data.toString().trim()}`))
    this.child.once('exit', (code, signal) => {
      console.log(`[backend] exited code=${code} signal=${signal}`)
      this.child = null
    })
    this.child.once('error', (error) => console.error('[backend] process error', error))

    await this.waitUntilReady()
    return { reused: false }
  }

  async probeExisting() {
    let response
    try {
      response = await requestJson(`${this.baseUrl}/api/health`, 600)
    } catch {
      return false
    }
    if (response.statusCode !== 200 || response.body?.service !== 'documate-backend') {
      throw new Error(`端口 ${this.port} 已被其他服务占用`)
    }
    const ready = await requestJson(`${this.baseUrl}/api/ready`, 1000)
    if (ready.statusCode !== 200 || ready.body?.status !== 'ready') {
      throw new Error('已运行的 DocuMate 后端未就绪')
    }
    return true
  }

  async waitUntilReady(maxAttempts = 60, intervalMs = 250) {
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      if (!this.child) throw new Error('DocuMate 后端在就绪前退出')
      try {
        const response = await requestJson(`${this.baseUrl}/api/ready`, 800)
        if (response.statusCode === 200 && response.body?.status === 'ready') return
      } catch {
        // 后端启动期内连接失败属于正常重试。
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs))
    }
    await this.stop()
    throw new Error('DocuMate 后端启动超时')
  }

  async stop(timeoutMs = 5000) {
    const child = this.child
    if (!child || !this.ownsProcess) return
    await new Promise((resolve) => {
      let finished = false
      const finish = () => {
        if (finished) return
        finished = true
        clearTimeout(timer)
        resolve()
      }
      const timer = setTimeout(() => {
        if (child.exitCode === null) this.signal(child, 'SIGKILL')
        finish()
      }, timeoutMs)
      child.once('exit', finish)
      this.signal(child, 'SIGTERM')
    })
    this.child = null
    this.ownsProcess = false
  }

  signal(child, signal) {
    if (process.platform !== 'win32' && Number.isInteger(child.pid)) {
      try {
        process.kill(-child.pid, signal)
        return
      } catch (error) {
        if (error?.code === 'ESRCH') return
      }
    }
    child.kill(signal)
  }
}

module.exports = { BackendProcessManager, requestJson }
