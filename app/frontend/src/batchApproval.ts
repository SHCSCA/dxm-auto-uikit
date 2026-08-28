import type { Task } from './types'

export const BATCH_SAVE_ONLY_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'

export type BatchApprovalAttempt = {
  taskId: number
}

type BatchApprovalInput = {
  taskId: number
  approvedBy: string
  confirmation: string
}

export type BatchApprovalRequest =
  | {
      method: 'POST'
      path: string
      body: {
        approved_by: string
        confirmation: typeof BATCH_SAVE_ONLY_CONFIRMATION
      }
    }
  | {
      method: 'GET'
      path: string
    }

export type BatchTaskDestination = 'monitor' | 'results'

const TERMINAL_TASK_STATUSES = new Set([
  'completed',
  'completed_with_errors',
  'partial_success',
  'failed',
  'needs_manual_review',
  'stopped',
  'cancelled',
  'unknown',
])

export function markBatchApprovalAttempted(taskId: number): BatchApprovalAttempt {
  assertTaskId(taskId)
  return { taskId }
}

export function nextBatchApprovalRequest(
  attempt: BatchApprovalAttempt | null,
  input: BatchApprovalInput,
): BatchApprovalRequest {
  assertTaskId(input.taskId)
  if (attempt) {
    if (attempt.taskId !== input.taskId) {
      throw new Error('上一任务的批准结果仍未确认；不能批准另一任务')
    }
    return {
      method: 'GET',
      path: `/api/tasks/${input.taskId}`,
    }
  }

  const approvedBy = input.approvedBy.trim()
  if (!approvedBy) throw new Error('请填写批准人')
  if (input.confirmation !== BATCH_SAVE_ONLY_CONFIRMATION) {
    throw new Error(`请输入确认短语 ${BATCH_SAVE_ONLY_CONFIRMATION}`)
  }
  return {
    method: 'POST',
    path: `/api/tasks/${input.taskId}/approve-and-start`,
    body: {
      approved_by: approvedBy,
      confirmation: BATCH_SAVE_ONLY_CONFIRMATION,
    },
  }
}

export function batchTaskDestination(task: Task): BatchTaskDestination {
  return TERMINAL_TASK_STATUSES.has(task.status) ? 'results' : 'monitor'
}

function assertTaskId(taskId: number) {
  if (!Number.isInteger(taskId) || taskId <= 0) throw new Error('任务 ID 无效')
}
