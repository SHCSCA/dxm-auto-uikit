import assert from 'node:assert/strict'
import test from 'node:test'
import { postJson } from '../src/api.ts'
import { frontendErrorEntries } from '../src/diagnostics/frontendErrors.ts'

test('failed write submission is recorded safely once and is never retried', async () => {
  let calls = 0
  const originalFetch = globalThis.fetch
  const originalConsole = console.error
  console.error = () => undefined
  globalThis.fetch = async () => {
    calls += 1
    throw new Error('password=secret 真实字段')
  }
  try {
    await assert.rejects(postJson('/api/tasks/91827/approve-and-start?token=secret', { password: 'secret' }))
    assert.equal(calls, 1)
    const entry = frontendErrorEntries().at(-1)
    assert.equal(entry.action, 'POST /api/tasks/:id/approve-and-start')
    assert.doesNotMatch(JSON.stringify(entry), /91827|password|secret|真实字段/)
  } finally {
    globalThis.fetch = originalFetch
    console.error = originalConsole
  }
})
