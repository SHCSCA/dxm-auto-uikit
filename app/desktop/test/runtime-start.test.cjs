const test = require('node:test')
const assert = require('node:assert/strict')

const {
  createDesktopStartupController,
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

test('activate before runtime verification fails closed without starting runtime', async () => {
  let starts = 0
  let windows = 0
  const controller = createDesktopStartupController({
    startRuntime: async () => {
      starts += 1
      return { apiBase: 'http://127.0.0.1:8000' }
    },
    createMainWindow: async () => { windows += 1 },
  })

  await assert.rejects(
    controller.onActivate({ hasWindows: false }),
    /runtime has not been verified/i,
  )
  assert.equal(starts, 0)
  assert.equal(windows, 0)
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
