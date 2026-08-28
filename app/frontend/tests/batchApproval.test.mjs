import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BATCH_SAVE_ONLY_CONFIRMATION,
  batchTaskDestination,
  markBatchApprovalAttempted,
  nextBatchApprovalRequest,
} from '../src/batchApproval.ts'

test('atomic batch approval posts once then polls the task after an unknown outcome', () => {
  const approval = {
    taskId: 41,
    approvedBy: ' operator-a ',
    confirmation: BATCH_SAVE_ONLY_CONFIRMATION,
  }

  assert.deepEqual(nextBatchApprovalRequest(null, approval), {
    method: 'POST',
    path: '/api/tasks/41/approve-and-start',
    body: {
      approved_by: 'operator-a',
      confirmation: 'CONFIRM_DXM_SAVE_ONLY',
    },
  })

  assert.deepEqual(
    nextBatchApprovalRequest(markBatchApprovalAttempted(41), approval),
    {
      method: 'GET',
      path: '/api/tasks/41',
    },
  )
})

test('batch approval requires an operator and the exact save-only confirmation', () => {
  assert.throws(
    () => nextBatchApprovalRequest(null, {
      taskId: 41,
      approvedBy: '   ',
      confirmation: BATCH_SAVE_ONLY_CONFIRMATION,
    }),
    /请填写批准人/,
  )
  assert.throws(
    () => nextBatchApprovalRequest(null, {
      taskId: 41,
      approvedBy: 'operator-a',
      confirmation: 'confirm_dxm_save_only',
    }),
    /CONFIRM_DXM_SAVE_ONLY/,
  )
})

test('accepted batch tasks route to monitoring until a terminal result exists', () => {
  const task = {
    id: 41,
    name: 'frozen batch',
    status: 'running',
    mode: 'batch_draft_save',
    publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
    total_jobs: 3,
    completed_jobs: 0,
    failed_jobs: 0,
    payload: {},
  }

  assert.equal(batchTaskDestination(task), 'monitor')
  assert.equal(batchTaskDestination({ ...task, status: 'completed' }), 'results')
  assert.equal(
    batchTaskDestination({ ...task, status: 'needs_manual_review' }),
    'results',
  )
})
