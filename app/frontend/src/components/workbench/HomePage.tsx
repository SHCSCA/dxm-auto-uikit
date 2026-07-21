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
  runtimeStatus,
  onShowDxmAccess,
  onShowDraftEdit,
  onShowConsole,
}: HomePageProps) {
  const recentException = workspace.exceptions.find((item) => item.status !== 'resolved' && item.status !== 'closed')
    ?? workspace.exceptions[0]
    ?? null
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const agentActive = runtimeStatus?.realBrowser?.active === true
  const currentScopeLabel = '当前保存任务'
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
        : {
            tone: 'ready',
            label: '可以准备商品箱批次',
            detail: '先读取当前商品箱范围，再冻结模板并完成人工批准；只保存，不发布。',
          }

  const primaryAction = !dxmLoggedIn
    ? {
        label: '登录店小秘',
        detail: '在可见浏览器中完成账号、密码和验证码。',
        action: onShowDxmAccess,
      }
    : agentActive
      ? {
          label: '查看浏览器现场',
          detail: '查看当前商品、安全检查与真实执行状态。',
          action: onShowConsole,
        }
      : {
          label: '进入批量编辑',
          detail: '读取真实商品箱范围，选择整批模板并创建草稿。',
          action: onShowDraftEdit,
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
