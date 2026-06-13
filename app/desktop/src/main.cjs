const { app, BrowserWindow, ipcMain, safeStorage, shell } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const net = require('node:net')
const http = require('node:http')
const { spawn } = require('node:child_process')

app.setName('DXM Agent Console')

let mainWindow = null
let backendProcess = null

const runtimeInfo = {
  repoRoot: null,
  backendPort: null,
  apiBase: null,
  frontendPath: null,
  backendLogPath: null,
  desktopLogPath: null,
  qaCapturePath: null,
  lastError: null,
}

function getQaCapturePath() {
  const arg = process.argv.find((value) => value.startsWith('--qa-capture='))
  if (!arg) return null
  const capturePath = arg.slice('--qa-capture='.length).trim()
  return capturePath || null
}

function getQaCredentialSmokePath() {
  const arg = process.argv.find((value) => value.startsWith('--qa-credential-smoke='))
  if (!arg) return null
  const outputPath = arg.slice('--qa-credential-smoke='.length).trim()
  return outputPath || null
}

function initializeDesktopLogPath() {
  try {
    const dataDir = path.join(app.getPath('userData'), 'data')
    fs.mkdirSync(dataDir, { recursive: true })
    runtimeInfo.desktopLogPath = path.join(dataDir, 'desktop-main.log')
  } catch {
    // App paths may be unavailable before Electron is ready.
  }
}

function resolveRepoRoot() {
  const candidates = [
    process.resourcesPath,
    path.resolve(__dirname, '..', '..', '..'),
    path.resolve(process.cwd(), '..', '..'),
    process.cwd(),
    app.getAppPath(),
  ]

  for (const candidate of candidates) {
    const backendEntry = path.join(candidate, 'app', 'backend', 'src', 'main.py')
    if (fs.existsSync(backendEntry)) {
      return candidate
    }
  }

  throw new Error('Cannot locate repo root containing app/backend/src/main.py')
}

function ensureDataDir(repoRoot) {
  const dataDir = app.isPackaged
    ? path.join(app.getPath('userData'), 'data')
    : path.join(repoRoot, 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  return dataDir
}

function getDesktopDataDir() {
  const dataDir = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  return dataDir
}

function getCredentialPath() {
  return path.join(getDesktopDataDir(), 'dxm-login-credential.json')
}

function safeStorageAvailable() {
  try {
    return Boolean(safeStorage && safeStorage.isEncryptionAvailable())
  } catch {
    return false
  }
}

function loadDxmCredential() {
  const credentialPath = getCredentialPath()
  if (!fs.existsSync(credentialPath)) {
    return { ok: true, available: safeStorageAvailable(), credential: null }
  }
  if (!safeStorageAvailable()) {
    return { ok: false, available: false, credential: null, error: 'Electron safeStorage is unavailable.' }
  }
  try {
    const raw = JSON.parse(fs.readFileSync(credentialPath, 'utf8'))
    const encrypted = Buffer.from(String(raw.passwordCipherBase64 || ''), 'base64')
    const password = encrypted.length ? safeStorage.decryptString(encrypted) : ''
    return {
      ok: true,
      available: true,
      credential: {
        username: String(raw.username || ''),
        password,
        updatedAt: raw.updatedAt || null,
      },
    }
  } catch (error) {
    return {
      ok: false,
      available: true,
      credential: null,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

function saveDxmCredential(payload) {
  if (!safeStorageAvailable()) {
    return { ok: false, available: false, error: 'Electron safeStorage is unavailable.' }
  }
  const username = String(payload?.username || '').trim()
  const password = String(payload?.password || '')
  if (!username || !password) {
    return { ok: false, available: true, error: 'Username and password are required.' }
  }
  const encrypted = safeStorage.encryptString(password)
  const body = {
    username,
    passwordCipherBase64: encrypted.toString('base64'),
    updatedAt: new Date().toISOString(),
    storage: 'electron-safeStorage',
  }
  fs.writeFileSync(getCredentialPath(), JSON.stringify(body, null, 2), 'utf8')
  return { ok: true, available: true, updatedAt: body.updatedAt }
}

function clearDxmCredential() {
  const credentialPath = getCredentialPath()
  if (fs.existsSync(credentialPath)) {
    fs.rmSync(credentialPath, { force: true })
  }
  return { ok: true, available: safeStorageAvailable() }
}

function runCredentialSmoke(outputPath) {
  const credentialPath = getCredentialPath()
  const previousCredential = fs.existsSync(credentialPath)
    ? fs.readFileSync(credentialPath, 'utf8')
    : null
  const result = {
    ok: false,
    available: safeStorageAvailable(),
    saved: false,
    loaded: false,
    cleared: false,
    restoredPreviousCredential: previousCredential !== null,
    credentialPath,
  }

  try {
    const saved = saveDxmCredential({ username: '__qa_dxm_user__', password: '__qa_dxm_password__' })
    if (!saved.ok) throw new Error(saved.error || 'Credential save failed')
    result.saved = true

    const loaded = loadDxmCredential()
    if (!loaded.ok) throw new Error(loaded.error || 'Credential load failed')
    if (!loaded.credential) throw new Error('Credential smoke did not load a credential')
    if (loaded.credential.username !== '__qa_dxm_user__') throw new Error('Credential smoke username mismatch')
    if (loaded.credential.password !== '__qa_dxm_password__') throw new Error('Credential smoke password mismatch')
    result.loaded = true

    const cleared = clearDxmCredential()
    if (!cleared.ok) throw new Error(cleared.error || 'Credential clear failed')
    result.cleared = !fs.existsSync(credentialPath)
    if (!result.cleared) throw new Error('Credential smoke did not clear test credential')

    result.ok = true
  } catch (error) {
    result.error = error instanceof Error ? error.message : String(error)
  } finally {
    if (previousCredential !== null) {
      fs.writeFileSync(credentialPath, previousCredential, 'utf8')
    } else if (fs.existsSync(credentialPath)) {
      fs.rmSync(credentialPath, { force: true })
    }
    result.restored = previousCredential !== null ? fs.existsSync(credentialPath) : !fs.existsSync(credentialPath)
    fs.mkdirSync(path.dirname(outputPath), { recursive: true })
    fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8')
    appendDesktopLog(`Credential smoke written: ${outputPath} ok=${result.ok}`)
  }

  if (!result.ok) {
    throw new Error(`Credential smoke failed: ${result.error || 'unknown error'}`)
  }
  return result
}

function appendDesktopLog(message) {
  if (!runtimeInfo.desktopLogPath) initializeDesktopLogPath()
  const logPath = runtimeInfo.desktopLogPath
  if (!logPath) return
  const line = `[${new Date().toISOString()}] ${message}\n`
  fs.appendFileSync(logPath, line, 'utf8')
}

function logPackagedResourceStatus(repoRoot) {
  const resources = [
    'tools/probes/l2_readonly_probe_runner.py',
    'tools/probes/l2_readonly_probe.py',
    'config/l2_readonly_allowlist.json',
  ]
  const facts = resources.map((relativePath) => {
    const fullPath = path.join(repoRoot, ...relativePath.split('/'))
    return `${relativePath}=${fs.existsSync(fullPath) ? 'ok' : 'missing'} (${fullPath})`
  })
  appendDesktopLog(`Packaged resource status: repoRoot=${repoRoot}; ${facts.join('; ')}`)
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function createStartupErrorWindow(error) {
  const message = error instanceof Error ? error.stack || error.message : String(error)
  const logPath = runtimeInfo.desktopLogPath || 'desktop-main.log'
  mainWindow = new BrowserWindow({
    width: 860,
    height: 560,
    minWidth: 720,
    minHeight: 420,
    backgroundColor: '#f8fafc',
    title: 'DXM Agent Console startup failed',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  const html = `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>DXM Agent Console startup failed</title>
    <style>
      body { margin: 0; padding: 28px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #f8fafc; color: #111827; }
      main { max-width: 760px; margin: 0 auto; display: grid; gap: 16px; }
      h1 { margin: 0; font-size: 24px; }
      p { margin: 0; line-height: 1.7; color: #4b5563; }
      code, pre { border: 1px solid #d1d5db; border-radius: 8px; background: #fff; }
      code { display: block; padding: 10px 12px; overflow-wrap: anywhere; }
      pre { max-height: 260px; overflow: auto; padding: 12px; white-space: pre-wrap; }
    </style>
  </head>
  <body>
    <main>
      <h1>DXM Agent Console 启动失败</h1>
      <p>桌面壳已启动，但后端服务或前端资源没有成功加载。请把下面日志路径和错误内容用于排查。</p>
      <section>
        <strong>日志文件</strong>
        <code>${escapeHtml(logPath)}</code>
      </section>
      <section>
        <strong>错误详情</strong>
        <pre>${escapeHtml(message)}</pre>
      </section>
    </main>
  </body>
</html>`
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
}

function findFreePort(preferredPort, maxAttempts = 80) {
  return new Promise((resolve, reject) => {
    let port = preferredPort

    const tryPort = () => {
      const server = net.createServer()
      server.once('error', () => {
        port += 1
        if (port >= preferredPort + maxAttempts) {
          reject(new Error(`No free loopback port from ${preferredPort}`))
          return
        }
        tryPort()
      })
      server.once('listening', () => {
        server.close(() => resolve(port))
      })
      server.listen(port, '127.0.0.1')
    }

    tryPort()
  })
}

function resolvePythonPath(repoRoot) {
  const bundledVenvPython = path.join(repoRoot, 'app', 'backend', '.venv', 'Scripts', 'python.exe')
  // Contract path: app/backend/.venv/Scripts/python.exe
  if (fs.existsSync(bundledVenvPython)) {
    return bundledVenvPython
  }
  if (app.isPackaged) {
    throw new Error(`Packaged backend Python is missing: ${bundledVenvPython}`)
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function startBackend(repoRoot, port) {
  const backendDir = path.join(repoRoot, 'app', 'backend')
  const dataDir = ensureDataDir(repoRoot)
  const backendLogPath = path.join(dataDir, 'backend.log')
  runtimeInfo.backendLogPath = backendLogPath
  // Desktop launcher log contract: data/desktop-main.log
  runtimeInfo.desktopLogPath = path.join(dataDir, 'desktop-main.log')

  const pythonPath = resolvePythonPath(repoRoot)
  const args = ['-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', String(port)]
  appendDesktopLog(`Starting backend: ${pythonPath} ${args.join(' ')}`)

  backendProcess = spawn(pythonPath, args, {
    cwd: backendDir,
    env: {
      ...process.env,
      DXM_DATA_DIR: dataDir,
      DXM_RESOURCE_ROOT: repoRoot,
      DXM_LAUNCHER_LOG_FILE: runtimeInfo.desktopLogPath,
      DXM_BACKEND_PORT: String(port),
      DXM_BACKEND_URL: `http://127.0.0.1:${port}`,
      // Desktop mode contract: DXM_DESKTOP=1
      DXM_DESKTOP: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONDONTWRITEBYTECODE: '1',
    },
    windowsHide: true,
  })

  const logStream = fs.createWriteStream(backendLogPath, { flags: 'a' })
  backendProcess.stdout.on('data', (chunk) => logStream.write(chunk))
  backendProcess.stderr.on('data', (chunk) => logStream.write(chunk))
  backendProcess.on('exit', (code, signal) => {
    appendDesktopLog(`Backend exited: code=${code ?? 'null'} signal=${signal ?? 'null'}`)
    logStream.end()
  })
  backendProcess.on('error', (error) => {
    runtimeInfo.lastError = error.message
    appendDesktopLog(`Backend spawn error: ${error.stack || error.message}`)
  })
}

function waitForHealth(apiBase, timeoutMs = 45000) {
  const startedAt = Date.now()
  return new Promise((resolve, reject) => {
    const poll = () => {
      const request = http.get(`${apiBase}/health`, (response) => {
        response.resume()
        if (response.statusCode && response.statusCode >= 200 && response.statusCode < 500) {
          resolve()
          return
        }
        retry()
      })
      request.on('error', retry)
      request.setTimeout(1500, () => {
        request.destroy()
        retry()
      })
    }

    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`Backend health check timed out: ${apiBase}/health`))
        return
      }
      setTimeout(poll, 500)
    }

    poll()
  })
}

function resolveFrontendPath(repoRoot) {
  // Frontend entry contract: app/frontend/dist/index.html
  const frontendPath = path.join(repoRoot, 'app', 'frontend', 'dist', 'index.html')
  if (!fs.existsSync(frontendPath)) {
    throw new Error('Frontend dist missing. Run npm --prefix app/frontend run build first.')
  }
  return frontendPath
}

function killBackendProcess() {
  if (!backendProcess || backendProcess.killed) return
  appendDesktopLog('Stopping backend process')
  backendProcess.kill()
  backendProcess = null
}

async function createWindow() {
  try {
    initializeDesktopLogPath()
    appendDesktopLog(`Desktop app starting packaged=${app.isPackaged} resourcesPath=${process.resourcesPath}`)
    const qaCapturePath = getQaCapturePath()
    const qaCredentialSmokePath = getQaCredentialSmokePath()
    runtimeInfo.qaCapturePath = qaCapturePath
    const repoRoot = resolveRepoRoot()
    runtimeInfo.repoRoot = repoRoot
    const port = await findFreePort(8000)
    runtimeInfo.backendPort = port
    runtimeInfo.apiBase = `http://127.0.0.1:${port}`
    logPackagedResourceStatus(repoRoot)
    startBackend(repoRoot, port)
    await waitForHealth(runtimeInfo.apiBase)

    const frontendPath = resolveFrontendPath(repoRoot)
    runtimeInfo.frontendPath = frontendPath

    mainWindow = new BrowserWindow({
      width: 1480,
      height: 940,
      minWidth: 1180,
      minHeight: 760,
      show: !qaCapturePath,
      backgroundColor: '#f6f8fb',
      title: 'DXM Agent Console',
      webPreferences: {
        preload: path.join(__dirname, 'preload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
      },
    })

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      shell.openExternal(url)
      return { action: 'deny' }
    })

    await mainWindow.loadFile(frontendPath, {
      query: {
        apiBase: runtimeInfo.apiBase,
        desktop: '1',
      },
    })
    appendDesktopLog(`Loaded frontend ${frontendPath} with apiBase=${runtimeInfo.apiBase}`)
    if (qaCredentialSmokePath) {
      runCredentialSmoke(qaCredentialSmokePath)
    }
    if (qaCapturePath) {
      await new Promise((resolve) => setTimeout(resolve, 1200))
      fs.mkdirSync(path.dirname(qaCapturePath), { recursive: true })
      const image = await mainWindow.webContents.capturePage()
      fs.writeFileSync(qaCapturePath, image.toPNG())
      appendDesktopLog(`QA capture written: ${qaCapturePath}`)
      app.quit()
    }
  } catch (error) {
    runtimeInfo.lastError = error.stack || error.message
    appendDesktopLog(`Desktop startup failed: ${runtimeInfo.lastError}`)
    killBackendProcess()
    createStartupErrorWindow(error)
  }
}

ipcMain.handle('desktop:get-runtime-info', () => ({ ...runtimeInfo }))
ipcMain.handle('desktop:dxm-credential:load', () => loadDxmCredential())
ipcMain.handle('desktop:dxm-credential:save', (_event, payload) => saveDxmCredential(payload))
ipcMain.handle('desktop:dxm-credential:clear', () => clearDxmCredential())

app.whenReady().then(() => {
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('will-quit', () => {
  killBackendProcess()
})

process.on('uncaughtException', (error) => {
  runtimeInfo.lastError = error.stack || error.message
  appendDesktopLog(`Uncaught exception: ${runtimeInfo.lastError}`)
})

process.on('unhandledRejection', (reason) => {
  runtimeInfo.lastError = reason instanceof Error ? reason.stack || reason.message : String(reason)
  appendDesktopLog(`Unhandled rejection: ${runtimeInfo.lastError}`)
})
