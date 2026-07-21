import { useCallback, useEffect, useMemo, useState } from 'react'
import { getJson, postJson } from '../../api'
import type { EditBatchDetail, EditBatchItem, EditBatchProgressSummary, EditBatchSummary } from '../../types'

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
  const [error, setError] = useState<string | null>(null)
  const [pollingNotice, setPollingNotice] = useState<string | null>(null)

  const openBatch = useCallback(async (batchId: number, options?: { silent?: boolean }) => {
    const silent = options?.silent === true
    setSelectedBatchId(batchId)
    if (!silent) {
      setDetailLoading(true)
      setError(null)
    }
    try {
      const nextDetail = await getJson<EditBatchDetail>(`/api/edit-batches/${batchId}`)
      setDetail(nextDetail)
      setPollingNotice(null)
      setBatches((current) => current.map((batch) => batch.id === batchId
        ? { ...batch, status: nextDetail.status, updated_at: nextDetail.updated_at }
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

  const progress = useMemo(() => detail ? progressFor(detail) : null, [detail])
  const currentItem = detail && progress?.current_ordinal
    ? detail.items.find((item) => item.ordinal === progress.current_ordinal) ?? null
    : null
  const exceptionalItems = detail?.items.filter((item) => item.outcome && item.outcome.classification !== 'SUCCEEDED') ?? []
  const executionReasonCode = detail ? detail.execution?.reason_code ?? detail.execution?.stop_reason_code : null

  async function requestStop() {
    if (!detail || detail.status !== 'running' || stopping) return
    const requestedBy = window.prompt('请输入停止申请人（最多 200 字）')?.trim()
    if (!requestedBy) return
    if (requestedBy.length > 200) {
      setError('停止请求未提交：停止申请人不能超过 200 字。')
      return
    }
    setStopping(true)
    setError(null)
    try {
      const nextDetail = await postJson<EditBatchDetail>(`/api/edit-batches/${detail.id}/stop`, {
        requested_by: requestedBy,
      })
      setDetail(nextDetail)
      setBatches((current) => current.map((batch) => batch.id === nextDetail.id
        ? { ...batch, status: nextDetail.status, updated_at: nextDetail.updated_at }
        : batch))
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
            <p>运行中的批次会自动更新。主视图只保留进度和下一步，异常与证据收在详情中。</p>
          </div>
          <div className="batch-records-head__actions">
            <button className="button button--quiet" type="button" onClick={() => { void loadBatches() }} disabled={loading || detailLoading}>刷新</button>
            <button className="button button--primary" type="button" onClick={onCreateBatch}>创建新批次</button>
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
                <small>{batch.template.name ?? '模板待确认'} · {formatDateTime(batch.created_at)}</small>
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
                <h2>{detail.scope_snapshot.store_identity.store_name}</h2>
              </div>
              <span className={`batch-status-badge is-${statusTone(detail.status)}`}>{humanBatchStatus(detail.status)}</span>
            </div>

            {error && <div className="batch-inline-error" role="alert">{error}</div>}
            {pollingNotice && <div className="batch-polling-notice" role="status">{pollingNotice}</div>}

            {detail.status === 'draft' ? (
              <div className="batch-draft-boundary">
                <span><strong>等待批准</strong><small>范围和模板已冻结，尚未开始处理商品。</small></span>
                <button className="button button--primary" type="button" onClick={() => onOpenBatch(detail.id)}>继续批准</button>
              </div>
            ) : progress ? (
              <div className="batch-progress-card" aria-label="批次执行进度">
                <div className="batch-progress-card__headline">
                  <span>
                    <strong>{detail.status === 'stop_requested' ? '正在安全停止' : humanBatchStatus(detail.status)}</strong>
                    <small>{currentItem ? `当前：第 ${currentItem.ordinal} 件 · ${currentItem.item_snapshot.title}` : progressSummary(detail, progress)}</small>
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
                {(detail.status === 'running' || detail.status === 'stop_requested') && (
                  <button
                    className="button button--quiet batch-stop-action"
                    type="button"
                    onClick={() => { void requestStop() }}
                    disabled={stopping || detail.status === 'stop_requested'}
                  >
                    {detail.status === 'stop_requested' ? '已请求停止' : stopping ? '正在提交停止…' : '停止批次'}
                  </button>
                )}
              </div>
            ) : null}

            <dl className="batch-fact-grid" aria-label="批次摘要">
              <div><dt>商品</dt><dd>{detail.items.length} 件 · 严格串行</dd></div>
              <div><dt>模板</dt><dd>{detail.template_snapshot.template_name} · {templateVersion(detail)}</dd></div>
              <div><dt>批准</dt><dd>整批一次</dd></div>
              <div><dt>边界</dt><dd>只保存 · 不发布</dd></div>
            </dl>

            <ol className="batch-record-items" aria-label="批次商品明细">
              {detail.items.map((item) => (
                <li key={item.id} className={item.status === 'running' ? 'is-current' : ''}>
                  <span>{item.ordinal}</span>
                  <div>
                    <strong>{item.item_snapshot.title}</strong>
                    <small>{item.item_snapshot.dxm_product_id ?? item.item_snapshot.stable_record_key}</small>
                  </div>
                  <b>{humanItemStatus(item.status)}</b>
                </li>
              ))}
            </ol>

            <details className="batch-evidence-details">
              <summary>异常与证据{exceptionalItems.length ? ` · ${exceptionalItems.length} 项` : ''}</summary>
              <div className="batch-evidence-payload">
                {executionReasonCode && (
                  <span><strong>批次停止原因</strong><b>{humanReasonCode(executionReasonCode)}</b><code>{executionReasonCode}</code></span>
                )}
                {exceptionalItems.map((item) => (
                  <span key={item.id}>
                    <strong>第 {item.ordinal} 件 · {humanOutcome(item)}</strong>
                    <b>{humanReasonCode(item.outcome?.reason_code)}</b>
                    {item.outcome?.reason_code && <code>{item.outcome.reason_code}</code>}
                  </span>
                ))}
                {!executionReasonCode && !exceptionalItems.length && <span><strong>暂无异常</strong><b>当前没有需要人工处理的结果。</b></span>}
                <div className="batch-digest-strip">
                  <span><strong>范围摘要</strong><code>{detail.scope_snapshot_digest}</code></span>
                  <span><strong>模板摘要</strong><code>{detail.template_snapshot_digest}</code></span>
                  <span><strong>策略摘要</strong><code>{detail.policy_digest}</code></span>
                </div>
              </div>
            </details>
          </>
        ) : error ? (
          <div className="batch-inline-error" role="alert">{error}</div>
        ) : (
          <div className="batch-record-empty">
            <strong>选择一条批次记录</strong>
            <span>详情会从后端读取，不使用本地结果。</span>
          </div>
        )}
      </article>
    </section>
  )
}

function progressFor(detail: EditBatchDetail): EditBatchProgressSummary {
  if (detail.progress) return detail.progress
  const execution = detail.execution
  const succeeded = execution?.succeeded_count ?? detail.items.filter((item) => item.status === 'succeeded').length
  const isolated = execution?.isolated_count ?? detail.items.filter((item) => item.status === 'isolated_pre_save_no_write').length
  const stopped = detail.items.filter((item) => item.status === 'stopped_uncertain').length
  const runningItem = detail.items.find((item) => item.status === 'running')
  const completed = execution?.completed_count ?? succeeded + isolated + stopped
  const total = execution?.total_count ?? detail.items.length
  return {
    total,
    completed,
    succeeded,
    isolated,
    pending: detail.items.filter((item) => item.status === 'pending').length,
    running: runningItem ? 1 : 0,
    stopped,
    current_ordinal: execution?.current_ordinal ?? runningItem?.ordinal ?? null,
    percent: total ? Math.round((completed / total) * 100) : 0,
  }
}

function humanRecordsError(caught: unknown, action: string) {
  const message = caught instanceof Error ? caught.message.toLowerCase() : ''
  if (message.includes('session') || message.includes('runtime')) return `${action}：当前浏览器现场已经变化，请回到浏览器现场确认。`
  if (message.includes('status') || message.includes('state')) return `${action}：批次状态已经变化，请刷新后查看最新记录。`
  return `${action}。请刷新工作台后重试。`
}

function humanBatchStatus(status: string) {
  const labels: Record<string, string> = {
    draft: '草稿 · 待批准',
    approved: '已批准 · 等待开始',
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

function humanReasonCode(reasonCode: string | null | undefined) {
  if (!reasonCode) return '未记录额外原因'
  const labels: Record<string, string> = {
    ITEM_SAVE_PROVEN: '已证明只保存成功',
    PRE_SAVE_VALIDATION_ISOLATED: '保存前校验未通过，且已证明零写入',
    PUBLISH_RISK_DETECTED: '检测到发布风险，批次已停止',
    MUTATION_OUTCOME_UNCERTAIN: '保存动作结果不确定，需要人工复核',
    OUTCOME_IDENTITY_DRIFT: '商品或浏览器身份发生变化',
    EVIDENCE_MISSING: '结果证据不完整，需要人工复核',
    SESSION_LOST: '浏览器会话已丢失',
    STOP_REQUESTED: '操作员请求停止',
  }
  return labels[reasonCode] ?? '执行未能安全继续，需要人工复核'
}

function progressSummary(detail: EditBatchDetail, progress: EditBatchProgressSummary) {
  if (detail.status === 'completed') return `已完成 ${progress.total} 件，全部结束。`
  if (detail.status === 'stopped') return detail.execution?.manual_review_required || detail.execution?.requires_manual_review
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
