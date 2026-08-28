import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

import { deleteJson, getJson, postJson, withDxmSessionBusyRetry } from '../../api'
import { useDxmShop } from '../../dxmShopContext'
import { normalizeSchemaValueForDefinition, resolveSchemaChoiceOptions } from '../../schemaValueEditor'
import type {
  DxmCategoryRecord,
  DxmDraftShop,
  DxmDraftShopsResponse,
  DxmTemplateRef,
  DxmTemplateRefSyncResult,
  DxmEditorCategoryModel,
  DxmEditorCategoryCapabilities,
  DxmEditorSectionTemplate,
  E2CategorySchema,
  E2CategorySchemaProperty,
  LocalPlanTemplate,
} from '../../types'
import { CategoryCascadePicker, categoryLabel } from './CategoryCascadePicker'

type LocalPlanWorkspaceProps = {
  plans: LocalPlanTemplate[]
  dxmTemplateRefs: DxmTemplateRef[]
  onChanged: () => void | Promise<void>
}

type SchemaFieldDraft = {
  uiLabelZh: string
  strategy: 'auto' | 'current' | 'template' | 'fill' | 'fixed'
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
  regional: '区域调价模板',
  module_property: '产品属性模板',
  module_template: '编辑页模块模板',
  module_package: '包装模块模板',
}

export function LocalPlanWorkspace({
  plans,
  dxmTemplateRefs,
  onChanged,
}: LocalPlanWorkspaceProps) {
  const {
    shops: contextShops,
    selectedShopId,
    setSelectedShopId,
  } = useDxmShop()
  const [fallbackShops, setFallbackShops] = useState<DxmDraftShop[]>([])
  const shops = contextShops.length ? contextShops : fallbackShops
  const [viewMode, setViewMode] = useState<'list' | 'edit'>('list')
  const [activeSection, setActiveSection] = useState('plan_setup')
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null)
  const [supersedesId, setSupersedesId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [version, setVersion] = useState('1.0.0')
  const [planPath, setPlanPath] = useState<'A' | 'B'>('A')
  const [shopId, setShopId] = useState('')
  const [categoryIdsText, setCategoryIdsText] = useState('')
  const [categoryRecords, setCategoryRecords] = useState<DxmCategoryRecord[]>([])
  const [categoryNames, setCategoryNames] = useState<Record<string, string>>({})
  const [categorySchemas, setCategorySchemas] = useState<Record<string, E2CategorySchema>>({})
  const [editorModels, setEditorModels] = useState<Record<string, DxmEditorCategoryModel>>({})
  const [categoryCapabilities, setCategoryCapabilities] = useState<Record<string, DxmEditorCategoryCapabilities>>({})
  const [syncedRefs, setSyncedRefs] = useState<DxmTemplateRef[]>([])
  const [fieldDrafts, setFieldDrafts] = useState<SchemaFieldDrafts>({})
  const [selectedRefIds, setSelectedRefIds] = useState<number[]>([])
  const [provenance, setProvenance] = useState('operator_reviewed_local_plan')
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [syncingRefs, setSyncingRefs] = useState(false)
  const [syncingFieldKey, setSyncingFieldKey] = useState<string | null>(null)
  const [descriptionEditorOpen, setDescriptionEditorOpen] = useState(false)
  const [descriptionStep, setDescriptionStep] = useState<'idle' | 'generated' | 'confirmed' | 'saved'>('idle')
  const [marketingImagesEnabled, setMarketingImagesEnabled] = useState(false)
  const [semiCountries, setSemiCountries] = useState<string[]>([])
  const [semiGoodsConfig, setSemiGoodsConfig] = useState({
    original_box: '',
    logistics_attribute: '',
    weight: '',
    length: '',
    width: '',
    height: '',
  })
  const [semiVariantConfig, setSemiVariantConfig] = useState({
    product_price: '',
    sku_code_strategy: '',
    goods_code_strategy: '',
    barcode_strategy: '',
    jit_stock: '',
  })
  const [planPendingArchive, setPlanPendingArchive] = useState<LocalPlanTemplate | null>(null)

  const activePlans = useMemo(
    () => plans.filter((plan) => plan.is_active && (!selectedShopId || plan.shop_id === selectedShopId)),
    [plans, selectedShopId],
  )
  const archivedPlans = useMemo(
    () => plans.filter((plan) => !plan.is_active && (!selectedShopId || plan.shop_id === selectedShopId)),
    [plans, selectedShopId],
  )
  const selectedPlan = useMemo(
    () => plans.find((plan) => plan.id === selectedPlanId
      && (!selectedShopId || plan.shop_id === selectedShopId)) ?? null,
    [plans, selectedPlanId, selectedShopId],
  )
  const selectedCategoryIds = parseLooseCategoryIds(categoryIdsText)
  const selectedCategories = useMemo(
    () => selectedCategoryIds.map((categoryId) => (
      categoryRecords.find((record) => record.categoryId === categoryId) ?? {
        categoryId,
        nameZh: categoryNames[categoryId],
      }
    )),
    [categoryNames, categoryRecords, selectedCategoryIds],
  )
  const effectiveRefs = useMemo(() => {
    const byId = new Map<number, DxmTemplateRef>()
    dxmTemplateRefs.forEach((ref) => byId.set(ref.id, ref))
    syncedRefs.forEach((ref) => byId.set(ref.id, ref))
    return [...byId.values()]
  }, [dxmTemplateRefs, syncedRefs])
  const availableRefs = effectiveRefs.filter((ref) => (
    ref.availability === 'available'
    && (!shopId || ref.shop_id === shopId)
    && (!ref.category_id || selectedCategoryIds.includes(ref.category_id))
  ))
  const editorCategoryIds = selectedCategoryIds.filter((categoryId) => editorModels[categoryId])
  const activeEditorCategoryId = editorCategoryIds[0]
  const activeEditorModel = activeEditorCategoryId ? editorModels[activeEditorCategoryId] : undefined
  const semiManagedAvailability = resolveSemiManagedAvailability(
    activeEditorCategoryId ? categoryCapabilities[activeEditorCategoryId] : undefined,
  )
  const editorSections = (activeEditorModel?.sections ?? []).filter(
    (section) => section.code !== 'semi_managed' || planPath === 'B',
  )

  // Standalone contract pages may render without App's provider.  Keep a
  // read-only fallback there; the desktop App always prefers its account-bound
  // global shop list.
  useEffect(() => {
    if (contextShops.length) return
    void getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops')
      .then((response) => {
        setFallbackShops(response.shops)
        setShopId((current) => current || selectedShopId || response.shops[0]?.id || '')
      })
      .catch(() => undefined)
  }, [contextShops.length, selectedShopId])

  useEffect(() => {
    if (selectedShopId && selectedShopId !== shopId) setShopId(selectedShopId)
  }, [selectedShopId, shopId])

  useEffect(() => {
    if (!selectedShopId || selectedPlanId == null) return
    const plan = plans.find((candidate) => candidate.id === selectedPlanId)
    if (plan && plan.shop_id !== selectedShopId) {
      setSelectedPlanId(null)
      setSupersedesId(null)
      setViewMode('list')
      setMessage({ tone: 'error', text: '当前店铺已切换，已关闭上一店铺的方案编辑。' })
    }
  }, [plans, selectedPlanId, selectedShopId])

  function openCreate() {
    setViewMode('edit')
    setActiveSection('plan_setup')
    setSelectedPlanId(null)
    setSupersedesId(null)
    setName('')
    setVersion('1.0.0')
    setPlanPath('A')
    setShopId(selectedShopId || (shops[0]?.id ?? ''))
    setCategoryIdsText('')
    setCategoryRecords([])
    setCategorySchemas({})
    setEditorModels({})
    setSyncedRefs([])
    setFieldDrafts({})
    setSelectedRefIds([])
    setDescriptionStep('idle')
    setMarketingImagesEnabled(false)
    setSemiCountries([])
    setSemiGoodsConfig({ original_box: '', logistics_attribute: '', weight: '', length: '', width: '', height: '' })
    setSemiVariantConfig({ product_price: '', sku_code_strategy: '', goods_code_strategy: '', barcode_strategy: '', jit_stock: '' })
    setMessage(null)
  }

  function openEditForPlan(plan: LocalPlanTemplate) {
    setViewMode('edit')
    setActiveSection('plan_setup')
    setSelectedPlanId(plan.id)
    setSupersedesId(null)
    setName(plan.name)
    setVersion(plan.version)
    setPlanPath(plan.path)
    setShopId(plan.shop_id)
    if (plan.shop_id !== selectedShopId) setSelectedShopId(plan.shop_id)
    setCategoryIdsText(plan.category_ids.join(', '))
    setCategoryRecords(plan.category_ids.map((categoryId) => ({ categoryId })))
    setCategorySchemas({})
    setEditorModels({})
    setSyncedRefs([])
    setSelectedRefIds(plan.dxm_template_refs.map((binding) => binding.ref_id))
    setProvenance(plan.provenance)
    setDescriptionStep(plan.category_ids.some((categoryId) => plan.editor_actions?.[categoryId]?.description) ? 'saved' : 'idle')
    setMarketingImagesEnabled(plan.category_ids.some((categoryId) => Boolean(plan.editor_actions?.[categoryId]?.marketing_images)))
    setSemiCountries((plan.semi_managed?.countries ?? []).map(String))
    setSemiGoodsConfig((current) => ({ ...current, ...(plan.semi_managed?.goods_config ?? {}) } as typeof current))
    setSemiVariantConfig((current) => ({ ...current, ...(plan.semi_managed?.variant_config ?? {}) } as typeof current))
    setMessage(plan.category_ids.length === 1 ? null : {
      tone: 'error',
      text: '这是旧版多类目方案，只能查看。请按每个类目分别新建方案，系统不会静默丢弃旧规则。',
    })
    void hydrateCategoryNames(plan.category_ids)
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

  function addCategory(record: DxmCategoryRecord) {
    setCategoryIdsText(record.categoryId)
    setCategoryRecords([record])
    setCategoryNames({ [record.categoryId]: categoryLabel(record) })
    setCategorySchemas({})
    setEditorModels({})
    setCategoryCapabilities({})
    setFieldDrafts({})
    setSelectedRefIds([])
    setDescriptionStep('idle')
    setMarketingImagesEnabled(false)
    setSemiCountries([])
    setSemiGoodsConfig({ original_box: '', logistics_attribute: '', weight: '', length: '', width: '', height: '' })
    setSemiVariantConfig({ product_price: '', sku_code_strategy: '', goods_code_strategy: '', barcode_strategy: '', jit_stock: '' })
    setMessage({ tone: 'success', text: '已选择一个末级类目。请读取该类目的真实字段、选项与模板。' })
  }

  function removeCategory(categoryId: string) {
    if (!selectedCategoryIds.includes(categoryId)) return
    setCategoryIdsText('')
    setCategoryRecords([])
    setCategoryNames({})
    setCategorySchemas({})
    setEditorModels({})
    setCategoryCapabilities({})
    setFieldDrafts({})
    setSelectedRefIds([])
    setDescriptionStep('idle')
    setMarketingImagesEnabled(false)
    setSemiCountries([])
    setSemiGoodsConfig({ original_box: '', logistics_attribute: '', weight: '', length: '', width: '', height: '' })
    setSemiVariantConfig({ product_price: '', sku_code_strategy: '', goods_code_strategy: '', barcode_strategy: '', jit_stock: '' })
  }

  function changePlanShop(nextShopId: string) {
    if (nextShopId === shopId) return
    setShopId(nextShopId)
    setSelectedShopId(nextShopId)
    setCategoryIdsText('')
    setCategoryRecords([])
    setCategoryNames({})
    setCategorySchemas({})
    setEditorModels({})
    setCategoryCapabilities({})
    setSyncedRefs([])
    setSelectedRefIds([])
    setFieldDrafts({})
    setDescriptionStep('idle')
    setMarketingImagesEnabled(false)
    setSemiCountries([])
    setSemiGoodsConfig({ original_box: '', logistics_attribute: '', weight: '', length: '', width: '', height: '' })
    setSemiVariantConfig({ product_price: '', sku_code_strategy: '', goods_code_strategy: '', barcode_strategy: '', jit_stock: '' })
    setMessage({ tone: 'success', text: '店铺已切换。适用类目、字段与模板已清空，请按新店铺重新选择。' })
  }

  async function hydrateCategoryNames(categoryIds: string[]) {
    const unresolved = categoryIds.filter((categoryId) => !categoryNames[categoryId])
    if (!unresolved.length) return
    const resolved = await Promise.all(unresolved.map(async (categoryId) => {
      try {
        return await withDxmSessionBusyRetry(
          () => getJson<DxmCategoryRecord | null>(`/api/dxm/category/get?category_id=${encodeURIComponent(categoryId)}`),
        )
      } catch {
        return null
      }
    }))
    const found = resolved.filter((record): record is DxmCategoryRecord => record !== null)
    if (!found.length) return
    setCategoryRecords((current) => {
      const byId = new Map(current.map((record) => [record.categoryId, record]))
      found.forEach((record) => byId.set(record.categoryId, record))
      return [...byId.values()]
    })
    setCategoryNames((current) => ({
      ...current,
      ...Object.fromEntries(found.map((record) => [record.categoryId, categoryLabel(record)])),
    }))
  }

  async function syncReadonlyRefs(fieldKey?: string) {
    const normalizedShopId = shopId.trim()
    if (!/^[1-9][0-9]*$/.test(normalizedShopId)) {
      setMessage({ tone: 'error', text: '请先选择店铺。' })
      return
    }
    setSyncingRefs(true)
    setSyncingFieldKey(fieldKey ?? null)
    setMessage(null)
    try {
      const syncIds = selectedCategoryIds
      if (syncIds.length !== 1) {
        throw new Error('一个普货方案必须且只能选择一个末级类目。')
      }
      const names = Object.fromEntries(selectedCategories.map((record) => [record.categoryId, categoryLabel(record)]))
      setCategoryNames((current) => ({ ...current, ...names }))
      const result = await withDxmSessionBusyRetry(
        () => postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync', {
          shop_id: normalizedShopId,
          category_ids: syncIds,
        }),
      )
      setCategorySchemas(result.category_schemas)
      setEditorModels(result.editor_models)
      setCategoryCapabilities(result.category_capabilities ?? {})
      setSyncedRefs(result.refs)
      const baseDrafts = fieldKey
        ? mergeFieldDrafts(result.category_schemas, fieldDrafts)
        : buildFieldDrafts(result.category_schemas, selectedPlan)
      setFieldDrafts(hydrateSelectedTemplateValues(
        result.category_schemas,
        result.editor_models,
        selectedRefIds,
        baseDrafts,
      ))
      await onChanged()
      setMessage({
        tone: 'success',
        text: fieldKey
          ? `已刷新「${fieldKey}」对应接口选项；已保留当前方案中已填写的内容。`
          : `已读取当前类目的真实字段、接口选项与 ${result.refs.length} 条分区模板。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '店小秘只读同步失败。',
      })
    } finally {
      setSyncingRefs(false)
      setSyncingFieldKey(null)
    }
  }

  async function savePlan() {
    setSubmitting(true)
    setMessage(null)
    try {
      const categoryIds = parseLooseCategoryIds(categoryIdsText)
      if (!name.trim()) throw new Error('请填写方案名称。')
      if (!/^[1-9][0-9]*$/.test(shopId.trim())) throw new Error('请选择店铺。')
      if (categoryIds.length !== 1) throw new Error('一个普货方案必须且只能选择一个末级类目。')
      if (planPath === 'B' && semiManagedAvailability === 'unsupported') {
        throw new Error('当前店铺的半托管资格未通过只读接口确认，不能保存 Path B 方案。')
      }
      const missingSchemas = categoryIds.filter((categoryId) => !categorySchemas[categoryId])
      if (missingSchemas.length) {
        throw new Error(`有 ${missingSchemas.length} 个已选类目的字段定义尚未读取。请点击「读取类目字段与模板」后再创建方案。`)
      }
      const { fillRules, fixedFieldValues, fieldMappings, sourcePolicies } = buildStructuredPlanFields(
        categoryIds,
        categorySchemas,
        fieldDrafts,
        planPath,
      )
      const refs = selectedRefIds.map((refId) => {
        const ref = availableRefs.find((candidate) => candidate.id === refId)
        if (!ref) throw new Error(`只读引用 #${refId} 已漂移或不可用`)
        return { ref_id: ref.id, source_digest: ref.source_digest }
      })
      const semiManagedComplete = planPath === 'B'
        && semiCountries.length > 0
        && Object.values(semiGoodsConfig).every((value) => String(value).trim())
        && Object.values(semiVariantConfig).every((value) => String(value).trim())
      const body = {
        name: name.trim(),
        version: (supersedesId ? version.trim() : '1.0.0') || '1.0.0',
        shop_id: shopId.trim(),
        category_ids: categoryIds,
        scope_contract: 'single_target_category.v2',
        path: planPath,
        fixed_values: { publish_allowed: false, field_values: fixedFieldValues },
        fill_rules: fillRules,
        dxm_template_refs: refs,
        field_mappings: fieldMappings,
        source_policies: sourcePolicies,
        configuration_contract: 'local_plan_template.v3',
        status: planPath === 'B' && !semiManagedComplete ? 'draft' : 'ready',
        source_snapshots: {
          category_ids: categoryIds,
          schema_categories: Object.keys(categorySchemas),
          template_ref_ids: selectedRefIds,
        },
        ...(planPath === 'B' ? {
          semi_managed: {
            enabled: true,
            countries: semiCountries,
            goods_config: semiGoodsConfig,
            variant_config: semiVariantConfig,
            source_snapshot: {
              shop_id: shopId,
              category_id: categoryIds[0],
            },
          },
        } : {}),
        ...((descriptionStep === 'saved' || marketingImagesEnabled) ? { editor_actions: {
          [categoryIds[0]]: {
            ...(descriptionStep === 'saved' ? {
            description: {
              editor: 'new',
              generate_mobile_from_pc: true,
              confirm_before_save: true,
            },
            } : {}),
            ...(marketingImagesEnabled ? {
              marketing_images: {
                generate_from_product_images: true,
                required_slots: ['1:1_white_background', '3:4_scene'],
              },
            } : {}),
          },
        } } : {}),
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

  async function archivePlan(plan: LocalPlanTemplate) {
    if (!plan.is_active) return
    setSubmitting(true)
    setMessage(null)
    try {
      await deleteJson<LocalPlanTemplate>(`/api/local-plan-templates/${plan.id}`)
      await onChanged()
      if (selectedPlanId === plan.id) setViewMode('list')
      setMessage({ tone: 'success', text: `已删除方案「${plan.name}」。已开始的任务不受影响。` })
      setPlanPendingArchive(null)
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '方案删除失败。',
      })
    } finally {
      setSubmitting(false)
    }
  }

  function selectSectionTemplate(categoryId: string, options: DxmEditorSectionTemplate[], rawRefId: string) {
    const optionIds = new Set(options.map((option) => option.ref_id))
    const nextRefId = rawRefId ? Number(rawRefId) : null
    setSelectedRefIds((current) => [
      ...current.filter((refId) => !optionIds.has(refId)),
      ...(nextRefId == null ? [] : [nextRefId]),
    ])
    const coveredFields = new Set(options.flatMap((option) => option.resolved_field_keys))
    const selected = nextRefId == null ? null : options.find((option) => option.ref_id === nextRefId) ?? null
    setFieldDrafts((current) => {
      const categoryDrafts = { ...(current[categoryId] ?? {}) }
      for (const fieldKey of coveredFields) {
        const previous = categoryDrafts[fieldKey]
        if (previous && (previous.strategy === 'fill' || previous.strategy === 'fixed')) continue
        categoryDrafts[fieldKey] = {
          ...(previous ?? { uiLabelZh: '', strategy: 'auto' as const, value: undefined }),
          strategy: 'template',
          value: undefined,
        }
      }
      for (const [fieldKey, value] of Object.entries(selected?.resolved_values ?? {})) {
        const previous = categoryDrafts[fieldKey]
        if (previous && (previous.strategy === 'fill' || previous.strategy === 'fixed')) continue
        const definition = categorySchemas[categoryId]?.properties[fieldKey]
        categoryDrafts[fieldKey] = {
          ...(previous ?? { uiLabelZh: '', strategy: 'auto' as const, value: undefined }),
          strategy: 'template',
          value: definition ? normalizeSchemaValueForDefinition(definition, value) : value,
        }
      }
      return { ...current, [categoryId]: categoryDrafts }
    })
    setMessage(selected ? {
      tone: 'success',
      text: `已应用「${selected.display_name || '店小秘模板'}」；模板中的 ${Object.keys(selected.resolved_values ?? {}).length} 个值已回填到当前分区。`,
    } : null)
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
          ...(current[categoryId]?.[fieldKey] ?? { uiLabelZh: '', strategy: 'auto', value: undefined }),
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
        {message && (
          <div className={message.tone === 'success' ? 'draft-selection-notice' : 'draft-selection-alert'} role="status">
            {message.text}
          </div>
        )}
        {activePlans.length ? (
          <div className="local-plan-cards">
            {activePlans.map((plan) => (
              <article
                key={plan.id}
                className="local-plan-card"
              >
                <button type="button" className="local-plan-card__open" onClick={() => openEditForPlan(plan)}>
                  <strong>{plan.name}</strong>
                  <span>{shopLabel(plan.shop_id, shops)} · {plan.category_ids.length === 1 ? '单类目' : `${plan.category_ids.length} 个旧版类目`} · 10 个店小秘主编辑分区 · 引用 {plan.dxm_template_refs.length} 个模板</span>
                  <small>上次更新 {plan.updated_at.replace('T', ' ').slice(0, 16)}</small>
                </button>
                <button
                  className="button button--quiet local-plan-card__delete"
                  type="button"
                  disabled={submitting}
                  onClick={() => setPlanPendingArchive(plan)}
                >
                  删除方案
                </button>
              </article>
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
                <article
                  key={plan.id}
                  className="local-plan-card"
                >
                  <button type="button" className="local-plan-card__open" onClick={() => openEditForPlan(plan)}>
                    <strong>{plan.name}</strong>
                    <span>{shopLabel(plan.shop_id, shops)}</span>
                    <small>已删除 · 可查看但不能再用于新任务</small>
                  </button>
                </article>
              ))}
            </div>
          </details>
        )}
        {planPendingArchive && (
          <ArchiveConfirmation
            plan={planPendingArchive}
            submitting={submitting}
            onCancel={() => setPlanPendingArchive(null)}
            onConfirm={() => { void archivePlan(planPendingArchive) }}
          />
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
              <button className="button button--quiet" type="button" disabled={submitting} onClick={() => setPlanPendingArchive(selectedPlan)}>删除</button>
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
          <nav className="lp-sections-nav" aria-label="店小秘编辑分区">
            <button
              type="button"
              className={activeSection === 'plan_setup' ? 'is-active' : ''}
              onClick={() => setActiveSection('plan_setup')}
            >
              <span>方案设置</span>
              {!name.trim() && <b>·</b>}
            </button>
            {editorSections.map((section) => {
              const count = section.field_keys.length + section.templates.length
              return (
                <button
                  key={section.code}
                  type="button"
                  className={activeSection === section.code ? 'is-active' : ''}
                  onClick={() => setActiveSection(section.code)}
                >
                  <span>{section.label}</span>
                  {count > 0 ? <small>{count}</small> : null}
                </button>
              )
            })}
            {planPath === 'B' && (
              <button
                type="button"
                className={activeSection === 'semi_managed' ? 'is-active' : ''}
                onClick={() => setActiveSection('semi_managed')}
              >
                <span>半托管二段页</span>
                <small>{semiCountries.length}</small>
              </button>
            )}
          </nav>

          <div className="lp-section-form">
            {activeSection === 'plan_setup' && (
              <div className="lp-form-block">
                <label className="lp-field">
                  <span>方案名称</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 Funload 普货只保存" />
                </label>
                <label className="lp-field">
                  <span>店铺</span>
                  <select value={shopId} onChange={(event) => changePlanShop(event.target.value)}>
                    {!shops.length && <option value={shopId}>{shopId || '请先连接店小秘'}</option>}
                    {shops.map((shop) => (
                      <option key={shop.id} value={shop.id}>{shop.name}</option>
                    ))}
                  </select>
                </label>
                <fieldset className="lp-path-choice">
                  <legend>编辑路径</legend>
                  <label className={planPath === 'A' ? 'is-selected' : ''}>
                    <input type="radio" name="plan-path" checked={planPath === 'A'} onChange={() => setPlanPath('A')} />
                    <span><strong>仅店小秘主编辑页</strong><small>Path A · 当前已放行真实只保存</small></span>
                  </label>
                  <label className={planPath === 'B' ? 'is-selected' : ''}>
                    <input
                      type="radio"
                      name="plan-path"
                      checked={planPath === 'B'}
                      disabled={semiManagedAvailability === 'unsupported' && planPath !== 'B'}
                      onChange={() => setPlanPath('B')}
                    />
                    <span><strong>主编辑页 + 半托管</strong><small>Path B · 可配置；真实批量执行仍需单独验收</small></span>
                  </label>
                  {planPath === 'B' && (
                    <p className={semiManagedAvailability === 'unsupported' ? 'lp-path-choice__warning' : undefined}>
                      {semiManagedAvailability === 'unsupported'
                        ? '当前店铺的只读资格接口未证明支持半托管，不能保存为可执行 Path B。'
                        : semiManagedAvailability === 'unknown'
                          ? '尚未读取当前类目的半托管资格；同步后才会显示是否可用。'
                          : '半托管作为编辑路径参与方案，但不会伪装成店小秘主编辑页的额外分区；相关字段仍按独立执行合同验收。'}
                    </p>
                  )}
                </fieldset>
                <div className="lp-field">
                  <div className="local-plan-categories__head">
                    <span>方案类目（仅 1 个）</span>
                    <button className="button button--quiet" type="button" disabled={!shopId || !selectedCategoryIds.length || syncingRefs} onClick={() => { void syncReadonlyRefs() }}>
                      {syncingRefs ? '正在读取…' : '读取类目字段与模板'}
                    </button>
                  </div>
                  <CategoryCascadePicker
                    selectedCategories={selectedCategories}
                    disabled={syncingRefs || submitting}
                    onAdd={addCategory}
                    onRemove={removeCategory}
                  />
                  <small className="lp-category-help">一个方案绑定一个末级类目。重新选择类目会替换原类目，并清空上一类目的字段与模板配置。</small>
                </div>
              </div>
            )}

            {activeSection === 'semi_managed' && planPath === 'B' && (
              <SemiManagedConfig
                countries={semiCountries}
                goodsConfig={semiGoodsConfig}
                variantConfig={semiVariantConfig}
                onCountriesChange={setSemiCountries}
                onGoodsConfigChange={setSemiGoodsConfig}
                onVariantConfigChange={setSemiVariantConfig}
                countryOptions={resolveSemiCountryOptions(activeEditorModel?.category_id, categoryCapabilities)}
                logisticsOptions={resolveSemiLogisticsOptions(activeEditorModel?.category_id, categoryCapabilities)}
              />
            )}

            {activeSection !== 'plan_setup' && activeSection !== 'semi_managed' && (
              <div className="lp-form-block">
                <div className="e2-structured-plan__head">
                  <span>
                    <strong>{activeEditorModel?.sections.find((section) => section.code === activeSection)?.label}</strong>
                    <small>{activeEditorModel?.sections.find((section) => section.code === activeSection)?.help} 分区、字段和模板均来自本次店小秘接口 JSON。</small>
                  </span>
                </div>
                {Object.keys(categorySchemas).length ? (
                  <div className="lp-split">
                    <div className="lp-split__content" role="tabpanel">
                      {(() => {
                        const availableCategoryIds = selectedCategoryIds.filter((c) => categorySchemas[c] && editorModels[c])
                        const categoryId = availableCategoryIds[0]
                        if (!categoryId) return null
                        const schema = categorySchemas[categoryId]
                        if (!schema) return null
                        const section = editorModels[categoryId].sections.find((item) => item.code === activeSection)
                        if (!section) return null
                        const activeFields = section.field_keys
                          .map((fieldKey) => [fieldKey, schema.properties[fieldKey]] as const)
                          .filter((entry): entry is readonly [string, E2CategorySchemaProperty] => Boolean(entry[1]))
                        return (
                          <section className="e2-category-fields" aria-label={`类目 ${categoryId} 字段`}>
                            <header>
                              <span>
                                <strong>{displayPlanCategoryName(categoryId, categoryNames)}</strong>
                                <small>{activeFields.length} 个配置项 · {activeFields.filter(([fieldKey]) => schema.required.includes(fieldKey)).length} 个必填</small>
                              </span>
                            </header>
                            {section.templates.length > 0 && (
                              <div className="e2-section-templates">
                                <div className="e2-section-templates__head">
                                  <strong>本分区可用模板</strong>
                                  <small>选择后立即带入模板值；保存方案不会修改店小秘中的原模板。</small>
                                </div>
                                <div className="e2-section-templates__list">
                                  {Object.entries(groupSectionTemplates(section.templates)).map(([refType, options]) => {
                                    const selected = options.find((option) => selectedRefIds.includes(option.ref_id))
                                    const label = REF_TYPE_LABELS[refType as DxmTemplateRef['ref_type']]
                                    const mappedEntries = selected
                                      ? Object.entries(selected.resolved_values ?? {})
                                        .filter(([fieldKey]) => Boolean(schema.properties[fieldKey]))
                                      : []
                                    return (
                                      <div key={refType} className="e2-section-template-control">
                                        <label className="e2-section-template-select">
                                          <span>{label}</span>
                                          <select
                                            aria-label={`${label} 模板选择`}
                                            value={selected?.ref_id ?? ''}
                                            onChange={(event) => selectSectionTemplate(categoryId, options, event.target.value)}
                                          >
                                            <option value="">请选择店小秘中的{label}</option>
                                            {options.map((template) => (
                                              <option key={template.ref_id} value={template.ref_id}>
                                                {template.display_name || `模板 ${template.dxm_template_id}`}
                                                {template.coverage_state === 'none'
                                                  ? '（仅身份引用，未返回可回填字段）'
                                                  : template.coverage_state === 'partial'
                                                    ? `（已映射 ${template.resolved_field_count ?? template.resolved_field_keys.length} 个字段，另有 ${template.unmapped_field_keys?.length ?? 0} 个字段未映射）`
                                                    : template.resolved_field_keys.length > 0
                                                      ? `（覆盖 ${template.resolved_field_keys.length} 个字段）`
                                                      : ''}
                                              </option>
                                            ))}
                                          </select>
                                        </label>
                                        {selected && (
                                          <TemplateAppliedSummary
                                            template={selected}
                                            entries={mappedEntries}
                                            schema={schema}
                                          />
                                        )}
                                      </div>
                                    )
                                  })}
                                </div>
                              </div>
                            )}
                            {section.widgets?.some((widget) => widget.kind === 'description_editor') && (
                              <div className="e2-description-workflow">
                                <div>
                                  <strong>描述</strong>
                                  <span>使用店小秘新版编辑器，并根据 PC 端描述生成移动端描述。</span>
                                </div>
                                <button
                                  className="button button--secondary"
                                  type="button"
                                  onClick={() => setDescriptionEditorOpen(true)}
                                >
                                  {descriptionStep === 'saved' ? '已配置 · 重新查看' : '使用新版编辑器'}
                                </button>
                              </div>
                            )}
                            {section.widgets?.some((widget) => widget.kind === 'marketing_image_generator') && (
                              <div className="e2-marketing-workflow">
                                <div>
                                  <strong>营销图片</strong>
                                  <span>执行时使用每件商品的主图，生成 1:1 白底图和 3:4 场景图。</span>
                                </div>
                                <button
                                  className={marketingImagesEnabled ? 'button button--success' : 'button button--secondary'}
                                  type="button"
                                  aria-pressed={marketingImagesEnabled}
                                  onClick={() => setMarketingImagesEnabled((current) => !current)}
                                >
                                  {marketingImagesEnabled ? '已配置一键生成' : '一键生成'}
                                </button>
                              </div>
                            )}
                            {activeFields.length ? (
                              <div className="e2-category-fields__rows">
                              {activeFields.map(([fieldKey, definition], index) => {
                                const draft = fieldDrafts[categoryId]?.[fieldKey]
                                const required = schema.required.includes(fieldKey)
                                const isPathSwitch = fieldKey === 'isJoinChoice'
                                const effectiveValue = isPathSwitch ? planPath === 'B' : draft?.value
                                const selectedTemplate = section.templates.find(
                                  (template) => selectedRefIds.includes(template.ref_id)
                                    && template.resolved_field_keys.includes(fieldKey),
                                )
                                return (
                                    <DirectSchemaField
                                    key={fieldKey}
                                    definition={definition}
                                    fieldKey={fieldKey}
                                    label={schemaLabel(definition, index)}
                                    required={required}
                                    inheritedLabel={fieldKey === 'title' ? '留空时沿用每件商品的原标题' : undefined}
                                    readOnlyValue={fieldKey === 'shopName'
                                      ? shopLabel(shopId, shops)
                                      : fieldKey === 'categoryId'
                                        ? displayPlanCategoryName(categoryId, categoryNames)
                                        : undefined}
                                    templateName={selectedTemplate?.display_name}
                                    value={effectiveValue}
                                    pathValue={isPathSwitch ? planPath === 'B' : undefined}
                                    syncing={syncingFieldKey === fieldKey}
                                    onSync={activeSection !== 'attribute_info' && definition.option_source ? () => { void syncReadonlyRefs(fieldKey) } : undefined}
                                    onChange={(value) => updateFieldDraft(categoryId, fieldKey, {
                                      strategy: isConfiguredValue(value) ? 'fill' : 'current',
                                      value,
                                    })}
                                  />
                                )
                              })}
                              </div>
                            ) : (
                              <div className="e2-category-fields__empty">
                                {section.templates.length
                                  ? '当前分区由模板选择驱动，本次接口没有返回可单独补差的字段。'
                                  : '当前类目的店小秘接口没有返回这个分区的可配置字段或模板；系统不会伪造内容。'}
                              </div>
                            )}
                          </section>
                        )
                      })()}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">
                    <strong>编辑页 JSON 待同步</strong>
                    <span>返回「方案设置」同步当前店铺与类目后，系统才会生成分区、字段和模板。</span>
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
        {(syncingRefs || submitting) && (
          <div className="lp-busy-indicator" role="status" aria-live="polite">
            <span className="ui-spinner" aria-hidden="true" />
            <span>{syncingRefs ? '正在读取店小秘类目字段与模板…' : '正在校验并保存方案…'}</span>
          </div>
        )}
      </div>
      {planPendingArchive && (
        <ArchiveConfirmation
          plan={planPendingArchive}
          submitting={submitting}
          onCancel={() => setPlanPendingArchive(null)}
          onConfirm={() => { void archivePlan(planPendingArchive) }}
        />
      )}
      {descriptionEditorOpen && (
        <div className="lp-description-overlay" role="dialog" aria-modal="true" aria-labelledby="description-editor-title">
          <div className="lp-description-dialog">
            <header>
              <div>
                <span>执行动作配置</span>
                <h3 id="description-editor-title">新版描述编辑器流程</h3>
              </div>
              <button className="button button--quiet" type="button" onClick={() => setDescriptionEditorOpen(false)}>关闭</button>
            </header>
            <div className="lp-description-dialog__canvas">
              <aside>
                <strong>配置说明</strong>
                <span>这里只保存动作合同</span>
                <span>不会在控制台伪造编辑结果</span>
              </aside>
              <main>
                <strong>执行时按真实店小秘页面完成以下动作</strong>
                <p>批量保存阶段才会打开真实编辑页：进入新版编辑器 → 根据 PC 端描述一键生成 → 人工确认生成结果 → 点击保存。</p>
                <ol className="lp-description-dialog__contract-list">
                  <li>进入真实“新版编辑器”</li>
                  <li>点击“根据 PC 端描述一键生成”</li>
                  <li>读取生成结果并执行确认门禁</li>
                  <li>点击“保存”，再做页面与回包读回</li>
                </ol>
                <label className="lp-description-dialog__enable">
                  <input
                    type="checkbox"
                    checked={descriptionStep === 'saved'}
                    onChange={(event) => setDescriptionStep(event.target.checked ? 'saved' : 'idle')}
                  />
                  <span>启用这组描述动作（不启用则沿用商品当前描述）</span>
                </label>
              </main>
            </div>
            <footer>
              <button className="button button--primary" type="button" onClick={() => setDescriptionEditorOpen(false)}>
                保存动作配置
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>,
    document.body,
  )
}

function shopLabel(shopId: string, shops: DxmDraftShop[]) {
  return shops.find((shop) => shop.id === shopId)?.name ?? `店铺 ${shopId}`
}

function ArchiveConfirmation({
  plan,
  submitting,
  onCancel,
  onConfirm,
}: {
  plan: LocalPlanTemplate
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div className="lp-confirm-overlay" role="alertdialog" aria-modal="true" aria-labelledby="archive-plan-title">
      <div className="lp-confirm-dialog">
        <span className="lp-confirm-dialog__icon" aria-hidden="true">!</span>
        <div>
          <h3 id="archive-plan-title">删除方案「{plan.name}」？</h3>
          <p>方案会移入“已删除”，不能再用于新任务；已经开始的保存任务不受影响。</p>
        </div>
        <div className="lp-confirm-dialog__actions">
          <button className="button button--quiet" type="button" disabled={submitting} onClick={onCancel}>取消</button>
          <button className="button button--danger" type="button" disabled={submitting} onClick={onConfirm}>
            {submitting ? '正在删除…' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}

type SemiManagedConfigProps = {
  countries: string[]
  goodsConfig: { original_box: string; logistics_attribute: string; weight: string; length: string; width: string; height: string }
  variantConfig: { product_price: string; sku_code_strategy: string; goods_code_strategy: string; barcode_strategy: string; jit_stock: string }
  onCountriesChange: (value: string[]) => void
  onGoodsConfigChange: (value: SemiManagedConfigProps['goodsConfig']) => void
  onVariantConfigChange: (value: SemiManagedConfigProps['variantConfig']) => void
  countryOptions: Array<{ value: string; label: string }>
  logisticsOptions: Array<{ value: string; label: string }>
}

function SemiManagedConfig({
  countries,
  goodsConfig,
  variantConfig,
  onCountriesChange,
  onGoodsConfigChange,
  onVariantConfigChange,
  countryOptions,
  logisticsOptions,
}: SemiManagedConfigProps) {
  const setGoods = (key: keyof SemiManagedConfigProps['goodsConfig'], value: string) => {
    onGoodsConfigChange({ ...goodsConfig, [key]: value })
  }
  const setVariant = (key: keyof SemiManagedConfigProps['variantConfig'], value: string) => {
    onVariantConfigChange({ ...variantConfig, [key]: value })
  }
  const fallbackCountryOptions = countries.map((value) => ({ value, label: value }))
  return (
    <div className="lp-form-block semi-managed-config">
      <div className="e2-structured-plan__head">
        <span>
          <strong>半托管二段页配置</strong>
          <small>这里保存执行规则；真实运行时才进入店小秘 editFromSmt 页面填写并保存。</small>
        </span>
        <span className="semi-managed-config__badge">Path B · 独立配置</span>
      </div>
      <section className="semi-managed-config__section">
        <h3>参加国家</h3>
        <p>必须明确选择国家，不默认全选；选项来自当前店铺和类目的半托管接口。</p>
        <SearchableMultiSelect
          label="参加国家"
          options={countryOptions.length ? countryOptions : fallbackCountryOptions}
          value={countries}
          onChange={onCountriesChange}
        />
        {!countryOptions.length && <small className="semi-managed-config__warning">当前还没有读取到国家选项；请先同步店铺半托管能力，不能用文本猜测国家。</small>}
      </section>
      <section className="semi-managed-config__section">
        <h3>货品信息</h3>
        <div className="semi-managed-config__grid">
          <label><span>是否原箱</span><select value={goodsConfig.original_box} onChange={(event) => setGoods('original_box', event.target.value)}><option value="">请选择</option><option value="true">是</option><option value="false">否</option></select></label>
          <label><span>物流属性</span>{logisticsOptions.length ? (
            <select value={goodsConfig.logistics_attribute} onChange={(event) => setGoods('logistics_attribute', event.target.value)}>
              <option value="">请选择已同步的物流属性</option>
              {logisticsOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select>
          ) : <input value={goodsConfig.logistics_attribute} disabled placeholder="未读取到真实物流属性选项" onChange={(event) => setGoods('logistics_attribute', event.target.value)} />}</label>
          <label><span>重量</span><input type="number" min="0" step="any" value={goodsConfig.weight} onChange={(event) => setGoods('weight', event.target.value)} /></label>
          <label><span>长度</span><input type="number" min="0" step="any" value={goodsConfig.length} onChange={(event) => setGoods('length', event.target.value)} /></label>
          <label><span>宽度</span><input type="number" min="0" step="any" value={goodsConfig.width} onChange={(event) => setGoods('width', event.target.value)} /></label>
          <label><span>高度</span><input type="number" min="0" step="any" value={goodsConfig.height} onChange={(event) => setGoods('height', event.target.value)} /></label>
        </div>
      </section>
      {!logisticsOptions.length && <div className="semi-managed-config__warning">当前类目没有可用的物流属性接口选项。为避免把猜测值写入半托管页，物流属性必须先由真实接口返回后才能配置。</div>}
      <section className="semi-managed-config__section">
        <h3>变种信息</h3>
        <div className="semi-managed-config__grid">
          <label><span>产品价格</span><input type="number" min="0" step="any" value={variantConfig.product_price} onChange={(event) => setVariant('product_price', event.target.value)} /></label>
          <label><span>SKU 编码策略</span><input value={variantConfig.sku_code_strategy} placeholder="固定值或生成规则" onChange={(event) => setVariant('sku_code_strategy', event.target.value)} /></label>
          <label><span>货品编码策略</span><input value={variantConfig.goods_code_strategy} placeholder="固定值或生成规则" onChange={(event) => setVariant('goods_code_strategy', event.target.value)} /></label>
          <label><span>条码策略</span><input value={variantConfig.barcode_strategy} placeholder="固定值或生成规则" onChange={(event) => setVariant('barcode_strategy', event.target.value)} /></label>
          <label><span>JIT 库存</span><input type="number" min="0" step="1" value={variantConfig.jit_stock} onChange={(event) => setVariant('jit_stock', event.target.value)} /></label>
        </div>
      </section>
      <div className="semi-managed-config__notice">保存方案前必须完成参加国家、货品和变种必填项。任何未能在真实二段页读回的配置都会阻止执行。</div>
    </div>
  )
}

function resolveSemiCountryOptions(
  categoryId: string | undefined,
  capabilities: Record<string, DxmEditorCategoryCapabilities>,
) {
  const raw = categoryId ? capabilities[categoryId]?.semi_managed_country_options : undefined
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const record = item as Record<string, unknown>
    const value = record.id ?? record.value ?? record.code
    if (value === undefined || value === null) return []
    return [{ value: String(value), label: String(record.nameZh ?? record.label ?? record.name ?? value) }]
  })
}

function resolveSemiLogisticsOptions(
  categoryId: string | undefined,
  capabilities: Record<string, DxmEditorCategoryCapabilities>,
) {
  const raw = categoryId ? capabilities[categoryId]?.logistics_attribute_options : undefined
  if (!Array.isArray(raw)) return []
  const result: Array<{ value: string; label: string }> = []
  const visit = (items: unknown[]) => {
    for (const item of items) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) continue
      const record = item as Record<string, unknown>
      const value = record.value_id ?? record.valueId ?? record.id ?? record.value ?? record.code
      if (value !== undefined && value !== null && String(value).trim()) {
        const label = record.nameZh ?? record.label ?? record.name ?? record.text ?? value
        const normalized = { value: String(value), label: String(label) }
        if (!result.some((option) => option.value === normalized.value)) result.push(normalized)
      }
      if (Array.isArray(record.children)) visit(record.children)
    }
  }
  visit(raw)
  return result
}

function resolveSemiManagedAvailability(
  capability: DxmEditorCategoryCapabilities | undefined,
): 'supported' | 'unsupported' | 'unknown' {
  if (!capability || !Object.prototype.hasOwnProperty.call(capability, 'pop_choice_shop')) {
    return 'unknown'
  }
  const record = capability.pop_choice_shop
  if (!record || typeof record !== 'object') return 'unsupported'
  const enabled = record.isPopChoice === true || record.isPopChoice === 1 || record.isPopChoice === '1'
  const choiceShopId = record.popChoiceShopId ?? record.shopId
  return enabled && choiceShopId !== undefined && choiceShopId !== null && String(choiceShopId).trim() !== '' && String(choiceShopId) !== '0'
    ? 'supported'
    : 'unsupported'
}

function countNestedOptions(values: Array<Record<string, unknown>>): number {
  return values.reduce((count, value) => {
    const children = Array.isArray(value.children)
      ? value.children.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
      : []
    return count + 1 + countNestedOptions(children)
  }, 0)
}

function groupSectionTemplates(templates: DxmEditorSectionTemplate[]) {
  const grouped: Partial<Record<DxmTemplateRef['ref_type'], DxmEditorSectionTemplate[]>> = {}
  for (const template of templates) {
    (grouped[template.ref_type] ??= []).push(template)
  }
  return grouped
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
    const existingSourcePolicies = plan.source_policies?.[categoryId] ?? {}
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
              : existingSourcePolicies[fieldKey] ?? 'auto',
          value: Object.prototype.hasOwnProperty.call(existingFixedMap, fieldKey)
            ? existingFixedMap[fieldKey]
            : existingRules[fieldKey]?.value,
        },
      ]),
    )
  }
  return result
}

function hydrateSelectedTemplateValues(
  schemas: Record<string, E2CategorySchema>,
  models: Record<string, DxmEditorCategoryModel>,
  selectedRefIds: number[],
  baseDrafts: SchemaFieldDrafts,
): SchemaFieldDrafts {
  const selected = new Set(selectedRefIds)
  const result: SchemaFieldDrafts = Object.fromEntries(
    Object.entries(baseDrafts).map(([categoryId, drafts]) => [categoryId, { ...drafts }]),
  )
  for (const [categoryId, model] of Object.entries(models)) {
    const schema = schemas[categoryId]
    if (!schema) continue
    const categoryDrafts = { ...(result[categoryId] ?? {}) }
    for (const section of model.sections) {
      for (const template of section.templates) {
        if (!selected.has(template.ref_id)) continue
        const values = template.resolved_values && typeof template.resolved_values === 'object'
          ? template.resolved_values
          : {}
        for (const [fieldKey, value] of Object.entries(values)) {
          if (!schema.properties[fieldKey]) continue
          const previous = categoryDrafts[fieldKey]
          if (previous?.strategy === 'fill' || previous?.strategy === 'fixed') continue
          categoryDrafts[fieldKey] = {
            ...(previous ?? {
              uiLabelZh: schemaLabel(schema.properties[fieldKey], 0),
              strategy: 'auto' as const,
              value: undefined,
            }),
            strategy: 'template',
            value: normalizeSchemaValueForDefinition(schema.properties[fieldKey], value),
          }
        }
      }
    }
    result[categoryId] = categoryDrafts
  }
  return result
}

function mergeFieldDrafts(
  schemas: Record<string, E2CategorySchema>,
  current: SchemaFieldDrafts,
): SchemaFieldDrafts {
  const next: SchemaFieldDrafts = {}
  for (const [categoryId, schema] of Object.entries(schemas)) {
    next[categoryId] = Object.fromEntries(
      Object.entries(schema.properties).map(([fieldKey, definition], index) => [
        fieldKey,
        current[categoryId]?.[fieldKey] ?? {
          uiLabelZh: schemaLabel(definition, index),
          strategy: 'current' as const,
          value: undefined,
        },
      ]),
    )
  }
  return next
}

function buildStructuredPlanFields(
  categoryIds: string[],
  schemas: Record<string, E2CategorySchema>,
  drafts: SchemaFieldDrafts,
  planPath: 'A' | 'B',
) {
  const fillRules: LocalPlanTemplate['fill_rules'] = {}
  const fixedFieldValues: Record<string, Record<string, unknown>> = {}
  const fieldMappings: LocalPlanTemplate['field_mappings'] = {}
  const sourcePolicies: NonNullable<LocalPlanTemplate['source_policies']> = {}
  for (const categoryId of categoryIds) {
    const schema = schemas[categoryId]
    if (!schema) {
      throw new Error(`适用类目「${categoryId}」缺少已读取的字段定义，不能生成空的分类规则。请返回方案设置重新读取。`)
    }
    const categoryDrafts = drafts[categoryId] ?? {}
    fillRules[categoryId] = {}
    fixedFieldValues[categoryId] = {}
    sourcePolicies[categoryId] = {}
    const entries = Object.keys(schema.properties).map((fieldKey, index) => {
      const definition = schema.properties[fieldKey]
      const draft = categoryDrafts[fieldKey] ?? {
        uiLabelZh: schemaLabel(definition, index),
        strategy: 'auto' as const,
        value: undefined,
      }
      const uiLabelZh = schemaLabel(definition, index)
      if (!/[\u3400-\u9fff]/.test(uiLabelZh)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 缺少中文字段名`)
      }
      if (fieldKey === 'isJoinChoice') {
        fixedFieldValues[categoryId][fieldKey] = planPath === 'B'
      }
      if (fieldKey === 'categoryId') {
        fixedFieldValues[categoryId][fieldKey] = categoryId
      }
      if ((draft.strategy === 'fill' || draft.strategy === 'fixed') && !isConfiguredValue(draft.value)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 已选择${draft.strategy === 'fixed' ? '固定值' : '补差规则'}但没有操作值`)
      }
      if (draft.strategy === 'fill' && isConfiguredValue(draft.value)) {
        fillRules[categoryId][fieldKey] = { value: draft.value }
      }
      if (draft.strategy === 'fixed' && isConfiguredValue(draft.value)) {
        fixedFieldValues[categoryId][fieldKey] = draft.value
      }
      if (draft.strategy === 'current' || draft.strategy === 'template') {
        sourcePolicies[categoryId][fieldKey] = draft.strategy
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
  return { fillRules, fixedFieldValues, fieldMappings, sourcePolicies }
}

type TemplateAppliedSummaryProps = {
  template: DxmEditorSectionTemplate
  entries: Array<[string, unknown]>
  schema: E2CategorySchema
}

function TemplateAppliedSummary({ template, entries, schema }: TemplateAppliedSummaryProps) {
  const unmappedCount = template.unmapped_field_keys?.length ?? 0
  const coverageState = template.coverage_state ?? (entries.length ? 'complete' : 'none')
  return (
    <div className={`e2-template-applied-summary e2-template-applied-summary--${coverageState}`}>
      <div className="e2-template-applied-summary__head">
        <strong>
          {coverageState === 'none'
            ? '模板身份已读取，但没有可回填字段'
            : `已回填 ${entries.length} 个共享配置字段`}
        </strong>
        {coverageState === 'partial' && (
          <span>另有 {unmappedCount} 个接口字段未能映射，执行前会保持 fail-closed。</span>
        )}
      </div>
      {entries.length > 0 && (
        <div className="e2-template-applied-summary__values">
          {entries.slice(0, 8).map(([fieldKey, value]) => (
            <span key={fieldKey} className="e2-template-applied-summary__item">
              <b>{schemaLabel(schema.properties[fieldKey], 0)}</b>
              <em>{formatTemplateValue(value, schema.properties[fieldKey])}</em>
            </span>
          ))}
          {entries.length > 8 && <small>还有 {entries.length - 8} 个字段已回填</small>}
        </div>
      )}
    </div>
  )
}

function formatTemplateValue(value: unknown, definition: E2CategorySchemaProperty) {
  const normalized = normalizeSchemaValueForDefinition(definition, value)
  const options = resolveSchemaChoiceOptions(definition)
  const labelFor = (item: unknown) => {
    const option = options?.find((candidate) => candidate.value === String(item))
    return option?.label ?? String(item)
  }
  if (definition.type === 'array' && Array.isArray(normalized)) {
    if (!normalized.length) return '未设置'
    if (options) {
      const labels = normalized.slice(0, 3).map(labelFor)
      return normalized.length > 3 ? `${labels.join('、')} 等 ${normalized.length} 项` : labels.join('、')
    }
    return `${normalized.length} 项`
  }
  if (options) return labelFor(normalized)
  return formatEditorValue(normalized)
}

function displayPlanCategoryName(categoryId: string, categoryNames: Record<string, string>) {
  return categoryNames[categoryId]?.trim() || '中文类目名称待读取'
}

function formatEditorValue(value: unknown) {
  if (value === undefined || value === null || value === '') return '未读取'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string' || typeof value === 'number') {
    const text = String(value)
    return text.length > 54 ? `${text.slice(0, 51)}…` : text
  }
  if (Array.isArray(value)) return `${value.length} 项`
  if (typeof value === 'object') return `${Object.keys(value as Record<string, unknown>).length} 项配置`
  return String(value)
}

function schemaLabel(definition: E2CategorySchemaProperty, index: number) {
  const label = typeof definition.ui_label_zh === 'string' ? definition.ui_label_zh.trim() : ''
  return label || `字段${index + 1}`
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

type DirectSchemaFieldProps = {
  definition: E2CategorySchemaProperty
  fieldKey: string
  label: string
  required: boolean
  inheritedLabel?: string
  readOnlyValue?: string
  templateName?: string
  value: unknown
  pathValue?: boolean
  syncing: boolean
  onSync?: () => void
  onChange: (value: unknown) => void
}

function DirectSchemaField({
  definition,
  fieldKey,
  label,
  required,
  inheritedLabel,
  readOnlyValue,
  templateName,
  value,
  pathValue,
  syncing,
  onSync,
  onChange,
}: DirectSchemaFieldProps) {
  const readOnly = definition.read_only === true
  const choiceOptions = resolveSchemaChoiceOptions(definition)
  return (
    <div className="e2-schema-field">
      <div className="e2-schema-field__direct-head">
        <span>
          <strong>{label}</strong>
          {required && <em className="e2-required-badge">必填</em>}
        </span>
        {onSync && (
          <button className="button button--quiet e2-field-sync" type="button" disabled={syncing} onClick={onSync}>
            {syncing ? '同步中…' : `同步${label}选项`}
          </button>
        )}
      </div>
      {pathValue !== undefined ? (
        <div className="e2-schema-field__readonly"><strong>{pathValue ? '参与半托管' : '不参与半托管'}</strong><small>由方案编辑路径决定</small></div>
      ) : readOnly ? (
        <div className="e2-schema-field__readonly">
          <strong>{readOnlyValue || '由当前店铺与方案类目确定'}</strong>
          <small>{fieldKey === 'categoryId' ? '执行时整批商品统一切换到此类目' : '来自方案当前店铺，不依赖单独商品'}</small>
        </div>
      ) : definition.ui_control === 'sku_matrix' ? (
        <SkuMatrixEditor
          definition={definition}
          value={value}
          onChange={onChange}
        />
      ) : definition.ui_control === 'regional_pricing' ? (
        <RegionalPricingEditor value={value} templateName={templateName} />
      ) : definition.ui_control === 'json' ? (
        <div className="e2-schema-field__readonly e2-schema-field__readonly--blocked">
          <strong>{templateName ? `已引用模板「${templateName}」` : '海关监管需要专用配置'}</strong>
          <small>请先同步并选择店小秘模板；税率代码、推荐品名和材质等复合控件不会接受手写 JSON。</small>
        </div>
      ) : choiceOptions ? (
        definition.type === 'array' ? (
          <SearchableMultiSelect
            label={label}
            options={choiceOptions}
            value={Array.isArray(value) ? value.map(String) : []}
            onChange={onChange}
          />
        ) : (
          <label className="e2-schema-field__value">
            <span>方案设置</span>
            <select
              aria-label={`${label} 方案设置`}
              value={value == null ? '' : String(value)}
              onChange={(event) => onChange(event.target.value || undefined)}
            >
              <option value="">沿用每件商品原值</option>
              {choiceOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        )
      ) : (
        <SchemaValueEditor
          definition={definition}
          fieldKey={fieldKey}
          value={value}
          valueLabel="方案设置"
          onChange={onChange}
        />
      )}
      <small className="e2-schema-field__help">
        {templateName ? `已由模板「${templateName}」带入；仍可在这里调整。` : inheritedLabel || '留空时沿用每件商品原值。'}
      </small>
    </div>
  )
}

type SkuMatrixEditorProps = {
  definition: E2CategorySchemaProperty
  value: unknown
  onChange: (value: unknown) => void
}

const SKU_MATRIX_COLUMNS = ['skuCode', 'skuPrice', 'cargoPrice', 'ipmSkuStock', 'aeopSKUProperty']

function SkuMatrixEditor({ definition, value, onChange }: SkuMatrixEditorProps) {
  const rows = Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : []
  const properties = definition.items && typeof definition.items === 'object' && !Array.isArray(definition.items)
    ? definition.items.properties ?? {}
    : {}
  const columns = SKU_MATRIX_COLUMNS.filter((key) => properties[key] || key !== 'aeopSKUProperty')
  const labelFor = (key: string) => properties[key]?.ui_label_zh || ({
    skuCode: 'SKU 编码',
    skuPrice: 'SKU 售价',
    cargoPrice: 'SKU 货值',
    ipmSkuStock: 'SKU 库存',
    aeopSKUProperty: '属性组合',
  }[key] ?? key)
  const updateCell = (index: number, key: string, raw: string) => {
    const nextRows = rows.map((row) => ({ ...row }))
    const property = properties[key]
    if (property?.type === 'integer') {
      nextRows[index][key] = raw.trim() === '' ? undefined : Number.parseInt(raw, 10)
    } else if (property?.type === 'number') {
      nextRows[index][key] = raw.trim() === '' ? undefined : Number(raw)
    } else {
      nextRows[index][key] = raw
    }
    onChange(nextRows)
  }
  const addRow = () => onChange([...rows, { skuCode: '', skuPrice: '', cargoPrice: '', ipmSkuStock: 0, aeopSKUProperty: [] }])
  const removeRow = (index: number) => onChange(rows.filter((_, rowIndex) => rowIndex !== index))

  return (
    <div className="e2-sku-matrix" data-testid="sku-matrix-editor">
      <div className="e2-sku-matrix__toolbar">
        <span>按店小秘 SKU 矩阵填写；保存前会校验售价、货值、库存和属性组合。</span>
        <button className="button button--quiet" type="button" onClick={addRow}>新增 SKU</button>
      </div>
      {rows.length ? (
        <div className="e2-sku-matrix__table-wrap">
          <table className="e2-sku-matrix__table">
            <thead><tr>{columns.map((key) => <th key={key}>{labelFor(key)}</th>)}<th>操作</th></tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {columns.map((key) => (
                    <td key={key}>
                      {key === 'aeopSKUProperty' ? (
                        <span className="e2-sku-matrix__property-summary">{formatSkuProperties(row[key])}</span>
                      ) : (
                        <input
                          aria-label={`${labelFor(key)} ${index + 1}`}
                          type={properties[key]?.type === 'integer' || properties[key]?.type === 'number' ? 'number' : 'text'}
                          min={properties[key]?.type === 'integer' || properties[key]?.type === 'number' ? 0 : undefined}
                          step={properties[key]?.type === 'integer' ? 1 : 'any'}
                          value={row[key] == null ? '' : String(row[key])}
                          onChange={(event) => updateCell(index, key, event.target.value)}
                        />
                      )}
                    </td>
                  ))}
                  <td><button className="button button--quiet" type="button" onClick={() => removeRow(index)}>移除</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="e2-sku-matrix__empty">当前方案还没有 SKU 行；执行时将沿用商品现有 SKU。需要统一改价或库存时，请新增 SKU 行。</div>
      )}
    </div>
  )
}

function formatSkuProperties(value: unknown) {
  if (!Array.isArray(value) || !value.length) return '沿用商品属性组合'
  const labels = value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const record = item as Record<string, unknown>
    const label = record.propertyValueDefinitionName ?? record.themeVal ?? record.attrVal
    return label == null ? [] : [String(label)]
  })
  return labels.length ? labels.join(' / ') : `${value.length} 项属性组合`
}

type RegionalPricingEditorProps = {
  value: unknown
  templateName?: string
}

function RegionalPricingEditor({ value, templateName }: RegionalPricingEditorProps) {
  const parsed = parseRegionalPricing(value)
  return (
    <div className="e2-regional-pricing" data-testid="regional-pricing-editor">
      <div className="e2-regional-pricing__head">
        <strong>{templateName ? `已引用区域调价模板「${templateName}」` : '区域调价由店小秘模板驱动'}</strong>
        <span>{parsed ? '已读取结构化报价配置' : '尚未选择区域调价模板'}</span>
      </div>
      {parsed ? <RegionalPricingValue value={parsed} /> : (
        <div className="e2-regional-pricing__empty">请在上方选择已同步的区域调价模板。没有模板时不会把原始 JSON 当作可填写文本，执行也不会猜测国家或报价方式。</div>
      )}
    </div>
  )
}

function parseRegionalPricing(value: unknown): unknown {
  if (value && typeof value === 'object') return value
  if (typeof value !== 'string' || !value.trim()) return undefined
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : undefined
  } catch {
    return undefined
  }
}

const REGIONAL_LABELS: Record<string, string> = {
  country: '国家', countryCode: '国家代码', region: '区域', regionCode: '区域代码',
  price: '价格', quote: '报价', ratio: '倍率', currency: '币种',
  enabled: '启用', value: '值', name: '名称', mode: '调价方式',
}

function RegionalPricingValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return <div className="e2-regional-pricing__rows">{value.map((item, index) => <div className="e2-regional-pricing__row" key={index}><b>区域 {index + 1}</b><RegionalPricingValue value={item} /></div>)}</div>
  }
  if (value && typeof value === 'object') {
    return <div className="e2-regional-pricing__grid">{Object.entries(value as Record<string, unknown>).map(([key, child]) => (
      <div className="e2-regional-pricing__cell" key={key}><span>{REGIONAL_LABELS[key] ?? key}</span><strong>{formatRegionalValue(child)}</strong></div>
    ))}</div>
  }
  return <span>{String(value ?? '未设置')}</span>
}

function formatRegionalValue(value: unknown) {
  if (value && typeof value === 'object') return Array.isArray(value) ? `${value.length} 项` : `${Object.keys(value as Record<string, unknown>).length} 项配置`
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value ?? '未设置')
}

type SearchableMultiSelectProps = {
  label: string
  options: Array<{ value: string; label: string }>
  value: string[]
  onChange: (value: string[]) => void
}

function SearchableMultiSelect({ label, options, value, onChange }: SearchableMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const selected = new Set(value)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleOptions = options.filter((option) => (
    !normalizedQuery
      || option.label.toLocaleLowerCase().includes(normalizedQuery)
      || option.value.toLocaleLowerCase().includes(normalizedQuery)
  ))
  const toggle = (optionValue: string) => {
    onChange(selected.has(optionValue)
      ? value.filter((item) => item !== optionValue)
      : [...value, optionValue])
  }
  return (
    <div className="e2-multi-select">
      <button
        className="e2-multi-select__trigger"
        type="button"
        aria-label={`${label} 方案设置`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="e2-multi-select__chips">
          {value.length ? value.map((item) => {
            const option = options.find((candidate) => candidate.value === item)
            return (
              <span className="e2-multi-select__chip" key={item}>
                {option?.label ?? item}
                <span aria-hidden="true">×</span>
              </span>
            )
          }) : <span className="e2-multi-select__placeholder">请选择{label}</span>}
        </span>
        <span className="e2-multi-select__count">{value.length} 项⌄</span>
      </button>
      {open && (
        <div className="e2-multi-select__menu">
          <div className="e2-multi-select__toolbar">
            <input
              autoFocus
              type="search"
              value={query}
              aria-label={`搜索${label}选项`}
              placeholder="搜索中文名称或 ID"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setOpen(false)
              }}
            />
            <button type="button" className="button button--quiet" onClick={() => onChange([])}>清空</button>
          </div>
          <div className="e2-multi-select__options" role="listbox" aria-multiselectable="true" aria-label={`${label}选项`}>
            {visibleOptions.map((option) => (
              <label className={selected.has(option.value) ? 'is-selected' : ''} key={option.value}>
                <input
                  type="checkbox"
                  checked={selected.has(option.value)}
                  onChange={() => toggle(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
            {!visibleOptions.length && <p className="e2-multi-select__empty">没有匹配选项</p>}
          </div>
        </div>
      )}
    </div>
  )
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
