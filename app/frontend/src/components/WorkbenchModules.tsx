import type {
  AcceptanceGap,
  AgentConsoleSession,
  DeliveryWorkspace,
  DxmReferenceTemplateSection,
  Evidence,
  EvidencePoint,
  ExceptionItem,
  LogItem,
  Product,
  RegressionGate,
  Report,
  RunStep,
  Task,
  Template,
} from '../types'
import { evidenceGrade, humanLevel, humanTaskStatus, referenceSectionLabels, toArtifactUrl } from '../workspace'

type CommonProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
}

type TaskCenterProps = CommonProps & {
  busy: boolean
  onSelectTask: (taskId: number) => void
  onBootstrapDemo: () => void
  onStartTask: () => void
}

type ExecutionConsoleProps = CommonProps & {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  busy: boolean
  onStartAgentConsole: () => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
}

export function Dashboard({ workspace, selectedTask }: CommonProps) {
  const totalJobs = workspace.tasks.reduce((sum, task) => sum + task.total_jobs, 0)
  const completedJobs = workspace.tasks.reduce((sum, task) => sum + task.completed_jobs, 0)
  const failedJobs = workspace.tasks.reduce((sum, task) => sum + task.failed_jobs, 0)
  const blockerCount = workspace.acceptanceGaps.filter((gap) => gap.severity === 'blocker').length
  const referenceReady = workspace.dxmReferenceTemplates.filter((item) => item.templateNames.length).length
  const grade = workspace.evidenceGrade?.grade ?? 'C'

  return (
    <section className="dashboard-grid" aria-label="Dashboard">
      <div className="hero-panel">
        <div>
          <h1>半托管保存交付工作台</h1>
          <p>面向运营交付的桌面工作台：先看配置与任务，再看执行、证据、异常和报告，不暴露任何上架入口。</p>
        </div>
        <div className="hero-panel__status">
          <span>当前批次</span>
          <strong>{selectedTask ? selectedTask.name : '待创建保存核验批次'}</strong>
          <small>{selectedTask ? humanTaskStatus(selectedTask.status) : '可先准备演示数据'}</small>
        </div>
      </div>

      <MetricCard label="商品数" value={workspace.products.length} detail="已进入保存核验视图" tone="blue" />
      <MetricCard label="任务进度" value={`${completedJobs}/${Math.max(totalJobs, 1)}`} detail={`失败 ${failedJobs} 项`} tone="green" />
      <MetricCard label="模板映射" value={`${referenceReady}/${workspace.dxmReferenceTemplates.length}`} detail="dxm_reference_templates 覆盖" tone="yellow" />
      <MetricCard label="证据等级" value={grade} detail={`阻断缺口 ${blockerCount} 项`} tone={grade === 'A' ? 'green' : grade === 'B' ? 'yellow' : 'red'} />

      <div className="module-card span-3">
        <ModuleHead title="回归门禁矩阵" meta="L0-L3" />
        <RegressionGateGrid gates={workspace.regressionGates} />
      </div>

      <div className="module-card span-2">
        <ModuleHead title="真实验收缺口" meta={`${workspace.acceptanceGaps.length} 项`} />
        <GapList gaps={workspace.acceptanceGaps.slice(0, 4)} />
      </div>
      <div className="module-card">
        <ModuleHead title="保存隔离检查" meta="安全条已启用" />
        <div className="check-list">
          <CheckRow label="无上架按钮" ok />
          <CheckRow label="报告记录保存结果" ok={workspace.reports.length > 0} />
          <CheckRow label={`证据等级 ${grade}`} ok={grade === 'A' || grade === 'B'} />
          <CheckRow label="模板来源可追溯" ok={referenceReady > 0} />
        </div>
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

export function ConfigCenter({ workspace }: CommonProps) {
  const product = workspace.products[0]
  const enabledTemplates = workspace.templates.filter((item) => item.is_enabled)
  const templateResults = workspace.templateResolution?.dxm_reference_template_results ?? {}

  return (
    <section className="module-layout" aria-label="配置中心">
      <div className="module-card span-2">
        <ModuleHead title="配置中心" meta={`${enabledTemplates.length} 个启用模板`} />
        <div className="config-matrix">
          <ConfigItem label="店铺" value={workspace.stores[0]?.name ?? 'Dang Kang'} hint={workspace.stores[0]?.platform ?? 'AliExpress'} />
          <ConfigItem label="类目" value={product?.category_name ?? '立牌类谷子'} hint="用于匹配属性和模板范围" />
          <ConfigItem label="图片银行" value={product?.image?.eu_outer_package_filename ?? '待补外包装图'} hint="欧盟外包装/标签实拍图" />
          <ConfigItem label="执行模式" value="single_save" hint="保存核验，不走上架动作" />
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="dxm_reference_templates 映射" meta={`${Object.keys(templateResults).length} 段已有执行结果`} />
        <ReferenceTemplateMap sections={workspace.dxmReferenceTemplates} />
      </div>

      <div className="module-card span-3">
        <ModuleHead title="模板清单" meta="现有 API + fallback" />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>类型</th>
                <th>模板名</th>
                <th>绑定范围</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {workspace.templates.map((template) => (
                <TemplateRow key={template.id} template={template} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

export function TaskCenter({ workspace, selectedTask, busy, onSelectTask, onBootstrapDemo, onStartTask }: TaskCenterProps) {
  const needsApproval = selectedTask ? requiresManualApproval(selectedTask) : false
  const startDisabled = busy || !selectedTask || needsApproval
  return (
    <section className="module-layout" aria-label="任务中心">
      <div className="module-card span-2">
        <ModuleHead title="任务中心" meta={`${workspace.tasks.length} 个批次`} />
        <div className="toolbar">
          <button className="button button--secondary" type="button" onClick={onBootstrapDemo} disabled={busy}>
            准备运营演示数据
          </button>
          <button className="button button--primary" type="button" onClick={onStartTask} disabled={startDisabled}>
            {needsApproval ? '等待人工批准' : '启动保存核验任务'}
          </button>
        </div>
        {needsApproval && (
          <div className="approval-note">
            L3 真实保存写操作必须先由后端人工批准令牌解锁；当前工作台不会直接启动 single_save/batch_save。
          </div>
        )}
        <div className="task-list">
          {workspace.tasks.map((task) => (
            <button
              key={task.id}
              type="button"
              className={`task-row ${selectedTask?.id === task.id ? 'is-selected' : ''}`}
              onClick={() => onSelectTask(task.id)}
            >
              <div>
                <strong>{task.name}</strong>
                <span>{task.payload.store_name ?? workspace.stores[0]?.name ?? 'Dang Kang'} / {task.payload.category_name ?? '未指定类目'}</span>
              </div>
              <div className="task-row__meta">
                <span>{humanTaskStatus(task.status)}</span>
                <small>{task.completed_jobs}/{Math.max(task.total_jobs, 1)} 完成</small>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="module-card">
        <ModuleHead title="商品队列" meta={`${workspace.products.length} 个商品`} />
        <div className="product-list">
          {workspace.products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="任务验收口径" meta="运营可读" />
        <div className="acceptance-strip">
          <span>先验证配置完整性</span>
          <span>再启动保存核验</span>
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
  busy,
  onStartAgentConsole,
  onStopAgentConsole,
  onSnapshotAgentConsole,
}: ExecutionConsoleProps) {
  const taskLogs = selectedTask ? workspace.logs.filter((item) => item.task_id === selectedTask.id) : workspace.logs
  const steps = workspace.deliverySteps.length
    ? workspace.deliverySteps.map((step) => ({
      title: step.label,
      code: step.state,
      detail: `${step.state}${step.evidence_count ? ` / 证据 ${step.evidence_count}` : ''}${step.workflow_actions?.length ? ` / ${step.workflow_actions.join(', ')}` : ''}`,
      state: step.status === 'completed' ? 'done' : step.status === 'running' ? 'current' : step.status === 'failed' ? 'blocked' : 'pending',
    }))
    : buildConsoleSteps(selectedTask, workspace.logs)
  const activeStep = steps.find((step) => step.state === 'current' || step.state === 'blocked') ?? steps.find((step) => step.state === 'pending') ?? steps[0]
  const browserFrame = getBrowserFrame(workspace, selectedTask, agentConsole)

  return (
    <section className="agent-console-layout" aria-label="执行控制台">
      <div className="module-card agent-console-stage">
        <ModuleHead
          title="Agent Console"
          meta={agentConsole?.active ? `会话 ${agentConsole.session_id}` : '独立 Profile 浏览器 / 可见执行'}
        />
        <AgentConsoleControls
          agentConsole={agentConsole}
          agentConsoleError={agentConsoleError}
          selectedTask={selectedTask}
          busy={busy}
          onStartAgentConsole={onStartAgentConsole}
          onStopAgentConsole={onStopAgentConsole}
          onSnapshotAgentConsole={onSnapshotAgentConsole}
        />
        <AgentBrowserFrame
          workspace={workspace}
          selectedTask={selectedTask}
          activeStep={activeStep}
          browserFrame={browserFrame}
          agentConsole={agentConsole}
        />
      </div>

      <div className="module-card span-2">
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
      </div>

      <div className="module-card">
        <ModuleHead title="实时摘要" meta="只读观察" />
        <div className="console-summary">
          <strong>{selectedTask ? humanTaskStatus(selectedTask.status) : '待启动'}</strong>
          <span>{agentConsole?.active ? '可见浏览器会话已建立，右上 HUD 会展示当前步骤。' : '可先打开独立 Profile 浏览器，用户旁观自动化动作。'}</span>
          <span>HUD 只展示步骤和安全状态，不提供发布入口。</span>
          {(agentConsoleError || agentConsole?.last_error) && <span className="console-error">{agentConsoleError || agentConsole?.last_error}</span>}
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="执行日志" meta={`${taskLogs.length} 条`} />
        <div className="timeline-list">
          {taskLogs.map((log) => (
            <LogRow key={log.id} log={log} />
          ))}
        </div>
      </div>
    </section>
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
  const storeName = (hasConsoleHud ? hud?.store_name : null) ?? selectedTask?.payload.store_name ?? workspace.stores[0]?.name ?? 'Dang Kang'
  const hudTitle = (hasConsoleHud ? hud?.title ?? hud?.label : null) ?? activeStep?.title ?? '等待任务'
  const hudState = (hasConsoleHud ? hud?.state ?? hud?.code : null) ?? activeStep?.code ?? 'WAITING'
  const hudAction = (hasConsoleHud ? hud?.action ?? hud?.detail : null) ?? activeStep?.detail ?? '等待后端推送步骤'
  const hudNext = (hasConsoleHud ? hud?.next_step : null) ?? nextStep?.label ?? '等待状态机推进'
  const hudGuard = (hasConsoleHud ? hud?.guard : null) ?? (workspace.publishGuardState?.safe ? '通过' : '等待证明')
  const hudDotState = agentConsole?.last_error ? 'blocked' : agentConsole?.active ? 'current' : activeStep?.state ?? 'pending'
  const product = workspace.products[0]

  return (
    <div className="agent-browser">
      <div className="agent-browser__chrome">
        <div className="traffic-lights" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="browser-tab">店小秘 Agent Console</div>
        <div className="browser-url">{browserFrame.url}</div>
        <span className={`status-pill ${agentConsole?.browser_visible ? 'ok' : 'muted'}`}>
          {agentConsole?.browser_visible ? '可见浏览器' : 'Profile 待命'}
        </span>
      </div>
      <div className="agent-browser__viewport">
        {browserFrame.screenshotUrl ? (
          <img src={browserFrame.screenshotUrl} alt="当前真实浏览器截图" />
        ) : (
          <div className="browser-placeholder">
            <div className="dxm-topbar">
              <strong>店小秘</strong>
              <span>产品编辑 / 速卖通 / 半托管</span>
            </div>
            <div className="dxm-toolbar">
              <span>Dang Kang</span>
              <span>{product?.category_name ?? '立牌类谷子'}</span>
              <span>保存核验</span>
            </div>
            <div className="dxm-form-grid">
              <div>
                <label>商品标题</label>
                <strong>{product?.title ?? '等待真实商品'}</strong>
              </div>
              <div>
                <label>图片银行</label>
                <strong>{product?.image?.eu_outer_package_filename ?? '等待外包装图'}</strong>
              </div>
              <div>
                <label>半托管</label>
                <strong>待进入半托管信息页</strong>
              </div>
              <div>
                <label>保存策略</label>
                <strong>只保存，不发布</strong>
              </div>
            </div>
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
        <span>{browserFrame.source}</span>
        <span>{agentConsole?.profile_dir ? `Profile: ${agentConsole.profile_dir}` : '等待启动独立浏览器 Profile'}</span>
      </div>
    </div>
  )
}

function AgentConsoleControls({
  agentConsole,
  agentConsoleError,
  selectedTask,
  busy,
  onStartAgentConsole,
  onStopAgentConsole,
  onSnapshotAgentConsole,
}: {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  selectedTask: Task | null
  busy: boolean
  onStartAgentConsole: () => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
}) {
  const active = Boolean(agentConsole?.active)
  const screenshot = agentConsole?.screenshot_url ?? agentConsole?.screenshot ?? ''
  return (
    <div className="agent-console-controls">
      <div className="agent-console-controls__status">
        <span className={`status-pill ${active ? 'ok' : 'muted'}`}>{active ? '浏览器会话中' : '未打开浏览器'}</span>
        <span className={`status-pill ${agentConsole?.browser_visible ? 'ok' : active ? 'warn' : 'muted'}`}>
          {agentConsole?.browser_visible ? '窗口可见' : '窗口未显示'}
        </span>
        <span className="status-pill ok">只保存不发布</span>
      </div>
      <div className="agent-console-controls__fields">
        <StatusField label="session_id" value={agentConsole?.session_id} />
        <StatusField label="last_step" value={agentConsole?.last_step_code ?? agentConsole?.hud?.state} />
        <StatusField label="profile_dir" value={agentConsole?.profile_dir} />
        <StatusField label="current_url" value={agentConsole?.current_url ?? agentConsole?.target_url} />
        <StatusField label="screenshot" value={screenshot} />
      </div>
      <div className="agent-console-controls__actions">
        <button className="button button--primary" type="button" onClick={onStartAgentConsole} disabled={busy || !selectedTask}>
          打开可见浏览器
        </button>
        <button className="button button--quiet" type="button" onClick={onSnapshotAgentConsole} disabled={busy || !active}>
          抓取当前截图
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

export function EvidenceTimeline({ workspace, selectedTask }: CommonProps) {
  const evidences = selectedTask ? workspace.evidences.filter((item) => item.task_id === selectedTask.id) : workspace.evidences
  const evidencePoints = workspace.evidencePoints.filter((item) => !item.id || evidences.some((evidence) => evidence.id === item.id) || item.kind !== 'state_snapshot')

  return (
    <section className="module-layout" aria-label="证据中心">
      <div className="module-card span-3">
        <ModuleHead title="交付证据摘要" meta={`等级 ${workspace.evidenceGrade?.grade ?? 'C'}`} />
        <div className="evidence-point-grid">
          {evidencePoints.slice(0, 8).map((point, index) => (
            <EvidencePointCard key={`${point.kind}-${point.id ?? index}`} point={point} />
          ))}
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="原始证据" meta={`${evidences.length} 条`} />
        <div className="evidence-timeline">
          {evidences.map((evidence) => (
            <EvidenceRow key={evidence.id} evidence={evidence} />
          ))}
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

export function ExceptionQueue({ workspace }: CommonProps) {
  return (
    <section className="module-layout" aria-label="异常池">
      <div className="module-card span-2">
        <ModuleHead title="异常池" meta={`${workspace.exceptions.length} 条异常`} />
        <div className="exception-list">
          {workspace.exceptions.map((item) => (
            <ExceptionCard key={item.id} item={item} />
          ))}
        </div>
      </div>
      <div className="module-card">
        <ModuleHead title="真实验收缺口" meta={`${workspace.acceptanceGaps.length} 项`} />
        <GapList gaps={workspace.acceptanceGaps} />
      </div>
    </section>
  )
}

export function ReportCenter({ workspace, selectedTask }: CommonProps) {
  const reports = selectedTask ? workspace.reports.filter((item) => item.task_id === selectedTask.id) : workspace.reports
  const reportSummary = workspace.reportSummary

  return (
    <section className="module-layout" aria-label="报告中心">
      <div className="module-card span-3">
        <ModuleHead title="保存隔离摘要" meta={workspace.publishGuardState?.status ?? '等待执行'} />
        <div className="report-check-grid">
          <CheckRow label={`报告 ${reportSummary?.total_reports ?? reports.length} 份`} ok={(reportSummary?.total_reports ?? reports.length) > 0} />
          <CheckRow label={`保存结果 ${reportSummary?.save_results?.length ?? 0} 条`} ok={Boolean(reportSummary?.save_results?.length)} />
          <CheckRow label={`未发布证明 ${reportSummary?.published_proofs?.length ?? 0} 条`} ok={Boolean(reportSummary?.published_proofs?.length)} />
          <CheckRow label={`网络/HAR ${((reportSummary?.network_save_results?.length ?? 0) + (reportSummary?.har_summaries?.length ?? 0))} 条`} ok={Boolean((reportSummary?.network_save_results?.length ?? 0) + (reportSummary?.har_summaries?.length ?? 0))} />
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="报告中心" meta={`${reports.length} 份报告`} />
        <div className="report-grid">
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="报告必须覆盖" meta="交付检查表" />
        <div className="report-check-grid">
          <CheckRow label="配置模板命中" ok={workspace.dxmReferenceTemplates.some((item) => item.templateNames.length)} />
          <CheckRow label="执行步骤与结果" ok={workspace.logs.length > 0} />
          <CheckRow label="证据等级 A/B/C" ok={workspace.evidences.length > 0} />
          <CheckRow label="异常和验收缺口" ok={workspace.acceptanceGaps.length > 0} />
        </div>
      </div>
    </section>
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

function ConfigItem({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="config-item">
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
          <small>来源：{section.source === 'new' ? 'dxm_reference_templates' : section.source === 'legacy' ? '旧字段兼容' : 'fallback'}</small>
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
        <strong>{log.message}</strong>
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
      {url ? <a href={url} target="_blank" rel="noreferrer">查看证据</a> : <span className="status-pill muted">无文件</span>}
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
      {url ? <a href={url} target="_blank" rel="noreferrer">查看</a> : <span>无文件</span>}
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
        {url ? <a href={url} target="_blank" rel="noreferrer">打开报告</a> : <span>等待文件</span>}
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
        <article key={gap.id} className={`gap-row severity-${gap.severity}`}>
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

function CheckRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className={`check-row ${ok ? 'ok' : 'warn'}`}>
      <span aria-hidden="true">{ok ? '✓' : '!'}</span>
      <strong>{label}</strong>
    </div>
  )
}

function humanGateStatus(status: string) {
  return ({
    ready: '已就绪',
    not_run: '未运行',
    mock_passed: '离线通过',
    passed: '通过',
    failed: '失败',
    approval_required: '需批准',
  } as Record<string, string>)[status] ?? status
}

function gateStatusPill(status: string) {
  if (status === 'passed' || status === 'ready' || status === 'mock_passed') return 'ok'
  if (status === 'failed') return 'danger'
  return 'warn'
}

function gateStatusTone(status: string) {
  if (status === 'passed' || status === 'ready' || status === 'mock_passed') return 'is-ok'
  if (status === 'failed') return 'is-danger'
  return 'is-warn'
}

function buildConsoleSteps(selectedTask: Task | null, logs: LogItem[]) {
  const active = selectedTask?.status === 'running'
  const completed = selectedTask?.status === 'completed'
  const hasLogs = logs.length > 0
  return [
    { title: '配置预检', detail: '店铺、商品、模板、图片与保存隔离口径', state: hasLogs ? 'done' : 'current' },
    { title: '任务领取', detail: '绑定商品与批次，不触碰上架入口', state: active || completed ? 'done' : 'pending' },
    { title: '普通编辑', detail: '标题、类目、SKU、图片、合规字段核验', state: active ? 'current' : completed ? 'done' : 'pending' },
    { title: '半托管补齐', detail: '半托管货品、服务、运费和责任人字段', state: completed ? 'done' : 'pending' },
    { title: '保存核验', detail: '保存结果、隔离结果和截图证据', state: completed ? 'done' : 'pending' },
    { title: '报告复盘', detail: '证据等级、异常池、验收缺口归档', state: completed ? 'done' : 'pending' },
  ]
}

function getBrowserFrame(workspace: DeliveryWorkspace, selectedTask: Task | null, agentConsole?: AgentConsoleSession | null) {
  if (agentConsole?.active) {
    const screenshotUrl = toArtifactUrl(agentConsole.screenshot_url ?? agentConsole.screenshot)
    return {
      url: agentConsole.current_url || agentConsole.target_url || 'https://www.dianxiaomi.com/',
      screenshotUrl,
      source: screenshotUrl ? '来自 Agent Console 当前截图' : agentConsole.browser_visible ? '来自可见独立 Profile 浏览器会话' : '浏览器会话已创建，等待窗口可见',
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
    url: pageUrl || 'https://www.dianxiaomi.com/smt/product/edit',
    screenshotUrl,
    source: screenshotUrl ? '来自最新执行截图' : '原型占位画面，等待真实浏览器会话',
  }
}

function nextPendingStep(steps: RunStep[], currentCode?: string) {
  if (!steps.length) return null
  const currentIndex = currentCode ? steps.findIndex((step) => step.state === currentCode) : -1
  return steps.slice(Math.max(currentIndex + 1, 0)).find((step) => step.status === 'pending') ?? null
}

function requiresManualApproval(task: Task) {
  return task.mode === 'single_save' || task.mode === 'batch_save'
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
