import { useEffect, useMemo, useState } from 'react'
import { getJson, postJson } from '../../api'
import type {
  DraftBoxScopeSnapshot,
  DraftBoxScopeSnapshotCreateRequest,
  EditBatchApproveAndStartRequest,
  EditBatchCreateRequest,
  EditBatchDetail,
  Store,
  Template,
} from '../../types'

type ActiveBatchExecution = {
  kind: 'batch' | 'task'
  id: number
  label: string
} | null

type BatchFlowBlocker = {
  title: string
  detail: string
  action: string
  onAction: () => void
} | null

type BatchEditPageProps = {
  stores: Store[]
  templates: Template[]
  scopeSnapshot: DraftBoxScopeSnapshot | null
  initialBatchId: number | null
  activeExecution: ActiveBatchExecution
  batchStateAvailable: boolean
  dxmReady: boolean
  diagnosticBrowserActive: boolean
  onScopeSnapshotChange: (snapshot: DraftBoxScopeSnapshot | null) => void
  onBatchSelected: (batchId: number | null) => void
  onShowTemplates: () => void
  onShowRecords: (batchId?: number) => void
  onShowDxmAccess: () => void
  onShowConsole: () => void
  onShowTasks: () => void
  onCreateSingleSave: (storeId: number, productId: number) => Promise<void>
  onRefreshStatus: () => Promise<void> | void
}

const scopeLimits = [5, 10, 20, 50]

export function BatchEditPage({
  stores,
  templates,
  scopeSnapshot,
  initialBatchId,
  activeExecution,
  batchStateAvailable,
  dxmReady,
  diagnosticBrowserActive,
  onScopeSnapshotChange,
  onBatchSelected,
  onShowTemplates,
  onShowRecords,
  onShowDxmAccess,
  onShowConsole,
  onShowTasks,
  onCreateSingleSave,
  onRefreshStatus,
}: BatchEditPageProps) {
  const storeLevelBatchTemplates = useMemo(
    () => templates.filter((template) => (
      template.template_type === 'edit_batch_bundle'
      && template.is_enabled
      && isStoreLevelBatchTemplate(template)
    )),
    [templates],
  )
  const batchTemplates = useMemo(
    () => scopeSnapshot
      ? storeLevelBatchTemplates.filter((template) => templateMatchesScopeStore(template, scopeSnapshot.store_identity.store_name, stores))
      : storeLevelBatchTemplates,
    [scopeSnapshot, storeLevelBatchTemplates, stores],
  )
  const hiddenLegacyBundleCount = useMemo(
    () => templates.filter((template) => (
      template.template_type === 'edit_batch_bundle'
      && template.is_enabled
      && !isStoreLevelBatchTemplate(template)
    )).length,
    [templates],
  )
  const hiddenOtherStoreBundleCount = Math.max(0, storeLevelBatchTemplates.length - batchTemplates.length)
  const [maxItems, setMaxItems] = useState(5)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [selectedSingleProductId, setSelectedSingleProductId] = useState('')
  const [draftBatch, setDraftBatch] = useState<EditBatchDetail | null>(null)
  const [approvedBy, setApprovedBy] = useState('')
  const [saveOnlyConfirmed, setSaveOnlyConfirmed] = useState(false)
  const [startOutcomeUnknown, setStartOutcomeUnknown] = useState(false)
  const [busyAction, setBusyAction] = useState<'load' | 'capture' | 'single' | 'create' | 'start' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ownsActiveBatch = activeExecution?.kind === 'batch' && activeExecution.id === draftBatch?.id
  const flowBlocker: BatchFlowBlocker = activeExecution && !ownsActiveBatch
    ? activeExecution.kind === 'batch'
      ? {
          title: `${activeExecution.label} 正在严格串行执行`,
          detail: '全局一次只执行一个真实写入流程。当前批次结束前不能读取、冻结或启动另一批。',
          action: '查看正在执行的批次',
          onAction: () => onShowRecords(activeExecution.id),
        }
      : {
          title: `${activeExecution.label} 正在执行`,
          detail: '全局一次只执行一个真实写入流程。当前任务结束前不能启动商品箱整批编辑。',
          action: '查看当前保存任务',
          onAction: onShowTasks,
        }
    : !batchStateAvailable
      ? {
          title: '批次占用状态暂时无法确认',
          detail: '为避免并发真实写入，当前不会读取范围、冻结草稿或启动批次。',
          action: '刷新占用状态',
          onAction: onRefreshStatus,
        }
      : diagnosticBrowserActive
        ? {
            title: '旧诊断浏览器正在占用共享浏览器',
            detail: '关闭运行中的旧诊断浏览器后再读取范围或批准批次；不需要先打开诊断浏览器。',
            action: '前往浏览器诊断',
            onAction: onShowConsole,
          }
        : !dxmReady
          ? {
              title: '先完成真实店小秘登录',
              detail: '登录状态确认后才能读取真实商品箱范围；当前不会执行保存或发布。',
              action: '登录店小秘',
              onAction: onShowDxmAccess,
            }
          : null

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
    const available = (scopeSnapshot?.items ?? []).filter((item) => item.local_product_id)
    if (!available.length) {
      setSelectedSingleProductId('')
      return
    }
    if (!available.some((item) => String(item.local_product_id) === selectedSingleProductId)) {
      setSelectedSingleProductId(String(available[0].local_product_id))
    }
  }, [scopeSnapshot, selectedSingleProductId])

  useEffect(() => {
    if (!initialBatchId || draftBatch?.id === initialBatchId) return
    let cancelled = false
    setBusyAction('load')
    setError(null)
    void getJson<EditBatchDetail>(`/api/edit-batches/${initialBatchId}`)
      .then((batch) => {
        if (!cancelled) {
          setDraftBatch(batch)
          setStartOutcomeUnknown(false)
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(humanBatchError(caught, '读取批次失败', 'state_read'))
      })
      .finally(() => {
        if (!cancelled) setBusyAction(null)
      })
    return () => {
      cancelled = true
    }
  }, [draftBatch?.id, initialBatchId])

  async function captureLiveScope() {
    if (flowBlocker) return
    onBatchSelected(null)
    setBusyAction('capture')
    setError(null)
    try {
      const snapshot = await postJson<DraftBoxScopeSnapshot>('/api/dxm/draft-box/scope-snapshots', {
        max_items: maxItems,
      } satisfies DraftBoxScopeSnapshotCreateRequest)
      onScopeSnapshotChange(snapshot)
      setDraftBatch(null)
      setStartOutcomeUnknown(false)
      void Promise.resolve().then(() => onRefreshStatus()).catch(() => undefined)
    } catch (caught) {
      onScopeSnapshotChange(null)
      setError(humanBatchError(caught, '读取商品箱现场失败', 'pre_dispatch'))
    } finally {
      setBusyAction(null)
    }
  }

  async function createDraftBatch() {
    if (flowBlocker || !scopeSnapshot || !selectedTemplate) return
    setBusyAction('create')
    setError(null)
    try {
      const created = await postJson<EditBatchDetail>('/api/edit-batches', {
        scope_snapshot_id: scopeSnapshot.id,
        template_id: selectedTemplate.id,
      } satisfies EditBatchCreateRequest)
      setDraftBatch(created)
      onScopeSnapshotChange(null)
      onBatchSelected(created.id)
      setApprovedBy('')
      setSaveOnlyConfirmed(false)
      setStartOutcomeUnknown(false)
    } catch (caught) {
      setError(humanBatchError(caught, '冻结批次草稿失败', 'pre_dispatch'))
    } finally {
      setBusyAction(null)
    }
  }

  async function createSingleSaveTask() {
    const storeId = scopeSnapshot?.store_identity.store_id
    const productId = Number(selectedSingleProductId)
    if (!storeId || !Number.isInteger(productId) || productId <= 0) return
    setBusyAction('single')
    setError(null)
    try {
      await onCreateSingleSave(storeId, productId)
    } catch (caught) {
      setError(humanBatchError(caught, '创建单商品只保存任务失败', 'pre_dispatch'))
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
    if (flowBlocker || !draftBatch || draftBatch.status !== 'draft' || !approvedBy.trim() || !saveOnlyConfirmed) return
    setBusyAction('start')
    setError(null)
    setStartOutcomeUnknown(false)
    try {
      const started = await postJson<EditBatchDetail>(`/api/edit-batches/${draftBatch.id}/approve-and-start`, {
        approved_by: approvedBy.trim(),
        confirmation: 'CONFIRM_DXM_BATCH_SAVE_ONLY',
      } satisfies EditBatchApproveAndStartRequest)
      setDraftBatch(started)
      onShowRecords(started.id)
    } catch (caught) {
      setError(humanBatchError(caught, '批准并开始批次失败', 'approve_start'))
      setStartOutcomeUnknown(true)
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
            <div><dt>店铺</dt><dd>{draftBatch.scope_snapshot.store_identity?.store_name ?? '店铺已冻结'}</dd></div>
            <div><dt>模板</dt><dd>{draftBatch.template_snapshot.template_name ?? '模板已冻结'} · {templateVersion(draftBatch.template_snapshot)}</dd></div>
          </dl>
          {isDraft && flowBlocker ? (
            <BatchFlowBlockerCard blocker={flowBlocker} />
          ) : isDraft ? (
            <div className="batch-approval-card" aria-label="整批一次批准">
              <div className="batch-approval-card__intro">
                <strong>批准并开始</strong>
                <span>这次批准只适用于上方已冻结范围；保存前变化会零写入停止，结果不确定才转人工对账。</span>
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
                  <small>逐件串行；保存前安全停止无需对账，结果不确定停止且不自动重试。</small>
                </span>
              </label>
              {error && <div className="batch-inline-error" role="alert">{error}</div>}
              {startOutcomeUnknown ? (
                <button className="button button--primary batch-primary-action" type="button" onClick={() => onShowRecords(draftBatch.id)}>
                  刷新批次记录
                </button>
              ) : (
                <button
                  className="button button--primary batch-primary-action"
                  type="button"
                  onClick={() => { void approveAndStartBatch() }}
                  disabled={busyAction !== null || !approvedBy.trim() || !saveOnlyConfirmed}
                >
                  {busyAction === 'start' ? '正在批准并开始…' : '批准并开始'}
                </button>
              )}
            </div>
          ) : (
            <button className="button button--primary batch-primary-action" type="button" onClick={() => onShowRecords(draftBatch.id)}>
              查看实时批次记录
            </button>
          )}
        </article>
      </section>
    )
  }

  return (
    <section className="module-layout batch-edit-page" aria-label="批量编辑商品">
      {/* PublishGuard Banner - Permanent Warning */}
      <div className="publishguard-banner publishguard-banner--batch" role="alert">
        <strong>⚠ 本系统仅支持草稿保存，禁止任何发布操作</strong>
        <p>最终发布永久禁止：立即发布、保存并发布、上线等按钮均已永久禁用。</p>
      </div>

      <article className="module-card span-3 batch-builder-head">
        <div className="module-head">
          <div>
            <span className="eyebrow">批量编辑 · 真实商品箱现场</span>
            <h2>冻结当前商品箱范围</h2>
            <p>本页开放受控逐件批次：范围冻结、一次批准、严格串行、只保存。旧版批量保存、无人值守和发布仍关闭。</p>
          </div>
          <span className="batch-boundary-chip">只保存 · 不发布</span>
        </div>
      </article>

      {flowBlocker ? (
        <article className="module-card span-3 batch-capture-card">
          <BatchFlowBlockerCard blocker={flowBlocker} />
        </article>
      ) : !scopeSnapshot ? (
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
              <strong>{storeLevelBatchTemplates.length ? '店铺级模板候选已准备' : '模板尚未就绪'}</strong>
              <small>{storeLevelBatchTemplates.length
                ? '读取现场店铺后，只保留店铺身份精确一致的整批模板。'
                : hiddenLegacyBundleCount
                  ? '旧的类目绑定或无明确店铺整批模板已隐藏；必须重新生成店铺级模板。'
                  : '不影响只读范围读取；创建草稿前必须到模板中心准备完整模板包。'}</small>
            </span>
            <b>{storeLevelBatchTemplates.length ? `${storeLevelBatchTemplates.length} 套候选` : '先读取现场，再补模板'}</b>
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
              <span>店铺、顺序和商品身份已从当前现场读取；创建草稿后会与模板一起固定。</span>
              <span>{isZeroWriteProven(scopeSnapshot.zero_write_proof) ? '本次读取未执行导航、点击或写入。' : '只读边界尚未得到确认。'}</span>
            </div>
            {error && <div className="batch-inline-error" role="alert">{error}</div>}
            {scopeSnapshot.store_identity.store_id && scopeSnapshot.items.some((item) => item.local_product_id) ? (
              <div className="batch-template-inline" aria-label="单商品只保存入口">
                <label htmlFor="single-save-product">
                  <span>单商品只保存</span>
                  <select
                    id="single-save-product"
                    value={selectedSingleProductId}
                    onChange={(event) => setSelectedSingleProductId(event.target.value)}
                    disabled={busyAction !== null}
                  >
                    {scopeSnapshot.items.filter((item) => item.local_product_id).map((item) => (
                      <option value={String(item.local_product_id)} key={item.ordinal}>{item.ordinal}. {item.title}</option>
                    ))}
                  </select>
                  <small>使用本次实时商品箱证据创建一个受控任务；仍需配置检查、商品箱 L2 和人工批准。</small>
                </label>
                <button className="button button--secondary" type="button" onClick={() => { void createSingleSaveTask() }} disabled={busyAction !== null || !selectedSingleProductId}>
                  {busyAction === 'single' ? '正在创建单商品任务…' : '创建单商品只保存任务'}
                </button>
              </div>
            ) : (
              <div className="batch-template-blocker" role="status">
                <strong>先连接现场店铺</strong>
                <span>当前商品箱店铺未与工作台中的唯一店铺匹配；范围已安全读取，但不能创建真实保存任务。</span>
              </div>
            )}
            {selectedTemplate ? (
              <>
                <label className="batch-template-select" htmlFor="batch-template">
                  <span>整批编辑模板</span>
                  <select id="batch-template" value={String(selectedTemplate.id)} onChange={(event) => setSelectedTemplateId(event.target.value)} disabled={busyAction !== null}>
                    {batchTemplates.map((template) => (
                      <option value={String(template.id)} key={template.id}>{template.template_name} · {templateVersion(template)}</option>
                    ))}
                  </select>
                  <small>仅列出与当前现场店铺一致的店铺级整批模板；后端会再次验证全部必需分区。</small>
                </label>
                <button className="button button--primary batch-primary-action" type="button" onClick={() => { void createDraftBatch() }} disabled={busyAction !== null}>
                  {busyAction === 'create' ? '正在冻结草稿…' : '冻结批次草稿'}
                </button>
                <button className="button button--quiet" type="button" onClick={onShowTemplates} disabled={busyAction !== null}>检查模板中心</button>
              </>
            ) : (
              <div className="batch-template-blocker" role="status">
                <strong>整批模板未就绪</strong>
                <span>{hiddenOtherStoreBundleCount
                  ? `现有店铺级模板属于其他店铺，与 ${scopeSnapshot.store_identity.store_name} 不一致。现场已安全读取，但不能创建草稿。`
                  : hiddenLegacyBundleCount
                    ? '现有模板仍绑定类目或缺少明确店铺，无法用当前商品箱现场精确核对。现场已安全读取，但不能创建草稿。'
                    : '当前生产数据中没有已启用的完整整批模板。现场已安全读取，但不能创建草稿。'}</span>
                <button className="button button--primary batch-primary-action" type="button" onClick={onShowTemplates}>重新生成店铺级整批模板</button>
              </div>
            )}
          </aside>
        </>
      )}
    </section>
  )
}

function humanBatchError(caught: unknown, action: string, phase: 'state_read' | 'pre_dispatch' | 'approve_start') {
  const message = caught instanceof Error ? caught.message.trim() : ''
  const normalized = message.toLowerCase()
  if (phase === 'approve_start') {
    return '批准并启动的结果暂未确认。请先刷新批次记录；系统不会自动重试，在状态明确前禁止重复批准或启动。必要时人工核对真实店小秘页面。'
  }
  if (phase === 'state_read') {
    return '批次状态暂未读取成功。请刷新批次记录；状态明确前不要重复批准或启动。'
  }
  if (
    normalized.includes('已有任务')
    || normalized.includes('已有批次')
    || normalized.includes('正在占用')
    || normalized.includes('already running')
    || normalized.includes('another edit batch')
  ) {
    return '当前已有任务或批次正在执行。请先结束当前任务或批次，再回来批准本批次。'
  }
  if (
    normalized.includes('agent console')
    || normalized.includes('诊断浏览器')
    || normalized.includes('浏览器现场')
    || normalized.includes('browser is busy')
  ) {
    return '旧浏览器诊断窗口仍在运行。请先到“浏览器诊断”关闭该窗口，再回来读取范围或批准批次。系统没有执行保存。'
  }
  if (normalized.includes('template')) return '整批模板未通过完整性检查。请在模板中心启用完整的整批编辑模板后重试；系统没有执行保存或发布。'
  if (normalized.includes('session') || normalized.includes('browser')) return '当前店小秘登录会话已变化或不可用。请重新检测登录状态，并确认旧诊断浏览器已关闭后重试；系统没有执行保存或发布。'
  if (normalized.includes('scope') || normalized.includes('draft-box') || normalized.includes('draft box')) return '当前商品箱范围不能安全冻结。请确认页面、店铺和商品顺序后重新读取；系统没有执行保存或发布。'
  return `${action}。请刷新工作台后重试；系统没有执行保存或发布。`
}

function BatchFlowBlockerCard({ blocker }: { blocker: Exclude<BatchFlowBlocker, null> }) {
  return (
    <div className="batch-template-blocker" role="status">
      <strong>{blocker.title}</strong>
      <span>{blocker.detail}</span>
      <button className="button button--primary batch-primary-action" type="button" onClick={blocker.onAction}>
        {blocker.action}
      </button>
    </div>
  )
}

function templateVersion(template: Pick<Template, 'payload'> | { payload?: { version?: unknown } } | null) {
  const version = template?.payload?.version
  return typeof version === 'string' && version.trim() ? `v${version.replace(/^v/i, '')}` : '版本未标注'
}

function scopeFilterSummary(filter: Record<string, unknown>) {
  const controls = Array.isArray(filter.controls) ? filter.controls : []
  const values = controls.flatMap((control) => {
    if (!control || typeof control !== 'object') return []
    const record = control as Record<string, unknown>
    const rawKey = typeof record.key === 'string' ? record.key : ''
    const key = businessFilterLabel(rawKey)
    if (!key) return []
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
    const rawKey = typeof record.key === 'string' ? record.key : ''
    const key = businessSortLabel(rawKey)
    if (!key) return []
    const direction = humanSortDirection(typeof record.direction === 'string' ? record.direction : '')
    return [`${key}${direction ? ` ${direction}` : ''}`]
  })
  return values.length ? values.join(' · ') : '当前页面顺序'
}

function businessFilterLabel(key: string) {
  return ({
    store: '店铺',
    store_name: '店铺',
    status: '状态',
    keyword: '关键词',
    category: '类目',
    category_name: '类目',
    page_size: '每页数量',
  } as Record<string, string>)[key.trim().toLowerCase()] ?? ''
}

function businessSortLabel(key: string) {
  return ({
    created_at: '创建时间',
    updated_at: '更新时间',
    title: '商品标题',
    price: '价格',
    ordinal: '页面顺序',
  } as Record<string, string>)[key.trim().toLowerCase()] ?? ''
}

function humanSortDirection(direction: string) {
  return ({ asc: '升序', ascending: '升序', desc: '降序', descending: '降序' } as Record<string, string>)[direction.trim().toLowerCase()] ?? ''
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

function isStoreLevelBatchTemplate(template: Template) {
  const binding = template.payload?.binding
  if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return false
  const record = binding as Record<string, unknown>
  const storeId = Number(record.store_id)
  const storeName = typeof record.store_name === 'string' ? record.store_name.trim() : ''
  return Object.prototype.hasOwnProperty.call(record, 'category_name')
    && record.category_name === null
    && ((Number.isInteger(storeId) && storeId > 0) || Boolean(storeName))
}

function templateMatchesScopeStore(template: Template, scopeStoreName: string, stores: Store[]) {
  const binding = template.payload?.binding
  if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return false
  const record = binding as Record<string, unknown>
  const boundStoreName = typeof record.store_name === 'string' ? record.store_name.trim() : ''
  if (boundStoreName) return normalizeStoreName(boundStoreName) === normalizeStoreName(scopeStoreName)
  const storeId = Number(record.store_id)
  if (!Number.isInteger(storeId) || storeId <= 0) return false
  const boundStore = stores.find((store) => store.id === storeId)
  return Boolean(boundStore && normalizeStoreName(boundStore.name) === normalizeStoreName(scopeStoreName))
}

function normalizeStoreName(value: string) {
  return value.trim().toLocaleLowerCase('zh-CN')
}
