import type {
  ConfigPreview,
  DeliveryWorkspace,
  RuntimeStatus,
  Task,
  TaskWorkerControl,
} from '../../types'
import { isTaskControlActive } from '../../taskControl'
import { humanTaskDisplayName, humanOperatorMessage } from './workbenchCopy'
import { TaskControlKeys } from './TaskControlKeys'

type ProductTasksPageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  busy: boolean
  l3ApprovedBy: string
  onL3ApprovedByChange: (value: string) => void
  onSelectTask: (taskId: number) => void
  onRunL2Probe: () => void
  onStartTask: (taskId: number) => void
  onPauseTask: (taskId: number) => void
  onResumeTask: (taskId: number) => void
  onStopTask: (taskId: number) => void
  onShowDxmAccess: () => void
  onShowConfig: () => void
  onShowDraftEdit: () => void
  onShowConsole: () => void
  onShowReports: () => void
}

const READONLY_PRECHECK_CTA = '运行保存前安全检查'

export function ProductTasksPage({
  workspace,
  selectedTask,
  configPreview,
  configPreviewError,
  configPreviewLoading,
  runtimeStatus,
  runtimeStatusError,
  busy,
  l3ApprovedBy,
  onL3ApprovedByChange,
  onSelectTask,
  onRunL2Probe,
  onStartTask,
  onPauseTask,
  onResumeTask,
  onStopTask,
  onShowDxmAccess,
  onShowConfig,
  onShowDraftEdit,
  onShowConsole,
  onShowReports,
}: ProductTasksPageProps) {
  const currentTask = selectedTask && isOperatorTask(selectedTask) ? selectedTask : firstOperatorTask(workspace.tasks)
  const taskRows = workspace.tasks.filter(isOperatorTask).slice(0, 8)
  const showControlKeys = Boolean(currentTask && isTaskControlActive(currentTask.status))
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const currentApprover = l3ApprovedBy.trim()
  const currentTaskNeedsApproval = Boolean(
    currentTask
    && currentTask.status === 'draft'
    && currentTask.mode === 'single_save'
    && l2Gate?.status === 'passed'
  )
  const currentTaskApprovalMissing = currentTaskNeedsApproval && !currentApprover
  const configForTask = currentTask && configPreview?.taskId === currentTask.id ? configPreview : null
  const decision = buildTaskDecision({
    task: currentTask,
    configOk: currentTask?.mode !== 'single_save' || configForTask?.ok === true,
    configPreviewError,
    configPreviewLoading,
    l2Passed: l2Gate?.status === 'passed',
    currentApproverPresent: Boolean(currentApprover),
    dxmLoggedIn: isDxmLoggedIn(runtimeStatus, runtimeStatusError),
    diagnosticBrowserActive: runtimeStatus?.agentConsole?.active === true,
    busy,
  })
  const primaryAction = actionForDecision(decision.code, currentTask, {
    onShowDraftEdit,
    onShowDxmAccess,
    onShowConfig,
    onRunL2Probe,
    onStartTask,
    onShowConsole,
    onShowReports,
  })
  const primaryDisabled = busy || !primaryAction || decision.disabled || currentTaskApprovalMissing

  return (
    <section className="module-layout" aria-label="当前保存任务">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">当前保存任务</span>
            <h2>{currentTask ? humanTaskDisplayName(currentTask) : '还没有可启动的保存任务'}</h2>
            <p>这里保留单商品只保存的历史与执行入口。新任务直接从商品箱读取现有商品并创建，只保存、不发布。</p>
          </div>
        </div>

        <div className={`task-current-panel__decision task-current-panel__decision--${decision.tone}`} aria-label="当前任务判断">
          <span>
            <strong>发生了什么</strong>
            <b>{decision.what}</b>
          </span>
          <span>
            <strong>为什么不能继续</strong>
            <b>{decision.why}</b>
          </span>
          <span>
            <strong>下一步</strong>
            <b>{decision.next}</b>
          </span>
        </div>

        <div className="task-current-panel__checks" aria-label="任务启动条件">
          <span className={currentTask ? 'is-ok' : 'is-warn'}>
            <strong>任务</strong>
            <b>{currentTask ? taskStatusLabel(currentTask.status) : '未创建'}</b>
          </span>
          <span className={currentTask?.mode !== 'single_save' || configForTask?.ok === true ? 'is-ok' : 'is-warn'}>
            <strong>编辑页模板</strong>
            <b>{configStatusLabel(currentTask, configForTask, configPreviewLoading, configPreviewError)}</b>
          </span>
          <span className={l2Gate?.status === 'passed' ? 'is-ok' : 'is-warn'}>
            <strong>保存前检查</strong>
            <b>{gateStatusLabel(l2Gate?.status)}</b>
          </span>
          <span className={currentTaskApprovalMissing ? 'is-warn' : 'is-ok'}>
            <strong>本次任务批准人</strong>
            <b>{currentTaskNeedsApproval ? currentApprover || '待填写' : '保存前检查通过后填写'}</b>
          </span>
          <span className={l3Gate?.status === 'passed' ? 'is-ok' : 'is-warn'}>
            <strong>历史执行证据</strong>
            <b>{gateStatusLabel(l3Gate?.status)}</b>
          </span>
        </div>

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={primaryAction} disabled={primaryDisabled || showControlKeys}>
            {decision.cta}
          </button>
        </div>

        {currentTask && showControlKeys && (
          <TaskControlKeys
            taskId={currentTask.id}
            status={currentTask.status}
            workerControl={resolveTaskWorkerControl(currentTask)}
            busy={busy}
            showStart={false}
            completedJobs={currentTask.completed_jobs}
            totalJobs={currentTask.total_jobs}
            onPause={onPauseTask}
            onResume={onResumeTask}
            onStop={onStopTask}
          />
        )}

        {currentTask?.mode === 'single_save' && l2Gate?.status !== 'passed' && (
          <div className="gate-note">
            <strong>保存前检查没有通过</strong>
            <span>{safeGateDetail(l2Gate?.detail) || '需要确认商品箱页面能正常打开，且检查过程没有写入动作。'}</span>
          </div>
        )}

        {currentTaskNeedsApproval && (
          <div className="gate-note">
            <strong>人工确认只保存不发布</strong>
            <span>确认本次只保存不发布。填写批准人后系统会直接批准并启动；如旧诊断浏览器仍在运行，必须先关闭。</span>
            <label className="approval-inline">
              <span>批准人</span>
              <input value={l3ApprovedBy} onChange={(event) => onL3ApprovedByChange(event.target.value)} placeholder="填写当前操作者" disabled={busy} required />
            </label>
          </div>
        )}
      </div>

      <div className="module-card span-1">
        <div className="module-head">
          <h2>任务记录</h2>
          <span>{taskRows.length ? `${taskRows.length} 个可查看` : '暂无'}</span>
        </div>
        {taskRows.length ? (
          <div className="task-list" aria-label="任务记录">
            {taskRows.map((task) => (
              <button
                key={task.id}
                className={`task-list-item ${currentTask?.id === task.id ? 'is-selected' : ''}`}
                type="button"
                onClick={() => onSelectTask(task.id)}
                disabled={busy}
              >
                <strong>{humanTaskDisplayName(task)}</strong>
                <span>{taskModeLabel(task.mode)} / {taskStatusLabel(task.status)}</span>
                <small>任务 #{task.id}，{task.total_jobs || 1} 个商品</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="gate-note">
            <strong>还没有任务</strong>
            <span>从商品箱读取现有商品并创建只保存任务。</span>
          </div>
        )}
      </div>
    </section>
  )
}

function firstOperatorTask(tasks: Task[]) {
  return tasks.find(isActionableSingleSaveTask) ?? tasks.find(isOperatorTask) ?? null
}

function isOperatorTask(task: Task) {
  return task.mode === 'single_save'
}

function isActionableSingleSaveTask(task: Task) {
  return task.mode === 'single_save' && !['completed', 'partial_success', 'cancelled', 'stopped', 'archived'].includes(task.status)
}

function isDxmLoggedIn(runtimeStatus: RuntimeStatus | null, runtimeStatusError: string | null) {
  if (runtimeStatusError) return false
  return ['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'].includes(runtimeStatus?.dxmLogin?.status ?? '')
}

function buildTaskDecision({
  task,
  configOk,
  configPreviewError,
  configPreviewLoading,
  l2Passed,
  currentApproverPresent,
  dxmLoggedIn,
  diagnosticBrowserActive,
  busy,
}: {
  task: Task | null
  configOk: boolean
  configPreviewError: string | null
  configPreviewLoading: boolean
  l2Passed: boolean
  currentApproverPresent: boolean
  dxmLoggedIn: boolean
  diagnosticBrowserActive: boolean
  busy: boolean
}) {
  if (!task) {
    return decision('go_draft_edit', 'warn', '还没有保存任务', '当前没有可启动的单商品只保存任务。', '直接读取商品箱现有商品并创建只保存批次。', '读取商品箱范围', false)
  }
  if (task.status === 'completed' || task.status === 'partial_success') {
    return decision('show_reports', 'ok', '任务已完成', '当前任务已经结束，不能重复启动。', '查看保存结果和未发布证明。', '查看保存结果', false)
  }
  if (task.status === 'running') {
    return decision('none', 'ok', '任务正在运行', '系统正在控制真实浏览器，避免重复启动。可用下方四键请求暂停或停止。', '保持当前页等待状态更新；暂停/停止须 worker 在商品安全点确认。', '任务执行中', true)
  }
  if (task.status === 'pause_requested') {
    return decision('none', 'warn', '暂停确认中', '操作员已请求暂停，等待 worker 在当前商品结束后确认。', '确认前不能继续；如需终止可请求停止。', '等待 worker 确认暂停', true)
  }
  if (task.status === 'paused') {
    return decision('none', 'ok', '任务已暂停', 'worker 已确认暂停；已完成保存不会重做。', '使用下方四键继续或停止。', '已暂停', true)
  }
  if (task.status === 'stop_requested') {
    return decision('none', 'warn', '停止确认中', '操作员已请求停止，等待 worker 安全收敛后确认。', '确认前不再派发新商品。', '等待 worker 确认停止', true)
  }
  if (task.status === 'stopped' || task.status === 'cancelled') {
    return decision('show_reports', 'warn', '任务已停止', 'worker 已确认停止或任务已取消，不能重复启动。', '查看已完成结果与剩余未派发商品。', '查看保存结果', false)
  }
  if (task.status !== 'draft') {
    return decision('go_draft_edit', 'warn', '当前任务不可直接启动', '这条任务不是草稿状态。', '重新从商品箱商品创建编辑保存任务。', '去商品箱编辑保存', false)
  }
  if (diagnosticBrowserActive) {
    return decision('show_console', 'warn', '旧诊断浏览器仍在运行', '单商品只保存和整批执行不能与旧 Agent Console 共享浏览器。', '到浏览器诊断关闭旧窗口，再回来批准并启动。', '关闭旧诊断浏览器', false)
  }
  if (!dxmLoggedIn) {
    return decision('show_login', 'warn', '需要登录店小秘', '系统还没有检测到真实店小秘登录态。', '先到账号与浏览器完成登录，再回来继续。', '登录店小秘', false)
  }
  if (task.mode === 'single_save' && configPreviewLoading) {
    return decision('none', 'warn', '正在检查模板', '系统正在读取本次编辑页模板。', '等待检查完成后再启动。', '等待配置检查', true)
  }
  if (task.mode === 'single_save' && (configPreviewError || !configOk)) {
    return decision('show_config', 'warn', '需要补齐编辑页模板', configPreviewError ? humanOperatorMessage(configPreviewError) : '当前任务的编辑页模板还没有通过检查。', '去模板中心确认本次执行会使用哪些值。', '检查编辑页模板', false)
  }
  if (!l2Passed) {
    return decision('run_l2', 'warn', '需要保存前检查', '真实浏览器保存前必须确认商品箱页面没有写入风险。', '运行保存前安全检查。', READONLY_PRECHECK_CTA, false)
  }
  if (task.mode === 'single_save' && !currentApproverPresent) {
    return decision('start', 'warn', '等待人工确认只保存不发布', '确认本次只保存不发布，并填写本次任务批准人。', '填写批准人后再启动单商品只保存。', '填写当前批准人', true)
  }
  return decision('start', 'ok', '可以处理单商品只保存', '当前没有阻断项，旧诊断浏览器已关闭。', '一次批准后由任务运行器直接启动真实执行。', '批准并启动只保存', busy)
}

function decision(code: string, tone: 'ok' | 'warn', what: string, why: string, next: string, cta: string, disabled: boolean) {
  return { code, tone, what, why, next, cta, disabled }
}

function actionForDecision(code: string, currentTask: Task | null, actions: {
  onShowDraftEdit: () => void
  onShowDxmAccess: () => void
  onShowConfig: () => void
  onRunL2Probe: () => void
  onStartTask: (taskId: number) => void
  onShowConsole: () => void
  onShowReports: () => void
}) {
  return ({
    go_draft_edit: actions.onShowDraftEdit,
    show_login: actions.onShowDxmAccess,
    show_config: actions.onShowConfig,
    run_l2: actions.onRunL2Probe,
    show_console: actions.onShowConsole,
    show_reports: actions.onShowReports,
    start: () => currentTask ? actions.onStartTask(currentTask.id) : undefined,
  } as Record<string, (() => void) | undefined>)[code]
}

function configStatusLabel(task: Task | null, configPreview: ConfigPreview | null, loading: boolean, error: string | null) {
  if (!task) return '等待任务'
  if (task.mode !== 'single_save') return '当前任务无需编辑模板'
  if (loading) return '检查中'
  if (error) return '检查失败'
  return configPreview?.ok ? '已通过' : '待补齐'
}

function gateStatusLabel(status?: string | null) {
  return ({
    passed: '通过',
    failed: '失败',
    blocked: '已阻断',
    approval_required: '待人工确认',
    not_run: '未运行',
    partial: '部分完成',
    mock_passed: '离线证据',
    ready: '已就绪',
  } as Record<string, string>)[status ?? 'not_run'] ?? '未运行'
}

function taskStatusLabel(status: string) {
  return ({
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
  } as Record<string, string>)[status] ?? status
}

function resolveTaskWorkerControl(task: Task): TaskWorkerControl | null {
  if (task.workerControl) return task.workerControl
  const nested = task.payload?.worker_control
  if (nested && typeof nested === 'object') return nested as TaskWorkerControl
  return null
}

function taskModeLabel(mode: string) {
  return ({
    single_save: '商品箱编辑保存',
  } as Record<string, string>)[mode] ?? mode
}

function safeGateDetail(detail?: string | null) {
  if (!detail) return ''
  const operatorMessage = humanOperatorMessage(detail)
  if (operatorMessage !== detail) return operatorMessage
  const normalized = detail.toLowerCase()
  if (
    normalized.includes('/api/')
    || normalized.includes('traceback')
    || normalized.includes('greenlet')
    || normalized.includes('playwright')
    || normalized.includes('internal server error')
    || normalized.includes('run-id')
    || normalized.includes('probe')
  ) {
    return '保存前检查未通过；原始技术信息已收进维护日志，请按页面提示重新检查。'
  }
  return detail
    .split('draft_box').join('商品箱页')
    .split('L2').join('保存前检查')
    .split('L3').join('真实保存')
}
