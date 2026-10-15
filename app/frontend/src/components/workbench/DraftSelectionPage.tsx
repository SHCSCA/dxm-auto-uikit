import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getJson, withDxmSessionBusyRetry } from '../../api'
import { categoryLabel, resolveCategorySelection } from '../../categorySelection'
import { frontendConfig } from '../../config/frontendConfig'
import { recordFrontendError } from '../../diagnostics/frontendErrors'
import { useDxmShop } from '../../dxmShopContext'
import {
  DraftProductIdentityConflictError,
  MAX_DRAFT_SELECTION,
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
} from '../../types'


type DraftSelectionPageProps = {
  localPlans: LocalPlanTemplate[]
  taskInput: ConfirmedDraftTaskInput | null
  onTaskInputChange: (taskInput: ConfirmedDraftTaskInput | null) => void
  onShowDxmAccess: () => void
  onShowPlans: () => void
  onReviewSnapshot: () => boolean
}

const PAGE_SIZES = frontendConfig.draftSelection.pageSizes
const DEFAULT_PAGE_SIZE = frontendConfig.draftSelection.defaultPageSize

const emptyPagination: DxmDraftPageResponse['pagination'] = {
  page_no: 1,
  page_size: DEFAULT_PAGE_SIZE,
  total_pages: 0,
  total_items: 0,
  has_previous: false,
  has_next: false,
}

export function DraftSelectionPage({
  localPlans: e2LocalPlans,
  taskInput,
  onTaskInputChange,
  onShowDxmAccess,
  onShowPlans,
  onReviewSnapshot,
}: DraftSelectionPageProps) {
  const {
    selectedShopId: globalShopId,
    setSelectedShopId,
    snapshot: globalShopSnapshot,
    loading: globalShopsLoading,
    error: globalShopReadError,
    refresh: refreshDxmShops,
  } = useDxmShop()
  const [shopsResponse, setShopsResponse] = useState<DxmDraftShopsResponse | null>(null)
  const [products, setProducts] = useState<DxmDraftProduct[]>([])
  const [pagination, setPagination] = useState(emptyPagination)
  const [shopId, setShopId] = useState('')
  const [pageNo, setPageNo] = useState(1)
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZES)[number]>(DEFAULT_PAGE_SIZE)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectedProducts, setSelectedProducts] = useState<Record<string, DxmDraftProduct>>({})
  const [planId, setPlanId] = useState('')
  const [productsLoading, setProductsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [productSessionRef, setProductSessionRef] = useState<string | null>(null)
  const [categoryError, setCategoryError] = useState<string | null>(null)
  const [targetCategoryId, setTargetCategoryId] = useState<string | null>(null)
  const [targetCategoryName, setTargetCategoryName] = useState<string | null>(null)
  const [targetCategoryMatch, setTargetCategoryMatch] = useState<string | null>(null)
  const [targetCategoryPath, setTargetCategoryPath] = useState('')
  const requestSequence = useRef(0)
  const readerSessionRef = useRef<string | null>(null)
  const globalShopReadErrorRef = useRef(globalShopReadError)
  globalShopReadErrorRef.current = globalShopReadError
  const selectedProductsRef = useRef<Record<string, DxmDraftProduct>>({})
  const confirmedHandoffRef = useRef(false)
  const confirmationTokenRef = useRef(0)
  const shopsLoading = globalShopsLoading

  const availablePlans = useMemo(
    () => e2LocalPlans.filter((plan) => plan.is_active && plan.path === 'B' && plan.shop_id === shopId),
    [e2LocalPlans, shopId],
  )
  const selectedPlanId = Number(planId)
  const selectedPlan = availablePlans.find((plan) => plan.id === selectedPlanId) ?? null
  const selectedCount = selectedIds.length
  const pageSelectionIds = products.map((product) => product.id)
  const currentPageFullySelected = pageSelectionIds.length > 0
    && pageSelectionIds.every((productId) => selectedIds.includes(productId))
  const selectionCountIsWithinBatchLimit = selectedCount >= MIN_DRAFT_SELECTION
    && selectedCount <= MAX_DRAFT_SELECTION
  const canReviewTask = selectionCountIsWithinBatchLimit
    && selectedPlan !== null
    && targetCategoryId !== null
    && categoryError === null
    && productSessionRef !== null
    && productSessionRef === shopsResponse?.session_ref
    && error === null

  useEffect(() => {
    let cancelled = false
    setTargetCategoryId(null)
    setTargetCategoryName(null)
    setTargetCategoryMatch(null)
    setTargetCategoryPath('')
    setCategoryError(null)
    onTaskInputChange(null)
    const categoryId = selectedPlan?.category_ids.length === 1 ? selectedPlan.category_ids[0] : null
    if (!categoryId || !productSessionRef) return () => { cancelled = true }
    void resolveCategorySelection(categoryId, (id) => withDxmSessionBusyRetry(
      () => getJson(`/api/dxm/category/get?category_id=${encodeURIComponent(id)}`),
    )).then((chain) => {
      if (cancelled) return
      const record = chain[chain.length - 1]
      setTargetCategoryId(record.categoryId)
      setTargetCategoryName(categoryLabel(record))
      setTargetCategoryMatch(record.nameEn || record.nameZh || null)
      setTargetCategoryPath(chain.map(categoryLabel).join(' / '))
    }).catch((caught) => {
      recordFrontendError(caught, { component: 'draft_selection', action: 'verify_plan_category' })
      if (!cancelled) setCategoryError('方案目标类目无法由当前目录核实；请回到普货方案重新选择真实末级类目。')
    })
    return () => { cancelled = true }
  }, [onTaskInputChange, productSessionRef, selectedPlan?.id, selectedPlan?.version, selectedPlan?.category_ids.join(',')])

  const invalidateReaderState = useCallback((
    reason: DraftSelectionInvalidationReason,
    clearShops: boolean,
  ) => {
    const invalidated = invalidateDraftSelectionState(reason)
    requestSequence.current += 1
    confirmedHandoffRef.current = false
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

  const loadShops = useCallback(async (force = false) => {
    try {
      const rawResponse = await refreshDxmShops(force)
      if (!rawResponse) {
        throw new Error(globalShopReadErrorRef.current || '店铺列表读取失败，请稍后重试。')
      }
      const response = assertRealDraftShopsResponse(rawResponse)
      const sessionChanged = readerSessionRef.current !== null
        && readerSessionRef.current !== response.session_ref
      if (sessionChanged) {
        invalidateReaderState('browser_session_change', false)
      }
      readerSessionRef.current = response.session_ref
      setShopsResponse(response)
      const availableShopIds = new Set(response.shops.map((shop) => shop.id))
      const preferredShopId = globalShopId && availableShopIds.has(globalShopId)
        ? globalShopId
        : response.shops[0]?.id ?? ''
      if (preferredShopId) {
        setShopId((current) => current && availableShopIds.has(current) ? current : preferredShopId)
        if (globalShopId !== preferredShopId) setSelectedShopId(preferredShopId)
      }
      if (sessionChanged) {
        // A new reader session invalidates every prior product identity and
        // draft handoff.  Surface it as a blocking state even if the list can
        // be reloaded successfully afterwards; otherwise a stale confirmation
        // could look successful during the re-render window.
        setError('真实浏览器会话已变化，原选择已清空；请重新读取并确认任务输入。')
        setNotice('真实浏览器会话已变化，原选择已清空，避免跨会话任务输入漂移。')
      } else {
        // An automatic provider re-render after a changed session must not
        // erase the fail-closed notice.  A deliberate operator refresh is
        // allowed to clear it only after the fresh read succeeds.
        setError((current) => force || !current?.includes('会话已变化') ? null : current)
      }
      return response
    } catch (caught) {
      invalidateReaderState('reader_failure', true)
      setError(humanReaderError(caught))
      return null
    }
  }, [globalShopId, invalidateReaderState, refreshDxmShops, setSelectedShopId])

  const loadProducts = useCallback(async (
    nextShopId: string,
    nextPageNo: number,
    expectedSessionRef: string,
  ) => {
    if (!nextShopId) {
      setProducts([])
      setPagination(emptyPagination)
      setProductsLoading(false)
      return
    }
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setProductsLoading(true)
    try {
      const params = new URLSearchParams({
        shop_id: nextShopId,
        page_no: String(nextPageNo),
        page_size: String(pageSize),
      })
      const rawResponse = await withDxmSessionBusyRetry(
        () => getJson<unknown>(
          `/api/dxm/draft-reader/products?${params.toString()}`,
        ),
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
  }, [invalidateReaderState, loadShops, pageSize])

  useEffect(() => {
    const invalidated = invalidateDraftSelectionState('page_remount')
    onTaskInputChange(invalidated.confirmedInput)
    return () => {
      requestSequence.current += 1
        confirmationTokenRef.current += 1
      if (!confirmedHandoffRef.current) {
        // React may defer a parent update issued while the child is being
        // removed.  Apply it once immediately and once after the commit so a
        // stale task input cannot survive a page unmount.
        onTaskInputChange(invalidated.confirmedInput)
        queueMicrotask(() => {
          if (!confirmedHandoffRef.current) onTaskInputChange(null)
        })
      }
    }
  }, [onTaskInputChange])

  useEffect(() => {
    if (globalShopSnapshot) {
      void loadShops()
      return
    }
    // First entry after a desktop restart has no cached shop snapshot.  Read
    // it once here; subsequent pages reuse the provider result.
    void loadShops()
  }, [globalShopSnapshot, loadShops])

  useEffect(() => {
    if (!shopsResponse) return
    const availableShopIds = new Set(shopsResponse.shops.map((shop) => shop.id))
    const nextShopId = globalShopId && availableShopIds.has(globalShopId)
      ? globalShopId
      : shopsResponse.shops[0]?.id ?? ''
    if (nextShopId && nextShopId !== shopId) changeShop(nextShopId)
  }, [globalShopId, shopId, shopsResponse])

  useEffect(() => {
    if (!shopsResponse) {
      setProductsLoading(false)
      return
    }
    void loadProducts(shopId, pageNo, shopsResponse.session_ref)
  }, [loadProducts, pageNo, pageSize, shopId, shopsResponse])

  useEffect(() => {
    if (!planId || availablePlans.some((plan) => String(plan.id) === planId)) return
    setPlanId('')
    onTaskInputChange(null)
  }, [availablePlans, onTaskInputChange, planId])

  function changeShop(nextShopId: string) {
    if (!nextShopId) return
    const nextSelection = resetSelectionForShopChange(shopId, nextShopId, selectedIds)
    setShopId(nextShopId)
    setSelectedShopId(nextShopId)
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
    const confirmationToken = confirmationTokenRef.current + 1
    confirmationTokenRef.current = confirmationToken
    setConfirming(true)
    // A page can be reused after a Reader refresh.  Treat every new
    // confirmation as a fresh handoff decision; never inherit a previous
    // auto-advance marker into the next unmount lifecycle.
    confirmedHandoffRef.current = false
    try {
      const expectedReaderSessionRef = readerSessionRef.current
      // Confirming an input is a security boundary: it must re-read the
      // live reader session rather than reuse the page's display snapshot.
      const freshShops = await loadShops(true)
      if (confirmationToken !== confirmationTokenRef.current) return
      if (
        !freshShops
        || !expectedReaderSessionRef
        || freshShops.session_ref !== expectedReaderSessionRef
        || !productSessionRef
        || productSessionRef !== freshShops.session_ref
        || readerSessionRef.current !== freshShops.session_ref
      ) {
        throw new ReaderSessionChangedError()
      }
      if (!selectedPlan || selectedPlan.path !== 'B' || !targetCategoryId) throw new Error('请选择完整 Path B 方案和已核实的末级类目。')
      await resolveCategorySelection(targetCategoryId, (id) => withDxmSessionBusyRetry(
        () => getJson(`/api/dxm/category/get?category_id=${encodeURIComponent(id)}`),
      ))
      const nextInput = buildConfirmedDraftTaskInput(
        {
          shopId,
          productIds: selectedIds,
          planId: selectedPlan?.id ?? null,
          targetCategoryId,
          targetCategoryName,
          targetCategoryMatch,
          products: selectedIds
            .map((productId) => selectedProductsRef.current[productId])
            .filter((product): product is DxmDraftProduct => Boolean(product)),
        },
        productSessionRef,
      )
      if (confirmationToken !== confirmationTokenRef.current) return
      onTaskInputChange(nextInput)
      setNotice('任务输入已形成；正在进入快照预览与冻结，本步骤没有保存、发布或任何真实写入。')
      setError(null)
      confirmedHandoffRef.current = onReviewSnapshot() === true
    } catch (caught) {
      recordFrontendError(caught, { component: 'draft_selection', action: 'confirm_input' })
      if (caught instanceof ReaderSessionChangedError) {
        invalidateReaderState('browser_session_change', false)
        setError(caught.message)
      } else {
        setError(humanReaderError(caught)
          || `请选择 ${MIN_DRAFT_SELECTION}–${MAX_DRAFT_SELECTION} 件草稿商品，并选择一个本地编辑方案。`)
      }
      onTaskInputChange(null)
    } finally {
      if (confirmationToken === confirmationTokenRef.current) setConfirming(false)
    }
  }

  async function refreshReader() {
    setNotice(null)
    setCategoryError(null)
    invalidateReaderState('reader_refresh', false)
    const shops = await loadShops(true)
    if (!shops) return
    const availableShopIds = new Set(shops.shops.map((shop) => shop.id))
    if (!shopId || !availableShopIds.has(shopId)) {
      const nextShopId = shops.shops[0]?.id ?? ''
      if (nextShopId) changeShop(nextShopId)
      return
    }
  }

  return (
    <section className="draft-selection-page" aria-label="采集箱草稿选品">
      {/* PublishGuard Banner - Permanent Warning */}
      <div className="publishguard-banner publishguard-banner--draft" role="alert">
        <strong>⚠ 本系统仅支持草稿保存，禁止任何发布操作</strong>
        <p>最终发布永久禁止：立即发布、保存并发布、上线等按钮均已永久禁用。</p>
      </div>

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
          <button className="button button--secondary" type="button" onClick={() => { void refreshReader() }} disabled={shopsLoading || productsLoading}>
            重新读取草稿
          </button>
          <button className="button button--secondary" type="button" onClick={onShowDxmAccess}>检查店小秘连接</button>
        </div>
      )}
      {notice && <div className="draft-selection-notice" role="status">{notice}</div>}

      <div className="draft-selection-grid">
        <article className="module-card draft-selection-browser">
          <div className="draft-selection-toolbar">
            <label>
              <span>店铺筛选</span>
              <select value={shopId} onChange={(event) => changeShop(event.target.value)} disabled={shopsLoading || !shopId}>
                {!shopId && <option value="">请先选择店铺</option>}
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
              const shopLabel = shopName(product.shop_id, shopsResponse)
              return (
                <label key={product.id} className={`draft-product-row ${selected ? 'is-selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleProduct(product)}
                  />
                  {product.thumbnail_url
                    ? <img className="draft-product-row__thumb" src={product.thumbnail_url} alt="" />
                    : <span className="draft-product-row__thumb is-empty" aria-hidden="true" />}
                  <span className="draft-product-row__main">
                    <strong>{product.subject || `草稿商品 ${product.id}`}</strong>
                    {product.remark && <em className="draft-product-row__remark">备注：{product.remark}</em>}
                    <small>「{shopLabel}」{product.source_platform ? ` · ${product.source_platform}` : ''}</small>
                    <small className="draft-product-row__category">
                      类目：{product.category_name || `类目 ${product.category_id ?? '未知'}`}
                      {product.category_name && product.category_id ? ` · 类目编号 ${product.category_id}` : ''}
                    </small>
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
            <span>{paginationSummary(pagination)}</span>
            <div className="draft-selection-pagination__nav">
              <button
                className="button button--quiet"
                type="button"
                disabled={productsLoading || !pagination.has_previous}
                onClick={() => setPageNo((current) => Math.max(1, current - 1))}
              >
                上一页
              </button>
              <button
                className="button button--quiet"
                type="button"
                disabled={productsLoading || !pagination.has_next}
                onClick={() => setPageNo((current) => current + 1)}
              >
                下一页
              </button>
              <label>
                <span className="sr-only">每页条数</span>
                <select
                  value={pageSize}
                  disabled={productsLoading}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value) as (typeof PAGE_SIZES)[number])
                    setPageNo(1)
                  }}
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>{size}条/页</option>
                  ))}
                </select>
              </label>
            </div>
          </footer>
        </article>

        <aside className="module-card draft-selection-receipt">
          <div className="draft-selection-receipt__head">
            <div>
              <span>任务输入</span>
              <h2>{selectedCount} 件已选择</h2>
            </div>
            <span className={`status-pill ${selectionCountIsWithinBatchLimit ? 'ok' : 'warn'}`}>
              范围 {MIN_DRAFT_SELECTION}–{MAX_DRAFT_SELECTION} 件
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
            {selectedCount === 0 && <p>从左侧真实草稿中选择 {MIN_DRAFT_SELECTION}–{MAX_DRAFT_SELECTION} 件；选择可跨分页保留。</p>}
            {selectedCount > MAX_DRAFT_SELECTION && <p>本次最多可确认 {MAX_DRAFT_SELECTION} 件，请移除多余商品后继续。</p>}
          </div>

          <label className="draft-selection-plan">
            <span>本地编辑方案</span>
            <select value={planId} onChange={(event) => { setPlanId(event.target.value); onTaskInputChange(null) }}>
              <option value="">选择方案</option>
              {availablePlans.map((plan) => (
                <option key={plan.id} value={plan.id}>{plan.name} · v{plan.version}</option>
              ))}
            </select>
            <small>仅引用本地普货方案；店小秘模板只用于配置参考，不会被自动升级为执行方案。</small>
          </label>

          {!availablePlans.length && (
            <button className="draft-selection-plan-empty" type="button" onClick={onShowPlans}>
              暂无可用本地批量方案，前往编辑方案
            </button>
          )}

          <div className="draft-selection-target">
            <span>方案目标末级类目</span>
            <div className="draft-selection-target__plan-owned">
              <strong>{targetCategoryPath || targetCategoryName || '等待当前目录核实'}</strong>
              <small>由完整 Path B 方案固定；核实真实叶子和祖先链后才可预览快照。更换目标请返回普货方案。</small>
            </div>
            {categoryError && <div className="draft-selection-alert" role="alert">{categoryError}</div>}
          </div>

          <div className="draft-selection-contract">
            <div className="draft-selection-contract__intro">
              <span>待复核输入</span>
              <small>这三项决定本次批量保存的店铺、商品范围和普货方案；确认后会进入快照校验，不会立即保存。</small>
            </div>
            <dl>
              <div>
                <dt>店铺</dt>
                <dd>{shopId ? `${shopName(shopId, shopsResponse)}（编号 ${shopId}）` : '未选择店铺'}</dd>
              </div>
              <div>
                <dt>商品范围</dt>
                <dd>{selectedCount ? `${selectedCount} 件真实草稿` : '未选择商品'}</dd>
              </div>
              <div>
                <dt>普货方案</dt>
                <dd>{selectedPlan ? planLabel(selectedPlan) : '未选择方案'}</dd>
              </div>
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
              <span>
                店铺：{shopName(taskInput.input.shopId, shopsResponse)} · 商品：{taskInput.input.productIds.length} 件 · 普货方案：{selectedPlan ? planLabel(selectedPlan) : `方案编号 ${taskInput.input.planId}`}
              </span>
              <details>
                <summary>查看内部绑定（排查用）</summary>
                <code>{JSON.stringify(taskInput.input)}</code>
              </details>
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

function paginationSummary(pagination: DxmDraftPageResponse['pagination']) {
  if (pagination.total_items <= 0) return '共 0 条'
  const from = (pagination.page_no - 1) * pagination.page_size + 1
  const to = Math.min(pagination.page_no * pagination.page_size, pagination.total_items)
  return `第 ${from}–${to} 条，共 ${pagination.total_items} 条`
}

function planLabel(plan: LocalPlanTemplate) {
  return `${plan.name}（版本 ${plan.version}）`
}

function humanReaderError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '真实草稿读取失败'
  if (/at least \d+|at most \d+/i.test(message)) {
    return `请选择 ${MIN_DRAFT_SELECTION}–${MAX_DRAFT_SELECTION} 件真实草稿商品。`
  }
  if (/登录|会话|浏览器|店小秘/.test(message)) return message
  if (/fetch|network|failed/i.test(message)) return '本机 Reader 服务不可用；请确认后端已启动后刷新。'
  return message
}
