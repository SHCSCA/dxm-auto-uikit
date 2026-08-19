import assert from 'node:assert/strict'
import test from 'node:test'

import { filterAuditEvents, humanAuditAction } from '../src/operationAudit.ts'

test('filters timeline by task and status', () => {
  const events = [
    { seq: 1, recorded_at: 't1', event_id: 'a', correlation_id: 'c1', root_correlation_id: 'r', actor: 'operator', component: 'plan', action: 'preview', phase: 'completed', status: 'ok', task_id: '10' },
    { seq: 2, recorded_at: 't2', event_id: 'b', correlation_id: 'c2', root_correlation_id: 'r', actor: 'runner', component: 'save', action: 'save_only_click', phase: 'dispatched', status: 'UNKNOWN', task_id: '10', product_id: '99' },
    { seq: 3, recorded_at: 't3', event_id: 'c', correlation_id: 'c3', root_correlation_id: 'r', actor: 'operator', component: 'plan', action: 'preview', phase: 'completed', status: 'ok', task_id: '11' },
  ]
  const filtered = filterAuditEvents(events, { task_id: '10', status: 'UNKNOWN' })
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].event_id, 'b')
})

test('uses chinese labels for known actions', () => {
  assert.equal(humanAuditAction({ action: 'approve_and_start' }), '批准并开始')
})
