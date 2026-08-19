import { useEffect, useMemo, useState } from 'react'

import { getJson, postJson } from '../../api'
import type {
  DxmDraftPageResponse,
  DxmDraftShop,
  DxmDraftShopsResponse,
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
}

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
  const [shops, setShops] = useState<DxmDraftShop[]>([])
  const [shopId, setShopId] = useState('')
  const [typeFilter, setTypeFilter] = useState<'all' | DxmTemplateRef['ref_type']>('all')
  const [selectedId, setSelectedId] = useState<number | null>(refs[0]?.id ?? null)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const response = await getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops')
        setShops(response.shops)
        setShopId((current) => current || response.shops[0]?.id || '')
      } catch (error) {
        setMessage({
          tone: 'error',
          text: error instanceof Error ? error.message : '店铺列表读取失败，请先连接店小秘。',
        })
      }
    })()
  }, [])

  const visibleRefs = useMemo(
    () => refs.filter((ref) => (
      (!shopId || ref.shop_id === shopId)
      && (typeFilter === 'all' || ref.ref_type === typeFilter)
    )),
    [refs, shopId, typeFilter],
  )
  const selected = visibleRefs.find((ref) => ref.id === selectedId) ?? visibleRefs[0] ?? null

  async function syncFromDxm() {
    if (!shopId) {
      setMessage({ tone: 'error', text: '请先选择店铺。' })
      return
    }
    setSyncing(true)
    setMessage(null)
    try {
      const page = await getJson<DxmDraftPageResponse>(
        `/api/dxm/draft-reader/products?shop_id=${encodeURIComponent(shopId)}&page_no=1&page_size=100`,
      )
      const categoryIds = [...new Set(page.items.map((item) => item.category_id).filter((value): value is string => Boolean(value)))]
      if (!categoryIds.length) {
        throw new Error('该店采集箱草稿没有类目，无法同步模板。请先在店小秘给草稿选好类目。')
      }
      const result = await postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync', {
        shop_id: shopId,
        category_ids: categoryIds,
      })
      await onChanged()
      setMessage({
        tone: 'ok',
        text: `已从店小秘同步 ${result.refs.length} 条模板（店铺 ${shopName(shopId, shops)}，${categoryIds.length} 个类目）。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '同步失败。',
      })
    } finally {
      setSyncing(false)
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
            <button className="button button--primary" type="button" disabled={!shopId || syncing} onClick={() => { void syncFromDxm() }}>
              {syncing ? '正在同步…' : '同步当前店铺'}
            </button>
          </div>
        </div>
        <div className="dxm-template-library__toolbar">
          <label>
            <span>店铺</span>
            <select value={shopId} onChange={(event) => setShopId(event.target.value)}>
              {!shops.length && <option value="">暂无店铺，请先登录</option>}
              {shops.map((shop) => (
                <option key={shop.id} value={shop.id}>{shop.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>类型</span>
            <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as typeof typeFilter)}>
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
        {message && (
          <div className={message.tone === 'ok' ? 'draft-selection-notice' : 'draft-selection-alert'} role="status">
            {message.text}
          </div>
        )}
      </div>

      <article className="module-card span-2">
        <div className="dxm-template-table" role="table" aria-label="已同步模板">
          <div className="dxm-template-table__head" role="row">
            <span>模板名</span>
            <span>类型</span>
            <span>店铺</span>
            <span>类目</span>
            <span>状态</span>
          </div>
          {visibleRefs.length ? visibleRefs.map((ref) => (
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
          )) : (
            <div className="empty-state">
              <strong>还没有同步到模板</strong>
              <span>选好店铺后点「同步当前店铺」。模板本身请在店小秘后台创建。</span>
            </div>
          )}
        </div>
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
