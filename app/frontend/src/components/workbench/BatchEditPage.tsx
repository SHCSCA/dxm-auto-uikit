import { useEffect, useMemo, useState } from 'react'
import { postJson } from '../../api'
import type { DraftBoxScopeSnapshot, EditBatchDetail, Template } from '../../types'

type BatchEditPageProps = {
  templates: Template[]
  onShowTemplates: () => void
  onShowRecords: () => void
}

const scopeLimits = [5, 10, 20, 50]

export function BatchEditPage({ templates, onShowTemplates, onShowRecords }: BatchEditPageProps) {
  const batchTemplates = useMemo(
    () => templates.filter((template) => template.template_type === 'edit_batch_bundle' && template.is_enabled),
    [templates],
  )
  const [maxItems, setMaxItems] = useState(5)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [scopeSnapshot, setScopeSnapshot] = useState<DraftBoxScopeSnapshot | null>(null)
  const [draftBatch, setDraftBatch] = useState<EditBatchDetail | null>(null)
  const [busyAction, setBusyAction] = useState<'capture' | 'create' | null>(null)
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

  async function captureLiveScope() {
    setBusyAction('capture')
    setError(null)
    try {
      const snapshot = await postJson<DraftBoxScopeSnapshot>('/api/dxm/draft-box/scope-snapshots', {
        max_items: maxItems,
      })
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
      })
      setDraftBatch(created)
    } catch (caught) {
      setError(humanBatchError(caught, '冻结批次草稿失败'))
    } finally {
      setBusyAction(null)
    }
  }

  if (draftBatch) {
    return (
      <section className="module-layout batch-edit-page" aria-label="批量编辑商品">
        <article className="module-card span-3 batch-draft-receipt">
          <div className="batch-boundary-line">
            <span className="batch-state-dot is-frozen" aria-hidden="true" />
            <div>
              <span>不可变批次草稿 #{draftBatch.id}</span>
              <h2>批次草稿已冻结，批准与执行尚未开放</h2>
              <p>商品顺序、店铺、模板版本与只保存策略已写入草稿；当前没有批准或执行入口，也没有产生保存结果。</p>
            </div>
          </div>
          <dl className="batch-fact-grid" aria-label="已冻结批次事实">
            <div><dt>状态</dt><dd>{humanBatchStatus(draftBatch.status)}</dd></div>
            <div><dt>商品范围</dt><dd>{draftBatch.items.length} 件，按现场顺序</dd></div>
            <div><dt>店铺</dt><dd>{draftBatch.scope_snapshot.store_identity.store_name}</dd></div>
            <div><dt>模板</dt><dd>{draftBatch.template_snapshot.template_name} · {templateVersion(draftBatch.template_snapshot)}</dd></div>
          </dl>
          <details className="batch-evidence-details">
            <summary>证据详情</summary>
            <div className="batch-digest-strip">
              <span><strong>范围摘要</strong><code>{draftBatch.scope_snapshot_digest}</code></span>
              <span><strong>模板摘要</strong><code>{draftBatch.template_snapshot_digest}</code></span>
              <span><strong>策略摘要</strong><code>{draftBatch.policy_digest}</code></span>
            </div>
          </details>
          <button className="button button--primary batch-primary-action" type="button" onClick={onShowRecords}>
            查看批次记录
          </button>
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
            <p>读取同一可见浏览器现场的商品箱商品行，保留当前筛选、排序和商品顺序。只读取，不导航、不交互、不写入。</p>
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
            <dl className="batch-fact-grid batch-fact-grid--scope" aria-label="商品箱现场证据">
              <div><dt>来源页</dt><dd>{scopeSnapshot.page_identity.title}</dd><small>{compactDxmPath(scopeSnapshot.page_identity.url)}</small></div>
              <div><dt>筛选</dt><dd>{scopeFilterSummary(scopeSnapshot.filter_state)}</dd></div>
              <div><dt>排序</dt><dd>{scopeSortSummary(scopeSnapshot.sort_state)}</dd></div>
              <div><dt>分页</dt><dd>{scopePageSummary(scopeSnapshot.page_state)}</dd></div>
            </dl>
            <ol className="batch-scope-items" aria-label="冻结商品顺序">
              {scopeSnapshot.items.map((item) => (
                <li key={item.target_identity_sha256}>
                  <span>{item.ordinal}</span>
                  <div>
                    <strong>{item.title}</strong>
                    <small>{item.dxm_product_id ? `产品 ID ${item.dxm_product_id}` : item.stable_record_key}</small>
                  </div>
                  <b title={item.target_identity_sha256}>身份已绑定</b>
                </li>
              ))}
            </ol>
            <details className="batch-evidence-details">
              <summary>证据详情</summary>
              <div className="batch-evidence-payload">
                <span><strong>DOM 摘要</strong><code>{scopeSnapshot.evidence.dom_sha256}</code></span>
                <span><strong>行证据摘要</strong><code>{scopeSnapshot.evidence.refs_digest}</code></span>
                {scopeSnapshot.items.map((item) => (
                  <span key={item.target_identity_sha256}><strong>商品 {item.ordinal} 身份</strong><code>{item.target_identity_sha256}</code></span>
                ))}
              </div>
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
              <strong>现场证据已绑定</strong>
              <span>行证据 {scopeSnapshot.evidence.refs.length} 条</span>
              <span>零写入：{isZeroWriteProven(scopeSnapshot.zero_write_proof) ? '导航、交互、写入均未发生' : '未证明'}</span>
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
  return status === 'draft' ? '草稿 · 未批准' : status
}
