import type React from 'react'
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
  onShowConsole: () => void
  onShowEvidence: () => void
}

type ExecutionConsoleProps = CommonProps & {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  busy: boolean
  onStartAgentConsole: () => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onShowTasks: () => void
  onShowEvidence: () => void
}

export function Dashboard({ workspace, selectedTask }: CommonProps) {
  const totalJobs = workspace.tasks.reduce((sum, task) => sum + task.total_jobs, 0)
  const completedJobs = workspace.tasks.reduce((sum, task) => sum + task.completed_jobs, 0)
  const failedJobs = workspace.tasks.reduce((sum, task) => sum + task.failed_jobs, 0)
  const blockerCount = workspace.acceptanceGaps.filter((gap) => gap.severity === 'blocker').length
  const referenceReady = workspace.dxmReferenceTemplates.filter((item) => item.templateNames.length).length
  const grade = workspace.evidenceGrade?.grade ?? 'C'
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
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
          <h1>半托管保存交付工作台</h1>
          <p>面向运营交付的桌面工作台：先看配置与任务，再看执行、证据、异常和报告，不暴露任何上架入口。</p>
        </div>
        <div className="hero-panel__status">
          <span>当前批次</span>
          <strong>{selectedTask ? selectedTask.name : '待创建保存核验批次'}</strong>
          <small>{nextAction} / {selectedTask ? humanTaskStatus(selectedTask.status) : '可先准备演示数据'}</small>
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
  const hasStores = workspace.stores.length > 0
  const hasProducts = workspace.products.length > 0

  return (
    <section className="module-layout" aria-label="配置中心">
      <div className="module-card span-2">
        <ModuleHead title="配置中心" meta={`${enabledTemplates.length} 个启用模板`} />
        <div className="config-matrix">
          <ConfigItem label="店铺" value={workspace.stores[0]?.name ?? '未配置真实店铺'} hint={workspace.stores[0]?.platform ?? '等待 /api/stores 返回'} empty={!hasStores} />
          <ConfigItem label="类目" value={product?.category_name ?? '未绑定真实商品类目'} hint="用于匹配属性和模板范围" empty={!hasProducts} />
          <ConfigItem label="图片银行" value={product?.image?.eu_outer_package_filename ?? '未绑定真实外包装图'} hint="欧盟外包装/标签实拍图" empty={!hasProducts} />
          <ConfigItem label="执行模式" value="single_save" hint="保存核验，不走上架动作" />
        </div>
        {(!hasStores || !hasProducts) && (
          <EmptyState
            title="暂无真实店铺/商品配置"
            detail="当前未从接口读取到 stores/products，不展示 Dang Kang 或立牌类谷子默认值以免误判为已配置。"
          />
        )}
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

export function TaskCenter({ workspace, selectedTask, busy, onSelectTask, onBootstrapDemo, onStartTask, onShowConsole, onShowEvidence }: TaskCenterProps) {
  const needsApproval = selectedTask ? requiresManualApproval(selectedTask) : false
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const needsRealL2 = selectedTask ? requiresRealL2(selectedTask) : false
  const l2BlocksStart = needsRealL2 && l2Gate?.status !== 'passed'
  const l3BlocksStart = l3Gate?.status === 'blocked'
  const l2DiagnosticSummaries = summarizeL2Diagnostics(l2Gate)
  const startDisabled = busy || !selectedTask || needsApproval || l2BlocksStart || l3BlocksStart
  const startLabel = !selectedTask
    ? '请选择任务'
    : l2BlocksStart
      ? l2StartLabel(l2Gate?.status)
      : needsApproval
        ? '等待人工批准'
        : '启动保存核验任务'
  return (
    <section className="module-layout" aria-label="任务中心">
      <div className="module-card span-2">
        <ModuleHead title="任务中心" meta={`${workspace.tasks.length} 个批次`} />
        <div className="toolbar">
          <button className="button button--secondary" type="button" onClick={onBootstrapDemo} disabled={busy}>
            创建演示批次（写入本地）
          </button>
          <button className="button button--primary" type="button" onClick={onStartTask} disabled={startDisabled}>
            {startLabel}
          </button>
        </div>
        {(l2BlocksStart || l3BlocksStart) && (
          <div className="gate-note gate-note--danger">
            <strong>真实保存已阻断</strong>
            <span>{l2Gate?.detail ?? '需要 data_acquisition 与 draft_box 两个真实只读检查均通过。'}</span>
            {l3BlocksStart && <span>{l3Gate?.detail ?? 'L3 已阻断，必须先解除发布隔离风险。'}</span>}
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowConsole}>查看只读诊断</button>
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
            L3 真实写操作必须先由后端人工批准令牌解锁；当前工作台不会直接启动 claim_only/single_save/batch_save。
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
                <span>{task.payload.store_name ?? workspace.stores[0]?.name ?? '未绑定店铺'} / {task.payload.category_name ?? '未指定类目'}</span>
              </div>
              <div className="task-row__meta">
                <span>{humanTaskStatus(task.status)}</span>
                <small>{task.completed_jobs}/{Math.max(task.total_jobs, 1)} 完成</small>
              </div>
            </button>
          ))}
          {!workspace.tasks.length && (
            <EmptyState title="暂无保存核验批次" detail="可创建一条本地演示批次；真实任务接入后会显示店铺、类目和商品数。" />
          )}
        </div>
      </div>

      <div className="module-card">
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
              ? 'L3 已阻断：真实保存必须停止并复核 publish guard。'
              : 'L3 真实写操作仍需要人工批准令牌，approval_required 不是已通过。'}
          />
          <div className="gate-note">
            当前按钮策略：L2 非 passed 或 L3 blocked 时保持阻断；即使 L2 通过，claim_only/single_save/batch_save 仍需后端人工批准。
          </div>
        </div>
      </div>

      <div className="module-card">
        <ModuleHead title="商品队列" meta={`${workspace.products.length} 个商品`} />
        <div className="product-list">
          {workspace.products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
          {!workspace.products.length && (
            <EmptyState title="暂无商品" detail="准备演示数据后会生成一条保存核验商品；真实导入后这里展示待保存队列。" />
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
  busy,
  onStartAgentConsole,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onShowTasks,
  onShowEvidence,
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
    ? l2Gate?.detail ?? 'L2 真实只读 probe 未通过。'
    : l3Gate?.detail ?? 'L3 未完成批准或验收。'
  const diagnosticBlocked = l2Gate?.status !== 'passed'
  const diagnosticBlockReason = l2Gate?.detail ?? 'L2 真实只读 probe 未通过。'

  return (
    <section className="agent-console-layout" aria-label="执行控制台">
      <div className="module-card agent-console-stage">
        <ModuleHead
          title="Agent Console"
          meta={agentConsole?.active ? `会话 ${agentConsole.session_id}` : '只读诊断浏览器 / 不启动保存'}
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
          onStopAgentConsole={onStopAgentConsole}
          onSnapshotAgentConsole={onSnapshotAgentConsole}
        />
        {realSaveBlocked && (
          <div className="gate-note gate-note--danger">
            <strong>下一步</strong>
            <span>{realSaveBlockReason}</span>
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowTasks}>回到任务门禁</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
            </div>
          </div>
        )}
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
          <span>{diagnosticBlocked ? '当前仅可查看 L2 诊断与证据，禁止打开真实浏览器/L3。' : realSaveBlocked ? '可打开只读诊断浏览器；真实保存/L3 仍禁止启动。' : agentConsole?.active ? '只读诊断浏览器会话已建立，右上 HUD 会展示当前安全状态。' : '门禁满足后可打开只读诊断浏览器。'}</span>
          <span>HUD 只展示诊断步骤和安全状态，不提供保存或发布入口。</span>
          {(agentConsoleError || agentConsole?.last_error) && <span className="console-error">{agentConsoleError || agentConsole?.last_error}</span>}
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="执行日志" meta={`${taskLogs.length} 条`} />
        <div className="timeline-list">
          {taskLogs.map((log) => (
            <LogRow key={log.id} log={log} />
          ))}
          {!taskLogs.length && (
            <EmptyState title="暂无执行日志" detail="当前仅可查看 L2 诊断与证据；L2 未通过时禁止启动真实保存/L3。" />
          )}
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
  const storeName = (hasConsoleHud ? hud?.store_name : null) ?? selectedTask?.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺'
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
        ) : agentConsole?.active || agentConsole?.updated_at ? (
          <div className="browser-placeholder">
            <div className="dxm-topbar">
              <strong>店小秘</strong>
              <span>诊断占位 / 非真实页面证据</span>
            </div>
            <div className="dxm-toolbar">
              <span>{storeName}</span>
              <span>{product?.category_name ?? '等待真实类目'}</span>
              <span>只读诊断</span>
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
                <label>当前口径</label>
                <strong>原型占位，不代表页面可达</strong>
              </div>
            </div>
          </div>
        ) : (
          <div className="browser-empty-state">
            <strong>尚未打开真实诊断浏览器</strong>
            <span>当前不展示仿真店小秘页面，也不把商品信息伪装成浏览器证据。</span>
            <small>请先通过 L2/L3 门禁；未通过时只能查看诊断和证据缺口。</small>
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
  realSaveBlocked,
  realSaveBlockReason,
  diagnosticBlocked,
  diagnosticBlockReason,
  onStartAgentConsole,
  onStopAgentConsole,
  onSnapshotAgentConsole,
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
        <span className="status-pill warn">只读诊断</span>
      </div>
      <div className="agent-console-controls__fields">
        <StatusField label="session_id" value={agentConsole?.session_id} />
        <StatusField label="last_step" value={agentConsole?.last_step_code ?? agentConsole?.hud?.state} />
        <StatusField label="profile_dir" value={agentConsole?.profile_dir} />
        <StatusField label="current_url" value={agentConsole?.current_url ?? agentConsole?.target_url} />
        <StatusField label="screenshot" value={screenshot} />
      </div>
      <div className="agent-console-controls__actions">
        <button
          className="button button--secondary"
          type="button"
          onClick={onStartAgentConsole}
          disabled={busy || !selectedTask || diagnosticBlocked}
          title={diagnosticBlocked ? diagnosticBlockReason : realSaveBlocked ? realSaveBlockReason : '仅打开只读诊断浏览器，不启动保存'}
        >
          {diagnosticBlocked ? 'L2 未通过，禁止打开诊断浏览器' : '打开只读诊断浏览器'}
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
              detail="保存结果、未发布证明和网络/HAR 摘要齐全后才会形成 A/B/C 证据等级。"
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
        <ModuleHead title="真实验收缺口" meta={`${workspace.acceptanceGaps.length} 项`} />
        <GapList gaps={workspace.acceptanceGaps} />
      </div>
    </section>
  )
}

export function ReportCenter({
  workspace,
  selectedTask,
  onShowEvidence,
  onShowConsole,
}: CommonProps & { onShowEvidence: () => void; onShowConsole: () => void }) {
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
          {!reports.length && (
            <EmptyState
              title="暂无报告"
              detail="L3 金丝雀完成并生成未发布证明后，这里会展示报告和证据路径。当前可先查看 L2 诊断和证据缺口。"
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
      <div className="module-card span-3">
        <ModuleHead title="报告必须覆盖" meta="交付检查表" />
        <div className="report-check-grid">
          <CheckRow label="配置模板命中" ok={workspace.dxmReferenceTemplates.some((item) => item.templateNames.length)} />
          <CheckRow label="执行步骤与结果" ok={workspace.logs.length > 0} />
          <CheckRow label="证据等级 A/B/C" ok={workspace.evidences.length > 0} />
          <CheckRow label="验收缺口已列明" ok={workspace.acceptanceGaps.length > 0} />
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

function EmptyState({ title, detail, actions }: { title: string; detail: string; actions?: React.ReactNode }) {
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
    return {
      target,
      targetLabel: target === 'data_acquisition' ? 'data_acquisition 采集页' : target === 'draft_box' ? 'draft_box 草稿箱' : target,
      navigation: `最终 ${finalPath}（${l2FinalPathLabel(finalClass)}）`,
      failedChecks,
      topRequests,
      renderHint: renderState?.app_shell_only === true ? '页面疑似停留在 app shell/loading，未证明目标模块可达。' : null,
      reviewCandidateCount: reviewCandidates.length,
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
    mock_passed: '离线通过',
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
    url: pageUrl || '等待真实只读诊断截图',
    screenshotUrl,
    source: screenshotUrl ? '来自最新执行截图' : '原型占位画面，非真实页面可达证据',
  }
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
  return task.mode === 'single_save' || task.mode === 'batch_save'
}

function requiresRealL2(task: Task) {
  return task.mode === 'single_save' || task.mode === 'batch_save'
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
    .replaceAll('只点击保存', 'L3 保存门禁待批准')
    .replaceAll('SAVE_ONLY', 'L3_SAVE_GATE')
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
