import { useEffect, useMemo, useRef, useState } from 'react'

import { getJson, postJson } from '../../api'
import {
  BATCH_SAVE_ONLY_CONFIRMATION,
  batchTaskDestination,
  markBatchApprovalAttempted,
  nextBatchApprovalRequest,
  type BatchApprovalAttempt,
} from '../../batchApproval'
import type { ConfirmedDraftTaskInput } from '../../draftSelection'
import { humanTaskControlStatus, isTaskControlActive } from '../../taskControl'
import type { LocalPlanTemplate, PlanSnapshot, Task, TaskWorkerControl } from '../../types'
import { TaskControlKeys } from './TaskControlKeys'

type BatchSavePlaceholderPageProps = {
  taskInput: ConfirmedDraftTaskInput | null
  controlledTask?: Task | null
  busy?: boolean
  onShowSelection: () => void
  onShowPlans: () => void
  onTaskSelected: (task: Task) => void
  onPauseTask: (taskId: number) => void
  onResumeTask: (taskId: number) => void
  onStopTask: (taskId: number) => void
  onShowTaskMonitor: () => void
  onShowResults: () => void
}

export function BatchSavePlaceholderPage({
  taskInput,
  controlledTask = null,
  busy: parentBusy = false,
  onShowSelection,
  onShowPlans,
  onTaskSelected,
  onPauseTask,
  onResumeTask,
  onStopTask,
  onShowTaskMonitor,
  onShowResults,
}: BatchSavePlaceholderPageProps) {
  const [plan, setPlan] = useState<LocalPlanTemplate | null>(null)
  const [preview, setPreview] = useState<PlanSnapshot | null>(null)
  const [frozen, setFrozen] = useState<PlanSnapshot | null>(null)
  const [createdTask, setCreatedTask] = useState<Task | null>(null)
  const [message, setMessage] = useState<{ tone: 'success' | 'error' | 'warn'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [approvedBy, setApprovedBy] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [approvalAttempt, setApprovalAttempt] = useState<BatchApprovalAttempt | null>(null)
  const [approvalPhase, setApprovalPhase] = useState<'idle' | 'submitting' | 'polling' | 'accepted'>('idle')
  const approvalAttemptRef = useRef<BatchApprovalAttempt | null>(null)

  const items = taskInput?.input.items ?? []
  const categoryIds = useMemo(
    () => [...new Set(items.map((item) => item.categoryId).filter((value): value is string => Boolean(value)))],
    [items],
  )
  const categoryNames = useMemo(
    () => Object.fromEntries(
      items
        .map((item) => [item.categoryId, item.categoryName])
        .filter((entry): entry is [string, string] => Boolean(entry[0]) && Boolean(entry[1])),
    ),
    [items],
  )
  const missingCategoryCount = items.filter((item) => !item.categoryId).length

  useEffect(() => {
    let cancelled = false
    setPlan(null)
    setPreview(null)
    setFrozen(null)
    setCreatedTask(null)
    setMessage(null)
    setApprovedBy('')
    setConfirmation('')
    setApprovalAttempt(null)
    approvalAttemptRef.current = null
    setApprovalPhase('idle')
    if (!taskInput) return () => { cancelled = true }
    void getJson<LocalPlanTemplate>(`/api/local-plan-templates/${taskInput.input.planId}`)
      .then((value) => {
        if (!cancelled) setPlan(value)
      })
      .catch(() => {
        if (!cancelled) setMessage({ tone: 'error', text: '无法读取已确认的 local_plan_template；快照没有生成。' })
      })
    return () => { cancelled = true }
  }, [taskInput])

  useEffect(() => {
    if (approvalPhase !== 'polling' || !approvalAttempt) return
    let cancelled = false
    let timer: number | undefined

    const pollTask = async () => {
      try {
        const task = await getJson<Task>(`/api/tasks/${approvalAttempt.taskId}`)
        if (cancelled) return
        setCreatedTask(task)
        if (task.mode !== 'batch_draft_save') {
          setApprovalPhase('accepted')
          setMessage({ tone: 'error', text: '任务模式与冻结事实不一致；系统已停止轮询且不会再次提交批准。' })
          return
        }
        if (task.status !== 'draft') {
          setApprovalPhase('accepted')
          setMessage({ tone: 'success', text: `任务 #${task.id} 已进入 ${task.status}；只保存批准已消费，发布仍不允许。` })
          onTaskSelected(task)
          if (batchTaskDestination(task) === 'results') {
            onShowResults()
          } else {
            onShowTaskMonitor()
          }
          return
        }
        setMessage({
          tone: 'warn',
          text: `任务 #${task.id} 仍为 draft；批准结果尚未确认。系统只会继续 GET 轮询，不会重复 POST。`,
        })
      } catch {
        if (cancelled) return
        setMessage({
          tone: 'warn',
          text: `任务 #${approvalAttempt.taskId} 状态暂时读不到；结果按 UNKNOWN 处理，只读轮询继续，绝不重复批准。`,
        })
      }
      if (!cancelled) timer = window.setTimeout(() => { void pollTask() }, 2000)
    }

    void pollTask()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [approvalAttempt, approvalPhase, onShowResults, onShowTaskMonitor, onTaskSelected])

  function buildSnapshotRequest(expectedSnapshotHash: string | null = null) {
    if (!taskInput || !plan) throw new Error('请先确认真实商品范围和本地方案')
    if (taskInput.input.shopId === '-1') throw new Error('E2 快照必须绑定一个明确 shopId')
    if (items.length !== taskInput.input.productIds.length) throw new Error('任务输入缺少逐商品身份；请返回采集箱重新确认')
    if (missingCategoryCount) throw new Error('存在 categoryId 待解析商品，不能冻结')
    return {
      local_plan_template_id: plan.id,
      shop_id: taskInput.input.shopId,
      session_ref: taskInput.sessionRef,
      product_ids: taskInput.input.productIds,
      target_category_id: taskInput.input.targetCategoryId,
      target_category_name: taskInput.input.targetCategoryName,
      target_category_match: taskInput.input.targetCategoryMatch,
      expected_snapshot_hash: expectedSnapshotHash,
      ...(expectedSnapshotHash ? {
        idempotency_key: `e2-freeze-${expectedSnapshotHash.slice(0, 24).toLowerCase()}`,
      } : {}),
    }
  }

  async function previewSnapshot() {
    setBusy(true)
    setMessage(null)
    try {
      const request = buildSnapshotRequest()
      const result = await postJson<PlanSnapshot>('/api/plan-snapshots/preview', request)
      setPreview(result)
      setFrozen(null)
      setCreatedTask(null)
      setMessage({ tone: 'success', text: '快照预览已通过；尚未创建任务，也没有启动保存。' })
    } catch (error) {
      setPreview(null)
      setMessage({ tone: 'error', text: error instanceof Error ? error.message : '快照预览失败。' })
    } finally {
      setBusy(false)
    }
  }

  async function freezeTask() {
    setBusy(true)
    setMessage(null)
    try {
      if (!preview) throw new Error('请先预览并校验当前快照')
      const request = buildSnapshotRequest(preview.snapshot_hash)
      const snapshot = await postJson<PlanSnapshot>('/api/plan-snapshots', request)
      if (!snapshot.task_id) throw new Error('原子冻结回包缺少 task_id')
      const task = await getJson<Task>(`/api/tasks/${snapshot.task_id}`)
      setPreview(snapshot)
      setFrozen(snapshot)
      setCreatedTask(task)
      setMessage({
        tone: 'success',
        text: `已冻结任务 #${task.id}；状态仍为 draft，E2 没有启动 batch_draft_save runner。`,
      })
    } catch (error) {
      setMessage({ tone: 'error', text: error instanceof Error ? error.message : '冻结任务失败。' })
    } finally {
      setBusy(false)
    }
  }

  async function approveAndStartTask() {
    if (!createdTask || !frozen || approvalAttemptRef.current) return
    let request
    try {
      request = nextBatchApprovalRequest(null, {
        taskId: createdTask.id,
        approvedBy,
        confirmation,
      })
    } catch (error) {
      setMessage({ tone: 'error', text: error instanceof Error ? error.message : '批准输入无效。' })
      return
    }
    if (request.method !== 'POST') return

    const attempt = markBatchApprovalAttempted(createdTask.id)
    approvalAttemptRef.current = attempt
    setApprovalAttempt(attempt)
    setApprovalPhase('submitting')
    setMessage(null)
    try {
      await postJson(request.path, request.body)
      setMessage({ tone: 'success', text: '原子批准请求已返回；正在只读确认任务状态，不会再次提交。' })
    } catch {
      setMessage({
        tone: 'warn',
        text: '原子批准请求结果不明；系统不会重按，现改为只读 GET 轮询任务状态。',
      })
    } finally {
      setApprovalPhase('polling')
    }
  }

  const approvalContractValid = Boolean(
    frozen
    && createdTask
    && frozen.task_id === createdTask.id
    && frozen.mode === 'batch_draft_save'
    && frozen.approval_context.publish_allowed === false
    && createdTask.mode === 'batch_draft_save'
    && createdTask.status === 'draft',
  )
  const approvalReady = approvalContractValid
    && approvedBy.trim().length > 0
    && confirmation === BATCH_SAVE_ONLY_CONFIRMATION
    && !approvalAttempt

  // Prefer parent-refreshed task (workspace polling) when it matches the frozen task.
  const liveTask = (
    controlledTask
    && createdTask
    && controlledTask.id === createdTask.id
  ) ? controlledTask : (createdTask ?? controlledTask)
  const controlBusy = busy || parentBusy
  const showControlKeys = Boolean(liveTask && isTaskControlActive(liveTask.status))

  return (
    <section className="batch-save-placeholder" aria-label="开始批量保存">
      <header className="batch-save-placeholder__hero">
        <div>
          <span>E2 → E3 · 冻结后一次原子批准</span>
          <h1>开始批量保存</h1>
          <p>先预览并冻结不可变 plan_snapshot，再由人工一次批准 batch_draft_save；任何阶段都不允许发布。</p>
        </div>
        <span className="status-pill warn">只保存 · 不发布</span>
      </header>

      <div className="batch-save-placeholder__guard" role="status">
        <strong>发布始终不允许</strong>
        <span>冻结前保持零写；冻结后只允许一次原子“批准并开始”，结果不明时只读轮询、绝不重按。</span>
      </div>

      <div className="batch-save-placeholder__grid">
        <article className="module-card">
          <span>01</span>
          <h2>真实草稿范围</h2>
          <p>{taskInput ? `${taskInput.input.productIds.length} 件任务输入已绑定当前 Reader 证明。` : '尚无可复核的当前会话任务输入。'}</p>
          <button className="button button--secondary" type="button" onClick={onShowSelection}>
            返回采集箱选品
          </button>
        </article>
        <article className="module-card">
          <span>02</span>
          <h2>local_plan_template</h2>
          <p>{plan ? `${plan.name} · v${plan.version} · #${plan.id}` : taskInput ? `正在读取本地方案 #${taskInput.input.planId}` : '选择 local_plan_template 后才能形成任务输入。'}</p>
          <button className="button button--secondary" type="button" onClick={onShowPlans}>
            审阅铺货方案
          </button>
        </article>
        <article className="module-card">
          <span>03</span>
          <h2>执行与证据</h2>
          <p>批准仅释放严格串行只保存任务；回包、页面成功态与独立未发布证明仍须由真实任务产生，本页不伪造。</p>
        </article>
      </div>

      <section className="module-card e2-snapshot-review" aria-label="plan snapshot 预览与冻结">
        <div className="module-head">
          <div>
            <span className="eyebrow">plan_snapshot · 不可变</span>
            <h2>逐商品类目真相</h2>
            <p>后端重新读取当前 draft、模板与类目 Schema；系统核对 session_ref、hash、中文映射、必填解析与英文策略。</p>
          </div>
          <span className="status-pill neutral">{items.length} 件 · {categoryIds.length} 个类目</span>
        </div>

        {categoryIds.length ? (
          <div className="e2-schema-grid" aria-label="待后端重验的类目作用域">
            {categoryIds.map((categoryId) => (
              <div key={categoryId}>
                <strong>{categoryNames[categoryId] || `类目 ${categoryId}`}</strong>
                <span>{categoryNames[categoryId] ? `categoryId ${categoryId}` : 'Schema 仅由当前真实会话的只读接口取得，前端不可手填。'}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <strong>没有可冻结的 categoryId</strong>
            <span>请返回采集箱重新读取并确认至少 3 件带 categoryId 的真实草稿。</span>
          </div>
        )}

        {preview && (
          <div className="e2-snapshot-facts">
            <span><strong>snapshot hash</strong><code>{preview.snapshot_hash}</code></span>
            <span><strong>逐商品快照</strong><b>{preview.item_snapshots.length} 份</b></span>
            <span><strong>证据策略</strong><b>three_proofs</b></span>
            <span><strong>发布允许</strong><b>否</b></span>
          </div>
        )}

        <div className="e2-snapshot-actions">
          <button className="button button--secondary" type="button" disabled={busy || !taskInput || !plan} onClick={() => { void previewSnapshot() }}>
            预览并校验快照
          </button>
          <button className="button button--primary" type="button" disabled={busy || !preview || Boolean(frozen)} onClick={() => { void freezeTask() }}>
            冻结为 draft 任务（不启动）
          </button>
          {createdTask && <span>任务 #{createdTask.id} · {createdTask.status} · {createdTask.mode}</span>}
        </div>
        {message && <p className={`e2-plan-message ${message.tone}`} role="status">{message.text}</p>}
      </section>

      {frozen && createdTask && (
        <section className="module-card e2-snapshot-review" aria-label="batch_draft_save 一次批准">
          <div className="module-head">
            <div>
              <span className="eyebrow">task facts · 已冻结</span>
              <h2>人工批准只保存任务</h2>
              <p>批准绑定下列 task 与 snapshot。提交一次后按钮永久锁定；状态不明只轮询任务，不会再次 POST。</p>
            </div>
            <span className="status-pill neutral">{humanTaskControlStatus(liveTask?.status || createdTask.status)}</span>
          </div>

          <dl className="batch-fact-grid" aria-label="已冻结任务事实">
            <div><dt>任务</dt><dd>#{createdTask.id}</dd></div>
            <div><dt>模式</dt><dd>{createdTask.mode}</dd></div>
            <div><dt>商品范围</dt><dd>{frozen.product_ids.length} 件</dd></div>
            <div><dt>发布允许</dt><dd>否</dd></div>
            <div><dt>进度</dt><dd>{(liveTask?.completed_jobs ?? createdTask.completed_jobs) ?? 0}/{(liveTask?.total_jobs ?? createdTask.total_jobs) ?? frozen.product_ids.length}</dd></div>
          </dl>
          <div className="batch-digest-strip">
            <span><strong>plan_snapshot_hash</strong><code>{frozen.snapshot_hash}</code></span>
            <span><strong>店铺作用域</strong><code>{frozen.shop_scope}</code></span>
            <span><strong>执行路径</strong><code>Path A · save only</code></span>
          </div>

          {!approvalContractValid ? (
            <p className="batch-inline-error" role="alert">任务与冻结事实不一致，原子批准入口已关闭。</p>
          ) : (
            <div className="batch-approval-card" aria-label="batch_draft_save 原子批准">
              <div className="batch-approval-card__intro">
                <strong>批准并开始</strong>
                <span>唯一写请求：POST /api/tasks/{createdTask.id}/approve-and-start</span>
              </div>
              <label htmlFor="batch-task-approved-by">
                <span>批准人</span>
                <input
                  id="batch-task-approved-by"
                  type="text"
                  value={approvedBy}
                  onChange={(event) => setApprovedBy(event.target.value)}
                  placeholder="填写本次批准人"
                  autoComplete="name"
                  maxLength={200}
                  disabled={Boolean(approvalAttempt)}
                />
              </label>
              <label htmlFor="batch-task-confirmation">
                <span>输入确认短语 <code>{BATCH_SAVE_ONLY_CONFIRMATION}</code></span>
                <input
                  id="batch-task-confirmation"
                  type="text"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  placeholder={BATCH_SAVE_ONLY_CONFIRMATION}
                  autoComplete="off"
                  maxLength={64}
                  disabled={Boolean(approvalAttempt)}
                />
              </label>
              <label className="batch-save-only-confirmation">
                <input type="checkbox" checked readOnly aria-label="发布不允许" />
                <span>
                  <strong>只保存、不发布</strong>
                  <small>发布守卫不可解除；UNKNOWN 停批并转人工复核，绝不自动重试保存。</small>
                </span>
              </label>
              <button
                className="button button--primary batch-primary-action"
                type="button"
                onClick={() => { void approveAndStartTask() }}
                disabled={!approvalReady || approvalPhase !== 'idle' || showControlKeys}
              >
                {approvalPhase === 'submitting'
                  ? '正在原子批准…'
                  : approvalPhase === 'polling'
                    ? '结果确认中（仅 GET）'
                    : approvalPhase === 'accepted' || showControlKeys
                      ? '批准已消费'
                      : '一次批准并开始只保存'}
              </button>
            </div>
          )}

          {liveTask && showControlKeys && (
            <div className="batch-task-control" aria-label="batch_draft_save 四键控制">
              <TaskControlKeys
                taskId={liveTask.id}
                status={liveTask.status}
                workerControl={resolveTaskWorkerControl(liveTask)}
                busy={controlBusy}
                showStart={false}
                completedJobs={liveTask.completed_jobs}
                totalJobs={liveTask.total_jobs}
                onPause={onPauseTask}
                onResume={onResumeTask}
                onStop={onStopTask}
              />
              <div className="action-row">
                <button className="button button--secondary" type="button" onClick={onShowTaskMonitor}>
                  打开任务监控
                </button>
                <button className="button button--quiet" type="button" onClick={onShowResults}>
                  查看保存结果
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {!frozen && liveTask && showControlKeys && (
        <section className="module-card" aria-label="进行中的 batch_draft_save 控制">
          <div className="module-head">
            <div>
              <span className="eyebrow">task control · E4</span>
              <h2>任务 #{liveTask.id} · {humanTaskControlStatus(liveTask.status)}</h2>
              <p>当前会话没有本地冻结卡片，但仍可对已运行任务请求暂停/继续/停止；状态以后端 worker ack 为准。</p>
            </div>
          </div>
          <TaskControlKeys
            taskId={liveTask.id}
            status={liveTask.status}
            workerControl={resolveTaskWorkerControl(liveTask)}
            busy={controlBusy}
            showStart={false}
            completedJobs={liveTask.completed_jobs}
            totalJobs={liveTask.total_jobs}
            onPause={onPauseTask}
            onResume={onResumeTask}
            onStop={onStopTask}
          />
        </section>
      )}
    </section>
  )
}

function resolveTaskWorkerControl(task: Task): TaskWorkerControl | null {
  if (task.workerControl) return task.workerControl
  const nested = task.payload?.worker_control
  if (nested && typeof nested === 'object') return nested as TaskWorkerControl
  return null
}
