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
            <h2>从采集箱商品进入编辑页并只保存</h2>
            <p>编辑保存只接受已经认领到采集箱的真实商品。当前模式：只保存，不发布。</p>
          </div>
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            选择模板
          </button>
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
              去采集认领
            </button>
          </div>
        )}

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={createSaveTask} disabled={busy || !canCreateTask}>
            创建编辑保存任务
          </button>
          <button className="button button--secondary" type="button" onClick={onShowExecutionConsole} disabled={!selectedTask}>
            打开执行控制台
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
          <li>在模板中心确认编辑页取值。</li>
          <li>人工确认后启动真实浏览器保存。</li>
        </ol>
      </div>
    </section>
  )
}
