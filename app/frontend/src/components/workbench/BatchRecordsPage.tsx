import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson } from '../../api'
import type { EditBatchDetail, EditBatchItem, EditBatchProgressSummary, EditBatchStopRequest, EditBatchSummary } from '../../types'

type BatchRecordsPageProps = {
  initialBatchId: number | null
  onCreateBatch: () => void
  onOpenBatch: (batchId: number) => void
}

const POLLING_STATUSES = new Set(['running', 'stop_requested'])

export function BatchRecordsPage({ initialBatchId, onCreateBatch, onOpenBatch }: BatchRecordsPageProps) {
  const [batches, setBatches] = useState<EditBatchSummary[]>([])
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null)
  const [detail, setDetail] = useState<EditBatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [stopRequestedBy, setStopRequestedBy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pollingNotice, setPollingNotice] = useState<string | null>(null)

  const openBatch = useCallback(async (batchId: number, options?: { silent?: boolean }) => {
    const silent = options?.silent === true
    setSelectedBatchId(batchId)
    if (!silent) {
      setDetailLoading(true)
      setError(null)
      setStopRequestedBy('')
    }
    try {
      const nextDetail = await getJson<EditBatchDetail>(`/api/edit-batches/${batchId}`)
      setDetail(nextDetail)
      setPollingNotice(null)
      setBatches((current) => current.map((batch) => batch.id === batchId
        ? {
            ...batch,
            status: nextDetail.status,
            updated_at: nextDetail.updated_at,
            execution: nextDetail.execution,
            progress: nextDetail.progress,
          }
        : batch))
    } catch (caught) {
      if (silent) {
        setPollingNotice('实时进度暂时未更新，工作台会继续重试。')
      } else {
        setDetail(null)
        setError(humanRecordsError(caught, '读取批次详情失败'))
      }
    } finally {
      if (!silent) setDetailLoading(false)
    }
  }, [])

  const loadBatches = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextBatches = await getJson<EditBatchSummary[]>('/api/edit-batches')
      setBatches(nextBatches)
      const nextSelectedId = initialBatchId && nextBatches.some((batch) => batch.id === initialBatchId)
        ? initialBatchId
        : nextBatches.some((batch) => batch.id === selectedBatchId)
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
  }, [initialBatchId, openBatch, selectedBatchId])

  useEffect(() => {
    void loadBatches()
    // Initial load is intentionally tied to the API boundary, not to local state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!detail || !POLLING_STATUSES.has(detail.status)) return
    const timer = window.setInterval(() => {
      void openBatch(detail.id, { silent: true })
    }, 2000)
    return () => window.clearInterval(timer)
  }, [detail?.id, detail?.status, openBatch])

  const progress = detail?.progress ?? null
  const currentItem = detail && progress?.current_ordinal
    ? detail.items.find((item) => item.ordinal === progress.current_ordinal) ?? null
    : null
  const exceptionalItems = detail?.items.filter((item) => item.outcome && item.outcome.classification !== 'SUCCEEDED') ?? []
  const primaryNotice = error
    ? { tone: 'danger', text: error }
    : detail?.execution.manual_review_required
      ? {
          tone: 'danger',
          text: '其中一件商品的最终结果无法完整证明；批次已停止，请先人工核对真实店小秘页面。',
        }
      : pollingNotice
        ? { tone: 'warning', text: pollingNotice }
        : null

  async function requestStop() {
    if (!detail || detail.status !== 'running' || stopping) return
    const requestedBy = stopRequestedBy.trim()
    if (!requestedBy) {
      setError('请先填写停止申请人。')
      return
    }
    if (requestedBy.length > 200) {
      setError('停止请求未提交：停止申请人不能超过 200 字。')
      return
    }
    setStopping(true)
    setError(null)
    try {
      const nextDetail = await postJson<EditBatchDetail>(`/api/edit-batches/${detail.id}/stop`, {
        requested_by: requestedBy,
      } satisfies EditBatchStopRequest)
      setDetail(nextDetail)
      setBatches((current) => current.map((batch) => batch.id === nextDetail.id
        ? {
            ...batch,
            status: nextDetail.status,
            updated_at: nextDetail.updated_at,
            execution: nextDetail.execution,
            progress: nextDetail.progress,
          }
        : batch))
      setStopRequestedBy('')
    } catch (caught) {
      setError(humanRecordsError(caught, '停止请求未提交'))
    } finally {
      setStopping(false)
    }
  }

  return (
    <section className="module-layout batch-records-page" aria-label="批次记录">
      <article className="module-card span-3 batch-records-head">
        <div className="module-head">
          <div>
            <span className="eyebrow">真实执行记录</span>
            <h2>批次记录</h2>
            <p>受控逐件批次会自动更新；旧版批量任务、无人值守和发布仍关闭。主视图只保留进度与下一步。</p>
          </div>
          <div className="batch-records-head__actions">
            <button className="button button--quiet" type="button" onClick={() => { void loadBatches() }} disabled={loading || detailLoading}>刷新</button>
          </div>
        </div>
      </article>

      <article className="module-card span-1 batch-record-list">
        <div className="module-head">
          <h2>批次</h2>
          <span>{batches.length} 条</span>
        </div>
        {loading ? (
          <div className="batch-record-empty" role="status">正在读取批次记录…</div>
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
                <small>{batch.store_identity?.store_name ?? '店铺待确认'} · {batch.item_count} 件</small>
                <small>{POLLING_STATUSES.has(batch.status)
                  ? `${batch.progress.completed}/${batch.progress.total} 已完成 · ${batch.template.name ?? '模板待确认'}`
                  : `${batch.template.name ?? '模板待确认'} · ${formatDateTime(batch.created_at)}`}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="batch-record-empty">
            <strong>还没有批次</strong>
            <span>读取真实商品箱范围后即可创建。</span>
          </div>
        )}
      </article>

      <article className="module-card span-2 batch-record-detail">
        {detailLoading ? (
          <div className="batch-record-empty" role="status">正在读取批次详情…</div>
        ) : detail ? (
          <>
            <div className="module-head">
              <div>
                <span className="eyebrow">批次 #{detail.id}</span>
                <h2>{detail.scope_snapshot.store_identity?.store_name ?? '店铺已冻结'}</h2>
              </div>
              <span className={`batch-status-badge is-${statusTone(detail.status)}`}>{humanBatchStatus(detail.status)}</span>
            </div>

            {primaryNotice && (
              <div className={`batch-primary-notice is-${primaryNotice.tone}`} role={primaryNotice.tone === 'danger' ? 'alert' : 'status'}>
                <strong>{primaryNotice.tone === 'danger' ? '需要处理' : '进度暂未更新'}</strong>
                <span>{primaryNotice.text}</span>
              </div>
            )}

            {detail.status === 'draft' ? (
              <div className="batch-draft-boundary">
                <span><strong>等待批准</strong><small>范围和模板已冻结，尚未开始处理商品。</small></span>
                <button className="button button--primary" type="button" onClick={() => onOpenBatch(detail.id)}>继续批准</button>
              </div>
            ) : detail.status === 'approved' ? (
              <div className="batch-draft-boundary">
                <span>
                  <strong>旧式批准记录未启动</strong>
                  <small>该记录没有经过原子的“批准并启动”流程，不能继续执行。请新建批次并重新核对范围。</small>
                </span>
                <button className="button button--primary" type="button" onClick={onCreateBatch}>新建安全批次</button>
              </div>
            ) : progress ? (
              <div className="batch-progress-card" aria-label="批次执行进度">
                <div className="batch-progress-card__headline">
                  <span>
                    <strong>{detail.status === 'stop_requested' ? '正在安全停止' : humanBatchStatus(detail.status)}</strong>
                    <small>{currentItem ? `当前：第 ${currentItem.ordinal} 件 · ${currentItem.item_snapshot.title ?? '商品已绑定'}` : progressSummary(detail, progress)}</small>
                  </span>
                  <b>{progress.completed}/{progress.total}</b>
                </div>
                <div className="batch-progress-track" aria-label={`已完成 ${progress.percent}%`}>
                  <span style={{ width: `${boundedPercent(progress.percent)}%` }} />
                </div>
                <div className="batch-progress-card__facts">
                  <span><strong>{progress.succeeded}</strong><small>保存成功</small></span>
                  <span><strong>{progress.isolated}</strong><small>保存前隔离</small></span>
                  <span><strong>{progress.pending + progress.running}</strong><small>待处理</small></span>
                </div>
                {detail.status === 'running' && (
                  <div className="batch-stop-form">
                    <label htmlFor="batch-stop-requested-by">
                      <span>需要安全停止？填写申请人后提交</span>
                      <input
                        id="batch-stop-requested-by"
                        value={stopRequestedBy}
                        maxLength={200}
                        onChange={(event) => setStopRequestedBy(event.target.value)}
                        placeholder="姓名或值班标识"
                      />
                    </label>
                    <button
                      className="button button--quiet batch-stop-action"
                      type="button"
                      onClick={() => { void requestStop() }}
                      disabled={stopping}
                    >
                      {stopping ? '正在提交停止…' : '安全停止批次'}
                    </button>
                  </div>
                )}
                {detail.status === 'stop_requested' && <small className="batch-stop-pending">停止请求已提交；当前商品确认结束后不会再派发下一件。</small>}
              </div>
            ) : null}

            {detail.status === 'completed' && (
              <div className="batch-draft-boundary is-complete">
                <span><strong>下一步：创建下一批</strong><small>本批次已经结束，可以重新读取最新商品箱范围。</small></span>
                <button className="button button--primary" type="button" onClick={onCreateBatch}>创建下一批</button>
              </div>
            )}
            {detail.status === 'stopped' && !detail.execution.manual_review_required && (
              <div className="batch-draft-boundary is-complete">
                <span><strong>批次已安全停止</strong><small>当前没有结果不确定项；需要继续时请重新读取最新范围。</small></span>
                <button className="button button--primary" type="button" onClick={onCreateBatch}>重新读取范围</button>
              </div>
            )}
            {detail.status === 'stopped' && detail.execution.manual_review_required && (
              <div className="batch-primary-notice is-danger">
                <strong>下一步：人工核对真实页面</strong>
                <span>先确认停止位置商品是否已经保存；结果明确前不要创建重试批次。</span>
              </div>
            )}

            <div className="batch-record-template-summary" aria-label="本批次模板摘要">
              <span>
                <strong>{detail.template_snapshot.template_name}</strong>
                <small>{templateVersion(detail)} · {detail.items.length} 件 · 严格串行</small>
              </span>
              <b>只保存 · 不发布</b>
            </div>

            <details className="batch-evidence-details">
              <summary>商品明细 · {detail.items.length} 件</summary>
              <ol className="batch-record-items" aria-label="批次商品明细">
                {detail.items.map((item) => (
                  <li key={item.id} className={item.status === 'running' ? 'is-current' : ''}>
                    <span>{item.ordinal}</span>
                    <div>
                      <strong>{item.item_snapshot.title ?? '商品已绑定'}</strong>
                      <small>{item.item_snapshot.dxm_product_id ? `产品 ID ${item.item_snapshot.dxm_product_id}` : '商品身份已由后端绑定'}</small>
                    </div>
                    <b>{humanItemStatus(item.status)}</b>
                  </li>
                ))}
              </ol>
            </details>

            <details className="batch-evidence-details">
              <summary>异常与人工复核{exceptionalItems.length ? ` · ${exceptionalItems.length} 项` : ' · 无待处理项'}</summary>
              <div className="batch-evidence-payload">
                {exceptionalItems.map((item) => (
                  <span key={item.id}>
                    <strong>第 {item.ordinal} 件 · {humanOutcome(item)}</strong>
                    <b>{item.outcome?.manual_review_required ? '先人工核对真实页面，不要自动重试' : '已在保存前安全隔离，未执行写入'}</b>
                    <small>{item.outcome?.manual_review_required ? '需要人工复核' : '已在保存前安全隔离'}{item.outcome?.finished_at ? ` · ${formatDateTime(item.outcome.finished_at)}` : ''}</small>
                  </span>
                ))}
                {!exceptionalItems.length && <span><strong>暂无异常</strong><b>当前没有需要人工处理的结果。</b></span>}
              </div>
            </details>
          </>
        ) : error ? (
          <div className="batch-inline-error" role="alert">{error}</div>
        ) : (
          <div className="batch-record-empty">
            <strong>{batches.length ? '选择一条批次记录' : '还没有真实批次'}</strong>
            <span>{batches.length ? '详情会从后端读取，不使用本地结果。' : '先读取真实商品箱范围，再冻结店铺级模板。'}</span>
            {!batches.length && <button className="button button--primary" type="button" onClick={onCreateBatch}>读取商品箱范围</button>}
          </div>
        )}
      </article>
    </section>
  )
}

function humanRecordsError(caught: unknown, action: string) {
  const message = caught instanceof Error ? caught.message.toLowerCase() : ''
  if (message.includes('session') || message.includes('runtime')) return `${action}：当前店小秘会话已经变化，请重新检测登录，并确认旧诊断浏览器已关闭。`
  if (message.includes('status') || message.includes('state')) return `${action}：批次状态已经变化，请刷新后查看最新记录。`
  return `${action}。请刷新工作台后重试。`
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

function humanItemStatus(status: string) {
  const labels: Record<string, string> = {
    pending: '等待处理',
    running: '正在保存',
    succeeded: '保存成功',
    isolated_pre_save_no_write: '保存前隔离',
    stopped_uncertain: '已停止 · 待复核',
  }
  return labels[status] ?? '状态待确认'
}

function humanOutcome(item: EditBatchItem) {
  const labels: Record<string, string> = {
    SUCCEEDED: '保存成功',
    ISOLATED_PRE_SAVE_NO_WRITE: '保存前隔离',
    STOPPED_UNCERTAIN: '结果不确定',
  }
  return labels[item.outcome?.classification ?? ''] ?? humanItemStatus(item.status)
}

function progressSummary(detail: EditBatchDetail, progress: EditBatchProgressSummary) {
  if (detail.status === 'completed') return `已完成 ${progress.total} 件，全部结束。`
  if (detail.status === 'stopped') return detail.execution.manual_review_required
    ? '批次已停止，需要人工复核。'
    : '批次已安全停止。'
  return progress.pending ? `还有 ${progress.pending} 件等待处理。` : '等待后端更新当前商品。'
}

function statusTone(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'stopped') return 'danger'
  if (status === 'running' || status === 'approved') return 'active'
  if (status === 'stop_requested') return 'warning'
  return 'neutral'
}

function templateVersion(detail: EditBatchDetail) {
  const version = detail.template_snapshot.payload?.version
  return typeof version === 'string' && version.trim() ? `v${version.replace(/^v/i, '')}` : '版本未标注'
}

function boundedPercent(value: number) {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
}

function formatDateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}
