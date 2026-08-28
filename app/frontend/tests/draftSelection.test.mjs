import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DraftProductIdentityConflictError,
  MAX_DRAFT_SELECTION,
  MIN_DRAFT_SELECTION,
  ReaderSessionChangedError,
  assertRealDraftPageResponse,
  assertRealDraftShopsResponse,
  buildConfirmedDraftTaskInput,
  buildDraftTaskInput,
  invalidateDraftSelectionState,
  mergeDraftSelection,
  mergeDraftProductSelection,
  readerSourceLabel,
  resetSelectionForShopChange,
  resetSelectionForSessionChange,
  toggleDraftSelection,
} from '../src/draftSelection.ts'

const realShopsResponse = {
  source: 'api',
  session_bound: true,
  session_ref: 'session-a',
  shops: [],
}

const realPageResponse = {
  source: 'api',
  session_bound: true,
  session_ref: 'session-a',
  filter: {
    shop_id: '101',
    dxm_state: 'draft',
  },
  pagination: {
    page_no: 1,
    page_size: 20,
    total_pages: 1,
    total_items: 1,
    has_previous: false,
    has_next: false,
  },
  items: [{
    id: '1001',
    shop_id: '101',
    subject: 'Draft one',
    category_id: '301',
    dxm_state: 'draft',
  }],
  deduplicated_count: 0,
}


test('confirmed input carries unified target category into the batch contract', () => {
  const confirmed = buildConfirmedDraftTaskInput(
    {
      shopId: '101',
      productIds: ['1001'],
      planId: 42,
      products: [{
        id: '1001',
        shop_id: '101',
        subject: 'Draft one',
        category_id: '301',
        dxm_state: 'draft',
      }],
      targetCategoryId: '300',
      targetCategoryName: 'ACG Stand(立牌类谷子)',
      targetCategoryMatch: 'ACG Stand',
    },
    'session-a',
  )
  assert.deepEqual(confirmed, {
    sessionRef: 'session-a',
    input: {
      shopId: '101',
      productIds: ['1001'],
      planId: 42,
      targetCategoryId: '300',
      targetCategoryName: 'ACG Stand(立牌类谷子)',
      targetCategoryMatch: 'ACG Stand',
      items: [{
        productId: '1001',
        shopId: '101',
        categoryId: '301',
        categoryName: null,
        title: 'Draft one',
      }],
    },
  })
  assert.equal(confirmed.input.targetCategoryId, '300')
})


test('confirmed input rejects an invalid target category id', () => {
  assert.throws(
    () => buildConfirmedDraftTaskInput(
      {
        shopId: '101',
        productIds: ['1001'],
        planId: 42,
        targetCategoryId: '0',
        targetCategoryMatch: 'ACG Stand',
      },
      'session-a',
    ),
    /target category/,
  )
})


test('selection keeps stable unique product ids in operator order', () => {
  assert.deepEqual(
    mergeDraftSelection(['1001'], ['1002', '1001', '1003']),
    ['1001', '1002', '1003'],
  )
  assert.deepEqual(
    toggleDraftSelection(['1001', '1002', '1003'], '1002'),
    ['1001', '1003'],
  )
  assert.deepEqual(
    toggleDraftSelection(['1001', '1003'], '1004'),
    ['1001', '1003', '1004'],
  )
})


test('cross-page selection accepts identical products and rejects identity drift', () => {
  const firstPageProduct = realPageResponse.items[0]
  const selected = mergeDraftProductSelection({}, [firstPageProduct])

  assert.deepEqual(
    mergeDraftProductSelection(selected, [{ ...firstPageProduct }]),
    selected,
  )
  for (const conflict of [
    { ...firstPageProduct, shop_id: '202' },
    { ...firstPageProduct, category_id: '999' },
    { ...firstPageProduct, subject: 'Changed after page turn' },
  ]) {
    assert.throws(
      () => mergeDraftProductSelection(selected, [conflict]),
      DraftProductIdentityConflictError,
    )
  }
})


test('changing shop clears cross-store selection', () => {
  assert.deepEqual(
    resetSelectionForShopChange('101', '202', ['1001', '1002', '1003']),
    [],
  )
  assert.deepEqual(
    resetSelectionForShopChange('101', '101', ['1001', '1002', '1003']),
    ['1001', '1002', '1003'],
  )
})


test('changing visible browser session clears cross-session selection', () => {
  assert.deepEqual(
    resetSelectionForSessionChange('session-a', 'session-b', ['1001', '1002', '1003']),
    [],
  )
  assert.deepEqual(
    resetSelectionForSessionChange('session-a', 'session-a', ['1001', '1002', '1003']),
    ['1001', '1002', '1003'],
  )
})


test('task input requires at least one product and a positive plan id', () => {
  assert.equal(MIN_DRAFT_SELECTION, 1)
  assert.equal(MAX_DRAFT_SELECTION, 100)
  assert.throws(
    () => buildDraftTaskInput({
      shopId: '101',
      productIds: [],
      planId: 9,
    }),
    /at least 1/,
  )
  assert.throws(
    () => buildDraftTaskInput({
      shopId: '101',
      productIds: ['1001'],
      planId: null,
    }),
    /plan/,
  )
})


test('task input rejects more than one hundred products before preview', () => {
  assert.throws(
    () => buildDraftTaskInput({
      shopId: '101',
      productIds: Array.from({ length: MAX_DRAFT_SELECTION + 1 }, (_, index) => String(index + 1000)),
      planId: 9,
    }),
    /at most 100/,
  )
})


test('reviewable task input keeps the exact shop, products and plan', () => {
  assert.deepEqual(
    buildDraftTaskInput({
      shopId: '-1',
      productIds: ['1001', '1002', '1002', '1003'],
      planId: 9,
    }),
    {
      shopId: '-1',
      productIds: ['1001', '1002', '1003'],
      planId: 9,
    },
  )
})


test('confirmed task input is bound to the current Reader session', () => {
  assert.deepEqual(
    buildConfirmedDraftTaskInput({
      shopId: '101',
      productIds: ['1001', '1002', '1003'],
      planId: 9,
    }, 'session-a'),
    {
      sessionRef: 'session-a',
      input: {
        shopId: '101',
        productIds: ['1001', '1002', '1003'],
        planId: 9,
      },
    },
  )
  assert.throws(
    () => buildConfirmedDraftTaskInput({
      shopId: '101',
      productIds: ['1001', '1002', '1003'],
      planId: 9,
    }, ''),
    /session/,
  )
})


test('Reader failure, page remount and session change invalidate stale input', () => {
  for (const reason of ['reader_failure', 'page_remount', 'browser_session_change']) {
    assert.deepEqual(
      invalidateDraftSelectionState(reason),
      {
        sessionRef: null,
        selectedIds: [],
        selectedProducts: {},
        confirmedInput: null,
        invalidatedBy: reason,
      },
    )
  }
})


test('shop source attestation rejects fallback and mock payloads', () => {
  assert.equal(assertRealDraftShopsResponse(realShopsResponse), realShopsResponse)
  for (const source of ['fallback', 'mock']) {
    assert.throws(
      () => assertRealDraftShopsResponse({ ...realShopsResponse, source }),
      /真实 API/,
    )
  }
})


test('product source attestation rejects fallback and mock payloads', () => {
  assert.equal(
    assertRealDraftPageResponse(realPageResponse, {
      shopId: '101',
      sessionRef: 'session-a',
    }),
    realPageResponse,
  )
  for (const source of ['fallback', 'mock']) {
    assert.throws(
      () => assertRealDraftPageResponse(
        { ...realPageResponse, source },
        { shopId: '101', sessionRef: 'session-a' },
      ),
      /真实 API/,
    )
  }
})


test('product response from another Reader session fails closed', () => {
  assert.throws(
    () => assertRealDraftPageResponse(
      { ...realPageResponse, session_ref: 'session-b' },
      { shopId: '101', sessionRef: 'session-a' },
    ),
    ReaderSessionChangedError,
  )
})


test('Reader source label exposes API, waiting and failed states', () => {
  assert.equal(readerSourceLabel(realShopsResponse, null), '实时 API · 当前会话')
  assert.equal(readerSourceLabel(null, null), '等待真实 API')
  assert.equal(
    readerSourceLabel(null, '本机 Reader 服务不可用'),
    '真实 Reader 读取失败',
  )
  assert.equal(
    readerSourceLabel(null, '真实浏览器会话已变化'),
    '真实 Reader 读取失败 · 状态已失效',
  )
})
