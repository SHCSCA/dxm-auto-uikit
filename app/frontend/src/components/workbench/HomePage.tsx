import type { DeliveryWorkspace, EditBatchSummary, RuntimeStatus, Task } from '../../types'
import { DXM_LOGGED_IN_STATUSES, displayTaskName } from '../WorkbenchModules'
import frontendPackage from '../../../package.json'

type HomePageProps = {
  workspace: DeliveryWorkspace
  editBatches: EditBatchSummary[]
  selectedTask: Task | null
  runtimeStatus: RuntimeStatus | null
  currentShopId: string
  currentShopName: string | null
  shopLoading: boolean
  shopError: string | null
  onShowDxmAccess: () => void
  onRefreshShops: () => void
  onShowDraftEdit: () => void
  onShowTasks: () => void
  onShowConsole: () => void
  onShowBatchRecords: (batchId?: number) => void
  onOpenBatch: (batchId: number) => void
}

export function HomePage({
  workspace,
  editBatches,
  selectedTask,
  runtimeStatus,
  currentShopId,
  currentShopName,
  shopLoading,
  shopError,
  onShowDxmAccess,
  onRefreshShops,
  onShowDraftEdit,
  onShowTasks,
  onShowConsole,
  onShowBatchRecords,
  onOpenBatch,
}: HomePageProps) {
  const recentException = workspace.exceptions.find((item) => item.status !== 'resolved' && item.status !== 'closed')
    ?? workspace.exceptions[0]
    ?? null
  const dxmLoggedIn = runtimeStatus ? DXM_LOGGED_IN_STATUSES.has(runtimeStatus.dxmLogin.status) : false
  const diagnosticBrowserActive = runtimeStatus?.agentConsole?.active === true
  const activeBatch = editBatches.find((batch) => batch.status === 'running' || batch.status === 'stop_requested') ?? null
  const draftBatch = editBatches.find((batch) => batch.status === 'draft') ?? null
  const reviewBatch = editBatches.find((batch) => batch.execution.manual_review_required) ?? null
  const runningTask = workspace.tasks.find((task) => task.status === 'running') ?? null
  const currentScopeLabel = activeBatch ? '当前整批执行' : runningTask ? '当前单商品任务' : reviewBatch ? '待人工对账批次' : draftBatch ? '待批准批次' : '当前保存任务'
  const currentScopeProgress = activeBatch
    ? `${activeBatch.progress.completed}/${activeBatch.progress.total} 件已处理`
    : runningTask
      ? `${runningTask.completed_jobs}/${Math.max(runningTask.total_jobs, 1)} 项已处理`
      : reviewBatch
        ? `${reviewBatch.progress.completed}/${reviewBatch.progress.total} 件已处理，停止位置待确认`
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
    : reviewBatch
      ? {
          tone: 'waiting',
          label: '结果不确定，等待人工对账',
          detail: `批次 #${reviewBatch.id} 未能证明停止位置的最终结果；确认前不要重试。`,
        }
    : diagnosticBrowserActive
      ? {
          tone: 'waiting',
          label: '旧诊断浏览器仍在运行',
          detail: '单商品保存和整批执行前必须先关闭它。',
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
      : shopError
        ? {
            tone: 'waiting',
            label: '店铺读取失败，不能开始新批次',
            detail: '保留上一份可信店铺快照；重新读取成功前不会混用或清空店铺范围。',
          }
        : shopLoading
          ? {
              tone: 'waiting',
              label: '正在读取当前账号的店铺',
              detail: '店铺列表是模板、方案和草稿隔离的前置事实。',
            }
          : !currentShopId
            ? {
                tone: 'waiting',
                label: '请先选择当前店铺',
                detail: '未选店铺时不会读取模板、生成方案或创建批次。',
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
      : reviewBatch
        ? {
            label: '人工对账停止位置',
            detail: '先确认真实店小秘页面结果；结果明确前不要创建或启动重试批次。',
            action: () => onShowBatchRecords(reviewBatch.id),
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
              action: () => onOpenBatch(draftBatch.id),
            }
        : !dxmLoggedIn
    ? {
        label: '登录店小秘',
        detail: '在可见浏览器中完成账号、密码和验证码。',
        action: onShowDxmAccess,
      }
    : shopError
      ? {
          label: '重新读取店铺',
          detail: '读取失败期间不会使用旧店铺列表创建新方案。',
          action: onRefreshShops,
        }
      : shopLoading
        ? {
            label: '等待店铺读取完成',
            detail: '店铺读取完成后才能进入商品箱批量编辑。',
            action: onShowDxmAccess,
          }
        : !currentShopId
          ? {
              label: '选择当前店铺',
              detail: '先在账号与店铺页确认本次操作的店铺范围。',
              action: onShowDxmAccess,
            }
          : {
              label: '进入批量编辑',
              detail: '读取真实商品箱范围，选择整批模板并创建草稿。',
              action: onShowDraftEdit,
            }

  return (
    <section className="dashboard-grid home-workbench" aria-label="编辑工作台">
      {/* PublishGuard Banner - Permanent Warning */}
      <div className="publishguard-banner publishguard-banner--home" role="alert">
        <strong>⚠ 本系统仅支持草稿保存，禁止任何发布操作</strong>
        <p>最终发布永久禁止：立即发布、保存并发布、上线等按钮均已永久禁用。</p>
      </div>

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
        <article className="module-card home-brief-card" aria-label="当前店铺">
          <span>当前店铺</span>
          <strong>{shopLoading ? '正在读取…' : currentShopName ?? '尚未选择'}</strong>
          <small>{shopError ? '读取失败：请重新读取' : currentShopId ? `店铺 ID ${currentShopId} · 数据按店铺隔离` : '登录后从店铺列表选择'}</small>
        </article>
        <article className="module-card home-brief-card" aria-label="系统版本">
          <span>工作台版本</span>
          <strong>v{frontendPackage.version}</strong>
          <small>{runtimeStatus?.runtimeIdentity?.gitDirty ? '当前工作树存在未提交变更' : '运行身份已读取'}</small>
        </article>
        <article className="module-card home-brief-card" aria-label={currentScopeLabel}>
          <span>{currentScopeLabel}</span>
          <strong>{activeBatch
            ? `批次 #${activeBatch.id} · ${activeBatch.store_identity?.store_name ?? '店铺已冻结'}`
            : runningTask
              ? displayTaskName(runningTask)
              : reviewBatch
                ? `批次 #${reviewBatch.id} · 等待人工对账`
                : draftBatch
                  ? `批次 #${draftBatch.id} · 等待批准`
                  : selectedTask
                    ? displayTaskName(selectedTask)
                    : '尚无真实任务'}</strong>
          <small>{currentScopeProgress}</small>
        </article>
        <article className={`module-card home-brief-card ${reviewBatch || recentException ? 'is-warning' : 'is-clear'}`} aria-label="最近异常">
          <span>需要处理</span>
          <strong>{reviewBatch ? `批次 #${reviewBatch.id} 需要人工对账` : recentException?.title ?? '暂无待处理问题'}</strong>
          <small>{reviewBatch ? '先对账真实店小秘页面，不要自动重试结果不确定的商品。' : recentException?.suggestion || '出现问题时会在这里显示最近一条。'}</small>
        </article>
      </div>
    </section>
  )
}
