import type { DeliveryWorkspace, RuntimeStatus, Task } from '../types'
import { humanTaskStatus } from '../workspace'

const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])

type SafetyStatusBarProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  runtimeStatus: RuntimeStatus | null
  busy: boolean
  onRefresh: () => void
  onShowTasks: () => void
  onShowConsole: () => void
}

export function SafetyStatusBar({ workspace, selectedTask, runtimeStatus, busy, onRefresh, onShowTasks, onShowConsole }: SafetyStatusBarProps) {
  const activeTaskLabel = selectedTask ? `#${selectedTask.id} ${humanTaskStatus(selectedTask.status)}` : '未选择任务'
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const publishGuardReasons = workspace.publishGuardState?.reasons ?? []
  const l2BlocksRealSave = l2Gate?.status !== 'passed'
  const l3BlocksRealSave = l3Gate?.status === 'blocked'
  const l3NeedsApproval = l3Gate?.status !== 'passed'
  const realWriteExpectedBlocked = l2BlocksRealSave || l3NeedsApproval
  const blockerGaps = workspace.acceptanceGaps.filter((gap) => gap.severity === 'blocker')
  const visibleBlockerGaps = blockerGaps.filter((gap) => !(realWriteExpectedBlocked && l3PostEvidenceGapIds.has(gap.id)))
  const l3PostEvidenceGapCount = blockerGaps.filter((gap) => realWriteExpectedBlocked && l3PostEvidenceGapIds.has(gap.id)).length
  const hasBlocker = visibleBlockerGaps.length > 0
  const tone = l2BlocksRealSave || l3BlocksRealSave
    ? 'danger'
    : workspace.source === 'mock' || workspace.evidenceGrade?.grade === 'C' || hasBlocker
      ? 'warn'
      : 'ok'
  const headline = tone === 'danger'
    ? '真实写入门禁未通过'
    : tone === 'warn'
      ? '尚未形成真实可交付证明'
      : workspace.safety.guarantee
  const gateStatusLine = `只读检查 ${humanGateStatus(l2Gate?.status ?? workspace.safety.l2Status ?? 'not_run')}，人工确认 ${humanGateStatus(l3Gate?.status ?? 'not_run')}`
  const statusLine = `当前任务 ${activeTaskLabel}，${tone === 'danger' ? `保存前置条件未完成：${gateStatusLine}` : gateStatusLine}`
  const gateDetails = [
    l2Gate ? `只读检查：${l2Gate.detail}` : '只读检查：缺少真实只读门禁状态',
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
    ? `${statusLine}。完成只读检查和人工确认后，再启动只保存任务。`
    : detail
  const runtimeEndpointLine = runtimeStatus
    ? `服务端 ${runtimeStatus.backend.url ?? `端口 ${runtimeStatus.backend.port ?? '未知'}`} / 前端 ${runtimeStatus.frontend.url ?? `端口 ${runtimeStatus.frontend.port ?? '未知'}`}`
    : '服务端与前端地址待检测'
  const runtimeChips = runtimeStatus
    ? [
      { label: `后端：${runtimeStatus.backend.status === 'ok' ? '运行中' : '异常'}`, tone: runtimeStatus.backend.status === 'ok' ? 'ok' : 'danger' },
      { label: `前端：${runtimeStatus.frontend.status === 'ok' ? '运行中' : '异常'}`, tone: runtimeStatus.frontend.status === 'ok' ? 'ok' : 'danger' },
      { label: `后端端口：${runtimeStatus.backend.port ?? '未知'}`, tone: runtimeStatus.backend.status === 'ok' ? 'ok' : 'danger' },
      { label: `前端端口：${runtimeStatus.frontend.port ?? '未知'}`, tone: runtimeStatus.frontend.status === 'ok' ? 'ok' : 'danger' },
      { label: `自动浏览器：${runtimeStatus.agentConsole.active ? '运行中' : '待命'}`, tone: runtimeStatus.agentConsole.active ? 'ok' : 'warn' },
      { label: `DXM 登录：${runtimeStatus.dxmLogin.status}`, tone: runtimeStatus.dxmLogin.status.includes('error') ? 'danger' : 'warn' },
    ]
    : []
  const detailChips = [
    ...runtimeChips,
    { label: `只读检查：${humanGateStatus(l2Gate?.status ?? 'not_run')}`, tone: l2BlocksRealSave ? 'danger' : 'ok' },
    { label: `人工确认：${l3NeedsApproval ? `不可启动 / ${humanGateStatus(l3Gate?.status ?? 'not_run')}` : humanGateStatus(l3Gate?.status ?? 'not_run')}`, tone: l3BlocksRealSave ? 'danger' : l3NeedsApproval ? 'warn' : 'ok' },
    ...visibleBlockerGaps.slice(0, 2).map((gap) => ({ label: `阻断项：${gap.title}`, tone: 'danger' })),
    ...(l3PostEvidenceGapCount > 0 ? [{ label: `保存后证据：${l3PostEvidenceGapCount} 项预期阻断`, tone: 'warn' }] : []),
    ...publishGuardReasons.slice(0, 2).map((reason) => ({ label: `发布隔离：${reason}`, tone: 'danger' })),
    ...workspace.safety.forbiddenActions.slice(0, 2).map((action) => ({ label: `${action}：无入口`, tone: 'muted' })),
  ]
  const primaryStatus = l2BlocksRealSave
    ? '先完成只读检查'
    : l3NeedsApproval
      ? '等待人工确认'
      : '可申请受控保存'
  const primaryActionLabel = l2BlocksRealSave
    ? '去任务中心处理'
    : l3NeedsApproval
      ? '去确认保存条件'
      : '打开执行控制台'
  const handlePrimaryAction = l2BlocksRealSave || l3NeedsApproval ? onShowTasks : onShowConsole

  return (
    <section className={`safety-bar safety-bar--${tone}`} aria-label="安全门禁状态条">
      <div className="safety-bar__main">
        <span className="safety-dot" aria-hidden="true" />
        <div>
          <strong>{headline}</strong>
          <span>{conciseDetail}</span>
          <small className="safety-bar__runtime-endpoints">{runtimeEndpointLine}</small>
          {tone === 'danger' && (
            <details className="safety-bar__details">
              <summary>查看阻断详情</summary>
              <span>{detail}</span>
            </details>
          )}
        </div>
      </div>
      <div className="safety-bar__meta" aria-label="禁止入口检查">
        <span className={`guard-chip guard-chip--${tone === 'danger' ? 'danger' : tone === 'warn' ? 'warn' : 'ok'}`}>{primaryStatus}</span>
        <button className="button button--secondary safety-bar__primary-action" type="button" onClick={handlePrimaryAction} disabled={busy}>
          {primaryActionLabel}
        </button>
        <details className="safety-bar__meta-details">
          <summary>详情</summary>
          <div>
            {detailChips.map((chip) => (
              <span key={chip.label} className={`guard-chip guard-chip--${chip.tone}`}>{chip.label}</span>
            ))}
          </div>
        </details>
        <button className="button button--quiet" type="button" onClick={onRefresh} disabled={busy}>
          刷新
        </button>
      </div>
    </section>
  )
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
