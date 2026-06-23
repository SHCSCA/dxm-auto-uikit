import { useMemo, useState } from 'react'
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
  const saveSteps = [
    {
      title: '选择已进入采集箱的商品',
      detail: claimedProducts.length ? '从第一段认领结果中选择，不能绕过采集认领。' : '还没有采集箱商品，请先完成数据采集认领。',
      state: selectedProduct ? '已选择' : '待处理',
    },
    {
      title: '确认本次使用的模板',
      detail: '到模板中心确认标题、类目、价格、图片、物流和合规字段的最终取值。',
      state: selectedTask ? '待确认' : '待创建任务',
    },
    {
      title: '人工确认只保存',
      detail: '保存前由人工确认本次只点击保存，不发布、不批量、不无人值守。',
      state: selectedTask ? '等待确认' : '待创建任务',
    },
    {
      title: '启动 Agent 保存',
      detail: '打开真实浏览器，Agent 从采集箱进入编辑页并执行填写。',
      state: selectedTask ? '可前往执行浏览器' : '待创建任务',
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
    <section className="module-layout" aria-label="编辑保存">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第二段</span>
            <h2>采集箱编辑保存</h2>
            <p>只允许从采集箱商品开始。编辑保存只接受第一段已经认领到采集箱的真实商品；当前模式：只保存，不发布。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            去模板中心
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
            {claimedProducts.map((product) => (
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
                <small>SKU {product.sku_count}，图片 {product.image_count}，状态 {product.status}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="gate-note">
            <strong>还没有可编辑的采集箱商品</strong>
            <span>请先完成采集认领，确认商品进入采集箱后再创建编辑保存任务。</span>
            <button className="button button--primary" type="button" onClick={onShowAcquisition}>
              去数据采集认领
            </button>
          </div>
        )}

        <div className="gate-note gate-note--danger">
          <strong>发布动作会立即停止</strong>
          <span>本功能只点击“保存”。如果页面出现“发布”“保存并发布”“移入待发布”，系统会停止并要求人工处理。</span>
        </div>

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={createSaveTask} disabled={busy || !canCreateTask}>
            创建采集箱编辑保存任务
          </button>
          <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={!selectedTask}>
            去执行浏览器
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
          <li>去模板中心确认编辑页取值。</li>
          <li>人工确认后去执行浏览器启动 Agent 保存。</li>
        </ol>
        <div className="action-row action-row--stacked">
          <button className="button button--secondary" type="button" onClick={onShowAcquisition}>
            去数据采集认领
          </button>
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            去模板中心
          </button>
          <button className="button button--primary" type="button" onClick={onShowExecutionConsole} disabled={!selectedTask}>
            去执行浏览器
          </button>
        </div>
      </div>
    </section>
  )
}
