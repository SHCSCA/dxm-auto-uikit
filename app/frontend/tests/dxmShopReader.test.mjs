import assert from 'node:assert/strict'
import test from 'node:test'
import { createDxmShopReader } from '../src/dxmShopReader.ts'
import { frontendConfig } from '../src/config/frontendConfig.ts'

function deferred() {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function shops(id) {
  return { source: 'api', session_bound: true, session_ref: `synthetic-${id}`, shops: [{ id, name: `shop-${id}` }] }
}

function reader() {
  const events = []
  return { events, reader: createDxmShopReader({ commit: value => events.push(['commit', value]),
    loading: value => events.push(['loading', value]), error: value => events.push(['error', value]) }) }
}

function response(value) { return new Response(JSON.stringify(value), { status: 200 }) }

test('one session shares its in-flight GET and caches the actual returned snapshot', async (t) => {
  const request = deferred(); let calls = 0
  t.mock.method(globalThis, 'fetch', () => { calls++; return request.promise })
  const { reader: current, events } = reader()
  const first = current.refresh()
  assert.equal(current.refresh(true), first)
  request.resolve(response(shops('current')))
  assert.deepEqual(await first, shops('current'))
  assert.deepEqual(await current.refresh(), shops('current'))
  assert.equal(calls, 1)
  assert.deepEqual(events.at(-1), ['loading', false])
})

test('invalidate rejects both the old response and its return value while the new GET stays independent', async (t) => {
  const old = deferred(), fresh = deferred(); let calls = 0
  t.mock.method(globalThis, 'fetch', () => (++calls === 1 ? old.promise : fresh.promise))
  const { reader: current, events } = reader()
  const obsolete = current.refresh()
  current.invalidate()
  const active = current.refresh(true)
  const boundary = events.length
  old.resolve(response(shops('old')))
  assert.equal(await obsolete, null)
  assert.equal(events.length, boundary)
  assert.equal(current.refresh(true), active)
  assert.equal(calls, 2)
  fresh.resolve(response(shops('new')))
  assert.deepEqual(await active, shops('new'))
  assert.deepEqual(await current.refresh(), shops('new'))
  assert.equal(events.some(([kind, value]) => kind === 'commit' && value?.session_ref === 'synthetic-old'), false)
})

test('late old errors cannot clear the current loading owner or replace its visible error', async (t) => {
  const old = deferred(), fresh = deferred(); let calls = 0
  t.mock.method(globalThis, 'fetch', () => (++calls === 1 ? old.promise : fresh.promise))
  const { reader: current, events } = reader()
  const obsolete = current.refresh()
  current.invalidate()
  const active = current.refresh(true), boundary = events.length
  old.reject(new Error('synthetic obsolete request failure'))
  assert.equal(await obsolete, null)
  assert.equal(events.length, boundary)
  assert.equal(current.refresh(true), active)
  fresh.resolve(response(shops('new')))
  assert.deepEqual(await active, shops('new'))
})

test('a failed current refresh remains visible and preserves the last same-session verified snapshot', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    if (++calls === 1) return response(shops('current'))
    throw new Error('synthetic current request failure')
  })
  const { reader: current, events } = reader()
  await current.refresh()
  assert.equal(await current.refresh(true), null)
  assert.match(events.findLast(([kind, value]) => kind === 'error' && value)?.[1], /current request failure/)
  assert.deepEqual(await current.refresh(), shops('current'))
  assert.equal(calls, 2)
  current.invalidate()
  assert.deepEqual(events.at(-3), ['commit', null])
})

test('an obsolete session-busy retry never issues a fresh request in the new session', async (t) => {
  let calls = 0, retry
  const scheduled = deferred()
  t.mock.method(globalThis, 'setTimeout', (callback, delay) => {
    assert.equal(delay, frontendConfig.sessionBusy.delaysMs[0])
    retry = callback; scheduled.resolve(); return 0
  })
  t.mock.method(globalThis, 'fetch', async () => {
    if (++calls === 1) return new Response(JSON.stringify({ detail: '上一条会话操作仍在处理，请稍后。' }), { status: 409 })
    return response(shops('new'))
  })
  const { reader: current } = reader()
  const obsolete = current.refresh()
  await scheduled.promise
  current.invalidate()
  assert.deepEqual(await current.refresh(true), shops('new'))
  retry()
  assert.equal(await obsolete, null)
  assert.equal(calls, 2)
})
