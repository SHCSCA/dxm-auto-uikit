import type { ConfigPreview, DeliveryWorkspace, DesktopRuntimeInfo, RuntimeStatus, Task } from '../types'
import { humanTaskStatus } from '../workspace'

const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])
const dxmReadySessionStatuses = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])

type SafetyStatusBarProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  configPreviewError?: string | null
  configPreviewLoading: boolean
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError?: string | null
  desktopRuntime?: DesktopRuntimeInfo | null
  busy: boolean
  onRefresh: () => void
  onShowDxmAccess: () => void
  onShowConfig: () => void
  onShowTasks: () => void
  onShowConsole: () => void
  onShowReports: () => void
}

export function SafetyStatusBar({ workspace, selectedTask, configPreview, configPreviewError, configPreviewLoading, runtimeStatus, runtimeStatusError, desktopRuntime, busy, onRefresh, onShowDxmAccess, onShowConfig, onShowTasks, onShowConsole, onShowReports }: SafetyStatusBarProps) {
  const activeTaskLabel = selectedTask ? `#${selectedTask.id}` : '未选择任务'
  const activeTaskStatusLabel = selectedTask ? humanTaskStatus(selectedTask.status) : ''
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const selectedRealDxmMutationTask = Boolean(selectedTask && ['claim_only', 'single_save', 'batch_save'].includes(selectedTask.mode))
  const configBlocksRealSave = Boolean(
    selectedTask
    && selectedRealDxmMutationTask
    && !selectedTaskCompleted
    && (configPreviewError || configPreviewLoading || !configPreview || configPreview.taskId !== selectedTask.id || !configPreview.ok)
  )
  const publishGuardReasons = workspace.publishGuardState?.reasons ?? []
  const l2BlocksRealSave = l2Gate?.status !== 'passed'
  const l3BlocksRealSave = l3Gate?.status === 'blocked'
  const l3NeedsApproval = l3Gate?.status !== 'passed'
  const taskBlocksRealSave = !selectedTask && workspace.tasks.length > 0
  const realWriteExpectedBlocked = l2BlocksRealSave || l3NeedsApproval
  const blockerGaps = workspace.acceptanceGaps.filter((gap) => gap.severity === 'blocker')
  const noTaskSelected = !selectedTask && workspace.tasks.length === 0
  const preTaskEvidenceGapIds = new Set(['gap-evidence-a', 'gap-report', 'empty-workspace'])
  const visibleBlockerGaps = blockerGaps.filter((gap) => {
    if (realWriteExpectedBlocked && l3PostEvidenceGapIds.has(gap.id)) return false
    if (noTaskSelected && preTaskEvidenceGapIds.has(gap.id)) return false
    return true
  })
  const l3PostEvidenceGapCount = blockerGaps.filter((gap) => realWriteExpectedBlocked && l3PostEvidenceGapIds.has(gap.id)).length
  const hasBlocker = visibleBlockerGaps.length > 0
  const runtimeStatusUnavailable = Boolean(runtimeStatusError)
  const dxmLoggedIn = runtimeStatus ? dxmReadySessionStatuses.has(runtimeStatus.dxmLogin.status) : false
  const realBrowser = runtimeStatus?.realBrowser ?? (runtimeStatus
    ? {
      status: runtimeStatus.agentConsole.status,
      active: runtimeStatus.agentConsole.active,
      browserVisible: runtimeStatus.agentConsole.browserVisible,
      browserLaunching: runtimeStatus.agentConsole.browserLaunching,
      source: 'agent_console',
      currentUrl: runtimeStatus.agentConsole.currentUrl,
      lastError: runtimeStatus.agentConsole.lastError,
    }
    : null)
  const agentActive = realBrowser?.active === true
  const tone = runtimeStatusUnavailable || l3BlocksRealSave || hasBlocker || publishGuardReasons.length > 0
    ? 'danger'
    : l2BlocksRealSave || l3NeedsApproval || workspace.source === 'mock' || workspace.evidenceGrade?.grade === 'C'
      ? 'warn'
      : 'ok'
  const nextHeadline = taskBlocksRealSave
    ? '继续下一步：选择单商品只保存任务'
    : configBlocksRealSave
      ? '继续下一步：补齐本次任务配置'
      : !dxmLoggedIn
      ? '继续下一步：打开真实店小秘登录'
      : l2BlocksRealSave
      ? '继续下一步：运行保存前安全检查'
      : l3NeedsApproval
        ? '继续下一步：人工确认单商品只保存'
        : '当前可执行：单商品只保存自动化'
  const headline = selectedTaskCompleted
    ? '当前任务已完成，可查看保存结果'
    : runtimeStatusUnavailable
      ? '工作台服务连接异常'
      : nextHeadline
  const gateStatusLine = `保存前安全检查 ${humanGateStatus(l2Gate?.status ?? workspace.safety.l2Status ?? 'not_run')}，人工确认 ${humanGateStatus(l3Gate?.status ?? 'not_run')}`
  const statusLine = `当前任务 ${activeTaskLabel}，${tone === 'danger' ? `保存前置条件未完成：${gateStatusLine}` : gateStatusLine}`
  const gateDetails = [
    l2Gate ? `保存前安全检查：${l2Gate.detail}` : '保存前安全检查：缺少页面检查状态',
    l3Gate ? `人工确认保存：${l3Gate.detail}` : '人工确认保存：缺少真实保存门禁状态',
  ]
  const blockerDetails = [
    ...visibleBlockerGaps.map((gap) => `阻断项：${gap.title} - ${gap.detail}`),
    ...(l3PostEvidenceGapCount > 0 ? [`保存后证据：${l3PostEvidenceGapCount} 项预期阻断 - 真实写入放行后再补齐`] : []),
    ...publishGuardReasons.map((reason) => `发布隔离：${reason}`),
  ]
  const detail = tone === 'danger'
    ? [...gateDetails, ...blockerDetails].join('；') || '真实保存启动条件未满足。'
    : tone === 'warn'
      ? `${statusLine}，最近校验 ${workspace.safety.lastCheckedAt}`
      : `当前任务 ${activeTaskLabel}，最近校验 ${workspace.safety.lastCheckedAt}`
  const conciseDetail = tone === 'danger'
    ? runtimeStatusUnavailable
      ? '后端未连接不是账号、配置或店小秘页面问题；请查看实时日志、刷新状态或重启免安装版。'
      : '工作台只会执行受控“只保存”，发布和批量无人值守仍保持关闭。'
    : selectedTaskCompleted
      ? `任务 ${activeTaskLabel} ${activeTaskStatusLabel}，继续查看保存结果和未发布证明。`
      : '按操作引导继续：选择任务、补配置、真实登录、保存前安全检查、人工确认后才启动保存。'
  const runtimeOwner = runtimeStatus?.runtimeControl?.owner ?? 'direct'
  const runtimeOwnerChip = runtimeOwnerLabel(runtimeOwner, Boolean(runtimeStatus?.runtimeControl?.managedByDesktop))
  const backendPortMismatch = typeof desktopRuntime?.backendPort === 'number'
    && typeof runtimeStatus?.backend.port === 'number'
    && desktopRuntime.backendPort !== runtimeStatus.backend.port
  const backendInstanceMismatch = Boolean(
    desktopRuntime?.backendInstanceId
    && runtimeStatus
    && runtimeStatus.backend.instanceId !== desktopRuntime.backendInstanceId,
  )
  const runtimeChips = runtimeStatus
    ? [
      { label: `启动方式：${runtimeOwnerChip}`, tone: runtimeOwner === 'direct' ? 'warn' : 'ok' },
      { label: `本机服务：${runtimeStatus.backend.status === 'ok' ? '正常' : '异常'}`, tone: runtimeStatus.backend.status === 'ok' ? 'ok' : 'danger' },
      { label: `主窗口：${frontendRuntimeLabel(runtimeStatus.frontend)}`, tone: runtimeStatus.frontend.status === 'ok' ? 'ok' : 'danger' },
      { label: `真实浏览器：${humanRealBrowserStatus(realBrowser)}`, tone: realBrowser?.active ? 'ok' : realBrowser?.browserLaunching ? 'warn' : 'warn' },
      { label: `店小秘登录：${humanDxmLoginStatus(runtimeStatus.dxmLogin.status)}`, tone: dxmLoginTone(runtimeStatus.dxmLogin.status) },
    ]
    : []
  const detailChips = [
    ...(runtimeStatusUnavailable ? [{ label: '状态接口异常', tone: 'danger' }] : []),
    ...runtimeChips,
    ...(desktopRuntime ? [{ label: '免安装版：已接入本机服务', tone: desktopRuntime.lastError ? 'danger' : 'ok' }] : []),
    ...(backendPortMismatch ? [{ label: '桌面服务与当前接口不一致', tone: 'danger' }] : []),
    ...(backendInstanceMismatch ? [{ label: '桌面服务实例不一致', tone: 'danger' }] : []),
    { label: `保存前安全检查：${humanGateStatus(l2Gate?.status ?? 'not_run')}`, tone: l2BlocksRealSave ? 'danger' : 'ok' },
    { label: `人工确认：${l3NeedsApproval ? `不可启动 / ${humanGateStatus(l3Gate?.status ?? 'not_run')}` : humanGateStatus(l3Gate?.status ?? 'not_run')}`, tone: l3BlocksRealSave ? 'danger' : l3NeedsApproval ? 'warn' : 'ok' },
    ...visibleBlockerGaps.slice(0, 2).map((gap) => ({ label: `阻断项：${gap.title}`, tone: 'danger' })),
    ...(l3PostEvidenceGapCount > 0 ? [{ label: `保存后证据：${l3PostEvidenceGapCount} 项预期阻断`, tone: 'warn' }] : []),
    ...publishGuardReasons.slice(0, 2).map((reason) => ({ label: `发布隔离：${reason}`, tone: 'danger' })),
    ...workspace.safety.forbiddenActions.slice(0, 2).map((action) => ({ label: `${action}：无入口`, tone: 'muted' })),
  ]
  const boundaryChips = [
    { label: '批量/无人值守：未放行', tone: 'warn' },
    { label: '发布：无入口', tone: 'muted' },
  ]
  const primaryStatus = selectedTaskCompleted
    ? '当前任务已完成'
    : runtimeStatusUnavailable
    ? '状态接口异常'
    : taskBlocksRealSave
    ? '等待选择任务'
    : configBlocksRealSave
    ? '等待补齐配置'
    : !dxmLoggedIn
    ? '等待真实登录'
    : l2BlocksRealSave
    ? '先完成安全检查'
    : l3NeedsApproval
      ? '等待人工确认'
      : '可启动只保存'
  const visibleBlockerReason = selectedTaskCompleted
    ? '任务已完成，下一步复核保存结果。'
    : runtimeStatusUnavailable
    ? '服务连接异常，请刷新状态或查看日志。'
    : taskBlocksRealSave
    ? '已有任务但未选择，请先选择任务。'
    : configBlocksRealSave
    ? '本次任务配置未补齐。'
    : !dxmLoggedIn
    ? '店小秘未登录或登录状态未确认。'
    : l2BlocksRealSave
    ? '保存前安全检查未通过。'
    : l3NeedsApproval
      ? '保存前需要人工确认。'
      : agentActive
        ? '真实浏览器正在执行。'
        : '没有阻断。'
  const primaryActionLabel = selectedTaskCompleted
    ? '查看保存结果'
    : runtimeStatusUnavailable
      ? '查看日志'
    : '下一步'
  const handlePrimaryAction = selectedTaskCompleted
    ? onShowReports
    : runtimeStatusUnavailable
      ? onShowConsole
    : taskBlocksRealSave
      ? onShowTasks
    : configBlocksRealSave
      ? onShowConfig
    : !dxmLoggedIn
      ? onShowDxmAccess
      : l2BlocksRealSave
        ? onShowConsole
        : l3NeedsApproval
          ? onShowTasks
          : onShowConsole

  return (
    <section className={`safety-bar safety-bar--${tone}`} aria-label="工作台当前状态">
      <div className="safety-bar__main">
        <span className="safety-dot" aria-hidden="true" />
        <div>
          <strong>{headline}</strong>
        </div>
      </div>
      <div className="safety-bar__meta" aria-label="当前操作">
        <span className={`guard-chip guard-chip--${tone === 'danger' ? 'danger' : tone === 'warn' ? 'warn' : 'ok'}`}>{primaryStatus}</span>
        <span className="guard-chip guard-chip--ok">只保存，不发布</span>
        <span className="safety-bar__blocker" title={visibleBlockerReason}>{visibleBlockerReason}</span>
        <button className="button button--secondary safety-bar__primary-action" type="button" onClick={handlePrimaryAction} disabled={busy}>
          {primaryActionLabel}
        </button>
        <details className="safety-bar__meta-details inline-disclosure">
          <summary>维护详情</summary>
          <p className="safety-bar__compact-detail">{conciseDetail}</p>
          <div>
            <strong className="safety-bar__details-title">维护状态说明</strong>
            {boundaryChips.map((chip) => (
              <span key={chip.label} className={`guard-chip guard-chip--${chip.tone}`}>{chip.label}</span>
            ))}
            {detailChips.map((chip) => (
              <span key={chip.label} className={`guard-chip guard-chip--${chip.tone}`}>{chip.label}</span>
            ))}
          </div>
          <span>{detail}</span>
        </details>
        <button className="button button--quiet" type="button" onClick={onRefresh} disabled={busy}>
          {runtimeStatusUnavailable ? '刷新状态' : '刷新'}
        </button>
      </div>
    </section>
  )
}

function dxmLoginTone(status: string) {
  if (dxmReadySessionStatuses.has(status)) return 'ok'
  return status.includes('error') ? 'danger' : 'warn'
}

function humanDxmLoginStatus(status: string) {
  if (dxmReadySessionStatuses.has(status)) return '已登录'
  if (status === 'waiting_captcha') return '等待验证码'
  if (status === 'login_failed') return '登录未通过'
  if (status.includes('error')) return '异常'
  return '待确认'
}

function humanRealBrowserStatus(browser: RuntimeStatus['realBrowser'] | null | undefined) {
  if (!browser) return '待确认'
  if (browser.browserLaunching) return '启动中'
  if (browser.active && browser.browserVisible) return browser.source === 'dxm_flow' ? '业务窗口已打开' : '运行中'
  if (browser.active) return '会话已建立'
  return '待命'
}

function runtimeOwnerLabel(owner: string, managedByDesktop: boolean) {
  if (owner === 'desktop' || managedByDesktop) return '免安装版已接管'
  if (owner === 'start_mvp') return 'start-mvp 已接管'
  return '旧进程/直接启动'
}

function frontendRuntimeLabel(frontend: RuntimeStatus['frontend']) {
  if (frontend.url?.startsWith('file://') || frontend.detail?.includes('桌面内置页面')) {
    return '桌面内置页面'
  }
  return frontend.status === 'ok' ? '运行中' : '异常'
}

function humanGateStatus(status: string) {
  return ({
    ready: '已就绪',
    not_run: '未运行',
    mock_passed: '离线证据',
    partial: '部分完成',
    passed: '通过',
    failed: '失败',
    blocked: '已阻断',
    approval_required: '需批准',
  } as Record<string, string>)[status] ?? status
}
