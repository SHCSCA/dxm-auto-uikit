const DEFAULT_GRACE_TIMEOUT_MS = 3000
const DEFAULT_FINAL_TIMEOUT_MS = 2000
const DESKTOP_BACKEND_ENV_KEYS = Object.freeze([
  'DXM_RUNTIME_OWNER',
  'DXM_DESKTOP',
  'DXM_DESKTOP_PARENT_CHANNEL',
  'DXM_BACKEND_PORT',
  'DXM_RUNTIME_CONTROL_COMMAND_FILE',
])

function buildDesktopBackendEnvironment(baseEnvironment, { port }) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new TypeError('desktop backend port must be an integer from 1 through 65535')
  }
  const env = { ...baseEnvironment }
  const keys = new Set(DESKTOP_BACKEND_ENV_KEYS)
  for (const key of Object.keys(env)) {
    if (keys.has(key.toUpperCase())) delete env[key]
  }
  env.DXM_RUNTIME_OWNER = 'electron_desktop'
  env.DXM_DESKTOP = '1'
  env.DXM_DESKTOP_PARENT_CHANNEL = 'stdin-v1'
  env.DXM_BACKEND_PORT = String(port)
  return env
}

function asError(value, fallbackMessage) {
  if (value instanceof Error) return value
  const detail = value === null || value === undefined ? fallbackMessage : String(value)
  return new Error(detail)
}

function classifyWritableLogFailure({
  phase,
  ownership,
  currentOwnership,
  setupCleanupReleased,
}) {
  if (phase === 'opening') return 'opening'
  if (phase !== 'opened') throw new TypeError(`unknown writable log failure phase: ${String(phase)}`)
  if (setupCleanupReleased !== true) return 'setup'
  if (!ownership || currentOwnership !== ownership) return 'stale'
  return 'exact-current'
}

function createWritableLogOpenGate(stream, {
  timeoutMs = DEFAULT_FINAL_TIMEOUT_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onError = () => {},
  onDiagnostic = () => {},
} = {}) {
  if (!stream || typeof stream.on !== 'function' || typeof stream.once !== 'function'
    || typeof stream.off !== 'function') {
    throw new TypeError('writable log open gate requires one writable stream')
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1) {
    throw new TypeError('writable log open timeout must be a positive integer')
  }

  let opened = stream.pending === false && Number.isInteger(stream.fd)
  let closed = stream.closed === true
  let settled = false
  let timeout = null
  let resolveOpen
  let rejectOpen

  const report = (value, stage) => {
    try {
      onDiagnostic(asError(value, stage), stage)
    } catch {
      // Diagnostics cannot replace log-stream error containment.
    }
  }

  const openPromise = new Promise((resolve, reject) => {
    resolveOpen = resolve
    rejectOpen = reject
  })
  // The stream can fail on the next turn immediately after createWriteStream().
  // Keep the stable promise observed even before its caller starts awaiting it.
  openPromise.catch(() => {})

  const clearTimeoutIfNeeded = () => {
    if (timeout === null) return
    clearTimer(timeout)
    timeout = null
  }

  const removeOpenListener = () => stream.off('open', handleOpen)

  const removeAllListeners = () => {
    removeOpenListener()
    stream.off('close', handleClose)
    stream.off('error', handleError)
  }

  const rejectBeforeOpen = (error) => {
    if (settled) return
    settled = true
    clearTimeoutIfNeeded()
    removeOpenListener()
    rejectOpen(error)
  }

  function handleOpen() {
    if (settled || closed) return
    opened = true
    settled = true
    clearTimeoutIfNeeded()
    removeOpenListener()
    resolveOpen(stream)
  }

  function handleClose() {
    closed = true
    clearTimeoutIfNeeded()
    removeAllListeners()
    if (!settled) {
      const error = new Error('writable log stream closed before open')
      error.code = 'DXM_LOG_STREAM_CLOSED_BEFORE_OPEN'
      settled = true
      rejectOpen(error)
    }
  }

  function handleError(value) {
    const error = asError(value, 'writable log stream failed')
    const phase = opened ? 'opened' : 'opening'
    try {
      onError(error, phase)
    } catch (callbackError) {
      report(callbackError, 'log-error-callback')
    }
    if (!opened) rejectBeforeOpen(error)
  }

  // Install the persistent error sink first: fs.createWriteStream reports open
  // failures asynchronously, outside the caller's surrounding try/catch.
  stream.on('error', handleError)
  stream.once('close', handleClose)
  stream.once('open', handleOpen)

  if (closed) {
    handleClose()
  } else if (opened) {
    handleOpen()
  } else {
    try {
      timeout = setTimer(() => {
        const error = new Error(`writable log stream did not open within ${timeoutMs}ms`)
        error.code = 'DXM_LOG_STREAM_OPEN_TIMEOUT'
        rejectBeforeOpen(error)
      }, timeoutMs)
    } catch (value) {
      const error = asError(value, 'writable log open timer failed')
      error.code = 'DXM_LOG_STREAM_OPEN_TIMER_FAILED'
      report(error, 'log-open-timer')
      rejectBeforeOpen(error)
    }
  }

  return Object.freeze({
    waitUntilOpen() {
      return openPromise
    },
  })
}

function createSpawnSetupCleanup(child, {
  timeoutMs = DEFAULT_FINAL_TIMEOUT_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onClose = () => {},
  onChildError = () => {},
  onDiagnostic = () => {},
} = {}) {
  if (!child || typeof child.on !== 'function' || typeof child.once !== 'function'
    || typeof child.off !== 'function' || typeof child.kill !== 'function') {
    throw new TypeError('spawn setup cleanup requires one exact ChildProcess')
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1) {
    throw new TypeError('spawn setup cleanup timeout must be a positive integer')
  }

  let released = false
  let closeObserved = false
  let closeCode = null
  let closeSignal = null
  let terminationPromise = null
  let resolveTermination = null
  let rejectTermination = null
  let timeout = null
  let finished = false
  let stdinEndAttempted = false
  let stdinEndError = null
  let stdinError = null
  let killAttempted = false
  let killAccepted = null
  let killError = null

  const report = (value, stage) => {
    try {
      onDiagnostic(asError(value, stage), stage)
    } catch {
      // Diagnostics cannot replace exact-child setup cleanup.
    }
  }

  const getFacts = () => Object.freeze({
    released,
    closeObserved,
    closeCode,
    closeSignal,
    stdinEndAttempted,
    stdinEndError: stdinEndError?.message || null,
    stdinError: stdinError?.message || null,
    killAttempted,
    killAccepted,
    killError: killError?.message || null,
  })

  const clearTimeoutIfNeeded = () => {
    if (timeout === null) return
    clearTimer(timeout)
    timeout = null
  }

  const removeListeners = () => {
    child.off('close', handleClose)
    child.off('error', handleChildError)
    if (child.stdin && typeof child.stdin.off === 'function') {
      child.stdin.off('error', handleStdinError)
    }
  }

  const successResult = () => Object.freeze({
    ignored: false,
    closed: true,
    killAttempted,
    stdinEndAttempted,
  })

  const finishSuccess = () => {
    if (finished || !terminationPromise) return
    finished = true
    clearTimeoutIfNeeded()
    removeListeners()
    resolveTermination(successResult())
  }

  function handleClose(code, signal) {
    if (closeObserved || released) return
    closeObserved = true
    closeCode = code ?? null
    closeSignal = signal ?? null
    try {
      onClose(closeCode, closeSignal)
    } catch (error) {
      report(error, 'unowned-close-callback')
    }
    removeListeners()
    finishSuccess()
  }

  function handleChildError(value) {
    const error = asError(value, 'unowned backend child error')
    try {
      onChildError(error)
    } catch (callbackError) {
      report(callbackError, 'unowned-child-error-callback')
    }
  }

  function handleStdinError(value) {
    stdinError = asError(value, 'unowned backend stdin error')
    report(stdinError, 'unowned-stdin-error')
  }

  child.once('close', handleClose)
  child.on('error', handleChildError)
  if (child.stdin && typeof child.stdin.on === 'function'
    && typeof child.stdin.off === 'function') {
    child.stdin.on('error', handleStdinError)
  }

  const finishFailure = (stage) => {
    if (finished || closeObserved) {
      if (closeObserved) finishSuccess()
      return
    }
    finished = true
    clearTimeoutIfNeeded()
    const error = new Error(
      `unowned backend child pid=${Number.isInteger(child.pid) ? child.pid : 'unknown'} did not close after bounded setup cleanup (${stage})`,
    )
    error.code = 'DXM_UNOWNED_BACKEND_CLOSE_TIMEOUT'
    error.cleanupFacts = getFacts()
    rejectTermination(error)
  }

  const terminate = ({ reason = 'startup-construction' } = {}) => {
    if (terminationPromise) return terminationPromise
    if (released) {
      terminationPromise = Promise.resolve(Object.freeze({
        ignored: true,
        released: true,
        closed: false,
      }))
      return terminationPromise
    }

    terminationPromise = new Promise((resolve, reject) => {
      resolveTermination = resolve
      rejectTermination = reject
    })
    if (closeObserved) {
      finishSuccess()
      return terminationPromise
    }

    const stdin = child.stdin
    if (stdin && typeof stdin.end === 'function'
      && stdin.destroyed !== true && stdin.writableEnded !== true) {
      stdinEndAttempted = true
      try {
        stdin.end()
      } catch (error) {
        stdinEndError = asError(error, 'unowned backend stdin end failed')
        report(stdinEndError, 'unowned-stdin-end')
      }
    }

    if (!closeObserved
      && child.exitCode === null
      && child.signalCode === null
      && !killAttempted) {
      killAttempted = true
      try {
        killAccepted = child.kill() === true
        if (!killAccepted) {
          report(new Error('unowned backend child rejected kill request'), 'unowned-kill-rejected')
        }
      } catch (error) {
        killAccepted = false
        killError = asError(error, 'unowned backend child kill failed')
        report(killError, 'unowned-kill')
      }
    }

    if (!closeObserved && !finished) {
      try {
        timeout = setTimer(() => finishFailure(String(reason)), timeoutMs)
      } catch (error) {
        const schedulingError = asError(error, 'unowned backend cleanup timer failed')
        schedulingError.code = 'DXM_UNOWNED_BACKEND_CLEANUP_SCHEDULING_FAILED'
        schedulingError.cleanupFacts = getFacts()
        finished = true
        report(schedulingError, 'unowned-cleanup-timer')
        rejectTermination(schedulingError)
      }
    }
    return terminationPromise
  }

  const release = () => {
    if (released || terminationPromise || closeObserved) return false
    released = true
    removeListeners()
    return true
  }

  return Object.freeze({ terminate, release, getFacts })
}

function createBackendShutdownController({
  getCurrentOwnership,
  setCurrentOwnership,
  isCurrentOwnershipLive,
  invalidateStartup = () => {},
  onDiagnostic = () => {},
  onTerminationFailure = () => {},
  graceTimeoutMs = DEFAULT_GRACE_TIMEOUT_MS,
  finalTimeoutMs = DEFAULT_FINAL_TIMEOUT_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  if (typeof getCurrentOwnership !== 'function' || typeof setCurrentOwnership !== 'function') {
    throw new TypeError('current backend ownership accessors are required')
  }
  if (typeof isCurrentOwnershipLive !== 'function') {
    throw new TypeError('isCurrentOwnershipLive must be a function')
  }
  if (!Number.isInteger(graceTimeoutMs) || graceTimeoutMs < 1
    || !Number.isInteger(finalTimeoutMs) || finalTimeoutMs < 1) {
    throw new TypeError('backend shutdown timeouts must be positive integers')
  }

  const lifecycleStates = new WeakMap()
  let latestTerminationRecord = null
  let pendingSpawnSetup = null

  const report = (error, stage) => {
    try {
      onDiagnostic(asError(error, stage), stage)
    } catch {
      // Diagnostics cannot replace or interrupt exact-child termination.
    }
  }

  const exactCurrent = (ownership) => Boolean(
    ownership
    && getCurrentOwnership() === ownership
    && ownership.child
    && ownership.child.pid === ownership.pid,
  )

  const exactCurrentLive = (ownership) => exactCurrent(ownership)
    && isCurrentOwnershipLive(ownership) === true

  function registerSpawnSetup(child, {
    onClose = () => {},
    onChildError = () => {},
    onDiagnostic: onSetupDiagnostic = () => {},
  } = {}) {
    const record = {
      child,
      cleanup: null,
      authority: null,
      released: false,
      terminationPromise: null,
    }
    record.cleanup = createSpawnSetupCleanup(child, {
      timeoutMs: finalTimeoutMs,
      setTimer,
      clearTimer,
      onClose,
      onChildError,
      onDiagnostic: onSetupDiagnostic,
    })
    record.authority = Object.freeze({ child })
    const failRegistration = (code, reason, message) => {
      record.terminationPromise = record.cleanup.terminate({ reason })
      const error = new Error(message)
      error.code = code
      error.terminationPromise = record.terminationPromise
      throw error
    }
    if (getCurrentOwnership()) {
      failRegistration(
        'DXM_BACKEND_CURRENT_OWNERSHIP_CONFLICT',
        'current-ownership-registration-conflict',
        'backend spawn setup cannot register while exact ownership is current',
      )
    }
    if (pendingSpawnSetup
      && pendingSpawnSetup.released !== true
      && pendingSpawnSetup.cleanup.getFacts().closeObserved !== true) {
      failRegistration(
        'DXM_BACKEND_PENDING_SETUP_CONFLICT',
        'pending-setup-registration-conflict',
        'one backend spawn setup authority is already pending',
      )
    }
    pendingSpawnSetup = record
    return record.authority
  }

  function attachOwnership(ownership, {
    endLogStream = () => {},
    onChildEvent = () => {},
  } = {}) {
    if (!ownership || !ownership.child || ownership.child.pid !== ownership.pid) {
      throw new TypeError('one exact backend ownership record is required')
    }
    if (lifecycleStates.has(ownership) || ownership.lifecycleAttached) {
      throw new Error('backend ownership lifecycle is already attached')
    }
    const child = ownership.child
    const stdin = child.stdin
    if (!stdin || typeof stdin.on !== 'function' || typeof stdin.write !== 'function') {
      throw new Error('backend child stdin must be one writable pipe')
    }
    if (typeof child.on !== 'function' || typeof child.off !== 'function') {
      throw new Error('backend child must expose EventEmitter lifecycle methods')
    }

    const state = {
      endLogStream,
      logEnded: false,
      startFailure: null,
      terminationControl: null,
      cleaned: false,
      onChildEvent,
      startupInvalidated: false,
    }

    const invalidateUnexpected = (eventName, wasCurrent) => {
      if (!wasCurrent || ownership.terminationRequested || state.startupInvalidated) return
      state.startupInvalidated = true
      try {
        invalidateStartup(ownership, eventName)
      } catch (error) {
        report(error, `invalidate-${eventName}`)
      }
    }

    const handleExit = (code, signal) => {
      ownership.exitObserved = true
      ownership.exitCode = code ?? null
      ownership.exitSignal = signal ?? null
      const wasCurrent = exactCurrent(ownership)
      invalidateUnexpected('exit', wasCurrent)
      try {
        state.onChildEvent('exit', code ?? null, signal ?? null)
      } catch (error) {
        report(error, 'exit-callback')
      }
    }

    const cleanupLifecycleListeners = () => {
      if (state.cleaned) return
      state.cleaned = true
      child.off('error', handleChildError)
      child.off('exit', handleExit)
      child.off('close', handleClose)
      stdin.off('error', handlePipeError)
      stdin.off('close', handlePipeClose)
    }
    state.cleanupLifecycleListeners = cleanupLifecycleListeners

    const handleClose = (code, signal) => {
      ownership.closeObserved = true
      ownership.closeCode = code ?? null
      ownership.closeSignal = signal ?? null
      const wasCurrent = exactCurrent(ownership)
      if (wasCurrent) setCurrentOwnership(null)
      invalidateUnexpected('close', wasCurrent)
      try {
        state.onChildEvent('close', code ?? null, signal ?? null)
      } catch (error) {
        report(error, 'close-callback')
      }
      if (!state.logEnded) {
        state.logEnded = true
        try {
          state.endLogStream()
        } catch (error) {
          report(error, 'close-log-stream')
        }
      }
      cleanupLifecycleListeners()
    }

    const triggerChannelFailure = (value, stage) => {
      const error = asError(value, `backend ${stage} failed`)
      report(error, stage)
      if (typeof state.startFailure === 'function') state.startFailure(error)
      invalidateUnexpected(stage, exactCurrent(ownership))
      if (exactCurrent(ownership) || ownership.terminationPromise) {
        const termination = requestTermination(ownership, { reason: stage })
        termination.catch(() => {})
        const control = state.terminationControl
        if (control && !control.finished) control.forceFallback(error, stage)
      }
    }

    const handleChildError = (error) => triggerChannelFailure(error, 'child-error')
    const handlePipeError = (error) => triggerChannelFailure(error, 'stdin-error')
    const handlePipeClose = () => {
      if (!ownership.closeObserved && exactCurrentLive(ownership)) {
        triggerChannelFailure(new Error('backend stdin pipe closed while child was live'), 'stdin-close')
      }
    }

    lifecycleStates.set(ownership, state)
    ownership.lifecycleAttached = true
    child.on('error', handleChildError)
    child.on('exit', handleExit)
    child.on('close', handleClose)
    stdin.on('error', handlePipeError)
    stdin.on('close', handlePipeClose)
    return ownership
  }

  function handoffSpawnSetup(setupAuthority, ownership, lifecycleOptions = {}) {
    const record = pendingSpawnSetup
    if (!record || record.authority !== setupAuthority || record.child !== ownership?.child) {
      throw new Error('backend ownership handoff requires the exact pending spawn setup authority')
    }
    const failHandoff = (code, message) => {
      if (!record.terminationPromise) {
        record.terminationPromise = record.cleanup.terminate({ reason: 'ownership-handoff' })
      }
      const error = new Error(message)
      error.code = code
      error.terminationPromise = record.terminationPromise
      throw error
    }
    if (record.terminationPromise) {
      failHandoff(
        'DXM_BACKEND_SETUP_TERMINATING',
        'backend spawn setup termination already won the ownership handoff',
      )
    }
    if (record.cleanup.getFacts().closeObserved) {
      failHandoff(
        'DXM_BACKEND_SETUP_CLOSED',
        'backend child closed before exact ownership handoff completed',
      )
    }
    const existingOwnership = getCurrentOwnership()
    if (existingOwnership && existingOwnership !== ownership) {
      failHandoff(
        'DXM_BACKEND_OWNERSHIP_CONFLICT',
        'backend ownership handoff cannot replace another current ownership',
      )
    }

    attachOwnership(ownership, lifecycleOptions)
    try {
      setCurrentOwnership(ownership)
    } catch (error) {
      const state = lifecycleStates.get(ownership)
      state?.cleanupLifecycleListeners?.()
      lifecycleStates.delete(ownership)
      ownership.lifecycleAttached = false
      throw error
    }
    if (!record.cleanup.release()) {
      setCurrentOwnership(existingOwnership || null)
      const state = lifecycleStates.get(ownership)
      state?.cleanupLifecycleListeners?.()
      lifecycleStates.delete(ownership)
      ownership.lifecycleAttached = false
      failHandoff(
        'DXM_BACKEND_SETUP_TERMINATING',
        'backend spawn setup termination won the ownership handoff',
      )
    }
    record.released = true
    pendingSpawnSetup = null
    return ownership
  }

  function startParentChannel(ownership) {
    if (ownership?.channelStartPromise) return ownership.channelStartPromise
    const state = lifecycleStates.get(ownership)
    if (!state || !ownership.lifecycleAttached) {
      throw new Error('backend ownership lifecycle must be attached before START')
    }
    if (!exactCurrentLive(ownership)) {
      throw new Error('backend START requires the exact current live child')
    }
    if (ownership.terminationRequested) {
      throw new Error('backend START is forbidden after termination was requested')
    }

    let settled = false
    let resolveStart
    let rejectStart
    const startPromise = new Promise((resolve, reject) => {
      resolveStart = resolve
      rejectStart = reject
    })
    ownership.channelStartRequested = true
    ownership.channelStartPromise = startPromise

    const failStart = (value) => {
      if (settled) return
      settled = true
      const error = asError(value, 'backend START write failed')
      ownership.channelStartError = error
      state.startFailure = null
      rejectStart(error)
      report(error, 'start-write')
      const termination = requestTermination(ownership, { reason: 'start-write' })
      termination.catch(() => {})
    }
    state.startFailure = failStart

    try {
      ownership.child.stdin.write(`START ${ownership.instanceId}\n`, (error) => {
        if (error) {
          if (settled) {
            const lateError = asError(error, 'backend START callback failed')
            report(lateError, 'start-write-callback')
            const termination = requestTermination(ownership, { reason: 'start-write-callback' })
            termination.catch(() => {})
          } else {
            failStart(error)
          }
          return
        }
        if (settled) return
        settled = true
        state.startFailure = null
        ownership.channelStarted = true
        resolveStart(ownership)
      })
    } catch (error) {
      failStart(error)
    }
    return startPromise
  }

  function requestTermination(ownership, { reason = 'unspecified' } = {}) {
    if (ownership?.terminationPromise) return ownership.terminationPromise
    const state = lifecycleStates.get(ownership)
    if (!state || !exactCurrent(ownership)) {
      return Promise.resolve(Object.freeze({ ignored: true, closed: Boolean(ownership?.closeObserved) }))
    }

    let resolveTermination
    let rejectTermination
    const terminationPromise = new Promise((resolve, reject) => {
      resolveTermination = resolve
      rejectTermination = reject
    })
    const control = {
      finished: false,
      graceTimer: null,
      finalTimer: null,
      forceFallback: null,
    }
    ownership.terminationRequested = true
    ownership.terminationReason = String(reason)
    ownership.terminationPromise = terminationPromise
    latestTerminationRecord = { ownership, promise: terminationPromise }
    state.terminationControl = control

    const clearTerminationResources = () => {
      if (control.graceTimer !== null) {
        clearTimer(control.graceTimer)
        control.graceTimer = null
      }
      if (control.finalTimer !== null) {
        clearTimer(control.finalTimer)
        control.finalTimer = null
      }
      ownership.child.off('close', finishOnClose)
      if (state.terminationControl === control) state.terminationControl = null
    }

    const finishSuccess = () => {
      if (control.finished) return
      control.finished = true
      clearTerminationResources()
      resolveTermination(Object.freeze({
        ignored: false,
        closed: true,
        killAttempted: ownership.killAttempted,
      }))
    }

    const finishFailure = () => {
      if (control.finished) return
      control.finished = true
      clearTerminationResources()
      const error = new Error(
        `backend child pid=${ownership.pid} did not close after bounded termination`,
      )
      try {
        onTerminationFailure(error, ownership)
      } catch (callbackError) {
        report(callbackError, 'termination-failure-callback')
      }
      rejectTermination(error)
    }

    function finishOnClose() {
      finishSuccess()
    }

    const scheduleFinalWait = () => {
      if (control.finished || ownership.closeObserved || control.finalTimer !== null) {
        if (ownership.closeObserved) finishSuccess()
        return
      }
      control.finalTimer = setTimer(finishFailure, finalTimeoutMs)
    }

    const attemptExactKillOnce = () => {
      if (control.finished || ownership.killAttempted || !exactCurrentLive(ownership)) return false
      ownership.killAttempted = true
      ownership.killAttemptCount += 1
      try {
        ownership.killAccepted = ownership.child.kill() === true
      } catch (error) {
        ownership.killAccepted = false
        ownership.killError = asError(error, 'backend child kill failed')
        report(ownership.killError, 'kill')
      }
      return true
    }

    control.forceFallback = (error, stage) => {
      if (control.finished) return
      if (control.graceTimer !== null) {
        clearTimer(control.graceTimer)
        control.graceTimer = null
      }
      if (error) report(error, `${stage}-fallback`)
      attemptExactKillOnce()
      scheduleFinalWait()
    }

    const beginTermination = () => {
      if (control.finished) return
      if (ownership.closeObserved) {
        finishSuccess()
        return
      }

      if (exactCurrentLive(ownership) && !ownership.shutdownWriteAttempted) {
        ownership.shutdownWriteAttempted = true
        try {
          ownership.child.stdin.write('SHUTDOWN\n', (error) => {
            if (control.finished) return
            if (error) {
              ownership.shutdownWriteError = asError(error, 'backend SHUTDOWN write failed')
              control.forceFallback(ownership.shutdownWriteError, 'shutdown-write-callback')
              return
            }
            ownership.shutdownWriteCompleted = true
          })
        } catch (error) {
          ownership.shutdownWriteError = asError(error, 'backend SHUTDOWN write failed')
          control.forceFallback(ownership.shutdownWriteError, 'shutdown-write')
        }
      }

      if (!control.finished && control.graceTimer === null && control.finalTimer === null) {
        control.graceTimer = setTimer(() => {
          control.graceTimer = null
          attemptExactKillOnce()
          scheduleFinalWait()
        }, graceTimeoutMs)
      }
    }

    ownership.child.on('close', finishOnClose)
    queueMicrotask(beginTermination)
    return terminationPromise
  }

  function requestCurrentOrPendingTermination({ reason = 'unspecified' } = {}) {
    const currentOwnership = getCurrentOwnership()
    if (currentOwnership) return requestTermination(currentOwnership, { reason })
    if (pendingSpawnSetup && pendingSpawnSetup.released !== true) {
      if (!pendingSpawnSetup.terminationPromise) {
        pendingSpawnSetup.terminationPromise = pendingSpawnSetup.cleanup.terminate({ reason })
      }
      return pendingSpawnSetup.terminationPromise
    }
    const pending = latestTerminationRecord?.ownership.closeObserved
      ? null
      : latestTerminationRecord?.promise
    return pending || Promise.resolve(Object.freeze({ ignored: true, closed: true }))
  }

  return Object.freeze({
    registerSpawnSetup,
    handoffSpawnSetup,
    attachOwnership,
    startParentChannel,
    requestTermination,
    requestCurrentOrPendingTermination,
  })
}

function createBeforeQuitController({
  app,
  requestCurrentOrPendingTermination,
  onTerminationError = () => {},
}) {
  if (!app || typeof app.quit !== 'function') throw new TypeError('app.quit must be a function')
  if (typeof requestCurrentOrPendingTermination !== 'function') {
    throw new TypeError('before-quit current-or-pending termination dependency is required')
  }
  let allowFinalQuit = false
  let finalQuitRequested = false
  let terminationPromise = null

  const requestFinalQuit = () => {
    if (finalQuitRequested) return
    finalQuitRequested = true
    allowFinalQuit = true
    app.quit()
  }

  return Object.freeze({
    handleBeforeQuit(event) {
      if (allowFinalQuit) return null
      event?.preventDefault?.()
      if (!terminationPromise) {
        try {
          terminationPromise = requestCurrentOrPendingTermination({ reason: 'before-quit' })
        } catch (error) {
          terminationPromise = Promise.reject(error)
        }
        terminationPromise.then(
          requestFinalQuit,
          (error) => {
            try {
              onTerminationError(error)
            } catch {
              // A diagnostic failure cannot trap Electron in before-quit.
            }
            requestFinalQuit()
          },
        )
      }
      return terminationPromise
    },
    getTerminationPromise() {
      return terminationPromise
    },
  })
}

module.exports = {
  DEFAULT_GRACE_TIMEOUT_MS,
  DEFAULT_FINAL_TIMEOUT_MS,
  buildDesktopBackendEnvironment,
  classifyWritableLogFailure,
  createWritableLogOpenGate,
  createSpawnSetupCleanup,
  createBackendShutdownController,
  createBeforeQuitController,
}
