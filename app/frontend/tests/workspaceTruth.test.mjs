import assert from 'node:assert/strict'
import test from 'node:test'
import { buildEmptyWorkspace } from '../src/workspace.ts'

test('an empty or disconnected workspace does not invent release or save evidence', () => {
  const workspace = buildEmptyWorkspace()
  assert.deepEqual(workspace.tasks, [])
  assert.deepEqual(workspace.evidences, [])
  assert.equal(workspace.publishGuardState.safe, false)
  assert.equal(workspace.realModeReleasePlan.modes.every((mode) => mode.allowed === false), true)
  assert.equal(workspace.realModeReleasePlan.modes.every((mode) => mode.readiness_checklist.every((item) => item.status !== 'passed')), true)
})
