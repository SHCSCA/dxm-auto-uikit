import { useEffect, useMemo, useState } from 'react'

import { getJson, postJson } from '../../api'
import type { ConfirmedDraftTaskInput } from '../../draftSelection'
import type { LocalPlanTemplate, PlanSnapshot, Task } from '../../types'

type BatchSavePlaceholderPageProps = {
  taskInput: ConfirmedDraftTaskInput | null
  onShowSelection: () => void
  onShowPlans: () => void
}

export function BatchSavePlaceholderPage({
  taskInput,
  onShowSelection,
  onShowPlans,
}: BatchSavePlaceholderPageProps) {
  const [plan, setPlan] = useState<LocalPlanTemplate | null>(null)
  const [preview, setPreview] = useState<PlanSnapshot | null>(null)
  const [frozen, setFrozen] = useState<PlanSnapshot | null>(null)
  const [createdTask, setCreatedTask] = useState<Task | null>(null)
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const items = taskInput?.input.items ?? []
  const categoryIds = useMemo(
    () => [...new Set(items.map((item) => item.categoryId).filter((value): value is string => Boolean(value)))],
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

  return (
    <section className="batch-save-placeholder" aria-label="开始批量保存">
      <header className="batch-save-placeholder__hero">
        <div>
          <span>E2 · 启动前复核与冻结</span>
          <h1>开始批量保存</h1>
          <p>本页只预览并冻结不可变 plan_snapshot；E2 不提供开始、保存或发布动作。</p>
        </div>
        <span className="status-pill warn">尚未开放执行</span>
      </header>

      <div className="batch-save-placeholder__guard" role="status">
        <strong>不会启动保存或发布</strong>
        <span>创建的 batch_draft_save 任务保持 draft；启动接口继续 fail-closed。</span>
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
          <p>开始、暂停、继续、停止，以及回包、页面成功态、独立未发布证明属于 E3–E4，本页不伪造这些证据。</p>
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
                <strong>categoryId {categoryId}</strong>
                <span>Schema 仅由当前真实会话的只读接口取得，前端不可手填。</span>
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
          {createdTask && <span>任务 #{createdTask.id} · draft · runner 未开放</span>}
        </div>
        {message && <p className={`e2-plan-message ${message.tone}`} role="status">{message.text}</p>}
      </section>
    </section>
  )
}
