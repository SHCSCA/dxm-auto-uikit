import type { ConfigPreview, DeliveryWorkspace, RuntimeStatus, Task } from '../../types'
import { humanTaskStatus } from '../../workspace'
import {
  CheckRow,
  DXM_LOGGED_IN_STATUSES,
  GapList,
  ModuleHead,
  displayTaskName,
  isRealWriteExpectedBlocked,
  l3PostEvidenceGapIds,
  presentAcceptanceGaps,
  requiresManualApproval,
} from '../WorkbenchModules'

type HomePageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  runtimeStatus: RuntimeStatus | null
  onShowDxmAccess: () => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowReports: () => void
}

export function HomePage({ workspace, selectedTask, configPreview, runtimeStatus, onShowDxmAccess, onShowTasks, onShowConfig, onShowConsole, onShowReports }: HomePageProps) {
  const realWriteExpectedBlocked = isRealWriteExpectedBlocked(workspace)
  const presentedAcceptanceGaps = presentAcceptanceGaps(workspace.acceptanceGaps, realWriteExpectedBlocked)
  const blockerCount = presentedAcceptanceGaps.filter((gap) => gap.severity === 'blocker').length
  const l3PostEvidenceCount = presentedAcceptanceGaps.filter((gap) => l3PostEvidenceGapIds.has(gap.id)).length
  const grade = workspace.evidenceGrade?.grade ?? 'C'
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const configReady = Boolean(selectedTaskCompleted || (selectedTask && configPreview?.taskId === selectedTask.id && configPreview.ok))
  const l2Passed = l2Gate?.status === 'passed'
  const l3Passed = l3Gate?.status === 'passed'
  const realWriteReady = !realWriteExpectedBlocked
  const agentActive = runtimeStatus?.agentConsole.active === true
  const waitingForManualConfirm = Boolean(selectedTask && requiresManualApproval(selectedTask) && l2Passed && !l3Passed && !selectedTaskCompleted)
  const controlOwner = agentActive ? 'Agent 操作中' : waitingForManualConfirm ? '等待人工确认' : '用户操作中'
  const controlOwnerDetail = agentActive
    ? '真实浏览器正在执行，请看浏览器左上角进度。'
    : waitingForManualConfirm
      ? '保存前需要确认只保存、不发布。'
      : '当前由你选择下一步，系统不会自动保存或发布。'
  const nextAction = selectedTaskCompleted
    ? { label: '查看本次保存结果', detail: '复核报告、未发布证明和真实浏览器记录。', cta: '查看保存结果', action: onShowReports }
    : !dxmLoggedIn
      ? { label: '登录真实店小秘', detail: '打开可见浏览器完成账号、密码和验证码。', cta: '去登录店小秘', action: onShowDxmAccess }
      : !selectedTask
        ? { label: '创建数据采集认领任务', detail: '先从数据采集把真实商品认领到采集箱。', cta: '去数据采集认领', action: onShowTasks }
        : selectedTask.mode === 'claim_only' && selectedTask.status !== 'completed'
          ? { label: '运行数据采集认领', detail: '打开真实浏览器，把商品认领到采集箱。', cta: '去执行浏览器', action: onShowConsole }
        : !configReady
          ? { label: '填写模板中心配置', detail: '确认本次编辑保存会读取哪些字段值。', cta: '去模板中心', action: onShowConfig }
          : !l2Passed
            ? { label: '运行真实只读检查', detail: '先读取店小秘页面，确认不会领取、保存或发布。', cta: '去执行浏览器', action: onShowConsole }
            : requiresManualApproval(selectedTask) && !l3Passed
              ? { label: '人工确认只保存', detail: '确认只保存、不发布后才能启动执行浏览器。', cta: '去执行浏览器', action: onShowConsole }
              : { label: '启动执行浏览器', detail: '系统将操控独立真实浏览器，只保存当前单商品。', cta: '去执行浏览器', action: onShowConsole }
  const blockerReason = selectedTaskCompleted
    ? '任务已完成，当前只需要复核结果。'
    : !dxmLoggedIn
      ? '店小秘还没有登录。'
      : !selectedTask
        ? '还没有创建数据采集认领任务。'
        : selectedTask.mode === 'claim_only' && selectedTask.status !== 'completed'
          ? '采集认领还没有完成。'
          : !configReady
            ? '模板中心配置还没有补齐。'
            : !l2Passed
              ? '真实只读检查还没有通过。'
              : waitingForManualConfirm
                ? '保存前还没有完成人工确认。'
                : agentActive
                  ? 'Agent 正在真实浏览器中执行。'
                  : '没有阻断。'
  const decisionCards = [
    { label: '现在该做什么', value: nextAction.label, detail: nextAction.detail, ok: selectedTaskCompleted || (!agentActive && blockerReason === '没有阻断。') },
    { label: '为什么不能继续', value: blockerReason, detail: controlOwnerDetail, ok: blockerReason === '没有阻断。' || selectedTaskCompleted },
    { label: '下一步', value: nextAction.cta, detail: selectedTask ? displayTaskName(selectedTask) : '从数据采集认领开始。', ok: true },
  ]

  return (
    <section className="dashboard-grid" aria-label="今天做什么">
      <div className="hero-panel home-command">
        <div>
          <h1>首页</h1>
          <p>按两段真实流程推进：先从数据采集认领到采集箱，再从采集箱编辑商品并只保存。</p>
          <p className="hero-panel__note">不会发布；批量和无人值守保存保持关闭。</p>
          <div className="hero-panel__outcomes home-command__status-grid" aria-label="首页决策：现在该做什么 / 为什么不能继续 / 下一步">
            {decisionCards.map((card) => (
              <span key={card.label} className={card.ok ? 'is-ok' : 'is-warn'}>
                <strong>{card.label}</strong>
                <b>{card.value}</b>
                <small>{card.detail}</small>
              </span>
            ))}
          </div>
          <div className="home-command__boundary" aria-label="保存边界">
            <span><strong>当前模式</strong><b>只保存</b></span>
            <span><strong>保存范围</strong><b>{realWriteReady ? '单商品只保存可执行' : '等待人工确认'}</b></span>
            <span><strong>{realWriteReady ? '当前范围' : '下一步'}</strong><b>{realWriteReady ? '只保存，不发布' : '完成页面检查'}</b></span>
          </div>
        </div>
        <div className="hero-panel__status home-command__next">
          <span>现在只做这一步</span>
          <strong>{nextAction.label}</strong>
          <small>{nextAction.detail}</small>
          <div className="home-command__current-task">
            <span>当前任务</span>
            <strong>{selectedTask ? displayTaskName(selectedTask) : '未选择任务'}</strong>
          </div>
          <button className="button button--secondary" type="button" onClick={nextAction.action}>{nextAction.cta}</button>
        </div>
      </div>

      <div className="module-card span-3 home-menu-map">
        <ModuleHead title="两段式操作入口" meta="普通用户只按当前按钮推进" />
        <div className="home-menu-map__grid home-menu-map__grid--compact">
          <button className="button button--quiet" type="button" onClick={onShowDxmAccess}>店小秘登录</button>
          <button className="button button--quiet" type="button" onClick={onShowTasks}>数据采集认领</button>
          <button className="button button--quiet" type="button" onClick={onShowConfig}>模板中心</button>
          <button className="button button--quiet" type="button" onClick={onShowConsole}>执行浏览器</button>
          <button className="button button--quiet" type="button" onClick={onShowReports}>结果报告</button>
        </div>
        <details className="inline-disclosure home-menu-map__guide">
          <summary>查看完整路径</summary>
          <OperationGuide workspace={workspace} selectedTask={selectedTask} />
        </details>
      </div>

      <details className="module-card span-3 disclosure-card">
          <summary>维护人员查看技术状态</summary>
        <div className="check-list check-list--inline">
          <CheckRow label="真实店铺/商品已读取" ok={workspace.stores.length > 0 && workspace.products.length > 0} />
          <CheckRow label="真实只读检查通过" ok={l2Gate?.status === 'passed'} />
          <CheckRow label="仅单商品只保存放行" ok />
          <CheckRow label="发布入口隔离" ok={workspace.publishGuardState?.publish_allowed === false || workspace.publishGuardState?.safe === true} />
          <CheckRow label={`证据等级 ${grade} / 待处理 ${blockerCount} 项${l3PostEvidenceCount ? ` / 保存后补齐 ${l3PostEvidenceCount} 项` : ''}`} ok={grade === 'A'} />
        </div>
        <GapList gaps={presentedAcceptanceGaps.slice(0, 4)} />
      </details>
    </section>
  )
}

function OperationGuide({ workspace, selectedTask }: { workspace: DeliveryWorkspace; selectedTask: Task | null }) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const steps = [
    { label: '登录店小秘', ok: workspace.stores.length > 0 },
    { label: '数据采集认领到采集箱', ok: selectedTask?.mode === 'claim_only' || selectedTask?.mode === 'single_save' },
    { label: '采集箱商品套用模板', ok: selectedTask?.mode === 'single_save' },
    { label: '确认真实只读检查通过', ok: l2Gate?.status === 'passed' },
    { label: '人工批准后启动真实浏览器保存', ok: l3Gate?.status === 'passed' || selectedTask?.status === 'completed' },
  ]
  return (
    <ol className="operation-guide">
      {steps.map((step, index) => (
        <li key={step.label} className={step.ok ? 'is-done' : ''}>
          <span>{index + 1}</span>
          <strong>{step.label}</strong>
        </li>
      ))}
    </ol>
  )
}
