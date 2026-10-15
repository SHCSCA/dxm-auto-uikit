import assert from 'node:assert/strict'
import test from 'node:test'
import { frontendErrorEntries, recordFrontendError } from '../src/diagnostics/frontendErrors.ts'
import { frontendConfig } from '../src/config/frontendConfig.ts'

test('frontend diagnostics are structured, bounded and exclude sensitive error contents', () => {
  const logged = []
  const original = console.error
  console.error = (value) => logged.push(value)
  try {
    for (let index = 0; index < frontendConfig.diagnostics.maximumEntries + 1; index += 1) {
      recordFrontendError(new Error('password=secret 商品真实字段'), { component: 'test', action: 'rejected_request', status: 409 })
    }
  } finally {
    console.error = original
  }
  const entries = frontendErrorEntries()
  assert.equal(entries.length, frontendConfig.diagnostics.maximumEntries)
  assert.equal(entries[0].schema, 'dxm.frontend_error.v1')
  assert.equal(entries[0].status, 409)
  assert.equal(entries[0].error_name, 'Error')
  assert.doesNotMatch(logged.join(''), /password|secret|商品真实字段|stack/)
})
