import type { ConfigPreview, DeliveryWorkspace, RegressionGate, Task } from '../../types'
import { humanOperatorMessage } from './workbenchCopy'

const READONLY_PRECHECK_CTA = '运行真实只读检查'
const LEGACY_QA_REAL_MUTATION_TASK_NAME = ['QA guarded', 'real mutation task'].join(' ')

type L2ProbeResourceState = {
  blocked: boolean
  title: string
  detail: string
  repairSteps: string[]
  checkedPathPreview: string[]
}

type L2DiagnosticSummary = {
  target: string
  targetLabel: string
  navigation: string
  failedChecks: string[]
  nextAction: string
}

type SingleSaveRecoveryGuideProps = {
  selectedTask: Task | null
  latestSingleSaveTask: Task | null
  selectedTaskIsUnreleasedRealMode: boolean
  configBlocksStart: boolean
  l2BlocksStart: boolean
  l3BlocksStart: boolean
  canCreateRealTask: boolean
  busy: boolean
  l2ProbeResourceState: L2ProbeResourceState
  onSelectSingleSave: () => void
  onCreateSingleSave: () => void
  onRunL2Probe: () => void
  onShowConfig: () => void
  onShowReports: () => void
}

type TaskCurrentActionPanelProps = {
  selectedTask: Task | null
  workspace: DeliveryWorkspace
  configPreview: ConfigPreview | null
  l2Gate?: RegressionGate
  l3Gate?: RegressionGate
  startLabel: string
  startDisabled: boolean
  busy: boolean
  l2ProbeResourceState: L2ProbeResourceState
  onStartTask: () => void
  onRunL2Probe: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

type ReadonlyRecheckHelpCardProps = {
  l2Gate?: RegressionGate
  l3BlocksStart: boolean
  summaries: L2DiagnosticSummary[]
  busy: boolean
  demoEnabled: boolean
  selectedTask: Task | null
  selectedTaskIsDryRun: boolean
  l2ProbeResourceState: L2ProbeResourceState
  onRunL2Probe: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

export function L2ProbeResourceRepairPanel({ l2ProbeResourceState }: { l2ProbeResourceState: L2ProbeResourceState }) {
  if (!l2ProbeResourceState.blocked || (!l2ProbeResourceState.repairSteps.length && !l2ProbeResourceState.checkedPathPreview.length)) return null
  return (
    <div className="l2-probe-repair-panel" aria-label="真实只读检查资源修复步骤">
      <strong>真实只读检查资源修复步骤</strong>
      {l2ProbeResourceState.repairSteps.length > 0 && (
        <ol>
          {l2ProbeResourceState.repairSteps.map((step) => <li key={step}>{step}</li>)}
        </ol>
      )}
      {l2ProbeResourceState.checkedPathPreview.length > 0 && (
        <details className="inline-disclosure">
          <summary>查看已检查路径</summary>
          <div>
            {l2ProbeResourceState.checkedPathPreview.map((path) => <small key={path}>{path}</small>)}
          </div>
        </details>
      )}
    </div>
  )
}

export function ReadonlyRecheckHelpCard({
  l2Gate,
  l3BlocksStart,
  summaries,
  busy,
  demoEnabled,
  selectedTask,
  selectedTaskIsDryRun,
  l2ProbeResourceState,
  onRunL2Probe,
  onShowConsole,
  onShowEvidence,
  onShowReports,
}: ReadonlyRecheckHelpCardProps) {
  return (
    <div className="readonly-recheck-help" data-testid="readonly-recheck-help">
      <div className="readonly-recheck-help__main">
        <div>
          <strong>真实只读检查未通过，真实保存先暂停</strong>
          <span>{humanGateDetail(l2Gate?.detail) ?? '需要商品采集页与草稿箱页两个真实只读检查均通过。'}</span>
        </div>
        <span className="guard-chip guard-chip--danger">当前状态：{humanGateStateLabel(l2Gate?.status ?? 'not_run')}</span>
      </div>
      <div className="readonly-recheck-help__facts" aria-label="真实只读检查说明">
        <span>
          <strong>真实只读检查做什么</strong>
          <small>检查商品采集页和草稿箱页是否能正常打开。</small>
        </span>
        <span>
          <strong>不会做什么</strong>
          <small>不领取、不备注、不保存、不发布。</small>
        </span>
        <span>
          <strong>通过后做什么</strong>
          <small>再回到单商品只保存，由人工确认后启动。</small>
        </span>
      </div>
      {l3BlocksStart && <span className="readonly-recheck-help__note">真实只读检查未通过或人工确认未完成前，不启动认领、批量保存或真实保存。</span>}
      {demoEnabled && selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span className="readonly-recheck-help__note">开发自检批次不触达店小秘；真实保存仍以单商品只保存规则为准。</span>}
      {!selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span className="readonly-recheck-help__note">当前真实任务保持门禁控制，请先处理上方阻断原因。</span>}
      <div className="next-step-actions">
        <button
          className="button button--primary"
          type="button"
          onClick={onRunL2Probe}
          disabled={busy || l2ProbeResourceState.blocked}
          title={l2ProbeResourceState.title}
        >
          {READONLY_PRECHECK_CTA}
        </button>
        {l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
        <L2ProbeResourceRepairPanel l2ProbeResourceState={l2ProbeResourceState} />
      </div>
      <details className="inline-disclosure readonly-recheck-help__optional-actions">
        <summary>可选处理</summary>
        <div className="next-step-actions">
          <button className="button button--secondary" type="button" onClick={onShowConsole}>查看阻断说明</button>
          <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看检查计划</button>
          <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
        </div>
      </details>
      <details className="inline-disclosure readonly-recheck-help__diagnostics">
        <summary>查看诊断摘要</summary>
        {summaries.length > 0 ? summaries.slice(0, 2).map((item) => (
          <span key={item.target}>{item.targetLabel}：{humanDiagnosticNavigation(item.navigation)}，{item.failedChecks.slice(0, 2).map(humanFailedCheckLabel).join(' / ') || '页面检查未满足'}。下一步：{item.nextAction}</span>
        )) : <span>暂无诊断明细；先运行真实只读检查生成结果。</span>}
      </details>
    </div>
  )
}

export function TaskCurrentActionPanel({
  selectedTask,
  workspace,
  configPreview,
  l2Gate,
  l3Gate,
  startLabel,
  startDisabled,
  busy,
  l2ProbeResourceState,
  onStartTask,
  onRunL2Probe,
  onShowConfig,
  onShowConsole,
  onShowEvidence,
  onShowReports,
}: TaskCurrentActionPanelProps) {
  const storeName = selectedTask?.payload.store_name ?? workspace.stores[0]?.name ?? '未绑定店铺'
  const categoryName = selectedTask?.payload.category_name ?? '未指定类目'
  const configOk = selectedTask ? configPreview?.ok === true : false
  const l2Ready = l2Gate?.status === 'passed'
  const l3Ready = l3Gate?.status === 'passed'
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const primaryDisabled = busy || (!selectedTaskCompleted && startDisabled)
  const primaryAction = selectedTaskCompleted ? onShowReports : onStartTask
  const configCheckOk = selectedTaskCompleted || configOk
  const l2CheckOk = selectedTaskCompleted || l2Ready
  const l3CheckOk = selectedTaskCompleted || l3Ready
  const configCheckLabel = selectedTaskCompleted ? '已完成' : configOk ? '已就绪' : selectedTask ? '待补齐' : '待选择任务'
  const l2CheckLabel = selectedTaskCompleted ? '已完成' : humanGateStateLabel(l2Gate?.status ?? 'not_run')
  const l3CheckLabel = selectedTaskCompleted ? '已完成' : humanGateStateLabel(l3Gate?.status ?? 'blocked')
  const showPrecheckRecoveryActions = Boolean(selectedTask && !selectedTaskCompleted && requiresRealL2(selectedTask) && !l2Ready)
  const decision = taskStartDecision({
    selectedTask,
    configOk,
    l2Ready,
    l3Ready,
    startDisabled,
    startLabel,
    busy,
  })

  return (
    <div className="task-current-panel" aria-label="当前任务执行">
      <div className="task-current-panel__main">
        <div>
          <span className="task-current-panel__eyebrow">当前任务</span>
          <h1>{selectedTask ? displayTaskName(selectedTask) : '先选择或创建单商品只保存任务'}</h1>
          {selectedTask && (
            <span className="task-current-panel__task-id">{`当前任务 #${selectedTask.id}`}</span>
          )}
          <p>{selectedTask ? `${storeName} / ${categoryName} / ${humanTaskModeLabel(selectedTask.mode)}` : '默认只展示真实自动化主路径；创建新任务和历史批次已收起。'}</p>
        </div>
        <button
          className="button button--primary"
          type="button"
          onClick={primaryAction}
          disabled={primaryDisabled}
          aria-disabled={primaryDisabled}
          data-testid="task-start-button"
          data-start-disabled={primaryDisabled ? 'true' : 'false'}
          data-section={selectedTaskCompleted ? 'reports' : undefined}
        >
          {startLabel}
        </button>
      </div>
      <div className={`task-current-panel__decision task-current-panel__decision--${decision.tone}`} aria-label="启动判定">
        <span>
          <strong>当前能做</strong>
          <b>{decision.scope}</b>
        </span>
        <span>
          <strong>原因</strong>
          <b>{decision.reason}</b>
        </span>
        <span>
          <strong>下一步</strong>
          <b>{decision.next}</b>
        </span>
      </div>
      {showPrecheckRecoveryActions && (
        <div className="task-current-panel__precheck-actions" aria-label="真实只读检查未通过处理">
          <span>真实只读检查没有通过，不能启动真实保存。先运行真实只读检查；如果仍失败，到“真实浏览器”看日志，再查看检查计划。</span>
          <div>
            <button
              className="button button--secondary"
              type="button"
              onClick={onRunL2Probe}
              disabled={busy || l2ProbeResourceState.blocked}
              title={l2ProbeResourceState.title}
            >
              运行真实只读检查
            </button>
          </div>
          {l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
          <details className="inline-disclosure task-current-panel__optional-actions">
            <summary>可选处理：查看阻断说明 / 查看证据缺口 / 检查计划</summary>
            <div className="next-step-actions">
              <button className="button button--quiet" type="button" onClick={onShowConsole}>查看真实浏览器</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
              <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">查看检查计划</button>
            </div>
          </details>
        </div>
      )}
      <div className="task-current-panel__checks" aria-label="启动检查">
        <span className={configCheckOk ? 'is-ok' : 'is-warn'}>
          <strong>配置</strong>
          <b>{configCheckLabel}</b>
        </span>
        <span className={l2CheckOk ? 'is-ok' : 'is-warn'}>
          <strong>真实只读检查</strong>
          <b>{l2CheckLabel}</b>
        </span>
        <span className={l3CheckOk ? 'is-ok' : 'is-warn'}>
          <strong>人工确认</strong>
          <b>{l3CheckLabel}</b>
        </span>
      </div>
      <details className="inline-disclosure task-current-panel__optional-actions">
        <summary>可选处理：查看阻断说明 / 查看证据缺口 / 检查计划</summary>
        <div className="next-step-actions">
        <button className="button button--quiet" type="button" onClick={onShowConfig}>补齐配置</button>
        <button className="button button--quiet" type="button" onClick={onShowConsole}>打开真实浏览器复核</button>
        <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
        <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">查看检查计划</button>
        </div>
      </details>
    </div>
  )
}

export function SingleSaveRecoveryGuide({
  selectedTask,
  latestSingleSaveTask,
  selectedTaskIsUnreleasedRealMode,
  configBlocksStart,
  l2BlocksStart,
  l3BlocksStart,
  canCreateRealTask,
  busy,
  l2ProbeResourceState,
  onSelectSingleSave,
  onCreateSingleSave,
  onRunL2Probe,
  onShowConfig,
  onShowReports,
}: SingleSaveRecoveryGuideProps) {
  const selectSingleSaveDisabledReason = busy
    ? '正在处理当前操作，请稍候。'
    : !latestSingleSaveTask
      ? '暂无最近单商品只保存任务，请创建新的单商品只保存任务。'
      : ''
  const createSingleSaveDisabledReason = busy
    ? '正在处理当前操作，请稍候。'
    : !canCreateRealTask
      ? '请先确认有真实店铺和 1 个商品，再创建单商品只保存任务。'
      : ''
  const steps = [
    {
      title: '回到单商品只保存',
      detail: selectedTaskIsUnreleasedRealMode
        ? `${humanTaskModeLabel(selectedTask?.mode)} 当前未发布；不能复用认领/批量保存证据。`
        : latestSingleSaveTask
          ? `可继续使用最近单商品只保存任务：#${latestSingleSaveTask.id} ${displayTaskName(latestSingleSaveTask)}`
          : '还没有可用单商品只保存任务，需要用当前店铺和商品创建一个。',
      done: Boolean(selectedTask?.mode === 'single_save' && !selectedTaskIsUnreleasedRealMode),
    },
    {
      title: '补齐 DXM 编辑页配置',
      detail: configBlocksStart ? '当前任务配置检查未通过，先回编辑页配置补字段。' : '配置检查未阻断当前任务。',
      done: !configBlocksStart,
    },
    {
      title: '刷新真实只读检查',
      detail: l2BlocksStart ? '商品采集页与草稿箱页必须同一轮检查、不过期、无写请求。' : '真实只读检查当前未阻断启动判断。',
      done: !l2BlocksStart,
    },
    {
      title: '填写批准人并启动保存',
      detail: l3BlocksStart ? '真实只读检查通过后再填写批准人，只启动一个单商品只保存任务。' : '通过后仍需页面内填写批准人。',
      done: !l3BlocksStart,
    },
  ]

  return (
    <div className="single-save-recovery-guide" data-testid="single-save-recovery-guide">
      <div className="single-save-recovery-guide__head">
        <div>
          <strong>恢复到单商品只保存</strong>
          <span>当前任务不可直接启动时，按这里回到真实自动化可执行路径。</span>
        </div>
        <span className="guard-chip guard-chip--danger">不放行认领/批量保存</span>
      </div>
      <div className="single-save-recovery-guide__steps">
        {steps.map((step, index) => (
          <article key={step.title} className={step.done ? 'is-done' : 'is-current'}>
            <span>{index + 1}</span>
            <div>
              <strong>{step.title}</strong>
              <small>{step.detail}</small>
            </div>
          </article>
        ))}
      </div>
      <div className="single-save-recovery-guide__actions">
        <button
          className="button button--secondary"
          type="button"
          onClick={onSelectSingleSave}
          disabled={Boolean(selectSingleSaveDisabledReason)}
          aria-describedby={selectSingleSaveDisabledReason ? 'single-save-recovery-select-reason' : undefined}
          title={selectSingleSaveDisabledReason || undefined}
        >
          选择最近单商品只保存任务
        </button>
        {selectSingleSaveDisabledReason && (
          <small id="single-save-recovery-select-reason" className="single-save-recovery-guide__reason">
            {selectSingleSaveDisabledReason}
          </small>
        )}
        <button
          className="button button--quiet"
          type="button"
          onClick={onCreateSingleSave}
          disabled={Boolean(createSingleSaveDisabledReason)}
          aria-describedby={createSingleSaveDisabledReason ? 'single-save-recovery-create-reason' : undefined}
          title={createSingleSaveDisabledReason || undefined}
        >
          创建新的单商品只保存任务
        </button>
        {createSingleSaveDisabledReason && (
          <small id="single-save-recovery-create-reason" className="single-save-recovery-guide__reason">
            {createSingleSaveDisabledReason}
          </small>
        )}
        {configBlocksStart && (
          <button className="button button--quiet" type="button" onClick={onShowConfig}>
            去补配置
          </button>
        )}
        {(l2BlocksStart || l3BlocksStart) && (
          <button
            className="button button--quiet"
            type="button"
            onClick={onRunL2Probe}
            disabled={busy || l2ProbeResourceState.blocked}
            title={l2ProbeResourceState.title}
          >
            {READONLY_PRECHECK_CTA}
          </button>
        )}
        {(l2BlocksStart || l3BlocksStart) && l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
        {(l2BlocksStart || l3BlocksStart) && (
          <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">
            查看检查计划
          </button>
        )}
      </div>
    </div>
  )
}

export function RealModeReleasePlanPanel({ items }: { items: DeliveryWorkspace['realModeReleasePlan']['modes'] }) {
  if (!items.length) return null
  return (
    <div className="real-mode-release-panel" aria-label="未发布真实模式放行准备清单">
      <div className="real-mode-release-panel__head">
        <div>
          <strong>认领 / 批量保存放行准备</strong>
          <span>认领当前未发布；批量保存当前未发布；不能复用单商品只保存证据。</span>
        </div>
        <span className="guard-chip guard-chip--danger">仅受控单商品只保存</span>
      </div>
      <div className="real-mode-release-panel__grid">
        {items.map((item) => (
          <article key={item.mode} className="real-mode-release-item" data-mode={item.mode} data-status={item.status}>
            <div className="real-mode-release-item__title">
              <strong>{item.label || `${item.mode} 当前未发布`}</strong>
              <span>{item.allowed ? '可启动' : '未发布/阻断'}</span>
            </div>
            <ul>
              {(item.readiness_checklist ?? []).slice(0, 4).map((check) => (
                <li key={check.id}>
                  <span>{check.status === 'passed' ? 'OK' : '缺口'}</span>
                  <p>{humanReadinessCheckLabel(check.id, check.label)}</p>
                </li>
              ))}
            </ul>
            <small>{humanReleaseBlocker(item.blockers[0])}</small>
          </article>
        ))}
      </div>
      <p>批量大小上限、逐商品未发布证明、部分失败报告、回滚/人工接管全部完成前，批量保存不启动真实浏览器保存。</p>
    </div>
  )
}

function displayTaskName(task: Pick<Task, 'name' | 'mode'>) {
  if (task.mode === 'single_save' && task.name === LEGACY_QA_REAL_MUTATION_TASK_NAME) {
    return 'QA local gated single_save fixture'
  }
  if (task.mode === 'single_save' && task.name.toLowerCase().includes('l3 canary save-only')) {
    return '单商品只保存核验任务'
  }
  return task.name
}

function humanTaskModeLabel(mode?: string | null) {
  const labels: Record<string, string> = {
    probe: '真实只读检查',
    single_save: '单商品只保存',
    claim_only: '认领未开放',
    batch_save: '批量保存未开放',
    dry_run: '开发自检',
  }
  return mode ? labels[mode] ?? mode : '等待任务'
}

function isReleasedRealDxmMutationTask(task: Task) {
  return task.mode === 'single_save'
}

function isUnreleasedRealDxmMutationTask(task: Task) {
  return task.mode === 'claim_only' || task.mode === 'batch_save'
}

function isRealDxmMutationTask(task: Task) {
  return isReleasedRealDxmMutationTask(task) || isUnreleasedRealDxmMutationTask(task)
}

function requiresRealL2(task: Task) {
  return isRealDxmMutationTask(task)
}

function humanGateStateLabel(status: string) {
  const labels: Record<string, string> = {
    passed: '通过',
    failed: '失败',
    blocked: '已阻断',
    approval_required: '待人工确认',
    not_run: '未运行',
    partial: '部分完成',
    mock_passed: '离线证据',
    ready: '已就绪',
  }
  return labels[status] ?? status
}

function humanGateDetail(detail?: string | null) {
  if (!detail) return null
  const operatorMessage = humanOperatorMessage(detail)
  if (operatorMessage !== detail) return operatorMessage
  const resourceMessage = humanL2PrecheckError(detail)
  if (resourceMessage !== detail) return resourceMessage
  const safeDetail = safeGateDetailFallback(detail)
  if (safeDetail !== detail) return safeDetail
  if (
    detail.includes('时效')
    || detail.includes('过期')
    || detail.includes('最新证据年龄')
    || detail.includes('证据年龄')
    || detail.includes('age')
    || detail.includes('expired')
  ) {
    return `真实只读检查证据已过期，请点击“${READONLY_PRECHECK_CTA}”刷新后再继续。`
  }
  if (detail.includes('data_acquisition') || detail.includes('draft_box')) {
    return safeDetail
      .split('data_acquisition').join('商品采集页')
      .split('draft_box').join('草稿箱页')
      .split('L2').join('真实只读检查')
      .split('L3').join('真实保存')
      .split('passed').join('通过')
      .split('probe').join('真实只读检查')
  }
  return safeDetail
    .split('L2').join('真实只读检查')
    .split('L3').join('真实保存')
    .split('passed').join('通过')
    .split('probe').join('真实只读检查')
}

function safeGateDetailFallback(detail: string) {
  const normalized = detail.toLowerCase()
  if (
    normalized.includes('/api/')
    || normalized.includes(' get ')
    || normalized.includes(' post ')
    || normalized.includes(' x')
    || normalized.includes('blocked requests')
    || normalized.includes('traceback')
    || normalized.includes('greenlet')
    || normalized.includes('playwright')
    || normalized.includes('internal server error')
  ) {
    return '真实只读检查未通过；原始诊断已收进技术详情，请按页面提示处理后重新检查。'
  }
  return String(detail)
}

function humanL2PrecheckError(message: string) {
  if (message.includes('L2 readonly probe resources are missing')) {
    return '真实只读检查组件未安装完整：请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe runner is missing')) {
    return '真实只读检查组件未安装完整：缺少真实只读检查启动器。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe script is missing')) {
    return '真实只读检查组件未安装完整：缺少真实只读检查脚本。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  return message
}

function humanDiagnosticNavigation(value: string) {
  return value
    .split('data_acquisition').join('商品采集页')
    .split('draft_box').join('草稿箱页')
    .replace(/\/web\/productCrawl\/dataAcquisition/g, '商品采集页')
    .replace(/\/web\/smt\/smtProductList\/draft/g, '草稿箱页')
}

function humanFailedCheckLabel(value: string) {
  if (value.includes('strict_pass_checks')) return '页面检查未满足'
  if (value.includes('network')) return '网络检查未满足'
  if (value.includes('render')) return '页面渲染未满足'
  return value
    .split('strict_pass_checks').join('页面检查')
    .split('passed').join('通过')
}

function taskStartDecision({
  selectedTask,
  configOk,
  l2Ready,
  l3Ready,
  startDisabled,
  startLabel,
  busy,
}: {
  selectedTask: Task | null
  configOk: boolean
  l2Ready: boolean
  l3Ready: boolean
  startDisabled: boolean
  startLabel: string
  busy: boolean
}) {
  if (!selectedTask) {
    return {
      scope: '选择或创建任务',
      reason: '尚未选择单商品只保存任务。',
      next: '创建真实任务，或从历史批次选择一个单商品只保存任务。',
      tone: 'warn',
    }
  }
  if (selectedTask.status === 'completed') {
    return {
      scope: '查看结果报告',
      reason: '当前任务已完成，不需要再次启动。',
      next: '查看保存结果、未发布证明和检查计划。',
      tone: 'ok',
    }
  }
  if (selectedTask.status === 'running') {
    return {
      scope: '等待当前任务运行',
      reason: '任务正在运行，避免重复启动。',
      next: '到“真实浏览器”查看真实浏览器、日志和步骤。',
      tone: 'ok',
    }
  }
  if (selectedTask.status !== 'draft') {
    return {
      scope: '不可启动',
      reason: '当前任务不是草稿状态。',
      next: '选择草稿任务，或创建新的单商品只保存任务。',
      tone: 'warn',
    }
  }
  if (isUnreleasedRealDxmMutationTask(selectedTask)) {
    return {
      scope: '不可启动',
      reason: `${humanTaskModeLabel(selectedTask.mode)} 当前未放行。`,
      next: '回到单商品只保存路径；认领和批量保存需要单独验收。',
      tone: 'warn',
    }
  }
  if (isRealDxmMutationTask(selectedTask) && !configOk) {
    return {
      scope: '先补配置',
      reason: '当前任务配置检查未通过。',
      next: '去编辑页配置补齐 DXM 编辑页必填字段。',
      tone: 'warn',
    }
  }
  if (requiresRealL2(selectedTask) && !l2Ready) {
    return {
      scope: '先做真实只读检查',
      reason: '真实只读检查未通过或已过期。',
      next: `${READONLY_PRECHECK_CTA}，确认商品采集页和草稿箱页均无写入风险。`,
      tone: 'warn',
    }
  }
  if (requiresRealL2(selectedTask) && !l3Ready) {
    return {
      scope: '等待人工确认',
      reason: '真实保存前还没有完成批准人确认。',
      next: '填写批准人后，只启动单商品只保存任务。',
      tone: 'warn',
    }
  }
  if (busy || startDisabled) {
    return {
      scope: '暂不可操作',
      reason: startLabel,
      next: '等待当前操作结束后刷新任务状态。',
      tone: 'warn',
    }
  }
  return {
    scope: startLabel.includes('保存') || startLabel.includes('批准') ? '可申请单商品只保存' : '可启动当前任务',
    reason: '配置、真实只读检查和人工确认当前未阻断。',
    next: '点击主按钮后，在“真实浏览器”查看执行。',
    tone: 'ok',
  }
}

function humanReadinessCheckLabel(id: string, fallback: string) {
  return ({
    dedicated_l2_l3: '独立只读与真实保存证据链',
    claim_ownership_proof: '目标草稿领取归属证明',
    no_editor_or_save: '不打开编辑页、不触发保存请求证明',
    rollback_release: '归属释放或人工回滚路径',
    batch_size_limit: '批量大小上限',
    per_job_save_and_unpublished: '逐商品保存结果与 published=false',
    partial_failure_rollback: '部分失败报告与回滚/人工接管',
  } as Record<string, string>)[id] ?? fallback
}

function humanReleaseBlocker(value?: string) {
  if (!value) return '需要独立验收后放行'
  if (value.includes('cannot reuse single_save')) return '不能复用单商品只保存证据'
  if (value.includes('claim marker')) return '领取标记写入语义需独立审计'
  if (value.includes('rollback')) return '回滚/人工接管流程未验收'
  if (value.includes('batch failure')) return '批量失败隔离与回滚未验收'
  if (value.includes('unattended')) return '无人值守执行仍未开放'
  return value
}
