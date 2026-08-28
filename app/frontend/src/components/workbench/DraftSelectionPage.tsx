import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getJson, withDxmSessionBusyRetry } from '../../api'
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
  DxmCategoryRecord,
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

const PAGE_SIZES = [20, 50, 100, 200] as const
const DEFAULT_PAGE_SIZE = 100

const emptyPagination: DxmDraftPageResponse['pagination'] = {
  page_no: 1,
  page_size: DEFAULT_PAGE_SIZE,
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
  const [categoryLevels, setCategoryLevels] = useState<DxmCategoryRecord[][]>([[], [], []])
  const [categorySelection, setCategorySelection] = useState<(DxmCategoryRecord | null)[]>([null, null, null])
  const [categoryLoading, setCategoryLoading] = useState(false)
  const [categoryError, setCategoryError] = useState<string | null>(null)
  const [categorySearch, setCategorySearch] = useState('')
  const [categorySearchResults, setCategorySearchResults] = useState<DxmCategoryRecord[]>([])
  const [targetCategoryId, setTargetCategoryId] = useState<string | null>(null)
  const [targetCategoryName, setTargetCategoryName] = useState<string | null>(null)
  const [targetCategoryMatch, setTargetCategoryMatch] = useState<string | null>(null)
  const [targetCategoryPath, setTargetCategoryPath] = useState('')
  const requestSequence = useRef(0)
  // Product pages and the optional category cascade are independent read
  // channels.  A slow/failed category request must never make a valid draft
  // page look stale (and vice versa).
  const categoryRequestSequence = useRef(0)
  const readerSessionRef = useRef<string | null>(null)
  const selectedProductsRef = useRef<Record<string, DxmDraftProduct>>({})
  const confirmedHandoffRef = useRef(false)
  const confirmationTokenRef = useRef(0)
  const categoryRootSessionRef = useRef<string | null>(null)
  const shopsLoading = globalShopsLoading

  const availablePlans = useMemo(
    () => e2LocalPlans?.filter((plan) => plan.is_active)
      ?? plans.filter((plan) => plan.is_enabled && plan.template_type === 'edit_batch_bundle'),
    [e2LocalPlans, plans],
  )
  const selectedPlanId = Number(planId)
  const selectedPlan = availablePlans.find((plan) => plan.id === selectedPlanId) ?? null
  const planOwnsTargetCategory = selectedPlan !== null
    && 'scope_contract' in selectedPlan
    && selectedPlan.scope_contract === 'single_target_category.v2'
  const selectedCount = selectedIds.length
  const pageSelectionIds = products.map((product) => product.id)
  const currentPageFullySelected = pageSelectionIds.length > 0
    && pageSelectionIds.every((productId) => selectedIds.includes(productId))
  const selectionCountIsWithinBatchLimit = selectedCount >= MIN_DRAFT_SELECTION
    && selectedCount <= MAX_DRAFT_SELECTION
  const canReviewTask = selectionCountIsWithinBatchLimit
    && selectedPlan !== null
    && (!planOwnsTargetCategory || targetCategoryId !== null)
    && productSessionRef !== null
    && productSessionRef === shopsResponse?.session_ref
    && error === null

  useEffect(() => {
    if (!planOwnsTargetCategory || !selectedPlan || !('category_ids' in selectedPlan)) return
    const categoryId = selectedPlan.category_ids[0]
    if (!categoryId) return
    let cancelled = false
    setTargetCategoryId(categoryId)
    setTargetCategoryName(null)
    setTargetCategoryMatch(null)
    setTargetCategoryPath('')
    void withDxmSessionBusyRetry(
      () => getJson<DxmCategoryRecord | null>(`/api/dxm/category/get?category_id=${encodeURIComponent(categoryId)}`),
    ).then((record) => {
      if (cancelled || !record) return
      setTargetCategoryName(categoryLabel(record))
      setTargetCategoryMatch(record.nameEn || record.nameZh || null)
      setTargetCategoryPath(categoryPathLabel(record))
      setCategorySelection([null, null, record])
    }).catch(() => {
      if (!cancelled) setTargetCategoryName(`类目 ${categoryId}`)
    })
    return () => { cancelled = true }
  }, [planOwnsTargetCategory, selectedPlan])

  const invalidateReaderState = useCallback((
    reason: DraftSelectionInvalidationReason,
    clearShops: boolean,
  ) => {
    const invalidated = invalidateDraftSelectionState(reason)
    requestSequence.current += 1
    categoryRequestSequence.current += 1
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
        throw new Error(globalShopReadError || '店铺列表读取失败，请稍后重试。')
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
  }, [globalShopId, globalShopReadError, invalidateReaderState, refreshDxmShops, setSelectedShopId])

  const loadCategoryChildren = useCallback(async (level: number, pcid: string) => {
    const sequence = categoryRequestSequence.current + 1
    categoryRequestSequence.current = sequence
    setCategoryLoading(true)
    try {
      const params = new URLSearchParams(pcid ? { pcid } : {})
      const records = await withDxmSessionBusyRetry(
        () => getJson<DxmCategoryRecord[]>(
          `/api/dxm/category/children?${params.toString()}`,
        ),
      )
      if (sequence !== categoryRequestSequence.current) return
      setCategoryLevels((current) => {
        const next = [...current]
        // DXM may return an empty root/child page while search already gave us
        // a verified full path.  Keep that path as the cascade source instead
        // of turning the next selector back into a disabled empty control.
        next[level] = records.length || !next[level].length ? records : next[level]
        return next
      })
      setCategoryError(null)
      setCategoryLoading(false)
    } catch (caught) {
      if (sequence !== categoryRequestSequence.current) return
      setCategoryLevels((current) => {
        // Keep a search-derived path when the optional children request is
        // unavailable; otherwise the operator would lose the just-selected
        // category and the cascade would fall back to search-only again.
        return current
      })
      setCategoryLoading(false)
      setCategoryError(humanCategoryError(caught))
    }
  }, [])

  const adoptTargetCategory = useCallback((
    record: DxmCategoryRecord,
    drillIntoChildren: boolean,
    level?: number,
  ) => {
    const name = categoryLabel(record)
    const path = categoryPathLabel(record)
    // A first- or second-level click only opens the next selector.  It must
    // never accidentally become the batch target category.  The third level
    // (or a provider-declared leaf selected from search) is the only value
    // eligible for the subsequent frozen snapshot.
    const isFinalCategory = level === 2 || isLeafCategory(record)
    setTargetCategoryId(isFinalCategory ? record.categoryId : null)
    setTargetCategoryName(isFinalCategory ? (name || null) : null)
    // Keep the English name as the execution hint while the visible label is
    // always Chinese-first.  The frozen backend mapping still owns the final
    // value written into DXM.
    setTargetCategoryMatch(isFinalCategory ? (record.nameEn || record.nameZh || null) : null)
    setTargetCategoryPath(isFinalCategory ? path : '')
    setCategorySelection((current) => {
      const next = [...current]
      if (level !== undefined) {
        next[level] = record
        for (let i = level + 1; i < next.length; i += 1) next[i] = null
      }
      return next
    })
    if (drillIntoChildren && level !== undefined && level + 1 < 3) {
      void loadCategoryChildren(level + 1, record.categoryId)
    }
    setCategorySearchResults([])
    onTaskInputChange(null)
    setNotice('已设置统一目标类目；整批商品将统一切换到该类目，快照预检会按目标类目必填字段把关。')
    setCategoryError(null)
  }, [loadCategoryChildren, onTaskInputChange])

  const pickCategory = useCallback((level: number, record: DxmCategoryRecord) => {
    adoptTargetCategory(record, true, level)
  }, [adoptTargetCategory])

  async function searchCategories() {
    const keyword = categorySearch.trim()
    if (!keyword) return
    setCategoryLoading(true)
    try {
      const params = new URLSearchParams({ keyword })
      const records = await withDxmSessionBusyRetry(
        () => getJson<DxmCategoryRecord[]>(
          `/api/dxm/category/search?${params.toString()}`,
        ),
      )
      setCategorySearchResults(records)
      // Some DXM sessions return an empty root list even though category search
      // returns full paths.  Use those paths as a read-only cascade fallback so
      // the operator is not forced to use search-only selection.
      setCategoryLevels((current) => mergeCategorySearchLevels(current, records))
      setCategoryLoading(false)
      setCategoryError(null)
    } catch (caught) {
      setCategorySearchResults([])
      setCategoryLoading(false)
      setCategoryError(humanCategoryError(caught))
    }
  }

  const targetCategoryLabel = categorySelection
    .filter((record): record is DxmCategoryRecord => record !== null)
    .map((record) => record.nameZh || record.nameEn || '')
    .filter(Boolean)
    .join('/')

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
      categoryRequestSequence.current += 1
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
    // The reader owns one visible browser session.  Load root categories only
    // after the first concrete shop/product read completes so both requests
    // cannot race and turn a valid cascade into a misleading 409 failure.
    if (
      !shopsResponse
      || productsLoading
      || categoryLoading
      || categoryLevels[0].length
      || categoryRootSessionRef.current === shopsResponse.session_ref
    ) return
    categoryRootSessionRef.current = shopsResponse.session_ref
    void loadCategoryChildren(0, '')
  }, [categoryLevels, categoryLoading, loadCategoryChildren, productsLoading, shopsResponse])

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
    categoryRootSessionRef.current = null
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
                <option key={plan.id} value={plan.id}>{'name' in plan ? `${plan.name} · v${plan.version}` : plan.template_name}</option>
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
            <span>{planOwnsTargetCategory ? '方案目标类目' : '统一目标类目（旧方案兼容）'}</span>
            {planOwnsTargetCategory ? (
              <div className="draft-selection-target__plan-owned">
                <strong>{targetCategoryPath || targetCategoryName || `类目 ${targetCategoryId ?? ''}`}</strong>
                <small>由普货方案固定；本次选择的全部商品都会切换到这个类目。如需更换，请编辑或新建方案。</small>
              </div>
            ) : <>
            <div className="draft-selection-target__cascade" aria-label="统一目标类目三级联动">
              {[0, 1, 2].map((level) => (
                <select
                  key={level}
                  value={categorySelection[level]?.categoryId ?? ''}
                  disabled={categoryLoading || (level > 0 && !categorySelection[level - 1])}
                  onChange={(event) => {
                    const record = categoryLevels[level]
                      .find((item) => item.categoryId === event.target.value)
                    if (record) pickCategory(level, record)
                  }}
                >
                  <option value="">{level === 0 ? '一级类目' : `${level + 1} 级类目`}</option>
                  {categoryLevels[level].map((record) => (
                    <option key={record.categoryId} value={record.categoryId}>
                      {categoryLabel(record)}
                    </option>
                  ))}
                </select>
              ))}
            </div>
            <div className="draft-selection-target__search">
              <input
                value={categorySearch}
                onChange={(event) => setCategorySearch(event.target.value)}
                placeholder="按名称搜索类目，如 立牌"
                disabled={categoryLoading}
              />
              <button
                className="button button--quiet"
                type="button"
                disabled={categoryLoading || !categorySearch.trim()}
                onClick={() => { void searchCategories() }}
              >
                搜索
              </button>
            </div>
            <small className="draft-selection-target__cascade-status">
              {categoryLoading
                ? '正在读取店小秘类目树，请等待当前层完成。'
                : categorySelection[1]
                  ? '已选择二级类目，请继续选择三级类目；只有末级类目会作为统一目标。'
                  : categorySelection[0]
                    ? '已选择一级类目，请继续选择二级类目。'
                    : '先从一级类目开始逐层选择；搜索仅用于快速定位和补充。'}
            </small>
            <small>搜索结果会自动补全可选的三级路径；它是快速定位方式，不替代逐级选择。</small>
            {!categoryLevels[0].length && !categoryLoading && (
              <small className="draft-selection-target__hint">
                一级类目暂未读取到。可重新读取三级联动，或搜索类目作为补充；搜索不是唯一选择方式。
              </small>
            )}
            {categoryError && (
              <div className="draft-selection-target__error" role="status" aria-live="polite">
                <span>{categoryError}</span>
                <button
                  className="button button--quiet"
                  type="button"
                  disabled={categoryLoading}
                  onClick={() => {
                    categoryRootSessionRef.current = null
                    setCategoryLevels([[], [], []])
                    setCategorySelection([null, null, null])
                    void loadCategoryChildren(0, '')
                  }}
                >
                  重新读取类目
                </button>
              </div>
            )}
            {categorySearchResults.length > 0 && (
              <ul className="draft-selection-target__results">
                {categorySearchResults.map((record) => (
                  <li key={record.categoryId}>
                    <button
                      type="button"
                      onClick={() => adoptTargetCategory(record, false)}
                    >
                      <span>{categoryLabel(record)}</span>
                      <small>{categoryPathLabel(record)} · 类目编号 {record.categoryId}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {targetCategoryId && (
              <small className="draft-selection-target__picked">
                整批将统一切换到：{targetCategoryPath || targetCategoryLabel}
                （类目编号 {targetCategoryId}）
              </small>
            )}
            <small>旧方案不选择时沿用商品当前类目；选择后快照预检按目标类目必填字段把关。</small>
            </>}
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

function categoryLabel(record: DxmCategoryRecord) {
  if (record.nameZh) return displayCategoryName(record.nameZh)
  if (record.nameEn) return `未提供中文名称（${record.nameEn}）`
  return `类目 ${record.categoryId}`
}

function planLabel(plan: Template | LocalPlanTemplate) {
  return 'name' in plan
    ? `${plan.name}（版本 ${plan.version}）`
    : `${plan.template_name}（已启用）`
}

function categoryPathLabel(record: DxmCategoryRecord) {
  const rawPath = record.nodePath || categoryLabel(record)
  return rawPath
    .split(/\s*(?:>|\/)\s*/)
    .map((segment) => displayCategoryName(segment))
    .filter(Boolean)
    .join(' / ')
}

function displayCategoryName(value: string) {
  const normalized = value.trim()
  const chinese = normalized.match(/[\u3400-\u9fff][\u3400-\u9fff\s·（）()\-]*/)?.[0]?.trim()
  if (chinese) return chinese.replace(/[()（）]/g, '').trim()
  return normalized
}

function isLeafCategory(record: DxmCategoryRecord) {
  return record.isleaf === 1 || record.isleaf === '1' || record.isleaf === true
}

function mergeCategorySearchLevels(
  current: DxmCategoryRecord[][],
  records: DxmCategoryRecord[],
) {
  const next = current.map((level) => [...level])
  for (const result of records) {
    const ids = (result.nodePathId || '').split('/').map((value) => value.trim()).filter(Boolean)
    const names = (result.nodePath || '').split(/\s*(?:>|\/)\s*/).map((value) => value.trim()).filter(Boolean)
    const leafId = result.categoryId
    if (!ids.length || ids[ids.length - 1] !== leafId) ids.push(leafId)
    if (!names.length) names.push(categoryLabel(result))
    const offset = Math.max(0, 3 - ids.length)
    ids.slice(-3).forEach((id, index) => {
      const sourceIndex = names.length - ids.slice(-3).length + index
      const name = names[sourceIndex] || (index === ids.slice(-3).length - 1 ? categoryLabel(result) : `类目 ${id}`)
      const level = offset + index
      if (level > 2) return
      const existing = next[level].find((item) => item.categoryId === id)
      const record: DxmCategoryRecord = {
        categoryId: id,
        nameZh: displayCategoryName(name),
        nameEn: index === ids.slice(-3).length - 1 ? result.nameEn : undefined,
        nodePath: names.slice(Math.max(0, sourceIndex - index), sourceIndex + 1).join(' / '),
        nodePathId: ids.slice(0, index + 1).join('/'),
        pcid: index > 0 ? ids[index - 1] : undefined,
        isleaf: index === ids.slice(-3).length - 1 ? result.isleaf : false,
        level: level + 1,
      }
      if (!existing) next[level].push(record)
    })
  }
  return next
}

function humanCategoryError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '类目读取失败'
  if (/登录|会话|浏览器|店小秘/.test(message)) return message
  if (/fetch|network|failed/i.test(message)) return '本机 Reader 服务不可用；类目联动不可用，请确认后端已启动后重试。'
  if (/409|忙/.test(message)) return '类目服务当前忙；稍后重试。'
  return `类目读取失败：${message}`
}

function humanReaderError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '真实草稿读取失败'
  if (/at least 1|at most 100/i.test(message)) {
    return `请选择 ${MIN_DRAFT_SELECTION}–${MAX_DRAFT_SELECTION} 件真实草稿商品。`
  }
  if (/登录|会话|浏览器|店小秘/.test(message)) return message
  if (/fetch|network|failed/i.test(message)) return '本机 Reader 服务不可用；请确认后端已启动后刷新。'
  return message
}
