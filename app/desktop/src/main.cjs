const { app, BrowserWindow, ipcMain, safeStorage, shell } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const crypto = require('node:crypto')
const { spawn } = require('node:child_process')
const desktopPackage = require('../package.json')
const {
  createDirectLaunchManifest,
  resolveLaunchManifest,
  resolvePortablePackageSha,
  createExpectedRuntimeIdentity,
  buildBackendEnvironment,
  createBackendOwnership,
  terminateExactOwnedBackend,
  createBackendChildLifecycle,
  waitForOwnedBackendHealth,
} = require('./runtime-identity.cjs')
const {
  classifyLaunchArguments,
  resolveSelectedDataDir,
  selectBackendPort,
  createTcpOccupancyProbe,
  createHttpRuntimeProbe,
  inspectLegacyRuntimePorts,
} = require('./launch-policy.cjs')
const {
  createDesktopStartupController,
  focusExistingWindow,
  registerPrimaryInstanceLifecycle,
} = require('./runtime-start.cjs')

app.setName('DXM Agent Console')

const normalUserDataDir = app.getPath('userData')
let launchPolicy = null
let launchPolicyValid = false
let ownsSingleInstanceLock = false
try {
  launchPolicy = classifyLaunchArguments({
    argv: process.argv,
    normalUserDataDir,
  })
  if (launchPolicy.isIsolatedQa) {
    fs.mkdirSync(launchPolicy.qaUserDataDir, { recursive: true })
    app.setPath('userData', launchPolicy.qaUserDataDir)
  }
  launchPolicyValid = true
  ownsSingleInstanceLock = app.requestSingleInstanceLock()
  if (!ownsSingleInstanceLock) app.quit()
} catch (error) {
  console.error(`Invalid desktop launch policy: ${error instanceof Error ? error.message : String(error)}`)
  app.exit(1)
}

let mainWindow = null
let backendOwnership = null

const runtimeInfo = {
  repoRoot: null,
  backendPort: null,
  backendPid: null,
  backendInstanceId: null,
  runtimeIdentity: null,
  apiBase: null,
  frontendPath: null,
  backendLogPath: null,
  desktopLogPath: null,
  dataDir: null,
  dataDirReady: false,
  qaCapturePath: null,
  qaVisibleSmokePath: null,
  lastError: null,
}

function initializeDesktopLogPath() {
  if (!runtimeInfo.dataDir) return
  runtimeInfo.desktopLogPath = path.join(runtimeInfo.dataDir, 'desktop-main.log')
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

function ensureDataDir(dataDir) {
  fs.mkdirSync(dataDir, { recursive: true })
  runtimeInfo.dataDirReady = true
  return dataDir
}

function getDesktopDataDir() {
  if (!runtimeInfo.dataDir) throw new Error('Desktop runtime data directory is not selected')
  const dataDir = runtimeInfo.dataDir
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
  if (!logPath || !runtimeInfo.dataDirReady) return
  const line = `[${new Date().toISOString()}] ${message}\n`
  try {
    fs.appendFileSync(logPath, line, 'utf8')
  } catch (error) {
    console.error(`Desktop log write failed: ${error instanceof Error ? error.message : String(error)}`)
  }
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

function rawStartupErrorDetail(error) {
  return error instanceof Error ? error.stack || error.message : String(error)
}

function userStartupErrorMessage(error) {
  const raw = rawStartupErrorDetail(error)
  const normalized = raw.toLowerCase()
  const conflict = error?.conflict && typeof error.conflict === 'object' ? error.conflict : null
  if (normalized.includes('packaged backend python is missing') || normalized.includes('resources')) {
    return '免安装目录不完整，后端运行资源没有找到。请重新解压或重新复制完整的 DXM Agent Console 免安装版目录后再启动。'
  }
  if (normalized.includes('same data directory')) {
    const facts = conflict ? [
      Number.isInteger(conflict.port) ? `端口 ${conflict.port}` : null,
      conflict.pid === null || conflict.pid === undefined ? null : `进程 ${conflict.pid}`,
      conflict.instanceId ? `实例 ${conflict.instanceId}` : null,
    ].filter(Boolean) : []
    const factText = facts.length ? `（${facts.join('，')}）` : ''
    return `已有 DXM Agent Console 正在使用同一数据目录${factText}。请先从原窗口正常退出，再重新打开；系统不会自动接管或结束旧进程。`
  }
  if (normalized.includes('loopback port 8000')) {
    return '本机 8000 端口已被占用。请先关闭占用该端口的旧控制台或其他程序，再重新打开；系统不会自动结束该进程。'
  }
  if (normalized.includes('no free loopback port') || normalized.includes('eaddrinuse')) {
    return '本机服务端口被占用。请关闭旧的 DXM Agent Console 窗口或后台进程，然后重新打开。'
  }
  if (normalized.includes('frontend') || normalized.includes('index.html')) {
    return '桌面页面资源没有加载成功。请确认免安装目录没有缺文件，并重新打开程序。'
  }
  if (normalized.includes('backend') || normalized.includes('uvicorn') || normalized.includes('python')) {
    return '后端服务启动失败。请关闭旧窗口后重试；如果仍失败，把日志文件发给维护人员排查。'
  }
  return '工作台启动失败。系统没有执行保存或发布动作；请关闭旧窗口后重新打开，如果仍失败请查看日志文件。'
}

function createStartupErrorWindow(error) {
  appendDesktopLog(`Startup failure detail: ${rawStartupErrorDetail(error)}`)
  const message = userStartupErrorMessage(error)
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
      ol { margin: 0; padding-left: 20px; color: #374151; line-height: 1.8; }
      code, pre { border: 1px solid #d1d5db; border-radius: 8px; background: #fff; }
      code { display: block; padding: 10px 12px; overflow-wrap: anywhere; }
      .notice { border: 1px solid #fecaca; background: #fff1f2; color: #991b1b; border-radius: 10px; padding: 14px; }
      .muted { color: #64748b; font-size: 13px; }
    </style>
  </head>
  <body>
    <main>
      <h1>DXM Agent Console 启动失败</h1>
      <p>桌面壳已启动，但后端服务或前端资源没有成功加载。</p>
      <section class="notice">
        <strong>发生了什么</strong>
        <p>${escapeHtml(message)}</p>
      </section>
      <section>
        <strong>处理步骤</strong>
        <ol>
          <li>先关闭当前窗口。</li>
          <li>确认没有旧的 DXM Agent Console 或旧浏览器后台进程。</li>
          <li>重新打开完整的免安装版 exe；如果仍失败，把下面日志文件发给维护人员。</li>
        </ol>
      </section>
      <section>
        <strong>日志文件</strong>
        <code>${escapeHtml(logPath)}</code>
      </section>
      <p class="muted">原始错误已写入日志文件，页面不直接显示技术堆栈，避免普通用户被无关细节干扰。</p>
    </main>
  </body>
</html>`
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
}

const tcpOccupancyProbe = createTcpOccupancyProbe()
const httpRuntimeProbe = createHttpRuntimeProbe()

async function isLoopbackPortFree(port, { signal } = {}) {
  return await tcpOccupancyProbe({
    host: '127.0.0.1',
    port,
    signal,
  }) === false
}

function createBackendInstanceId() {
  return `desktop-${Date.now().toString(36)}-${crypto.randomBytes(6).toString('hex')}`
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

function startBackend(repoRoot, port, backendInstanceId, launchIdentity) {
  const backendDir = path.join(repoRoot, 'app', 'backend')
  const {
    manifest,
    packageSha256,
    dataDir,
    workflowProfileDir,
    resourceRoot,
  } = launchIdentity
  const backendLogPath = path.join(dataDir, 'backend.log')
  runtimeInfo.backendLogPath = backendLogPath
  // Desktop launcher log contract: data/desktop-main.log
  runtimeInfo.desktopLogPath = path.join(dataDir, 'desktop-main.log')

  const pythonPath = resolvePythonPath(repoRoot)
  const args = ['-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', String(port)]
  appendDesktopLog(`Starting backend: ${pythonPath} ${args.join(' ')}`)

  const backendEnvironment = buildBackendEnvironment({
    ...process.env,
    DXM_LAUNCHER_LOG_FILE: runtimeInfo.desktopLogPath,
    DXM_BACKEND_PORT: String(port),
    DXM_BACKEND_URL: `http://127.0.0.1:${port}`,
    // Desktop mode contract: DXM_DESKTOP=1
    DXM_DESKTOP: '1',
    DXM_WORKFLOW_ACTION_RUNTIME: 'browser_agent',
    DXM_WORKFLOW_PERSISTENT_PROFILE: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONDONTWRITEBYTECODE: '1',
  }, {
    manifest,
    instanceId: backendInstanceId,
    packageSha256,
    dataDir,
    resourceRoot,
    workflowProfileDir,
  })
  const child = spawn(pythonPath, args, {
    cwd: backendDir,
    env: backendEnvironment,
    windowsHide: true,
  })

  const logStream = fs.createWriteStream(backendLogPath, { flags: 'a' })
  let logStreamEnded = false
  const endLogStream = () => {
    if (logStreamEnded) return
    logStreamEnded = true
    logStream.end()
  }
  child.stdout.on('data', (chunk) => logStream.write(chunk))
  child.stderr.on('data', (chunk) => logStream.write(chunk))
  let ownership = null
  child.on('error', (error) => {
    if (!Number.isInteger(child.pid) || child.pid <= 0) {
      runtimeInfo.lastError = error.message
      endLogStream()
    } else if (ownership && backendOwnership === ownership) {
      runtimeInfo.lastError = error.message
    }
    appendDesktopLog(`Backend spawn error: ${error.stack || error.message}`)
  })
  if (!Number.isInteger(child.pid) || child.pid <= 0) {
    endLogStream()
    throw new Error('Backend spawn did not return a valid child pid')
  }
  const expectedIdentity = createExpectedRuntimeIdentity({
    manifest,
    instanceId: backendInstanceId,
    packageSha256,
    backendPid: child.pid,
    dataDir,
    workflowProfileDir,
    resourceRoot,
  })
  ownership = createBackendOwnership({ child, instanceId: backendInstanceId, expectedIdentity })
  backendOwnership = ownership
  runtimeInfo.backendPid = child.pid
  runtimeInfo.backendInstanceId = backendInstanceId
  runtimeInfo.runtimeIdentity = null

  const lifecycle = createBackendChildLifecycle({
    ownership,
    getCurrentOwnership: () => backendOwnership,
    setCurrentOwnership: (value) => { backendOwnership = value },
    endLogStream,
  })
  const finalizeChild = (eventName, code, signal) => {
    appendDesktopLog(`Backend ${eventName}: code=${code ?? 'null'} signal=${signal ?? 'null'}`)
    lifecycle.handle(eventName)
  }
  child.on('exit', (code, signal) => finalizeChild('exit', code, signal))
  child.on('close', (code, signal) => finalizeChild('close', code, signal))
  return ownership
}

function waitForHealth(apiBase, timeoutMs = 45000, ownership) {
  return waitForOwnedBackendHealth({
    apiBase,
    timeoutMs,
    ownership,
    getCurrentOwnership: () => backendOwnership,
    onVerified: (identity) => { runtimeInfo.runtimeIdentity = identity },
    log: (message) => appendDesktopLog(message),
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
  const ownership = backendOwnership
  if (!ownership) return
  const processToStop = ownership.child
  const attempted = terminateExactOwnedBackend({
    currentOwnership: backendOwnership,
    ownership,
    runtimeInfo,
  })
  if (!attempted) return
  appendDesktopLog(`Stop requested for exact backend child handle pid=${processToStop.pid ?? 'unknown'}`)
}

async function startDesktopRuntime() {
  const qaCapturePath = launchPolicy.smokeOutputs.capture
  const qaCredentialSmokePath = launchPolicy.smokeOutputs.credential
  const qaVisibleSmokePath = launchPolicy.smokeOutputs.visible
  runtimeInfo.qaCapturePath = qaCapturePath
  runtimeInfo.qaVisibleSmokePath = qaVisibleSmokePath

  const repoRoot = resolveRepoRoot()
  const dataDir = resolveSelectedDataDir({
    isIsolatedQa: launchPolicy.isIsolatedQa,
    isPackaged: app.isPackaged,
    repoRoot,
    userDataDir: app.getPath('userData'),
  })
  runtimeInfo.repoRoot = repoRoot
  runtimeInfo.dataDir = dataDir
  const port = await selectBackendPort({
    isIsolatedQa: launchPolicy.isIsolatedQa,
    isPortFree: isLoopbackPortFree,
  })
  if (!launchPolicy.isIsolatedQa) {
    await inspectLegacyRuntimePorts({
      dataDir,
      tcpProbe: tcpOccupancyProbe,
      httpProbe: httpRuntimeProbe,
    })
  }

  ensureDataDir(dataDir)
  initializeDesktopLogPath()
  appendDesktopLog(`Desktop app starting packaged=${app.isPackaged} resourcesPath=${process.resourcesPath}`)
  const backendInstanceId = createBackendInstanceId()
  const workflowProfileDir = path.join(dataDir, 'browser_profiles', 'dxm_workflow')
  const launchManifest = resolveLaunchManifest({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    packageVersion: app.getVersion(),
    explicitManifestFile: process.env.DXM_BUILD_MANIFEST_FILE || null,
    directManifestFactory: () => createDirectLaunchManifest({
      repoRoot,
      packageVersion: app.getVersion(),
      buildId: `direct-${backendInstanceId}`,
    }),
  })
  const packageSha256 = await resolvePortablePackageSha({
    isPackaged: app.isPackaged,
    portableExecutableFile: process.env.PORTABLE_EXECUTABLE_FILE,
    portableExecutableDir: process.env.PORTABLE_EXECUTABLE_DIR,
    portableExecutableAppFilename: process.env.PORTABLE_EXECUTABLE_APP_FILENAME,
    expectedPortableAppFilename: desktopPackage.name,
    innerExecutablePath: process.execPath,
  })
  runtimeInfo.backendPort = port
  runtimeInfo.apiBase = `http://127.0.0.1:${port}`
  logPackagedResourceStatus(repoRoot)
  const ownership = startBackend(repoRoot, port, backendInstanceId, {
    manifest: launchManifest,
    packageSha256,
    dataDir,
    workflowProfileDir,
    resourceRoot: repoRoot,
  })
  await waitForHealth(runtimeInfo.apiBase, 45000, ownership)

  const frontendPath = resolveFrontendPath(repoRoot)
  runtimeInfo.frontendPath = frontendPath
  return Object.freeze({
    apiBase: runtimeInfo.apiBase,
    frontendPath,
    qaCapturePath,
    qaCredentialSmokePath,
    qaVisibleSmokePath,
  })
}

async function createMainWindow(runtime) {
  if (focusExistingWindow(() => mainWindow)) return mainWindow
  const window = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1180,
    minHeight: 760,
    show: !runtime.qaCapturePath,
    backgroundColor: '#f6f8fb',
    title: 'DXM Agent Console',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow = window
  window.once('closed', () => {
    if (mainWindow === window) mainWindow = null
  })

  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  await window.loadFile(runtime.frontendPath, {
    query: {
      apiBase: runtime.apiBase,
      desktop: '1',
    },
  })
  appendDesktopLog(`Loaded frontend ${runtime.frontendPath} with apiBase=${runtime.apiBase}`)
  if (runtime.qaCredentialSmokePath) {
    runCredentialSmoke(runtime.qaCredentialSmokePath)
  }
  if (runtime.qaCapturePath) {
    await new Promise((resolve) => setTimeout(resolve, 1200))
    fs.mkdirSync(path.dirname(runtime.qaCapturePath), { recursive: true })
    const image = await window.webContents.capturePage()
    fs.writeFileSync(runtime.qaCapturePath, image.toPNG())
    appendDesktopLog(`QA capture written: ${runtime.qaCapturePath}`)
    app.quit()
  }
  if (runtime.qaVisibleSmokePath) {
    await new Promise((resolve) => setTimeout(resolve, 900))
    const result = {
      ok: Boolean(mainWindow && mainWindow.isVisible()),
      windowVisible: Boolean(mainWindow && mainWindow.isVisible()),
      windowFocused: Boolean(mainWindow && mainWindow.isFocused()),
      windowBounds: mainWindow ? mainWindow.getBounds() : null,
      backendPort: runtimeInfo.backendPort,
      apiBase: runtimeInfo.apiBase,
      frontendPath: runtimeInfo.frontendPath,
      desktopLogPath: runtimeInfo.desktopLogPath,
      backendLogPath: runtimeInfo.backendLogPath,
      checkedAt: new Date().toISOString(),
    }
    fs.mkdirSync(path.dirname(runtime.qaVisibleSmokePath), { recursive: true })
    fs.writeFileSync(runtime.qaVisibleSmokePath, JSON.stringify(result, null, 2))
    appendDesktopLog(`QA visible smoke written: ${runtime.qaVisibleSmokePath} visible=${result.windowVisible}`)
    if (!result.ok) {
      app.exit(1)
    }
    app.quit()
  }
  return window
}

const startupController = launchPolicyValid && ownsSingleInstanceLock
  ? createDesktopStartupController({
      startRuntime: startDesktopRuntime,
      createMainWindow,
    })
  : null
let startupFailureShown = false

function handleDesktopStartupFailure(error) {
  runtimeInfo.lastError = error instanceof Error ? error.stack || error.message : String(error)
  appendDesktopLog(`Desktop startup failed: ${runtimeInfo.lastError}`)
  killBackendProcess()
  if (!startupFailureShown) {
    startupFailureShown = true
    createStartupErrorWindow(error)
  }
}

if (ownsSingleInstanceLock) {
  ipcMain.handle('desktop:get-runtime-info', () => ({
    ...runtimeInfo,
    runtimeIdentity: runtimeInfo.runtimeIdentity ? { ...runtimeInfo.runtimeIdentity } : null,
  }))
  ipcMain.handle('desktop:dxm-credential:load', () => loadDxmCredential())
  ipcMain.handle('desktop:dxm-credential:save', (_event, payload) => saveDxmCredential(payload))
  ipcMain.handle('desktop:dxm-credential:clear', () => clearDxmCredential())
}

registerPrimaryInstanceLifecycle({
  launchPolicyValid,
  ownsSingleInstanceLock,
  app,
  startupController,
  hasWindows: () => BrowserWindow.getAllWindows().length > 0,
  focusWindow: () => focusExistingWindow(() => mainWindow),
  handleFailure: handleDesktopStartupFailure,
  onWindowAllClosed: () => {
    if (process.platform !== 'darwin') app.quit()
  },
  onWillQuit: () => {
    killBackendProcess()
  },
})

process.on('uncaughtException', (error) => {
  runtimeInfo.lastError = error.stack || error.message
  appendDesktopLog(`Uncaught exception: ${runtimeInfo.lastError}`)
})

process.on('unhandledRejection', (reason) => {
  runtimeInfo.lastError = reason instanceof Error ? reason.stack || reason.message : String(reason)
  appendDesktopLog(`Unhandled rejection: ${runtimeInfo.lastError}`)
})
