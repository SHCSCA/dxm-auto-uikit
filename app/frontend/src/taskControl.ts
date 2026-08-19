/**
 * E4 task four-key control: start / pause / resume / stop.
 * Buttons follow durable backend status + worker ack, never frontend-only timers.
 */

export type TaskControlAction = 'start' | 'pause' | 'resume' | 'stop'

export type TaskWorkerControlView = {
  schemaVersion?: string | null
  request?: 'pause' | 'stop' | null
  requestedAt?: string | null
  ackedAt?: string | null
  ack?: 'paused' | 'stopped' | null
  reasonCode?: string | null
  detail?: string | null
  pending?: boolean
}

export type TaskControlSnapshot = {
  status: string
  workerControl?: TaskWorkerControlView | null
}

/** Statuses that still own the runner / browser and should poll. */
export const ACTIVE_TASK_CONTROL_STATUSES = new Set([
  'running',
  'pause_requested',
  'stop_requested',
  'paused',
])

export const TERMINAL_TASK_CONTROL_STATUSES = new Set([
  'completed',
  'partial_success',
  'failed',
  'stopped',
  'cancelled',
  'needs_manual_review',
  'unknown',
  'archived',
])

export type TaskControlButtonState = {
  action: TaskControlAction
  label: string
  enabled: boolean
  primary: boolean
  pending: boolean
  title: string
}

export function humanTaskControlStatus(status: string): string {
  return (
    {
      draft: '待启动',
      running: '运行中',
      pause_requested: '暂停确认中',
      paused: '已暂停',
      stop_requested: '停止确认中',
      stopped: '已停止',
      completed: '已完成',
      partial_success: '部分成功',
      failed: '失败',
      cancelled: '已取消',
      needs_manual_review: '待人工复核',
      unknown: '结果不明',
      archived: '已归档',
    } as Record<string, string>
  )[status] ?? status
}

export function isTaskControlActive(status: string): boolean {
  return ACTIVE_TASK_CONTROL_STATUSES.has(status)
}

export function isTaskControlTerminal(status: string): boolean {
  return TERMINAL_TASK_CONTROL_STATUSES.has(status)
}

/**
 * Derive four-key enablement from durable task status.
 * Start is only for draft (approve/start path may live elsewhere).
 */
export function buildTaskControlButtons(snapshot: TaskControlSnapshot): TaskControlButtonState[] {
  const status = String(snapshot.status || '').trim()
  const pendingRequest = snapshot.workerControl?.pending === true
    ? snapshot.workerControl.request
    : status === 'pause_requested'
      ? 'pause'
      : status === 'stop_requested'
        ? 'stop'
        : null

  const startEnabled = status === 'draft'
  const pauseEnabled = status === 'running' && pendingRequest !== 'stop'
  const resumeEnabled = status === 'paused'
  const stopEnabled = status === 'running' || status === 'pause_requested' || status === 'paused'

  return [
    {
      action: 'start',
      label: '开始',
      enabled: startEnabled,
      primary: startEnabled,
      pending: false,
      title: startEnabled
        ? '完成审批与门禁后开始任务'
        : status === 'running' || status === 'pause_requested'
          ? '任务已在运行，不能重复开始'
          : status === 'paused'
            ? '任务已暂停，请使用继续'
            : '当前状态不能开始',
    },
    {
      action: 'pause',
      label: pendingRequest === 'pause' ? '暂停确认中…' : '暂停',
      enabled: pauseEnabled,
      primary: false,
      pending: pendingRequest === 'pause',
      title: pendingRequest === 'pause'
        ? '暂停已请求，等待 worker 在商品安全点确认'
        : pauseEnabled
          ? '停止派发下一商品；当前商品安全点后进入已暂停'
          : '仅运行中可暂停',
    },
    {
      action: 'resume',
      label: '继续',
      enabled: resumeEnabled,
      primary: resumeEnabled,
      pending: false,
      title: resumeEnabled
        ? '从已确认暂停点继续；已完成保存不会重做'
        : status === 'pause_requested'
          ? '须等 worker 确认暂停后才能继续'
          : '仅已暂停可继续',
    },
    {
      action: 'stop',
      label: pendingRequest === 'stop' ? '停止确认中…' : '停止',
      enabled: stopEnabled,
      primary: false,
      pending: pendingRequest === 'stop',
      title: pendingRequest === 'stop'
        ? '停止已请求，等待 worker 安全收敛后确认'
        : stopEnabled
          ? '安全收敛当前商品后停止；不再派发新商品'
          : '当前状态不能停止',
    },
  ]
}

export function taskControlNotice(snapshot: TaskControlSnapshot): string | null {
  const status = String(snapshot.status || '').trim()
  if (status === 'pause_requested') {
    return '暂停已请求：当前商品结束后 worker 才会确认已暂停，HVD 以 workerAck 为准。'
  }
  if (status === 'stop_requested') {
    return '停止已请求：当前商品安全收敛后不再派发新商品。'
  }
  if (status === 'paused') {
    return '任务已暂停（worker 已确认）。可继续或停止；继续不会重做已完成保存。'
  }
  if (status === 'stopped') {
    return '任务已停止（worker 已确认）。剩余未派发商品保持 pending。'
  }
  if (status === 'running') {
    return '任务运行中。暂停/停止均为请求态，须 worker 在安全点确认。'
  }
  return null
}
