import { useEffect, useMemo, useState } from 'react'
import type { Product, Task } from '../../types'

type DraftEditSavePageProps = {
  claimedProducts: Product[]
  selectedTask: Task | null
  busy: boolean
  onCreateSaveTask: (productId: number) => void
  onShowAcquisition: () => void
  onShowTemplates: () => void
  onShowExecutionConsole: () => void
}

export function DraftEditSavePage({
  claimedProducts,
  selectedTask,
  busy,
  onCreateSaveTask,
  onShowAcquisition,
  onShowTemplates,
  onShowExecutionConsole,
}: DraftEditSavePageProps) {
  const [selectedProductId, setSelectedProductId] = useState(claimedProducts[0]?.id ? String(claimedProducts[0].id) : '')
  const selectedProduct = useMemo(
    () => claimedProducts.find((product) => String(product.id) === selectedProductId) ?? claimedProducts[0] ?? null,
    [claimedProducts, selectedProductId],
  )
  const canCreateTask = Boolean(selectedProduct)

  useEffect(() => {
    if (!claimedProducts.length) {
      if (selectedProductId) setSelectedProductId('')
      return
    }
    if (!claimedProducts.some((product) => String(product.id) === selectedProductId)) {
      setSelectedProductId(String(claimedProducts[0].id))
    }
  }, [claimedProducts, selectedProductId])

  const saveSteps = [
    {
      title: '选择已进入采集箱的商品',
      detail: claimedProducts.length ? '从第一段认领结果中选择，不能绕过采集认领。' : '还没有采集箱商品，请先完成数据采集认领。',
      state: selectedProduct ? '已选择' : '待处理',
    },
    {
      title: '确认本次使用的模板',
      detail: '检查编辑页模板，确认标题、类目、价格、图片、物流和合规字段的最终取值。',
      state: selectedTask ? '待确认' : '待创建任务',
    },
    {
      title: '人工确认只保存',
      detail: '保存前由人工确认本次只点击保存，不发布、不批量、不无人值守。',
      state: selectedTask ? '等待确认' : '待创建任务',
    },
    {
      title: '开始编辑并只保存',
      detail: '打开真实浏览器，从采集箱进入编辑页并按模板填写。',
      state: selectedTask ? '可前往浏览器现场' : '待创建任务',
    },
    {
      title: '查看保存结果',
      detail: '保存完成后查看保存成功证据和未发布证明。',
      state: '结果页查看',
    },
  ]

  function createSaveTask() {
    if (!selectedProduct) return
    onCreateSaveTask(selectedProduct.id)
  }

  return (
    <section className="module-layout" aria-label="采集箱商品">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第二段</span>
            <h2>采集箱商品</h2>
            <p>这里只显示第一段已认领并通过采集箱确认的真实商品。选择商品后，再创建编辑保存任务；当前模式：只保存，不发布。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            检查编辑页模板
          </button>
        </div>

        <div className="task-flow-steps" aria-label="采集箱编辑保存步骤">
          {saveSteps.map((step, index) => (
            <article className="task-flow-step" key={step.title}>
              <span>{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.detail}</p>
                <small>{step.state}</small>
              </div>
            </article>
          ))}
        </div>

        <div className="status-grid">
          <span><strong>采集箱商品</strong><b>{claimedProducts.length ? `${claimedProducts.length} 个可处理` : '暂无'}</b></span>
          <span><strong>当前任务</strong><b>{selectedTask ? selectedTask.name : '等待创建'}</b></span>
          <span><strong>保存边界</strong><b>只保存，不发布</b></span>
        </div>

        {claimedProducts.length ? (
          <div className="real-task-products" aria-label="采集箱商品">
            {claimedProducts.map((product) => {
              const payload = productPayload(product)
              const draftBoxVerified = product.draft_box_verified === true || payload.draft_box_verified === true
              const sourceUrl = textValue(product.source_url) || textValue(payload.source_url) || textValue(payload.url)
              const claimTaskId = textValue(product.claim_task_id) || textValue(payload.claim_task_id)
              const sourceLabel = textValue(product.source_status_label) || (textValue(payload.source ?? product.source) === 'dxm_data_acquisition'
                ? '真实数据采集'
                : '等待来源确认')
              const lifecycleLabel = textValue(product.lifecycle_label) || humanProductStatus(product.status)
              const draftBoxVerificationLabel = textValue(product.draft_box_verification_label) || (draftBoxVerified ? '已通过采集箱验证' : '等待验证')
              return (
                <button
                  key={product.id}
                  className={`task-product-choice ${selectedProduct?.id === product.id ? 'is-selected' : ''}`}
                  type="button"
                  onClick={() => setSelectedProductId(String(product.id))}
                  disabled={busy}
                  aria-pressed={selectedProduct?.id === product.id}
                >
                  <strong>{product.title}</strong>
                  <span>{product.category_name || '未指定类目'}</span>
                  <small>SKU {product.sku_count}，图片 {product.image_count}，{lifecycleLabel}</small>
                  <small>采集箱验证：{draftBoxVerificationLabel}</small>
                  <small>商品来源：{sourceLabel}</small>
                  <small>来源链接：{sourceUrl || '等待来源链接'}</small>
                  <small>认领任务：{claimTaskId ? `#${claimTaskId}` : '等待认领任务'}</small>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="gate-note">
            <strong>还没有可编辑的采集箱商品</strong>
            <span>请先完成采集认领，确认商品进入采集箱后再创建编辑保存任务。</span>
            <button className="button button--primary" type="button" onClick={onShowAcquisition}>
              去采集认领
            </button>
          </div>
        )}

        <div className="gate-note gate-note--danger">
          <strong>发布动作会立即停止</strong>
          <span>本功能只点击“保存”。如果页面出现“发布”“保存并发布”“移入待发布”，系统会停止并要求人工处理。</span>
        </div>

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={createSaveTask} disabled={busy || !canCreateTask}>
            创建编辑保存任务
          </button>
          <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={!selectedTask}>
            开始编辑并只保存
          </button>
        </div>
      </div>

      <div className="module-card span-1">
        <div className="module-head">
          <h2>下一步</h2>
          <span>{selectedTask ? '等待人工确认' : '先创建任务'}</span>
        </div>
        <ol className="plain-list">
          <li>确认采集箱商品正确。</li>
          <li>检查编辑页模板并确认最终取值。</li>
          <li>人工确认后进入浏览器现场开始只保存。</li>
        </ol>
        <div className="action-row action-row--stacked">
          <button className="button button--secondary" type="button" onClick={onShowAcquisition}>
            去采集认领
          </button>
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            检查编辑页模板
          </button>
          <button className="button button--primary" type="button" onClick={onShowExecutionConsole} disabled={!selectedTask}>
            开始编辑并只保存
          </button>
        </div>
      </div>
    </section>
  )
}

function humanProductStatus(status: string) {
  return ({
    claimed_to_draft: '已进入采集箱，可编辑保存',
    ready_for_edit: '已确认可编辑保存',
    draft: '等待采集认领',
  } as Record<string, string>)[status] ?? '等待处理'
}

function productPayload(product: Product): Record<string, unknown> {
  return product.payload && typeof product.payload === 'object' ? product.payload : {}
}

function textValue(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
