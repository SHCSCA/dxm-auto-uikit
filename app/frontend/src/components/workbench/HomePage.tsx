import type { ConfigPreview, DeliveryWorkspace, RuntimeStatus, Task } from '../../types'
import {
  DXM_LOGGED_IN_STATUSES,
  displayTaskName,
  isRealWriteExpectedBlocked,
  requiresManualApproval,
} from '../WorkbenchModules'

type HomePageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  runtimeStatus: RuntimeStatus | null
  onShowDxmAccess: () => void
  onShowAcquisition: () => void
  onShowDraftEdit: () => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowReports: () => void
}

export function HomePage({ workspace, selectedTask, configPreview, runtimeStatus, onShowDxmAccess, onShowAcquisition, onShowDraftEdit, onShowTasks, onShowConfig, onShowConsole, onShowReports }: HomePageProps) {
  const realWriteExpectedBlocked = isRealWriteExpectedBlocked(workspace)
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const configReady = Boolean(selectedTaskCompleted || (selectedTask && configPreview?.taskId === selectedTask.id && configPreview.ok))
  const l2Passed = l2Gate?.status === 'passed'
  const l3Passed = l3Gate?.status === 'passed'
  const realWriteReady = !realWriteExpectedBlocked
  const agentActive = runtimeStatus?.realBrowser?.active === true
  const claimTaskCompleted = selectedTask?.mode === 'claim_only' && selectedTask.status === 'completed'
  const waitingForManualConfirm = Boolean(selectedTask && requiresManualApproval(selectedTask) && l2Passed && !l3Passed && !selectedTaskCompleted)
  const controlOwner = agentActive ? '自动助手操作中' : waitingForManualConfirm ? '等待人工确认' : '用户操作中'
  const controlOwnerDetail = agentActive
    ? '真实浏览器正在执行，请看浏览器左上角进度。'
    : waitingForManualConfirm
      ? '保存前需要确认只保存、不发布。'
      : '当前由你选择下一步，系统不会自动保存或发布。'
  const nextAction = claimTaskCompleted
    ? { label: '选择商品箱商品并编辑保存', detail: '选择已进入商品箱的真实商品，确认模板后只保存。', cta: '去商品箱编辑保存', action: onShowDraftEdit }
    : selectedTaskCompleted
    ? { label: '查看本次保存结果', detail: '复核报告、未发布证明和真实浏览器记录。', cta: '查看保存结果', action: onShowReports }
    : !dxmLoggedIn
      ? { label: '登录真实店小秘', detail: '打开可见浏览器完成账号、密码和验证码。', cta: '去登录店小秘', action: onShowDxmAccess }
      : !selectedTask
        ? { label: '待认领入箱', detail: '先从店小秘已有待认领列表中选择商品，并认领到商品箱。', cta: '去待认领入箱', action: onShowAcquisition }
        : selectedTask.mode === 'claim_only' && selectedTask.status !== 'completed'
          ? { label: '运行待认领入箱', detail: '打开真实浏览器，把已有待认领商品认领到商品箱。', cta: '去真实浏览器', action: onShowConsole }
        : !configReady
          ? { label: '检查编辑页模板', detail: '确认本次编辑保存会读取哪套模板和字段值。', cta: '去编辑页模板', action: onShowConfig }
          : !l2Passed
            ? { label: '运行保存前安全检查', detail: '先读取店小秘页面，确认不会认领、保存或发布。', cta: '去真实浏览器', action: onShowConsole }
            : requiresManualApproval(selectedTask) && !l3Passed
              ? { label: '人工确认只保存', detail: '确认只保存、不发布后才能启动真实浏览器。', cta: '去真实浏览器', action: onShowConsole }
              : { label: '打开真实浏览器', detail: '系统将操控独立真实浏览器，只保存当前单商品。', cta: '去真实浏览器', action: onShowConsole }
  const blockerReason = claimTaskCompleted
    ? '待认领商品已进入商品箱，下一步从商品箱创建只保存任务。'
    : selectedTaskCompleted
    ? '任务已完成，当前只需要复核结果。'
      : !dxmLoggedIn
      ? '店小秘还没有登录。'
      : !selectedTask
        ? '还没有创建待认领入箱任务。'
        : selectedTask.mode === 'claim_only' && selectedTask.status !== 'completed'
          ? '待认领入箱还没有完成。'
          : !configReady
            ? '编辑页模板还没有补齐。'
            : !l2Passed
            ? '保存前安全检查还没有通过。'
              : waitingForManualConfirm
                ? '保存前还没有完成人工确认。'
                : agentActive
                  ? '自动助手正在真实浏览器中执行。'
                  : '没有阻断。'
  const decisionCards = [
    { label: '现在该做什么', value: nextAction.label, detail: nextAction.detail, ok: selectedTaskCompleted || (!agentActive && blockerReason === '没有阻断。') },
    { label: '为什么不能继续', value: blockerReason, detail: controlOwnerDetail, ok: blockerReason === '没有阻断。' || selectedTaskCompleted },
    { label: '下一步', value: nextAction.cta, detail: selectedTask ? displayTaskName(selectedTask) : '从待认领入箱开始。', ok: true },
  ]

  return (
    <section className="dashboard-grid" aria-label="今天做什么">
      <div className="hero-panel home-command">
        <div>
          <h1>操作首页</h1>
          <p>按两段真实流程推进：先处理店小秘已有待认领商品，再从商品箱进入编辑保存。</p>
          <p className="hero-panel__note">不会发布；批量和无人值守保存保持关闭。</p>
          <div className="hero-panel__outcomes home-command__status-grid" aria-label="操作首页决策：现在该做什么 / 为什么不能继续 / 下一步">
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
            <span><strong>真实浏览器</strong><b>{agentActive ? '执行中' : '按需启动'}</b></span>
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
      <div className="module-card home-flow-card">
        <div className="module-head">
          <div>
            <h2>两段真实流程</h2>
            <p>先认领，再编辑保存。系统不会跳过商品箱直接保存。</p>
            <p>系统只处理店小秘已有待认领商品，不填写产品网址，不新建商品。</p>
          </div>
          <span>{controlOwner}</span>
        </div>
        <OperationGuide workspace={workspace} selectedTask={selectedTask} />
      </div>
    </section>
  )
}

function OperationGuide({ workspace, selectedTask }: { workspace: DeliveryWorkspace; selectedTask: Task | null }) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const steps = [
    { label: '登录店小秘', ok: workspace.stores.length > 0 },
    { label: '第一段：待认领入箱', ok: selectedTask?.mode === 'claim_only' || selectedTask?.mode === 'single_save' },
    { label: '第二段：商品箱编辑只保存', ok: selectedTask?.mode === 'single_save' },
    { label: '确认保存前安全检查通过', ok: l2Gate?.status === 'passed' },
    { label: '人工确认后只保存', ok: l3Gate?.status === 'passed' || selectedTask?.status === 'completed' },
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
