function createRuntimeStarter(startRuntime) {
  if (typeof startRuntime !== 'function') throw new TypeError('startRuntime must be a function')
  let startPromise = null
  return function startRuntimeOnce() {
    if (!startPromise) startPromise = Promise.resolve().then(startRuntime)
    return startPromise
  }
}

function focusExistingWindow(getWindow) {
  const window = typeof getWindow === 'function' ? getWindow() : null
  if (!window || window.isDestroyed?.()) return false
  if (window.isMinimized?.()) window.restore()
  window.show?.()
  window.focus?.()
  return true
}

const STARTUP_FAILURE_MESSAGES = Object.freeze({
  DXM_PACKAGED_BACKEND_MISSING: '免安装目录不完整，后端运行资源没有找到。请重新解压或重新复制完整的 DXM Agent Console 免安装版目录后再启动。',
  DXM_FRONTEND_MISSING: '桌面页面资源没有加载成功。请确认免安装目录没有缺文件，并重新打开程序。',
  DXM_QA_PORT_UNAVAILABLE: '隔离验收环境没有找到可用的本机服务端口。请关闭本次验收窗口后重试。',
  DXM_PORT_8000_OCCUPIED: '本机 8000 端口已被占用。请先确认并关闭占用该端口的程序，再重新打开；系统不会自动结束该进程。',
  DXM_PORT_8000_UNCERTAIN: '无法确认本机 8000 端口可用。为避免连接到错误服务，本次启动已停止；请稍后重试或联系维护人员。',
  DXM_BACKEND_START_FAILED: '后端服务启动失败。请重新打开；如果仍失败，把本页错误码和实际生成的日志文件发给维护人员排查。',
  DXM_STARTUP_FAILED: '工作台启动失败。系统没有执行保存或发布动作；请关闭当前窗口后重新打开。',
})

function normalizeStartupFailureCode(error) {
  const code = typeof error?.code === 'string' ? error.code.trim() : ''
  if (code === 'DXM_SAME_DATA_RUNTIME' || Object.hasOwn(STARTUP_FAILURE_MESSAGES, code)) return code
  return 'DXM_STARTUP_FAILED'
}

function createStartupFailurePresentation(error, {
  desktopLogWritten = false,
  desktopLogPath = null,
} = {}) {
  const code = normalizeStartupFailureCode(error)
  let message = STARTUP_FAILURE_MESSAGES[code] || STARTUP_FAILURE_MESSAGES.DXM_STARTUP_FAILED
  if (code === 'DXM_SAME_DATA_RUNTIME') {
    const conflict = error?.conflict && typeof error.conflict === 'object' ? error.conflict : null
    const facts = conflict ? [
      Number.isInteger(conflict.port) ? `端口 ${conflict.port}` : null,
      conflict.pid === null || conflict.pid === undefined ? null : `进程 ${conflict.pid}`,
      conflict.instanceId ? `实例 ${conflict.instanceId}` : null,
    ].filter(Boolean) : []
    const factText = facts.length ? `（${facts.join('，')}）` : ''
    message = `已有 DXM Agent Console 正在使用同一数据目录${factText}。请先从原窗口正常退出，再重新打开；系统不会自动接管或结束旧进程。`
  }
  const logAvailable = desktopLogWritten === true && typeof desktopLogPath === 'string' && desktopLogPath.length > 0
  return Object.freeze({
    code,
    message,
    logAvailable,
    logPath: logAvailable ? desktopLogPath : null,
    logMessage: logAvailable
      ? '原始错误已写入以下启动日志。'
      : '此次失败发生在启动日志可写之前，未生成启动日志。',
  })
}

function prepareElectronLaunchOwnership({
  argv,
  normalUserDataDir,
  classifyLaunchArguments,
  createQaRoot,
  setUserDataPath,
  requestSingleInstanceLock,
  quit,
}) {
  if (typeof classifyLaunchArguments !== 'function') throw new TypeError('classifyLaunchArguments must be a function')
  if (typeof requestSingleInstanceLock !== 'function') throw new TypeError('requestSingleInstanceLock must be a function')
  const launchPolicy = classifyLaunchArguments({ argv, normalUserDataDir })
  if (launchPolicy.isIsolatedQa) {
    if (typeof createQaRoot !== 'function' || typeof setUserDataPath !== 'function') {
      throw new TypeError('isolated QA launch ownership requires path preparation functions')
    }
    createQaRoot(launchPolicy.qaUserDataDir)
    setUserDataPath(launchPolicy.qaUserDataDir)
  }
  const ownsSingleInstanceLock = requestSingleInstanceLock() === true
  if (!ownsSingleInstanceLock && typeof quit === 'function') quit()
  return Object.freeze({
    launchPolicy,
    launchPolicyValid: true,
    ownsSingleInstanceLock,
  })
}

async function createTransactionalWindow({
  createWindow,
  getCurrentWindow,
  setCurrentWindow,
  initializeWindow,
}) {
  if (typeof createWindow !== 'function' || typeof getCurrentWindow !== 'function'
    || typeof setCurrentWindow !== 'function' || typeof initializeWindow !== 'function') {
    throw new TypeError('transactional window dependencies are required')
  }
  const window = createWindow()
  setCurrentWindow(window)
  try {
    await initializeWindow(window)
    return window
  } catch (error) {
    discardExactWindow({ window, getCurrentWindow, setCurrentWindow })
    throw error
  }
}

function discardExactWindow({ window, getCurrentWindow, setCurrentWindow }) {
  if (!window || typeof getCurrentWindow !== 'function' || typeof setCurrentWindow !== 'function') return false
  try {
    if (!window.isDestroyed?.() && typeof window.destroy === 'function') window.destroy()
  } catch {
    // Window cleanup must not replace the startup failure that triggered it.
  }
  if (getCurrentWindow() === window) setCurrentWindow(null)
  return true
}

function invalidateStartupForExactOwnership({
  currentOwnership,
  eventOwnership,
  eventName,
  startupController,
}) {
  if (!currentOwnership || currentOwnership !== eventOwnership) return false
  if (![
    'exit',
    'close',
    'kill',
    'child-error',
    'stdin-error',
    'stdin-close',
  ].includes(eventName)) return false
  if (typeof startupController?.invalidateRuntime !== 'function') return false
  startupController.invalidateRuntime('stopped')
  return true
}

function createQaDeadlineController({
  deadlineMs,
  requestFailedQuit,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  if (deadlineMs !== null && (!Number.isInteger(deadlineMs) || deadlineMs < 1)) {
    throw new TypeError('QA deadline must be null or a positive integer')
  }
  if (typeof requestFailedQuit !== 'function'
    || typeof setTimer !== 'function'
    || typeof clearTimer !== 'function') {
    throw new TypeError('QA deadline dependencies must be functions')
  }
  let timer = null
  let canceled = false
  let fired = false

  const fire = () => {
    if (canceled || fired) return false
    fired = true
    timer = null
    requestFailedQuit()
    return true
  }

  return Object.freeze({
    arm() {
      if (deadlineMs === null || canceled || fired || timer !== null) return false
      timer = setTimer(fire, deadlineMs)
      return true
    },
    cancel() {
      if (deadlineMs === null || canceled || fired || timer === null) return false
      canceled = true
      clearTimer(timer)
      timer = null
      return true
    },
  })
}

function createNativeExitCoordinator({ app }) {
  if (!app || typeof app.quit !== 'function' || typeof app.exit !== 'function') {
    throw new TypeError('app.quit and app.exit must be functions')
  }
  let pendingNativeExitCode = null
  let quitRequested = false
  let nativeExitFinalized = false

  return Object.freeze({
    requestQuit({ failed = false } = {}) {
      if (failed) pendingNativeExitCode = 1
      if (quitRequested || nativeExitFinalized) return false
      quitRequested = true
      app.quit()
      return true
    },
    markFailure() {
      if (pendingNativeExitCode === 1) return false
      pendingNativeExitCode = 1
      return true
    },
    finalizeAfterCleanup() {
      if (pendingNativeExitCode === null || nativeExitFinalized) return false
      nativeExitFinalized = true
      app.exit(pendingNativeExitCode)
      return true
    },
  })
}

async function loadStartupErrorContent({
  window,
  richContentUrl,
  fallbackContentUrl,
  onLoadError = () => {},
}) {
  if (!window || typeof window.loadURL !== 'function') throw new TypeError('window.loadURL must be a function')
  const reportLoadError = (error, stage) => {
    try {
      onLoadError(error, stage)
    } catch {
      // Error reporting is secondary to containing the BrowserWindow load rejection.
    }
  }
  try {
    await window.loadURL(richContentUrl)
    return 'rich'
  } catch (error) {
    reportLoadError(error, 'rich')
  }
  try {
    await window.loadURL(fallbackContentUrl)
    return 'fallback'
  } catch (error) {
    reportLoadError(error, 'fallback')
    return 'failed'
  }
}

function createDesktopStartupController({ startRuntime, createMainWindow, discardMainWindow = () => {} }) {
  if (typeof createMainWindow !== 'function') throw new TypeError('createMainWindow must be a function')
  if (typeof discardMainWindow !== 'function') throw new TypeError('discardMainWindow must be a function')
  const startRuntimeOnce = createRuntimeStarter(startRuntime)
  let verifiedRuntime = null
  let readyPromise = null
  let state = 'idle'

  return Object.freeze({
    startRuntimeOnce,
    onReady() {
      if (!readyPromise) {
        state = 'starting'
        readyPromise = startRuntimeOnce().then(async (runtime) => {
          const window = await createMainWindow(runtime)
          if (state !== 'starting') {
            discardMainWindow(window)
            throw new Error(`Desktop startup was invalidated while creating the first window: ${state}`)
          }
          verifiedRuntime = runtime
          state = 'ready'
          return runtime
        }).catch((error) => {
          verifiedRuntime = null
          if (state === 'starting') state = 'failed'
          throw error
        })
      }
      return readyPromise
    },
    async onActivate({ hasWindows }) {
      if (hasWindows) return false
      if (state !== 'ready' || !verifiedRuntime) return false
      await createMainWindow(verifiedRuntime)
      return true
    },
    invalidateRuntime(nextState = 'stopped') {
      if (nextState !== 'failed' && nextState !== 'stopped') {
        throw new Error(`Invalid desktop startup terminal state: ${nextState}`)
      }
      verifiedRuntime = null
      state = nextState
    },
    getState() {
      return state
    },
    getVerifiedRuntime() {
      return verifiedRuntime
    },
  })
}

function registerPrimaryInstanceLifecycle({
  launchPolicyValid,
  ownsSingleInstanceLock,
  app,
  startupController,
  hasWindows,
  focusWindow,
  handleFailure,
  onWindowAllClosed,
  onBeforeQuit = () => {},
  onWillQuit,
}) {
  if (!launchPolicyValid || !ownsSingleInstanceLock) return false
  if (!app || !startupController) throw new TypeError('primary lifecycle dependencies are required')

  app.on('second-instance', () => {
    focusWindow()
  })
  app.on('activate', () => {
    Promise.resolve(startupController.onActivate({ hasWindows: hasWindows() }))
      .catch(handleFailure)
  })
  app.on('window-all-closed', onWindowAllClosed)
  app.on('before-quit', onBeforeQuit)
  app.on('will-quit', onWillQuit)
  app.whenReady()
    .then(() => startupController.onReady())
    .catch(handleFailure)
  return true
}

module.exports = {
  createRuntimeStarter,
  focusExistingWindow,
  createStartupFailurePresentation,
  prepareElectronLaunchOwnership,
  createTransactionalWindow,
  discardExactWindow,
  invalidateStartupForExactOwnership,
  createQaDeadlineController,
  createNativeExitCoordinator,
  loadStartupErrorContent,
  createDesktopStartupController,
  registerPrimaryInstanceLifecycle,
}
