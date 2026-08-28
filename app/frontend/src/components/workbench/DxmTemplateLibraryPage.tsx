import { useMemo, useState } from 'react'

import { postJson, withDxmSessionBusyRetry } from '../../api'
import { useDxmShop } from '../../dxmShopContext'
import type {
  DxmDraftShop,
  DxmTemplateRef,
  DxmTemplateRefSyncResult,
} from '../../types'

const REF_TYPE_LABELS: Record<DxmTemplateRef['ref_type'], string> = {
  product: '产品模板',
  attribute: '属性模板',
  variation: '变种模板',
  freight: '运费模板',
  service: '服务模板',
  size: '尺码表',
  regional: '区域调价模板',
  module_property: '产品属性模板',
  module_template: '编辑页模块模板',
  module_package: '包装模块模板',
}

const TEMPLATE_PAGE_SIZES = [20, 50, 100, 200] as const

type DxmTemplateLibraryPageProps = {
  refs: DxmTemplateRef[]
  onChanged: () => void | Promise<void>
  onShowDxmAccess: () => void
  onShowPlans: () => void
}

export function DxmTemplateLibraryPage({
  refs,
  onChanged,
  onShowDxmAccess,
  onShowPlans,
}: DxmTemplateLibraryPageProps) {
  const {
    shops,
    selectedShopId: shopId,
    setSelectedShopId,
    loading: shopsLoading,
    error: shopReadError,
    refresh: refreshShops,
  } = useDxmShop()
  const [typeFilter, setTypeFilter] = useState<'all' | DxmTemplateRef['ref_type']>('all')
  const [selectedId, setSelectedId] = useState<number | null>(refs[0]?.id ?? null)
  const [pageNo, setPageNo] = useState(1)
  const [pageSize, setPageSize] = useState<(typeof TEMPLATE_PAGE_SIZES)[number]>(20)
  const [syncing, setSyncing] = useState(false)
  const [syncStage, setSyncStage] = useState<'idle' | 'reading_templates'>('idle')
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const [lastSync, setLastSync] = useState<DxmTemplateRefSyncResult | null>(null)

  const visibleRefs = useMemo(
    () => refs.filter((ref) => (
      (!shopId || ref.shop_id === shopId)
      && (typeFilter === 'all' || ref.ref_type === typeFilter)
    )),
    [refs, shopId, typeFilter],
  )
  const totalPages = Math.max(1, Math.ceil(visibleRefs.length / pageSize))
  const currentPage = Math.min(pageNo, totalPages)
  const pagedRefs = useMemo(
    () => visibleRefs.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [currentPage, pageSize, visibleRefs],
  )
  const selected = pagedRefs.find((ref) => ref.id === selectedId) ?? pagedRefs[0] ?? null

  async function syncFromDxm() {
    if (!shopId) {
      await refreshShops(true)
      setMessage({ tone: 'error', text: '尚未选择店铺，请先在左侧选择真实店铺。' })
      return
    }
    setSyncing(true)
    setSyncStage('reading_templates')
    setMessage(null)
    try {
      setSyncStage('reading_templates')
      const result = await withDxmSessionBusyRetry(
        () => postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync-shop', {
          shop_id: shopId,
        }),
      )
      await onChanged()
      setLastSync(result)
      const elapsedSeconds = typeof result.elapsed_ms === 'number'
        ? `${Math.max(0.1, result.elapsed_ms / 1000).toFixed(1)} 秒`
        : null
      setMessage({
        tone: result.refs.length ? 'ok' : 'error',
        text: result.refs.length
          ? `已从店小秘同步 ${result.refs.length} 条店铺模板（店铺 ${shopName(shopId, shops)}；按店铺管理中心读取${result.category_ids.length ? `，其中 ${result.category_ids.length} 个类目仅为模板返回的关联信息，不是本次同步范围` : ''}${elapsedSeconds ? `，耗时 ${elapsedSeconds}` : ''}）。`
          : `店小秘读取已完成，但返回 0 条模板记录（当前店铺 ${shopName(shopId, shops)}；这不是采集箱为空导致的，请确认当前登录账号和店铺，仍有疑问请查看同步日志${elapsedSeconds ? `，耗时 ${elapsedSeconds}` : ''}）。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '同步失败。',
      })
    } finally {
      setSyncing(false)
      setSyncStage('idle')
    }
  }

  return (
    <section className="module-layout dxm-template-library" aria-label="店小秘模板">
      <div className="module-card span-3">
        <div className="module-head">
          <div>
            <span className="eyebrow">只读同步</span>
            <h2>店小秘里已配置的模板</h2>
            <p>这里只拉取你在店小秘后台配好的产品/属性/运费/服务等模板。不能在本控制台新建或改店小秘模板。</p>
          </div>
          <div className="dxm-template-library__actions">
            <button className="button button--quiet" type="button" onClick={onShowDxmAccess}>检查店小秘连接</button>
            <button className="button button--secondary" type="button" onClick={onShowPlans}>去建普货方案</button>
            <button className="button button--quiet" type="button" disabled={shopsLoading} onClick={() => { void refreshShops(true) }}>
              {shopsLoading ? '正在读取店铺…' : '重新读取店铺'}
            </button>
            <button className="button button--primary" type="button" disabled={!shopId || syncing || shopsLoading} onClick={() => { void syncFromDxm() }}>
              {syncStage === 'reading_templates' ? '正在读取店铺模板…' : '同步当前店铺'}
            </button>
          </div>
        </div>
        <div className="dxm-template-library__toolbar">
          <label>
            <span>店铺</span>
            <select value={shopId} disabled={shopsLoading} onChange={(event) => { setSelectedShopId(event.target.value); setPageNo(1) }}>
              {shopsLoading && <option value="">正在读取店铺…</option>}
              {!shopsLoading && !shops.length && <option value="">尚未读取到店铺</option>}
              {shops.map((shop) => (
                <option key={shop.id} value={shop.id}>{shop.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>类型</span>
            <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value as typeof typeFilter); setPageNo(1) }}>
              <option value="all">全部类型</option>
              {Object.entries(REF_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <div className="dxm-template-library__counts">
            <strong>{visibleRefs.length}</strong>
            <span>条可见 · 共 {refs.length} 条已同步</span>
          </div>
        </div>
        {shopsLoading && (
          <div className="dxm-template-library__shop-status" role="status">
            正在从已登录的真实浏览器读取店铺；如果上一条店小秘操作尚未结束，系统会自动重试。
          </div>
        )}
        {shopReadError && (
            <div className="draft-selection-alert dxm-template-library__shop-status" role="alert">
            店铺读取未完成：{shopReadError} <button className="button button--quiet" type="button" disabled={shopsLoading} onClick={() => { void refreshShops() }}>重新读取</button>
          </div>
        )}
        {message && (
          <div className={message.tone === 'ok' ? 'draft-selection-notice' : 'draft-selection-alert'} role="status">
            {message.text}
          </div>
        )}
        {lastSync && (
          <details className="dxm-template-library__trace">
            <summary>查看本次同步诊断（不含账号、Cookie 或模板正文）</summary>
            <p>
              同步编号：<code>{lastSync.sync_correlation_id ?? '本次旧接口未提供编号'}</code>
              {' · '}当前店铺：{shopName(lastSync.shop_id, shops)}
              {' · '}结果：{lastSync.sync_status === 'empty' ? '已读取但没有返回模板记录' : `已同步 ${lastSync.refs.length} 条`}
            </p>
            <ul>
              {(lastSync.request_trace ?? []).map((trace, index) => (
                <li key={`${trace.path}-${index}`}>
                  {trace.label}：{trace.outcome === 'ok' ? '成功' : '失败'}
                  {' · '}{trace.path}
                  {' · '}HTTP {trace.status ?? '未取得'}
                  {' · '}{trace.elapsed_ms}ms
                  {typeof trace.item_count === 'number' ? ` · ${trace.item_count} 条` : ''}
                  {trace.reason ? ` · ${trace.reason}` : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <article className="module-card span-2 dxm-template-list-card">
        <div className="dxm-template-table" role="table" aria-label="已同步模板">
          <div className="dxm-template-table__head" role="row">
            <span>模板名</span>
            <span>类型</span>
            <span>店铺</span>
            <span>类目</span>
            <span>状态</span>
          </div>
          {syncing && (
            <div className="dxm-template-library__sync-status" role="status">
              <strong>正在读取店小秘模板…</strong>
              <span>正在按当前登录账号与所选店铺读取管理中心模板；完成前不把当前列表判定为“无模板”。</span>
            </div>
          )}
          {visibleRefs.length ? pagedRefs.map((ref) => (
            <button
              key={ref.id}
              type="button"
              role="row"
              className={ref.id === selected?.id ? 'is-selected' : ''}
              onClick={() => setSelectedId(ref.id)}
            >
              <strong>{ref.observed_display_name || `模板 ${ref.dxm_template_id}`}</strong>
              <span>{REF_TYPE_LABELS[ref.ref_type]}</span>
              <span>{shopName(ref.shop_id, shops)}</span>
              <span>{ref.category_id ?? '店铺级'}</span>
              <b>{ref.availability === 'available' ? '可用' : '已漂移'}</b>
            </button>
          )) : syncing ? null : (
            <div className="empty-state">
              <strong>{refs.length ? '当前店铺没有已同步模板' : '还没有同步到模板'}</strong>
              <span>{refs.length
                ? `当前店铺（${shopName(shopId, shops)}）没有记录；其他店铺共已同步 ${refs.length} 条。`
                : '选好店铺后点「同步当前店铺」。如果同步结果显示 0 条，表示读取成功但店小秘没有返回模板记录。'}</span>
            </div>
          )}
        </div>
        <footer className="dxm-template-pagination" aria-label="模板分页">
          <span>{templatePaginationSummary(currentPage, pageSize, visibleRefs.length)}</span>
          <div className="dxm-template-pagination__nav">
            <button
              className="button button--quiet"
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setPageNo((current) => Math.max(1, current - 1))}
            >
              上一页
            </button>
            <span className="dxm-template-pagination__page">第 {currentPage} / {totalPages} 页</span>
            <button
              className="button button--quiet"
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setPageNo((current) => Math.min(totalPages, current + 1))}
            >
              下一页
            </button>
            <label>
              <span className="sr-only">每页模板数量</span>
              <select
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value) as (typeof TEMPLATE_PAGE_SIZES)[number])
                  setPageNo(1)
                }}
              >
                {TEMPLATE_PAGE_SIZES.map((size) => <option key={size} value={size}>{size} 条/页</option>)}
              </select>
            </label>
          </div>
        </footer>
      </article>

      <aside className="module-card">
        <div className="module-head">
          <div>
            <span className="eyebrow">查看</span>
            <h2>模板详情</h2>
          </div>
        </div>
        {selected ? (
          <dl className="dxm-template-detail">
            <div><dt>显示名</dt><dd>{selected.observed_display_name}</dd></div>
            <div><dt>类型</dt><dd>{REF_TYPE_LABELS[selected.ref_type]}</dd></div>
            <div><dt>店小秘 ID</dt><dd>{selected.dxm_template_id}</dd></div>
            <div><dt>店铺</dt><dd>{shopName(selected.shop_id, shops)}</dd></div>
            <div><dt>类目</dt><dd>{selected.category_id ?? '店铺级'}</dd></div>
            <div><dt>状态</dt><dd>{selected.availability === 'available' ? '可用' : '已漂移 / 不可用'}</dd></div>
            <div><dt>同步时间</dt><dd>{selected.synced_at.replace('T', ' ').slice(0, 19)}</dd></div>
          </dl>
        ) : (
          <p>从左侧点一条模板查看。</p>
        )}
        <div className="dxm-template-crud">
          <button type="button" className="button button--quiet" disabled>新建（请在店小秘做）</button>
          <button type="button" className="button button--quiet" disabled>编辑（只读）</button>
          <button type="button" className="button button--quiet" disabled>删除（只读）</button>
          <small>本页只同步和查看。增删改在店小秘后台；同步会更新本列表。</small>
        </div>
      </aside>
    </section>
  )
}

function shopName(shopId: string, shops: DxmDraftShop[]) {
  return shops.find((shop) => shop.id === shopId)?.name ?? shopId
}

function templatePaginationSummary(pageNo: number, pageSize: number, total: number) {
  if (!total) return '共 0 条'
  const from = (pageNo - 1) * pageSize + 1
  const to = Math.min(pageNo * pageSize, total)
  return `第 ${from}–${to} 条，共 ${total} 条`
}
