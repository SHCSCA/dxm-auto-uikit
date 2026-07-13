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

function createDesktopStartupController({ startRuntime, createMainWindow }) {
  if (typeof createMainWindow !== 'function') throw new TypeError('createMainWindow must be a function')
  const startRuntimeOnce = createRuntimeStarter(startRuntime)
  let verifiedRuntime = null
  let readyPromise = null

  return Object.freeze({
    startRuntimeOnce,
    onReady() {
      if (!readyPromise) {
        readyPromise = startRuntimeOnce().then(async (runtime) => {
          verifiedRuntime = runtime
          await createMainWindow(runtime)
          return runtime
        })
      }
      return readyPromise
    },
    async onActivate({ hasWindows }) {
      if (hasWindows) return false
      if (!verifiedRuntime) throw new Error('Desktop runtime has not been verified')
      await createMainWindow(verifiedRuntime)
      return true
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
  app.on('will-quit', onWillQuit)
  app.whenReady()
    .then(() => startupController.onReady())
    .catch(handleFailure)
  return true
}

module.exports = {
  createRuntimeStarter,
  focusExistingWindow,
  createDesktopStartupController,
  registerPrimaryInstanceLifecycle,
}
