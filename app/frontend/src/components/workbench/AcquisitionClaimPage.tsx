import { useEffect, useMemo, useState } from 'react'
import type { AcquisitionClaimCreateRequest, AcquisitionClaimResponse, Store, Template } from '../../types'

type AcquisitionClaimPageProps = {
  stores: Store[]
  templates: Template[]
  busy: boolean
  lastRequest: AcquisitionClaimResponse | null
  onCreateClaimRequest: (request: AcquisitionClaimCreateRequest) => void
  onNavigateDataAcquisition: () => void
  onShowDraftEdit: () => void
  onShowExecutionConsole: () => void
}

const claimSteps = [
  { title: '选择店铺与平台', detail: '确认这次认领使用哪个真实店小秘店铺。' },
  { title: '筛选已有待认领商品', detail: '填写关键词或类目，只筛选店小秘已有列表。' },
  { title: '认领到商品箱', detail: '打开浏览器现场处理认领，完成后进入第二段编辑保存。' },
  { title: '确认进入商品箱', detail: '认领完成后再进入第二段商品编辑保存。' },
]

export function AcquisitionClaimPage({
  stores,
  templates,
  busy,
  lastRequest,
  onCreateClaimRequest,
  onNavigateDataAcquisition,
  onShowDraftEdit,
  onShowExecutionConsole,
}: AcquisitionClaimPageProps) {
  const defaultStoreId = stores[0]?.id ? String(stores[0].id) : ''
  const [storeId, setStoreId] = useState(defaultStoreId)
  const [keyword, setKeyword] = useState('')
  const [categoryName, setCategoryName] = useState('')
  const [claimMark, setClaimMark] = useState('AI-OPS')
  const [templateId, setTemplateId] = useState('')
  const selectedStore = useMemo(
    () => stores.find((store) => String(store.id) === storeId) ?? stores[0] ?? null,
    [stores, storeId],
  )
  const enabledTemplates = templates.filter((template) => template.is_enabled)
  const hasProductHint = Boolean(keyword.trim() || categoryName.trim())
  const canSubmit = Boolean(selectedStore && claimMark.trim() && hasProductHint)
  const claimCompleted = Boolean(
    lastRequest && (
      lastRequest.stage === 'claimed_to_draft'
      || lastRequest.status === 'completed'
      || lastRequest.task_status === 'completed'
      || lastRequest.claimed_product_id
    ),
  )
  const draftBoxVerified = lastRequest?.draft_box_verified === true
  const claimedSourceLabel = lastRequest?.claimed_product_source === 'dxm_data_acquisition'
    ? '店小秘已有待认领商品'
    : lastRequest?.claimed_product_source || '等待认领完成'

  useEffect(() => {
    if (!stores.length) {
      if (storeId) setStoreId('')
      return
    }
    if (!stores.some((store) => String(store.id) === storeId)) {
      setStoreId(String(stores[0].id))
    }
  }, [storeId, stores])

  function submit() {
    if (!selectedStore || !canSubmit) return
    onCreateClaimRequest({
      storeId: selectedStore.id,
      keyword: keyword.trim() || undefined,
      categoryName: categoryName.trim() || undefined,
      claimMark: claimMark.trim(),
      templateId: templateId ? Number(templateId) : null,
    })
  }

  return (
    <section className="module-layout" aria-label="待认领入箱">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第一段</span>
            <h2>把已有待认领商品放进商品箱</h2>
            <p>只处理店小秘里已经存在的待认领商品。系统会筛选列表并点击认领，不会填写产品网址，也不会创建新的来源商品。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onNavigateDataAcquisition} disabled={busy}>
            打开已有待认领列表
          </button>
        </div>

        <ol className="operation-guide" aria-label="待认领入箱四步">
          {claimSteps.map((step, index) => (
            <li key={step.title} className={claimCompleted || (lastRequest && index < 2) ? 'is-done' : ''}>
              <span>{index + 1}</span>
              <strong>{step.title}</strong>
              <small>{step.detail}</small>
            </li>
          ))}
        </ol>

        <div className="config-grid">
          <label>
            <span>店铺</span>
            <select value={storeId} onChange={(event) => setStoreId(event.target.value)} disabled={busy || !stores.length}>
              {stores.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name} / {store.platform}
                </option>
              ))}
              {!stores.length && <option value="">等待真实店铺</option>}
            </select>
          </label>
          <label>
            <span>商品关键词</span>
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="筛选已有待认领列表" disabled={busy} />
          </label>
          <label>
            <span>商品类目</span>
            <input value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="例如：立牌类谷子" disabled={busy} />
          </label>
          <label>
            <span>认领标记</span>
            <input value={claimMark} onChange={(event) => setClaimMark(event.target.value)} placeholder="例如：AI-OPS" disabled={busy} />
          </label>
          <label>
            <span>后续模板</span>
            <select value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={busy}>
              <option value="">稍后在编辑页模板选择</option>
              {enabledTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.template_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!hasProductHint && (
          <p className="form-hint">请至少填写商品关键词或商品类目，用来定位店小秘已有待认领商品。</p>
        )}

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={submit} disabled={busy || !canSubmit}>
            创建商品认领任务
          </button>
          {lastRequest && !claimCompleted && (
            <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={busy}>
              开始认领到商品箱
            </button>
          )}
          {lastRequest && claimCompleted && (
            <>
              <button className="button button--primary" type="button" onClick={onShowDraftEdit} disabled={busy}>
                查看商品箱商品
              </button>
              <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={busy}>
                查看执行记录
              </button>
            </>
          )}
        </div>
      </div>

      <div className="module-card span-1">
        <div className="module-head">
          <h2>认领状态</h2>
          <span>{lastRequest ? '已创建' : '等待创建'}</span>
        </div>
        {lastRequest ? (
          <div className="status-grid">
            <span><strong>店铺</strong><b>{selectedStore?.name ?? lastRequest.store_id}</b></span>
            <span><strong>阶段</strong><b>{claimCompleted ? '商品已进入商品箱' : '等待启动真实浏览器认领'}</b></span>
            <span><strong>标记</strong><b>{lastRequest.claim_mark}</b></span>
            <span><strong>下一步</strong><b>{claimCompleted ? '去“商品箱编辑保存”选择该商品' : '认领到商品箱'}</b></span>
            {claimCompleted && <span><strong>商品箱商品</strong><b>{lastRequest.claimed_product_title || `商品 #${lastRequest.claimed_product_id}`}</b></span>}
            {claimCompleted && <span><strong>商品箱验证</strong><b>{draftBoxVerified ? '已确认进入商品箱' : '等待商品箱验证'}</b></span>}
            {claimCompleted && <span><strong>商品来源</strong><b>{claimedSourceLabel}</b></span>}
            {claimCompleted && <span><strong>认领类目</strong><b>{lastRequest.claimed_product_category_name || lastRequest.category_name || '等待类目'}</b></span>}
            {claimCompleted && <span><strong>商品箱身份</strong><b>{lastRequest.claimed_product_id ? `商品 #${lastRequest.claimed_product_id}` : '等待商品箱确认'}</b></span>}
          </div>
        ) : (
          <p>创建后，系统会进入店小秘已有待认领列表处理认领；认领完成前不会进入编辑保存。</p>
        )}
      </div>
    </section>
  )
}
