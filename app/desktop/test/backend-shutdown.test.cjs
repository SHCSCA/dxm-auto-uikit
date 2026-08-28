const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { createBackendOwnership } = require('../src/runtime-identity.cjs')

function loadShutdownModule() {
  return require('../src/backend-shutdown.cjs')
}

class FakeWritable extends EventEmitter {
  constructor(behavior = (_text, callback) => {
    callback(null)
    return true
  }) {
    super()
    this.behavior = behavior
    this.writes = []
    this.endCount = 0
  }

  write(text, callback) {
    this.writes.push(String(text))
    return this.behavior(String(text), callback)
  }

  end() {
    this.endCount += 1
  }
}

class FakeChild extends EventEmitter {
  constructor({ pid = 321, stdin = new FakeWritable(), killResult = true } = {}) {
    super()
    this.pid = pid
    this.stdin = stdin
    this.stdout = new EventEmitter()
    this.stderr = new EventEmitter()
    this.exitCode = null
    this.signalCode = null
    this.killResult = killResult
    this.killCount = 0
  }

  kill() {
    this.killCount += 1
    if (this.killResult instanceof Error) throw this.killResult
    return this.killResult
  }

  emitExit(code = 0, signal = null) {
    this.exitCode = code
    this.signalCode = signal
    this.emit('exit', code, signal)
  }

  emitClose(code = this.exitCode, signal = this.signalCode) {
    this.emit('close', code, signal)
  }
}

class FakeLogStream extends EventEmitter {
  constructor({ opened = false } = {}) {
    super()
    this.pending = !opened
    this.fd = opened ? 17 : null
    this.closed = false
  }

  emitOpen() {
    this.pending = false
    this.fd = 17
    this.emit('open', this.fd)
  }

  emitClose() {
    this.closed = true
    this.emit('close')
  }
}

function createOwnership(child = new FakeChild(), instanceId = 'exact-instance') {
  return createBackendOwnership({
    child,
    instanceId,
    expectedIdentity: {
      instanceId,
      backendPid: child.pid,
    },
  })
}

function createManualTimers() {
  let nextId = 1
  const entries = []
  return {
    setTimer(callback, delayMs) {
      const entry = { id: nextId++, callback, delayMs, active: true }
      entries.push(entry)
      return entry.id
    },
    clearTimer(id) {
      const entry = entries.find((candidate) => candidate.id === id)
      if (entry) entry.active = false
    },
    runNext() {
      const entry = entries.find((candidate) => candidate.active)
      assert.ok(entry, 'expected one active timer')
      entry.active = false
      entry.callback()
      return entry.delayMs
    },
    activeCount() {
      return entries.filter((entry) => entry.active).length
    },
  }
}

function makeController(ownership, overrides = {}) {
  const { createBackendShutdownController } = loadShutdownModule()
  let currentOwnership = ownership
  const invalidations = []
  const logEnds = []
  const diagnostics = []
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: (candidate) => currentOwnership === candidate
      && candidate.child.exitCode === null
      && candidate.child.signalCode === null
      && candidate.exitObserved !== true
      && candidate.closeObserved !== true,
    invalidateStartup: (candidate, eventName) => invalidations.push([candidate, eventName]),
    onDiagnostic: (error, stage) => diagnostics.push([stage, error.message]),
    graceTimeoutMs: 10,
    finalTimeoutMs: 10,
    ...overrides,
  })
  controller.attachOwnership(ownership, {
    endLogStream: () => logEnds.push(ownership),
  })
  return {
    controller,
    invalidations,
    logEnds,
    diagnostics,
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
  }
}

test('desktop backend environment removes stale owner facts case-insensitively before writing one exact contract', () => {
  const { buildDesktopBackendEnvironment } = loadShutdownModule()
  const original = {
    KEEP_ME: 'yes',
    DXM_RUNTIME_OWNER: 'forged',
    dxm_desktop: '0',
    Dxm_Desktop_Parent_Channel: 'pid-polling',
    dxm_backend_port: '9999',
    Dxm_Runtime_Control_Command_File: 'stale-parent-command.txt',
  }

  const env = buildDesktopBackendEnvironment(original, { port: 8007 })

  assert.equal(original.DXM_RUNTIME_OWNER, 'forged')
  assert.equal(env.KEEP_ME, 'yes')
  assert.equal(env.DXM_RUNTIME_OWNER, 'electron_desktop')
  assert.equal(env.DXM_DESKTOP, '1')
  assert.equal(env.DXM_DESKTOP_PARENT_CHANNEL, 'stdin-v1')
  assert.equal(env.DXM_BACKEND_PORT, '8007')
  assert.equal(
    Object.keys(env).some((key) => key.toUpperCase() === 'DXM_RUNTIME_CONTROL_COMMAND_FILE'),
    false,
  )
  for (const name of [
    'DXM_RUNTIME_OWNER',
    'DXM_DESKTOP',
    'DXM_DESKTOP_PARENT_CHANNEL',
    'DXM_BACKEND_PORT',
  ]) {
    assert.deepEqual(
      Object.keys(env).filter((key) => key.toUpperCase() === name),
      [name],
    )
  }
})

test('ownership installs lifecycle listeners before one START write and waits for its callback despite backpressure', async () => {
  let releaseStart
  let listenersAtWrite = null
  const stdin = new FakeWritable((_text, callback) => {
    listenersAtWrite = {
      exit: child.listenerCount('exit'),
      close: child.listenerCount('close'),
      childError: child.listenerCount('error'),
      pipeError: stdin.listenerCount('error'),
      pipeClose: stdin.listenerCount('close'),
    }
    releaseStart = () => callback(null)
    return false
  })
  const child = new FakeChild({ stdin })
  const ownership = createOwnership(child)
  const { controller } = makeController(ownership)

  const started = controller.startParentChannel(ownership)
  assert.strictEqual(controller.startParentChannel(ownership), started)
  assert.deepEqual(stdin.writes, ['START exact-instance\n'])
  assert.equal(ownership.channelStarted, false)
  assert.deepEqual(listenersAtWrite, {
    exit: 1,
    close: 1,
    childError: 1,
    pipeError: 1,
    pipeClose: 1,
  })

  releaseStart()
  assert.strictEqual(await started, ownership)
  assert.equal(ownership.channelStarted, true)
  assert.equal(stdin.endCount, 0)
})

test('START callback failure enters the same exact termination promise and waits for close after one kill', async () => {
  const timers = createManualTimers()
  const stdin = new FakeWritable((text, callback) => {
    queueMicrotask(() => callback(new Error(`${text.startsWith('START') ? 'start' : 'shutdown'} write failed`)))
    return true
  })
  const child = new FakeChild({ stdin, killResult: false })
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await assert.rejects(context.controller.startParentChannel(ownership), /start write failed/)
  const termination = ownership.terminationPromise
  assert.ok(termination instanceof Promise)
  assert.strictEqual(
    context.controller.requestTermination(ownership, { reason: 'startup-failure' }),
    termination,
  )
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(stdin.writes, ['START exact-instance\n', 'SHUTDOWN\n'])
  assert.equal(child.killCount, 1)
  assert.equal(ownership.killAttemptCount, 1)
  assert.equal(ownership.killAccepted, false)
  assert.strictEqual(context.getCurrentOwnership(), ownership)

  child.emitExit(1, null)
  let settled = false
  termination.then(() => { settled = true }, () => { settled = true })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(settled, false)
  assert.equal(child.killCount, 1)
  assert.strictEqual(context.getCurrentOwnership(), ownership)
  assert.deepEqual(context.logEnds, [])

  child.emitClose(1, null)
  await termination
  assert.equal(settled, true)
  assert.equal(context.getCurrentOwnership(), null)
  assert.deepEqual(context.logEnds, [ownership])
})

test('graceful termination shares one promise, writes one SHUTDOWN, keeps stdin open, and never kills', async () => {
  const timers = createManualTimers()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  await context.controller.startParentChannel(ownership)

  const first = context.controller.requestTermination(ownership, { reason: 'startup-failure' })
  const second = context.controller.requestTermination(ownership, { reason: 'before-quit' })
  const third = context.controller.requestTermination(ownership, { reason: 'qa-deadline' })
  assert.strictEqual(first, second)
  assert.strictEqual(second, third)
  await new Promise((resolve) => setImmediate(resolve))
  assert.deepEqual(child.stdin.writes, ['START exact-instance\n', 'SHUTDOWN\n'])
  assert.equal(child.stdin.endCount, 0)

  child.emitClose(0, null)
  await first
  assert.equal(child.killCount, 0)
  assert.equal(ownership.killAttemptCount, 0)
  assert.equal(context.getCurrentOwnership(), null)
  assert.equal(context.logEnds.length, 1)
  assert.equal(timers.activeCount(), 0)
})

test('timeout kills only the exact current live child once and final no-close failure retains authority', async () => {
  const timers = createManualTimers()
  const child = new FakeChild({ killResult: false })
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  await context.controller.startParentChannel(ownership)
  const termination = context.controller.requestTermination(ownership, { reason: 'before-quit' })
  const rejection = assert.rejects(termination, /did not close/i)
  await new Promise((resolve) => setImmediate(resolve))

  assert.equal(timers.runNext(), 10)
  assert.equal(child.killCount, 1)
  assert.equal(ownership.killAttemptCount, 1)
  assert.equal(ownership.killAccepted, false)
  assert.strictEqual(context.getCurrentOwnership(), ownership)
  assert.equal(timers.runNext(), 10)
  await rejection

  assert.strictEqual(context.getCurrentOwnership(), ownership)
  assert.strictEqual(context.controller.requestTermination(ownership), termination)
  assert.equal(child.killCount, 1)
  assert.equal(timers.activeCount(), 0)
})

test('exit before the grace deadline forbids kill while the private promise still waits for exact close', async () => {
  const timers = createManualTimers()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  await context.controller.startParentChannel(ownership)
  const termination = context.controller.requestTermination(ownership)

  child.emitExit(0, null)
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(timers.runNext(), 10)
  assert.equal(child.killCount, 0)
  assert.equal(ownership.exitObserved, true)
  assert.equal(ownership.closeObserved, false)
  assert.strictEqual(context.getCurrentOwnership(), ownership)

  child.emitClose(0, null)
  await termination
  assert.equal(timers.activeCount(), 0)
})

test('stale child events and stale timeout remain private and never clear, invalidate, or kill replacement ownership', async () => {
  const timers = createManualTimers()
  const staleChild = new FakeChild({ pid: 321 })
  const stale = createOwnership(staleChild, 'stale-instance')
  const context = makeController(stale, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  await context.controller.startParentChannel(stale)
  const termination = context.controller.requestTermination(stale)

  const replacementChild = new FakeChild({ pid: 654 })
  const replacement = createOwnership(replacementChild, 'replacement-instance')
  context.setCurrentOwnership(replacement)
  staleChild.emitExit(1, null)
  await new Promise((resolve) => setImmediate(resolve))
  assert.strictEqual(context.getCurrentOwnership(), replacement)
  assert.deepEqual(context.invalidations, [])

  assert.equal(timers.runNext(), 10)
  assert.equal(staleChild.killCount, 0)
  staleChild.emitClose(1, null)
  await termination
  assert.strictEqual(context.getCurrentOwnership(), replacement)
  assert.deepEqual(context.invalidations, [])
})

test('unexpected exact exit invalidates once, while requested graceful close does not', async () => {
  const unexpectedChild = new FakeChild()
  const unexpected = createOwnership(unexpectedChild)
  const unexpectedContext = makeController(unexpected)

  unexpectedChild.emitExit(9, null)
  unexpectedChild.emitClose(9, null)
  assert.deepEqual(unexpectedContext.invalidations, [[unexpected, 'exit']])
  assert.equal(unexpected.exitObserved, true)
  assert.equal(unexpected.exitCode, 9)
  assert.equal(unexpected.closeObserved, true)
  assert.equal(unexpected.closeCode, 9)

  const gracefulChild = new FakeChild()
  const graceful = createOwnership(gracefulChild)
  const gracefulContext = makeController(graceful)
  await gracefulContext.controller.startParentChannel(graceful)
  const termination = gracefulContext.controller.requestTermination(graceful)
  gracefulChild.emitClose(0, null)
  await termination
  assert.deepEqual(gracefulContext.invalidations, [])
})

test('unexpected exit retains exact authority so before-quit waits for close before one final quit', async () => {
  const { createBeforeQuitController } = loadShutdownModule()
  const timers = createManualTimers()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  let quitCount = 0
  const beforeQuit = createBeforeQuitController({
    app: { quit: () => { quitCount += 1 } },
    requestCurrentOrPendingTermination: (options) => (
      context.controller.requestCurrentOrPendingTermination(options)
    ),
  })

  child.emitExit(7, null)
  assert.strictEqual(context.getCurrentOwnership(), ownership)
  assert.deepEqual(context.invalidations, [[ownership, 'exit']])
  const event = { prevented: 0, preventDefault() { this.prevented += 1 } }
  const closeBarrier = beforeQuit.handleBeforeQuit(event)
  assert.strictEqual(closeBarrier, ownership.terminationPromise)
  assert.equal(event.prevented, 1)
  assert.equal(quitCount, 0)

  child.emitClose(7, null)
  await closeBarrier
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(quitCount, 1)
  assert.equal(context.getCurrentOwnership(), null)
  assert.deepEqual(context.invalidations, [[ownership, 'exit']])
  assert.equal(child.killCount, 0)
})

test('ready stdin failure invalidates exact runtime once before internal bounded termination', async () => {
  const timers = createManualTimers()
  const terminationFailures = []
  const child = new FakeChild({ killResult: false })
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    onTerminationFailure: (error, candidate) => terminationFailures.push([candidate, error.message]),
  })
  await context.controller.startParentChannel(ownership)
  ownership.verifiedIdentity = ownership.expectedIdentity

  child.stdin.emit('error', new Error('ready stdin failed'))
  const termination = ownership.terminationPromise
  assert.ok(termination instanceof Promise)
  assert.deepEqual(context.invalidations, [[ownership, 'stdin-error']])
  assert.equal(ownership.terminationRequested, true)
  assert.equal(child.killCount, 1)

  const rejected = assert.rejects(termination, /did not close/i)
  assert.equal(timers.runNext(), 10)
  await rejected
  assert.deepEqual(terminationFailures, [[ownership, `backend child pid=${ownership.pid} did not close after bounded termination`]])
  child.emitExit(1, null)
  child.emitClose(1, null)
  assert.deepEqual(context.invalidations, [[ownership, 'stdin-error']])
  assert.equal(context.getCurrentOwnership(), null)
})

for (const [stage, emitFailure] of [
  ['child-error', (child) => child.emit('error', new Error('ready child failed'))],
  ['stdin-close', (child) => child.stdin.emit('close')],
]) {
  test(`ready ${stage} invalidates exact runtime once before internal termination`, async () => {
    const child = new FakeChild()
    const ownership = createOwnership(child)
    const context = makeController(ownership)
    await context.controller.startParentChannel(ownership)
    ownership.verifiedIdentity = ownership.expectedIdentity

    emitFailure(child)
    assert.deepEqual(context.invalidations, [[ownership, stage]])
    assert.equal(ownership.terminationRequested, true)
    const termination = ownership.terminationPromise
    child.emitExit(1, null)
    child.emitClose(1, null)
    await termination
    assert.deepEqual(context.invalidations, [[ownership, stage]])
  })
}

test('pipe failure after explicit graceful termination does not invalidate or duplicate termination', async () => {
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership)
  await context.controller.startParentChannel(ownership)
  const termination = context.controller.requestTermination(ownership, { reason: 'before-quit' })
  await new Promise((resolve) => setImmediate(resolve))

  child.stdin.emit('error', new Error('pipe closed during requested shutdown'))
  assert.strictEqual(ownership.terminationPromise, termination)
  assert.deepEqual(context.invalidations, [])
  child.emitExit(0, null)
  child.emitClose(0, null)
  await termination
  assert.deepEqual(child.stdin.writes, ['START exact-instance\n', 'SHUTDOWN\n'])
  assert.equal(child.killCount, 1)
  assert.deepEqual(context.invalidations, [])
})

test('exact and stale child callbacks cannot replace lifecycle facts even when diagnostics throw', () => {
  const { createBackendShutdownController } = loadShutdownModule()
  const exactChild = new FakeChild({ pid: 321 })
  const exact = createOwnership(exactChild, 'exact-callback')
  const replacementChild = new FakeChild({ pid: 654 })
  const replacement = createOwnership(replacementChild, 'replacement-callback')
  let current = exact
  const callbacks = []
  const diagnostics = []
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => current,
    setCurrentOwnership: (value) => { current = value },
    isCurrentOwnershipLive: (candidate) => current === candidate,
    invalidateStartup: () => {},
    onDiagnostic: (_error, stage) => diagnostics.push(stage),
  })
  controller.attachOwnership(exact, {
    onChildEvent: (name) => {
      callbacks.push(`exact:${name}`)
      throw new Error(`diagnostic ${name} failed`)
    },
  })
  controller.attachOwnership(replacement, {
    onChildEvent: (name) => callbacks.push(`replacement:${name}`),
  })

  exactChild.emitExit(7, null)
  assert.strictEqual(current, exact)
  current = replacement
  exactChild.emitClose(7, null)

  assert.strictEqual(current, replacement)
  assert.deepEqual(callbacks, ['exact:exit', 'exact:close'])
  assert.deepEqual(diagnostics, ['exit-callback', 'close-callback'])
  assert.equal(exact.exitObserved, true)
  assert.equal(exact.closeObserved, true)
  assert.equal(replacement.exitObserved, false)
  assert.equal(replacement.closeObserved, false)
})

test('before-quit discovers pending spawn setup, reuses its exact cleanup, and waits for close', async () => {
  const { createBackendShutdownController, createBeforeQuitController } = loadShutdownModule()
  const timers = createManualTimers()
  const child = new FakeChild()
  let currentOwnership = null
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: () => false,
    finalTimeoutMs: 10,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  controller.registerSpawnSetup(child)
  let quitCount = 0
  const beforeQuit = createBeforeQuitController({
    app: { quit: () => { quitCount += 1 } },
    requestCurrentOrPendingTermination: (options) => (
      controller.requestCurrentOrPendingTermination(options)
    ),
  })
  const firstEvent = { prevented: 0, preventDefault() { this.prevented += 1 } }
  const secondEvent = { prevented: 0, preventDefault() { this.prevented += 1 } }

  const first = beforeQuit.handleBeforeQuit(firstEvent)
  const second = beforeQuit.handleBeforeQuit(secondEvent)

  assert.strictEqual(second, first)
  assert.equal(firstEvent.prevented, 1)
  assert.equal(secondEvent.prevented, 1)
  assert.equal(child.stdin.endCount, 1)
  assert.equal(child.killCount, 1)
  assert.equal(quitCount, 0)
  child.emitExit(0, null)
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(quitCount, 0)
  child.emitClose(0, null)
  await first
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(quitCount, 1)
})

test('pending setup termination wins over ownership handoff and exposes the same close promise', async () => {
  const { createBackendShutdownController } = loadShutdownModule()
  const timers = createManualTimers()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  let currentOwnership = null
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: (candidate) => currentOwnership === candidate,
    finalTimeoutMs: 10,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  const setupAuthority = controller.registerSpawnSetup(child)
  const termination = controller.requestCurrentOrPendingTermination({ reason: 'qa-deadline' })

  let handoffError = null
  try {
    controller.handoffSpawnSetup(setupAuthority, ownership)
  } catch (error) {
    handoffError = error
  }

  assert.equal(handoffError?.code, 'DXM_BACKEND_SETUP_TERMINATING')
  assert.strictEqual(handoffError?.terminationPromise, termination)
  assert.strictEqual(
    controller.requestCurrentOrPendingTermination({ reason: 'startup-failure' }),
    termination,
  )
  assert.equal(currentOwnership, null)
  assert.equal(ownership.lifecycleAttached, false)
  assert.equal(child.killCount, 1)
  child.emitClose(0, null)
  await termination
})

test('registration conflict cleans only the new child and cannot publish current plus pending', async () => {
  const { createBackendShutdownController } = loadShutdownModule()
  const existingChild = new FakeChild({ pid: 111 })
  const existing = createOwnership(existingChild, 'existing')
  const pendingChild = new FakeChild({ pid: 222 })
  let currentOwnership = existing
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: (candidate) => currentOwnership === candidate,
  })
  controller.attachOwnership(existing)

  let registrationError = null
  try {
    controller.registerSpawnSetup(pendingChild)
  } catch (error) {
    registrationError = error
  }

  assert.equal(registrationError?.code, 'DXM_BACKEND_CURRENT_OWNERSHIP_CONFLICT')
  assert.ok(registrationError?.terminationPromise instanceof Promise)
  assert.strictEqual(currentOwnership, existing)
  assert.equal(existingChild.killCount, 0)
  assert.equal(pendingChild.stdin.endCount, 1)
  assert.equal(pendingChild.killCount, 1)
  pendingChild.emitClose(1, null)
  await registrationError.terminationPromise
  assert.strictEqual(currentOwnership, existing)
  currentOwnership = null
  assert.deepEqual(
    await controller.requestCurrentOrPendingTermination({ reason: 'after-conflict' }),
    { ignored: true, closed: true },
  )
  existingChild.emitClose(0, null)
})

test('active pending registration conflict cleans only the newcomer and retains the first authority', async () => {
  const { createBackendShutdownController } = loadShutdownModule()
  const firstChild = new FakeChild({ pid: 111 })
  const newcomer = new FakeChild({ pid: 222 })
  let currentOwnership = null
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: () => false,
  })
  controller.registerSpawnSetup(firstChild)

  let registrationError = null
  try {
    controller.registerSpawnSetup(newcomer)
  } catch (error) {
    registrationError = error
  }

  assert.equal(registrationError?.code, 'DXM_BACKEND_PENDING_SETUP_CONFLICT')
  assert.ok(registrationError?.terminationPromise instanceof Promise)
  assert.equal(firstChild.stdin.endCount, 0)
  assert.equal(firstChild.killCount, 0)
  assert.equal(newcomer.stdin.endCount, 1)
  assert.equal(newcomer.killCount, 1)
  const firstTermination = controller.requestCurrentOrPendingTermination({ reason: 'before-quit' })
  assert.notStrictEqual(firstTermination, registrationError.terminationPromise)
  assert.equal(firstChild.killCount, 1)

  newcomer.emitClose(1, null)
  firstChild.emitClose(1, null)
  await Promise.all([registrationError.terminationPromise, firstTermination])
  assert.strictEqual(currentOwnership, null)
})

test('successful setup handoff transfers one exact child lifecycle before START', async () => {
  const { createBackendShutdownController } = loadShutdownModule()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  let currentOwnership = null
  const controller = createBackendShutdownController({
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    isCurrentOwnershipLive: (candidate) => currentOwnership === candidate
      && candidate.child.exitCode === null
      && candidate.child.signalCode === null,
  })
  const setupAuthority = controller.registerSpawnSetup(child)

  assert.strictEqual(
    controller.handoffSpawnSetup(setupAuthority, ownership),
    ownership,
  )
  assert.strictEqual(currentOwnership, ownership)
  assert.equal(ownership.lifecycleAttached, true)
  assert.equal(child.listenerCount('close'), 1)
  assert.equal(child.listenerCount('error'), 1)
  assert.equal(child.stdin.listenerCount('error'), 1)
  await controller.startParentChannel(ownership)
  assert.deepEqual(child.stdin.writes, ['START exact-instance\n'])

  const termination = controller.requestCurrentOrPendingTermination({ reason: 'startup-failure' })
  child.emitClose(0, null)
  await termination
  assert.strictEqual(currentOwnership, null)
  assert.equal(child.killCount, 0)
})

test('startup, QA, and before-quit reuse one pending setup cleanup in either request order', async () => {
  const { createBackendShutdownController, createBeforeQuitController } = loadShutdownModule()
  for (const reasons of [
    ['startup-failure', 'qa-deadline'],
    ['qa-deadline', 'startup-failure'],
  ]) {
    const child = new FakeChild()
    let currentOwnership = null
    const controller = createBackendShutdownController({
      getCurrentOwnership: () => currentOwnership,
      setCurrentOwnership: (value) => { currentOwnership = value },
      isCurrentOwnershipLive: () => false,
    })
    controller.registerSpawnSetup(child)
    const first = controller.requestCurrentOrPendingTermination({ reason: reasons[0] })
    const second = controller.requestCurrentOrPendingTermination({ reason: reasons[1] })
    const beforeQuit = createBeforeQuitController({
      app: { quit: () => {} },
      requestCurrentOrPendingTermination: (options) => (
        controller.requestCurrentOrPendingTermination(options)
      ),
    }).handleBeforeQuit({ preventDefault() {} })

    assert.strictEqual(second, first)
    assert.strictEqual(beforeQuit, first)
    assert.equal(child.stdin.endCount, 1)
    assert.equal(child.killCount, 1)
    child.emitClose(0, null)
    await first
  }
})

test('before-quit prevents every repeated request, reuses termination, then permits one final quit without recursion', async () => {
  const { createBeforeQuitController } = loadShutdownModule()
  const ownership = { id: 'owned' }
  let resolveTermination
  const termination = new Promise((resolve) => { resolveTermination = resolve })
  const requests = []
  let quitCount = 0
  const coordinator = createBeforeQuitController({
    app: { quit: () => { quitCount += 1 } },
    requestCurrentOrPendingTermination: (options) => {
      requests.push([ownership, options.reason])
      return termination
    },
  })
  const firstEvent = { prevented: 0, preventDefault() { this.prevented += 1 } }
  const secondEvent = { prevented: 0, preventDefault() { this.prevented += 1 } }

  assert.strictEqual(coordinator.handleBeforeQuit(firstEvent), termination)
  assert.strictEqual(coordinator.handleBeforeQuit(secondEvent), termination)
  assert.equal(firstEvent.prevented, 1)
  assert.equal(secondEvent.prevented, 1)
  assert.deepEqual(requests, [[ownership, 'before-quit']])
  assert.equal(quitCount, 0)

  resolveTermination()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(quitCount, 1)
  const finalEvent = { prevented: 0, preventDefault() { this.prevented += 1 } }
  assert.equal(coordinator.handleBeforeQuit(finalEvent), null)
  assert.equal(finalEvent.prevented, 0)
  assert.equal(quitCount, 1)
})

test('before-quit reuses startup-failure termination after exit and still waits for close', async () => {
  const { createBeforeQuitController } = loadShutdownModule()
  const timers = createManualTimers()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership, {
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  await context.controller.startParentChannel(ownership)
  const startupFailureTermination = context.controller.requestTermination(ownership, {
    reason: 'startup-failure',
  })
  await new Promise((resolve) => setImmediate(resolve))

  child.emitExit(1, null)
  assert.strictEqual(context.getCurrentOwnership(), ownership)
  assert.equal(ownership.closeObserved, false)

  let quitCount = 0
  const beforeQuit = createBeforeQuitController({
    app: { quit: () => { quitCount += 1 } },
    requestCurrentOrPendingTermination: (options) => (
      context.controller.requestCurrentOrPendingTermination(options)
    ),
  })
  const event = { prevented: 0, preventDefault() { this.prevented += 1 } }
  const beforeQuitTermination = beforeQuit.handleBeforeQuit(event)

  assert.strictEqual(beforeQuitTermination, startupFailureTermination)
  assert.equal(event.prevented, 1)
  assert.equal(quitCount, 0)

  child.emitClose(1, null)
  await beforeQuitTermination
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(quitCount, 1)
})

test('startup, QA, and before-quit reuse one current-or-pending termination promise in any order', async () => {
  const { createBeforeQuitController } = loadShutdownModule()
  const child = new FakeChild()
  const ownership = createOwnership(child)
  const context = makeController(ownership)
  await context.controller.startParentChannel(ownership)

  const startup = context.controller.requestCurrentOrPendingTermination({ reason: 'startup-failure' })
  child.emitExit(1, null)
  const qa = context.controller.requestCurrentOrPendingTermination({ reason: 'qa-deadline' })
  context.setCurrentOwnership(null)
  const pending = context.controller.requestCurrentOrPendingTermination({ reason: 'late-startup-handler' })
  const beforeQuit = createBeforeQuitController({
    app: { quit: () => {} },
    requestCurrentOrPendingTermination: (options) => (
      context.controller.requestCurrentOrPendingTermination(options)
    ),
  }).handleBeforeQuit({ preventDefault() {} })

  assert.strictEqual(startup, ownership.terminationPromise)
  assert.strictEqual(qa, startup)
  assert.strictEqual(pending, startup)
  assert.strictEqual(beforeQuit, startup)
  child.emitClose(1, null)
  await startup

  const ignored = context.controller.requestCurrentOrPendingTermination({ reason: 'after-close' })
  assert.deepEqual(await ignored, { ignored: true, closed: true })
})

function makeUnownedBarrier(child, overrides = {}) {
  const { createSpawnSetupCleanup } = loadShutdownModule()
  const timers = createManualTimers()
  const closes = []
  const diagnostics = []
  const childErrors = []
  const barrier = createSpawnSetupCleanup(child, {
    timeoutMs: 10,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    onClose: (code, signal) => closes.push([code, signal]),
    onChildError: (error) => childErrors.push(error.message),
    onDiagnostic: (error, stage) => diagnostics.push([stage, error.message]),
    ...overrides,
  })
  return { barrier, timers, closes, diagnostics, childErrors }
}

function makeLogOpenGate(stream, overrides = {}) {
  const { createWritableLogOpenGate } = loadShutdownModule()
  const timers = createManualTimers()
  const errors = []
  const diagnostics = []
  const gate = createWritableLogOpenGate(stream, {
    timeoutMs: 10,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    onError: (error, phase) => errors.push([phase, error.message]),
    onDiagnostic: (error, stage) => diagnostics.push([stage, error.message]),
    ...overrides,
  })
  return { gate, timers, errors, diagnostics }
}

test('writable log failure classification keeps stale ownership inert and setup failures latched', () => {
  const { classifyWritableLogFailure } = loadShutdownModule()
  const ownership = { id: 'spawn-under-setup' }
  const replacement = { id: 'replacement' }

  assert.equal(classifyWritableLogFailure({
    phase: 'opening',
    ownership,
    currentOwnership: replacement,
    setupCleanupReleased: true,
  }), 'opening')
  assert.equal(classifyWritableLogFailure({
    phase: 'opened',
    ownership,
    currentOwnership: replacement,
    setupCleanupReleased: false,
  }), 'setup')
  assert.equal(classifyWritableLogFailure({
    phase: 'opened',
    ownership,
    currentOwnership: ownership,
    setupCleanupReleased: false,
  }), 'setup')
  assert.equal(classifyWritableLogFailure({
    phase: 'opened',
    ownership,
    currentOwnership: replacement,
    setupCleanupReleased: true,
  }), 'stale')
  assert.equal(classifyWritableLogFailure({
    phase: 'opened',
    ownership: null,
    currentOwnership: null,
    setupCleanupReleased: true,
  }), 'stale')
  assert.equal(classifyWritableLogFailure({
    phase: 'opened',
    ownership,
    currentOwnership: ownership,
    setupCleanupReleased: true,
  }), 'exact-current')
})

test('writable log gate resolves an already-open stream and absorbs a later write error until close', async () => {
  const stream = new FakeLogStream({ opened: true })
  const context = makeLogOpenGate(stream)

  const first = context.gate.waitUntilOpen()
  assert.strictEqual(context.gate.waitUntilOpen(), first)
  assert.strictEqual(await first, stream)
  assert.doesNotThrow(() => stream.emit('error', new Error('late log write failed')))
  assert.deepEqual(context.errors, [['opened', 'late log write failed']])
  assert.equal(stream.listenerCount('error'), 1)
  stream.emitClose()
  assert.equal(stream.listenerCount('error'), 0)
  assert.equal(context.timers.activeCount(), 0)
})

test('writable log gate rejects one stable promise on open error, close-before-open, or timeout', async () => {
  const openErrorStream = new FakeLogStream()
  const openErrorContext = makeLogOpenGate(openErrorStream)
  const openError = openErrorContext.gate.waitUntilOpen()
  assert.doesNotThrow(() => openErrorStream.emit('error', new Error('open ENOENT')))
  await assert.rejects(openError, /open ENOENT/)
  assert.strictEqual(openErrorContext.gate.waitUntilOpen(), openError)
  assert.deepEqual(openErrorContext.errors, [['opening', 'open ENOENT']])
  openErrorStream.emitClose()
  assert.equal(openErrorStream.listenerCount('error'), 0)

  const earlyCloseStream = new FakeLogStream()
  const earlyCloseContext = makeLogOpenGate(earlyCloseStream)
  const earlyClose = earlyCloseContext.gate.waitUntilOpen()
  earlyCloseStream.emitClose()
  await assert.rejects(earlyClose, /closed before open/i)
  assert.equal(earlyCloseStream.listenerCount('error'), 0)

  const timeoutStream = new FakeLogStream()
  const timeoutContext = makeLogOpenGate(timeoutStream)
  const timedOut = timeoutContext.gate.waitUntilOpen()
  assert.equal(timeoutContext.timers.runNext(), 10)
  await assert.rejects(timedOut, /did not open/i)
  assert.strictEqual(timeoutContext.gate.waitUntilOpen(), timedOut)
  timeoutStream.emitClose()
  assert.equal(timeoutStream.listenerCount('error'), 0)
})

test('real asynchronous log ENOENT forbids START and startup waits for exact child close', async () => {
  const missingParent = path.join(
    os.tmpdir(),
    `dxm-missing-log-parent-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  )
  const logStream = fs.createWriteStream(path.join(missingParent, 'backend.log'), { flags: 'a' })
  const logGate = makeLogOpenGate(logStream, { timeoutMs: 1000 })
  const child = new FakeChild()
  const cleanup = makeUnownedBarrier(child)
  const startup = (async () => {
    try {
      await logGate.gate.waitUntilOpen()
      child.stdin.write('START forbidden\n', () => {})
    } catch (error) {
      await cleanup.barrier.terminate({ reason: 'log-open' })
      throw error
    }
  })()
  const rejected = assert.rejects(startup, /ENOENT/)

  // fs error delivery is I/O scheduled, not a promise microtask.  A sequence
  // of setImmediate turns can finish before Windows reports ENOENT under a
  // busy build, which made this safety assertion flaky despite the production
  // gate being correct.  Wait on a short bounded clock instead.
  for (let attempt = 0; attempt < 40 && child.killCount === 0; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
  assert.deepEqual(child.stdin.writes, [])
  assert.equal(child.stdin.endCount, 1)
  assert.equal(child.killCount, 1)
  let settled = false
  startup.then(() => { settled = true }, () => { settled = true })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(settled, false)

  child.emitClose(1, null)
  await rejected
  assert.equal(settled, true)
})

test('unowned spawn close barrier is installed immediately and close-before-terminate performs no I/O', async () => {
  const child = new FakeChild()
  const context = makeUnownedBarrier(child)

  assert.equal(child.listenerCount('close'), 1)
  assert.equal(child.listenerCount('error'), 1)
  child.emitClose(0, null)
  assert.equal(context.barrier.release(), false)
  const termination = context.barrier.terminate({ reason: 'invalid-pid' })

  assert.deepEqual(await termination, {
    ignored: false,
    closed: true,
    killAttempted: false,
    stdinEndAttempted: false,
  })
  assert.equal(child.stdin.endCount, 0)
  assert.equal(child.killCount, 0)
  assert.deepEqual(context.closes, [[0, null]])
  assert.equal(context.timers.activeCount(), 0)
})

for (const [label, killResult, expectedDiagnostic] of [
  ['kill false', false, 'unowned-kill-rejected'],
  ['kill throw', new Error('kill exploded'), 'unowned-kill'],
]) {
  test(`unowned spawn ${label} is recorded once and still waits for exact close`, async () => {
    const child = new FakeChild({ killResult })
    const context = makeUnownedBarrier(child)
    const termination = context.barrier.terminate({ reason: 'startup-construction' })

    assert.equal(child.stdin.endCount, 1)
    assert.equal(child.killCount, 1)
    const facts = context.barrier.getFacts()
    assert.equal(facts.killAttempted, true)
    assert.equal(facts.killAccepted, false)
    assert.equal(facts.killError, killResult instanceof Error ? 'kill exploded' : null)
    assert.equal(context.diagnostics.some(([stage]) => stage === expectedDiagnostic), true)

    child.emitClose(1, null)
    assert.deepEqual(await termination, {
      ignored: false,
      closed: true,
      killAttempted: true,
      stdinEndAttempted: true,
    })
    assert.equal(child.killCount, 1)
    assert.equal(context.timers.activeCount(), 0)
  })
}

test('unowned spawn no-close rejects after the bounded final wait and never retries exact kill', async () => {
  const child = new FakeChild({ killResult: true })
  const context = makeUnownedBarrier(child)
  const termination = context.barrier.terminate({ reason: 'startup-construction' })
  const rejected = assert.rejects(termination, (error) => {
    assert.equal(error.code, 'DXM_UNOWNED_BACKEND_CLOSE_TIMEOUT')
    assert.equal(error.cleanupFacts.killAttempted, true)
    assert.equal(error.cleanupFacts.killAccepted, true)
    return true
  })

  assert.equal(child.killCount, 1)
  assert.equal(context.timers.runNext(), 10)
  await rejected
  assert.equal(child.killCount, 1)
  assert.strictEqual(
    context.barrier.terminate({ reason: 'repeated-cleanup' }),
    termination,
  )
})

test('unowned setup timeout still ends the log exactly once on a later exact close', async () => {
  const child = new FakeChild({ killResult: false })
  let logEndCount = 0
  const context = makeUnownedBarrier(child, {
    onClose: () => { logEndCount += 1 },
  })
  const termination = context.barrier.terminate({ reason: 'startup-construction' })
  const rejected = assert.rejects(termination, /did not close/i)

  assert.equal(context.timers.runNext(), 10)
  await rejected
  assert.equal(logEndCount, 0)
  child.emitClose(1, null)
  child.emitClose(1, null)
  assert.equal(logEndCount, 1)
})

test('unowned setup records asynchronous stdin failure after end without an unhandled error', async () => {
  const child = new FakeChild()
  const context = makeUnownedBarrier(child)
  const termination = context.barrier.terminate({ reason: 'startup-construction' })

  assert.doesNotThrow(() => child.stdin.emit('error', new Error('late setup EPIPE')))
  assert.equal(context.barrier.getFacts().stdinError, 'late setup EPIPE')
  assert.equal(
    context.diagnostics.some(([stage, message]) => (
      stage === 'unowned-stdin-error' && message === 'late setup EPIPE'
    )),
    true,
  )
  child.emitClose(1, null)
  await termination
  assert.equal(child.stdin.listenerCount('error'), 0)
})

test('unowned setup timer installation failure rejects the stable cleanup promise', async () => {
  const child = new FakeChild()
  const context = makeUnownedBarrier(child, {
    setTimer: () => { throw new Error('timer install exploded') },
  })
  let termination = null

  assert.doesNotThrow(() => {
    termination = context.barrier.terminate({ reason: 'startup-construction' })
  })
  await assert.rejects(termination, /timer install exploded/)
  assert.strictEqual(context.barrier.terminate({ reason: 'repeated' }), termination)
  assert.equal(child.killCount, 1)
})

test('released unowned spawn barrier is inert after owned lifecycle takes authority', async () => {
  const child = new FakeChild()
  const context = makeUnownedBarrier(child)

  assert.equal(context.barrier.release(), true)
  assert.equal(context.barrier.release(), false)
  assert.equal(child.listenerCount('close'), 0)
  assert.equal(child.listenerCount('error'), 0)
  assert.deepEqual(await context.barrier.terminate({ reason: 'late-failure' }), {
    ignored: true,
    released: true,
    closed: false,
  })
  child.emitClose(0, null)
  assert.equal(child.stdin.endCount, 0)
  assert.equal(child.killCount, 0)
  assert.deepEqual(context.closes, [])
  assert.equal(context.timers.activeCount(), 0)
})
