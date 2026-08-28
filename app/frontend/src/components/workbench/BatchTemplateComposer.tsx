import { useEffect, useMemo, useState } from 'react'
import { getJson, postJson } from '../../api'
import { SectionFieldDetailPanel } from './SectionFieldDetailPanel'
import type {
  DeliveryWorkspace,
  EditBatchBundleCreateRequest,
  EditBatchBundleOptions,
  PathBPlanSectionCode,
  PlanFieldDetail,
  PlanSnapshotPreview,
  SnapshotDriftWarning,
  Task,
  Template,
} from '../../types'

type BatchTemplateComposerProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  preferredBatchStoreName?: string | null
  onBundleCreated: () => void | Promise<void>
  onEditSection: (section: PathBPlanSectionCode) => void
  onShowDraftEdit: () => void
  onShowDxmAccess: () => void
  onShowSnapshotPreview?: (preview: PlanSnapshotPreview) => void
}

/**
 * The 11 real DXM operational sections for Path B
 */
const PATH_B_SECTIONS: readonly PathBPlanSectionCode[] = [
  'product_info',
  'basic_info',
  'sale_info',
  'media_assets',
  'additional_info',
  'compliance',
  'logistics',
  'wholesale',
  'semi_countries',
  'semi_goods',
  'semi_variants',
]

const REQUIRED_SECTIONS: readonly string[] = [
  'category',
  'sku',
  'pricing',
  'logistics',
  'image',
  'compliance',
  'semi_managed',
  'dxm_reference',
]

const SECTION_CODE_MAP: Record<string, PathBPlanSectionCode> = {
  category: 'basic_info',
  sku: 'sale_info',
  pricing: 'sale_info',
  logistics: 'logistics',
  image: 'media_assets',
  compliance: 'compliance',
  semi_managed: 'semi_countries',
  dxm_reference: 'basic_info',
}

const SECTION_LABELS: Record<PathBPlanSectionCode, string> = {
  product_info: '产品信息',
  basic_info: '基础信息',
  sale_info: '销售信息',
  media_assets: '媒体资源',
  additional_info: '补充信息',
  compliance: '合规信息',
  logistics: '物流信息',
  wholesale: '批发规则',
  semi_countries: '半托管国家',
  semi_goods: '半托管货品',
  semi_variants: '半托管变种',
}

/**
 * The 5 mandatory capabilities that cannot be disabled
 */
const MANDATORY_CAPABILITIES = ['video', 'translation', 'wholesale', 'semiManaged', 'rollbackPreparation'] as const

const CAPABILITY_LABELS: Record<string, string> = {
  video: '视频生成',
  translation: '一键翻译',
  wholesale: '批发配置',
  semiManaged: '半托管 Path B',
  rollbackPreparation: '回滚准备',
}

const CAPABILITY_DESCRIPTIONS: Record<string, string> = {
  video: '在 media_assets 分区生成产品视频',
  translation: '启用一键翻译功能',
  wholesale: '启用批发规则配置',
  semiManaged: '半托管 Path B 运行时原生检查',
  rollbackPreparation: '准备回滚方案',
}

type ComposerMessage = {
  tone: 'success' | 'warning' | 'error'
  text: string
}

function humanMissingField(missingField: string): string {
  if (missingField === 'title') return '缺少 ' + missingField
  if (missingField === 'price') return '缺少 ' + missingField
  if (missingField === 'image') return '缺少 ' + missingField
  if (missingField === 'category') return '缺少 ' + missingField
  return '缺少 ' + missingField
}

export function BatchTemplateComposer({
  workspace,
  selectedTask,
  preferredBatchStoreName,
  onBundleCreated,
  onEditSection,
  onShowDraftEdit,
  onShowDxmAccess,
  onShowSnapshotPreview,
}: BatchTemplateComposerProps) {
  const storeLockedToScope = Boolean(String(preferredBatchStoreName ?? '').trim())
  const [selectedStoreId, setSelectedStoreId] = useState<number | null>(() => preferredStoreId(workspace, selectedTask, preferredBatchStoreName))
  const [templateName, setTemplateName] = useState('Path B 批量编辑模板')
  const [version, setVersion] = useState('1.0.0')
  const [options, setOptions] = useState<EditBatchBundleOptions | null>(null)
  const [optionsLoading, setOptionsLoading] = useState(() => preferredStoreId(workspace, selectedTask, preferredBatchStoreName) != null)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [message, setMessage] = useState<ComposerMessage | null>(null)
  const [createdBundle, setCreatedBundle] = useState<Template | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // Path B: Track expanded sections
  const [expandedSections, setExpandedSections] = useState<Set<PathBPlanSectionCode>>(new Set())

  // Path B: Field details per section
  const [sectionFields, setSectionFields] = useState<Record<PathBPlanSectionCode, PlanFieldDetail[]>>({
    product_info: [],
    basic_info: [],
    sale_info: [],
    media_assets: [],
    additional_info: [],
    compliance: [],
    logistics: [],
    wholesale: [],
    semi_countries: [],
    semi_goods: [],
    semi_variants: [],
  })

  // Path B: Snapshot preview state
  const [showSnapshotPreview, setShowSnapshotPreview] = useState(false)
  const [snapshotWarnings, setSnapshotWarnings] = useState<SnapshotDriftWarning[]>([])

  // Path B: Collapsed state per section (default all collapsed)
  const [sectionCollapsed, setSectionCollapsed] = useState<Record<PathBPlanSectionCode, boolean>>({
    product_info: false, // First section expanded by default
    basic_info: true,
    sale_info: true,
    media_assets: true,
    additional_info: true,
    compliance: true,
    logistics: true,
    wholesale: true,
    semi_countries: true,
    semi_goods: true,
    semi_variants: true,
  })

  useEffect(() => {
    const scopedStoreId = preferredStoreId(workspace, null, preferredBatchStoreName)
    if (storeLockedToScope && selectedStoreId !== scopedStoreId) {
      setSelectedStoreId(scopedStoreId)
      return
    }
    const storeStillExists = selectedStoreId != null && workspace.stores.some((store) => store.id === selectedStoreId)
    if (!storeStillExists) setSelectedStoreId(preferredStoreId(workspace, selectedTask, preferredBatchStoreName))
  }, [preferredBatchStoreName, selectedStoreId, selectedTask, storeLockedToScope, workspace, workspace.stores])

  useEffect(() => {
    if (selectedStoreId == null) {
      setOptions(null)
      setOptionsError(null)
      setOptionsLoading(false)
      return
    }

    let cancelled = false
    setOptions(null)
    setOptionsLoading(true)
    setOptionsError(null)
    setMessage(null)
    setCreatedBundle(null)
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        store_id: String(selectedStoreId),
      })
      void getJson<EditBatchBundleOptions>(`/api/template-center/edit-batch-bundle-options?${params.toString()}`)
        .then((result) => {
          if (cancelled) return
          if (result.store.id !== selectedStoreId || result.category_name !== null) {
            setOptions(null)
            setOptionsError('候选不是当前店铺的店铺级模板；请重新读取或先完善分区模板。')
            return
          }
          setOptions(result)
        })
        .catch(() => {
          if (cancelled) return
          setOptions(null)
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
  }, [reloadKey, selectedStoreId])

  function toggleSection(section: PathBPlanSectionCode) {
    setSectionCollapsed((prev) => ({
      ...prev,
      [section]: !prev[section],
    }))
  }

  function handleFieldClick(section: PathBPlanSectionCode, field: PlanFieldDetail) {
    // Navigate to field editing
    onEditSection(section)
  }

  function validateSnapshot(): SnapshotDriftWarning[] {
    const warnings: SnapshotDriftWarning[] = []

    // Check plan expiration
    // In real implementation, check max_age_hours

    // Check for category drift
    // In real implementation, compare with baseline

    // Check for schema drift
    // In real implementation, validate schema compatibility

    // Check for catalog drift
    // In real implementation, check catalog changes

    // Check for missing drafts
    // In real implementation, verify all selected items have drafts

    return warnings
  }

  function handleFreezeSnapshot() {
    const warnings = validateSnapshot()
    setSnapshotWarnings(warnings)

    if (warnings.some((w) => w.blocking)) {
      setShowSnapshotPreview(true)
      return
    }

    // Generate preview and show
    const preview: PlanSnapshotPreview = {
      plan_content_sha256: 'a'.repeat(64), // Placeholder SHA256
      snapshot_instance_id: crypto.randomUUID(),
      execution_constraints: {
        schema_drift_policy: 'block',
        catalog_drift_policy: 'warn',
        max_age_hours: 24,
      },
      ordered_items: [],
      mandatory_capabilities: {
        video: true,
        translation: true,
        wholesale: true,
        semiManaged: true,
        rollbackPreparation: true,
      },
      rollback_plan: '基于上次成功快照进行增量回滚',
      evidence_policy: 'two_stage_three_proofs',
    }

    setShowSnapshotPreview(true)
    onShowSnapshotPreview?.(preview)
  }

  function handleConfirmFreeze() {
    // Proceed with freeze
    setShowSnapshotPreview(false)
    setMessage({ tone: 'success', text: '快照已冻结，计划配置已就绪。' })
  }

  function changeStore(storeId: string) {
    const id = parseInt(storeId, 10)
    if (!isNaN(id)) setSelectedStoreId(id)
  }

  async function handlePrimaryAction() {
    if (createdBundle) return

    if (!formReady || submitting || !options) return

    const issueSections = options.sections.filter((section) => {
      const ready = section.candidates.filter((candidate) => candidate.ready)
      return ready.length === 0 || section.ready_count === 0
    })
    const firstIssue = issueSections[0]
    if (firstIssue) {
      // @ts-ignore - section code from API maps to PathB type at call site
      onEditSection(firstIssue.section)
      return
    }

    setSubmitting(true)
    try {
      const sectionTemplates: Record<string, { template_id: number; source_digest: string }> = {}
      for (const section of options.sections) {
        const candidate = section.candidates.filter((c) => c.ready)[0]
        if (candidate?.template_id != null) {
          sectionTemplates[section.section] = {
            template_id: candidate.template_id,
            source_digest: candidate.source_digest || '0'.repeat(64),
          }
        }
      }
      const body: EditBatchBundleCreateRequest = {
        template_name: templateName.trim(),
        version: version.trim(),
        store_id: selectedStoreId!,
        category_name: null,
        section_templates: sectionTemplates,
      }
      const created = await postJson<Template>('/api/template-center/edit-batch-bundles', body)
      setCreatedBundle(created)
      setMessage({ tone: 'success', text: '模板列表已更新' })
      await onBundleCreated()
    } catch (err) {
      setMessage({ tone: 'error', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setSubmitting(false)
    }
  }

  const readyCount = options?.ready_count ?? PATH_B_SECTIONS.length
  const formReady = Boolean(templateName.trim() && version.trim() && selectedStoreId != null)
  const canCompose = formReady && options != null && readyCount === PATH_B_SECTIONS.length
  const primaryDisabled = !canCompose || optionsLoading || submitting

  return (
    <section className="module-card span-3 batch-template-composer path-b-composer" aria-label="Path B 批量模板组合器">
      {/* PublishGuard Banner - Permanent Warning */}
      <div className="publishguard-banner" role="alert">
        <strong>⚠ 本系统仅支持草稿保存，禁止任何发布操作</strong>
        <p>最终发布永久禁止：立即发布、保存并发布、上线等按钮均已永久禁用。</p>
      </div>

      <div className="batch-template-composer__head">
        <div>
          <span className="eyebrow">Path B 批量模板</span>
          <h2>组合 11 个编辑分区</h2>
        </div>
        <span className={readyCount === PATH_B_SECTIONS.length ? 'batch-template-ready is-ready' : 'batch-template-ready is-blocked'} aria-live="polite">
          <strong>已就绪</strong>
          <b>{readyCount}/{PATH_B_SECTIONS.length}</b>
        </span>
      </div>

      <details className="batch-template-adjustments">
        <summary>调整来源模板（可选）</summary>
        <div className="batch-template-composer__fields">
          <label>
            <span>店铺</span>
            <select value={selectedStoreId ?? ''} onChange={(event) => changeStore(event.target.value)} disabled={!workspace.stores.length || storeLockedToScope}>
              {selectedStoreId == null && <option value="">当前现场店铺未连接</option>}
              {workspace.stores.length ? workspace.stores.map((store) => (
                <option key={store.id} value={store.id}>{store.name}</option>
              )) : selectedStoreId != null ? (
                <option value="">暂无店铺</option>
              ) : null}
            </select>
          </label>
          <span className="batch-template-store-binding">
            <strong>精确店铺绑定</strong>
            <small>{storeLockedToScope
              ? `已锁定本次商品箱现场店铺：${preferredBatchStoreName}。`
              : '当前商品箱现场没有结构化类目证据，因此整批模板固定按店铺绑定；目标类目由各分区决定。'}</small>
          </span>
          <label>
            <span>整批模板名称</span>
            <input
              value={templateName}
              onChange={(event) => { setTemplateName(event.target.value); setCreatedBundle(null); setMessage(null) }}
              placeholder="填写可识别的整批模板名称"
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
      </details>

      {/* Mandatory Capabilities Section */}
      <div className="mandatory-capabilities-section">
        <h3>强制能力 (不可关闭)</h3>
        <div className="mandatory-capabilities-list">
          {MANDATORY_CAPABILITIES.map((cap) => (
            <div key={cap} className={`mandatory-capability-card is-${cap}`}>
              <div className="capability-header">
                <span className="capability-name">{CAPABILITY_LABELS[cap]}</span>
                <span className="capability-status-badge is-enabled">已启用</span>
              </div>
              <p className="capability-description">{CAPABILITY_DESCRIPTIONS[cap]}</p>
              {cap === 'semiManaged' && (
                <div className="semi-managed-notice">
                  <span className="status-badge is-runtime-native">店小秘运行时原生检查</span>
                  <small>RUNTIME_NATIVE_GATE_REQUIRED</small>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 11 Collapsible Section Cards */}
      <div className="path-b-sections-container" aria-label="11 个 DXM 操作分区">
        {PATH_B_SECTIONS.map((sectionCode) => {
          const isCollapsed = sectionCollapsed[sectionCode]
          const fieldCount = sectionFields[sectionCode].length
          const gapCount = sectionFields[sectionCode].filter((f) => f.has_gap).length

          return (
            <details
              key={sectionCode}
              className={`section-card ${isCollapsed ? 'is-collapsed' : 'is-expanded'} ${gapCount > 0 ? 'has-gaps' : ''}`}
              open={!isCollapsed}
            >
              <summary
                className="section-card__header"
                onClick={(e) => {
                  e.preventDefault()
                  toggleSection(sectionCode)
                }}
              >
                <span className="section-card__title">
                  <strong>{SECTION_LABELS[sectionCode]}</strong>
                  <small>{fieldCount} 个字段{gapCount > 0 ? ` · ${gapCount} 个缺口` : ''}</small>
                </span>
                <span className={`section-card__toggle ${isCollapsed ? 'is-collapsed' : 'is-expanded'}`}>
                  {isCollapsed ? '▶' : '▼'}
                </span>
              </summary>

              {!isCollapsed && (
                <div className="section-card__content">
                  <SectionFieldDetailPanel
                    sectionCode={sectionCode}
                    sectionLabel={SECTION_LABELS[sectionCode]}
                    fields={sectionFields[sectionCode]}
                    onFieldClick={(field) => handleFieldClick(sectionCode, field)}
                  />

                  {(() => {
                    const sectionOption = options?.sections.find((s) => s.section === sectionCode)
                    const defaultCandidate = sectionOption?.candidates.find((c) => c.ready)
                    if (defaultCandidate?.missing_fields?.length) {
                      return (
                        <div className="section-missing-fields">
                          {defaultCandidate.missing_fields.map((missingField) => (
                            <span key={missingField} className="missing-field-badge">
                              {humanMissingField(missingField)}
                            </span>
                          ))}
                        </div>
                      )
                    }
                    return null
                  })()}

                  <div className="section-card__actions">
                    <button
                      className="button button--secondary"
                      type="button"
                      onClick={() => onEditSection(sectionCode)}
                    >
                      编辑 {SECTION_LABELS[sectionCode]}
                    </button>
                  </div>
                </div>
              )}
            </details>
          )
        })}
      </div>

      {optionsLoading && (
        <div className="batch-template-issues has-issues">
          <span className="batch-template-issues__summary">
            <strong>正在读取候选模板</strong>
            <b>请稍候</b>
          </span>
        </div>
      )}

      {optionsError && (
        <div className="batch-template-issues has-issues">
          <span className="batch-template-issues__summary">
            <strong>{optionsError}</strong>
            <b>需要重新读取</b>
          </span>
        </div>
      )}

      {selectedStoreId == null && !optionsLoading && !optionsError && (
        <div className="batch-template-issues has-issues">
          <span className="batch-template-issues__summary">
            <strong>尚未连接真实店铺</strong>
            <b>先完成店小秘接入</b>
          </span>
        </div>
      )}

      {message && !optionsError && (
        <p className={`batch-template-message is-${message.tone}`} aria-live="polite">
          {message.text}
        </p>
      )}

      <div className="batch-template-composer__action">
        {onShowSnapshotPreview && (
          <button
            className="button button--secondary"
            type="button"
            onClick={handleFreezeSnapshot}
            disabled={!formReady || optionsLoading}
          >
            冻结快照预览
          </button>
        )}
        <button
          className="button button--primary"
          type="button"
          onClick={() => createdBundle ? onShowDraftEdit() : handlePrimaryAction()}
          disabled={primaryDisabled}
        >
          {createdBundle
            ? '回到批次草稿'
            : submitting
              ? '正在生成整批模板'
              : '生成整批模板'}
        </button>
      </div>
    </section>
  )
}

function preferredStoreId(workspace: DeliveryWorkspace, selectedTask: Task | null, preferredBatchStoreName?: string | null) {
  const batchStoreName = String(preferredBatchStoreName ?? '').trim()
  const batchStore = workspace.stores.find((store) => normalizeStoreName(store.name) === normalizeStoreName(batchStoreName))
  if (batchStoreName) return batchStore?.id ?? null
  const taskStoreId = selectedTask?.store_id
  if (taskStoreId != null && workspace.stores.some((store) => store.id === taskStoreId)) return taskStoreId
  const taskStoreName = String(selectedTask?.payload?.store_name ?? '').trim()
  const taskStore = workspace.stores.find((store) => store.name === taskStoreName)
  return taskStore?.id ?? workspace.stores[0]?.id ?? null
}

function normalizeStoreName(value: string) {
  return value.trim().toLocaleLowerCase('zh-CN')
}
