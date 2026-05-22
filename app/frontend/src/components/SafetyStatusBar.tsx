import type { DeliveryWorkspace, Task } from '../types'
import { humanTaskStatus } from '../workspace'

type SafetyStatusBarProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  busy: boolean
  onRefresh: () => void
}

export function SafetyStatusBar({ workspace, selectedTask, busy, onRefresh }: SafetyStatusBarProps) {
  const activeTaskLabel = selectedTask ? `#${selectedTask.id} ${humanTaskStatus(selectedTask.status)}` : '未选择任务'

  return (
    <section className="safety-bar" aria-label="只保存不发布安全条">
      <div className="safety-bar__main">
        <span className="safety-dot" aria-hidden="true" />
        <div>
          <strong>{workspace.safety.guarantee}</strong>
          <span>当前任务 {activeTaskLabel}，最近校验 {workspace.safety.lastCheckedAt}</span>
        </div>
      </div>
      <div className="safety-bar__meta" aria-label="禁止入口检查">
        {workspace.safety.forbiddenActions.map((action) => (
          <span key={action} className="guard-chip">{action}：无入口</span>
        ))}
        <button className="button button--quiet" type="button" onClick={onRefresh} disabled={busy}>
          刷新工作台
        </button>
      </div>
    </section>
  )
}
