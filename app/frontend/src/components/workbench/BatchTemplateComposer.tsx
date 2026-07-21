import { useEffect, useMemo, useState } from 'react'
import { getJson, postJson } from '../../api'
import type {
  DeliveryWorkspace,
  EditBatchBundleCreateRequest,
  EditBatchBundleOptions,
  EditBatchBundleSectionCode,
  EditBatchBundleSectionOptions,
  Task,
  Template,
} from '../../types'

type BatchTemplateComposerProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  initialCategoryName: string
  onBundleCreated: () => void | Promise<void>
  onEditSection: (section: EditBatchBundleSectionCode) => void
  onShowDraftEdit: () => void
}

type IssueSection = {
  section: EditBatchBundleSectionCode
  label: string
  detail: string
}

type ComposerMessage = {
  tone: 'success' | 'warning' | 'error'
  text: string
}

export const EDIT_BATCH_BUNDLE_SECTIONS: readonly EditBatchBundleSectionCode[] = [
  'category',
  'sku',
  'pricing',
  'logistics',
  'image',
  'compliance',
  'semi_managed',
  'dxm_reference',
]

const SECTION_LABELS: Record<EditBatchBundleSectionCode, string> = {
  category: '类目与标题',
  sku: 'SKU 与库存',
  pricing: '价格策略',
  logistics: '包装物流',
  image: '图片与素材',
  compliance: '合规与海关',
  semi_managed: '半托管',
  dxm_reference: '店小秘引用模板',
}

const MISSING_FIELD_LABELS: Record<string, string> = {
  is_enabled: '模板尚未启用',
  binding: '店铺或类目绑定不匹配',
  category: '未填写类目匹配规则',
  'logistics.weight': '未填写重量',
  'logistics.length': '未填写包装长度',
  'logistics.width': '未填写包装宽度',
  'logistics.height': '未填写包装高度',
  'image.eu_outer_package_filename': '未选择欧盟外包装图',
  'image.marketing_images_strategy': '未填写营销图策略',
  'semi_managed.product_price_or_supply_price': '未填写商品价或供货价',
  'semi_managed.jit_stock': '未填写 JIT 库存',
  'semi_managed.is_original_box': '未填写原包装选项',
  'semi_managed.length': '未填写半托管包装长度',
  'semi_managed.width': '未填写半托管包装宽度',
  'semi_managed.height': '未填写半托管包装高度',
  'semi_managed.goods_code_strategy': '未填写货号策略',
  'semi_managed.barcode_strategy': '未填写条码策略',
  dxm_reference_templates: '店小秘引用模板不完整',
  TEMPLATE_SOURCE_INVALID: '模板内容格式无效',
  TEMPLATE_SOURCE_INCOMPLETE: '模板内容不完整',
  TEMPLATE_PUBLISH_FORBIDDEN: '模板包含不允许的发布配置',
}

export function BatchTemplateComposer({
  workspace,
  selectedTask,
  initialCategoryName,
  onBundleCreated,
  onEditSection,
  onShowDraftEdit,
}: BatchTemplateComposerProps) {
  const [selectedStoreId, setSelectedStoreId] = useState<number | null>(() => preferredStoreId(workspace, selectedTask))
  const [categoryName, setCategoryName] = useState(() => cleanInitialCategory(initialCategoryName))
  const [templateName, setTemplateName] = useState(() => defaultBundleName(initialCategoryName))
  const [version, setVersion] = useState('1.0.0')
  const [options, setOptions] = useState<EditBatchBundleOptions | null>(null)
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<Partial<Record<EditBatchBundleSectionCode, number>>>({})
  const [optionsLoading, setOptionsLoading] = useState(false)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [message, setMessage] = useState<ComposerMessage | null>(null)
  const [createdBundle, setCreatedBundle] = useState<Template | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const storeStillExists = selectedStoreId != null && workspace.stores.some((store) => store.id === selectedStoreId)
    if (!storeStillExists) setSelectedStoreId(preferredStoreId(workspace, selectedTask))
  }, [selectedStoreId, selectedTask, workspace.stores])

  useEffect(() => {
    setCategoryName(cleanInitialCategory(initialCategoryName))
    setTemplateName((current) => current.trim() || defaultBundleName(initialCategoryName))
  }, [initialCategoryName])

  useEffect(() => {
    if (selectedStoreId == null) {
      setOptions(null)
      setSelectedTemplateIds({})
      setOptionsError(null)
      setOptionsLoading(false)
      return
    }

    let cancelled = false
    const timer = window.setTimeout(() => {
      setOptionsLoading(true)
      setOptionsError(null)
      setMessage(null)
      setCreatedBundle(null)
      const params = new URLSearchParams({
        store_id: String(selectedStoreId),
      })
      if (categoryName.trim()) params.set('category_name', categoryName.trim())
      void getJson<EditBatchBundleOptions>(`/api/template-center/edit-batch-bundle-options?${params.toString()}`)
        .then((result) => {
          if (cancelled) return
          setOptions(result)
          setSelectedTemplateIds((current) => defaultSelections(result, current))
        })
        .catch(() => {
          if (cancelled) return
          setOptions(null)
          setSelectedTemplateIds({})
          setOptionsError('候选模板读取失败；系统没有生成整批模板。')
        })
        .finally(() => {
          if (!cancelled) setOptionsLoading(false)
        })
    }, 220)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [categoryName, reloadKey, selectedStoreId])

  const sectionsByCode = useMemo(() => new Map(
    (options?.sections ?? []).map((section) => [section.section, section] as const),
  ), [options])

  const issueSections = useMemo<IssueSection[]>(() => EDIT_BATCH_BUNDLE_SECTIONS.flatMap((sectionCode) => {
    const section = sectionsByCode.get(sectionCode)
    const candidates = readyCandidates(section)
    const selectedId = selectedTemplateIds[sectionCode]
    const selectedCandidate = candidates.find((candidate) => candidate.template_id === selectedId)
    if (section && section.ready_count > 0 && selectedCandidate) return []
    return [{
      section: sectionCode,
      label: SECTION_LABELS[sectionCode],
      detail: sectionIssueDetail(section),
    }]
  }), [sectionsByCode, selectedTemplateIds])

  const firstIssue = issueSections[0]
  const readyCount = options?.ready_count ?? 0
  const formReady = Boolean(templateName.trim() && version.trim() && selectedStoreId != null)
  const canCompose = Boolean(options?.ready && !firstIssue && formReady)
  const primaryLabel = createdBundle
    ? '回到批次草稿'
    : optionsLoading
      ? '正在读取候选'
      : optionsError
        ? '重新读取候选'
        : firstIssue
          ? `编辑「${firstIssue.label}」`
          : submitting
            ? '正在生成整批模板'
            : '生成整批模板'
  const primaryDisabled = optionsLoading
    || submitting
    || (!createdBundle && !optionsError && !firstIssue && !canCompose)
    || (!createdBundle && !optionsError && selectedStoreId == null)

  function changeStore(value: string) {
    const storeId = Number(value)
    setSelectedStoreId(Number.isInteger(storeId) && storeId > 0 ? storeId : null)
    setCreatedBundle(null)
    setMessage(null)
  }

  function changeCandidate(section: EditBatchBundleSectionCode, value: string) {
    const templateId = Number(value)
    setSelectedTemplateIds((current) => {
      const next = { ...current }
      if (Number.isInteger(templateId) && templateId > 0) next[section] = templateId
      else delete next[section]
      return next
    })
    setCreatedBundle(null)
    setMessage(null)
  }

  async function handlePrimaryAction() {
    if (createdBundle) {
      onShowDraftEdit()
      return
    }
    if (optionsError) {
      setMessage(null)
      setReloadKey((current) => current + 1)
      return
    }
    if (!options) return
    if (firstIssue) {
      onEditSection(firstIssue.section)
      return
    }
    if (!canCompose || selectedStoreId == null) return

    const sectionTemplates = {} as EditBatchBundleCreateRequest['section_templates']
    for (const sectionCode of EDIT_BATCH_BUNDLE_SECTIONS) {
      const section = sectionsByCode.get(sectionCode)
      const candidate = readyCandidates(section).find(
        (item) => item.template_id === selectedTemplateIds[sectionCode],
      )
      if (!candidate || !candidate.ready) {
        onEditSection(sectionCode)
        return
      }
      sectionTemplates[sectionCode] = {
        template_id: candidate.template_id,
        source_digest: candidate.source_digest,
      }
    }

    setSubmitting(true)
    setMessage(null)
    try {
      const created = await postJson<Template>('/api/template-center/edit-batch-bundles', {
        template_name: templateName.trim(),
        version: version.trim(),
        store_id: selectedStoreId,
        category_name: categoryName.trim() || null,
        section_templates: sectionTemplates,
      } satisfies EditBatchBundleCreateRequest)
      setCreatedBundle(created)
      try {
        await onBundleCreated()
        setMessage({ tone: 'success', text: `已生成「${created.template_name}」，模板列表已更新。` })
      } catch {
        setMessage({ tone: 'warning', text: `已生成「${created.template_name}」，但模板列表刷新失败；返回批次草稿前请刷新页面。` })
      }
    } catch {
      setOptionsError('候选需要重新读取后才能再次生成。')
      setMessage({ tone: 'error', text: '整批模板生成失败；候选可能已经变化。系统没有执行商品保存。' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="module-card span-3 batch-template-composer" aria-label="整批模板组合器">
      <div className="batch-template-composer__head">
        <div>
          <span className="eyebrow">整批模板</span>
          <h2>组合 8 个编辑分区</h2>
        </div>
        <span className={issueSections.length ? 'batch-template-ready is-blocked' : 'batch-template-ready is-ready'} aria-live="polite">
          <strong>已就绪</strong>
          <b>{readyCount}/{EDIT_BATCH_BUNDLE_SECTIONS.length}</b>
        </span>
      </div>

      <details className="batch-template-adjustments">
        <summary>调整来源模板（可选）</summary>
        <div className="batch-template-composer__fields">
          <label>
            <span>店铺</span>
            <select value={selectedStoreId ?? ''} onChange={(event) => changeStore(event.target.value)} disabled={!workspace.stores.length}>
              {workspace.stores.length ? workspace.stores.map((store) => (
                <option key={store.id} value={store.id}>{store.name}</option>
              )) : (
                <option value="">暂无店铺</option>
              )}
            </select>
          </label>
          <label>
            <span>绑定类目（可选）</span>
            <input
              value={categoryName}
              onChange={(event) => { setCategoryName(event.target.value); setCreatedBundle(null); setMessage(null) }}
              placeholder="留空则生成店铺级模板"
            />
          </label>
          <label>
            <span>整批模板名称</span>
            <input
              value={templateName}
              onChange={(event) => { setTemplateName(event.target.value); setCreatedBundle(null); setMessage(null) }}
              placeholder="例如 车载用品整批编辑模板"
            />
          </label>
          <label>
            <span>版本</span>
            <input
              value={version}
              onChange={(event) => { setVersion(event.target.value); setCreatedBundle(null); setMessage(null) }}
              placeholder="1.0.0"
            />
          </label>
        </div>

        <div className="batch-template-composer__sections" aria-label="8 个分区候选">
          {EDIT_BATCH_BUNDLE_SECTIONS.map((sectionCode) => {
            const section = sectionsByCode.get(sectionCode)
            const candidates = readyCandidates(section)
            return (
              <label key={sectionCode} className={!candidates.length ? 'has-issue' : ''}>
                <span>
                  <strong>{SECTION_LABELS[sectionCode]}</strong>
                  <small>{section?.ready_count ?? 0} 个就绪候选</small>
                </span>
                <select
                  value={selectedTemplateIds[sectionCode] ?? ''}
                  onChange={(event) => changeCandidate(sectionCode, event.target.value)}
                  disabled={!candidates.length || optionsLoading}
                >
                  {candidates.length ? candidates.map((candidate) => (
                    <option key={candidate.template_id} value={candidate.template_id}>{candidate.template_name}</option>
                  )) : (
                    <option value="">暂无就绪候选</option>
                  )}
                </select>
              </label>
            )
          })}
        </div>
      </details>

      <div className={optionsLoading || optionsError || issueSections.length ? 'batch-template-issues has-issues' : 'batch-template-issues is-clear'}>
        {optionsLoading ? (
          <span className="batch-template-issues__summary">
            <strong>正在读取候选模板</strong>
            <b>请稍候</b>
          </span>
        ) : optionsError ? (
          <span className="batch-template-issues__summary">
            <strong>{optionsError}</strong>
            <b>需要重新读取</b>
          </span>
        ) : issueSections.length ? (
          <>
            <span className="batch-template-issues__summary">
              <strong>首个阻断：{firstIssue?.label}</strong>
              <b>{issueSections.length} 个分区未就绪</b>
            </span>
            <details>
              <summary>查看问题明细</summary>
              <ul>
                {issueSections.map((issue) => (
                  <li key={issue.section}>
                    <b>{issue.label}</b>
                    <span>{issue.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : (
          <span><strong>全部就绪</strong> · 8 个分区均已有可用模板。</span>
        )}
      </div>

      {message && !optionsError && (
        <p className={`batch-template-message is-${message.tone}`} aria-live="polite">
          {message.text}
        </p>
      )}

      <div className="batch-template-composer__action">
        <button
          className="button button--primary"
          type="button"
          onClick={() => { void handlePrimaryAction() }}
          disabled={primaryDisabled}
        >
          {primaryLabel}
        </button>
      </div>
    </section>
  )
}

function preferredStoreId(workspace: DeliveryWorkspace, selectedTask: Task | null) {
  const taskStoreId = selectedTask?.store_id
  if (taskStoreId != null && workspace.stores.some((store) => store.id === taskStoreId)) return taskStoreId
  const taskStoreName = String(selectedTask?.payload?.store_name ?? '').trim()
  const taskStore = workspace.stores.find((store) => store.name === taskStoreName)
  return taskStore?.id ?? workspace.stores[0]?.id ?? null
}

function cleanInitialCategory(categoryName: string) {
  const value = categoryName.trim()
  return value === '未选择类目' ? '' : value
}

function defaultBundleName(categoryName: string) {
  const category = cleanInitialCategory(categoryName)
  return category ? `${category}整批编辑模板` : '整批编辑模板'
}

function readyCandidates(section: EditBatchBundleSectionOptions | undefined) {
  const candidates = [...(section?.candidates ?? [])]
  const defaultCandidate = section?.default_candidate
  if (defaultCandidate && !candidates.some((candidate) => candidate.template_id === defaultCandidate.template_id)) {
    candidates.unshift(defaultCandidate)
  }
  return candidates.filter((candidate) => candidate.ready)
}

function defaultSelections(
  options: EditBatchBundleOptions,
  current: Partial<Record<EditBatchBundleSectionCode, number>>,
) {
  const selections: Partial<Record<EditBatchBundleSectionCode, number>> = {}
  for (const sectionCode of EDIT_BATCH_BUNDLE_SECTIONS) {
    const section = options.sections.find((item) => item.section === sectionCode)
    const candidates = readyCandidates(section)
    const currentCandidate = candidates.find((candidate) => candidate.template_id === current[sectionCode])
    const defaultCandidate = section?.default_candidate?.ready ? section.default_candidate : undefined
    const selected = currentCandidate ?? defaultCandidate ?? candidates[0]
    if (selected) selections[sectionCode] = selected.template_id
  }
  return selections
}

function sectionIssueDetail(section: EditBatchBundleSectionOptions | undefined) {
  if (!section) return '未读取到该必需分区。'
  const missingField = section.candidates.flatMap((candidate) => candidate.missing_fields)[0]
  if (missingField) return humanMissingField(missingField)
  return section.ready_count > 0 ? '请选择一个就绪候选。' : '当前没有就绪候选，请先完善该分区模板。'
}

function humanMissingField(field: string) {
  if (MISSING_FIELD_LABELS[field]) return MISSING_FIELD_LABELS[field]
  if (field.startsWith('dxm_reference_templates.')) return '店小秘引用模板不完整'
  return '模板内容未满足该分区要求'
}
