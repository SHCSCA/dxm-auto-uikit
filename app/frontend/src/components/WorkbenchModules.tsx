import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { patchJson, postJson } from '../api'
import type {
  AcceptanceGap,
  AgentConsoleActionEvent,
  AgentConsoleSession,
  ConfigPreview,
  ConfigPreviewGroup,
  DeliveryWorkspace,
  DxmReferenceTemplateSection,
  Evidence,
  EvidencePoint,
  ExceptionItem,
  FinalDeliveryCheckSummary,
  LogItem,
  Product,
  RealTaskCreateRequest,
  RegressionGate,
  Report,
  RuntimeLogResponse,
  RuntimeLogItem,
  RuntimeLogSource,
  RuntimeStatus,
  RuntimeControlAction,
  RunStep,
  Task,
  Template,
} from '../types'
import { evidenceGrade, humanLevel, humanTaskStatus, referenceSectionLabels, toArtifactUrl } from '../workspace'

type CommonProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
}

type ConfigCenterProps = CommonProps & {
  configPreview: ConfigPreview | null
  configPreviewLoading: boolean
  onConfigSaved: () => void | Promise<void>
}

type GuideCenterProps = CommonProps & {
  configPreview: ConfigPreview | null
  runtimeStatus: RuntimeStatus | null
  onOpenDxmLogin: () => void
  onStartTask: () => void
  onShowConfig: () => void
  onShowTasks: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
  onShowReports: () => void
  onShowExceptions: () => void
}

const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])

const realWriteReleasePrerequisites = [
  {
    title: 'L2 双目标真实只读通过',
    detail: 'data_acquisition 与 draft_box 必须使用同一 run-id；无写请求、非只读请求、禁用 URL、WebSocket 或登录态异常。',
  },
  {
    title: 'allowlist 只能来自人工评审',
    detail: '不能用 allowlist 模板替代 L2 通过；批准后仍要改代码/配置并复跑同一批真实 L2。',
  },
  {
    title: '人工批准 L3 金丝雀',
    detail: '只有 L2 双目标 passed 后，才允许服务端批准单商品 save-only 金丝雀。',
  },
  {
    title: 'L3 证据补齐后再更新结论',
    detail: '保存成功、未发布证明、截图和 network/HAR 必须齐全，才能把真实写入从 BLOCKED 改为 READY。',
  },
]

type TaskCenterProps = CommonProps & {
  configPreview: ConfigPreview | null
  configPreviewLoading: boolean
  busy: boolean
  demoEnabled: boolean
  onSelectTask: (taskId: number) => void
  onCreateRealTask: (request: RealTaskCreateRequest) => void | Promise<void>
  onBootstrapDemo: () => void
  onStartTask: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

type ExecutionConsoleProps = CommonProps & {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  runtimeLogs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  runtimeLogSource: RuntimeLogSource
  runtimeLogError: string | null
  runtimeLogLevel: 'all' | 'info' | 'warning' | 'error'
  runtimeLogQuery: string
  busy: boolean
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
  onRuntimeLogLevelChange: (level: 'all' | 'info' | 'warning' | 'error') => void
  onRuntimeLogQueryChange: (query: string) => void
  onStartAgentConsole: () => void
  onOpenDxmLogin: () => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onRequestAgentConsoleTakeover: () => void
  onReleaseAgentConsoleTakeover: () => void
  onRuntimeControl: (action: RuntimeControlAction) => void
  onShowTasks: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

export function Dashboard({ workspace, selectedTask }: CommonProps) {
  const totalJobs = workspace.tasks.reduce((sum, task) => sum + task.total_jobs, 0)
  const completedJobs = workspace.tasks.reduce((sum, task) => sum + task.completed_jobs, 0)
  const failedJobs = workspace.tasks.reduce((sum, task) => sum + task.failed_jobs, 0)
  const realWriteExpectedBlocked = isRealWriteExpectedBlocked(workspace)
  const presentedAcceptanceGaps = presentAcceptanceGaps(workspace.acceptanceGaps, realWriteExpectedBlocked)
  const blockerCount = presentedAcceptanceGaps.filter((gap) => gap.severity === 'blocker').length
  const l3PostEvidenceCount = presentedAcceptanceGaps.filter((gap) => l3PostEvidenceGapIds.has(gap.id)).length
  const grade = workspace.evidenceGrade?.grade ?? 'C'
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const realWriteReady = !realWriteExpectedBlocked
  const nextAction = !selectedTask
    ? '去任务中心准备数据'
    : l2Gate?.status !== 'passed'
      ? '查看 L2 门禁'
      : requiresManualApproval(selectedTask)
        ? '等待人工批准'
        : '打开执行控制台'

  return (
    <section className="dashboard-grid" aria-label="Dashboard">
      <div className="hero-panel">
        <div>
          <h1>DXM 自动化工作台</h1>
          <p>任务编排、L2 真实只读证据、L3 批准和 save-only runner 集中在这里；发布入口始终隔离。</p>
          <p className="hero-panel__note">真实写入只允许在 L2 passed 和 L3 人工批准后由受控 runner 执行。</p>
          <div className="hero-panel__outcomes" aria-label="验收结论">
            <span><strong>自动化工作台</strong><b>可交付</b></span>
            <span><strong>真实 DXM 写入</strong><b>{realWriteReady ? '受控 READY' : 'L3 受控'}</b></span>
            <span><strong>{realWriteReady ? '当前范围' : '下一步'}</strong><b>{realWriteReady ? 'single_save READY' : '单商品金丝雀'}</b></span>
          </div>
        </div>
        <div className="hero-panel__status">
          <span>当前批次</span>
          <strong>{selectedTask ? selectedTask.name : '待创建保存核验批次'}</strong>
          <small>{nextAction} / {selectedTask ? humanTaskStatus(selectedTask.status) : '请先创建真实任务'}</small>
        </div>
      </div>

      <div className="module-card span-2">
        <ModuleHead title="操作引导" meta="按顺序完成" />
        <OperationGuide workspace={workspace} selectedTask={selectedTask} />
      </div>

      <div className="module-card">
        <ModuleHead title="当前状态" meta={realWriteReady ? 'single_save READY' : '等待门禁'} />
        <div className="check-list">
          <CheckRow label="真实店铺/商品已读取" ok={workspace.stores.length > 0 && workspace.products.length > 0} />
          <CheckRow label="L2 真实只读通过" ok={l2Gate?.status === 'passed'} />
          <CheckRow label="仅 single_save 放行" ok />
          <CheckRow label="发布入口隔离" ok={workspace.publishGuardState?.publish_allowed === false || workspace.publishGuardState?.safe === true} />
        </div>
      </div>

      <MetricCard label="商品数" value={workspace.products.length} detail="待执行商品队列" tone="blue" />
      <MetricCard label="任务进度" value={`${completedJobs}/${Math.max(totalJobs, 1)}`} detail={`失败 ${failedJobs} 项`} tone="green" />
      <MetricCard label="证据等级" value={grade} detail={`缺口 ${blockerCount} 项${l3PostEvidenceCount ? ` / L3 后置 ${l3PostEvidenceCount} 项` : ''}`} tone={grade === 'A' ? 'green' : grade === 'B' ? 'yellow' : 'red'} />

      <details className="module-card span-3 disclosure-card">
        <summary>查看验收门禁和证据缺口</summary>
        <RegressionGateGrid gates={workspace.regressionGates} />
        <GapList gaps={presentedAcceptanceGaps.slice(0, 4)} />
      </details>
    </section>
  )
}

function OperationGuide({ workspace, selectedTask }: CommonProps) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const steps = [
    { label: '配置店铺、类目、图片和半托管参数', ok: workspace.stores.length > 0 && workspace.products.length > 0 },
    { label: '选择真实 single_save 任务', ok: selectedTask?.mode === 'single_save' },
    { label: '确认 L2 真实只读通过', ok: l2Gate?.status === 'passed' },
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

export function GuideCenter({
  workspace,
  selectedTask,
  configPreview,
  runtimeStatus,
  onOpenDxmLogin,
  onStartTask,
  onShowConfig,
  onShowTasks,
  onShowConsole,
  onShowEvidence,
  onShowReports,
  onShowExceptions,
}: GuideCenterProps) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const backendOk = runtimeStatus?.backend?.status === 'ok'
  const frontendOk = runtimeStatus?.frontend?.status === 'ok'
  const agentReady = runtimeStatus?.agentConsole?.status === 'running' || runtimeStatus?.agentConsole?.status === 'idle'
  const dxmLoggedIn = runtimeStatus?.dxmLogin?.status === 'login_success' || runtimeStatus?.dxmLogin?.status === 'logged_in'
  const hasStore = workspace.stores.length > 0
  const hasProducts = workspace.products.length > 0
  const configOk = Boolean(configPreview?.ok)
  const selectedSingleSave = selectedTask?.mode === 'single_save'
  const l2Passed = l2Gate?.status === 'passed'
  const canRequestSave = selectedSingleSave && configOk && l2Passed
  const reportReady = workspace.reports.some((report) => report.task_id === selectedTask?.id) || Boolean(workspace.reportSummary?.latest_report)
  const hasExceptions = workspace.exceptions.length > 0
  const guideSteps = [
    {
      id: 'services',
      title: '确认服务运行',
      done: backendOk && frontendOk,
      detail: backendOk && frontendOk ? '后端和前端均可访问。' : '先确认启动器和端口状态。',
      reason: backendOk && frontendOk ? '' : `后端 ${runtimeStatus?.backend?.status ?? '未知'} / 前端 ${runtimeStatus?.frontend?.status ?? '未知'}`,
      action: '查看运行日志',
      onAction: onShowConsole,
    },
    {
      id: 'browser-login',
      title: '打开真实 DXM 浏览器并确认登录',
      done: Boolean(agentReady && dxmLoggedIn),
      detail: dxmLoggedIn ? '已检测到 DXM 登录态。' : '需要打开真实店小秘登录页并完成登录；账号密码只用于本次真实店小秘登录。',
      reason: dxmLoggedIn ? '' : `DXM 登录状态：${runtimeStatus?.dxmLogin?.status ?? '未知'}`,
      action: '打开登录页',
      onAction: onOpenDxmLogin,
      secondaryAction: '查看控制台',
      onSecondaryAction: onShowConsole,
    },
    {
      id: 'store',
      title: '选择店铺',
      done: hasStore,
      detail: hasStore ? `当前店铺：${workspace.stores[0]?.name}` : '还没有可用店铺。',
      reason: hasStore ? '' : '请先创建或连接店铺。',
      action: '去配置中心',
      onAction: onShowConfig,
    },
    {
      id: 'products',
      title: '导入商品',
      done: hasProducts,
      detail: hasProducts ? `商品队列 ${workspace.products.length} 个。` : '还没有待处理商品。',
      reason: hasProducts ? '' : '请先导入真实商品或创建任务商品。',
      action: '去任务中心',
      onAction: onShowTasks,
    },
    {
      id: 'config',
      title: '填写编辑页配置',
      done: configOk,
      detail: configOk ? '当前任务配置完整。' : `待补：${configPreview?.missing.slice(0, 4).join('、') || 'DXM 编辑页必填项'}`,
      reason: configOk ? '' : `${configPreview?.missing.length ?? 0} 个配置项待补齐。`,
      action: '补齐配置',
      onAction: onShowConfig,
    },
    {
      id: 'l2',
      title: '运行只读检查',
      done: l2Passed,
      detail: l2Passed ? '真实页面只读检查已通过。' : l2Gate?.detail ?? '只读检查还未通过。',
      reason: l2Passed ? '' : `L2：${l2Gate?.status ?? 'not_run'}`,
      action: '查看任务门禁',
      onAction: onShowTasks,
    },
    {
      id: 'approval',
      title: '人工确认真实保存',
      done: Boolean(l3Gate?.status === 'passed' || selectedTask?.status === 'running' || selectedTask?.status === 'completed'),
      detail: canRequestSave ? '可以申请只保存一个商品，仍不会发布。' : '配置、任务模式和只读检查通过后才可申请。',
      reason: canRequestSave ? '' : `任务 ${selectedTask ? selectedTask.mode : '未选择'} / 配置 ${configOk ? '完整' : '未完整'} / L2 ${l2Gate?.status ?? 'not_run'}`,
      action: canRequestSave ? '申请并启动 single_save' : '选择任务',
      onAction: canRequestSave ? onStartTask : onShowTasks,
    },
    {
      id: 'observe',
      title: '观察实时浏览器执行',
      done: Boolean(runtimeStatus?.agentConsole?.active || selectedTask?.status === 'completed'),
      detail: runtimeStatus?.agentConsole?.active ? '自动浏览器正在运行。' : '启动后在执行控制台观察页面、步骤和日志。',
      reason: runtimeStatus?.agentConsole?.active || selectedTask?.status === 'completed' ? '' : '等待任务启动后同步真实浏览器画面。',
      action: '进入控制台',
      onAction: onShowConsole,
    },
    {
      id: 'reports',
      title: '查看报告与证据',
      done: reportReady,
      detail: reportReady ? '已有报告或结构化保存结果。' : '保存任务完成后检查未发布证明和网络响应。',
      reason: reportReady ? '' : '报告、保存回包或未发布证明尚未齐全。',
      action: '查看报告',
      onAction: onShowReports,
      secondaryAction: '查看证据中心',
      onSecondaryAction: onShowEvidence,
    },
  ].map((step, index, steps) => {
    const priorDone = steps.slice(0, index).every((item) => item.done)
    const status = step.done ? 'done' : priorDone ? 'current' : 'blocked'
    return { ...step, status }
  })
  const completedSteps = guideSteps.filter((step) => step.done).length
  const nextGuideStep = guideSteps.find((step) => !step.done) ?? guideSteps[guideSteps.length - 1]

  return (
    <section className="module-layout" aria-label="操作引导">
      <div className="module-card span-3 guide-hero">
        <ModuleHead title="操作引导" meta="按当前状态推进" />
        <div className="guide-hero__body">
          <div>
            <h1>从启动到真实保存</h1>
            <p>先处理当前最靠前的一步；完整流程放在下方详情里，避免你一进来就被所有状态淹没。</p>
          </div>
          <span className={`status-pill ${canRequestSave ? 'ok' : 'warn'}`}>
            {canRequestSave ? '可申请 single_save' : '等待前置条件'}
          </span>
        </div>
      </div>

      <div className="module-card span-2 guide-next-card">
        <ModuleHead title="现在只做这一步" meta={`${completedSteps}/${guideSteps.length} 完成`} />
        <article className={`guide-step guide-step--primary is-${nextGuideStep.status}`} data-guide-step={nextGuideStep.id}>
          <span>{Math.max(guideSteps.indexOf(nextGuideStep) + 1, 1)}</span>
          <div>
            <strong>{nextGuideStep.title}</strong>
            <small>{nextGuideStep.detail}</small>
            {nextGuideStep.reason && <em>原因：{nextGuideStep.reason}</em>}
          </div>
          <div className="guide-step__actions">
            <button className="button button--primary" type="button" onClick={nextGuideStep.onAction}>
              {nextGuideStep.action}
            </button>
            {nextGuideStep.secondaryAction && (
              <button className="button button--quiet" type="button" onClick={nextGuideStep.onSecondaryAction}>
                {nextGuideStep.secondaryAction}
              </button>
            )}
          </div>
        </article>
        <details className="inline-disclosure guide-full-path">
          <summary>查看完整 9 步流程</summary>
          <div className="guide-step-list">
            {guideSteps.map((step, index) => (
              <article key={step.title} className={`guide-step is-${step.status}`} data-guide-step={step.id}>
                <span>{index + 1}</span>
                <div>
                  <strong>{step.title}</strong>
                  <small>{step.detail}</small>
                  {step.reason && <em>原因：{step.reason}</em>}
                </div>
                <div className="guide-step__actions">
                  <button className="button button--quiet" type="button" onClick={step.onAction}>
                    {step.action}
                  </button>
                  {step.secondaryAction && (
                    <button className="button button--quiet" type="button" onClick={step.onSecondaryAction}>
                      {step.secondaryAction}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </details>
      </div>
      <div className="module-card">
        <ModuleHead title="前置条件" meta="简要状态" />
        <div className="check-list">
          <CheckRow label="服务运行" ok={backendOk && frontendOk} />
          <CheckRow label="DXM 登录" ok={dxmLoggedIn} />
          <CheckRow label="配置完整" ok={configOk} />
          <CheckRow label="L2 通过" ok={l2Passed} />
          <CheckRow label="single_save 任务" ok={selectedSingleSave} />
        </div>
        {hasExceptions && (
          <div className="guide-exception-callout">
            <strong>发现异常 {workspace.exceptions.length} 项</strong>
            <small>先处理异常再继续真实保存。</small>
            <button className="button button--secondary" type="button" onClick={onShowExceptions}>查看异常池</button>
          </div>
        )}
      </div>
    </section>
  )
}

function RegressionGateGrid({ gates }: { gates: RegressionGate[] }) {
  return (
    <div className="regression-gate-grid">
      {gates.map((gate) => (
        <div key={gate.level} className={`regression-gate ${gateStatusTone(gate.status)}`}>
          <div className="regression-gate__head">
            <strong>{gate.level}</strong>
            <span className={`status-pill ${gateStatusPill(gate.status)}`}>{humanGateStatus(gate.status)}</span>
          </div>
          <h3>{gate.title}</h3>
          <p>{gate.detail}</p>
          <div className="regression-gate__meta">
            <span>证据 {gate.evidenceLevel}</span>
            <span>{gate.requiresApproval ? '需批准' : '本地门禁'}</span>
          </div>
          {gate.command && <code>{gate.command}</code>}
        </div>
      ))}
    </div>
  )
}

type ConfigSectionCode =
  | 'taskBasic'
  | 'category'
  | 'sku'
  | 'pricing'
  | 'image'
  | 'logistics'
  | 'compliance'
  | 'semiManaged'
  | 'dxmReference'
type EditableConfigField = {
  name: string
  label: string
  placeholder: string
  previewPath?: string
  usage?: 'direct' | 'template' | 'advisory'
  valueKind?: 'text' | 'list'
}
type EditableConfigSection = {
  code: ConfigSectionCode
  templateType: string
  previewSection: string
  title: string
  detail: string
  fields: EditableConfigField[]
}

const editableConfigSections: EditableConfigSection[] = [
  {
    code: 'taskBasic',
    templateType: 'task_basic',
    previewSection: 'task_basic',
    title: '店铺与任务基础',
    detail: '控制当前任务绑定店铺、执行模式、类目和认领标记。',
    fields: [
      { name: 'store_name', label: '店铺', placeholder: '例如：Dang Kang', usage: 'direct' },
      { name: 'execution_mode', label: '执行模式', placeholder: 'probe / single_save', usage: 'direct' },
      { name: 'category_name', label: '绑定类目', placeholder: '例如：立牌类谷子', usage: 'direct' },
      { name: 'claim_mark', label: '认领标记', placeholder: '用于区分 DXM 草稿箱记录', usage: 'direct' },
    ],
  },
  {
    code: 'category',
    templateType: 'category',
    previewSection: 'category',
    title: '类目与标题',
    detail: '控制 DXM 类目匹配和商品标题基础信息。',
    fields: [
      { name: 'category_name', label: '目标类目', placeholder: '例如：立牌类谷子', usage: 'direct' },
      { name: 'category_keyword', label: '类目关键词', placeholder: '用于 DXM 搜索类目', usage: 'direct' },
      { name: 'template_category_id', label: 'DXM 类目 ID', placeholder: '店小秘编辑页类目 ID', usage: 'advisory' },
      { name: 'title_override', label: '标题覆盖', placeholder: '留空则使用商品标题', usage: 'advisory' },
      { name: 'title_cleaning_rule', label: '标题清洗规则', placeholder: '删除平台词 / 保留英文', usage: 'advisory' },
      { name: 'title_strategy', label: '标题策略', placeholder: '保留原始标题 / 清洗关键词', usage: 'advisory' },
    ],
  },
  {
    code: 'sku',
    templateType: 'sku',
    previewSection: 'sku',
    title: 'SKU / 价格 / 库存',
    detail: 'SKU 规则、库存和变种属性策略，价格细项在下一分区微调。',
    fields: [
      { name: 'sku_code', label: 'SKU 编码', placeholder: 'SKU-001', usage: 'direct' },
      { name: 'stock', label: '库存', placeholder: '100', usage: 'direct' },
      { name: 'jit_stock', label: 'JIT 库存', placeholder: '100', usage: 'direct' },
      { name: 'normal_stock', label: '普通库存', placeholder: '100', usage: 'advisory' },
      { name: 'template_sku_rule', label: 'SKU 规则', placeholder: '使用商品 SKU / 自动生成', usage: 'advisory' },
      { name: 'sku_attribute_strategy', label: 'SKU 属性策略', placeholder: '按 DXM 默认属性映射', usage: 'advisory' },
      { name: 'variant_strategy', label: '变种策略', placeholder: '按商品变种 / 单规格', usage: 'advisory' },
    ],
  },
  {
    code: 'pricing',
    templateType: 'pricing',
    previewSection: 'pricing',
    title: '价格策略',
    detail: '商品价、供货价和价格处理策略。',
    fields: [
      { name: 'product_price', label: '商品价', placeholder: '7.99', usage: 'direct' },
      { name: 'supply_price', label: '供货价', placeholder: '5.20', usage: 'direct' },
      { name: 'price_source', label: '价格来源', placeholder: '商品 payload / 固定模板', usage: 'advisory' },
      { name: 'price_multiplier', label: '价格倍率', placeholder: '1.15', usage: 'advisory' },
      { name: 'fixed_price', label: '固定价格', placeholder: '7.99', usage: 'advisory' },
      { name: 'price_strategy', label: '价格策略', placeholder: '按模板固定价 / 商品导入价', usage: 'advisory' },
    ],
  },
  {
    code: 'image',
    templateType: 'image',
    previewSection: 'image',
    title: '图片与素材',
    detail: '主图、欧盟外包装图和营销图策略。',
    fields: [
      { name: 'eu_outer_package_filename', label: 'EU 外包装图', placeholder: 'outer-package.jpg', usage: 'direct' },
      { name: 'marketing_images_strategy', label: '营销图策略', placeholder: '使用商品图补齐 3:4', usage: 'direct' },
      { name: 'main_image_strategy', label: '主图策略', placeholder: '保留 800x800 合规主图', usage: 'advisory' },
      { name: 'fallback_strategy', label: '缺图回退策略', placeholder: '使用 EU 外包装图补齐', usage: 'advisory' },
      { name: 'invalid_image_strategy', label: '无效图处理', placeholder: '删除 0x0 / 保留合规图', usage: 'advisory' },
      { name: 'local_asset_path', label: '本地素材目录', placeholder: 'C:\\path\\to\\assets', usage: 'advisory' },
    ],
  },
  {
    code: 'logistics',
    templateType: 'logistics',
    previewSection: 'logistics',
    title: '包装物流',
    detail: '重量、尺寸和物流属性会直接影响编辑页填写。',
    fields: [
      { name: 'weight', label: '重量 kg', placeholder: '0.03', usage: 'direct' },
      { name: 'length', label: '长 cm', placeholder: '10', usage: 'direct' },
      { name: 'width', label: '宽 cm', placeholder: '10', usage: 'direct' },
      { name: 'height', label: '高 cm', placeholder: '2', usage: 'direct' },
      { name: 'logistics_attribute', label: '物流属性', placeholder: '普货', usage: 'direct' },
      { name: 'freight_template', label: '运费模板', placeholder: '半托管运费模板', usage: 'template' },
      { name: 'service_template', label: '服务模板', placeholder: '无忧服务模板', usage: 'template' },
      { name: 'package_gross_weight', label: '包装毛重 kg', placeholder: '0.05', usage: 'advisory' },
    ],
  },
  {
    code: 'compliance',
    templateType: 'compliance',
    previewSection: 'compliance',
    title: '合规 / 海关',
    detail: '缺失合规字段时真实保存会被前置校验阻断。',
    fields: [
      { name: 'customs_name', label: '报关品名', placeholder: 'Acrylic stand', usage: 'direct' },
      { name: 'material', label: '材质', placeholder: 'Acrylic', usage: 'advisory' },
      { name: 'purpose', label: '用途', placeholder: 'Decoration', usage: 'advisory' },
      { name: 'brand', label: '品牌', placeholder: '无品牌 / 品牌名', usage: 'advisory' },
      { name: 'statement', label: '合规声明', placeholder: '符合平台合规要求', usage: 'advisory' },
    ],
  },
  {
    code: 'semiManaged',
    templateType: 'semi_managed',
    previewSection: 'semi_managed',
    title: '半托管',
    detail: '供货价、库存、原包装和条码策略。',
    fields: [
      { name: 'product_price', label: '商品价', placeholder: '7.99', usage: 'direct' },
      { name: 'jit_stock', label: 'JIT 库存', placeholder: '100', usage: 'direct' },
      { name: 'is_original_box', label: '是否原包装', placeholder: '否', usage: 'direct' },
      { name: 'length', label: '半托管长 cm', placeholder: '10', usage: 'direct' },
      { name: 'width', label: '半托管宽 cm', placeholder: '10', usage: 'direct' },
      { name: 'height', label: '半托管高 cm', placeholder: '2', usage: 'direct' },
      { name: 'goods_code_strategy', label: '货号策略', placeholder: '使用 SKU', usage: 'advisory' },
      { name: 'barcode_strategy', label: '条码策略', placeholder: '自动生成/留空', usage: 'advisory' },
    ],
  },
  {
    code: 'dxmReference',
    templateType: 'dxm_reference',
    previewSection: 'dxm_reference',
    title: '店小秘引用模板',
    detail: '店小秘编辑页 8 段下拉模板引用，执行时按 resolved 结果匹配真实模板；尺码模板按类目属性规则处理。',
    fields: [
      { name: 'dxm_reference_templates.attribute_info.names', previewPath: 'dxm_reference_templates_resolved.attribute_info.names', label: '属性信息模板', placeholder: '每行一个属性信息模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.description.names', previewPath: 'dxm_reference_templates_resolved.description.names', label: '描述模板', placeholder: '每行一个描述模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.freight.names', previewPath: 'dxm_reference_templates_resolved.freight.names', label: '运费模板', placeholder: '每行一个运费模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.service.names', previewPath: 'dxm_reference_templates_resolved.service.names', label: '服务模板', placeholder: '每行一个服务模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.eu_responsible.names', previewPath: 'dxm_reference_templates_resolved.eu_responsible.names', label: '欧盟责任人', placeholder: '每行一个欧盟责任人', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.manufacturer.names', previewPath: 'dxm_reference_templates_resolved.manufacturer.names', label: '制造商', placeholder: '每行一个制造商', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.compliance.names', previewPath: 'dxm_reference_templates_resolved.compliance.names', label: '合规模板', placeholder: '每行一个合规模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.semi_managed.names', previewPath: 'dxm_reference_templates_resolved.semi_managed.names', label: '半托管模板', placeholder: '每行一个半托管模板', usage: 'template', valueKind: 'list' },
    ],
  },
]

function getNestedConfigValue(payload: Record<string, unknown>, path: string) {
  let current: unknown = payload
  for (const part of path.split('.')) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return current
}

function setNestedConfigValue(target: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split('.')
  let cursor = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value
      return
    }
    const next = cursor[part]
    if (!next || typeof next !== 'object' || Array.isArray(next)) {
      cursor[part] = {}
    }
    cursor = cursor[part] as Record<string, unknown>
  })
  return target
}

function parseEditableConfigFieldValue(field: EditableConfigField, rawValue: string): unknown {
  if (field.valueKind !== 'list') return rawValue
  return rawValue
    .replace(/\r\n/g, '\n')
    .replace(/[，,；;]/g, '\n')
    .replace(/\s\/\s/g, '\n')
    .split('\n')
    .map((item) => item.trim())
    .filter((item, index, items) => item && items.indexOf(item) === index)
}

function editableConfigDraftValue(value: unknown, field: EditableConfigField) {
  if (value === undefined || value === null) return ''
  if (Array.isArray(value)) return field.valueKind === 'list' ? value.join('\n') : value.join(' / ')
  return String(value)
}

function buildEditableConfigDraft(templates: Template[], configPreview: ConfigPreview | null) {
  const draft = {} as Record<ConfigSectionCode, Record<string, string>>
  editableConfigSections.forEach((section) => {
    const template = templates.find((item) => item.template_type === section.templateType)
    const payload = template?.payload ?? {}
    const preview = configPreview?.fieldGroups.find((group) => group.section === section.previewSection)
    draft[section.code] = Object.fromEntries(section.fields.map((field) => [
      field.name,
      (() => {
        const previewField = fieldPreview(preview, field)
        if (previewField && previewField.value !== undefined && previewField.value !== null && String(previewField.value).trim() !== '') {
          return editableConfigDraftValue(previewField.value, field)
        }
        const payloadValue = getNestedConfigValue(payload, field.name) ?? payload[field.name]
        return editableConfigDraftValue(payloadValue, field)
      })(),
    ]))
  })
  return draft
}

function ConfigReadinessPanel({
  configPreview,
  selectedTask,
  incompleteGroups,
}: {
  configPreview: ConfigPreview | null
  selectedTask: Task | null
  incompleteGroups: ConfigPreviewGroup[]
}) {
  if (!selectedTask) {
    return <EmptyState title="先选择任务" detail="选择 single_save 任务后，这里会显示执行前配置是否完整。" />
  }
  if (!configPreview) {
    return <div className="config-readiness is-warn"><strong>配置预检未加载</strong><span>请刷新工作台，或确认后端 /api/config/preview 可用。</span></div>
  }
  const missing = configPreview.missing.slice(0, 8)
  return (
    <div className={`config-readiness ${configPreview.ok ? 'is-ok' : 'is-warn'}`}>
      <div>
        <strong>{configPreview.ok ? '配置可用于当前任务' : '配置还不能启动真实保存'}</strong>
        <span>任务 #{configPreview.taskId} / {configPreview.mode ?? '未识别模式'} / {configPreview.ok ? '可进入 L2/L3 判断' : `待补 ${incompleteGroups.length || missing.length} 项`}</span>
      </div>
      {missing.length > 0 && (
        <div className="missing-strip">
          {missing.map((item) => <span key={item}>{item}</span>)}
        </div>
      )}
    </div>
  )
}

function NextRequiredConfigFields({
  section,
  preview,
  configOk,
  loading,
}: {
  section: EditableConfigSection
  preview: ConfigPreviewGroup | undefined
  configOk: boolean
  loading: boolean
}) {
  const missingFields = (preview?.fields ?? [])
    .filter((field) => field.missing)
    .slice(0, 5)
  const fallbackFields = section.fields.slice(0, 4).map((field) => ({
    label: field.label,
    path: field.previewPath ?? field.name,
    source: '等待预检',
  }))
  const fields = missingFields.length
    ? missingFields.map((field) => ({ label: field.label, path: field.path, source: field.source }))
    : fallbackFields

  return (
    <div className={`next-required-fields ${configOk ? 'is-ok' : 'is-warn'}`} aria-label="下一步必填字段">
      <div>
        <strong>{configOk ? '当前任务配置已就绪' : `下一步必填字段：${section.title}`}</strong>
        <span>{configOk ? '需要微调时再展开下方分区。' : '只显示当前最需要处理的字段；完整字段放在下方分区。'}</span>
      </div>
      <div className="next-required-fields__list">
        {loading ? (
          <span>正在读取预检结果...</span>
        ) : fields.map((field) => (
          <span key={`${field.path}:${field.label}`}>
            <b>{field.label}</b>
            <code>{field.path}</code>
            {!configOk && <small>{field.source}</small>}
          </span>
        ))}
      </div>
    </div>
  )
}

function sourceBadgeText(source: string) {
  if (source.startsWith('任务：')) return '任务覆盖'
  if (source.startsWith('商品：')) return '商品 payload'
  if (source.startsWith('模板：')) return '店铺/类目模板'
  if (source === '系统默认值') return '系统默认值'
  return source || '未设置'
}

function formatPreviewValue(value: unknown) {
  if (value === undefined || value === null || String(value).trim() === '') return '空'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function EffectiveValuePreview({
  configPreview,
  sourcePriorityLabels,
  title,
}: {
  configPreview: ConfigPreview | null
  sourcePriorityLabels: string[]
  title: string
}) {
  const fields = (configPreview?.fieldGroups ?? [])
    .flatMap((group) => group.fields.map((field) => ({ ...field, groupLabel: group.label })))
    .filter((field) => field.required || field.value !== undefined)
    .slice(0, 14)

  return (
    <div className="module-card span-3 effective-value-preview">
      <ModuleHead title={title} meta={configPreview?.taskId ? `任务 #${configPreview.taskId}` : '等待任务'} />
      <div className="source-legend" aria-label="取值优先级">
        {sourcePriorityLabels.map((label) => <span key={label}>{label}</span>)}
      </div>
      {!configPreview ? (
        <EmptyState title="暂无预览" detail="选择任务后，会展示执行器最终写入 DXM 编辑页的字段值。" />
      ) : (
        <div className="effective-value-grid">
          {fields.map((field) => (
            <div className={field.missing ? 'effective-value-item is-missing' : 'effective-value-item'} key={`${field.path}:${field.groupLabel}`}>
              <span>{field.groupLabel}</span>
              <strong>{field.label}</strong>
              <code>{formatPreviewValue(field.value)}</code>
              <small>{sourceBadgeText(field.source)} / {field.path}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function previewSummary(section: EditableConfigSection, preview?: ConfigPreviewGroup) {
  if (!preview) return `${section.detail} / 等待预检`
  if (!preview.templatePresent) return `${section.detail} / 未保存模板`
  if (!preview.complete) return `${section.detail} / 缺 ${preview.missing.length || preview.fields.filter((field) => field.missing).length} 项`
  return `${section.detail} / 执行时会按右侧来源取值`
}

function fieldPreview(preview: ConfigPreviewGroup | undefined, field: EditableConfigField) {
  return preview?.fields.find((item) => item.path === (field.previewPath ?? field.name) || item.name === field.name)
}

function fieldSourceText(field: ReturnType<typeof fieldPreview>) {
  if (!field) return '来源：等待预检'
  if (field.missing) return `缺失：${field.path}`
  const value = field.value === undefined || field.value === null || String(field.value).trim() === '' ? '空' : String(field.value)
  return `当前值：${value} / 来源：${field.source}`
}

function fieldUsageLabel(usage?: EditableConfigField['usage']) {
  if (usage === 'direct') return '直接填入 DXM'
  if (usage === 'template') return '模板匹配'
  if (usage === 'advisory') return '策略/备用'
  return ''
}

export function ConfigCenter({ workspace, selectedTask, configPreview, configPreviewLoading, onConfigSaved }: ConfigCenterProps) {
  const product = workspace.products[0]
  const enabledTemplates = workspace.templates.filter((item) => item.is_enabled)
  const templateResults = workspace.templateResolution?.dxm_reference_template_results ?? {}
  const hasStores = workspace.stores.length > 0
  const hasProducts = workspace.products.length > 0
  const previewGroups = new Map((configPreview?.fieldGroups ?? []).map((group) => [group.section, group]))
  const incompleteGroups = (configPreview?.fieldGroups ?? []).filter((group) => group.required && !group.complete)
  const initialConfigDraft = useMemo(() => buildEditableConfigDraft(workspace.templates, configPreview), [workspace.templates, configPreview])
  const [configDraft, setConfigDraft] = useState(initialConfigDraft)
  const [savingSection, setSavingSection] = useState<string | null>(null)
  const [configMessage, setConfigMessage] = useState<string | null>(null)
  const sectionsWithPreview = editableConfigSections.map((section) => ({
    section,
    preview: previewGroups.get(section.previewSection),
  }))
  const sectionsNeedingAttention = sectionsWithPreview.filter(({ preview }) => preview && (!preview.complete || !preview.templatePresent))
  const sectionsReady = sectionsWithPreview.filter(({ preview }) => !(preview && (!preview.complete || !preview.templatePresent)))
  const nextConfigSection = sectionsNeedingAttention[0]?.section ?? editableConfigSections[0]
  const nextConfigPreview = sectionsNeedingAttention[0]?.preview ?? previewGroups.get(nextConfigSection.previewSection)
  const readySectionCount = sectionsReady.length
  const configCoverageLabels = ['店铺与任务基础', '类目与标题', 'SKU / 价格 / 库存', '图片与素材', '包装物流', '合规 / 海关', '半托管', '店小秘引用模板']
  const effectivePreviewTitle = '本次任务实际取值预览'
  const sourcePriorityLabels = ['任务覆盖', '商品 payload', '店铺/类目模板', '系统默认值']
  const fieldUsageLegend = ['直接填入 DXM', '模板匹配', '策略/备用']
  const configCoverageFieldIds = [
    'dxm_reference_templates.attribute_info.names',
    'dxm_reference_templates.description.names',
    'dxm_reference_templates.freight.names',
    'dxm_reference_templates.service.names',
    'dxm_reference_templates.eu_responsible.names',
    'dxm_reference_templates.manufacturer.names',
    'dxm_reference_templates.compliance.names',
    'dxm_reference_templates.semi_managed.names',
    '尺码模板',
    'price_multiplier',
    'local_asset_path',
    'brand',
  ]

  useEffect(() => {
    setConfigDraft(initialConfigDraft)
  }, [initialConfigDraft])

  function updateConfigField(sectionCode: ConfigSectionCode, fieldName: string, value: string) {
    setConfigDraft((current) => ({
      ...current,
      [sectionCode]: {
        ...(current[sectionCode] ?? {}),
        [fieldName]: value,
      },
    }))
  }

  async function saveConfigSection(section: EditableConfigSection, scope: 'template' | 'task' = 'template') {
    setSavingSection(`${scope}:${section.code}`)
    setConfigMessage(null)
    try {
      const payload = section.fields.reduce<Record<string, unknown>>((acc, field) => {
        const rawValue = configDraft[section.code]?.[field.name] ?? ''
        setNestedConfigValue(acc, field.name, parseEditableConfigFieldValue(field, rawValue))
        return acc
      }, {})
      if (scope === 'task') {
        if (!selectedTask) throw new Error('请先选择任务')
        await patchJson<Task>(`/api/tasks/${selectedTask.id}/config-overrides`, {
          section: section.templateType,
          values: payload,
        })
        setConfigMessage(`${section.title} 已保存为本次任务覆盖，当前任务会优先使用这些值。`)
        await onConfigSaved()
        return
      }
      const existing = workspace.templates.find((template) => template.template_type === section.templateType)
      const body = {
        template_type: section.templateType,
        template_name: section.title,
        binding_scope: workspace.stores[0]?.name ?? '全局默认',
        payload,
        is_enabled: true,
      }
      if (existing) {
        await patchJson<Template>(`/api/templates/${existing.id}`, body)
      } else {
        await postJson<Template>('/api/templates', body)
      }
      setConfigMessage(`${section.title} 已保存为店铺/类目模板，后续任务会按该模板取值。`)
      await onConfigSaved()
    } catch (error) {
      setConfigMessage(error instanceof Error ? error.message : `${section.title} 保存失败`)
    } finally {
      setSavingSection(null)
    }
  }

  return (
    <section className="module-layout" aria-label="配置中心">
      <div className="module-card span-3 config-focus-card">
        <ModuleHead title="配置中心" meta={configPreviewLoading ? '正在预检' : `${enabledTemplates.length} 个启用模板`} />
        <div className="config-focus-card__body">
          <div>
            <h1>{configPreview?.ok ? '当前任务配置已满足启动预检' : `先补：${nextConfigSection.title}`}</h1>
            <p>
              {configPreview?.ok
                ? '仍可展开下方分区微调本次任务，保存后执行器会按页面填写值取数。'
                : previewSummary(nextConfigSection, nextConfigPreview)}
            </p>
          </div>
          <div className="config-focus-card__status">
            <span className={`status-pill ${configPreview?.ok ? 'ok' : 'warn'}`}>
              {configPreview?.ok ? '可用于当前任务' : `${incompleteGroups.length || sectionsNeedingAttention.length} 个分区待补`}
            </span>
            <small>{selectedTask ? `当前任务 #${selectedTask.id}` : '先到任务中心选择任务后，可保存为本次任务覆盖。'}</small>
          </div>
        </div>
        {(!hasStores || !hasProducts) && (
          <EmptyState
            title="暂无真实店铺/商品配置"
            detail="当前未从接口读取到 stores/products，不展示 Dang Kang 或立牌类谷子默认值以免误判为已配置。"
          />
        )}
        <NextRequiredConfigFields
          section={nextConfigSection}
          preview={nextConfigPreview}
          configOk={Boolean(configPreview?.ok)}
          loading={configPreviewLoading}
        />
        <div className="config-coverage-strip" aria-label="店小秘编辑页分区" data-field-coverage={configCoverageFieldIds.join('|')}>
          {configCoverageLabels.map((label) => <span key={label}>{label}</span>)}
        </div>
        <div className="config-usage-legend" aria-label="字段用途">
          {fieldUsageLegend.map((label) => <span key={label}>{label}</span>)}
        </div>
        <details className="inline-disclosure config-context-summary">
          <summary>查看店铺、商品、图片与执行模式</summary>
          <div className="config-matrix">
            <ConfigItem label="店铺" value={workspace.stores[0]?.name ?? '未配置真实店铺'} hint={workspace.stores[0]?.platform ?? '等待 /api/stores 返回'} empty={!hasStores} />
            <ConfigItem label="类目" value={product?.category_name ?? '未绑定真实商品类目'} hint="用于匹配属性和模板范围" empty={!hasProducts} />
            <ConfigItem label="图片银行" value={product?.image?.eu_outer_package_filename ?? '未绑定真实外包装图'} hint="欧盟外包装/标签实拍图" empty={!hasProducts} />
            <ConfigItem label="执行模式" value="真实 single_save" hint="受控 runner 执行，只保存不发布" />
          </div>
          <ConfigReadinessPanel
            configPreview={configPreview}
            selectedTask={selectedTask}
            incompleteGroups={incompleteGroups}
          />
        </details>
      </div>

      <EffectiveValuePreview configPreview={configPreview} sourcePriorityLabels={sourcePriorityLabels} title={effectivePreviewTitle} />

      <div className="module-card span-3">
        <ModuleHead title="DXM 编辑页配置" meta="默认只展开待补分区" />
        {configMessage && <div className="config-save-message">{configMessage}</div>}
        <div className="editable-config-grid">
          {(sectionsNeedingAttention.length ? sectionsNeedingAttention : sectionsWithPreview).map(({ section, preview }, index) => {
            const openByDefault = sectionsNeedingAttention.length
              ? index === 0
              : section.code === nextConfigSection.code
            return (
              <EditableConfigSectionCard
                key={section.code}
                section={section}
                preview={preview}
                configDraft={configDraft}
                savingSection={savingSection}
                selectedTask={selectedTask}
                openByDefault={openByDefault}
                onFieldChange={updateConfigField}
                onSave={saveConfigSection}
              />
            )
          })}
        </div>
        {sectionsNeedingAttention.length > 0 && (
          <details className="inline-disclosure config-ready-sections">
            <summary>查看已就绪分区（{readySectionCount} 个）</summary>
            <div className="editable-config-grid editable-config-grid--compact">
              {sectionsReady.map(({ section, preview }) => (
                <EditableConfigSectionCard
                  key={section.code}
                  section={section}
                  preview={preview}
                  configDraft={configDraft}
                  savingSection={savingSection}
                  selectedTask={selectedTask}
                  openByDefault={false}
                  onFieldChange={updateConfigField}
                  onSave={saveConfigSection}
                />
              ))}
            </div>
          </details>
        )}
      </div>

      <details className="module-card span-3 disclosure-card">
        <summary>高级模板映射（{Object.keys(templateResults).length} 段已有执行结果）</summary>
        <ReferenceTemplateMap sections={workspace.dxmReferenceTemplates} />
      </details>

      <details className="module-card span-3 disclosure-card">
        <summary>模板清单（{workspace.templates.length} 条）</summary>
        <div className="table-wrap">
          <table>
            <caption>配置模板清单</caption>
            <thead>
              <tr>
                <th scope="col">类型</th>
                <th scope="col">模板名</th>
                <th scope="col">绑定范围</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>
              {workspace.templates.map((template) => (
                <TemplateRow key={template.id} template={template} />
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

function EditableConfigSectionCard({
  section,
  preview,
  configDraft,
  savingSection,
  selectedTask,
  openByDefault,
  onFieldChange,
  onSave,
}: {
  section: EditableConfigSection
  preview: ConfigPreviewGroup | undefined
  configDraft: Record<ConfigSectionCode, Record<string, string>>
  savingSection: string | null
  selectedTask: Task | null
  openByDefault: boolean
  onFieldChange: (sectionCode: ConfigSectionCode, fieldName: string, value: string) => void
  onSave: (section: EditableConfigSection, scope: 'template' | 'task') => void | Promise<void>
}) {
  return (
    <details className={`editable-config-section ${preview?.complete ? 'is-complete' : 'is-incomplete'}`} open={openByDefault}>
      <summary className="editable-config-section__head">
        <div>
          <strong>{section.title}</strong>
          <span>{previewSummary(section, preview)}</span>
        </div>
        <span className={`status-pill ${preview?.complete ? 'ok' : 'warn'}`}>{preview?.complete ? '已就绪' : '待补齐'}</span>
      </summary>
      <div className="editable-config-section__fields">
        {section.fields.map((field) => (
          <label key={field.name}>
            <span>
              {field.label}{fieldPreview(preview, field)?.required ? ' *' : ''}
              {field.usage && <em className={`field-usage field-usage--${field.usage}`}>{fieldUsageLabel(field.usage)}</em>}
            </span>
            {field.valueKind === 'list' ? (
              <textarea
                value={configDraft[section.code]?.[field.name] ?? ''}
                placeholder={field.placeholder}
                rows={3}
                onChange={(event) => onFieldChange(section.code, field.name, event.target.value)}
              />
            ) : (
              <input
                value={configDraft[section.code]?.[field.name] ?? ''}
                placeholder={field.placeholder}
                onChange={(event) => onFieldChange(section.code, field.name, event.target.value)}
              />
            )}
            {field.valueKind === 'list' && <small className="field-source">每行一个；会按顺序匹配店小秘模板。</small>}
            <small className={fieldPreview(preview, field)?.missing ? 'field-source is-missing' : 'field-source'}>
              {fieldSourceText(fieldPreview(preview, field))}
            </small>
          </label>
        ))}
      </div>
      {preview?.missing.length ? (
        <div className="missing-strip">
          {preview.missing.slice(0, 4).map((item) => <span key={item}>{item}</span>)}
        </div>
      ) : null}
      <div className="editable-config-section__actions">
        <button
          className="button button--secondary"
          type="button"
          onClick={() => void onSave(section, 'task')}
          disabled={!selectedTask || savingSection === `task:${section.code}`}
        >
          {savingSection === `task:${section.code}` ? '保存中...' : '仅本次任务使用'}
        </button>
        <button
          className="button button--quiet"
          type="button"
          onClick={() => void onSave(section, 'template')}
          disabled={savingSection === `template:${section.code}`}
        >
          {savingSection === `template:${section.code}` ? '保存中...' : '保存为店铺模板'}
        </button>
      </div>
    </details>
  )
}

export function TaskCenter({ workspace, selectedTask, configPreview, configPreviewLoading, busy, demoEnabled, onSelectTask, onCreateRealTask, onBootstrapDemo, onStartTask, onShowConfig, onShowConsole, onShowEvidence, onShowReports }: TaskCenterProps) {
  const [draftStoreId, setDraftStoreId] = useState(() => workspace.stores[0]?.id ? String(workspace.stores[0].id) : '')
  const [draftMode, setDraftMode] = useState<RealTaskCreateRequest['mode']>('single_save')
  const [draftProductIds, setDraftProductIds] = useState<number[]>(() => workspace.products[0] ? [workspace.products[0].id] : [])
  const needsApproval = selectedTask ? requiresManualApproval(selectedTask) : false
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const needsRealL2 = selectedTask ? requiresRealL2(selectedTask) : false
  const selectedTaskIsDryRun = selectedTask?.mode === 'dry_run'
  const selectedTaskIsUnreleasedRealMode = selectedTask ? isUnreleasedRealDxmMutationTask(selectedTask) : false
  const l2BlocksStart = needsRealL2 && l2Gate?.status !== 'passed'
  const l3BlocksStart = needsRealL2 && l3Gate?.status === 'blocked'
  const configBlocksStart = Boolean(selectedTask && isRealDxmMutationTask(selectedTask) && configPreview && !configPreview.ok)
  const l2DiagnosticSummaries = summarizeL2Diagnostics(l2Gate)
  const selectedStore = workspace.stores.find((store) => String(store.id) === draftStoreId)
  const draftProductIdSet = new Set(draftProductIds)
  const selectedDraftProducts = workspace.products.filter((product) => draftProductIdSet.has(product.id))
  const canCreateRealTask = Boolean(selectedStore && selectedDraftProducts.length > 0 && !busy)
  const startDisabled = busy || !selectedTask || selectedTaskIsUnreleasedRealMode || configBlocksStart || l2BlocksStart || l3BlocksStart
  const startLabel = !selectedTask
    ? '请选择任务'
    : selectedTaskIsUnreleasedRealMode
      ? '未发布，禁止启动'
      : configBlocksStart
        ? '配置未完成，禁止启动'
      : l2BlocksStart
      ? l2StartLabel(l2Gate?.status)
      : l3BlocksStart
        ? 'L3 保持锁定，禁止启动'
        : needsApproval
          ? '批准并启动真实金丝雀'
          : needsRealL2
            ? '启动保存核验任务'
            : '启动本地演示任务'

  useEffect(() => {
    const firstStore = workspace.stores[0]
    if (!firstStore) {
      if (draftStoreId) setDraftStoreId('')
      return
    }
    if (!draftStoreId || !workspace.stores.some((store) => String(store.id) === draftStoreId)) {
      setDraftStoreId(String(firstStore.id))
    }
  }, [draftStoreId, workspace.stores])

  useEffect(() => {
    const availableIds = new Set(workspace.products.map((product) => product.id))
    setDraftProductIds((current) => {
      const kept = current.filter((id) => availableIds.has(id))
      if (kept.length) return kept.length === current.length ? current : kept
      return workspace.products[0] ? [workspace.products[0].id] : []
    })
  }, [workspace.products])

  function toggleDraftProduct(productId: number) {
    setDraftProductIds((current) => {
      if (current.includes(productId)) {
        const next = current.filter((id) => id !== productId)
        return next.length ? next : current
      }
      return [...current, productId]
    })
  }

  function submitRealTask() {
    if (!canCreateRealTask || !selectedStore) return
    void onCreateRealTask({
      storeId: selectedStore.id,
      mode: draftMode,
      productIds: selectedDraftProducts.map((product) => product.id),
    })
  }

  return (
    <section className="module-layout" aria-label="任务中心">
      <div className="module-card span-2">
        <ModuleHead title="任务中心" meta={`${workspace.tasks.length} 个批次`} />
        <div className="real-task-card" aria-label="创建真实任务" data-publish-scene="SMT_SEMI_MANAGED_SAVE_ONLY">
          <div className="real-task-card__head">
            <div>
              <strong>创建真实任务</strong>
              <span>选择店铺、商品和执行范围；保存路径固定为只保存不发布。</span>
            </div>
            <span className="guard-chip">发布动作未开放</span>
          </div>
          <div className="real-task-form">
            <label>
              <span>店铺</span>
              <select value={draftStoreId} onChange={(event) => setDraftStoreId(event.target.value)} disabled={busy || workspace.stores.length === 0}>
                {workspace.stores.map((store) => (
                  <option key={store.id} value={store.id}>{store.name} / {store.platform}</option>
                ))}
                {!workspace.stores.length && <option value="">等待真实店铺</option>}
              </select>
            </label>
            <div className="real-task-mode" role="radiogroup" aria-label="执行模式">
              <button className={draftMode === 'probe' ? 'is-selected' : ''} type="button" onClick={() => setDraftMode('probe')} aria-pressed={draftMode === 'probe'}>
                <strong>L2 只读检查</strong>
                <span>只读探测，不保存</span>
              </button>
              <button className={draftMode === 'single_save' ? 'is-selected' : ''} type="button" onClick={() => setDraftMode('single_save')} aria-pressed={draftMode === 'single_save'}>
                <strong>L3 single_save</strong>
                <span>人工批准后真实保存</span>
              </button>
              <button type="button" disabled aria-disabled="true">
                <strong>批量保存未放行</strong>
                <span>批量/无人值守需单独验收</span>
              </button>
            </div>
          </div>
          <div className="real-task-products" aria-label="选择商品">
            {workspace.products.slice(0, 6).map((product) => (
              <label key={product.id} className="real-task-product">
                <input
                  type="checkbox"
                  checked={draftProductIdSet.has(product.id)}
                  onChange={() => toggleDraftProduct(product.id)}
                  disabled={busy}
                />
                <span>{product.title}</span>
                <small>{product.category_name || '未指定类目'} / SKU {product.sku_count}</small>
              </label>
            ))}
            {workspace.products.length > 6 && <span className="toolbar-note">还有 {workspace.products.length - 6} 个商品会保留在队列，可分批创建。</span>}
            {!workspace.products.length && <EmptyState title="暂无商品" detail="请先导入真实商品；普通模式不使用本地演示商品。" />}
          </div>
          <div className="task-start-strip">
            <button
              className="button button--primary"
              type="button"
              onClick={submitRealTask}
              disabled={!canCreateRealTask}
              data-testid="real-task-create"
            >
              创建真实任务
            </button>
            <span className="toolbar-note">{selectedDraftProducts.length ? `已选择 ${selectedDraftProducts.length} 个商品` : '先选择商品'}</span>
          </div>
        </div>
        <div className="toolbar task-start-strip" aria-label="当前任务操作">
          {demoEnabled && (
            <>
              <button className="button button--quiet" type="button" onClick={onBootstrapDemo} disabled={busy}>
                创建本地 dry_run 演示批次
              </button>
              <span className="toolbar-note">开发模式，不触达 DXM</span>
            </>
          )}
          <button
            className="button button--primary"
            type="button"
            onClick={onStartTask}
            disabled={startDisabled}
            aria-disabled={startDisabled}
            data-testid="task-start-button"
            data-start-disabled={startDisabled ? 'true' : 'false'}
          >
            {startLabel}
          </button>
        </div>
        {(configBlocksStart || configPreviewLoading) && (
          <div className={`gate-note ${configBlocksStart ? 'gate-note--danger' : ''}`}>
            <strong>{configPreviewLoading ? '正在检查配置' : '配置预检未通过'}</strong>
            <span>{configPreviewLoading ? '正在读取当前任务的 DXM 编辑页字段来源。' : `请先补齐：${configPreview?.missing.slice(0, 6).join('、') || 'DXM 编辑页配置'}`}</span>
            {configBlocksStart && (
              <div className="next-step-actions">
                <button className="button button--secondary" type="button" onClick={onShowConfig}>去配置中心</button>
              </div>
            )}
          </div>
        )}
        {(l2BlocksStart || l3BlocksStart) && (
          <div className="gate-note gate-note--danger">
            <strong>真实保存已阻断</strong>
            <span>{l2Gate?.detail ?? '需要 data_acquisition 与 draft_box 两个真实只读检查均通过。'}</span>
            {l3BlocksStart && <span>L3 当前按门禁锁定：L2 未 passed 或人工批准未完成前，不启动未发布 claim_only/batch_save；仅受控 single_save 可在 L2 passed + 人工批准后进入 runner。</span>}
            {demoEnabled && selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span>本地演示批次仅用于开发验收；真实保存仍以 single_save 门禁为准。</span>}
            {!selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span>当前真实任务保持门禁控制，请先处理上方阻断原因。</span>}
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowConsole}>查看 L2 阻断说明</button>
              <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看 L2 评审与复验计划</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
            </div>
          </div>
        )}
        {l2BlocksStart && l2DiagnosticSummaries.length > 0 && (
          <div className="l2-block-summary">
            <strong>L2 阻断摘要</strong>
            {l2DiagnosticSummaries.slice(0, 2).map((item) => (
              <span key={item.target}>{item.targetLabel}：{item.navigation}，{item.failedChecks.slice(0, 2).join(' / ') || 'strict_pass_checks 未满足'}</span>
            ))}
          </div>
        )}
        {needsApproval && (
          <div className="gate-note">
            L3 真实 single_save 会先请求后端批准令牌，再通过受控 runner 启动；claim_only/batch_save 当前未发布，不发布。
          </div>
        )}
        <div className="task-list">
          {workspace.tasks.map((task) => (
            <button
              key={task.id}
              type="button"
              className={`task-row ${selectedTask?.id === task.id ? 'is-selected' : ''}`}
              onClick={() => onSelectTask(task.id)}
              data-task-id={task.id}
              data-task-mode={task.mode}
            >
              <div>
                <strong>{task.name}</strong>
                <span>{task.payload.store_name ?? workspace.stores[0]?.name ?? '未绑定店铺'} / {task.payload.category_name ?? '未指定类目'}</span>
              </div>
              <div className="task-row__meta">
                <span>{humanTaskStatus(task.status)}</span>
                <small>{task.completed_jobs}/{Math.max(task.total_jobs, 1)} 完成</small>
              </div>
            </button>
          ))}
          {!workspace.tasks.length && (
            <EmptyState title="暂无真实任务" detail={demoEnabled ? '开发模式可创建 dry_run 演示批次；普通使用请先导入商品并创建 single_save 任务。' : '请先导入商品并创建 single_save 任务，普通模式不展示本地演示入口。'} />
          )}
        </div>
      </div>

      <div className="module-card span-2 decision-card">
        <ModuleHead title="L2/L3 决策说明" meta="真实保存启动条件" />
        <div className="gate-decision">
          <DecisionRow
            label="L2 真实只读 probe"
            status={l2Gate?.status ?? 'not_run'}
            detail="只有 passed 才允许进入真实保存启动判断；mock_passed、partial、failed、not_run 都不能启动真实保存。"
          />
          {l2DiagnosticSummaries.length > 0 && (
            <div className="l2-diagnostics" aria-label="L2 失败诊断">
              <div className="l2-diagnostics__head">
                <strong>只读失败诊断</strong>
                <span>仅用于定位问题，不放行 L3</span>
              </div>
              {l2DiagnosticSummaries.map((item) => (
                <article key={item.target} className="l2-diagnostic-card">
                  <div className="l2-diagnostic-card__title">
                    <strong>{item.targetLabel}</strong>
                    <span>{item.navigation}</span>
                  </div>
                  <div className="l2-diagnostic-card__chips">
                    {item.failedChecks.slice(0, 4).map((check) => (
                      <span key={check} className="guard-chip guard-chip--danger">{check}</span>
                    ))}
                  </div>
                  <ul>
                    {item.topRequests.map((request) => (
                      <li key={request}>{request}</li>
                    ))}
                    {item.renderHint && <li>{item.renderHint}</li>}
                    {item.reviewCandidateCount > 0 && (
                      <li>只读依赖候选 {item.reviewCandidateCount} 项，仍需人工评审，不自动放行。</li>
                    )}
                  </ul>
                  {item.reviewCandidateRequests.length > 0 && (
                    <div className="l2-review-candidates" aria-label={`${item.targetLabel} 只读依赖人工评审清单`}>
                      <strong>只读依赖人工评审清单</strong>
                      <span>manual review only / allowlist_applied=false / 不自动放行 L2/L3</span>
                      <ul>
                        {item.reviewCandidateRequests.map((request) => (
                          <li key={request}>{request}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
          {l2Gate?.status !== 'passed' && l2DiagnosticSummaries.length === 0 && (
            <div className="l2-diagnostics" aria-label="L2 失败诊断">
              <div className="l2-diagnostics__head">
                <strong>只读失败诊断</strong>
                <span>未收到明细，不放行 L3</span>
              </div>
              <article className="l2-diagnostic-card">
                <div className="l2-diagnostic-card__title">
                  <strong>L2 未通过</strong>
                  <span>{l2Gate?.status ?? 'not_run'}</span>
                </div>
                <ul>
                  <li>{l2Gate?.detail ?? '缺少真实只读 probe 证据。'}</li>
                  <li>需要 data_acquisition 与 draft_box 双目标真实通过后，才可进入 L3 判断。</li>
                </ul>
              </article>
            </div>
          )}
          <DecisionRow
            label="L3 save-only 金丝雀"
            status={l3Gate?.status ?? 'not_run'}
            detail={l3Gate?.status === 'blocked'
              ? 'L3 当前按门禁锁定：L2 未 passed 或人工批准未完成前，不启动未发布 claim_only/batch_save；仅受控 single_save 可在 L2 passed + 人工批准后进入 runner。'
              : 'L3 真实写操作仍需要人工批准令牌，approval_required 不是已通过。'}
          />
          <div className="gate-note">
            当前按钮策略：L2 非 passed 或 L3 blocked 时保持阻断；single_save 仍需后端人工批准；claim_only/batch_save 当前未发布。
          </div>
        </div>
      </div>

      <div className="module-card product-queue-card">
        <ModuleHead title="商品队列" meta={`${workspace.products.length} 个商品`} />
        <div className="product-list">
          {workspace.products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
          {!workspace.products.length && (
            <EmptyState title="暂无商品" detail="真实导入后这里展示待保存队列；本地演示数据仅开发模式可用。" />
          )}
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="任务验收口径" meta="运营可读" />
        <div className="acceptance-strip">
          <span>先验证配置完整性</span>
          <span>L2 通过后才允许申请 L3</span>
          <span>保留截图与结构化证据</span>
          <span>异常进入人工池</span>
          <span>最后生成报告</span>
        </div>
      </div>
    </section>
  )
}

export function ExecutionConsole({
  workspace,
  selectedTask,
  agentConsole,
  agentConsoleError,
  runtimeLogs,
  runtimeLogSource,
  runtimeLogError,
  runtimeLogLevel,
  runtimeLogQuery,
  busy,
  onRuntimeLogSourceChange,
  onRuntimeLogLevelChange,
  onRuntimeLogQueryChange,
  onStartAgentConsole,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onRequestAgentConsoleTakeover,
  onReleaseAgentConsoleTakeover,
  onRuntimeControl,
  onShowTasks,
  onShowEvidence,
  onShowReports,
  onOpenDxmLogin,
}: ExecutionConsoleProps) {
  const taskLogs = selectedTask ? workspace.logs.filter((item) => item.task_id === selectedTask.id) : workspace.logs
  const steps = workspace.deliverySteps.length
    ? workspace.deliverySteps.map((step) => ({
      title: displaySafeStepLabel(step.label),
      code: displaySafeStepCode(step.state),
      detail: `${displaySafeStepCode(step.state)}${step.evidence_count ? ` / 证据 ${step.evidence_count}` : ''}${step.workflow_actions?.length ? ` / ${step.workflow_actions.map(displaySafeWorkflowAction).join(', ')}` : ''}`,
      state: step.status === 'completed' ? 'done' : step.status === 'running' ? 'current' : step.status === 'failed' ? 'blocked' : 'pending',
    }))
    : buildConsoleSteps(selectedTask, workspace.logs)
  const activeStep = steps.find((step) => step.state === 'current' || step.state === 'blocked') ?? steps.find((step) => step.state === 'pending') ?? steps[0]
  const browserFrame = getBrowserFrame(workspace, selectedTask, agentConsole)
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const realSaveBlocked = l2Gate?.status !== 'passed' || l3Gate?.status !== 'passed'
  const realSaveBlockReason = l2Gate?.status !== 'passed'
    ? l2Gate?.detail ?? '只读检查未通过。'
    : l3Gate?.detail ?? '人工确认保存未完成。'
  const diagnosticBlocked = l2Gate?.status !== 'passed'
  const diagnosticBlockReason = l2Gate?.detail ?? '只读检查未通过。'
  const runtimeLogCount = runtimeLogs[runtimeLogSource]?.items?.length
    ?? runtimeLogs[runtimeLogSource]?.lines.length
    ?? 0
  const actionTimelineCount = agentConsole?.action_events?.length ?? agentConsole?.step_history?.length ?? 0

  return (
    <section className="agent-console-layout" aria-label="执行控制台">
      <ConsoleFocusPanel
        selectedTask={selectedTask}
        activeStep={activeStep}
        agentConsole={agentConsole}
        realSaveBlocked={realSaveBlocked}
        realSaveBlockReason={realSaveBlockReason}
        runtimeLogSource={runtimeLogSource}
        runtimeLogCount={runtimeLogCount}
        onShowTasks={onShowTasks}
        onShowReports={onShowReports}
      />

      <div className="module-card span-2 agent-console-stage">
        <ModuleHead
          title="真实浏览器"
          meta={agentConsole?.active ? '自动浏览器运行中' : '打开真实店小秘，保存前仍需确认'}
        />
        <AgentConsoleControls
          agentConsole={agentConsole}
          agentConsoleError={agentConsoleError}
          selectedTask={selectedTask}
          busy={busy}
          realSaveBlocked={realSaveBlocked}
          realSaveBlockReason={realSaveBlockReason}
          diagnosticBlocked={diagnosticBlocked}
          diagnosticBlockReason={diagnosticBlockReason}
          onStartAgentConsole={onStartAgentConsole}
          onOpenDxmLogin={onOpenDxmLogin}
          onStopAgentConsole={onStopAgentConsole}
          onSnapshotAgentConsole={onSnapshotAgentConsole}
          onRequestAgentConsoleTakeover={onRequestAgentConsoleTakeover}
          onReleaseAgentConsoleTakeover={onReleaseAgentConsoleTakeover}
        />
        {realSaveBlocked && (
          <details className="gate-note gate-note--danger inline-disclosure">
            <summary>查看真实保存阻断详情</summary>
            <span>{realSaveBlockReason}</span>
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowTasks}>回到任务门禁</button>
              <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看 L2 评审与复验计划</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
            </div>
          </details>
        )}
        <AgentBrowserFrame
          workspace={workspace}
          selectedTask={selectedTask}
          activeStep={activeStep}
          browserFrame={browserFrame}
          agentConsole={agentConsole}
        />
      </div>

      <div className="module-card console-log-card console-log-card--live">
        <ModuleHead title="最近日志" meta={`${runtimeLogCount} 条，每 1.5 秒刷新`} />
        <RuntimeLogPreview logs={runtimeLogs} source={runtimeLogSource} error={runtimeLogError} />
        <small>完整日志、筛选和搜索已收起在下方，需要排查时再展开。</small>
      </div>

      <details className="module-card span-3 disclosure-card console-advanced console-log-drawer">
        <summary>完整日志中心</summary>
        <ModuleHead title="实时日志中心" meta={`${runtimeLogCount} 条，每 1.5 秒刷新`} />
        <RuntimeLogPanel
          logs={runtimeLogs}
          source={runtimeLogSource}
          error={runtimeLogError}
          level={runtimeLogLevel}
          query={runtimeLogQuery}
          onSourceChange={onRuntimeLogSourceChange}
          onLevelChange={onRuntimeLogLevelChange}
          onQueryChange={onRuntimeLogQueryChange}
        />
      </details>

      <details className="module-card span-3 disclosure-card console-advanced console-support-drawer">
        <summary>辅助面板：运行维护 / 自动操作轨迹</summary>
        <div className="console-support-grid">
          <section className="console-support-panel" aria-label="运行时维护">
            <ModuleHead title="运行时维护" meta="安全动作" />
            <RuntimeControlPanel
              busy={busy}
              agentConsole={agentConsole}
              onRuntimeControl={onRuntimeControl}
            />
          </section>
          <section className="console-support-panel console-support-panel--wide" aria-label="自动操作轨迹">
            <ModuleHead title="自动操作轨迹" meta={`${actionTimelineCount} 条`} />
            <AgentActionTimeline agentConsole={agentConsole} />
          </section>
        </div>
      </details>

      <details className="module-card span-3 disclosure-card console-advanced">
        <summary>执行步骤明细</summary>
        <ModuleHead title="状态机步骤" meta={selectedTask ? `任务 #${selectedTask.id}` : '未选择任务'} />
        <div className="stepper">
          {steps.map((step, index) => (
            <div key={step.title} className={`step ${step.state}`}>
              <span>{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <small>{step.detail}</small>
              </div>
            </div>
          ))}
        </div>
      </details>

      <details className="module-card span-3 disclosure-card console-advanced">
        <summary>任务执行日志</summary>
        <ModuleHead title="执行日志" meta={`${taskLogs.length} 条`} />
        <div className="timeline-list">
          {taskLogs.map((log) => (
            <LogRow key={log.id} log={log} />
          ))}
          {!taskLogs.length && (
            <EmptyState title="暂无执行日志" detail="当前仅可查看 L2 诊断与证据；L2 未通过时禁止启动真实保存/L3。" />
          )}
        </div>
      </details>
    </section>
  )
}

function RuntimeControlPanel({
  busy,
  agentConsole,
  onRuntimeControl,
}: {
  busy: boolean
  agentConsole: AgentConsoleSession | null
  onRuntimeControl: (action: RuntimeControlAction) => void
}) {
  const agentActive = Boolean(agentConsole?.active)
  return (
    <div className="runtime-control-panel">
      <button
        className="button button--secondary"
        type="button"
        disabled={busy || !agentActive}
        onClick={() => onRuntimeControl('stop_agent_console')}
      >
        停止浏览器 Agent
      </button>
      <button
        className="button button--quiet"
        type="button"
        disabled={busy}
        onClick={() => onRuntimeControl('clear_stuck_tasks')}
      >
        清理卡住任务
      </button>
      <details className="inline-disclosure">
        <summary>服务重启</summary>
        <div className="runtime-control-panel__restart">
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => onRuntimeControl('restart_backend')}>
            重启后端
          </button>
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => onRuntimeControl('restart_frontend')}>
            重启前端
          </button>
          <small>启动器托管提示：重启命令会写入启动器日志；若不是通过 start-mvp 启动，请手动重启。</small>
        </div>
      </details>
      <small>维护动作会写入启动器日志；真实保存任务不会被“清理卡住任务”取消。</small>
    </div>
  )
}

function AgentActionTimeline({ agentConsole }: { agentConsole: AgentConsoleSession | null }) {
  const events = getAgentActionTimelineEvents(agentConsole)
  if (!events.length) {
    return <EmptyState title="暂无动作轨迹" detail="任务运行时，点击、填写、保存等待步骤会从后端自动浏览器同步到这里。" />
  }
  return (
    <div className="agent-action-timeline">
      {events.map((event, index) => {
        const typeLabel = getAgentActionTypeLabel(event.type)
        const title = event.label ?? event.action ?? event.target ?? event.step_code ?? typeLabel
        const stepCode = displaySafeStepCode(event.step_code ?? event.state ?? event.type ?? 'WAITING')
        const fieldDomain = event.field_domain ?? '自动化'
        const detail = getAgentActionDetail(event)
        const status = getAgentActionStatus(event.status)
        return (
          <article key={`${event.timestamp ?? event.step_code ?? event.action ?? event.type}-${index}`} className="agent-action-row">
            <span>{events.length - index}</span>
            <div>
              <div className="agent-action-row__head">
                <span className="agent-action-row__type">{typeLabel}</span>
                {status && <span className={`status-pill ${status.tone}`}>{status.label}</span>}
              </div>
              <strong>{displaySafeStepLabel(title)}</strong>
              <small>{[
                stepCode,
                fieldDomain,
                event.task_id ? `task #${event.task_id}` : '',
                event.job_id ? `job #${event.job_id}` : '',
                event.product_id ? `product #${event.product_id}` : '',
              ].filter(Boolean).join(' / ')}</small>
              {detail && <code>{detail}</code>}
            </div>
          </article>
        )
      })}
    </div>
  )
}

function getAgentActionTimelineEvents(agentConsole: AgentConsoleSession | null): AgentConsoleActionEvent[] {
  const actionEvents = agentConsole?.action_events ?? []
  if (actionEvents.length) return [...actionEvents].reverse().slice(0, 12)

  return [...(agentConsole?.step_history ?? [])].reverse().slice(0, 12).map((event) => {
    const stepCode = String(event.step_code ?? event.state ?? event.code ?? 'WAITING')
    return {
      type: 'workflow_action',
      action: String(event.step_name ?? event.title ?? stepCode),
      label: String(event.step_name ?? event.title ?? stepCode),
      state: typeof event.state === 'string' ? event.state : undefined,
      step_code: stepCode,
      task_id: typeof event.task_id === 'number' ? event.task_id : undefined,
      job_id: typeof event.job_id === 'number' ? event.job_id : undefined,
      product_id: typeof event.product_id === 'number' ? event.product_id : undefined,
      field_domain: event.field_domain ? String(event.field_domain) : '状态机',
      status: typeof event.status === 'string' ? event.status : undefined,
      page_url: typeof event.page_url === 'string' ? event.page_url : undefined,
      screenshot_url: typeof event.screenshot_url === 'string' ? event.screenshot_url : typeof event.screenshot_path === 'string' ? event.screenshot_path : undefined,
      timestamp: typeof event.updated_at === 'string' ? event.updated_at : typeof event.timestamp === 'string' ? event.timestamp : undefined,
    }
  })
}

function getAgentActionTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    workflow_action: '流程',
    click: '点击',
    fill: '填写',
    select: '选择',
    upload: '上传',
    wait: '等待',
    save: '保存',
  }
  return labels[type ?? ''] ?? (type ? type.slice(0, 12) : '动作')
}

function getAgentActionStatus(status?: string) {
  if (!status) return null
  if (status === 'ok') return { label: 'ok', tone: 'ok' }
  if (status === 'failed') return { label: 'failed', tone: 'danger' }
  return { label: status.slice(0, 16), tone: 'muted' }
}

function getAgentActionDetail(event: AgentConsoleActionEvent) {
  if (event.save_result) return summarizeAgentSaveResult(event.save_result)
  if (event.page_url) return `URL ${shortUrl(event.page_url)}`
  if (event.target && event.value) return `${event.target}: ${event.value}`.slice(0, 120)
  if (event.target) return event.target.slice(0, 120)
  if (event.value) return event.value.slice(0, 120)
  if (event.screenshot_url) return event.screenshot_url.slice(0, 120)
  return ''
}

function summarizeAgentSaveResult(saveResult: Record<string, unknown>) {
  const entries = Object.entries(saveResult)
    .filter(([, value]) => value !== null && value !== undefined)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${summarizeAgentActionValue(value)}`)
  return entries.length ? entries.join(' / ') : '保存结果已返回'
}

function summarizeAgentActionValue(value: unknown) {
  if (typeof value === 'string') return value.slice(0, 48)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value).slice(0, 48)
  } catch {
    return String(value).slice(0, 48)
  }
}

function ConsoleFocusPanel({
  selectedTask,
  activeStep,
  agentConsole,
  realSaveBlocked,
  realSaveBlockReason,
  runtimeLogSource,
  runtimeLogCount,
  onShowTasks,
  onShowReports,
}: {
  selectedTask: Task | null
  activeStep?: { title: string; code?: string; detail: string; state: string }
  agentConsole: AgentConsoleSession | null
  realSaveBlocked: boolean
  realSaveBlockReason: string
  runtimeLogSource: RuntimeLogSource
  runtimeLogCount: number
  onShowTasks: () => void
  onShowReports: () => void
}) {
  const active = Boolean(agentConsole?.active)
  const sourceLabel = ({
    backend: '后端',
    frontend: '前端',
    launcher: '启动器',
    npm: '依赖安装',
  } as Record<typeof runtimeLogSource, string>)[runtimeLogSource]
  return (
    <div className="module-card span-3 console-focus-panel">
      <div className="console-focus-panel__main">
        <span className={`console-focus-panel__dot ${realSaveBlocked ? 'is-warn' : active ? 'is-live' : ''}`} aria-hidden="true" />
        <div>
          <ModuleHead title="当前执行" meta={selectedTask ? `任务 #${selectedTask.id}` : '未选择任务'} />
          <h1>{activeStep?.title ?? '等待选择任务'}</h1>
          <p>{activeStep?.detail ?? '先完成配置、只读检查和人工确认，再启动真实浏览器执行。'}</p>
        </div>
      </div>
      <div className="console-focus-panel__facts" aria-label="执行摘要">
        <span><strong>任务</strong><b>{selectedTask ? `${selectedTask.name} / ${humanTaskStatus(selectedTask.status)}` : '待选择'}</b></span>
        <span><strong>浏览器</strong><b>{active ? '自动浏览器运行中' : '待启动'}</b></span>
        <span><strong>日志</strong><b>{sourceLabel} {runtimeLogCount} 条</b></span>
        <span><strong>门禁</strong><b>{realSaveBlocked ? '保存前置条件未完成' : '可申请只保存'}</b></span>
      </div>
      <div className="console-focus-panel__actions">
        {realSaveBlocked && <small>{realSaveBlockReason}</small>}
        <button className="button button--secondary" type="button" onClick={onShowTasks}>处理任务门禁</button>
        <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">查看复验计划</button>
      </div>
    </div>
  )
}

function AgentBrowserFrame({
  workspace,
  selectedTask,
  activeStep,
  browserFrame,
  agentConsole,
}: {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  activeStep?: { title: string; code?: string; detail: string; state: string }
  browserFrame: { url: string; screenshotUrl: string; source: string }
  agentConsole: AgentConsoleSession | null
}) {
  const nextStep = nextPendingStep(workspace.deliverySteps, activeStep?.code)
  const hasConsoleHud = Boolean(agentConsole?.active || agentConsole?.updated_at)
  const hud = agentConsole?.hud
  const storeName = (hasConsoleHud ? hud?.store_name : null) ?? selectedTask?.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺'
  const hudTitle = (hasConsoleHud ? hud?.title ?? hud?.label : null) ?? activeStep?.title ?? '等待任务'
  const hudState = (hasConsoleHud ? hud?.state ?? hud?.code : null) ?? activeStep?.code ?? 'WAITING'
  const hudAction = (hasConsoleHud ? hud?.action ?? hud?.detail : null) ?? activeStep?.detail ?? '等待后端推送步骤'
  const hudNext = (hasConsoleHud ? hud?.next_step : null) ?? nextStep?.label ?? '等待状态机推进'
  const hudGuard = (hasConsoleHud ? hud?.guard : null) ?? (workspace.publishGuardState?.safe ? '通过' : '等待证明')
  const hudDotState = agentConsole?.last_error ? 'blocked' : agentConsole?.active ? 'current' : activeStep?.state ?? 'pending'
  const recentNetworkEvents = getRecentNetworkEvents(agentConsole)

  return (
    <div className="agent-browser">
      <div className="agent-browser__chrome">
        <div className="traffic-lights" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="browser-tab">店小秘自动浏览器</div>
        <div className="browser-url">{browserFrame.url}</div>
        <span className={`status-pill ${agentConsole?.browser_visible ? 'ok' : 'muted'}`}>
          {agentConsole?.browser_visible ? '可见浏览器' : '独立浏览器待命'}
        </span>
      </div>
      <div className="agent-browser__viewport">
        {browserFrame.screenshotUrl ? (
          <>
            <div className="agent-browser__evidence-note">
              <strong>真实窗口是主要操控界面</strong>
              <span>截图只作为证据缩略图；需要操作时点击“人工接管真实浏览器”。</span>
            </div>
            <img src={browserFrame.screenshotUrl} alt="当前真实浏览器证据缩略图" />
          </>
        ) : agentConsole?.active || agentConsole?.updated_at ? (
          <div className="browser-empty-state">
            <strong>真实窗口是主要操控界面</strong>
            <span>浏览器会话状态已记录，自动刷新画面还在等待首帧；截图只作为证据缩略图。</span>
            <small>需要人工介入时，用“人工接管真实浏览器”切到真实 dianxiaomi.com 窗口。</small>
          </div>
        ) : (
          <div className="browser-empty-state">
            <strong>尚未打开真实店小秘浏览器</strong>
            <span>点击上方按钮后，会使用独立浏览器打开真实 dianxiaomi.com。</span>
            <small>保存动作仍受只读检查和人工确认保护，不会触发发布。</small>
          </div>
        )}

        <div className="agent-hud" aria-label="浏览器内执行步骤框">
          <div className="agent-hud__head">
            <span className={`hud-dot ${hudDotState}`} />
            <strong>{hudTitle}</strong>
          </div>
          <dl>
            <div>
              <dt>店铺</dt>
              <dd>{storeName}</dd>
            </div>
            <div>
              <dt>当前状态</dt>
              <dd>{hudState}</dd>
            </div>
            <div>
              <dt>正在执行</dt>
              <dd>{hudAction}</dd>
            </div>
            <div>
              <dt>下一步</dt>
              <dd>{hudNext}</dd>
            </div>
          </dl>
          <div className="agent-hud__guard">
            <span>发布隔离</span>
            <strong>{hudGuard}</strong>
          </div>
        </div>
      </div>
      <div className="agent-browser__footer">
        <div className="agent-browser__source">
          <span>{browserFrame.source}</span>
          <div className="agent-network-events" aria-label="网络响应">
            <strong>网络响应</strong>
            {recentNetworkEvents.length > 0 ? (
              recentNetworkEvents.map((event, index) => (
                <span key={`${event.timestamp ?? event.url ?? 'network'}-${index}`}>
                  <b>{event.status ?? event.type ?? 'event'}</b>
                  <em>{event.method ?? '-'}</em>
                  <code>{shortUrl(event.url)}</code>
                </span>
              ))
            ) : (
              <span>
                <b>待命</b>
                <em>-</em>
                <code>等待网络响应</code>
              </span>
            )}
          </div>
        </div>
        <span>{agentConsole?.profile_dir ? `浏览器数据目录: ${agentConsole.profile_dir}` : '等待启动独立浏览器'}</span>
      </div>
    </div>
  )
}

function AgentConsoleControls({
  agentConsole,
  agentConsoleError,
  selectedTask,
  busy,
  realSaveBlocked,
  realSaveBlockReason,
  diagnosticBlocked,
  diagnosticBlockReason,
  onStartAgentConsole,
  onOpenDxmLogin,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onRequestAgentConsoleTakeover,
  onReleaseAgentConsoleTakeover,
}: {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  selectedTask: Task | null
  busy: boolean
  realSaveBlocked: boolean
  realSaveBlockReason: string
  diagnosticBlocked: boolean
  diagnosticBlockReason: string
  onStartAgentConsole: () => void
  onOpenDxmLogin: () => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onRequestAgentConsoleTakeover: () => void
  onReleaseAgentConsoleTakeover: () => void
}) {
  const active = Boolean(agentConsole?.active)
  const manualTakeover = Boolean(agentConsole?.manual_takeover)
  const screenshot = agentConsole?.screenshot_url ?? agentConsole?.screenshot ?? ''
  return (
    <div className="agent-console-controls">
      <div className="agent-console-controls__status">
        <span className={`status-pill ${active ? 'ok' : 'muted'}`}>{active ? '浏览器会话中' : '未打开浏览器'}</span>
        <span className={`status-pill ${agentConsole?.browser_visible ? 'ok' : active ? 'warn' : 'muted'}`}>
          {agentConsole?.browser_visible ? '窗口可见' : '窗口未显示'}
        </span>
        <span className={`status-pill ${manualTakeover ? 'warn' : 'muted'}`}>
          {manualTakeover ? '用户正在真实浏览器中接管' : 'Agent 可接管'}
        </span>
        <span className="status-pill warn">不会发布</span>
      </div>
      <details className="agent-console-controls__fields inline-disclosure">
        <summary>技术详情</summary>
        <div className="agent-console-controls__field-grid">
          <StatusField label="session_id" value={agentConsole?.session_id} />
          <StatusField label="last_step" value={agentConsole?.last_step_code ?? agentConsole?.hud?.state} />
          <StatusField label="profile_dir" value={agentConsole?.profile_dir} />
          <StatusField label="current_url" value={agentConsole?.current_url ?? agentConsole?.target_url} />
          <StatusField label="screenshot" value={screenshot} />
        </div>
      </details>
      <div className="agent-console-controls__actions">
        <button
          className="button button--secondary"
          type="button"
          onClick={onOpenDxmLogin}
          disabled={busy}
          title="登录和人工处理不要求 L2；只用于打开真实店小秘窗口，不启动保存。"
        >
          登录/人工处理真实浏览器
        </button>
        <button
          className="button button--quiet"
          type="button"
          onClick={onStartAgentConsole}
          disabled={busy || !selectedTask || diagnosticBlocked}
          title={diagnosticBlocked ? diagnosticBlockReason : realSaveBlocked ? realSaveBlockReason : '打开执行观察浏览器；保存前仍需人工确认'}
        >
          {diagnosticBlocked ? '只读通过后执行' : '启动执行观察'}
        </button>
        <button className="button button--quiet" type="button" onClick={onSnapshotAgentConsole} disabled={busy || !active}>
          刷新当前画面
        </button>
        <button className="button button--quiet" type="button" onClick={onRequestAgentConsoleTakeover} disabled={busy || !active}>
          人工接管真实浏览器
        </button>
        <button className="button button--quiet" type="button" onClick={onReleaseAgentConsoleTakeover} disabled={busy || !active || !manualTakeover}>
          交还 Agent
        </button>
        <button className="button button--secondary" type="button" onClick={onStopAgentConsole} disabled={busy || !active}>
          关闭浏览器
        </button>
      </div>
      {agentConsoleError && <div className="agent-console-controls__error console-error">{agentConsoleError}</div>}
    </div>
  )
}

function StatusField({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="agent-console-field">
      <span>{label}</span>
      <code>{value ? String(value) : '暂无'}</code>
    </div>
  )
}

function getRecentNetworkEvents(agentConsole: AgentConsoleSession | null) {
  const networkEvents = agentConsole?.network_events ?? []
  const responseEvents = networkEvents.filter((event) => {
    const type = event.type?.toLowerCase() ?? ''
    return type.includes('response') || typeof event.status === 'number'
  })
  return (responseEvents.length ? responseEvents : networkEvents).slice(-3).reverse()
}

function shortUrl(url?: string) {
  if (!url) return '暂无 URL'
  try {
    const parsed = new URL(url)
    const path = `${parsed.pathname}${parsed.search}`
    return `${parsed.host}${path}`.slice(0, 84)
  } catch {
    return url.slice(0, 84)
  }
}

function RuntimeLogPreview({
  logs,
  source,
  error,
}: {
  logs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  source: RuntimeLogSource
  error: string | null
}) {
  const current = logs[source]
  const items: RuntimeLogItem[] = current?.items ?? current?.lines.map((line) => ({ line, level: 'info', tags: [] })) ?? []
  const visibleItems = items.slice(-4)

  return (
    <div className="runtime-log-preview" aria-live="polite">
      {error && <div className="console-error">{error}</div>}
      {visibleItems.length ? (
        visibleItems.map((item, index) => (
          <div key={`${source}-preview-${index}`} className={`runtime-log-preview__line runtime-log-preview__line--${item.level}`}>
            <span>{item.level.toUpperCase()}</span>
            <code>{item.line}</code>
          </div>
        ))
      ) : (
        <span>{current?.exists === false ? '日志文件尚未生成。' : '等待服务写入日志...'}</span>
      )}
      <small>{current?.path ?? 'data/*.log'}</small>
    </div>
  )
}

function RuntimeLogPanel({
  logs,
  source,
  error,
  level,
  query,
  onSourceChange,
  onLevelChange,
  onQueryChange,
}: {
  logs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  source: RuntimeLogSource
  error: string | null
  level: 'all' | 'info' | 'warning' | 'error'
  query: string
  onSourceChange: (source: RuntimeLogSource) => void
  onLevelChange: (level: 'all' | 'info' | 'warning' | 'error') => void
  onQueryChange: (query: string) => void
}) {
  const current = logs[source]
  const logViewRef = useRef<HTMLDivElement | null>(null)
  const [autoFollow, setAutoFollow] = useState(true)
  const labels: Record<RuntimeLogSource, string> = {
    backend: '后端',
    frontend: '前端',
    launcher: '启动器',
    npm: '依赖安装',
    task: '任务',
    agent: '浏览器 Agent',
  }
  const items: RuntimeLogItem[] = current?.items ?? current?.lines.map((line) => ({ line, level: 'info', tags: [] })) ?? []

  useEffect(() => {
    if (!autoFollow || !logViewRef.current) return
    logViewRef.current.scrollTop = logViewRef.current.scrollHeight
  }, [autoFollow, items.length, source])

  function handleLogScroll() {
    const node = logViewRef.current
    if (!node || !autoFollow) return
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    if (distanceToBottom > 48) setAutoFollow(false)
  }

  function resumeAutoFollow() {
    setAutoFollow(true)
    window.requestAnimationFrame(() => {
      if (logViewRef.current) logViewRef.current.scrollTop = logViewRef.current.scrollHeight
    })
  }

  return (
    <div className="runtime-log-panel">
      <div className="runtime-log-toolbar">
        <strong>实时日志中心</strong>
        <span>后端、前端、启动器、任务和浏览器 Agent 日志会每 1.5 秒增量刷新。</span>
        <label>
          <input
            type="checkbox"
            checked={autoFollow}
            onChange={(event) => {
              if (event.target.checked) {
                resumeAutoFollow()
              } else {
                setAutoFollow(false)
              }
            }}
          />
          自动跟随最新日志
        </label>
      </div>
      <div className="runtime-log-tabs" role="tablist" aria-label="运行日志来源">
        {(Object.keys(labels) as RuntimeLogSource[]).map((item) => (
          <button
            key={item}
            type="button"
            className={item === source ? 'is-active' : ''}
            onClick={() => onSourceChange(item)}
          >
            {labels[item]}
          </button>
        ))}
      </div>
      <div className="runtime-log-filters">
        <label>
          <span>级别</span>
          <select value={level} onChange={(event) => onLevelChange(event.target.value as 'all' | 'info' | 'warning' | 'error')}>
            <option value="all">全部</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </label>
        <label>
          <span>搜索</span>
          <input value={query} placeholder="保存 / error / add.json" onChange={(event) => onQueryChange(event.target.value)} />
        </label>
      </div>
      {error && <div className="console-error">{error}</div>}
      <div ref={logViewRef} className="runtime-log-view" aria-live="polite" data-testid="runtime-log-view" onScroll={handleLogScroll}>
        {items.length
          ? items.map((item, index) => <RuntimeLogLine key={`${source}-${index}`} item={item} />)
          : <span>{current?.exists === false ? '日志文件尚未生成，启动服务后会自动出现。' : '等待日志刷新...'}</span>}
      </div>
      <small>{current?.path ?? 'data/*.log'} / 标签：启动、登录检测、配置校验、打开 DXM、点击、填写、保存、网络响应、报告生成</small>
    </div>
  )
}

function RuntimeLogLine({ item }: { item: RuntimeLogItem }) {
  return (
    <div className={`runtime-log-line runtime-log-line--${item.level}`}>
      <span>{item.level.toUpperCase()}</span>
      <code>{item.line}</code>
      {item.tags.length > 0 && (
        <small>{item.tags.slice(0, 3).map((tag) => <b key={tag}>{tag}</b>)}</small>
      )}
    </div>
  )
}

export function EvidenceTimeline({
  workspace,
  selectedTask,
  onShowTasks,
  onShowConsole,
}: CommonProps & { onShowTasks: () => void; onShowConsole: () => void }) {
  const evidences = selectedTask ? workspace.evidences.filter((item) => item.task_id === selectedTask.id) : workspace.evidences
  const reports = selectedTask ? workspace.reports.filter((item) => item.task_id === selectedTask.id) : workspace.reports
  const evidencePoints = filterEvidencePointsForTask(workspace.evidencePoints, evidences, reports, selectedTask)

  return (
    <section className="module-layout" aria-label="证据中心">
      <div className="module-card span-3">
        <ModuleHead title="交付证据摘要" meta={`等级 ${workspace.evidenceGrade?.grade ?? 'C'}`} />
        <div className="evidence-point-grid">
          {evidencePoints.slice(0, 8).map((point, index) => (
            <EvidencePointCard key={`${point.kind}-${point.id ?? index}`} point={point} />
          ))}
          {!evidencePoints.length && (
            <EmptyState
              title="暂无可验收证据"
              detail="当前真实写入未放行时，保存结果、未发布证明和网络/HAR 为 0 条是预期阻断；只有 L3 金丝雀完成后才生成可验收证据等级。"
              actions={(
                <>
                  <button className="button button--secondary" type="button" onClick={onShowTasks}>查看任务门禁</button>
                  <button className="button button--quiet" type="button" onClick={onShowConsole}>查看只读诊断</button>
                </>
              )}
            />
          )}
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="原始证据" meta={`${evidences.length} 条`} />
        <div className="evidence-timeline">
          {evidences.map((evidence) => (
            <EvidenceRow key={evidence.id} evidence={evidence} />
          ))}
          {!evidences.length && (
            <EmptyState
              title="暂无原始证据"
              detail="未执行不代表通过；真实截图、DOM、报告和网络摘要会在执行后出现。"
              actions={<button className="button button--secondary" type="button" onClick={onShowTasks}>查看阻断原因</button>}
            />
          )}
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="证据等级说明" meta="验收导向" />
        <div className="grade-grid">
          <GradeCard grade="A" title="可直接验收" detail="同屏绑定任务、账号、商品、保存结果，并可回溯文件。" />
          <GradeCard grade="B" title="可辅助验收" detail="有截图或结构化记录，但缺少部分上下文绑定。" />
          <GradeCard grade="C" title="只能提示风险" detail="前端或日志提示，不能单独作为交付验收证据。" />
        </div>
      </div>
    </section>
  )
}

export function ExceptionQueue({ workspace, selectedTask }: CommonProps) {
  const exceptions = selectedTask ? workspace.exceptions.filter((item) => item.task_id === selectedTask.id) : workspace.exceptions
  const presentedAcceptanceGaps = presentAcceptanceGaps(workspace.acceptanceGaps, isRealWriteExpectedBlocked(workspace))
  return (
    <section className="module-layout" aria-label="异常池">
      <div className="module-card span-2">
        <ModuleHead title="异常池" meta={`${exceptions.length} 条异常`} />
        <div className="exception-list">
          {exceptions.map((item) => (
            <ExceptionCard key={item.id} item={item} />
          ))}
          {!exceptions.length && (
            <EmptyState title="暂无异常" detail="未执行不代表通过；执行失败、字段缺失和门禁阻断会进入异常池。" />
          )}
        </div>
      </div>
      <div className="module-card">
        <ModuleHead title="真实验收缺口" meta={`${presentedAcceptanceGaps.length} 项`} />
        <GapList gaps={presentedAcceptanceGaps} />
      </div>
    </section>
  )
}

export function ReportCenter({
  workspace,
  selectedTask,
  finalCheck,
  onShowEvidence,
  onShowConsole,
}: CommonProps & { finalCheck: FinalDeliveryCheckSummary | null; onShowEvidence: () => void; onShowConsole: () => void }) {
  const reports = selectedTask ? workspace.reports.filter((item) => item.task_id === selectedTask.id) : workspace.reports
  const reportSummary = workspace.reportSummary
  const l2ProbePlan = workspace.l2ProbePlan
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const realWriteExpectedBlocked = finalCheck?.real_dxm_write_readiness === 'BLOCKED' && finalCheck?.real_dxm_mutation_allowed !== true
  const businessReportCount = reportSummary?.total_reports ?? reports.length
  const saveResultCount = reportSummary?.save_results?.length ?? 0
  const unpublishedProofCount = reportSummary?.published_proofs?.length ?? 0
  const networkHarCount = (reportSummary?.network_save_results?.length ?? 0) + (reportSummary?.har_summaries?.length ?? 0)
  const l2AllowlistReviewItems = summarizeL2Diagnostics(l2Gate).flatMap((item) =>
    item.reviewCandidateRequests.map((request) => ({ target: item.targetLabel, request })),
  )

  return (
    <section className="module-layout" aria-label="报告中心" data-testid="report-center-section">
      <FinalDeliveryCheckCard finalCheck={finalCheck} />
      <div className="module-card span-3">
        <ModuleHead title="保存隔离摘要" meta={workspace.publishGuardState?.status ?? '等待执行'} />
        <div className="report-check-grid">
          <BusinessReportCheckRow count={businessReportCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="保存结果" count={saveResultCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="未发布证明" count={unpublishedProofCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="网络/HAR" count={networkHarCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
        </div>
        {realWriteExpectedBlocked && (
          <p className="delivery-check-card__warning">L3 未放行前不要求生成真实保存证据；0 条代表当前自动化真实保存按门禁锁定。</p>
        )}
      </div>
      <div className="module-card span-3">
        <ModuleHead title="报告中心" meta={`${reports.length} 份报告`} />
        <div className="report-grid">
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
          {!reports.length && (
            <EmptyState
              title={realWriteExpectedBlocked ? 'L3 真实保存报告待放行' : '暂无报告'}
              detail={realWriteExpectedBlocked
                ? '真实写入 BLOCKED 时不要求生成业务保存报告；自动化工作台交付自检报告见上方最近交付自检。'
                : 'L3 金丝雀完成并生成未发布证明后，这里会展示报告和证据路径。当前可先查看 L2 诊断和证据缺口。'}
              actions={(
                <>
                  <button className="button button--secondary" type="button" onClick={onShowEvidence}>查看证据缺口</button>
                  <button className="button button--quiet" type="button" onClick={onShowConsole}>查看只读诊断</button>
                </>
              )}
            />
          )}
        </div>
      </div>
      <div className="module-card span-3 l2-next-step-card">
        <ModuleHead title="重新验证 L2" meta="需人工批准" />
        <div className="l2-allowlist-review">
          <div className="l2-allowlist-review__head">
            <strong>L2 allowlist 候选处理</strong>
            <span>先评审，再复跑 L2</span>
          </div>
          <p>review_only=true / allowlist_applied=false。未完成人工评审前，不运行下方 L2 复验命令。</p>
          {l2AllowlistReviewItems.length > 0 ? (
            <ul>
              {l2AllowlistReviewItems.slice(0, 8).map((item) => (
                <li key={`${item.target}:${item.request}`}>{item.target}：{item.request}</li>
              ))}
            </ul>
          ) : (
            <p>当前工作区没有可展示的 allowlist 候选；仍需按最终报告和 L2 证据复核后再决定是否重跑。</p>
          )}
        </div>
        <p>{l2ProbePlan.purpose || '真实写入保持阻断；仅在操作者确认可进行只读探测时，才重新运行双目标 L2。'}</p>
        <div className="l2-next-step-card__commands">
          {l2ProbePlan.commands.map((command) => (
            <code key={command}>{command}</code>
          ))}
        </div>
        <p>证据目录：{l2ProbePlan.outputDir}。{l2ProbePlan.acceptanceCriteria.join(' ')}</p>
        <p>{l2ProbePlan.safetyNotes.join(' ')}</p>
      </div>
      <div className="module-card span-3">
        <ModuleHead title={realWriteExpectedBlocked ? 'L3 后置报告必须覆盖' : '报告必须覆盖'} meta={realWriteExpectedBlocked ? '真实写入放行后' : '交付检查表'} />
        <div className="report-check-grid">
          <PostL3ReportCheckRow label="配置模板命中" ok={workspace.dxmReferenceTemplates.some((item) => item.templateNames.length)} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="执行步骤与结果" ok={workspace.logs.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="证据等级 A/B/C" ok={workspace.evidences.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="验收缺口已列明" ok={workspace.acceptanceGaps.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
        </div>
      </div>
    </section>
  )
}

function FinalDeliveryCheckCard({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const available = finalCheck?.status === 'available'
  const checkedAt = finalCheck?.checked_at ? new Date(finalCheck.checked_at).toLocaleString() : '尚无记录'
  const reportPath = finalCheck?.summary_path ?? 'outputs/final-delivery-check/final-delivery-check.md'
  const jsonPath = finalCheck?.json_path ?? 'outputs/final-delivery-check/final-delivery-check.json'
  const gitHead = finalCheck?.git_head ? finalCheck.git_head.slice(0, 8) : '未记录'
  const currentGitHead = finalCheck?.current_git_head ? finalCheck.current_git_head.slice(0, 8) : '未记录'
  const browserQaGitHead = finalCheck?.browser_qa_git_head ? finalCheck.browser_qa_git_head.slice(0, 8) : '未记录'
  const finalCheckMatchesCurrent = finalCheck?.final_check_matches_current_worktree === true
  const postFinalReportQaState = finalCheck?.post_final_report_qa_ok === true
    ? 'PASS'
    : finalCheck?.post_final_report_qa_ok === false
      ? 'FAIL'
      : '待刷新/未运行'
  const readiness = finalCheck?.real_dxm_write_readiness ?? '未检查'
  const realDxmMutationScope = finalCheck?.real_dxm_mutation_scope ?? (finalCheck?.real_dxm_mutation_allowed === true ? 'controlled_single_save_only' : 'none')
  const realDxmMutationAllowedLabel = finalCheck?.real_dxm_mutation_allowed === true
    ? `真实写入允许 true / ${realDxmMutationScope}`
    : '真实写入允许 false / none'
  const blockedReason = finalCheck?.real_dxm_write_blocked_reason
  const readinessDetail = !available
    ? '还没有读取到交付自检报告。运行 scripts\\final-delivery-check.bat 后，这里会显示最近一次验收摘要。'
    : readiness === 'READY'
      ? '当前自检显示受控 single_save READY；执行前仍需复核 L2/L3 证据、人工金丝雀批准和报告链路。批量、无人值守和发布仍需单独放行。'
      : readiness === 'BLOCKED'
        ? '当前预期交付态：自动化工作台可继续验收，真实保存保持阻断。BLOCKED 代表真实 L2/L3 尚未放行，不代表自动化工作台失败。'
        : '当前真实写入状态未知，不可执行真实写入；请先重新运行交付自检并复核 L2/L3 门禁。'

  return (
    <div className="module-card span-3 delivery-check-card">
      <ModuleHead title="最近交付自检" meta={available ? checkedAt : '尚未运行'} />
      <div className="report-check-grid">
        <CheckRow label={`自动化工作台 ${finalCheck?.local_workbench_check ?? '未检查'}`} ok={finalCheck?.local_workbench_check === 'PASS'} />
        <DeliveryReadinessRow readiness={readiness} />
        <FinalCheckFreshnessRow finalCheck={finalCheck} />
        <SourcePackageCheckRow finalCheck={finalCheck} />
        <CheckRow label={`浏览器 QA ${finalCheck?.browser_qa_ok === true ? 'PASS' : finalCheck?.browser_qa_ok === false ? 'FAIL' : '待刷新/未运行'}`} ok={finalCheck?.browser_qa_ok === true} />
        <CheckRow
          label={`最终报告中心 QA ${postFinalReportQaState}`}
          ok={finalCheck?.post_final_report_qa_ok === true}
          testId="final-report-center-qa"
          state={postFinalReportQaState}
        />
      </div>
      <div className="delivery-check-card__body">
        <p>{readinessDetail}</p>
        {blockedReason && (
          <p className="delivery-check-card__warning">真实写入阻断原因：{blockedReason}</p>
        )}
        <div className="delivery-check-card__next-step">
          <strong>下一步</strong>
          <span>
            {readiness === 'READY'
              ? '交付源码包前运行 clean worktree 验收；扩大到 claim_only / batch_save 前重新建立对应 L2/L3 证据链。'
              : '人工评审 allowlist 候选 - 改代码/配置 - 同一 run-id 复跑 data_acquisition + draft_box - 通过后再申请受控 L3 single_save。'}
          </span>
        </div>
        <div className="delivery-check-card__release-gates" aria-label="真实写入放行前置">
          <strong>真实写入放行前置</strong>
          <ol>
            {realWriteReleasePrerequisites.map((item) => (
              <li key={item.title}>
                <span>{item.title}</span>
                <small>{item.detail}</small>
              </li>
            ))}
          </ol>
        </div>
        {available && !finalCheckMatchesCurrent && (
          <p className="delivery-check-card__warning">
            自检未覆盖当前代码：请重新运行本地验收命令；源码包交付前运行源码包验收命令。
          </p>
        )}
        <div className="delivery-check-card__paths">
          <code>{reportPath}</code>
          <code>{jsonPath}</code>
          {finalCheck?.l2_allowlist_review_template_markdown_path && (
            <code>{finalCheck.l2_allowlist_review_template_markdown_path}</code>
          )}
          {finalCheck?.l2_allowlist_review_template_json_path && (
            <code>{finalCheck.l2_allowlist_review_template_json_path}</code>
          )}
          {finalCheck?.final_report_center_screenshot_path && (
            <code data-testid="final-report-center-screenshot-path">{finalCheck.final_report_center_screenshot_path}</code>
          )}
          <span>自检 Git {gitHead} / 当前 Git {currentGitHead}</span>
          <span>OK 范围 {finalCheck?.ok_scope ?? '未记录'} / {realDxmMutationAllowedLabel}</span>
          <span>受控 single_save {finalCheck?.controlled_single_save_ready === true ? 'READY' : '未放行'} / 批量无人值守发布 {finalCheck?.batch_unattended_publish_allowed === true ? '允许' : '阻断'}</span>
          <span>预期真实写入 {finalCheck?.expected_real_dxm_write_readiness ?? '未记录'} / 匹配 {finalCheck?.real_dxm_write_readiness_matches_expected === true ? 'true' : 'false'}</span>
          <span>L2 allowlist 评审模板 {finalCheck?.l2_allowlist_review_template_state ?? '未生成'} / 候选 {finalCheck?.l2_allowlist_review_template_candidate_count ?? 0} 项</span>
          <span>模板哈希 MD {shortHash(finalCheck?.l2_allowlist_review_template_markdown_sha256)} / JSON {shortHash(finalCheck?.l2_allowlist_review_template_json_sha256)}</span>
          <span>浏览器 QA Git {browserQaGitHead} / 截图哈希 {finalCheck?.browser_qa_screenshot_hashes ? Object.keys(finalCheck.browser_qa_screenshot_hashes).length : 0} 项</span>
          <span>最终报告页截图 qa-report-center-final.png / 截图哈希 {finalCheck?.post_final_report_qa_screenshot_hashes ? Object.keys(finalCheck.post_final_report_qa_screenshot_hashes).length : 0} 项</span>
        </div>
        <div className="delivery-check-card__commands">
          <div>
            <span>本地验收命令</span>
            <code className="delivery-check-card__command">scripts\final-delivery-check.bat</code>
          </div>
          <div>
            <span>源码包验收命令</span>
            <code className="delivery-check-card__command">scripts\final-delivery-check.bat -RequireCleanWorktree</code>
          </div>
        </div>
      </div>
    </div>
  )
}

function SourcePackageCheckRow({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const sourcePackageCheck = finalCheck?.source_package_check ?? '未检查'
  const sourcePackageReadiness = finalCheck?.source_package_readiness ?? '未检查'
  const notRequired = finalCheck?.source_package_check === 'NOT_REQUIRED'
  const ok = sourcePackageCheck === 'PASS' || notRequired
  const label = notRequired
    ? '源码包验收 NOT_REQUIRED（默认本地验收不要求源码包 clean）'
    : `源码包验收 ${sourcePackageCheck} / 工作区 ${sourcePackageReadiness}`

  return <CheckRow label={label} ok={ok} />
}

function shortHash(value?: string | null) {
  return value ? value.slice(0, 12) : '未记录'
}

function FinalCheckFreshnessRow({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const matches = finalCheck?.final_check_matches_current_worktree === true
  const freshness = finalCheck?.final_check_freshness ?? 'unknown'
  const label = matches ? '自检覆盖当前代码' : '自检未覆盖当前代码'
  const detail = matches
    ? '报告 Git 与当前工作区一致。'
    : freshness === 'dirty_worktree'
      ? '当前有未提交改动，报告不能作为源码包证明。'
      : freshness === 'stale_head'
        ? '报告 Git 与当前代码不一致。'
        : '尚无法确认报告与当前代码一致。'

  return (
    <div className={`final-check-freshness-row ${matches ? 'is-current' : 'is-stale'}`}>
      <span>{matches ? 'OK' : '!'}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  )
}

function DeliveryReadinessRow({ readiness }: { readiness: string }) {
  const isBlocked = readiness === 'BLOCKED'
  const isReady = readiness === 'READY'
  const tone = isReady ? 'is-ready' : isBlocked ? 'is-blocked' : 'is-unknown'
  const label = isReady ? '真实 DXM single_save READY' : isBlocked ? '真实 DXM 写入 BLOCKED' : `真实 DXM 写入 ${readiness}`
  const detail = isReady
    ? '仅代表受控单品保存；批量、无人值守和发布仍需单独放行。'
    : isBlocked
      ? '预期阻断，不可执行真实写入。'
      : '状态未知，不可执行真实写入。'

  return (
    <div className={`delivery-readiness-row ${tone}`}>
      <span>{isReady ? 'OK' : isBlocked ? 'LOCK' : '!'}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  )
}

function MetricCard({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone: string }) {
  return (
    <div className={`metric-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  )
}

function ModuleHead({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="module-head">
      <h2>{title}</h2>
      <span>{meta}</span>
    </div>
  )
}

function EmptyState({ title, detail, actions }: { title: string; detail: string; actions?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
      {actions && <div className="next-step-actions">{actions}</div>}
    </div>
  )
}

function ConfigItem({ label, value, hint, empty = false }: { label: string; value: string; hint: string; empty?: boolean }) {
  return (
    <div className={`config-item ${empty ? 'is-empty' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  )
}

function ReferenceTemplateMap({ sections }: { sections: DxmReferenceTemplateSection[] }) {
  return (
    <div className="reference-grid">
      {sections.map((section) => (
        <div key={section.section} className={`reference-cell ${section.templateNames.length ? 'is-ready' : 'is-missing'}`}>
          <div className="reference-cell__head">
            <strong>{referenceSectionLabels[section.section]}</strong>
            <span>{section.required ? '必填' : '可选'}</span>
          </div>
          <code>{section.section}</code>
          <div className="pill-list">
            {section.templateNames.length
              ? section.templateNames.map((name) => <span key={name}>{name}</span>)
              : <span className="is-muted">待后端返回命中模板</span>}
          </div>
          <small>来源：{section.source === 'new' ? 'dxm_reference_templates' : section.source === 'legacy' ? '旧字段兼容' : '默认规则'}</small>
        </div>
      ))}
    </div>
  )
}

function TemplateRow({ template }: { template: Template }) {
  return (
    <tr>
      <td><code>{template.template_type}</code></td>
      <td>{template.template_name}</td>
      <td>{template.binding_scope}</td>
      <td><span className={`status-pill ${template.is_enabled ? 'ok' : 'muted'}`}>{template.is_enabled ? '启用' : '停用'}</span></td>
    </tr>
  )
}

function ProductCard({ product }: { product: Product }) {
  return (
    <article className="product-card">
      <strong>{product.title}</strong>
      <span>{product.category_name} / {product.currency} {product.price}</span>
      <small>SKU {product.sku_count}，图片 {product.image_count}，状态 {product.status}</small>
    </article>
  )
}

function LogRow({ log }: { log: LogItem }) {
  return (
    <article className="timeline-row">
      <span className={`status-pill ${log.level === 'error' ? 'danger' : log.level === 'warning' ? 'warn' : 'ok'}`}>{humanLevel(log.level)}</span>
      <div>
        <strong>{displaySafeLogMessage(log.message)}</strong>
        <small>{formatTime(log.created_at)} / task #{log.task_id}{log.job_id ? ` / job #${log.job_id}` : ''}</small>
      </div>
    </article>
  )
}

function EvidenceRow({ evidence }: { evidence: Evidence }) {
  const grade = evidenceGrade(evidence)
  const url = toArtifactUrl((evidence as Evidence & { file_path_url?: string }).file_path_url ?? evidence.file_path)
  const title = String(evidence.meta?.title ?? evidence.evidence_type)
  const acceptance = String(evidence.meta?.acceptance ?? '等待补齐验收说明')

  return (
    <article className={`evidence-row grade-${grade}`}>
      <div className="grade-badge">{grade}</div>
      <div>
        <strong>{title}</strong>
        <span>{acceptance}</span>
        <small>{formatTime(evidence.created_at)} / {evidence.evidence_type}</small>
      </div>
      {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`查看证据：${title}`}>查看证据</a> : <span className="status-pill muted">无文件</span>}
    </article>
  )
}

function EvidencePointCard({ point }: { point: EvidencePoint }) {
  const title = String(point.action ?? point.state ?? point.kind)
  const ok = point.ok === undefined ? true : point.ok
  const url = toArtifactUrl(point.file_path_url ?? point.file_path)

  return (
    <article className={`evidence-point-card ${ok ? 'ok' : 'warn'}`}>
      <span className="status-pill muted">{point.kind}</span>
      <strong>{title}</strong>
      <small>{point.created_at ? formatTime(point.created_at) : '结构化报告项'}</small>
      {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`查看证据项：${title}`}>查看</a> : <span>无文件</span>}
    </article>
  )
}

function ExceptionCard({ item }: { item: ExceptionItem }) {
  return (
    <article className="exception-card">
      <div className="exception-card__head">
        <strong>{item.title}</strong>
        <span className="status-pill danger">{item.error_code}</span>
      </div>
      <p>{item.detail}</p>
      <small>{item.field_domain} / {item.suggestion}</small>
    </article>
  )
}

function ReportCard({ report }: { report: Report }) {
  const url = toArtifactUrl(report.file_path_url ?? report.file_path)
  return (
    <article className="report-card">
      <div className="report-card__head">
        <strong>{String(report.title ?? report.report_type ?? `报告 #${report.id}`)}</strong>
        <span className="status-pill ok">{String(report.status ?? 'draft')}</span>
      </div>
      <p>{humanReportSummary(report)}</p>
      <div className="report-card__footer">
        <small>{report.created_at ? formatTime(report.created_at) : '待生成时间'}</small>
        {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`打开报告：${String(report.title ?? report.report_type ?? `报告 #${report.id}`)}`}>打开报告</a> : <span>等待文件</span>}
      </div>
    </article>
  )
}

function GradeCard({ grade, title, detail }: { grade: 'A' | 'B' | 'C'; title: string; detail: string }) {
  return (
    <article className={`grade-card grade-${grade}`}>
      <span>{grade}</span>
      <strong>{title}</strong>
      <small>{detail}</small>
    </article>
  )
}

function GapList({ gaps }: { gaps: AcceptanceGap[] }) {
  return (
    <div className="gap-list">
      {gaps.map((gap) => (
        <article key={gap.id} className={`gap-row severity-${gap.severity}`} data-gap-id={gap.id} data-severity={gap.severity}>
          <div>
            <strong>{gap.title}</strong>
            <span>{gap.detail}</span>
          </div>
          <small>{gap.owner} / 证据 {gap.evidenceLevel}</small>
        </article>
      ))}
    </div>
  )
}

function isRealWriteExpectedBlocked(workspace: DeliveryWorkspace) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')

  return l2Gate?.status !== 'passed' || l3Gate?.status !== 'passed'
}

function presentAcceptanceGaps(gaps: AcceptanceGap[], realWriteExpectedBlocked: boolean): AcceptanceGap[] {
  if (!realWriteExpectedBlocked) return gaps

  return gaps.map((gap) => {
    if (!l3PostEvidenceGapIds.has(gap.id)) return gap

    return {
      ...gap,
      title: `L3 后置：${gap.title}`,
      severity: 'watch',
      detail: `${gap.detail}（预期阻断，真实写入放行后再补齐）`,
    }
  })
}

function CheckRow({ label, ok, testId, state }: { label: string; ok: boolean; testId?: string; state?: string }) {
  const tone = state === 'locked' ? 'locked' : ok ? 'ok' : 'warn'
  const marker = state === 'locked' ? 'LOCK' : ok ? '✓' : '!'

  return (
    <div className={`check-row ${tone}`} data-testid={testId} data-state={state}>
      <span aria-hidden="true">{marker}</span>
      <strong>{label}</strong>
    </div>
  )
}

function BusinessReportCheckRow({ count, realWriteExpectedBlocked }: { count: number; realWriteExpectedBlocked: boolean }) {
  if (count === 0 && realWriteExpectedBlocked) {
    return <CheckRow label="业务保存报告 0 份（L3 后置，预期阻断）" ok={false} state={'locked'} />
  }

  return <CheckRow label={`业务保存报告 ${count} 份`} ok={count > 0} state={count > 0 ? 'present' : 'missing'} />
}

function EvidenceCheckRow({ label, count, realWriteExpectedBlocked }: { label: string; count: number; realWriteExpectedBlocked: boolean }) {
  if (count === 0 && realWriteExpectedBlocked) {
    return <CheckRow label={`${label} 0 条（预期阻断）`} ok={false} state={'locked'} />
  }

  return <CheckRow label={`${label} ${count} 条`} ok={count > 0} state={count > 0 ? 'present' : 'missing'} />
}

function PostL3ReportCheckRow({ label, ok, realWriteExpectedBlocked }: { label: string; ok: boolean; realWriteExpectedBlocked: boolean }) {
  if (realWriteExpectedBlocked) {
    return <CheckRow label={`${label}（L3 放行后要求）`} ok={false} state={'locked'} />
  }

  return <CheckRow label={label} ok={ok} state={ok ? 'present' : 'missing'} />
}

function DecisionRow({ label, status, detail }: { label: string; status: string; detail: string }) {
  const ok = status === 'passed'
  return (
    <article className={`decision-row ${ok ? 'is-ok' : 'is-blocked'}`}>
      <div>
        <strong>{label}</strong>
        <span>{detail}</span>
      </div>
      <span className={`status-pill ${gateStatusPill(status)}`}>{humanGateStatus(status)}</span>
    </article>
  )
}

type L2DiagnosticSummary = {
  target: string
  targetLabel: string
  navigation: string
  failedChecks: string[]
  topRequests: string[]
  renderHint: string | null
  reviewCandidateCount: number
  reviewCandidateRequests: string[]
}

function summarizeL2Diagnostics(gate?: RegressionGate): L2DiagnosticSummary[] {
  const latest = asRecord(gate?.latest)
  const targets = asRecord(latest?.realTargets) ?? asRecord(latest?.mockTargets)
  if (!targets) return []
  return Object.entries(targets).map(([target, raw]) => {
    const targetData = asRecord(raw)
    const diagnostics = asRecord(targetData?.diagnostics)
    const navigation = asRecord(diagnostics?.navigation)
    const renderState = asRecord(diagnostics?.render_state)
    const checks = asRecord(diagnostics?.strict_pass_checks)
    const groups = Array.isArray(diagnostics?.blocked_request_groups) ? diagnostics.blocked_request_groups : []
    const reviewCandidates = Array.isArray(diagnostics?.allowlist_review_candidates) ? diagnostics.allowlist_review_candidates : []
    const failedChecks = Object.entries(checks ?? {})
      .filter(([, value]) => value === false)
      .map(([key]) => l2CheckLabel(key))
    const finalPath = stringValue(navigation?.final_path, '未知路径')
    const finalClass = stringValue(navigation?.final_path_class, 'unknown')
    const topRequests = groups.slice(0, 3).map((group) => {
      const item = asRecord(group)
      const count = numberValue(item?.count)
      const method = stringValue(item?.method, 'GET')
      const path = stringValue(item?.path, '未知请求')
      const reason = Array.isArray(item?.reasons) ? item.reasons.join(', ') : 'blocked'
      return `${method} ${path} x${count} / ${reason}`
    })
    const reviewCandidateRequests = reviewCandidates.slice(0, 4).map((candidate) => {
      const item = asRecord(candidate)
      const count = numberValue(item?.count)
      const method = stringValue(item?.method, 'GET')
      const host = stringValue(item?.host, '')
      const path = stringValue(item?.path, '未知请求')
      const reason = Array.isArray(item?.reasons) ? item.reasons.join(', ') : '待人工评审'
      return `${method} ${host}${path} x${count} / ${reason}`
    })
    return {
      target,
      targetLabel: target === 'data_acquisition' ? 'data_acquisition 采集页' : target === 'draft_box' ? 'draft_box 草稿箱' : target,
      navigation: `最终 ${finalPath}（${l2FinalPathLabel(finalClass)}）`,
      failedChecks,
      topRequests,
      renderHint: renderState?.app_shell_only === true ? '页面疑似停留在 app shell/loading，未证明目标模块可达。' : null,
      reviewCandidateCount: reviewCandidates.length,
      reviewCandidateRequests,
    }
  })
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === 'string' && value ? value : fallback
}

function numberValue(value: unknown) {
  return typeof value === 'number' ? value : Number(value) || 0
}

function l2CheckLabel(key: string) {
  return ({
    ok: 'probe 未通过',
    safety_ok: '安全断言失败',
    target_url_matches: '目标 URL 不匹配',
    final_url_matches: '最终路径偏离',
    cookies_loaded: 'cookie 未加载',
    not_login_page: '疑似登录页',
    zero_write: '存在写请求',
    zero_non_read: '存在非只读请求',
    zero_blocked: '存在拦截请求',
    zero_forbidden: '命中禁词 URL',
    zero_websocket: '存在 WebSocket',
  } as Record<string, string>)[key] ?? key
}

function l2FinalPathLabel(value: string) {
  return ({
    home: '回到首页',
    login: '登录页',
    target: '目标页',
    other: '其他路径',
    mock_or_external: '离线/外部',
    unknown: '未知',
  } as Record<string, string>)[value] ?? value
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

function gateStatusPill(status: string) {
  if (status === 'passed' || status === 'ready') return 'ok'
  if (status === 'failed' || status === 'blocked') return 'danger'
  return 'warn'
}

function gateStatusTone(status: string) {
  if (status === 'passed' || status === 'ready') return 'is-ok'
  if (status === 'failed' || status === 'blocked') return 'is-danger'
  return 'is-warn'
}

function buildConsoleSteps(selectedTask: Task | null, logs: LogItem[]) {
  const active = selectedTask?.status === 'running'
  const completed = selectedTask?.status === 'completed'
  const hasLogs = logs.length > 0
  return [
    { title: '配置预检', detail: '店铺、商品、模板、图片与隔离口径', state: hasLogs ? 'done' : 'current' },
    { title: '任务锁定', detail: '绑定商品与批次，不触碰上架入口', state: active || completed ? 'done' : 'pending' },
    { title: '只读诊断', detail: '核对真实页面、字段和截图证据', state: active ? 'current' : completed ? 'done' : 'pending' },
    { title: 'L2 复核', detail: '确认双目标同轮次只读证据', state: completed ? 'done' : 'pending' },
    { title: 'L3 门禁', detail: '需要人工批准与明确保存回包证据', state: completed ? 'done' : 'pending' },
    { title: '报告复盘', detail: '证据等级、异常池、验收缺口归档', state: completed ? 'done' : 'pending' },
  ]
}

function getBrowserFrame(workspace: DeliveryWorkspace, selectedTask: Task | null, agentConsole?: AgentConsoleSession | null) {
  if (agentConsole?.active) {
    const screenshotUrl = withCacheBust(toArtifactUrl(agentConsole.screenshot_url ?? agentConsole.screenshot), agentConsole.last_frame_at)
    return {
      url: agentConsole.current_url || agentConsole.target_url || 'https://www.dianxiaomi.com/',
      screenshotUrl,
      source: screenshotUrl ? '来自 Agent Console 自动刷新画面' : agentConsole.browser_visible ? '来自可见独立 Profile 浏览器会话' : '浏览器会话已创建，等待窗口可见',
    }
  }
  const taskEvidence = selectedTask
    ? workspace.evidences.filter((item) => item.task_id === selectedTask.id)
    : workspace.evidences
  const screenshot = [...taskEvidence]
    .reverse()
    .find((item) => {
      const path = item.file_path ?? ''
      return /\.(png|jpg|jpeg|webp)$/i.test(path)
    })
  const screenshotUrl = screenshot ? toArtifactUrl((screenshot as Evidence & { file_path_url?: string }).file_path_url ?? screenshot.file_path) : ''
  const pageUrl = String(screenshot?.meta?.page_url ?? workspace.evidencePoints.find((point) => point.state)?.page_url ?? '')

  return {
    url: pageUrl || '等待真实浏览器画面',
    screenshotUrl,
    source: screenshotUrl ? '来自最新执行截图' : '等待真实浏览器画面，当前无页面可达证据',
  }
}

function withCacheBust(url: string, stamp?: string | null) {
  if (!url || !stamp) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}frame=${encodeURIComponent(stamp)}`
}

function nextPendingStep(steps: RunStep[], currentCode?: string) {
  if (!steps.length) return null
  const currentIndex = currentCode ? steps.findIndex((step) => step.state === currentCode) : -1
  return steps.slice(Math.max(currentIndex + 1, 0)).find((step) => step.status === 'pending') ?? null
}

function filterEvidencePointsForTask(
  points: EvidencePoint[],
  evidences: Evidence[],
  reports: Report[],
  selectedTask: Task | null,
) {
  if (!selectedTask) return points

  const evidenceIds = new Set(evidences.map((item) => String(item.id)))
  const jobIds = new Set(evidences.map((item) => item.job_id).filter((value): value is number => typeof value === 'number').map(String))
  const reportIds = new Set(reports.map((item) => String(item.id)))

  return points.filter((point) => {
    const explicitTaskId = numberFromUnknown(point.task_id ?? point.taskId)
    if (explicitTaskId !== null) return explicitTaskId === selectedTask.id

    const evidenceId = point.evidence_id ?? point.evidenceId ?? point.id
    if (evidenceId !== undefined && evidenceIds.has(String(evidenceId))) return true

    const jobId = point.job_id ?? point.jobId
    if (jobId !== null && jobId !== undefined && jobIds.has(String(jobId))) return true

    const reportId = point.report_id ?? point.reportId
    if (reportId !== undefined && reportIds.has(String(reportId))) return true

    if (point.kind === 'state_snapshot') return false
    return isStructuredReportPoint(point)
  })
}

function isStructuredReportPoint(point: EvidencePoint) {
  const kind = String(point.kind ?? '').toLowerCase()
  return kind.includes('report') || kind.includes('summary') || kind.includes('publish_guard')
}

function numberFromUnknown(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function requiresManualApproval(task: Task) {
  return isReleasedRealDxmMutationTask(task)
}

function requiresRealL2(task: Task) {
  return isRealDxmMutationTask(task)
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

function l2StartLabel(status?: string) {
  if (status === 'partial') return 'L2 缺目标，禁止启动'
  if (status === 'failed') return 'L2 失败，禁止启动'
  if (status === 'mock_passed') return '等待真实 L2，禁止启动'
  return 'L2 未通过，禁止启动'
}

function displaySafeStepLabel(label: string) {
  return label.includes('只点击保存') ? 'L3 保存门禁待批准' : label
}

function displaySafeStepCode(code: string) {
  return code === 'SAVE_ONLY' ? 'L3_SAVE_GATE' : code
}

function displaySafeWorkflowAction(action: string) {
  return action === 'save_only' || action === 'SAVE_ONLY' ? 'l3_save_gate' : action
}

function displaySafeLogMessage(message: string) {
  return message
    .split('只点击保存').join('L3 保存门禁待批准')
    .split('SAVE_ONLY').join('L3_SAVE_GATE')
}

function humanReportSummary(report: Report) {
  if (typeof report.summary === 'string') return report.summary
  const summary = report.summary && typeof report.summary === 'object' ? report.summary as Record<string, unknown> : {}
  const saveResult = report.save_result && typeof report.save_result === 'object' ? report.save_result as Record<string, unknown> : {}
  return String(summary.blocked_reason ?? summary.status ?? saveResult.message ?? saveResult.msg ?? '等待执行结果补齐')
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
