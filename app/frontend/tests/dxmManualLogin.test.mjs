import assert from 'node:assert/strict'
import test from 'node:test'
import { createManualLoginController, manualLoginDisabledReason, manualLoginRuntimeView } from '../src/dxmManualLogin.ts'
import { canContinueDxmLogin } from '../src/dxmLoginUi.ts'

function state() {
  return { runtimeStatus: { browserAgent: { status: 'idle', active: false, manualTakeover: false,
    needsRestart: false, executionLeaseActive: false, sessionOperationActive: false, reservedCommandCount: 0 },
    agentConsole: { active: false }, dxmLogin: { status: 'logged_out', loggedIn: false, readerReady: false } },
    runtimeStatusError: null, busy: false, requestPending: false, hasActiveTask: false, hasActiveBatch: false,
    batchStateAvailable: true, agentConsoleActive: false }
}

function controller(current) {
  const events = []
  const open = createManualLoginController({ getState: () => current,
    pending: (value) => events.push(['pending', value]), error: (value) => events.push(['error', value]),
    notice: (value) => events.push(['notice', value]), invalidate: () => events.push(['invalidate']),
    handoff: () => events.push(['handoff']), refresh: async () => events.push(['refresh']) })
  return { open, events }
}

const handoff = { ok: true, stage: 'manual_login_required', reason_code: 'MANAGED_MANUAL_LOGIN_REQUIRED',
  logged_in: false, reader_ready: false, browser_visible: true }

test('manual open uses the actual API bus with an empty body and no credential dependency', async (t) => {
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    requests.push([url, init.method, JSON.parse(init.body)])
    return new Response(JSON.stringify(handoff), { status: 200 })
  })
  const { open, events } = controller(state())
  assert.equal(await open(), true)
  assert.deepEqual(requests, [['/api/dxm/workflow/manual-login', 'POST', {}]])
  assert.equal(events.filter(([event]) => event === 'handoff').length, 1)
  assert.match(events.find(([event, value]) => event === 'notice' && value)?.[1], /窗口已打开.*检测登录状态/)
  assert.deepEqual(events.at(-2), ['pending', false])
  assert.deepEqual(events.at(-1), ['refresh'])
})

test('runtime handoff clears old login qualification and permits only the existing detection action', () => {
  const old = state().runtimeStatus
  old.dxmLogin = { status: 'login_success', loggedIn: true, readerReady: true }
  const actual = manualLoginRuntimeView(old, true)
  assert.equal(actual.dxmLogin.loggedIn, false)
  assert.equal(actual.dxmLogin.readerReady, false)
  assert.equal(old.dxmLogin.readerReady, true)
  assert.equal(canContinueDxmLogin({ status: actual.dxmLogin.status, browserVisible: true, busy: false }), true)
  assert.match(manualLoginDisabledReason({ ...state(), runtimeStatus: actual }), /窗口已打开/)
})

test('busy, takeover, unknown flags, active task or reservation prevent any request', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => { calls++; throw new Error('unexpected request') })
  const changes = [value => { value.busy = true }, value => { value.requestPending = true },
    value => { value.hasActiveTask = true }, value => { value.hasActiveBatch = true },
    value => { value.runtimeStatus.browserAgent.manualTakeover = true },
    value => { value.runtimeStatus.browserAgent.executionLeaseActive = true },
    value => { value.runtimeStatus.browserAgent.sessionOperationActive = true },
    value => { value.runtimeStatus.browserAgent.reservedCommandCount = 1 },
    value => { delete value.runtimeStatus.browserAgent.executionLeaseActive }]
  for (const change of changes) {
    const current = state(); change(current)
    assert.equal(await controller(current).open(), false)
  }
  assert.equal(calls, 0)
})

test('double activation stays single flight and a misleading ok response never hands off', async (t) => {
  let resolve, calls = 0
  t.mock.method(globalThis, 'fetch', () => {
    calls++
    return new Promise(done => { resolve = done })
  })
  const { open, events } = controller(state())
  const pending = open()
  assert.equal(await open(), false)
  resolve(new Response(JSON.stringify({ ...handoff, logged_in: true, reader_ready: true }), { status: 200 }))
  assert.equal(await pending, false)
  assert.equal(calls, 1)
  assert.equal(events.some(([event]) => event === 'handoff'), false)
  assert.match(events.find(([event, value]) => event === 'error' && value)?.[1], /未能确认/)
})

test('backend conflict remains visible and is never retried', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls++
    return new Response(JSON.stringify({ detail: { message: '当前浏览器正在人工接管，不能替换登录会话。' } }), { status: 409 })
  })
  const { open, events } = controller(state())
  assert.equal(await open(), false)
  assert.equal(calls, 1)
  assert.match(events.find(([event, value]) => event === 'error' && value)?.[1], /人工接管/)
})
