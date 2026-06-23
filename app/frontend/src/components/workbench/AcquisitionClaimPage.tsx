import { useMemo, useState } from 'react'
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
  { title: '填写采集商品线索', detail: '填写关键词、类目和认领标记，便于 Agent 定位商品。' },
  { title: '启动真实浏览器认领', detail: '到执行浏览器启动 Agent，只做认领，不会保存、不会发布。' },
  { title: '确认商品进入采集箱', detail: '认领完成后再进入第二段采集箱编辑保存。' },
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
  const canSubmit = Boolean(selectedStore && claimMark.trim())

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
    <section className="module-layout" aria-label="采集认领">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第一段</span>
            <h2>从店小秘数据采集认领到采集箱</h2>
            <p>先创建认领任务，再到执行浏览器启动 Agent。这里只认领到采集箱，不会进入编辑页，不会保存，不会发布。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onNavigateDataAcquisition} disabled={busy}>
            打开真实数据采集页
          </button>
        </div>

        <ol className="operation-guide" aria-label="数据采集认领四步">
          {claimSteps.map((step, index) => (
            <li key={step.title} className={lastRequest && index === 0 ? 'is-done' : ''}>
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
            <span>搜索关键词</span>
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="用于在数据采集中定位商品" disabled={busy} />
          </label>
          <label>
            <span>认领类目</span>
            <input value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="例如：立牌类谷子" disabled={busy} />
          </label>
          <label>
            <span>认领标记</span>
            <input value={claimMark} onChange={(event) => setClaimMark(event.target.value)} placeholder="例如：AI-OPS" disabled={busy} />
          </label>
          <label>
            <span>后续模板</span>
            <select value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={busy}>
              <option value="">稍后在模板中心选择</option>
              {enabledTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.template_name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={submit} disabled={busy || !canSubmit}>
            创建采集认领请求
          </button>
          {lastRequest && (
            <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={busy}>
              去执行浏览器启动认领
            </button>
          )}
          <button className="button button--quiet" type="button" onClick={onShowDraftEdit}>
            去采集箱编辑保存
          </button>
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
            <span><strong>阶段</strong><b>等待启动真实浏览器认领</b></span>
            <span><strong>标记</strong><b>{lastRequest.claim_mark}</b></span>
            <span><strong>下一步</strong><b>去执行浏览器启动认领</b></span>
          </div>
        ) : (
          <p>创建后，Agent 会按该请求进入真实店小秘数据采集页处理认领；认领完成前不会保存或发布。</p>
        )}
      </div>
    </section>
  )
}
