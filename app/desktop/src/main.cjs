const { app, BrowserWindow, ipcMain, safeStorage, shell, screen } = require('electron')
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
  canTerminateOwnedBackend,
  waitForOwnedBackendHealth,
} = require('./runtime-identity.cjs')
const {
  buildDesktopBackendEnvironment,
  classifyWritableLogFailure,
  createWritableLogOpenGate,
  createBackendShutdownController,
  createBeforeQuitController,
} = require('./backend-shutdown.cjs')
const {
  classifyLaunchArguments,
  resolveSelectedDataDir,
  selectBackendPort,
  createTcpOccupancyProbe,
  createHttpRuntimeProbe,
  inspectLegacyRuntimePorts,
} = require('./launch-policy.cjs')
const {
  createQaDeadlineController,
  createNativeExitCoordinator,
  createDesktopStartupController,
  createStartupFailurePresentation,
  createTransactionalWindow,
  discardExactWindow,
  focusExistingWindow,
  invalidateStartupForExactOwnership,
  loadStartupErrorContent,
  prepareElectronLaunchOwnership,
  registerPrimaryInstanceLifecycle,
} = require('./runtime-start.cjs')
const { resolveDesktopWindowLayout, browserBoundsEnvironment } = require('./window-layout.cjs')

app.setName('DXM Agent Console')
const nativeExitCoordinator = createNativeExitCoordinator({ app })

const normalUserDataDir = app.getPath('userData')
let launchPolicy = null
let launchPolicyValid = false
let ownsSingleInstanceLock = false
try {
  const launchOwnership = prepareElectronLaunchOwnership({
    argv: process.argv,
    normalUserDataDir,
    classifyLaunchArguments,
    createQaRoot: (qaUserDataDir) => fs.mkdirSync(qaUserDataDir, { recursive: true }),
    setUserDataPath: (qaUserDataDir) => app.setPath('userData', qaUserDataDir),
    requestSingleInstanceLock: () => app.requestSingleInstanceLock(),
    quit: () => app.quit(),
  })
  launchPolicy = launchOwnership.launchPolicy
  launchPolicyValid = launchOwnership.launchPolicyValid
  ownsSingleInstanceLock = launchOwnership.ownsSingleInstanceLock
} catch (error) {
  console.error(`Invalid desktop launch policy: ${error instanceof Error ? error.message : String(error)}`)
  app.exit(1)
}

let mainWindow = null
let backendOwnership = null
let startupController = null

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
  desktopLogWritten: false,
  dataDir: null,
  dataDirReady: false,
  qaCapturePath: null,
  qaVisibleSmokePath: null,
  lastError: null,
}

const backendShutdownController = createBackendShutdownController({
  getCurrentOwnership: () => backendOwnership,
  setCurrentOwnership: (value) => { backendOwnership = value },
  isCurrentOwnershipLive: (ownership) => canTerminateOwnedBackend({
    currentOwnership: backendOwnership,
    ownership,
    runtimeInfo,
  }),
  invalidateStartup: (ownership, eventName) => {
    invalidateStartupForExactOwnership({
      currentOwnership: ownership,
      eventOwnership: ownership,
      eventName,
      startupController,
    })
  },
  onDiagnostic: (error, stage) => {
    runtimeInfo.lastError = error instanceof Error ? error.stack || error.message : String(error)
    appendDesktopLog(`Backend shutdown ${stage}: ${runtimeInfo.lastError}`)
  },
  onTerminationFailure: (error) => {
    nativeExitCoordinator.markFailure()
    appendDesktopLog(`Backend bounded termination failed: ${rawStartupErrorDetail(error)}`)
  },
})

const beforeQuitController = createBeforeQuitController({
  app,
  requestCurrentOrPendingTermination: (options) => (
    backendShutdownController.requestCurrentOrPendingTermination(options)
  ),
  onTerminationError: (error) => {
    nativeExitCoordinator.markFailure()
    appendDesktopLog(`Backend did not close cleanly before final quit: ${rawStartupErrorDetail(error)}`)
  },
})

const qaDeadlineController = (
  launchPolicyValid
  && ownsSingleInstanceLock
  && launchPolicy?.isIsolatedQa
  && launchPolicy.deadlineMs !== null
)
  ? createQaDeadlineController({
      deadlineMs: launchPolicy.deadlineMs,
      requestFailedQuit: () => nativeExitCoordinator.requestQuit({ failed: true }),
    })
  : null

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
  if (!logPath || !runtimeInfo.dataDirReady) return false
  const line = `[${new Date().toISOString()}] ${message}\n`
  try {
    fs.appendFileSync(logPath, line, 'utf8')
    runtimeInfo.desktopLogWritten = true
    return true
  } catch (error) {
    console.error(`Desktop log write failed: ${error instanceof Error ? error.message : String(error)}`)
    return false
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

function createCodedStartupError(code, message) {
  const error = new Error(message)
  error.code = code
  return error
}

function userStartupErrorMessage(error) {
  return createStartupFailurePresentation(error).message
}

function createStartupErrorWindow(error) {
  appendDesktopLog(`Startup failure detail: ${rawStartupErrorDetail(error)}`)
  if (focusExistingWindow(() => mainWindow)) return mainWindow
  const presentation = createStartupFailurePresentation(error, {
    desktopLogWritten: runtimeInfo.desktopLogWritten,
    desktopLogPath: runtimeInfo.desktopLogPath,
  })
  const message = userStartupErrorMessage(error)
  const window = new BrowserWindow({
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
  mainWindow = window
  window.once('closed', () => {
    if (mainWindow === window) mainWindow = null
  })
  const logSection = presentation.logAvailable
    ? `<strong>日志文件</strong><code>${escapeHtml(presentation.logPath)}</code>`
    : `<strong>启动日志</strong><p>${escapeHtml(presentation.logMessage)}</p>`
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
        <p>错误码：${escapeHtml(presentation.code)}</p>
      </section>
      <section>
        <strong>处理步骤</strong>
        <ol>
          <li>先关闭当前窗口。</li>
          <li>按上方提示处理对应冲突或目录问题。</li>
          <li>重新打开完整的免安装版 exe；如果仍失败，把错误码和实际生成的日志文件发给维护人员。</li>
        </ol>
      </section>
      <section>
        ${logSection}
      </section>
      <p class="muted">${escapeHtml(presentation.logMessage)}页面不直接显示技术堆栈，避免普通用户被无关细节干扰。</p>
    </main>
  </body>
</html>`
  const richContentUrl = `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
  const fallbackHtml = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DXM Agent Console 启动失败</title><body style="margin:0;padding:32px;font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#f8fafc;color:#111827"><h1>DXM Agent Console 启动失败</h1><p>请关闭当前窗口后重新打开完整的免安装版程序。</p><p>错误码：${escapeHtml(presentation.code)}</p></body></html>`
  const fallbackContentUrl = `data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml)}`
  void loadStartupErrorContent({
    window,
    richContentUrl,
    fallbackContentUrl,
    onLoadError: (loadError, stage) => {
      appendDesktopLog(`Startup error window ${stage} content load failed: ${rawStartupErrorDetail(loadError)}`)
    },
  })
  return window
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
  const packagedPython = path.join(repoRoot, 'app', 'backend', 'python-runtime', 'python.exe')
  if (app.isPackaged) {
    if (fs.existsSync(packagedPython)) {
      return packagedPython
    }
    throw createCodedStartupError(
      'DXM_PACKAGED_BACKEND_MISSING',
      `Packaged backend Python is missing: ${packagedPython}`,
    )
  }
  const bundledVenvPython = path.join(repoRoot, 'app', 'backend', '.venv', 'Scripts', 'python.exe')
  // Contract path: app/backend/.venv/Scripts/python.exe
  if (fs.existsSync(bundledVenvPython)) {
    return bundledVenvPython
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function buildPackagedPythonEnvironment(baseEnvironment, backendDir) {
  const environment = { ...baseEnvironment }
  if (!app.isPackaged) return environment
  for (const key of Object.keys(environment)) {
    if (['PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'].includes(key.toUpperCase())) {
      delete environment[key]
    }
  }
  environment.PYTHONHOME = path.join(backendDir, 'python-runtime')
  environment.PYTHONPATH = path.join(backendDir, '.venv', 'Lib', 'site-packages')
  environment.PYTHONNOUSERSITE = '1'
  return environment
}

async function startBackend(repoRoot, port, backendInstanceId, launchIdentity) {
  const backendDir = path.join(repoRoot, 'app', 'backend')
  const {
    manifest,
    packageSha256,
    dataDir,
    workflowProfileDir,
    resourceRoot,
    visibleBrowserBounds,
  } = launchIdentity
  const backendLogPath = path.join(dataDir, 'backend.log')
  runtimeInfo.backendLogPath = backendLogPath
  // Desktop launcher log contract: data/desktop-main.log
  runtimeInfo.desktopLogPath = path.join(dataDir, 'desktop-main.log')

  const pythonPath = resolvePythonPath(repoRoot)
  const args = ['-m', 'src.desktop_server']
  appendDesktopLog(`Starting backend: ${pythonPath} ${args.join(' ')}`)

  const packagedPythonEnvironment = buildPackagedPythonEnvironment(process.env, backendDir)
  const desktopBackendEnvironment = buildDesktopBackendEnvironment({
    ...packagedPythonEnvironment,
    DXM_LAUNCHER_LOG_FILE: runtimeInfo.desktopLogPath,
    DXM_BACKEND_URL: `http://127.0.0.1:${port}`,
    DXM_WORKFLOW_ACTION_RUNTIME: 'browser_agent',
    DXM_WORKFLOW_PERSISTENT_PROFILE: '1',
    ...(visibleBrowserBounds ? { DXM_VISIBLE_BROWSER_BOUNDS: visibleBrowserBounds } : {}),
    PYTHONIOENCODING: 'utf-8',
    PYTHONDONTWRITEBYTECODE: '1',
  }, { port })
  const backendEnvironment = buildBackendEnvironment(desktopBackendEnvironment, {
    manifest,
    instanceId: backendInstanceId,
    packageSha256,
    dataDir,
    resourceRoot,
    workflowProfileDir,
  })
  let logStreamEndRequested = false
  let logStreamEnded = false
  let logStream = null
  const endLogStream = () => {
    logStreamEndRequested = true
    if (logStreamEnded || !logStream) return
    logStreamEnded = true
    logStream.end()
  }
  let ownership = null
  let setupCleanupReleased = false
  let setupLogFailure = null
  let openedLogFailureHandled = false
  const child = spawn(pythonPath, args, {
    cwd: backendDir,
    env: backendEnvironment,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  })
  try {
    const spawnSetupAuthority = backendShutdownController.registerSpawnSetup(child, {
      onClose: endLogStream,
      onChildError: (error) => {
        runtimeInfo.lastError = error.message
        appendDesktopLog(`Backend spawn error before ownership: ${error.stack || error.message}`)
      },
      onDiagnostic: (error, stage) => {
        appendDesktopLog(`Unowned backend spawn cleanup ${stage}: ${rawStartupErrorDetail(error)}`)
      },
    })
    if (!Number.isInteger(child.pid) || child.pid <= 0) {
      throw createCodedStartupError(
        'DXM_BACKEND_START_FAILED',
        'Backend spawn did not return a valid child pid',
      )
    }
    if (!child.stdin || !child.stdout || !child.stderr
      || typeof child.stdin.write !== 'function'
      || typeof child.stdout.on !== 'function'
      || typeof child.stderr.on !== 'function') {
      throw createCodedStartupError(
        'DXM_BACKEND_START_FAILED',
        'Backend spawn did not provide exact stdin/stdout/stderr pipes',
      )
    }
    logStream = fs.createWriteStream(backendLogPath, { flags: 'a' })
    const logOpenGate = createWritableLogOpenGate(logStream, {
      onError: (error, phase) => {
        const failureScope = classifyWritableLogFailure({
          phase,
          ownership,
          currentOwnership: backendOwnership,
          setupCleanupReleased,
        })
        if (failureScope === 'stale') {
          appendDesktopLog(`Ignored stale backend log stream error: ${rawStartupErrorDetail(error)}`)
          return
        }
        if (failureScope === 'setup') {
          if (!setupLogFailure) setupLogFailure = error
          appendDesktopLog(`Backend log stream failed during ownership setup: ${rawStartupErrorDetail(error)}`)
          return
        }
        if (failureScope === 'exact-current' && openedLogFailureHandled) {
          appendDesktopLog(`Additional backend log stream error: ${rawStartupErrorDetail(error)}`)
          return
        }
        if (failureScope === 'exact-current') openedLogFailureHandled = true
        runtimeInfo.lastError = rawStartupErrorDetail(error)
        nativeExitCoordinator.markFailure()
        appendDesktopLog(`Backend log stream ${phase} failed: ${runtimeInfo.lastError}`)
        if (failureScope === 'exact-current') {
          try {
            startupController?.invalidateRuntime?.('stopped')
          } catch (invalidationError) {
            appendDesktopLog(
              `Backend log failure invalidation failed: ${rawStartupErrorDetail(invalidationError)}`,
            )
          }
          try {
            const termination = backendShutdownController.requestCurrentOrPendingTermination({
              reason: 'backend-log-error',
            })
            termination.catch((terminationError) => {
              nativeExitCoordinator.markFailure()
              appendDesktopLog(
                `Backend log failure termination failed: ${rawStartupErrorDetail(terminationError)}`,
              )
            })
          } catch (terminationError) {
            nativeExitCoordinator.markFailure()
            appendDesktopLog(
              `Backend log failure termination failed: ${rawStartupErrorDetail(terminationError)}`,
            )
          }
        }
      },
      onDiagnostic: (error, stage) => {
        nativeExitCoordinator.markFailure()
        appendDesktopLog(`Backend log gate ${stage}: ${rawStartupErrorDetail(error)}`)
      },
    })
    if (logStreamEndRequested) endLogStream()
    await logOpenGate.waitUntilOpen()
    if (setupLogFailure) throw setupLogFailure
    child.stdout.on('data', (chunk) => logStream.write(chunk))
    child.stderr.on('data', (chunk) => logStream.write(chunk))

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
    runtimeInfo.backendPid = child.pid
    runtimeInfo.backendInstanceId = backendInstanceId
    runtimeInfo.runtimeIdentity = null
    backendShutdownController.handoffSpawnSetup(spawnSetupAuthority, ownership, {
      endLogStream,
      onChildEvent: (eventName, code, signal) => {
        appendDesktopLog(`Backend ${eventName}: code=${code ?? 'null'} signal=${signal ?? 'null'}`)
      },
    })
    setupCleanupReleased = true
    await backendShutdownController.startParentChannel(ownership)
    return ownership
  } catch (startupError) {
    let cleanupError = null
    try {
      const exactCleanup = startupError?.terminationPromise
        || ownership?.terminationPromise
        || backendShutdownController.requestCurrentOrPendingTermination({
          reason: 'startup-construction',
        })
      await exactCleanup
    } catch (error) {
      cleanupError = error
    }
    if (cleanupError) {
      nativeExitCoordinator.markFailure()
      appendDesktopLog(`Backend startup cleanup failed: ${rawStartupErrorDetail(cleanupError)}`)
      const combinedError = new AggregateError(
        [startupError, cleanupError],
        `Backend startup failed and exact child cleanup did not complete: ${startupError.message}`,
      )
      combinedError.code = cleanupError.code || startupError.code || 'DXM_BACKEND_START_FAILED'
      throw combinedError
    }
    throw startupError
  }
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
    throw createCodedStartupError(
      'DXM_FRONTEND_MISSING',
      'Frontend dist missing. Run npm --prefix app/frontend run build first.',
    )
  }
  return frontendPath
}

function requestBackendTermination(reason) {
  const termination = backendShutdownController.requestCurrentOrPendingTermination({ reason })
  termination.catch((error) => {
    nativeExitCoordinator.markFailure()
    appendDesktopLog(`Exact backend termination failed: ${rawStartupErrorDetail(error)}`)
  })
  return termination
}

async function startDesktopRuntime() {
  const qaCapturePath = launchPolicy.smokeOutputs.capture
  const qaCredentialSmokePath = launchPolicy.smokeOutputs.credential
  const qaVisibleSmokePath = launchPolicy.smokeOutputs.visible
  runtimeInfo.qaCapturePath = qaCapturePath
  runtimeInfo.qaVisibleSmokePath = qaVisibleSmokePath

  const repoRoot = resolveRepoRoot()
  const desktopWindowLayout = resolveDesktopWindowLayout(screen.getPrimaryDisplay().workArea)
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
    isPackaged: app.isPackaged,
    isPortFree: isLoopbackPortFree,
  })
  if (!launchPolicy.isIsolatedQa) {
    await inspectLegacyRuntimePorts({
      dataDir,
      tcpProbe: tcpOccupancyProbe,
      httpProbe: httpRuntimeProbe,
      requireFixedPortFree: !(app.isPackaged && port !== 8000),
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
  const ownership = await startBackend(repoRoot, port, backendInstanceId, {
    manifest: launchManifest,
    packageSha256,
    dataDir,
    workflowProfileDir,
    resourceRoot: repoRoot,
    visibleBrowserBounds: browserBoundsEnvironment(desktopWindowLayout),
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
    desktopWindowLayout,
  })
}

async function createMainWindow(runtime) {
  if (focusExistingWindow(() => mainWindow)) return mainWindow
  return createTransactionalWindow({
    getCurrentWindow: () => mainWindow,
    setCurrentWindow: (value) => { mainWindow = value },
    createWindow: () => {
      const bounds = runtime.desktopWindowLayout.console
      const window = new BrowserWindow({
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        minWidth: 960,
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
      window.once('closed', () => {
        if (mainWindow === window) mainWindow = null
      })
      window.webContents.setWindowOpenHandler(({ url }) => {
        shell.openExternal(url)
        return { action: 'deny' }
      })
      return window
    },
    initializeWindow: async (window) => {
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
        setImmediate(() => nativeExitCoordinator.requestQuit())
      }
      if (runtime.qaVisibleSmokePath) {
        await new Promise((resolve) => setTimeout(resolve, 900))
        const result = {
          ok: Boolean(!window.isDestroyed() && window.isVisible()),
          windowVisible: Boolean(!window.isDestroyed() && window.isVisible()),
          windowFocused: Boolean(!window.isDestroyed() && window.isFocused()),
          windowBounds: window.isDestroyed() ? null : window.getBounds(),
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
          setImmediate(() => nativeExitCoordinator.requestQuit({ failed: true }))
        } else {
          setImmediate(() => nativeExitCoordinator.requestQuit())
        }
      }
    },
  })
}

startupController = launchPolicyValid && ownsSingleInstanceLock
  ? createDesktopStartupController({
      startRuntime: startDesktopRuntime,
      createMainWindow,
      discardMainWindow: (window) => discardExactWindow({
        window,
        getCurrentWindow: () => mainWindow,
        setCurrentWindow: (value) => { mainWindow = value },
      }),
    })
  : null

function handleDesktopStartupFailure(error) {
  runtimeInfo.lastError = error instanceof Error ? error.stack || error.message : String(error)
  appendDesktopLog(`Desktop startup failed: ${runtimeInfo.lastError}`)
  requestBackendTermination('startup-failure')
  createStartupErrorWindow(error)
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

qaDeadlineController?.arm()
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
  onBeforeQuit: (event) => beforeQuitController.handleBeforeQuit(event),
  onWillQuit: () => {
    qaDeadlineController?.cancel()
    nativeExitCoordinator.finalizeAfterCleanup()
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
