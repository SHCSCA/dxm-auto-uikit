import type { ConfigPreview, DeliveryWorkspace, RuntimeStatus, Task } from '../../types'
import { DXM_LOGGED_IN_STATUSES, displayTaskName } from '../WorkbenchModules'

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

export function HomePage({
  workspace,
  selectedTask,
  configPreview,
  runtimeStatus,
  onShowDxmAccess,
  onShowDraftEdit,
  onShowTasks,
  onShowConfig,
  onShowConsole,
}: HomePageProps) {
  const batchMode = workspace.realModeReleasePlan.modes.find((mode) => mode.mode === 'batch_save')
  const batchCapabilityReady = batchMode?.allowed === true
  const recentException = workspace.exceptions.find((item) => item.status !== 'resolved' && item.status !== 'closed')
    ?? workspace.exceptions[0]
    ?? null
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const agentActive = runtimeStatus?.realBrowser?.active === true
  const configReady = Boolean(
    selectedTask?.status === 'completed'
      || (selectedTask && configPreview?.taskId === selectedTask.id && configPreview.ok),
  )
  const currentScopeLabel = selectedTask?.total_jobs && selectedTask.total_jobs > 1 ? '当前批次' : '当前任务'
  const currentScopeProgress = selectedTask
    ? `${selectedTask.completed_jobs}/${Math.max(selectedTask.total_jobs, 1)} 项已处理`
    : '暂无运行中任务'

  const liveStatus = agentActive
    ? {
        tone: 'active',
        label: '浏览器现场执行中',
        detail: '当前操作由真实浏览器执行，任何不确定结果都会停止并等待人工处理。',
      }
    : !runtimeStatus
      ? {
          tone: 'waiting',
          label: '正在读取工作台状态',
          detail: '连接服务后才会显示可执行范围，当前不会启动真实操作。',
        }
      : !dxmLoggedIn
        ? {
            tone: 'waiting',
            label: '等待登录店小秘',
            detail: '完成真实浏览器登录后再读取商品箱现场。',
          }
        : batchCapabilityReady
          ? {
              tone: 'ready',
              label: '后端已放行批量编辑能力',
              detail: '实际执行仍需绑定当前现场并完成人工批准；只保存，不发布。',
            }
          : {
              tone: 'blocked',
              label: '批量编辑尚未开放',
              detail: '当前后端未放行批量保存，工作台不会模拟执行或生成成功结果。',
            }

  const primaryAction = !dxmLoggedIn
    ? {
        label: '登录店小秘',
        detail: '在可见浏览器中完成账号、密码和验证码。',
        action: onShowDxmAccess,
      }
    : selectedTask?.status === 'completed'
      ? {
          label: '查看任务记录',
          detail: '复核完成结果、未发布证明与异常。',
          action: onShowTasks,
        }
      : !selectedTask
        ? {
            label: '选择商品箱商品',
            detail: '从店小秘已有商品箱范围中选择要编辑的真实商品。',
            action: onShowDraftEdit,
          }
        : !configReady
          ? {
              label: '检查编辑模板',
              detail: '确认当前任务要使用的模板和必填字段。',
              action: onShowConfig,
            }
          : {
              label: '打开浏览器现场',
              detail: '查看当前任务、安全检查和真实执行状态。',
              action: onShowConsole,
            }

  return (
    <section className="dashboard-grid home-workbench" aria-label="编辑工作台">
      <div className="hero-panel home-command">
        <div className="home-command__header">
          <div>
            <span className="home-command__eyebrow">受控编辑工作台</span>
            <h1>编辑工作台</h1>
            <p>从当前真实店小秘现场继续，只保存，不发布。</p>
          </div>
          <span className={`home-status-line is-${liveStatus.tone}`} aria-label="当前状态">
            <strong>{liveStatus.label}</strong>
            <small>{liveStatus.detail}</small>
          </span>
        </div>

        <div className="home-command__primary">
          <div>
            <span>下一步</span>
            <strong>{primaryAction.label}</strong>
            <small>{primaryAction.detail}</small>
          </div>
          <button className="button button--primary" type="button" onClick={primaryAction.action}>
            {primaryAction.label}
          </button>
        </div>
      </div>

      <div className="home-brief-grid">
        <article className="module-card home-brief-card" aria-label={currentScopeLabel}>
          <span>{currentScopeLabel}</span>
          <strong>{selectedTask ? displayTaskName(selectedTask) : '未选择任务'}</strong>
          <small>{currentScopeProgress}</small>
        </article>
        <article className={`module-card home-brief-card ${recentException ? 'is-warning' : 'is-clear'}`} aria-label="最近异常">
          <span>最近异常</span>
          <strong>{recentException?.title ?? '暂无待处理异常'}</strong>
          <small>{recentException?.suggestion || '出现异常时会在这里显示最近一条。'}</small>
        </article>
      </div>
    </section>
  )
}
