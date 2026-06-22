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
  const controlOwner = agentActive ? 'Agent 操作中' : waitingForManualConfirm ? '系统等待确认' : '用户操作中'
  const controlOwnerDetail = agentActive
    ? '请看真实浏览器左上角进度；需要处理验证码或弹窗时再人工接管。'
    : waitingForManualConfirm
      ? '页面检查已过，启动保存前需要你确认只保存、不发布。'
      : '当前由你选择下一步，系统不会自动保存或发布。'
  const nextAction = selectedTaskCompleted
    ? { label: '查看本次保存结果', detail: '复核报告、未发布证明和真实浏览器记录。', cta: '查看保存结果', action: onShowReports }
    : !dxmLoggedIn
      ? { label: '登录真实店小秘', detail: '打开可见浏览器完成账号、密码和验证码。', cta: '去登录店小秘', action: onShowDxmAccess }
      : !selectedTask
        ? { label: '创建单商品只保存任务', detail: '选择一个商品，只创建受控保存任务。', cta: '去选择商品', action: onShowTasks }
        : !configReady
          ? { label: '填写编辑页配置', detail: '确认本次任务执行会读取哪些字段值。', cta: '去填写编辑页', action: onShowConfig }
          : !l2Passed
            ? { label: '运行真实只读检查', detail: '先读取店小秘页面，确认不会领取、保存或发布。', cta: '去开始只保存', action: onShowConsole }
            : requiresManualApproval(selectedTask) && !l3Passed
              ? { label: '人工确认只保存', detail: '确认只保存、不发布后才能启动执行浏览器。', cta: '去开始只保存', action: onShowConsole }
              : { label: '启动执行浏览器', detail: '系统将操控独立真实浏览器，只保存当前单商品。', cta: '去开始只保存', action: onShowConsole }
  const homeStatusCards = [
    { label: '店小秘登录', value: dxmLoggedIn ? '已登录' : '待登录', ok: dxmLoggedIn, detail: dxmLoggedIn ? '真实浏览器登录态可用' : '先打开真实浏览器登录' },
    { label: '当前任务', value: selectedTask ? humanTaskStatus(selectedTask.status) : '待创建', ok: Boolean(selectedTask), detail: selectedTask ? displayTaskName(selectedTask) : '选择一个商品创建只保存任务' },
    { label: '填写编辑页', value: configReady ? '已就绪' : '待补齐', ok: configReady, detail: configReady ? '执行取值已可核对' : '按店小秘编辑页分区补字段' },
    { label: '保存前检查', value: selectedTaskCompleted ? '已完成' : l2Passed ? '已通过' : '待运行', ok: selectedTaskCompleted || l2Passed, detail: selectedTaskCompleted ? '本次任务已结束，优先复核保存结果' : l2Passed ? '页面读取检查已通过' : '通过后才能启动执行浏览器' },
    { label: '人工确认', value: selectedTaskCompleted ? '已完成' : l3Passed ? '已确认' : '待确认', ok: selectedTaskCompleted || l3Passed, detail: '只保存，不发布；批量和无人值守关闭' },
    { label: '当前控制权', value: controlOwner, ok: !agentActive || runtimeStatus?.agentConsole.browserVisible === true, detail: controlOwnerDetail },
  ]
  const homeMenuGroups = [
    {
      title: '开始',
      menu: '今天做什么 / 登录店小秘',
      ok: dxmLoggedIn,
      detail: dxmLoggedIn ? '店小秘真实登录态已可用。' : '先打开真实店小秘浏览器，完成账号、密码和验证码。',
      cta: dxmLoggedIn ? '查看登录状态' : '去登录店小秘',
      action: onShowDxmAccess,
    },
    {
      title: '准备商品',
      menu: '选择商品 / 填写编辑页',
      ok: Boolean(selectedTask && configReady),
      detail: !selectedTask
        ? '先选择商品并创建单商品只保存任务。'
        : configReady
          ? '当前任务执行取值已可核对。'
          : '按店小秘编辑页分区补齐字段和模板。',
      cta: !selectedTask ? '去选择商品' : '去填写编辑页',
      action: !selectedTask ? onShowTasks : onShowConfig,
    },
    {
      title: '执行保存',
      menu: '开始只保存',
      ok: selectedTaskCompleted || (l2Passed && l3Passed),
      detail: selectedTaskCompleted
        ? '本次保存任务已完成，当前只需要复核保存结果和未发布证明。'
        : l2Passed
        ? '只读检查已通过，按人工确认后启动执行浏览器。'
        : '先运行真实只读检查，不领取、不保存、不发布。',
      cta: selectedTaskCompleted ? '查看保存结果' : '去开始只保存',
      action: selectedTaskCompleted ? onShowReports : onShowConsole,
    },
    {
      title: '复盘',
      menu: '保存结果 / 问题处理',
      ok: selectedTaskCompleted || workspace.reports.length > 0,
      detail: selectedTaskCompleted ? '查看保存结果、未发布证明和问题处理建议。' : '执行完成后在这里先看业务结果，必要时再展开证据。',
      cta: '查看保存结果',
      action: onShowReports,
    },
  ]

  return (
    <section className="dashboard-grid" aria-label="今天做什么">
      <div className="hero-panel home-command">
        <div>
          <h1>今天先做哪一步</h1>
          <p>按真实店铺、真实商品和编辑页配置推进：登录店小秘、选择商品、补齐配置、只读检查、人工确认后，只执行单商品保存。</p>
          <p className="hero-panel__note">不会发布；批量和无人值守保存仍保持关闭，验收详情放在下方折叠区。</p>
          <div className="hero-panel__outcomes home-command__status-grid" aria-label="当前流程状态">
            {homeStatusCards.map((card) => (
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
        <ModuleHead title="单商品只保存流程" meta="普通用户每次只处理一个入口" />
        <div className="home-menu-map__grid">
          {homeMenuGroups.map((group) => (
            <article key={group.title} className={group.ok ? 'is-ok' : 'is-current'}>
              <span>{group.title}</span>
              <strong>{group.menu}</strong>
              <small>{group.detail}</small>
              <button className="button button--quiet" type="button" onClick={group.action}>
                {group.cta}
              </button>
            </article>
          ))}
        </div>
        <details className="inline-disclosure home-menu-map__guide">
          <summary>查看完整 4 步路径</summary>
          <OperationGuide workspace={workspace} selectedTask={selectedTask} />
        </details>
      </div>

      <details className="module-card span-3 disclosure-card">
          <summary>维护人员查看状态详情</summary>
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
    { label: '配置店铺、类目、图片和半托管参数', ok: workspace.stores.length > 0 && workspace.products.length > 0 },
    { label: '选择单商品只保存任务', ok: selectedTask?.mode === 'single_save' },
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
