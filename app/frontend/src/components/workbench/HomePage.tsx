import type { ConfigPreview, DeliveryWorkspace, EditBatchSummary, RuntimeStatus, Task } from '../../types'
import { DXM_LOGGED_IN_STATUSES, displayTaskName } from '../WorkbenchModules'

type HomePageProps = {
  workspace: DeliveryWorkspace
  editBatches: EditBatchSummary[]
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  runtimeStatus: RuntimeStatus | null
  onShowDxmAccess: () => void
  onShowAcquisition: () => void
  onShowDraftEdit: () => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowBatchRecords: (batchId?: number) => void
  onShowReports: () => void
}

export function HomePage({
  workspace,
  editBatches,
  selectedTask,
  runtimeStatus,
  onShowDxmAccess,
  onShowDraftEdit,
  onShowTasks,
  onShowConsole,
  onShowBatchRecords,
}: HomePageProps) {
  const recentException = editBatches.length
    ? null
    : workspace.exceptions.find((item) => item.status !== 'resolved' && item.status !== 'closed')
      ?? workspace.exceptions[0]
      ?? null
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const diagnosticBrowserActive = runtimeStatus?.agentConsole?.active === true
  const activeBatch = editBatches.find((batch) => batch.status === 'running' || batch.status === 'stop_requested') ?? null
  const draftBatch = editBatches.find((batch) => batch.status === 'draft') ?? null
  const reviewBatch = editBatches.find((batch) => batch.execution.manual_review_required || batch.progress.stopped > 0) ?? null
  const runningTask = workspace.tasks.find((task) => task.status === 'running') ?? null
  const currentScopeLabel = activeBatch ? '当前整批执行' : runningTask ? '当前单商品任务' : draftBatch ? '待批准批次' : '当前保存任务'
  const currentScopeProgress = activeBatch
    ? `${activeBatch.progress.completed}/${activeBatch.progress.total} 件已处理`
    : runningTask
      ? `${runningTask.completed_jobs}/${Math.max(runningTask.total_jobs, 1)} 项已处理`
      : draftBatch
        ? `${draftBatch.item_count} 件范围已冻结`
        : selectedTask
          ? `${selectedTask.completed_jobs}/${Math.max(selectedTask.total_jobs, 1)} 项已处理`
          : '暂无运行中任务'

  const liveStatus = activeBatch
    ? {
        tone: 'active',
        label: '整批正在严格串行执行',
        detail: `已处理 ${activeBatch.progress.completed}/${activeBatch.progress.total} 件；不确定结果会停止且不自动重试。`,
      }
    : runningTask
      ? {
          tone: 'active',
          label: '单商品任务正在执行',
          detail: '任务执行器正在真实页面处理；请从当前保存任务查看状态。',
        }
    : diagnosticBrowserActive
      ? {
          tone: 'waiting',
          label: '旧诊断浏览器仍在运行',
          detail: '真实认领、单商品保存和整批执行前必须先关闭它。',
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

  const primaryAction = activeBatch
    ? {
        label: '查看串行进度',
        detail: '查看当前商品、完成数量和安全停止入口。',
        action: () => onShowBatchRecords(activeBatch.id),
      }
    : runningTask
      ? {
          label: '查看当前任务',
          detail: '查看真实执行状态；不要从诊断浏览器重复启动。',
          action: onShowTasks,
        }
      : diagnosticBrowserActive
        ? {
            label: '关闭旧诊断浏览器',
            detail: '释放共享浏览器后再回到批次流程。',
            action: onShowConsole,
          }
        : draftBatch
          ? {
              label: '继续批准批次',
              detail: '核对已冻结范围后，一次批准并启动严格串行执行。',
              action: () => onShowBatchRecords(draftBatch.id),
            }
        : !dxmLoggedIn
    ? {
        label: '登录店小秘',
        detail: '在可见浏览器中完成账号、密码和验证码。',
        action: onShowDxmAccess,
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
          <strong>{activeBatch
            ? `批次 #${activeBatch.id} · ${activeBatch.store_identity?.store_name ?? '店铺已冻结'}`
            : runningTask
              ? displayTaskName(runningTask)
              : draftBatch
                ? `批次 #${draftBatch.id} · 等待批准`
                : selectedTask
                  ? displayTaskName(selectedTask)
                  : '尚无真实任务'}</strong>
          <small>{currentScopeProgress}</small>
        </article>
        <article className={`module-card home-brief-card ${reviewBatch || recentException ? 'is-warning' : 'is-clear'}`} aria-label="最近异常">
          <span>需要处理</span>
          <strong>{reviewBatch ? `批次 #${reviewBatch.id} 需要人工核对` : recentException?.title ?? '暂无待处理问题'}</strong>
          <small>{reviewBatch ? '先核对真实店小秘页面，不要自动重试结果不确定的商品。' : recentException?.suggestion || '出现问题时会在这里显示最近一条。'}</small>
        </article>
      </div>
    </section>
  )
}
