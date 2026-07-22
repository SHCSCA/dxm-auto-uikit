import { useEffect, useMemo, useState } from 'react'
import { apiErrorReasonCode, getJson, postJson } from '../../api'
import type {
  DraftBoxScopeSnapshot,
  DraftBoxScopeSnapshotCreateRequest,
  EditBatchApproveAndStartRequest,
  EditBatchCreateRequest,
  EditBatchDetail,
  Template,
} from '../../types'

type BatchEditPageProps = {
  templates: Template[]
  initialBatchId: number | null
  onBatchSelected: (batchId: number | null) => void
  onShowTemplates: () => void
  onShowRecords: () => void
}

const scopeLimits = [5, 10, 20, 50]

export function BatchEditPage({
  templates,
  initialBatchId,
  onBatchSelected,
  onShowTemplates,
  onShowRecords,
}: BatchEditPageProps) {
  const batchTemplates = useMemo(
    () => templates.filter((template) => template.template_type === 'edit_batch_bundle' && template.is_enabled),
    [templates],
  )
  const [maxItems, setMaxItems] = useState(5)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [scopeSnapshot, setScopeSnapshot] = useState<DraftBoxScopeSnapshot | null>(null)
  const [draftBatch, setDraftBatch] = useState<EditBatchDetail | null>(null)
  const [approvedBy, setApprovedBy] = useState('')
  const [saveOnlyConfirmed, setSaveOnlyConfirmed] = useState(false)
  const [busyAction, setBusyAction] = useState<'load' | 'capture' | 'create' | 'start' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const selectedTemplate = batchTemplates.find((template) => String(template.id) === selectedTemplateId)
    ?? batchTemplates[0]
    ?? null

  useEffect(() => {
    if (!batchTemplates.length) {
      setSelectedTemplateId('')
      return
    }
    if (!batchTemplates.some((template) => String(template.id) === selectedTemplateId)) {
      setSelectedTemplateId(String(batchTemplates[0].id))
    }
  }, [batchTemplates, selectedTemplateId])

  useEffect(() => {
    if (!initialBatchId || draftBatch?.id === initialBatchId) return
    let cancelled = false
    setBusyAction('load')
    setError(null)
    void getJson<EditBatchDetail>(`/api/edit-batches/${initialBatchId}`)
      .then((batch) => {
        if (!cancelled) setDraftBatch(batch)
      })
      .catch((caught) => {
        if (!cancelled) setError(humanBatchError(caught, '读取批次失败'))
      })
      .finally(() => {
        if (!cancelled) setBusyAction(null)
      })
    return () => {
      cancelled = true
    }
  }, [draftBatch?.id, initialBatchId])

  async function captureLiveScope() {
    onBatchSelected(null)
    setBusyAction('capture')
    setError(null)
    try {
      const snapshot = await postJson<DraftBoxScopeSnapshot>('/api/dxm/draft-box/scope-snapshots', {
        max_items: maxItems,
      } satisfies DraftBoxScopeSnapshotCreateRequest)
      setScopeSnapshot(snapshot)
      setDraftBatch(null)
    } catch (caught) {
      setScopeSnapshot(null)
      setError(humanBatchError(caught, '读取商品箱现场失败'))
    } finally {
      setBusyAction(null)
    }
  }

  async function createDraftBatch() {
    if (!scopeSnapshot || !selectedTemplate) return
    setBusyAction('create')
    setError(null)
    try {
      const created = await postJson<EditBatchDetail>('/api/edit-batches', {
        scope_snapshot_id: scopeSnapshot.id,
        template_id: selectedTemplate.id,
      } satisfies EditBatchCreateRequest)
      setDraftBatch(created)
      onBatchSelected(created.id)
      setApprovedBy('')
      setSaveOnlyConfirmed(false)
    } catch (caught) {
      setError(humanBatchError(caught, '冻结批次草稿失败'))
    } finally {
      setBusyAction(null)
    }
  }

  if (initialBatchId && !draftBatch && busyAction === 'load') {
    return (
      <section className="module-layout batch-edit-page" aria-label="批量编辑商品">
        <article className="module-card span-3 batch-record-empty" role="status">正在读取批次 #{initialBatchId}…</article>
      </section>
    )
  }

  async function approveAndStartBatch() {
    if (!draftBatch || draftBatch.status !== 'draft' || !approvedBy.trim() || !saveOnlyConfirmed) return
    setBusyAction('start')
    setError(null)
    try {
      const started = await postJson<EditBatchDetail>(`/api/edit-batches/${draftBatch.id}/approve-and-start`, {
        approved_by: approvedBy.trim(),
        confirmation: 'CONFIRM_DXM_BATCH_SAVE_ONLY',
      } satisfies EditBatchApproveAndStartRequest)
      setDraftBatch(started)
      onShowRecords()
    } catch (caught) {
      setError(humanBatchError(caught, '批准并开始批次失败'))
    } finally {
      setBusyAction(null)
    }
  }

  if (draftBatch) {
    const isDraft = draftBatch.status === 'draft'
    const progress = draftBatch.progress
    return (
      <section className="module-layout batch-edit-page" aria-label="批量编辑商品">
        <article className="module-card span-3 batch-draft-receipt">
          <div className="batch-boundary-line">
            <span className={`batch-state-dot ${isDraft ? 'is-frozen' : 'is-running'}`} aria-hidden="true" />
            <div>
              <span>不可变批次 #{draftBatch.id}</span>
              <h2>{isDraft ? '范围已冻结，等待一次批准' : humanBatchStatus(draftBatch.status)}</h2>
              <p>{isDraft
                ? '商品顺序、店铺与模板版本已经固定。一次批准后严格串行处理，每件只保存、不发布。'
                : `批次已交给后端执行；${progress ? `当前完成 ${progress.completed}/${progress.total} 件。` : '进度会持续写入批次记录。'}`}</p>
            </div>
          </div>
          <dl className="batch-fact-grid" aria-label="已冻结批次事实">
            <div><dt>状态</dt><dd>{humanBatchStatus(draftBatch.status)}</dd></div>
            <div><dt>商品范围</dt><dd>{draftBatch.items.length} 件，按现场顺序</dd></div>
            <div><dt>店铺</dt><dd>{draftBatch.scope_snapshot.store_identity.store_name}</dd></div>
            <div><dt>模板</dt><dd>{draftBatch.template_snapshot.template_name} · {templateVersion(draftBatch.template_snapshot)}</dd></div>
          </dl>
          {isDraft ? (
            <div className="batch-approval-card" aria-label="整批一次批准">
              <div className="batch-approval-card__intro">
                <strong>批准并开始</strong>
                <span>这次批准只适用于上方已冻结范围；身份或现场发生变化时会停止。</span>
              </div>
              <label htmlFor="batch-approved-by">
                <span>批准人</span>
                <input
                  id="batch-approved-by"
                  value={approvedBy}
                  onChange={(event) => setApprovedBy(event.target.value)}
                  placeholder="填写本次批准人"
                  autoComplete="name"
                  maxLength={200}
                  disabled={busyAction !== null}
                />
              </label>
              <label className="batch-save-only-confirmation">
                <input
                  type="checkbox"
                  checked={saveOnlyConfirmed}
                  onChange={(event) => setSaveOnlyConfirmed(event.target.checked)}
                  disabled={busyAction !== null}
                />
                <span>
                  <strong>我确认只保存、不发布</strong>
                  <small>逐件串行；结果不确定时停止，且不自动重试。</small>
                </span>
              </label>
              {error && <div className="batch-inline-error" role="alert">{error}</div>}
              <button
                className="button button--primary batch-primary-action"
                type="button"
                onClick={() => { void approveAndStartBatch() }}
                disabled={busyAction !== null || !approvedBy.trim() || !saveOnlyConfirmed}
              >
                {busyAction === 'start' ? '正在批准并开始…' : '批准并开始'}
              </button>
            </div>
          ) : (
            <button className="button button--primary batch-primary-action" type="button" onClick={onShowRecords}>
              查看实时批次记录
            </button>
          )}
        </article>
      </section>
    )
  }

  return (
    <section className="module-layout batch-edit-page" aria-label="批量编辑商品">
      <article className="module-card span-3 batch-builder-head">
        <div className="module-head">
          <div>
            <span className="eyebrow">批量编辑 · 真实商品箱现场</span>
            <h2>冻结当前商品箱范围</h2>
            <p>本页开放受控逐件批次：范围冻结、一次批准、严格串行、只保存。旧版批量任务（batch_save）、无人值守和发布仍关闭。</p>
          </div>
          <span className="batch-boundary-chip">只保存 · 不发布</span>
        </div>
      </article>

      {!scopeSnapshot ? (
        <article className="module-card span-3 batch-capture-card">
          <div className="batch-capture-contract">
            <div>
              <strong>来源</strong>
              <span>速卖通 → 商品箱当前页</span>
              <small>商品和店铺身份全部由现场读回，前端不能提交自选 ID。</small>
            </div>
            <label htmlFor="batch-scope-limit">
              <span>冻结前 N 件</span>
              <select id="batch-scope-limit" value={maxItems} onChange={(event) => setMaxItems(Number(event.target.value))} disabled={busyAction !== null}>
                {scopeLimits.map((limit) => <option value={limit} key={limit}>{limit} 件</option>)}
              </select>
              <small>严格按当前页面顺序，最多读取所选上限。</small>
            </label>
          </div>
          <div className="batch-template-inline">
            <span>
              <strong>{selectedTemplate ? '将用于草稿的模板' : '模板尚未就绪'}</strong>
              <small>{selectedTemplate ? '读取现场后仍可在创建草稿前切换。' : '不影响只读范围读取；创建草稿前必须到模板中心准备完整模板包。'}</small>
            </span>
            <b>{selectedTemplate ? `${selectedTemplate.template_name} · ${templateVersion(selectedTemplate)}` : '先读取现场，再补模板'}</b>
          </div>
          {error && <div className="batch-inline-error" role="alert">{error}</div>}
          <button className="button button--primary batch-primary-action" type="button" onClick={() => { void captureLiveScope() }} disabled={busyAction !== null}>
            {busyAction === 'capture' ? '正在读取真实商品箱…' : '读取当前商品箱范围'}
          </button>
        </article>
      ) : (
        <>
          <article className="module-card span-2 batch-scope-card">
            <div className="module-head">
              <div>
                <span className="eyebrow">范围快照 #{scopeSnapshot.id}</span>
                <h2>{scopeSnapshot.store_identity.store_name} · {scopeSnapshot.items.length} 件</h2>
              </div>
              <span>{formatDateTime(scopeSnapshot.observed_at)}</span>
            </div>
            <details className="batch-scope-review">
              <summary>查看范围详情与 {scopeSnapshot.items.length} 件商品</summary>
              <dl className="batch-fact-grid batch-fact-grid--scope" aria-label="商品箱现场摘要">
                <div><dt>来源页</dt><dd>{scopeSnapshot.page_identity.title}</dd><small>{compactDxmPath(scopeSnapshot.page_identity.url)}</small></div>
                <div><dt>筛选</dt><dd>{scopeFilterSummary(scopeSnapshot.filter_state)}</dd></div>
                <div><dt>排序</dt><dd>{scopeSortSummary(scopeSnapshot.sort_state)}</dd></div>
                <div><dt>分页</dt><dd>{scopePageSummary(scopeSnapshot.page_state)}</dd></div>
              </dl>
              <ol className="batch-scope-items" aria-label="冻结商品顺序">
                {scopeSnapshot.items.map((item) => (
                  <li key={item.ordinal}>
                    <span>{item.ordinal}</span>
                    <div>
                      <strong>{item.title}</strong>
                      <small>{item.dxm_product_id ? `产品 ID ${item.dxm_product_id}` : '店小秘商品身份已绑定'}</small>
                    </div>
                    <b>已核对</b>
                  </li>
                ))}
              </ol>
            </details>
          </article>

          <aside className="module-card span-1 batch-freeze-card">
            <div className="module-head">
              <div>
                <span className="eyebrow">下一步</span>
                <h2>创建不可变草稿</h2>
              </div>
            </div>
            <div className="batch-evidence-note">
              <strong>{scopeSnapshot.items.length} 件商品已核对</strong>
              <span>店铺、顺序和商品身份已由后端冻结。</span>
              <span>{isZeroWriteProven(scopeSnapshot.zero_write_proof) ? '本次读取未执行导航、点击或写入。' : '只读边界尚未得到确认。'}</span>
            </div>
            {error && <div className="batch-inline-error" role="alert">{error}</div>}
            {selectedTemplate ? (
              <>
                <label className="batch-template-select" htmlFor="batch-template">
                  <span>整批编辑模板</span>
                  <select id="batch-template" value={String(selectedTemplate.id)} onChange={(event) => setSelectedTemplateId(event.target.value)} disabled={busyAction !== null}>
                    {batchTemplates.map((template) => (
                      <option value={String(template.id)} key={template.id}>{template.template_name} · {templateVersion(template)}</option>
                    ))}
                  </select>
                  <small>仅列出已启用的完整整批模板；后端会再次验证全部必需分区。</small>
                </label>
                <button className="button button--primary batch-primary-action" type="button" onClick={() => { void createDraftBatch() }} disabled={busyAction !== null}>
                  {busyAction === 'create' ? '正在冻结草稿…' : '冻结批次草稿'}
                </button>
                <button className="button button--quiet" type="button" onClick={onShowTemplates} disabled={busyAction !== null}>检查模板中心</button>
              </>
            ) : (
              <div className="batch-template-blocker" role="status">
                <strong>整批模板未就绪</strong>
                <span>当前生产数据中没有已启用的完整整批模板。现场已安全读取，但不能创建草稿。</span>
                <button className="button button--primary batch-primary-action" type="button" onClick={onShowTemplates}>前往模板中心</button>
              </div>
            )}
          </aside>
        </>
      )}
    </section>
  )
}

function humanBatchError(caught: unknown, action: string) {
  const reasonCode = apiErrorReasonCode(caught)
  if (reasonCode === 'LEGACY_TASK_ACTIVE' || reasonCode === 'ANOTHER_EDIT_BATCH_ACTIVE' || reasonCode === 'EDIT_BATCH_ACTIVE') {
    return '当前已有任务或批次正在执行。请先结束当前任务或批次，再回来批准本批次。'
  }
  const message = caught instanceof Error ? caught.message.trim() : ''
  const normalized = message.toLowerCase()
  if (normalized.includes('template')) return '整批模板未通过完整性检查。请在模板中心启用完整的整批编辑模板后重试；系统没有执行保存或发布。'
  if (normalized.includes('session') || normalized.includes('browser')) return '当前可见店小秘会话已变化或不可用。请回到浏览器现场确认仍在商品箱页面后重试；系统没有执行保存或发布。'
  if (normalized.includes('scope') || normalized.includes('draft-box') || normalized.includes('draft box')) return '当前商品箱范围不能安全冻结。请确认页面、店铺和商品顺序后重新读取；系统没有执行保存或发布。'
  return `${action}。请刷新工作台后重试；系统没有执行保存或发布。`
}

function templateVersion(template: Template | null) {
  const version = template?.payload?.version
  return typeof version === 'string' && version.trim() ? `v${version.replace(/^v/i, '')}` : '版本未标注'
}

function scopeFilterSummary(filter: Record<string, unknown>) {
  const controls = Array.isArray(filter.controls) ? filter.controls : []
  const values = controls.flatMap((control) => {
    if (!control || typeof control !== 'object') return []
    const record = control as Record<string, unknown>
    const key = typeof record.key === 'string' ? record.key : '筛选'
    const value = typeof record.value === 'string' || typeof record.value === 'number' ? String(record.value) : '已记录'
    return [`${key}: ${value}`]
  })
  return values.length ? values.join(' · ') : '当前页面筛选已记录'
}

function scopeSortSummary(sort: Record<string, unknown>) {
  const keys = Array.isArray(sort.keys) ? sort.keys : []
  const values = keys.flatMap((keyValue) => {
    if (!keyValue || typeof keyValue !== 'object') return []
    const record = keyValue as Record<string, unknown>
    const key = typeof record.key === 'string' ? record.key : '当前顺序'
    const direction = typeof record.direction === 'string' ? record.direction : ''
    return [`${key}${direction ? ` ${direction}` : ''}`]
  })
  return values.length ? values.join(' · ') : '当前页面顺序'
}

function scopePageSummary(pageState: DraftBoxScopeSnapshot['page_state']) {
  const parts: string[] = []
  if (typeof pageState.current_page === 'number') parts.push(`第 ${pageState.current_page} 页`)
  if (typeof pageState.page_size === 'number') parts.push(`每页 ${pageState.page_size} 件`)
  parts.push(`当前可见 ${pageState.visible_row_count} 件`)
  if (typeof pageState.total_items === 'number') parts.push(`共 ${pageState.total_items} 件`)
  return parts.join(' · ')
}

function isZeroWriteProven(proof: DraftBoxScopeSnapshot['zero_write_proof']) {
  return proof.navigation_attempted === false
    && proof.interactive_action_attempted === false
    && proof.mutation_dispatch_attempted === false
}

function compactDxmPath(value: string) {
  try {
    const url = new URL(value)
    return `${url.hostname}${url.pathname}`
  } catch {
    return '店小秘商品箱'
  }
}

function formatDateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}

function humanBatchStatus(status: string) {
  const labels: Record<string, string> = {
    draft: '草稿 · 待批准',
    approved: '旧式批准记录 · 未启动',
    running: '正在逐件保存',
    stop_requested: '正在安全停止',
    completed: '全部处理完成',
    stopped: '已停止',
  }
  return labels[status] ?? '状态待确认'
}
