import type { DeliveryWorkspace, DesktopRuntimeInfo, RuntimeStatus, Task } from '../types'
import { humanTaskStatus } from '../workspace'

const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])
const dxmReadySessionStatuses = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])

type SafetyStatusBarProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError?: string | null
  desktopRuntime?: DesktopRuntimeInfo | null
  busy: boolean
  onRefresh: () => void
  onShowTasks: () => void
  onShowConsole: () => void
}

export function SafetyStatusBar({ workspace, selectedTask, runtimeStatus, runtimeStatusError, desktopRuntime, busy, onRefresh, onShowTasks, onShowConsole }: SafetyStatusBarProps) {
  const activeTaskLabel = selectedTask ? `#${selectedTask.id}` : '未选择任务'
  const activeTaskStatusLabel = selectedTask ? humanTaskStatus(selectedTask.status) : ''
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const publishGuardReasons = workspace.publishGuardState?.reasons ?? []
  const l2BlocksRealSave = l2Gate?.status !== 'passed'
  const l3BlocksRealSave = l3Gate?.status === 'blocked'
  const l3NeedsApproval = l3Gate?.status !== 'passed'
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
  const tone = runtimeStatusUnavailable || l3BlocksRealSave || hasBlocker || publishGuardReasons.length > 0
    ? 'danger'
    : l2BlocksRealSave || l3NeedsApproval || workspace.source === 'mock' || workspace.evidenceGrade?.grade === 'C'
      ? 'warn'
      : 'ok'
  const nextHeadline = !dxmLoggedIn
    ? '继续下一步：打开真实店小秘登录'
    : l2BlocksRealSave
      ? '继续下一步：运行只读页面检查'
      : l3NeedsApproval
        ? '继续下一步：人工确认单商品只保存'
        : '当前可执行：单商品只保存自动化'
  const headline = selectedTaskCompleted
    ? '当前任务已完成，可查看执行记录'
    : runtimeStatusUnavailable
      ? '运行状态接口不可用'
      : realWriteExpectedBlocked
        ? `真实保存已阻断：${nextHeadline.replace('继续下一步：', '')}`
        : nextHeadline
  const gateStatusLine = `L2 页面核验 ${humanGateStatus(l2Gate?.status ?? workspace.safety.l2Status ?? 'not_run')}，人工确认 ${humanGateStatus(l3Gate?.status ?? 'not_run')}`
  const statusLine = `当前任务 ${activeTaskLabel}，${tone === 'danger' ? `保存前置条件未完成：${gateStatusLine}` : gateStatusLine}`
  const gateDetails = [
    l2Gate ? `L2 页面核验：${l2Gate.detail}` : 'L2 页面核验：缺少真实页面核验状态',
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
      ? '无法读取本机运行状态；请查看实时日志或重启免安装版。'
      : '工作台只会执行受控“只保存”，发布和批量无人值守仍保持关闭。'
    : selectedTaskCompleted
      ? `任务 ${activeTaskLabel} ${activeTaskStatusLabel}，继续查看报告、证据或打开执行控制台复核。`
      : '按操作引导继续：真实登录、配置、只读页面检查、人工确认后才启动保存。'
  const runtimeEndpointLine = runtimeStatus
    ? `服务端 ${runtimeStatus.backend.url ?? `端口 ${runtimeStatus.backend.port ?? '未知'}`} / 前端 ${runtimeStatus.frontend.url ?? `端口 ${runtimeStatus.frontend.port ?? '未知'}`}`
    : runtimeStatusUnavailable
      ? `运行状态接口不可用：${runtimeStatusError}`
      : '服务端与前端地址待检测'
  const desktopRuntimeLine = desktopRuntime
    ? `DXM Agent Console 桌面模式 / 后端 ${desktopRuntime.apiBase ?? `端口 ${desktopRuntime.backendPort ?? '未知'}`}`
    : null
  const runtimeOwner = runtimeStatus?.runtimeControl?.owner ?? 'direct'
  const runtimeOwnerChip = runtimeOwnerLabel(runtimeOwner, Boolean(runtimeStatus?.runtimeControl?.managedByDesktop))
  const backendPortMismatch = typeof desktopRuntime?.backendPort === 'number'
    && typeof runtimeStatus?.backend.port === 'number'
    && desktopRuntime.backendPort !== runtimeStatus.backend.port
  const runtimeChips = runtimeStatus
    ? [
      { label: `启动来源：${runtimeOwnerChip}`, tone: runtimeOwner === 'direct' ? 'warn' : 'ok' },
      { label: `后端：${runtimeStatus.backend.status === 'ok' ? '运行中' : '异常'}`, tone: runtimeStatus.backend.status === 'ok' ? 'ok' : 'danger' },
      { label: `前端：${runtimeStatus.frontend.status === 'ok' ? '运行中' : '异常'}`, tone: runtimeStatus.frontend.status === 'ok' ? 'ok' : 'danger' },
      { label: `后端端口：${runtimeStatus.backend.port ?? '未知'}`, tone: runtimeStatus.backend.status === 'ok' ? 'ok' : 'danger' },
      { label: `前端端口：${runtimeStatus.frontend.port ?? '未知'}`, tone: runtimeStatus.frontend.status === 'ok' ? 'ok' : 'danger' },
      { label: `自动浏览器：${runtimeStatus.agentConsole.active ? '运行中' : '待命'}`, tone: runtimeStatus.agentConsole.active ? 'ok' : 'warn' },
      { label: `DXM 登录：${runtimeStatus.dxmLogin.status}`, tone: dxmLoginTone(runtimeStatus.dxmLogin.status) },
    ]
    : []
  const detailChips = [
    ...(runtimeStatusUnavailable ? [{ label: '状态接口异常', tone: 'danger' }] : []),
    ...runtimeChips,
    ...(desktopRuntime ? [
      { label: 'DXM Agent Console 桌面模式', tone: 'ok' },
      { label: `桌面日志：${desktopRuntime.desktopLogPath ?? '待生成 desktop-main.log'}`, tone: desktopRuntime.lastError ? 'danger' : 'muted' },
      { label: `后端日志：${desktopRuntime.backendLogPath ?? '待生成 backend.log'}`, tone: 'muted' },
    ] : []),
    ...(backendPortMismatch ? [{ label: '桌面后端端口与接口端口不一致', tone: 'danger' }] : []),
    { label: `L2 页面核验：${humanGateStatus(l2Gate?.status ?? 'not_run')}`, tone: l2BlocksRealSave ? 'danger' : 'ok' },
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
    : !dxmLoggedIn
    ? '等待真实登录'
    : l2BlocksRealSave
    ? '先完成只读检查'
    : l3NeedsApproval
      ? '等待人工确认'
      : '可启动只保存'
  const primaryActionLabel = selectedTaskCompleted
    ? '查看执行记录'
    : '继续下一步'
  const handlePrimaryAction = selectedTaskCompleted
    ? onShowConsole
    : !dxmLoggedIn
      ? onShowConsole
      : l2BlocksRealSave || l3NeedsApproval
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
        <button className="button button--secondary safety-bar__primary-action" type="button" onClick={handlePrimaryAction} disabled={busy}>
          {primaryActionLabel}
        </button>
        <details className="safety-bar__meta-details inline-disclosure">
          <summary>系统状态与验收详情</summary>
          <p className="safety-bar__compact-detail">{conciseDetail}</p>
          <div>
            <span className="guard-chip guard-chip--muted">{runtimeEndpointLine}</span>
            {desktopRuntimeLine && <span className="guard-chip guard-chip--ok">{desktopRuntimeLine}</span>}
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
          刷新
        </button>
      </div>
    </section>
  )
}

function dxmLoginTone(status: string) {
  if (dxmReadySessionStatuses.has(status)) return 'ok'
  return status.includes('error') ? 'danger' : 'warn'
}

function runtimeOwnerLabel(owner: string, managedByDesktop: boolean) {
  if (owner === 'desktop' || managedByDesktop) return '免安装版已接管'
  if (owner === 'start_mvp') return 'start-mvp 已接管'
  return '旧进程/直接启动'
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
