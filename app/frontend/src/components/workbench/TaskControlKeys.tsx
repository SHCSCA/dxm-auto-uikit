import {
  buildTaskControlButtons,
  humanTaskControlStatus,
  taskControlNotice,
  type TaskControlAction,
  type TaskControlSnapshot,
} from '../../taskControl'

type TaskControlKeysProps = {
  taskId: number
  status: string
  workerControl?: TaskControlSnapshot['workerControl']
  busy?: boolean
  /** When false, hide the Start key (e.g. start lives on approve-and-start card). */
  showStart?: boolean
  completedJobs?: number
  totalJobs?: number
  onStart?: (taskId: number) => void
  onPause: (taskId: number) => void
  onResume: (taskId: number) => void
  onStop: (taskId: number) => void
}

/**
 * Task resolving state - used when task is in resolving/HVD state
 */
type ResolvingState = {
  resolving: boolean
  current_operation?: string
  waiting_for?: string
}

export function TaskControlKeys({
  taskId,
  status,
  workerControl,
  busy = false,
  showStart = true,
  completedJobs,
  totalJobs,
  onStart,
  onPause,
  onResume,
  onStop,
}: TaskControlKeysProps) {
  // Check if task is in resolving state
  const isResolving = status === 'resolving' || status === 'resolving_hvd'

  const snapshot: TaskControlSnapshot = { status, workerControl }
  const buttons = buildTaskControlButtons(snapshot).filter((button) => showStart || button.action !== 'start')
  const notice = taskControlNotice(snapshot)
  const progress =
    typeof completedJobs === 'number' && typeof totalJobs === 'number' && totalJobs > 0
      ? `${completedJobs}/${totalJobs}`
      : null

  function handle(action: TaskControlAction) {
    if (busy) return
    if (action === 'start') onStart?.(taskId)
    if (action === 'pause') onPause(taskId)
    if (action === 'resume') onResume(taskId)
    if (action === 'stop') onStop(taskId)
  }

  // R5-4: HVD resolving state behavior
  if (isResolving) {
    return (
      <section className="task-control-keys task-control-keys--resolving" aria-label="任务控制四键 (Resolving态)">
        <div className="task-control-keys__meta">
          <span>
            <strong>任务状态</strong>
            <b data-status={status} className="is-resolving">Resolving</b>
          </span>
          {progress && (
            <span>
              <strong>进度</strong>
              <b>{progress}</b>
            </span>
          )}
          <span className="task-control-keys__resolving-notice">
            <strong>Resolving 态</strong>
            <small>当前操作进行中，仅允许急停</small>
          </span>
        </div>

        <div className="task-control-keys__row task-control-keys__row--resolving" role="group" aria-label="暂停 继续 停止 (Resolving态)">
          {/* Pause button: shows "暂停" but action is deferred */}
          <button
            type="button"
            className={[
              'button',
              'button--secondary',
              'task-control-key--resolving-deferred',
            ].join(' ')}
            disabled={true}
            title="resolving态暂停延后生效"
            aria-label="暂停 (resolving态延后生效)"
            data-action="pause"
            data-resolving-deferred="true"
          >
            暂停
          </button>

          {/* Resume/Continue button: disabled */}
          <button
            type="button"
            className={[
              'button',
              'button--secondary',
              'task-control-key--resolving-disabled',
            ].join(' ')}
            disabled={true}
            title="resolving态继续禁用"
            aria-label="继续 (resolving态禁用)"
            data-action="resume"
            data-resolving-disabled="true"
          >
            继续
          </button>

          {/* Stop button: only records intent */}
          <button
            type="button"
            className={[
              'button',
              'button--danger-quiet',
              'task-control-key--emergency-stop',
            ].join(' ')}
            disabled={busy}
            title="急停仅记录意图"
            aria-label="急停 (仅记录意图)"
            data-action="stop"
            data-emergency-stop="true"
            onClick={() => handle('stop')}
          >
            急停
          </button>
        </div>

        <p className="task-control-keys__notice task-control-keys__notice--resolving" role="status">
          Resolving 态：暂停/继续均已禁用，急停仅记录意图，当前商品保存完成前不生效
        </p>
      </section>
    )
  }

  return (
    <section className="task-control-keys" aria-label="任务控制四键">
      <div className="task-control-keys__meta">
        <span>
          <strong>任务状态</strong>
          <b data-status={status}>{humanTaskControlStatus(status)}</b>
        </span>
        {progress && (
          <span>
            <strong>进度</strong>
            <b>{progress}</b>
          </span>
        )}
        {workerControl?.pending && workerControl.request && (
          <span className="task-control-keys__pending">
            <strong>等待 worker</strong>
            <b>{workerControl.request === 'pause' ? '确认暂停' : '确认停止'}</b>
          </span>
        )}
        {workerControl?.ack && !workerControl.pending && (
          <span>
            <strong>worker ack</strong>
            <b>{workerControl.ack}</b>
          </span>
        )}
      </div>

      <div className="task-control-keys__row" role="group" aria-label="开始 暂停 继续 停止">
        {buttons.map((button) => (
          <button
            key={button.action}
            type="button"
            className={[
              'button',
              button.primary ? 'button--primary' : 'button--secondary',
              button.action === 'stop' ? 'button--danger-quiet' : '',
              button.pending ? 'is-pending' : '',
            ].filter(Boolean).join(' ')}
            disabled={busy || !button.enabled}
            title={button.title}
            aria-label={button.label}
            data-action={button.action}
            data-pending={button.pending ? 'true' : 'false'}
            onClick={() => handle(button.action)}
          >
            {button.label}
          </button>
        ))}
      </div>

      {notice && (
        <p className="task-control-keys__notice" role="status">
          {notice}
        </p>
      )}
    </section>
  )
}
