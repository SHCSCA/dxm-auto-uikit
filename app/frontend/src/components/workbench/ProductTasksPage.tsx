import type {
  ConfigPreview,
  DeliveryWorkspace,
  RuntimeStatus,
  Task,
} from '../../types'
import { humanTaskDisplayName, humanOperatorMessage } from './workbenchCopy'

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
  onShowAcquisition: () => void
  onShowConfig: () => void
  onShowDraftEdit: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
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
  onShowAcquisition,
  onShowConfig,
  onShowDraftEdit,
  onShowConsole,
  onShowEvidence,
  onShowReports,
}: ProductTasksPageProps) {
  const currentTask = selectedTask && isOperatorTask(selectedTask) ? selectedTask : firstOperatorTask(workspace.tasks)
  const taskRows = workspace.tasks.filter(isOperatorTask).slice(0, 8)
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const currentApprover = l3ApprovedBy.trim()
  const currentTaskNeedsApproval = Boolean(
    currentTask
    && currentTask.status === 'draft'
    && (currentTask.mode === 'claim_only' || currentTask.mode === 'single_save')
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
    onShowAcquisition,
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
            <p>这里不选择商品，也不创建任务。要创建新的只保存任务，请先在“待认领入箱”完成第一段，再到“商品箱编辑保存”选择商品箱商品。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onShowReports}>
            查看结果与证据
          </button>
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
          <button className="button button--primary" type="button" onClick={primaryAction} disabled={primaryDisabled}>
            {decision.cta}
          </button>
          <button className="button button--secondary" type="button" onClick={onShowConsole} disabled={!currentTask}>
            浏览器诊断与关闭旧窗口
          </button>
          <button className="button button--secondary" type="button" onClick={onShowConfig} disabled={currentTask?.mode !== 'single_save'}>
            检查编辑页模板
          </button>
        </div>

        {currentTask?.mode === 'single_save' && l2Gate?.status !== 'passed' && (
          <div className="gate-note">
            <strong>保存前检查没有通过</strong>
            <span>{safeGateDetail(l2Gate?.detail) || '需要确认已有待认领列表和商品箱页面能正常打开，且检查过程没有写入动作。'}</span>
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onRunL2Probe} disabled={busy}>
                {READONLY_PRECHECK_CTA}
              </button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>
                查看证据缺口
              </button>
            </div>
          </div>
        )}

        {currentTaskNeedsApproval && (
          <div className="gate-note">
            <strong>{currentTask?.mode === 'claim_only' ? '人工确认认领到商品箱' : '人工确认只保存不发布'}</strong>
            <span>{currentTask?.mode === 'claim_only' ? '确认将该已有商品认领到商品箱' : '确认本次只保存不发布'}。关闭旧诊断浏览器并填写批准人后，系统才会直接批准并启动本次任务。</span>
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
            <span>先从“待认领入箱”处理真实已有商品，再到“商品箱编辑保存”创建只保存任务。</span>
          </div>
        )}
      </div>
    </section>
  )
}

function firstOperatorTask(tasks: Task[]) {
  return tasks.find(isActionableSingleSaveTask) ?? tasks.find(isActionableClaimTask) ?? tasks.find(isOperatorTask) ?? null
}

function isOperatorTask(task: Task) {
  return task.mode === 'claim_only' || task.mode === 'single_save'
}

function isActionableSingleSaveTask(task: Task) {
  return task.mode === 'single_save' && !['completed', 'cancelled', 'archived'].includes(task.status)
}

function isActionableClaimTask(task: Task) {
  return task.mode === 'claim_only' && !['completed', 'cancelled', 'archived'].includes(task.status)
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
    return decision('go_draft_edit', 'warn', '还没有保存任务', '当前没有可启动的待认领入箱或商品箱编辑保存任务。', '先到“待认领入箱”或“商品箱编辑保存”创建任务。', '去商品箱编辑保存', false)
  }
  if (task.status === 'completed') {
    return decision('show_reports', 'ok', '任务已完成', '当前任务已经结束，不能重复启动。', '查看保存结果和未发布证明。', '查看保存结果', false)
  }
  if (task.status === 'running') {
    return decision('show_console', 'ok', '任务正在运行', '系统正在控制真实浏览器，避免重复启动。', '到“浏览器现场”查看进度，必要时人工接管。', '查看浏览器现场', false)
  }
  if (task.status !== 'draft') {
    return decision('go_draft_edit', 'warn', '当前任务不可直接启动', '这条任务不是草稿状态。', '重新从商品箱商品创建编辑保存任务。', '去商品箱编辑保存', false)
  }
  if (task.mode === 'claim_only' && !taskHasSupportedSourceUrl(task)) {
    return decision('show_acquisition', 'warn', '缺少真实来源商品 URL', '关键词、类目或标题只能辅助筛选，不能唯一授权真实认领。', '回到待认领入箱，选择带来源 URL 的候选或粘贴完整商品链接。', '补齐来源商品 URL', false)
  }
  if (diagnosticBrowserActive) {
    return decision('show_console', 'warn', '旧诊断浏览器仍在运行', '真实认领、单商品只保存和整批执行不能与旧 Agent Console 共享浏览器。', '到浏览器诊断关闭旧窗口，再回来批准并启动。', '关闭旧诊断浏览器', false)
  }
  if (!dxmLoggedIn) {
    return decision('show_console', 'warn', '需要登录店小秘', '系统还没有检测到真实店小秘登录态。', '先打开真实浏览器完成登录，再回来继续。', '去浏览器现场', false)
  }
  if (task.mode === 'single_save' && configPreviewLoading) {
    return decision('none', 'warn', '正在检查模板', '系统正在读取本次编辑页模板。', '等待检查完成后再启动。', '等待配置检查', true)
  }
  if (task.mode === 'single_save' && (configPreviewError || !configOk)) {
    return decision('show_config', 'warn', '需要补齐编辑页模板', configPreviewError ? humanOperatorMessage(configPreviewError) : '当前任务的编辑页模板还没有通过检查。', '去模板中心确认本次执行会使用哪些值。', '检查编辑页模板', false)
  }
  if (!l2Passed) {
    return decision('run_l2', 'warn', '需要保存前检查', '真实浏览器保存前必须确认已有待认领列表和商品箱页面没有写入风险。', '运行保存前安全检查。', READONLY_PRECHECK_CTA, false)
  }
  if ((task.mode === 'claim_only' || task.mode === 'single_save') && !currentApproverPresent) {
    return task.mode === 'claim_only'
      ? decision('start', 'warn', '等待人工确认认领到商品箱', '确认将该已有商品认领到商品箱，并填写本次任务批准人。', '填写批准人后再启动待认领入箱。', '填写当前批准人', true)
      : decision('start', 'warn', '等待人工确认只保存不发布', '确认本次只保存不发布，并填写本次任务批准人。', '填写批准人后再启动单商品只保存。', '填写当前批准人', true)
  }
  return decision('start', 'ok', task.mode === 'claim_only' ? '可以处理待认领入箱' : '可以处理单商品只保存', '当前没有阻断项，旧诊断浏览器已关闭。', '一次批准后由任务运行器直接启动真实执行。', task.mode === 'claim_only' ? '批准并启动认领' : '批准并启动只保存', busy)
}

function decision(code: string, tone: 'ok' | 'warn', what: string, why: string, next: string, cta: string, disabled: boolean) {
  return { code, tone, what, why, next, cta, disabled }
}

function actionForDecision(code: string, currentTask: Task | null, actions: {
  onShowDraftEdit: () => void
  onShowAcquisition: () => void
  onShowConfig: () => void
  onRunL2Probe: () => void
  onStartTask: (taskId: number) => void
  onShowConsole: () => void
  onShowReports: () => void
}) {
  return ({
    go_draft_edit: actions.onShowDraftEdit,
    show_acquisition: actions.onShowAcquisition,
    show_config: actions.onShowConfig,
    run_l2: actions.onRunL2Probe,
    show_console: actions.onShowConsole,
    show_reports: actions.onShowReports,
    start: () => currentTask ? actions.onStartTask(currentTask.id) : undefined,
  } as Record<string, (() => void) | undefined>)[code]
}

function taskHasSupportedSourceUrl(task: Task) {
  const value = typeof task.payload?.source_url === 'string'
    ? task.payload.source_url
    : typeof task.payload?.claimed_product_source_url === 'string'
      ? task.payload.claimed_product_source_url
      : ''
  try {
    const url = new URL(value)
    const hostname = url.hostname.toLowerCase().replace(/\.$/, '')
    return ['http:', 'https:'].includes(url.protocol)
      && Boolean(hostname)
      && !url.username
      && !url.password
      && hostname !== 'localhost'
      && hostname !== '127.0.0.1'
      && hostname !== '::1'
      && !hostname.endsWith('.local')
      && hostname !== 'dianxiaomi.com'
      && !hostname.endsWith('.dianxiaomi.com')
  } catch {
    return false
  }
}

function configStatusLabel(task: Task | null, configPreview: ConfigPreview | null, loading: boolean, error: string | null) {
  if (!task) return '等待任务'
  if (task.mode !== 'single_save') return '第一段无需模板'
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
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    archived: '已归档',
  } as Record<string, string>)[status] ?? status
}

function taskModeLabel(mode: string) {
  return ({
    claim_only: '待认领入箱',
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
    .split('data_acquisition').join('已有待认领列表')
    .split('draft_box').join('商品箱页')
    .split('L2').join('保存前检查')
    .split('L3').join('真实保存')
}
