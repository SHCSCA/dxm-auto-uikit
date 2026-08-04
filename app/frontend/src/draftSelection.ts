import type {
  DxmDraftPageResponse,
  DxmDraftProduct,
  DxmDraftShopsResponse,
} from './types'

export const MIN_DRAFT_SELECTION = 3

export type DraftTaskInput = {
  shopId: string
  productIds: string[]
  planId: number
  items?: DraftTaskProduct[]
}

export type DraftTaskProduct = {
  productId: string
  shopId: string
  categoryId: string | null
  title: string
}

export type ConfirmedDraftTaskInput = {
  sessionRef: string
  input: DraftTaskInput
}

export type DraftSelectionInvalidationReason =
  | 'reader_failure'
  | 'page_remount'
  | 'browser_session_change'
  | 'product_identity_conflict'
  | 'reader_refresh'

type DraftTaskInputCandidate = {
  shopId: string
  productIds: string[]
  planId: number | null
  products?: DxmDraftProduct[]
}

export class ReaderSessionChangedError extends Error {
  constructor() {
    super('真实浏览器会话已变化，当前商品回包已拒绝。')
    this.name = 'ReaderSessionChangedError'
  }
}

export class DraftProductIdentityConflictError extends Error {
  constructor(productId: string) {
    super(`商品 ${productId} 在不同分页返回了冲突身份，已停止确认。`)
    this.name = 'DraftProductIdentityConflictError'
  }
}

export function assertRealDraftShopsResponse(
  value: unknown,
): DxmDraftShopsResponse {
  if (
    !isRecord(value)
    || value.source !== 'api'
    || value.session_bound !== true
    || !isNonEmptyString(value.session_ref)
    || !Array.isArray(value.shops)
  ) {
    throw new Error('店铺列表没有真实 API 与当前会话标识')
  }
  return value as DxmDraftShopsResponse
}

export function assertRealDraftPageResponse(
  value: unknown,
  expected: { shopId: string; sessionRef: string },
): DxmDraftPageResponse {
  if (
    !isRecord(value)
    || value.source !== 'api'
    || value.session_bound !== true
    || !isNonEmptyString(value.session_ref)
  ) {
    throw new Error('草稿列表没有真实 API 与当前会话标识')
  }
  if (value.session_ref !== expected.sessionRef) {
    throw new ReaderSessionChangedError()
  }
  if (
    !isRecord(value.filter)
    || value.filter.dxm_state !== 'draft'
    || value.filter.shop_id !== expected.shopId
    || !isRecord(value.pagination)
    || !Array.isArray(value.items)
    || typeof value.deduplicated_count !== 'number'
  ) {
    throw new Error('草稿列表来源、会话或筛选回显不一致')
  }
  return value as DxmDraftPageResponse
}

export function invalidateDraftSelectionState(
  reason: DraftSelectionInvalidationReason,
) {
  return {
    sessionRef: null,
    selectedIds: [] as string[],
    selectedProducts: {},
    confirmedInput: null,
    invalidatedBy: reason,
  }
}

export function readerSourceLabel(
  response: DxmDraftShopsResponse | null,
  error: string | null,
) {
  if (error) return '真实 Reader 读取失败 · 状态已失效'
  return response?.source === 'api' ? '实时 API · 当前会话' : '等待真实 API'
}

export function mergeDraftSelection(current: string[], incoming: string[]) {
  const selected = new Set<string>()
  for (const productId of [...current, ...incoming]) {
    selected.add(canonicalProductId(productId))
  }
  return [...selected]
}

export function mergeDraftProductSelection(
  current: Record<string, DxmDraftProduct>,
  incoming: DxmDraftProduct[],
) {
  const merged = { ...current }
  for (const product of incoming) {
    const existing = merged[product.id]
    if (existing && !sameDraftProductIdentity(existing, product)) {
      throw new DraftProductIdentityConflictError(product.id)
    }
    merged[product.id] = product
  }
  return merged
}

export function toggleDraftSelection(current: string[], productId: string) {
  const normalizedId = canonicalProductId(productId)
  return current.includes(normalizedId)
    ? current.filter((value) => value !== normalizedId)
    : [...current, normalizedId]
}

export function resetSelectionForShopChange(
  previousShopId: string,
  nextShopId: string,
  current: string[],
) {
  return previousShopId === nextShopId ? [...current] : []
}

export function resetSelectionForSessionChange(
  previousSessionRef: string | null,
  nextSessionRef: string,
  current: string[],
) {
  return previousSessionRef === null || previousSessionRef === nextSessionRef
    ? [...current]
    : []
}

export function buildDraftTaskInput(candidate: DraftTaskInputCandidate): DraftTaskInput {
  const shopId = canonicalShopId(candidate.shopId)
  const productIds = mergeDraftSelection([], candidate.productIds)
  if (productIds.length < MIN_DRAFT_SELECTION) {
    throw new Error(`at least ${MIN_DRAFT_SELECTION} draft products are required`)
  }
  if (
    candidate.planId === null
    || !Number.isSafeInteger(candidate.planId)
    || candidate.planId <= 0
  ) {
    throw new Error('a positive plan id is required')
  }
  const input: DraftTaskInput = {
    shopId,
    productIds,
    planId: candidate.planId,
  }
  if (candidate.products) {
    const productsById = new Map(candidate.products.map((product) => [product.id, product]))
    input.items = productIds.map((productId) => {
      const product = productsById.get(productId)
      if (!product || (shopId !== '-1' && product.shop_id !== shopId)) {
        throw new Error(`product ${productId} is not bound to the confirmed shop`)
      }
      return {
        productId,
        shopId: product.shop_id,
        categoryId: product.category_id,
        title: product.subject,
      }
    })
  }
  return input
}

export function buildConfirmedDraftTaskInput(
  candidate: DraftTaskInputCandidate,
  sessionRef: string,
): ConfirmedDraftTaskInput {
  if (!isNonEmptyString(sessionRef)) {
    throw new Error('a current Reader session is required')
  }
  return {
    sessionRef,
    input: buildDraftTaskInput(candidate),
  }
}

function canonicalShopId(value: string) {
  if (value === '-1') return value
  return canonicalPositiveIntegerText(value, 'shop')
}

function canonicalProductId(value: string) {
  return canonicalPositiveIntegerText(value, 'product')
}

function sameDraftProductIdentity(
  first: DxmDraftProduct,
  second: DxmDraftProduct,
) {
  return first.id === second.id
    && first.shop_id === second.shop_id
    && first.subject === second.subject
    && first.category_id === second.category_id
    && first.dxm_state === second.dxm_state
}

function canonicalPositiveIntegerText(value: string, label: string) {
  if (!/^[1-9]\d*$/.test(value)) {
    throw new Error(`${label} id must be a positive integer string`)
  }
  return String(Number(value)) === value || BigInt(value).toString() === value
    ? value
    : BigInt(value).toString()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}
