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
