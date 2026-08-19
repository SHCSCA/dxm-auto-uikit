const test = require('node:test')
const assert = require('node:assert/strict')

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
} = require('../src/runtime-start.cjs')

test('QA deadline arms once, fires once, and cancel makes a late callback inert', () => {
  let disabledTimerCalls = 0
  const disabled = createQaDeadlineController({
    deadlineMs: null,
    requestFailedQuit: () => assert.fail('disabled deadline must not quit'),
    setTimer: () => { disabledTimerCalls += 1 },
    clearTimer: () => assert.fail('disabled deadline has no timer to clear'),
  })
  assert.equal(disabled.arm(), false)
  assert.equal(disabled.cancel(), false)
  assert.equal(disabledTimerCalls, 0)

  const timerId = { id: 'qa-deadline' }
  let deadlineCallback = null
  let clearCount = 0
  let failedQuitCount = 0
  const deadline = createQaDeadlineController({
    deadlineMs: 25,
    requestFailedQuit: () => { failedQuitCount += 1 },
    setTimer: (callback, delayMs) => {
      assert.equal(delayMs, 25)
      deadlineCallback = callback
      return timerId
    },
    clearTimer: (candidate) => {
      assert.strictEqual(candidate, timerId)
      clearCount += 1
    },
  })
  assert.equal(deadline.arm(), true)
  assert.equal(deadline.arm(), false)
  deadlineCallback()
  deadlineCallback()
  assert.equal(failedQuitCount, 1)
  assert.equal(deadline.cancel(), false)
  assert.equal(clearCount, 0)

  let canceledCallback = null
  const canceled = createQaDeadlineController({
    deadlineMs: 50,
    requestFailedQuit: () => { failedQuitCount += 1 },
    setTimer: (callback) => {
      canceledCallback = callback
      return timerId
    },
    clearTimer: () => { clearCount += 1 },
  })
  assert.equal(canceled.arm(), true)
  assert.equal(canceled.cancel(), true)
  assert.equal(canceled.cancel(), false)
  canceledCallback()
  assert.equal(failedQuitCount, 1)
  assert.equal(clearCount, 1)
})

test('ready starts runtime once before the first window and activate creates only a window', async () => {
  const calls = []
  const controller = createDesktopStartupController({
    startRuntime: async () => {
      calls.push('runtime')
      return { apiBase: 'http://127.0.0.1:8000' }
    },
    createMainWindow: async (runtime) => {
      calls.push(`window:${runtime.apiBase}`)
    },
  })

  await Promise.all([controller.onReady(), controller.onReady()])
  await controller.onActivate({ hasWindows: false })
  await controller.onActivate({ hasWindows: true })

  assert.deepEqual(calls, [
    'runtime',
    'window:http://127.0.0.1:8000',
    'window:http://127.0.0.1:8000',
  ])
})

test('activate while startup is idle or still starting is a no-op without starting another runtime', async () => {
  let starts = 0
  let windows = 0
  let releaseRuntime
  const controller = createDesktopStartupController({
    startRuntime: () => new Promise((resolve) => {
      starts += 1
      releaseRuntime = () => resolve({ apiBase: 'http://127.0.0.1:8000' })
    }),
    createMainWindow: async () => { windows += 1 },
  })

  assert.equal(await controller.onActivate({ hasWindows: false }), false)
  assert.equal(starts, 0)
  assert.equal(windows, 0)
  assert.equal(controller.getState(), 'idle')

  const ready = controller.onReady()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(controller.getState(), 'starting')
  assert.equal(await controller.onActivate({ hasWindows: false }), false)
  assert.equal(starts, 1)
  assert.equal(windows, 0)

  releaseRuntime()
  await ready
  assert.equal(controller.getState(), 'ready')
  assert.equal(windows, 1)
})

test('first window failure leaves no verified runtime and activate never retries window creation', async () => {
  let windows = 0
  const controller = createDesktopStartupController({
    startRuntime: async () => ({ apiBase: 'http://127.0.0.1:8000' }),
    createMainWindow: async () => {
      windows += 1
      throw new Error('first window load failed')
    },
  })

  await assert.rejects(controller.onReady(), /first window load failed/)
  assert.equal(controller.getState(), 'failed')
  assert.equal(controller.getVerifiedRuntime(), null)
  assert.equal(await controller.onActivate({ hasWindows: false }), false)
  assert.equal(windows, 1)
})

test('exact invalidation during first-window initialization rolls back the returned window before surfacing failure', async () => {
  let releaseWindow
  let currentWindow = null
  let errorWindowCreated = false
  const firstWindow = {
    destroyed: false,
    isDestroyed() { return this.destroyed },
    destroy() { this.destroyed = true },
  }
  const controller = createDesktopStartupController({
    startRuntime: async () => ({ apiBase: 'http://127.0.0.1:8000' }),
    createMainWindow: async () => {
      currentWindow = firstWindow
      await new Promise((resolve) => { releaseWindow = resolve })
      return firstWindow
    },
    discardMainWindow: (window) => discardExactWindow({
      window,
      getCurrentWindow: () => currentWindow,
      setCurrentWindow: (value) => { currentWindow = value },
    }),
  })

  const ready = controller.onReady()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(controller.getState(), 'starting')
  controller.invalidateRuntime('stopped')
  releaseWindow()

  await assert.rejects(ready, /invalidated while creating the first window: stopped/)
  assert.equal(firstWindow.destroyed, true)
  assert.equal(currentWindow, null)
  assert.equal(controller.getVerifiedRuntime(), null)
  assert.equal(controller.getState(), 'stopped')
  if (!focusExistingWindow(() => currentWindow)) errorWindowCreated = true
  assert.equal(errorWindowCreated, true)
})

test('startup conflict presentation uses stable error code and ignores resource paths in the stack', () => {
  for (const [code, expectedMessage] of [
    ['DXM_SAME_DATA_RUNTIME', '已有 DXM Agent Console 正在使用同一数据目录'],
    ['DXM_PORT_8000_OCCUPIED', '本机 8000 端口已被占用'],
    ['DXM_PORT_8000_UNCERTAIN', '无法确认本机 8000 端口可用'],
  ]) {
    const error = new Error('review fixture')
    error.code = code
    error.stack = `Error: review fixture\n  at C:\\package\\resources\\app.asar\\src\\main.cjs:1:1`
    error.conflict = { port: 8000, pid: 42, instanceId: 'owned-instance' }

    const presentation = createStartupFailurePresentation(error, {
      desktopLogWritten: false,
      desktopLogPath: 'C:\\normal\\data\\desktop-main.log',
    })

    assert.equal(presentation.code, code)
    assert.match(presentation.message, new RegExp(expectedMessage))
    assert.equal(presentation.logAvailable, false)
    assert.equal(presentation.logPath, null)
    assert.match(presentation.logMessage, /未生成启动日志/)
  }
})

test('unknown startup failure does not become a package error because its stack contains resources', () => {
  const error = new Error('first window load failed')
  error.stack = 'Error: first window load failed\n  at C:\\portable\\resources\\app.asar\\src\\main.cjs:1:1'

  const presentation = createStartupFailurePresentation(error, {
    desktopLogWritten: true,
    desktopLogPath: 'C:\\qa\\data\\desktop-main.log',
  })

  assert.equal(presentation.code, 'DXM_STARTUP_FAILED')
  assert.doesNotMatch(presentation.message, /免安装目录不完整/)
  assert.equal(presentation.logAvailable, true)
  assert.equal(presentation.logPath, 'C:\\qa\\data\\desktop-main.log')
})

test('backend pid mismatch is explained as a port conflict, not a blank failure', () => {
  const error = new Error('Backend health check reached a mismatched backend at http://127.0.0.1:8000/health: runtime identity backendPid mismatch')
  const presentation = createStartupFailurePresentation(error, {
    desktopLogWritten: true,
    desktopLogPath: 'C:\\Users\\wz\\AppData\\Roaming\\DXM Agent Console\\data\\desktop-main.log',
  })
  assert.equal(presentation.code, 'DXM_BACKEND_IDENTITY_MISMATCH')
  assert.match(presentation.message, /8000/)
  assert.match(presentation.message, /不会接管/)
})

test('transactional window setup destroys only the failed window and clears only a matching reference', async () => {
  const destroyed = []
  let currentWindow = null
  const failedWindow = {
    isDestroyed: () => false,
    destroy: () => destroyed.push('failed'),
  }
  await assert.rejects(createTransactionalWindow({
    createWindow: () => failedWindow,
    getCurrentWindow: () => currentWindow,
    setCurrentWindow: (value) => { currentWindow = value },
    initializeWindow: async () => { throw new Error('load rejected') },
  }), /load rejected/)
  assert.deepEqual(destroyed, ['failed'])
  assert.equal(currentWindow, null)

  const replacementWindow = { id: 'replacement' }
  await assert.rejects(createTransactionalWindow({
    createWindow: () => failedWindow,
    getCurrentWindow: () => currentWindow,
    setCurrentWindow: (value) => { currentWindow = value },
    initializeWindow: async () => {
      currentWindow = replacementWindow
      throw new Error('late smoke rejected')
    },
  }), /late smoke rejected/)
  assert.deepEqual(destroyed, ['failed', 'failed'])
  assert.equal(currentWindow, replacementWindow)
})

test('launch ownership helper performs classify then QA mkdir, setPath, and lock', () => {
  const calls = []
  const policy = Object.freeze({ isIsolatedQa: true, qaUserDataDir: 'C:\\qa-owner' })
  const result = prepareElectronLaunchOwnership({
    argv: ['--qa-user-data-dir=C:\\qa-owner'],
    normalUserDataDir: 'C:\\normal-owner',
    classifyLaunchArguments: (input) => {
      calls.push(['classify', input])
      return policy
    },
    createQaRoot: (value) => calls.push(['mkdir', value]),
    setUserDataPath: (value) => calls.push(['setPath', value]),
    requestSingleInstanceLock: () => {
      calls.push(['lock'])
      return true
    },
    quit: () => calls.push(['quit']),
  })

  assert.deepEqual(calls.map(([name]) => name), ['classify', 'mkdir', 'setPath', 'lock'])
  assert.equal(result.launchPolicy, policy)
  assert.equal(result.launchPolicyValid, true)
  assert.equal(result.ownsSingleInstanceLock, true)
})

test('invalid launch classification and false lock cannot register any lifecycle', async () => {
  const invalidCalls = []
  assert.throws(() => prepareElectronLaunchOwnership({
    argv: [],
    normalUserDataDir: 'C:\\normal-owner',
    classifyLaunchArguments: () => {
      invalidCalls.push('classify')
      throw new Error('invalid QA policy')
    },
    createQaRoot: () => invalidCalls.push('mkdir'),
    setUserDataPath: () => invalidCalls.push('setPath'),
    requestSingleInstanceLock: () => invalidCalls.push('lock'),
    quit: () => invalidCalls.push('quit'),
  }), /invalid QA policy/)
  assert.deepEqual(invalidCalls, ['classify'])

  const lockCalls = []
  const ownership = prepareElectronLaunchOwnership({
    argv: [],
    normalUserDataDir: 'C:\\normal-owner',
    classifyLaunchArguments: () => ({ isIsolatedQa: false, qaUserDataDir: null }),
    createQaRoot: () => lockCalls.push('mkdir'),
    setUserDataPath: () => lockCalls.push('setPath'),
    requestSingleInstanceLock: () => {
      lockCalls.push('lock')
      return false
    },
    quit: () => lockCalls.push('quit'),
  })
  const appCalls = []
  assert.equal(registerPrimaryInstanceLifecycle({
    ...ownership,
    app: { on: () => appCalls.push('on'), whenReady: () => appCalls.push('ready') },
    startupController: {},
  }), false)
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(lockCalls, ['lock', 'quit'])
  assert.deepEqual(appCalls, [])
})

test('only an approved exact current backend stop or channel failure invalidates a verified startup', async () => {
  const controller = createDesktopStartupController({
    startRuntime: async () => ({ apiBase: 'http://127.0.0.1:8000' }),
    createMainWindow: async () => {},
  })
  await controller.onReady()
  const currentOwnership = { child: { pid: 21 } }
  const staleOwnership = { child: { pid: 21 } }

  assert.equal(invalidateStartupForExactOwnership({
    currentOwnership,
    eventOwnership: staleOwnership,
    eventName: 'exit',
    startupController: controller,
  }), false)
  assert.equal(controller.getState(), 'ready')
  assert.equal(invalidateStartupForExactOwnership({
    currentOwnership,
    eventOwnership: currentOwnership,
    eventName: 'error',
    startupController: controller,
  }), false)
  assert.equal(controller.getState(), 'ready')
  assert.equal(invalidateStartupForExactOwnership({
    currentOwnership,
    eventOwnership: currentOwnership,
    eventName: 'stdin-error',
    startupController: controller,
  }), true)
  assert.equal(controller.getState(), 'stopped')
  assert.equal(controller.getVerifiedRuntime(), null)
  assert.equal(await controller.onActivate({ hasWindows: false }), false)
})

test('failed native exit is finalized only after will-quit cleanup', () => {
  const events = []
  let onWillQuit
  const app = {
    quit: () => {
      events.push('app.quit')
      onWillQuit()
    },
    exit: (code) => events.push(`app.exit:${code}`),
  }
  const coordinator = createNativeExitCoordinator({ app })
  onWillQuit = () => {
    events.push('will-quit cleanup')
    coordinator.finalizeAfterCleanup()
  }

  assert.equal(coordinator.requestQuit({ failed: true }), true)
  assert.deepEqual(events, [
    'app.quit',
    'will-quit cleanup',
    'app.exit:1',
  ])
})

test('successful native exit uses normal quit and never calls app.exit', () => {
  const events = []
  let onWillQuit
  const app = {
    quit: () => {
      events.push('app.quit')
      onWillQuit()
    },
    exit: (code) => events.push(`app.exit:${code}`),
  }
  const coordinator = createNativeExitCoordinator({ app })
  onWillQuit = () => {
    events.push('will-quit cleanup')
    coordinator.finalizeAfterCleanup()
  }

  assert.equal(coordinator.requestQuit({ failed: false }), true)
  assert.deepEqual(events, ['app.quit', 'will-quit cleanup'])
})

test('repeated failed quit requests preserve failure and finalize native exit only once', () => {
  const events = []
  let coordinator
  const app = {
    quit: () => events.push('app.quit'),
    exit: (code) => {
      events.push(`app.exit:${code}`)
      coordinator.finalizeAfterCleanup()
    },
  }
  coordinator = createNativeExitCoordinator({ app })

  assert.equal(coordinator.requestQuit({ failed: true }), true)
  assert.equal(coordinator.requestQuit({ failed: true }), false)
  events.push('will-quit cleanup')
  assert.equal(coordinator.finalizeAfterCleanup(), true)
  assert.equal(coordinator.finalizeAfterCleanup(), false)
  assert.deepEqual(events, [
    'app.quit',
    'will-quit cleanup',
    'app.exit:1',
  ])
})

test('a bounded backend termination failure upgrades native exit without issuing another initial quit', () => {
  const events = []
  const coordinator = createNativeExitCoordinator({
    app: {
      quit: () => events.push('app.quit'),
      exit: (code) => events.push(`app.exit:${code}`),
    },
  })

  assert.equal(coordinator.requestQuit(), true)
  assert.equal(coordinator.markFailure(), true)
  assert.equal(coordinator.markFailure(), false)
  assert.equal(coordinator.finalizeAfterCleanup(), true)
  assert.deepEqual(events, ['app.quit', 'app.exit:1'])
})

test('QA deadline upgrades an already-started successful quit without another quit request', () => {
  const events = []
  let deadlineCallback = null
  const coordinator = createNativeExitCoordinator({
    app: {
      quit: () => events.push('app.quit'),
      exit: (code) => events.push(`app.exit:${code}`),
    },
  })
  const deadline = createQaDeadlineController({
    deadlineMs: 25,
    requestFailedQuit: () => coordinator.requestQuit({ failed: true }),
    setTimer: (callback) => {
      deadlineCallback = callback
      return 1
    },
    clearTimer: () => {},
  })

  assert.equal(deadline.arm(), true)
  assert.equal(coordinator.requestQuit(), true)
  deadlineCallback()
  deadlineCallback()
  assert.deepEqual(events, ['app.quit'])
  assert.equal(coordinator.finalizeAfterCleanup(), true)
  assert.deepEqual(events, ['app.quit', 'app.exit:1'])
})

test('startup error content falls back once when rich HTML fails to load', async () => {
  const urls = []
  const diagnostics = []
  const window = {
    loadURL: async (url) => {
      urls.push(url)
      if (urls.length === 1) throw new Error('rich content rejected')
    },
  }

  const result = await loadStartupErrorContent({
    window,
    richContentUrl: 'data:text/html,rich',
    fallbackContentUrl: 'data:text/html,safe-fallback',
    onLoadError: (error, stage) => diagnostics.push(`${stage}:${error.message}`),
  })

  assert.equal(result, 'fallback')
  assert.deepEqual(urls, ['data:text/html,rich', 'data:text/html,safe-fallback'])
  assert.deepEqual(diagnostics, ['rich:rich content rejected'])
})

test('startup error content contains a second load rejection without recursion or an unhandled rejection', async () => {
  const urls = []
  const diagnostics = []
  const result = await loadStartupErrorContent({
    window: {
      loadURL: async (url) => {
        urls.push(url)
        throw new Error(`rejected ${urls.length}`)
      },
    },
    richContentUrl: 'data:text/html,rich',
    fallbackContentUrl: 'data:text/html,safe-fallback',
    onLoadError: (error, stage) => diagnostics.push(`${stage}:${error.message}`),
  })

  assert.equal(result, 'failed')
  assert.equal(urls.length, 2)
  assert.deepEqual(diagnostics, ['rich:rejected 1', 'fallback:rejected 2'])
})

test('invalid policy or a missing single-instance lock registers no startup lifecycle', async () => {
  for (const gate of [
    { launchPolicyValid: false, ownsSingleInstanceLock: false },
    { launchPolicyValid: true, ownsSingleInstanceLock: false },
  ]) {
    const calls = []
    const app = {
      on: (...args) => calls.push(['on', ...args]),
      whenReady: () => {
        calls.push(['whenReady'])
        return Promise.resolve()
      },
    }
    const registered = registerPrimaryInstanceLifecycle({
      ...gate,
      app,
      startupController: {
        onReady: () => calls.push(['onReady']),
        onActivate: () => calls.push(['onActivate']),
      },
      hasWindows: () => false,
      focusWindow: () => calls.push(['focusWindow']),
      handleFailure: () => calls.push(['handleFailure']),
      onWindowAllClosed: () => calls.push(['windowAllClosed']),
      onWillQuit: () => calls.push(['willQuit']),
    })

    assert.equal(registered, false)
    await new Promise((resolve) => setImmediate(resolve))
    assert.deepEqual(calls, [])
  }
})

test('primary lifecycle registers ready once and keeps second-instance focus-only', async () => {
  const handlers = new Map()
  const calls = []
  const app = {
    on: (event, handler) => handlers.set(event, handler),
    whenReady: () => Promise.resolve(),
  }
  const registered = registerPrimaryInstanceLifecycle({
    launchPolicyValid: true,
    ownsSingleInstanceLock: true,
    app,
    startupController: {
      onReady: async () => { calls.push('ready') },
      onActivate: async (payload) => { calls.push(['activate', payload]) },
    },
    hasWindows: () => false,
    focusWindow: () => calls.push('focus'),
    handleFailure: (error) => calls.push(['failure', error]),
    onWindowAllClosed: () => calls.push('window-all-closed'),
    onWillQuit: () => calls.push('will-quit'),
  })

  assert.equal(registered, true)
  await new Promise((resolve) => setImmediate(resolve))
  handlers.get('second-instance')()
  handlers.get('activate')()
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(calls, ['ready', 'focus', ['activate', { hasWindows: false }]])
})
