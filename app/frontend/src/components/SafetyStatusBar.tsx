import type { DeliveryWorkspace, Task } from '../types'
import { humanTaskStatus } from '../workspace'

const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])

type SafetyStatusBarProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  busy: boolean
  onRefresh: () => void
}

export function SafetyStatusBar({ workspace, selectedTask, busy, onRefresh }: SafetyStatusBarProps) {
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
  const gateStatusLine = `L2 ${humanGateStatus(l2Gate?.status ?? workspace.safety.l2Status ?? 'not_run')}，L3 ${humanGateStatus(l3Gate?.status ?? 'not_run')}`
  const statusLine = `当前任务 ${activeTaskLabel}，${tone === 'danger' ? `真实写入门禁未通过：${gateStatusLine}` : gateStatusLine}`
  const gateDetails = [
    l2Gate ? `L2：${l2Gate.detail}` : 'L2：缺少真实只读门禁状态',
    l3Gate ? `L3：${l3Gate.detail}` : 'L3：缺少真实保存门禁状态',
  ]
  const blockerDetails = [
    ...visibleBlockerGaps.map((gap) => `blocker：${gap.title} - ${gap.detail}`),
    ...(l3PostEvidenceGapCount > 0 ? [`L3 后置证据：${l3PostEvidenceGapCount} 项预期阻断 - 真实写入放行后再补齐`] : []),
    ...publishGuardReasons.map((reason) => `publish guard：${reason}`),
  ]
  const detail = tone === 'danger'
    ? `${statusLine}。${[...gateDetails, ...blockerDetails].join('；') || '真实保存启动条件未满足。'}`
    : tone === 'warn'
      ? `${statusLine}，最近校验 ${workspace.safety.lastCheckedAt}`
      : `当前任务 ${activeTaskLabel}，最近校验 ${workspace.safety.lastCheckedAt}`

  return (
    <section className={`safety-bar safety-bar--${tone}`} aria-label="安全门禁状态条">
      <div className="safety-bar__main">
        <span className="safety-dot" aria-hidden="true" />
        <div>
          <strong>{headline}</strong>
          <span>{detail}</span>
        </div>
      </div>
      <div className="safety-bar__meta" aria-label="禁止入口检查">
        <span className={`guard-chip guard-chip--${l2BlocksRealSave ? 'danger' : 'ok'}`}>L2：{humanGateStatus(l2Gate?.status ?? 'not_run')}</span>
        <span className={`guard-chip guard-chip--${l3BlocksRealSave ? 'danger' : l3NeedsApproval ? 'warn' : 'ok'}`}>L3：{l3NeedsApproval ? `不可启动 / ${humanGateStatus(l3Gate?.status ?? 'not_run')}` : humanGateStatus(l3Gate?.status ?? 'not_run')}</span>
        {visibleBlockerGaps.slice(0, 2).map((gap) => (
          <span key={gap.id} className="guard-chip guard-chip--danger">blocker：{gap.title}</span>
        ))}
        {l3PostEvidenceGapCount > 0 && (
          <span className="guard-chip guard-chip--warn">L3 后置证据：{l3PostEvidenceGapCount} 项预期阻断</span>
        )}
        {publishGuardReasons.slice(0, 2).map((reason) => (
          <span key={reason} className="guard-chip guard-chip--danger">guard：{reason}</span>
        ))}
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
