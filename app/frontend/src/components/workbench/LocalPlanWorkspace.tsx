import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

import { deleteJson, getJson, postJson } from '../../api'
import { resolveSchemaChoiceOptions } from '../../schemaValueEditor'
import type {
  DxmDraftPageResponse,
  DxmDraftShop,
  DxmDraftShopsResponse,
  DxmTemplateRef,
  DxmTemplateRefSyncResult,
  E2CategorySchema,
  E2CategorySchemaProperty,
  LocalPlanTemplate,
} from '../../types'

type LocalPlanWorkspaceProps = {
  plans: LocalPlanTemplate[]
  dxmTemplateRefs: DxmTemplateRef[]
  onChanged: () => void | Promise<void>
}

type SchemaFieldDraft = {
  uiLabelZh: string
  strategy: 'inherit' | 'fill' | 'fixed'
  value: unknown
}

type SchemaFieldDrafts = Record<string, Record<string, SchemaFieldDraft>>

const REF_TYPE_LABELS: Record<DxmTemplateRef['ref_type'], string> = {
  product: '产品模板',
  attribute: '属性模板',
  variation: '变种模板',
  freight: '运费模板',
  service: '服务模板',
  size: '尺码表',
}

const REF_TYPE_ORDER: DxmTemplateRef['ref_type'][] = [
  'freight', 'service', 'product', 'attribute', 'variation', 'size',
]

export function LocalPlanWorkspace({
  plans,
  dxmTemplateRefs,
  onChanged,
}: LocalPlanWorkspaceProps) {
  const [viewMode, setViewMode] = useState<'list' | 'edit'>('list')
  const [activeSection, setActiveSection] = useState<'basic' | 'templates' | 'advanced'>('basic')
  const [activeRefType, setActiveRefType] = useState<DxmTemplateRef['ref_type'] | null>(null)
  const [activeAdvancedCategory, setActiveAdvancedCategory] = useState<string | null>(null)
  const [activeAdvancedGroup, setActiveAdvancedGroup] = useState<string>('product')
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null)
  const [supersedesId, setSupersedesId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [version, setVersion] = useState('1.0.0')
  const [shops, setShops] = useState<DxmDraftShop[]>([])
  const [shopId, setShopId] = useState('')
  const [categoryIdsText, setCategoryIdsText] = useState('')
  const [categoryChoices, setCategoryChoices] = useState<string[]>([])
  const [categoryNames, setCategoryNames] = useState<Record<string, string>>({})
  const [categorySchemas, setCategorySchemas] = useState<Record<string, E2CategorySchema>>({})
  const [fieldDrafts, setFieldDrafts] = useState<SchemaFieldDrafts>({})
  const [selectedRefIds, setSelectedRefIds] = useState<number[]>([])
  const [provenance, setProvenance] = useState('operator_reviewed_local_plan')
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [syncingRefs, setSyncingRefs] = useState(false)

  const activePlans = useMemo(() => plans.filter((plan) => plan.is_active), [plans])
  const archivedPlans = useMemo(() => plans.filter((plan) => !plan.is_active), [plans])
  const selectedPlan = useMemo(
    () => plans.find((plan) => plan.id === selectedPlanId) ?? null,
    [plans, selectedPlanId],
  )
  const selectedCategoryIds = parseLooseCategoryIds(categoryIdsText)
  const availableRefs = dxmTemplateRefs.filter((ref) => (
    ref.availability === 'available'
    && (!shopId || ref.shop_id === shopId)
    && (!ref.category_id || selectedCategoryIds.includes(ref.category_id))
  ))
  const refsByType = useMemo(() => {
    const grouped: Partial<Record<DxmTemplateRef['ref_type'], DxmTemplateRef[]>> = {}
    for (const ref of availableRefs) {
      (grouped[ref.ref_type] ??= []).push(ref)
    }
    return grouped
  }, [availableRefs])

  useEffect(() => {
    void (async () => {
      try {
        const response = await getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops')
        setShops(response.shops)
        setShopId((current) => current || response.shops[0]?.id || '')
      } catch {
        // 未登录时仍可用已同步引用建方案
      }
    })()
  }, [])

  function openCreate() {
    setViewMode('edit')
    setActiveSection('basic')
    setSelectedPlanId(null)
    setSupersedesId(null)
    setName('')
    setVersion('1.0.0')
    setShopId(shops[0]?.id ?? '')
    setCategoryIdsText('')
    setCategoryChoices([])
    setCategorySchemas({})
    setFieldDrafts({})
    setSelectedRefIds([])
    setMessage(null)
  }

  function openEditForPlan(plan: LocalPlanTemplate) {
    setViewMode('edit')
    setActiveSection('basic')
    setSelectedPlanId(plan.id)
    setSupersedesId(null)
    setName(plan.name)
    setVersion(plan.version)
    setShopId(plan.shop_id)
    setCategoryIdsText(plan.category_ids.join(', '))
    setCategoryChoices(plan.category_ids)
    setSelectedRefIds(plan.dxm_template_refs.map((binding) => binding.ref_id))
    setProvenance(plan.provenance)
    setMessage(null)
  }

  function beginVersionFromCurrent() {
    if (!selectedPlan) return
    setSupersedesId(selectedPlan.id)
    setVersion(nextPatchVersion(selectedPlan.version))
    setMessage(null)
  }

  function backToList() {
    setViewMode('list')
    setMessage(null)
  }

  function toggleRef(refId: number) {
    setSelectedRefIds((current) => current.includes(refId)
      ? current.filter((value) => value !== refId)
      : [...current, refId])
  }

  function toggleCategory(categoryId: string) {
    const next = selectedCategoryIds.includes(categoryId)
      ? selectedCategoryIds.filter((value) => value !== categoryId)
      : [...selectedCategoryIds, categoryId]
    setCategoryIdsText(next.join(', '))
  }

  async function syncReadonlyRefs() {
    const normalizedShopId = shopId.trim()
    if (!/^[1-9][0-9]*$/.test(normalizedShopId)) {
      setMessage({ tone: 'error', text: '请先选择店铺。' })
      return
    }
    setSyncingRefs(true)
    setMessage(null)
    try {
      const page = await getJson<DxmDraftPageResponse>(
        `/api/dxm/draft-reader/products?shop_id=${encodeURIComponent(normalizedShopId)}&page_no=1&page_size=100`,
      )
      const fromDrafts = [...new Set(page.items.map((item) => item.category_id).filter((value): value is string => Boolean(value)))]
      const syncIds = selectedCategoryIds.length ? selectedCategoryIds : fromDrafts
      if (!syncIds.length) {
        throw new Error('该店草稿没有类目，无法同步。请先在店小秘给草稿选类目。')
      }
      setCategoryChoices(syncIds)
      if (!selectedCategoryIds.length) setCategoryIdsText(syncIds.join(', '))
      const names: Record<string, string> = {}
      page.items.forEach((item) => {
        if (item.category_id && item.category_name) names[item.category_id] = item.category_name
      })
      setCategoryNames(names)
      const result = await postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync', {
        shop_id: normalizedShopId,
        category_ids: syncIds,
      })
      const grouped: Partial<Record<DxmTemplateRef['ref_type'], DxmTemplateRef[]>> = {}
      result.refs.forEach((ref) => { (grouped[ref.ref_type] ??= []).push(ref) })
      const firstType = REF_TYPE_ORDER.find((type) => (grouped[type] ?? []).length)
      if (firstType) setActiveRefType(firstType)
      if (syncIds[0]) setActiveAdvancedCategory(syncIds[0])
      setCategorySchemas(result.category_schemas)
      setFieldDrafts(buildFieldDrafts(result.category_schemas, supersedesId ? selectedPlan : null))
      await onChanged()
      setMessage({
        tone: 'success',
        text: `已同步 ${result.refs.length} 条店小秘模板，${syncIds.length} 个类目。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '店小秘只读同步失败。',
      })
    } finally {
      setSyncingRefs(false)
    }
  }

  async function savePlan() {
    setSubmitting(true)
    setMessage(null)
    try {
      const categoryIds = parseLooseCategoryIds(categoryIdsText)
      if (!name.trim()) throw new Error('请填写方案名称。')
      if (!/^[1-9][0-9]*$/.test(shopId.trim())) throw new Error('请选择店铺。')
      if (!categoryIds.length) throw new Error('请勾选至少一个适用类目（先点「同步店小秘模板」）。')
      const { fillRules, fixedFieldValues, fieldMappings } = buildStructuredPlanFields(
        categoryIds,
        categorySchemas,
        fieldDrafts,
      )
      const refs = selectedRefIds.map((refId) => {
        const ref = availableRefs.find((candidate) => candidate.id === refId)
        if (!ref) throw new Error(`只读引用 #${refId} 已漂移或不可用`)
        return { ref_id: ref.id, source_digest: ref.source_digest }
      })
      const body = {
        name: name.trim(),
        version: (supersedesId ? version.trim() : '1.0.0') || '1.0.0',
        shop_id: shopId.trim(),
        category_ids: categoryIds,
        path: 'A',
        fixed_values: { publish_allowed: false, field_values: fixedFieldValues },
        fill_rules: fillRules,
        dxm_template_refs: refs,
        field_mappings: fieldMappings,
        validation_policy: { required_fields: 'fail_closed', natural_language: 'english_before_save' },
        exception_policy: { unknown: 'stop_batch' },
        provenance: provenance.trim(),
      }
      const path = supersedesId == null
        ? '/api/local-plan-templates'
        : `/api/local-plan-templates/${supersedesId}/versions`
      const created = await postJson<LocalPlanTemplate>(path, body)
      setSelectedPlanId(created.id)
      setSupersedesId(null)
      await onChanged()
      setMessage({
        tone: 'success',
        text: `已保存「${created.name}」。采集箱选品的下拉里会出现这个方案。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '本地方案保存失败。',
      })
    } finally {
      setSubmitting(false)
    }
  }

  async function archiveSelectedPlan() {
    if (!selectedPlan || !selectedPlan.is_active) return
    if (!window.confirm(`确认删除「${selectedPlan.name}」吗？已开始的任务不受影响。`)) return
    setSubmitting(true)
    setMessage(null)
    try {
      await deleteJson<LocalPlanTemplate>(`/api/local-plan-templates/${selectedPlan.id}`)
      await onChanged()
      setViewMode('list')
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '方案删除失败。',
      })
    } finally {
      setSubmitting(false)
    }
  }

  function updateFieldDraft(
    categoryId: string,
    fieldKey: string,
    patch: Partial<SchemaFieldDraft>,
  ) {
    setFieldDrafts((current) => ({
      ...current,
      [categoryId]: {
        ...(current[categoryId] ?? {}),
        [fieldKey]: {
          ...(current[categoryId]?.[fieldKey] ?? { uiLabelZh: '', strategy: 'inherit', value: undefined }),
          ...patch,
        },
      },
    }))
  }

  if (viewMode === 'list') {
    return (
      <div className="local-plan-list">
        <div className="local-plan-list__head">
          <div>
            <h2>普货方案</h2>
            <p>采集箱选品时选这里的方案。点一个方案查看详情，或新建一个。</p>
          </div>
          <button className="button button--primary" type="button" onClick={openCreate}>新建方案</button>
        </div>

        <div className="local-plan-section-head">
          <h3>可用方案</h3>
          <small>{activePlans.length} 个</small>
        </div>
        {activePlans.length ? (
          <div className="local-plan-cards">
            {activePlans.map((plan) => (
              <button
                key={plan.id}
                type="button"
                className="local-plan-card"
                onClick={() => openEditForPlan(plan)}
              >
                <strong>{plan.name}</strong>
                <span>{shopLabel(plan.shop_id, shops)} · {plan.category_ids.length} 个类目 · 引用 {plan.dxm_template_refs.length} 个模板</span>
                <small>上次更新 {plan.updated_at.replace('T', ' ').slice(0, 16)}</small>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state local-plan-empty">
            <strong>还没有方案</strong>
            <span>点上方「新建方案」。方案会套用店小秘模板，再给采集箱选品用。</span>
          </div>
        )}

        {archivedPlans.length > 0 && (
          <details className="local-plan-archived">
            <summary>已删除（{archivedPlans.length}）</summary>
            <div className="local-plan-cards is-archived">
              {archivedPlans.map((plan) => (
                <button
                  key={plan.id}
                  type="button"
                  className="local-plan-card"
                  onClick={() => openEditForPlan(plan)}
                >
                  <strong>{plan.name}</strong>
                  <span>{shopLabel(plan.shop_id, shops)}</span>
                  <small>已删除 · 可查看但不能再用于新任务</small>
                </button>
              ))}
            </div>
          </details>
        )}
      </div>
    )
  }

  return createPortal(
    <div className="lp-modal-overlay" role="dialog" aria-modal="true" aria-label={selectedPlanId ? '编辑方案' : '新建方案'}>
      <div className="lp-modal">
        <header className="lp-modal__head">
          <div>
            <h2>{name.trim() || (selectedPlanId ? '查看方案' : '新建方案')}</h2>
          </div>
          <div className="lp-modal__actions">
            {selectedPlan?.is_active && (
              <button className="button button--quiet" type="button" disabled={submitting} onClick={() => { void archiveSelectedPlan() }}>删除</button>
            )}
            {selectedPlan && !supersedesId && (
              <button className="button button--secondary" type="button" onClick={beginVersionFromCurrent}>改新版</button>
            )}
            <button className="button button--quiet" type="button" onClick={backToList}>关闭</button>
          </div>
        </header>
        {message && (
          <div className={message.tone === 'success' ? 'draft-selection-notice' : 'draft-selection-alert'} role="status">
            {message.text}
          </div>
        )}

        <div className="lp-modal__body">
          <nav className="lp-sections-nav" aria-label="方案分区">
            <button
              type="button"
              className={activeSection === 'basic' ? 'is-active' : ''}
              onClick={() => setActiveSection('basic')}
            >
              基本信息
              {!name.trim() && <b>·</b>}
            </button>
            <button
              type="button"
              className={activeSection === 'templates' ? 'is-active' : ''}
              onClick={() => setActiveSection('templates')}
            >
              套用店小秘模板
              <small>{selectedRefIds.length || ''}</small>
            </button>
            <button
              type="button"
              className={activeSection === 'advanced' ? 'is-active' : ''}
              onClick={() => setActiveSection('advanced')}
            >
              高级（字段补差）
            </button>
          </nav>

          <div className="lp-section-form">
            {activeSection === 'basic' && (
              <div className="lp-form-block">
                <label className="lp-field">
                  <span>方案名称</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 Funload 普货只保存" />
                </label>
                <label className="lp-field">
                  <span>店铺</span>
                  <select value={shopId} onChange={(event) => setShopId(event.target.value)}>
                    {!shops.length && <option value={shopId}>{shopId || '请先连接店小秘'}</option>}
                    {shops.map((shop) => (
                      <option key={shop.id} value={shop.id}>{shop.name}</option>
                    ))}
                  </select>
                </label>
                <div className="lp-field">
                  <div className="local-plan-categories__head">
                    <span>适用类目</span>
                    <button className="button button--quiet" type="button" disabled={!shopId || syncingRefs} onClick={() => { void syncReadonlyRefs() }}>
                      {syncingRefs ? '同步中…' : '同步店小秘模板'}
                    </button>
                  </div>
                  <div className="e2-category-picks">
                    {categoryChoices.map((categoryId) => (
                      <label key={categoryId}>
                        <input
                          type="checkbox"
                          checked={selectedCategoryIds.includes(categoryId)}
                          onChange={() => toggleCategory(categoryId)}
                        />
                        <span>{categoryNames[categoryId] || `类目 ${categoryId}`}</span>
                      </label>
                    ))}
                    {!categoryChoices.length && (
                      <small>选好店铺后点「同步店小秘模板」，会列出该店草稿涉及的类目。</small>
                    )}
                  </div>
                </div>
              </div>
            )}

            {activeSection === 'templates' && (
              <div className="lp-form-block">
                <p className="module-hint">先在「基本信息」里同步，再按类型勾选要带进方案的模板。</p>
                {availableRefs.length ? (
                  <div className="lp-split">
                    <nav className="lp-split__nav" role="tablist" aria-orientation="vertical">
                      {REF_TYPE_ORDER
                        .filter((type) => (refsByType[type] ?? []).length)
                        .map((type) => (
                          <button
                            key={type}
                            type="button"
                            role="tab"
                            className={(activeRefType ?? 'freight') === type ? 'is-active' : ''}
                            onClick={() => setActiveRefType(type)}
                          >
                            <span>{REF_TYPE_LABELS[type]}</span>
                            <small>{(refsByType[type] ?? []).length}</small>
                          </button>
                        ))}
                    </nav>
                    <div className="lp-split__content" role="tabpanel">
                      {(refsByType[activeRefType ?? 'freight'] ?? []).map((ref) => (
                        <label key={ref.id} className="lp-ref-item">
                          <input
                            type="checkbox"
                            checked={selectedRefIds.includes(ref.id)}
                            onChange={() => toggleRef(ref.id)}
                          />
                          <span>
                            <strong>{ref.observed_display_name || `模板 ${ref.dxm_template_id}`}</strong>
                            {ref.category_id && <small>类目 {categoryNames[ref.category_id] || ref.category_id}</small>}
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">
                    <strong>还没有可引用的模板</strong>
                    <span>回「基本信息」点「同步店小秘模板」从当前店铺拉取。</span>
                  </div>
                )}
              </div>
            )}

            {activeSection === 'advanced' && (
              <div className="lp-form-block">
                <div className="e2-structured-plan__head">
                  <span>
                    <strong>逐字段覆盖</strong>
                    <small>留空表示沿用商品当前值或店小秘模板。日常建方案可跳过。</small>
                  </span>
                </div>
                {Object.keys(categorySchemas).length ? (
                  <div className="lp-split">
                    <nav className="lp-split__nav" role="tablist" aria-orientation="vertical">
                      {selectedCategoryIds
                        .filter((categoryId) => categorySchemas[categoryId])
                        .map((categoryId) => (
                        <button
                          key={categoryId}
                          type="button"
                          role="tab"
                          className={(activeAdvancedCategory ?? Object.keys(categorySchemas)[0]) === categoryId ? 'is-active' : ''}
                          onClick={() => setActiveAdvancedCategory(categoryId)}
                        >
                          <span>{categoryNames[categoryId] || `类目 ${categoryId}`}</span>
                          <small>{Object.keys(categorySchemas[categoryId].properties).length} 字段</small>
                        </button>
                      ))}
                    </nav>
                    <div className="lp-split__content" role="tabpanel">
                      {(() => {
                        const availableCategoryIds = selectedCategoryIds.filter((c) => categorySchemas[c])
                        const categoryId = availableCategoryIds.includes(activeAdvancedCategory ?? '')
                          ? activeAdvancedCategory!
                          : availableCategoryIds[0]
                        if (!categoryId) return null
                        const schema = categorySchemas[categoryId]
                        if (!schema) return null
                        const fieldGroups = groupSchemaFields(schema)
                        const activeGroup = fieldGroups.find((group) => group.key === activeAdvancedGroup) ?? fieldGroups[0]
                        return (
                          <section className="e2-category-fields" aria-label={`类目 ${categoryId} 字段`}>
                            <div className="e2-category-fields__global-hint">
                              所有字段由店小秘类目属性决定，不可修改。仅可设置取值方式和补差值。
                            </div>
                            <header>
                              <span>
                                <strong>{categoryNames[categoryId] || `类目 ${categoryId}`}</strong>
                                <small>必填 {schema.required.length} 项 · 共 {Object.keys(schema.properties).length} 项</small>
                              </span>
                            </header>
                            <nav className="lp-split__subnav" role="tablist">
                              {fieldGroups.map((group) => (
                                <button
                                  key={group.key}
                                  type="button"
                                  role="tab"
                                  className={activeGroup.key === group.key ? 'is-active' : ''}
                                  onClick={() => setActiveAdvancedGroup(group.key)}
                                >
                                  {group.label}
                                  <small>{group.fields.length}</small>
                                </button>
                              ))}
                            </nav>
                            <div className="e2-category-fields__rows">
                              {activeGroup.fields.map(([fieldKey, definition], index) => {
                                const draft = fieldDrafts[categoryId]?.[fieldKey] ?? {
                                  uiLabelZh: schemaLabel(definition, index),
                                  strategy: 'inherit' as const,
                                  value: undefined,
                                }
                                const required = schema.required.includes(fieldKey)
                                return (
                                  <div className="e2-schema-field" key={fieldKey}>
                                    <div className="e2-schema-field__identity">
                                      <div className="e2-schema-field__name">
                                        <strong>{schemaLabel(definition, index)}</strong>
                                        {required && <em className="e2-required-badge">必填</em>}
                                      </div>
                                      <label>
                                        <select
                                          aria-label={`${schemaLabel(definition, index)} 来源策略`}
                                          value={draft.strategy}
                                          onChange={(event) => updateFieldDraft(
                                            categoryId,
                                            fieldKey,
                                            { strategy: event.target.value as SchemaFieldDraft['strategy'] },
                                          )}
                                        >
                                          <option value="inherit">继承（店小秘模板 → 商品当前值）</option>
                                          <option value="fill">补差规则（覆盖继承值）</option>
                                          <option value="fixed">固定值（最高优先）</option>
                                        </select>
                                      </label>
                                      {draft.strategy !== 'inherit' && (
                                        <SchemaValueEditor
                                          definition={definition}
                                          fieldKey={fieldKey}
                                          value={draft.value}
                                          valueLabel={draft.strategy === 'fixed' ? '固定值' : '补差值'}
                                          onChange={(value) => updateFieldDraft(categoryId, fieldKey, { value })}
                                        />
                                      )}
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          </section>
                        )
                      })()}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">
                    <strong>高级字段待同步</strong>
                    <span>日常建方案跳过这里即可。</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <footer className="lp-modal__foot">
          <small>只保存 · 不发布 · 必填 fail-closed</small>
          <button className="button button--primary" type="button" disabled={submitting} onClick={() => { void savePlan() }}>
            {submitting ? '保存中…' : selectedPlanId ? '保存为新版本' : '创建方案'}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

function shopLabel(shopId: string, shops: DxmDraftShop[]) {
  return shops.find((shop) => shop.id === shopId)?.name ?? `店铺 ${shopId}`
}

function parseLooseCategoryIds(source: string) {
  return [...new Set(
    source
      .split(/[\s,，;；]+/)
      .map((value) => value.trim())
      .filter((value) => /^[1-9][0-9]*$/.test(value)),
  )]
}

function parseCategoryIds(source: string) {
  const categoryIds = source
    .split(/[\s,，;；]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  if (!categoryIds.length || categoryIds.some((value) => !/^[1-9][0-9]*$/.test(value))) {
    throw new Error('只读同步前必须填写至少一个稳定 categoryId')
  }
  if (new Set(categoryIds).size !== categoryIds.length) {
    throw new Error('categoryId 不得重复')
  }
  return categoryIds
}

function nextPatchVersion(version: string) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version)
  if (!match) return ''
  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`
}

function buildFieldDrafts(
  schemas: Record<string, E2CategorySchema>,
  plan: LocalPlanTemplate | null,
): SchemaFieldDrafts {
  if (!plan) return {}
  const result: SchemaFieldDrafts = {}
  for (const categoryId of Object.keys(schemas)) {
    const schema = schemas[categoryId]
    const existingRules = (plan.fill_rules[categoryId] ?? {}) as Record<string, { value: unknown }>
    const fixedByCategory = plan.fixed_values.field_values
    const existingFixed = (
      typeof fixedByCategory === 'object'
      && !Array.isArray(fixedByCategory)
      && fixedByCategory !== null
    ) ? (fixedByCategory as Record<string, unknown>)[categoryId] : undefined
    const existingFixedMap = (
      typeof existingFixed === 'object'
      && existingFixed !== null
      && !Array.isArray(existingFixed)
    ) ? existingFixed as Record<string, unknown> : {}
    const existingLabels = new Map(
      (plan.field_mappings[categoryId]?.entries ?? []).map((entry) => [entry.field_key, entry.ui_label_zh]),
    )
    result[categoryId] = Object.fromEntries(
      Object.entries(schema.properties).map(([fieldKey, definition], index) => [
        fieldKey,
        {
          uiLabelZh: existingLabels.get(fieldKey) ?? schemaLabel(definition, index),
          strategy: Object.prototype.hasOwnProperty.call(existingFixedMap, fieldKey)
            ? 'fixed'
            : existingRules[fieldKey]
              ? 'fill'
              : 'inherit',
          value: Object.prototype.hasOwnProperty.call(existingFixedMap, fieldKey)
            ? existingFixedMap[fieldKey]
            : existingRules[fieldKey]?.value,
        },
      ]),
    )
  }
  return result
}

function buildStructuredPlanFields(
  categoryIds: string[],
  schemas: Record<string, E2CategorySchema>,
  drafts: SchemaFieldDrafts,
) {
  const fillRules: LocalPlanTemplate['fill_rules'] = {}
  const fixedFieldValues: Record<string, Record<string, unknown>> = {}
  const fieldMappings: LocalPlanTemplate['field_mappings'] = {}
  for (const categoryId of categoryIds) {
    const schema = schemas[categoryId]
    if (!schema) continue
    const categoryDrafts = drafts[categoryId] ?? {}
    fillRules[categoryId] = {}
    fixedFieldValues[categoryId] = {}
    const entries = Object.keys(schema.properties).map((fieldKey, index) => {
      const definition = schema.properties[fieldKey]
      const draft = categoryDrafts[fieldKey] ?? {
        uiLabelZh: schemaLabel(definition, index),
        strategy: 'inherit' as const,
        value: undefined,
      }
      const uiLabelZh = schemaLabel(definition, index)
      if (!/[\u3400-\u9fff]/.test(uiLabelZh)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 缺少中文字段名`)
      }
      if (draft.strategy !== 'inherit' && !isConfiguredValue(draft.value)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 已选择${draft.strategy === 'fixed' ? '固定值' : '补差规则'}但没有操作值`)
      }
      if (draft.strategy === 'fill' && isConfiguredValue(draft.value)) {
        fillRules[categoryId][fieldKey] = { value: draft.value }
      }
      if (draft.strategy === 'fixed' && isConfiguredValue(draft.value)) {
        fixedFieldValues[categoryId][fieldKey] = draft.value
      }
      const uiBinding = definition.ui_binding
      if (typeof uiBinding !== 'string' || !/^dxm_(?:editor:[A-Za-z][A-Za-z0-9_]*|attribute:[1-9][0-9]*)$/.test(uiBinding)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 缺少后端验证的 UI binding`)
      }
      return {
        ui_label_zh: uiLabelZh,
        field_key: fieldKey,
        category_schema_path: `$.properties.${fieldKey}`,
        ui_binding: uiBinding,
      }
    })
    fieldMappings[categoryId] = { mapping_version: `zh-map-${categoryId}-ui-v1`, entries }
  }
  return { fillRules, fixedFieldValues, fieldMappings }
}

function schemaLabel(definition: E2CategorySchemaProperty, index: number) {
  const label = typeof definition.ui_label_zh === 'string' ? definition.ui_label_zh.trim() : ''
  return label || `字段${index + 1}`
}

const ADVANCED_GROUP_ORDER = [
  'freight', 'service', 'product', 'attribute', 'variation', 'size',
] as const

const ADVANCED_GROUP_LABELS: Record<string, string> = {
  freight: '运费模板',
  service: '服务模板',
  product: '产品模板',
  attribute: '属性模板',
  variation: '变种模板',
  size: '尺码表',
}

function advancedGroupOfField(fieldKey: string): string {
  if (fieldKey === 'freightTemplateId') return 'freight'
  if (fieldKey === 'promiseTemplateId') return 'service'
  if (fieldKey === 'sizechartId') return 'size'
  if (fieldKey === 'aeopAeProductSKUs' || fieldKey === 'skuCode' || fieldKey.startsWith('sku')) return 'variation'
  if (fieldKey.startsWith('attr_')) return 'attribute'
  return 'product'
}

function groupSchemaFields(schema: E2CategorySchema) {
  const groups = new Map<string, [string, E2CategorySchemaProperty][]>(
    ADVANCED_GROUP_ORDER.map((key) => [key, []]),
  )
  for (const [fieldKey, definition] of Object.entries(schema.properties)) {
    groups.get(advancedGroupOfField(fieldKey))?.push([fieldKey, definition])
  }
  return ADVANCED_GROUP_ORDER
    .filter((key) => (groups.get(key) ?? []).length)
    .map((key) => ({ key, label: ADVANCED_GROUP_LABELS[key], fields: groups.get(key) ?? [] }))
}

function isConfiguredValue(value: unknown): boolean {
  if (value === undefined || value === null) return false
  if (typeof value === 'string') return Boolean(value.trim())
  if (Array.isArray(value)) return value.some(isConfiguredValue)
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some(isConfiguredValue)
  }
  return true
}

type SchemaValueEditorProps = {
  definition: E2CategorySchemaProperty
  fieldKey: string
  value: unknown
  valueLabel?: string
  onChange: (value: unknown) => void
}

function SchemaValueEditor({
  definition,
  fieldKey,
  value,
  valueLabel = '补差值',
  onChange,
}: SchemaValueEditorProps) {
  const options = resolveSchemaChoiceOptions(definition)
  if (options) {
    return (
      <label className="e2-schema-field__value">
        <span>{valueLabel}</span>
        <select
          aria-label={`${fieldKey} ${valueLabel}`}
          multiple={definition.type === 'array'}
          value={definition.type === 'array'
            ? Array.isArray(value) ? value.map(String) : []
            : value == null ? '' : String(value)}
          onChange={(event) => onChange(
            definition.type === 'array'
              ? Array.from(event.target.selectedOptions).map((option) => option.value)
              : event.target.value || undefined,
          )}
        >
          {definition.type !== 'array' && <option value="">沿用当前值 / 只读模板</option>}
          {options.map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
    )
  }
  if (definition.type === 'boolean') {
    return (
      <label className="e2-schema-field__value">
        <span>{valueLabel}</span>
        <select
          aria-label={`${fieldKey} ${valueLabel}`}
          value={typeof value === 'boolean' ? String(value) : ''}
          onChange={(event) => onChange(event.target.value === '' ? undefined : event.target.value === 'true')}
        >
          <option value="">沿用当前值 / 只读模板</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      </label>
    )
  }
  if (definition.type === 'number' || definition.type === 'integer') {
    return (
      <label className="e2-schema-field__value">
        <span>{valueLabel}</span>
        <input
          aria-label={`${fieldKey} ${valueLabel}`}
          type="number"
          step={definition.type === 'integer' ? 1 : 'any'}
          value={typeof value === 'number' ? value : ''}
          placeholder="沿用当前值 / 只读模板"
          onChange={(event) => onChange(event.target.value === '' ? undefined : Number(event.target.value))}
        />
      </label>
    )
  }
  if (definition.type === 'object' && definition.properties) {
    const objectValue = (typeof value === 'object' && value !== null && !Array.isArray(value)) ? value as Record<string, unknown> : {}
    return (
      <fieldset className="e2-schema-subfields">
        <legend>子属性</legend>
        {Object.entries(definition.properties).map(([childKey, childDefinition]) => (
          <div key={childKey}>
            <span>
              {childDefinition.ui_label_zh ?? childKey}
              {definition.required?.includes(childKey) && <b>必填</b>}
            </span>
            <SchemaValueEditor
              definition={childDefinition}
              fieldKey={`${fieldKey}.${childKey}`}
              value={objectValue[childKey]}
              valueLabel={valueLabel}
              onChange={(childValue) => {
                const next = { ...objectValue }
                if (isConfiguredValue(childValue)) next[childKey] = childValue
                else delete next[childKey]
                onChange(Object.keys(next).length ? next : undefined)
              }}
            />
          </div>
        ))}
      </fieldset>
    )
  }
  if (definition.type === 'array' && definition.items) {
    const arrayValue = Array.isArray(value) ? value : []
    return (
      <fieldset className="e2-schema-array">
        <legend>{valueLabel}</legend>
        {arrayValue.map((item, index) => (
          <div className="e2-schema-array__item" key={`${fieldKey}-${index}`}>
            <SchemaValueEditor
              definition={definition.items as E2CategorySchemaProperty}
              fieldKey={`${fieldKey}[${index}]`}
              value={item}
              valueLabel={`第 ${index + 1} 项`}
              onChange={(itemValue) => {
                const next = [...arrayValue]
                next[index] = itemValue
                onChange(next)
              }}
            />
            <button
              className="button button--quiet"
              type="button"
              aria-label={`${fieldKey} 删除第 ${index + 1} 项`}
              onClick={() => onChange(arrayValue.filter((_, itemIndex) => itemIndex !== index))}
            >
              删除
            </button>
          </div>
        ))}
        <button
          className="button button--secondary"
          type="button"
          aria-label={`${fieldKey} 添加一项`}
          onClick={() => onChange([...arrayValue, emptyValueForSchema(definition.items as E2CategorySchemaProperty)])}
        >
          添加一项
        </button>
      </fieldset>
    )
  }
  if (definition.type === 'array') {
    return (
      <div className="e2-schema-field__readonly">
        <span>此数组缺少可验证的子项 Schema</span>
        <small>为避免手写 JSON 绕过校验，只能继承；请先补齐后端 Schema。</small>
      </div>
    )
  }
  return (
    <label className="e2-schema-field__value">
      <span>{valueLabel}</span>
      <input
        aria-label={`${fieldKey} ${valueLabel}`}
        value={typeof value === 'string' ? value : ''}
        placeholder={definition.natural_language === true ? '只填英文；留空沿用当前值 / 模板' : '留空沿用当前值 / 只读模板'}
        onChange={(event) => onChange(event.target.value || undefined)}
      />
    </label>
  )
}

function emptyValueForSchema(definition: E2CategorySchemaProperty): unknown {
  if (definition.type === 'object') return {}
  if (definition.type === 'array') return []
  if (definition.type === 'boolean') return false
  if (definition.type === 'number' || definition.type === 'integer') return 0
  return ''
}
