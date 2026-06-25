import type {
  DeliveryWorkspace,
  DesktopRuntimeInfo,
  FinalDeliveryCheckSummary,
  RegressionGate,
  RuntimeStatus,
  Task,
} from '../../types'
import { humanTaskStatus } from '../../workspace'

type SystemSettingsPageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  finalCheck: FinalDeliveryCheckSummary | null
  runtimeStatus: RuntimeStatus | null
  desktopRuntime: DesktopRuntimeInfo | null
}

const LEGACY_QA_REAL_MUTATION_TASK_NAME = ['QA guarded', 'real mutation task'].join(' ')

export function SystemSettingsPage({
  workspace,
  selectedTask,
  finalCheck,
  runtimeStatus,
  desktopRuntime,
}: SystemSettingsPageProps) {
  const releasedMode = workspace.realModeReleasePlan.modes.find((mode) => mode.allowed)
  const backendStatus = runtimeStatus?.backend?.status ?? 'unknown'
  const frontendStatus = runtimeStatus?.frontend?.status ?? (desktopRuntime?.frontendPath ? 'desktop_file' : 'unknown')
  const browserStatus = runtimeStatus?.realBrowser?.browserVisible
    ? runtimeStatus.realBrowser.source === 'dxm_flow' ? '真实业务浏览器已打开' : '真实浏览器已打开'
    : runtimeStatus?.realBrowser?.browserLaunching
      ? '真实浏览器启动中'
      : runtimeStatus?.realBrowser?.active
        ? '真实浏览器会话已建立'
      : '真实浏览器未打开'
  const finalCheckStatus = finalCheck?.status === 'available'
    ? `最近验收：${finalCheck.checked_at ? new Date(finalCheck.checked_at).toLocaleString('zh-CN', { hour12: false }) : '已读取'}`
    : '最近验收：未读取'

  return (
    <section className="module-layout" aria-label="系统设置">
      <div className="module-card span-3">
        <ModuleHead title="系统设置" meta="服务状态、日志路径和技术诊断" />
        <div className="settings-summary-grid">
          <div className="settings-summary-card">
            <span>当前可执行范围</span>
            <strong>{releasedMode?.label ?? '单商品只保存'}</strong>
            <small>只保存，不发布；批量、无人值守和发布入口保持关闭。</small>
          </div>
          <div className="settings-summary-card">
            <span>当前任务</span>
            <strong>{selectedTask ? displayTaskName(selectedTask) : '未选择任务'}</strong>
            <small>{selectedTask ? humanTaskStatus(selectedTask.status) : '请先在选择商品中创建或选择任务'}</small>
          </div>
          <div className="settings-summary-card">
            <span>真实浏览器</span>
            <strong>{browserStatus}</strong>
            <small>真实店小秘操作只发生在独立可见浏览器窗口内。</small>
          </div>
        </div>
      </div>

      <div className="module-card span-2">
        <ModuleHead title="运行状态" meta={finalCheckStatus} />
        <div className="check-list">
          <CheckRow label={`后端服务：${humanRuntimeServiceStatus(backendStatus)}`} ok={isRuntimeServiceOk(backendStatus)} />
          <CheckRow label={`前端页面：${humanRuntimeServiceStatus(frontendStatus)}`} ok={isRuntimeServiceOk(frontendStatus)} />
          <CheckRow label="发布入口关闭" ok={workspace.realModeReleasePlan.publish_allowed === false} />
          <CheckRow label="无人值守关闭" ok={workspace.realModeReleasePlan.batch_unattended_publish_allowed === false} />
        </div>
      </div>

      <details className="module-card disclosure-card">
        <summary>
          日志和本机路径
          <span>排障时展开</span>
        </summary>
        <div className="settings-path-list">
          <div><span>后端日志</span><code>{desktopRuntime?.backendLogPath ?? '运行后生成'}</code></div>
          <div><span>桌面日志</span><code>{desktopRuntime?.desktopLogPath ?? '运行后生成'}</code></div>
          <div><span>服务地址</span><code>{runtimeStatus?.backend?.url ?? desktopRuntime?.apiBase ?? '等待服务启动'}</code></div>
        </div>
      </details>

      <details className="module-card span-3 disclosure-card">
        <summary>
          技术诊断
          <span>维护人员使用</span>
        </summary>
        <RegressionGateGrid gates={workspace.regressionGates} />
        <p>验收状态用于判断当前版本能否交付受控单商品只保存路径；不扩大为批量、无人值守或发布能力。</p>
      </details>
    </section>
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

function CheckRow({ label, ok, testId, state }: { label: string; ok: boolean; testId?: string; state?: string }) {
  const tone = state === 'locked' ? 'locked' : ok ? 'ok' : 'warn'
  const marker = state === 'locked' ? '暂停' : ok ? '✓' : '!'

  return (
    <div className={`check-row ${tone}`} data-testid={testId} data-state={state}>
      <span aria-hidden="true">{marker}</span>
      <strong>{label}</strong>
    </div>
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

function displayTaskName(task: Pick<Task, 'name' | 'mode'>) {
  if (task.mode === 'single_save' && task.name === LEGACY_QA_REAL_MUTATION_TASK_NAME) {
    return '旧版单商品只保存核验任务'
  }
  if (task.mode === 'single_save' && task.name.toLowerCase().includes('l3 canary save-only')) {
    return '单商品只保存核验任务'
  }
  return task.name
}

function humanRuntimeServiceStatus(status?: string | null) {
  return ({
    running: '运行中',
    ok: '运行中',
    healthy: '运行中',
    desktop_file: '桌面内置页面',
    unavailable: '不可用',
    failed: '异常',
    error: '异常',
    unknown: '未知',
  } as Record<string, string>)[status ?? 'unknown'] ?? status ?? '未知'
}

function isRuntimeServiceOk(status?: string | null) {
  return ['running', 'ok', 'healthy', 'desktop_file'].includes(status ?? '')
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
