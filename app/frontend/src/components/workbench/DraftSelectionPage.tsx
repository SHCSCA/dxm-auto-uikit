import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getJson } from '../../api'
import {
  DraftProductIdentityConflictError,
  MIN_DRAFT_SELECTION,
  ReaderSessionChangedError,
  assertRealDraftPageResponse,
  assertRealDraftShopsResponse,
  buildConfirmedDraftTaskInput,
  invalidateDraftSelectionState,
  mergeDraftSelection,
  mergeDraftProductSelection,
  readerSourceLabel,
  resetSelectionForShopChange,
  toggleDraftSelection,
  type ConfirmedDraftTaskInput,
  type DraftSelectionInvalidationReason,
} from '../../draftSelection'
import type {
  DxmDraftPageResponse,
  DxmDraftProduct,
  DxmDraftShopsResponse,
  LocalPlanTemplate,
  Template,
} from '../../types'


type DraftSelectionPageProps = {
  plans: Template[]
  localPlans?: LocalPlanTemplate[]
  taskInput: ConfirmedDraftTaskInput | null
  onTaskInputChange: (taskInput: ConfirmedDraftTaskInput | null) => void
  onShowDxmAccess: () => void
  onShowPlans: () => void
  onReviewSnapshot: () => boolean
}

const PAGE_SIZE = 20

const emptyPagination: DxmDraftPageResponse['pagination'] = {
  page_no: 1,
  page_size: PAGE_SIZE,
  total_pages: 0,
  total_items: 0,
  has_previous: false,
  has_next: false,
}

export function DraftSelectionPage({
  plans,
  localPlans: e2LocalPlans,
  taskInput,
  onTaskInputChange,
  onShowDxmAccess,
  onShowPlans,
  onReviewSnapshot,
}: DraftSelectionPageProps) {
  const [shopsResponse, setShopsResponse] = useState<DxmDraftShopsResponse | null>(null)
  const [products, setProducts] = useState<DxmDraftProduct[]>([])
  const [pagination, setPagination] = useState(emptyPagination)
  const [shopId, setShopId] = useState('-1')
  const [pageNo, setPageNo] = useState(1)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectedProducts, setSelectedProducts] = useState<Record<string, DxmDraftProduct>>({})
  const [planId, setPlanId] = useState('')
  const [shopsLoading, setShopsLoading] = useState(true)
  const [productsLoading, setProductsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [productSessionRef, setProductSessionRef] = useState<string | null>(null)
  const requestSequence = useRef(0)
  const readerSessionRef = useRef<string | null>(null)
  const selectedProductsRef = useRef<Record<string, DxmDraftProduct>>({})
  const confirmedHandoffRef = useRef(false)

  const availablePlans = useMemo(
    () => e2LocalPlans?.filter((plan) => plan.is_active)
      ?? plans.filter((plan) => plan.is_enabled && plan.template_type === 'edit_batch_bundle'),
    [e2LocalPlans, plans],
  )
  const selectedPlanId = Number(planId)
  const selectedPlan = availablePlans.find((plan) => plan.id === selectedPlanId) ?? null
  const selectedCount = selectedIds.length
  const pageSelectionIds = products.map((product) => product.id)
  const currentPageFullySelected = pageSelectionIds.length > 0
    && pageSelectionIds.every((productId) => selectedIds.includes(productId))
  const canReviewTask = selectedCount >= MIN_DRAFT_SELECTION
    && selectedPlan !== null
    && productSessionRef !== null
    && productSessionRef === shopsResponse?.session_ref
    && error === null

  const invalidateReaderState = useCallback((
    reason: DraftSelectionInvalidationReason,
    clearShops: boolean,
  ) => {
    const invalidated = invalidateDraftSelectionState(reason)
    requestSequence.current += 1
    setSelectedIds(invalidated.selectedIds)
    setSelectedProducts(invalidated.selectedProducts)
    selectedProductsRef.current = invalidated.selectedProducts
    setProducts([])
    setPagination(emptyPagination)
    setProductSessionRef(invalidated.sessionRef)
    setProductsLoading(false)
    onTaskInputChange(invalidated.confirmedInput)
    if (clearShops) {
      readerSessionRef.current = null
      setShopsResponse(null)
    }
  }, [onTaskInputChange])

  const loadShops = useCallback(async () => {
    setShopsLoading(true)
    try {
      const rawResponse = await getJson<unknown>('/api/dxm/draft-reader/shops')
      const response = assertRealDraftShopsResponse(rawResponse)
      const sessionChanged = readerSessionRef.current !== null
        && readerSessionRef.current !== response.session_ref
      if (sessionChanged) {
        invalidateReaderState('browser_session_change', false)
      }
      readerSessionRef.current = response.session_ref
      setShopsResponse(response)
      setError(null)
      if (sessionChanged) setNotice('真实浏览器会话已变化，原选择已清空，避免跨会话任务输入漂移。')
      return response
    } catch (caught) {
      invalidateReaderState('reader_failure', true)
      setError(humanReaderError(caught))
      return null
    } finally {
      setShopsLoading(false)
    }
  }, [invalidateReaderState])

  const loadProducts = useCallback(async (
    nextShopId: string,
    nextPageNo: number,
    expectedSessionRef: string,
  ) => {
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setProductsLoading(true)
    try {
      const params = new URLSearchParams({
        shop_id: nextShopId,
        page_no: String(nextPageNo),
        page_size: String(PAGE_SIZE),
      })
      const rawResponse = await getJson<unknown>(
        `/api/dxm/draft-reader/products?${params.toString()}`,
      )
      const response = assertRealDraftPageResponse(rawResponse, {
        shopId: nextShopId,
        sessionRef: expectedSessionRef,
      })
      if (sequence !== requestSequence.current) return
      mergeDraftProductSelection(
        selectedProductsRef.current,
        response.items.filter((product) => selectedProductsRef.current[product.id]),
      )
      setProducts(response.items)
      setPagination(response.pagination)
      setProductSessionRef(response.session_ref)
      setError((current) => current?.includes('会话已变化') ? current : null)
      setNotice((current) => response.deduplicated_count > 0
        ? `当前页已合并 ${response.deduplicated_count} 条完全相同的重复商品。`
        : current?.includes('会话已变化')
          ? current
          : null)
    } catch (caught) {
      if (sequence !== requestSequence.current) return
      const sessionChanged = caught instanceof ReaderSessionChangedError
      const identityConflict = caught instanceof DraftProductIdentityConflictError
      invalidateReaderState(
        sessionChanged
          ? 'browser_session_change'
          : identityConflict
            ? 'product_identity_conflict'
            : 'reader_failure',
        sessionChanged,
      )
      setError(humanReaderError(caught))
      if (sessionChanged) {
        setNotice('真实浏览器会话已变化，旧店铺与商品范围已失效；正在重新读取店铺。')
        void loadShops()
      }
    } finally {
      if (sequence === requestSequence.current) setProductsLoading(false)
    }
  }, [invalidateReaderState, loadShops])

  useEffect(() => {
    const invalidated = invalidateDraftSelectionState('page_remount')
    onTaskInputChange(invalidated.confirmedInput)
    return () => {
      requestSequence.current += 1
      if (!confirmedHandoffRef.current) onTaskInputChange(invalidated.confirmedInput)
    }
  }, [onTaskInputChange])

  useEffect(() => {
    void loadShops()
  }, [loadShops])

  useEffect(() => {
    if (!shopsResponse) {
      setProductsLoading(false)
      return
    }
    void loadProducts(shopId, pageNo, shopsResponse.session_ref)
  }, [loadProducts, pageNo, shopId, shopsResponse])

  useEffect(() => {
    if (!planId || availablePlans.some((plan) => String(plan.id) === planId)) return
    setPlanId('')
    onTaskInputChange(null)
  }, [availablePlans, onTaskInputChange, planId])

  function changeShop(nextShopId: string) {
    const nextSelection = resetSelectionForShopChange(shopId, nextShopId, selectedIds)
    setShopId(nextShopId)
    setPageNo(1)
    setSelectedIds(nextSelection)
    setProductSessionRef(null)
    if (nextSelection.length === 0) setSelectedProducts({})
    if (nextSelection.length === 0) selectedProductsRef.current = {}
    setNotice(selectedIds.length > 0 && nextShopId !== shopId
      ? '店铺筛选已变化，原选择已清空，避免跨店任务输入漂移。'
      : null)
    onTaskInputChange(null)
  }

  function toggleProduct(product: DxmDraftProduct) {
    try {
      const nextIds = toggleDraftSelection(selectedIds, product.id)
      const nextProducts = nextIds.includes(product.id)
        ? mergeDraftProductSelection(selectedProductsRef.current, [product])
        : { ...selectedProductsRef.current }
      if (!nextIds.includes(product.id)) delete nextProducts[product.id]
      selectedProductsRef.current = nextProducts
      setSelectedIds(nextIds)
      setSelectedProducts(nextProducts)
      onTaskInputChange(null)
    } catch (caught) {
      invalidateReaderState('product_identity_conflict', false)
      setError(humanReaderError(caught))
    }
  }

  function toggleCurrentPage() {
    if (currentPageFullySelected) {
      const pageIds = new Set(pageSelectionIds)
      setSelectedIds((current) => current.filter((productId) => !pageIds.has(productId)))
      setSelectedProducts((current) => {
        const next = { ...current }
        pageIds.forEach((productId) => delete next[productId])
        selectedProductsRef.current = next
        return next
      })
    } else {
      try {
        const nextProducts = mergeDraftProductSelection(selectedProductsRef.current, products)
        selectedProductsRef.current = nextProducts
        setSelectedIds((current) => mergeDraftSelection(current, pageSelectionIds))
        setSelectedProducts(nextProducts)
      } catch (caught) {
        invalidateReaderState('product_identity_conflict', false)
        setError(humanReaderError(caught))
        return
      }
    }
    onTaskInputChange(null)
  }

  async function confirmTaskInput() {
    setConfirming(true)
    try {
      const freshShops = await loadShops()
      if (
        !freshShops
        || !productSessionRef
        || productSessionRef !== freshShops.session_ref
        || readerSessionRef.current !== freshShops.session_ref
      ) {
        throw new ReaderSessionChangedError()
      }
      const nextInput = buildConfirmedDraftTaskInput(
        {
          shopId,
          productIds: selectedIds,
          planId: selectedPlan?.id ?? null,
          products: selectedIds
            .map((productId) => selectedProductsRef.current[productId])
            .filter((product): product is DxmDraftProduct => Boolean(product)),
        },
        productSessionRef,
      )
      onTaskInputChange(nextInput)
      setNotice('任务输入已形成；正在进入快照预览与冻结，本步骤没有保存、发布或任何真实写入。')
      setError(null)
      confirmedHandoffRef.current = onReviewSnapshot() === true
    } catch (caught) {
      if (caught instanceof ReaderSessionChangedError) {
        invalidateReaderState('browser_session_change', false)
        setError(caught.message)
      } else {
        setError(humanReaderError(caught)
          || `至少选择 ${MIN_DRAFT_SELECTION} 件草稿商品，并选择一个本地编辑方案。`)
      }
      onTaskInputChange(null)
    } finally {
      setConfirming(false)
    }
  }

  async function refreshReader() {
    setNotice(null)
    invalidateReaderState('reader_refresh', false)
    const shops = await loadShops()
    if (!shops) return
    const availableShopIds = new Set(shops.shops.map((shop) => shop.id))
    if (shopId !== '-1' && !availableShopIds.has(shopId)) {
      changeShop('-1')
      return
    }
  }

  return (
    <section className="draft-selection-page" aria-label="采集箱草稿选品">
      <header className="draft-selection-hero">
        <div>
          <span className="draft-selection-eyebrow">E1 · 只读选品</span>
          <h1>从真实采集箱选择草稿</h1>
          <p>读取当前可见店小秘会话中的店铺与草稿列表。这里仅形成可复核任务输入，不会保存或发布。</p>
        </div>
        <div className="draft-selection-hero__actions">
          <span className={`status-pill ${shopsResponse?.source === 'api' && !error ? 'ok' : 'warn'}`}>
            {readerSourceLabel(shopsResponse, error)}
          </span>
          <button className="button button--quiet" type="button" onClick={() => { void refreshReader() }} disabled={shopsLoading || productsLoading}>
            {shopsLoading || productsLoading ? '读取中…' : '刷新'}
          </button>
        </div>
      </header>

      {error && (
        <div className="draft-selection-alert" role="alert">
          <div>
            <strong>真实草稿读取已停止</strong>
            <span>{error}</span>
          </div>
          <button className="button button--secondary" type="button" onClick={onShowDxmAccess}>检查店小秘连接</button>
        </div>
      )}
      {notice && <div className="draft-selection-notice" role="status">{notice}</div>}

      <div className="draft-selection-grid">
        <article className="module-card draft-selection-browser">
          <div className="draft-selection-toolbar">
            <label>
              <span>店铺筛选</span>
              <select value={shopId} onChange={(event) => changeShop(event.target.value)} disabled={shopsLoading}>
                <option value="-1">全部店铺</option>
                {(shopsResponse?.shops ?? []).map((shop) => (
                  <option key={shop.id} value={shop.id}>
                    {shop.name} / {shop.platform}
                  </option>
                ))}
              </select>
            </label>
            <div className="draft-selection-toolbar__summary">
              <span>草稿总数</span>
              <strong>{productsLoading ? '—' : pagination.total_items}</strong>
              <small>固定状态：draft</small>
            </div>
            <button
              className="button button--quiet"
              type="button"
              onClick={toggleCurrentPage}
              disabled={productsLoading || products.length === 0}
            >
              {currentPageFullySelected ? '取消本页' : '选择本页'}
            </button>
          </div>

          <div className="draft-selection-list" aria-busy={productsLoading}>
            {productsLoading && <div className="draft-selection-empty" role="status">正在读取真实草稿列表…</div>}
            {!productsLoading && products.map((product) => {
              const selected = selectedIds.includes(product.id)
              return (
                <label key={product.id} className={`draft-product-row ${selected ? 'is-selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleProduct(product)}
                  />
                  <span className="draft-product-row__main">
                    <strong>{product.subject || `草稿商品 ${product.id}`}</strong>
                    <small>商品 ID {product.id} · 店铺 {shopName(product.shop_id, shopsResponse)}</small>
                  </span>
                  <span className="draft-product-row__meta">
                    <b>{product.category_id ? `类目 ${product.category_id}` : '类目待解析'}</b>
                    <small>草稿</small>
                  </span>
                </label>
              )
            })}
            {!productsLoading && products.length === 0 && !error && (
              <div className="draft-selection-empty">
                <strong>当前筛选没有草稿商品</strong>
                <span>可以切换店铺或刷新；系统不会显示本地 mock/fallback 商品。</span>
              </div>
            )}
          </div>

          <footer className="draft-selection-pagination">
            <button
              className="button button--quiet"
              type="button"
              disabled={productsLoading || !pagination.has_previous}
              onClick={() => setPageNo((current) => Math.max(1, current - 1))}
            >
              上一页
            </button>
            <span>
              第 {pagination.page_no} / {Math.max(1, pagination.total_pages)} 页
            </span>
            <button
              className="button button--quiet"
              type="button"
              disabled={productsLoading || !pagination.has_next}
              onClick={() => setPageNo((current) => current + 1)}
            >
              下一页
            </button>
          </footer>
        </article>

        <aside className="module-card draft-selection-receipt">
          <div className="draft-selection-receipt__head">
            <div>
              <span>任务输入</span>
              <h2>{selectedCount} 件已选择</h2>
            </div>
            <span className={`status-pill ${selectedCount >= MIN_DRAFT_SELECTION ? 'ok' : 'warn'}`}>
              最少 {MIN_DRAFT_SELECTION} 件
            </span>
          </div>

          <div className="draft-selection-picked">
            {selectedIds.slice(0, 8).map((productId) => (
              <button
                key={productId}
                type="button"
                onClick={() => {
                  const product = selectedProducts[productId]
                  if (product) toggleProduct(product)
                }}
              >
                <span>{selectedProducts[productId]?.subject || `草稿商品 ${productId}`}</span>
                <small>{productId} · 移除</small>
              </button>
            ))}
            {selectedCount > 8 && <small>另有 {selectedCount - 8} 件已选择，ID 会全部进入任务输入。</small>}
            {selectedCount === 0 && <p>从左侧真实草稿中选择至少 {MIN_DRAFT_SELECTION} 件；选择可跨分页保留。</p>}
          </div>

          <label className="draft-selection-plan">
            <span>本地编辑方案</span>
            <select value={planId} onChange={(event) => { setPlanId(event.target.value); onTaskInputChange(null) }}>
              <option value="">选择方案</option>
              {availablePlans.map((plan) => (
                <option key={plan.id} value={plan.id}>{'name' in plan ? `${plan.name} · v${plan.version}` : plan.template_name}</option>
              ))}
            </select>
            <small>仅引用 local_plan_template；不会把 DXM 模板引用自动升级为执行方案。</small>
          </label>

          {!availablePlans.length && (
            <button className="draft-selection-plan-empty" type="button" onClick={onShowPlans}>
              暂无可用本地批量方案，前往编辑方案
            </button>
          )}

          <div className="draft-selection-contract">
            <span>待复核输入</span>
            <dl>
              <div><dt>shopId</dt><dd>{shopId}</dd></div>
              <div><dt>productIds</dt><dd>{selectedCount} 个真实 ID</dd></div>
              <div><dt>planId</dt><dd>{selectedPlan?.id ?? '待选择'}</dd></div>
            </dl>
          </div>

          <button
            className="button button--primary draft-selection-confirm"
            type="button"
            onClick={() => { void confirmTaskInput() }}
            disabled={!canReviewTask || confirming}
          >
            {confirming ? '正在重验当前账号…' : '确认任务输入（不启动）'}
          </button>

          {taskInput
            && taskInput.sessionRef === shopsResponse?.session_ref
            && taskInput.sessionRef === productSessionRef
            && (
            <div className="draft-selection-confirmed" role="status">
              <strong>任务输入已确认</strong>
              <code>{JSON.stringify(taskInput.input)}</code>
              <span>只读选品完成；下一步只预览并冻结 draft 任务，不会启动批量保存。</span>
            </div>
            )}
        </aside>
      </div>
    </section>
  )
}

function shopName(shopId: string, response: DxmDraftShopsResponse | null) {
  return response?.shops.find((shop) => shop.id === shopId)?.name ?? shopId
}

function humanReaderError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '真实草稿读取失败'
  if (/登录|会话|浏览器|店小秘/.test(message)) return message
  if (/fetch|network|failed/i.test(message)) return '本机 Reader 服务不可用；请确认后端已启动后刷新。'
  return message
}
