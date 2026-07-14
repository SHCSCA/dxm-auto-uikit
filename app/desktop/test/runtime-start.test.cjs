const test = require('node:test')
const assert = require('node:assert/strict')

const {
  createDesktopStartupController,
  createStartupFailurePresentation,
  createTransactionalWindow,
  invalidateStartupForExactOwnership,
  prepareElectronLaunchOwnership,
  registerPrimaryInstanceLifecycle,
} = require('../src/runtime-start.cjs')

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

test('only exact current ownership exit, close, or kill invalidates a verified startup', async () => {
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
    eventName: 'kill',
    startupController: controller,
  }), true)
  assert.equal(controller.getState(), 'stopped')
  assert.equal(controller.getVerifiedRuntime(), null)
  assert.equal(await controller.onActivate({ hasWindows: false }), false)
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
