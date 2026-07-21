import { useCallback, useEffect, useState } from 'react'
import { getJson } from '../../api'
import type { EditBatchDetail, EditBatchSummary } from '../../types'

type BatchRecordsPageProps = {
  onCreateBatch: () => void
}

export function BatchRecordsPage({ onCreateBatch }: BatchRecordsPageProps) {
  const [batches, setBatches] = useState<EditBatchSummary[]>([])
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null)
  const [detail, setDetail] = useState<EditBatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const openBatch = useCallback(async (batchId: number) => {
    setSelectedBatchId(batchId)
    setDetailLoading(true)
    setError(null)
    try {
      const nextDetail = await getJson<EditBatchDetail>(`/api/edit-batches/${batchId}`)
      setDetail(nextDetail)
    } catch (caught) {
      setDetail(null)
      setError(humanRecordsError(caught, '读取批次详情失败'))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const loadBatches = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextBatches = await getJson<EditBatchSummary[]>('/api/edit-batches')
      setBatches(nextBatches)
      const nextSelectedId = nextBatches.some((batch) => batch.id === selectedBatchId)
        ? selectedBatchId
        : nextBatches[0]?.id ?? null
      if (nextSelectedId) {
        await openBatch(nextSelectedId)
      } else {
        setSelectedBatchId(null)
        setDetail(null)
      }
    } catch (caught) {
      setBatches([])
      setDetail(null)
      setError(humanRecordsError(caught, '读取批次记录失败'))
    } finally {
      setLoading(false)
    }
  }, [openBatch, selectedBatchId])

  useEffect(() => {
    void loadBatches()
    // Initial load is intentionally tied to the API boundary, not to local state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="module-layout batch-records-page" aria-label="批次记录">
      <article className="module-card span-3 batch-records-head">
        <div className="module-head">
          <div>
            <span className="eyebrow">真实后端记录</span>
            <h2>批次记录</h2>
            <p>仅展示后端持久化的不可变范围、模板和策略摘要；这里不会补造执行结果。</p>
          </div>
          <div className="batch-records-head__actions">
            <button className="button button--quiet" type="button" onClick={() => { void loadBatches() }} disabled={loading || detailLoading}>刷新</button>
            <button className="button button--primary" type="button" onClick={onCreateBatch}>创建批次草稿</button>
          </div>
        </div>
      </article>

      <article className="module-card span-1 batch-record-list">
        <div className="module-head">
          <h2>批次</h2>
          <span>{batches.length} 条</span>
        </div>
        {loading ? (
          <div className="batch-record-empty" role="status">正在读取后端批次记录…</div>
        ) : batches.length ? (
          <div className="batch-record-buttons" aria-label="批次列表">
            {batches.map((batch) => (
              <button
                className={batch.id === selectedBatchId ? 'is-selected' : ''}
                type="button"
                key={batch.id}
                onClick={() => { void openBatch(batch.id) }}
                aria-pressed={batch.id === selectedBatchId}
              >
                <span><strong>批次 #{batch.id}</strong><b>{humanBatchStatus(batch.status)}</b></span>
                <small>{batch.store_identity?.store_name ?? '店铺身份缺失'} · {batch.item_count} 件</small>
                <small>{batch.template.name ?? '模板名称缺失'} · {formatDateTime(batch.created_at)}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="batch-record-empty">
            <strong>还没有批次草稿</strong>
            <span>从真实商品箱现场读取范围并冻结后，记录会出现在这里。</span>
          </div>
        )}
      </article>

      <article className="module-card span-2 batch-record-detail">
        {error ? (
          <div className="batch-inline-error" role="alert">{error}</div>
        ) : detailLoading ? (
          <div className="batch-record-empty" role="status">正在读取批次详情…</div>
        ) : detail ? (
          <>
            <div className="module-head">
              <div>
                <span className="eyebrow">批次 #{detail.id}</span>
                <h2>{detail.scope_snapshot.store_identity.store_name}</h2>
              </div>
              <span>{humanBatchStatus(detail.status)}</span>
            </div>
            <div className="batch-draft-boundary" role="status">
              <strong>批次草稿已冻结，批准与执行尚未开放</strong>
              <span>当前记录只证明草稿事实已持久化，不代表任何商品已经保存。</span>
            </div>
            <dl className="batch-fact-grid" aria-label="批次不可变摘要">
              <div><dt>商品</dt><dd>{detail.items.length} 件，严格现场顺序</dd></div>
              <div><dt>模板</dt><dd>{detail.template_snapshot.template_name} · {templateVersion(detail)}</dd></div>
              <div><dt>批准模式</dt><dd>整批一次 · 当前未开放</dd></div>
              <div><dt>执行策略</dt><dd>单件串行 · 并发 {detail.policy.global_concurrency}</dd></div>
            </dl>
            <details className="batch-evidence-details">
              <summary>证据详情</summary>
              <div className="batch-digest-strip">
                <span><strong>范围摘要</strong><code>{detail.scope_snapshot_digest}</code></span>
                <span><strong>模板摘要</strong><code>{detail.template_snapshot_digest}</code></span>
                <span><strong>策略摘要</strong><code>{detail.policy_digest}</code></span>
              </div>
            </details>
            <ol className="batch-record-items" aria-label="批次商品明细">
              {detail.items.map((item) => (
                <li key={item.id}>
                  <span>{item.ordinal}</span>
                  <div>
                    <strong>{item.item_snapshot.title}</strong>
                    <small>{item.item_snapshot.dxm_product_id ?? item.item_snapshot.stable_record_key}</small>
                  </div>
                  <b>{humanItemStatus(item.status)}</b>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <div className="batch-record-empty">
            <strong>选择一条批次记录</strong>
            <span>详情会从后端单独读取，不使用本地缓存。</span>
          </div>
        )}
      </article>
    </section>
  )
}

function humanRecordsError(caught: unknown, action: string) {
  void caught
  return `${action}。请刷新工作台后重试；系统没有执行保存或发布。`
}

function humanBatchStatus(status: string) {
  return status === 'draft' ? '草稿 · 未批准' : status
}

function humanItemStatus(status: string) {
  return status === 'pending' ? '等待批准' : status
}

function templateVersion(detail: EditBatchDetail) {
  const version = detail.template_snapshot.payload?.version
  return typeof version === 'string' && version.trim() ? `v${version.replace(/^v/i, '')}` : '版本未标注'
}

function formatDateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}
