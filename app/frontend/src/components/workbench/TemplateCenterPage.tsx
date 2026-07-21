import { useEffect, useMemo, useRef, useState } from 'react'
import { getJsonOrDefault, patchJson, postJson } from '../../api'
import type { ConfigPreview, DeliveryWorkspace, Task, Template, TemplateCenterMetadata, TemplateCenterSection } from '../../types'
import { BatchTemplateComposer } from './BatchTemplateComposer'

type TemplateCenterMode = 'sections' | 'batch_bundle'

type TemplateCenterPageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  onConfigSaved: () => void | Promise<void>
  onRefreshConfigPreview: () => void | Promise<void>
  onShowDraftEdit: () => void
}

const fallbackTemplateCenterMetadata: TemplateCenterMetadata = {
  sections: [
    { id: 'task_basic', label: '店铺与任务基础', template_type: 'task_basic', fields: [
      { key: 'store_name', label: '店铺', required: true, value_kind: 'text' },
      { key: 'execution_mode', label: '任务模式', required: true, value_kind: 'text' },
      { key: 'category_name', label: '绑定类目', required: false, value_kind: 'text' },
      { key: 'claim_mark', label: '认领标记', required: false, value_kind: 'text' },
    ] },
    { id: 'category', label: '类目与标题', template_type: 'category', fields: [
      { key: 'category_name', label: '目标类目', required: false, value_kind: 'text' },
      { key: 'template_category_id', label: '目标类目 ID', required: false, value_kind: 'text' },
      { key: 'category_keyword', label: '类目关键词', required: true, value_kind: 'text' },
      { key: 'title_strategy', label: '标题策略', required: false, value_kind: 'text' },
      { key: 'title_override', label: '标题覆盖值', required: false, value_kind: 'text' },
      { key: 'title_cleaning_rule', label: '标题清洗规则', required: false, value_kind: 'text' },
      { key: 'title_keyword_map', label: '标题关键词映射', required: false, value_kind: 'text' },
    ] },
    { id: 'sku', label: 'SKU / 价格 / 库存', template_type: 'sku', fields: [
      { key: 'sku_code', label: 'SKU 编码', required: false, value_kind: 'text' },
      { key: 'stock', label: '库存', required: false, value_kind: 'number' },
      { key: 'jit_stock', label: 'JIT 库存', required: false, value_kind: 'number' },
      { key: 'normal_stock', label: '普通库存', required: false, value_kind: 'number' },
      { key: 'template_sku_rule', label: 'SKU 规则', required: false, value_kind: 'text' },
      { key: 'sku_attribute_strategy', label: 'SKU 属性策略', required: false, value_kind: 'text' },
      { key: 'variant_strategy', label: '变体处理策略', required: false, value_kind: 'text' },
    ] },
    { id: 'pricing', label: '价格策略', template_type: 'pricing', fields: [
      { key: 'product_price', label: '商品价', required: false, value_kind: 'number' },
      { key: 'supply_price', label: '供货价', required: false, value_kind: 'number' },
      { key: 'price_source', label: '价格来源', required: false, value_kind: 'text' },
      { key: 'price_multiplier', label: '价格倍率', required: false, value_kind: 'number' },
      { key: 'fixed_price', label: '固定价', required: false, value_kind: 'number' },
      { key: 'price_strategy', label: '价格策略', required: false, value_kind: 'text' },
    ] },
    { id: 'image', label: '图片与素材', template_type: 'image', fields: [
      { key: 'eu_outer_package_filename', label: 'EU 外包装图', required: true, value_kind: 'text' },
      { key: 'marketing_images_strategy', label: '营销图策略', required: true, value_kind: 'text' },
      { key: 'main_image_strategy', label: '主图策略', required: false, value_kind: 'text' },
      { key: 'fallback_strategy', label: '图片不足时处理方式', required: false, value_kind: 'text' },
      { key: 'invalid_image_strategy', label: '无效图片处理', required: false, value_kind: 'text' },
      { key: 'local_asset_path', label: '本地素材路径', required: false, value_kind: 'text' },
    ] },
    { id: 'logistics', label: '包装物流', template_type: 'logistics', fields: [
      { key: 'weight', label: '重量 kg', required: true, value_kind: 'number' },
      { key: 'length', label: '长 cm', required: true, value_kind: 'number' },
      { key: 'width', label: '宽 cm', required: true, value_kind: 'number' },
      { key: 'height', label: '高 cm', required: true, value_kind: 'number' },
      { key: 'logistics_attribute', label: '物流属性', required: false, value_kind: 'text' },
      { key: 'freight_template', label: '运费模板', required: false, value_kind: 'text' },
      { key: 'service_template', label: '服务模板', required: false, value_kind: 'text' },
      { key: 'package_gross_weight', label: '包装毛重', required: false, value_kind: 'number' },
    ] },
    { id: 'compliance', label: '合规 / 海关', template_type: 'compliance', fields: [
      { key: 'customs_name', label: '报关品名', required: false, value_kind: 'text' },
      { key: 'material', label: '材质', required: false, value_kind: 'text' },
      { key: 'purpose', label: '用途', required: false, value_kind: 'text' },
      { key: 'brand', label: '品牌', required: false, value_kind: 'text' },
      { key: 'statement', label: '合规声明', required: false, value_kind: 'text' },
    ] },
    { id: 'semi_managed', label: '半托管', template_type: 'semi_managed', fields: [
      { key: 'product_price', label: '商品价', required: false, value_kind: 'number' },
      { key: 'supply_price', label: '供货价', required: false, value_kind: 'number' },
      { key: 'jit_stock', label: 'JIT 库存', required: true, value_kind: 'number' },
      { key: 'is_original_box', label: '是否原包装', required: true, value_kind: 'text' },
      { key: 'length', label: '半托管长 cm', required: true, value_kind: 'number' },
      { key: 'width', label: '半托管宽 cm', required: true, value_kind: 'number' },
      { key: 'height', label: '半托管高 cm', required: true, value_kind: 'number' },
      { key: 'goods_code_strategy', label: '货号策略', required: true, value_kind: 'text' },
      { key: 'barcode_strategy', label: '条码策略', required: true, value_kind: 'text' },
    ] },
    { id: 'dxm_reference', label: '店小秘引用模板', template_type: 'dxm_reference', fields: [
      { key: referenceFieldKey('attribute_info'), label: '属性信息模板', required: true, value_kind: 'list' },
      { key: referenceFieldKey('description'), label: '描述模板', required: true, value_kind: 'list' },
      { key: referenceFieldKey('freight'), label: '运费模板', required: true, value_kind: 'list' },
      { key: referenceFieldKey('service'), label: '服务模板', required: true, value_kind: 'list' },
      { key: referenceFieldKey('eu_responsible'), label: '欧盟责任人', required: true, value_kind: 'list' },
      { key: referenceFieldKey('manufacturer'), label: '制造商', required: true, value_kind: 'list' },
      { key: referenceFieldKey('compliance'), label: '合规模板', required: true, value_kind: 'list' },
      { key: referenceFieldKey('semi_managed'), label: '半托管模板', required: true, value_kind: 'list' },
    ] },
  ],
  source_priority: ['精确店铺/类目模板', '用户指定模板', '店铺默认模板', '系统默认模板', '商品原始数据', '高级：本次任务临时覆盖'],
  actions: ['设为店铺默认模板', '设为类目默认模板', '另存为新模板', '高级：仅本次任务临时覆盖'],
}

export function TemplateCenterPage({
  workspace,
  selectedTask,
  configPreview,
  configPreviewError,
  configPreviewLoading,
  onConfigSaved,
  onRefreshConfigPreview,
  onShowDraftEdit,
}: TemplateCenterPageProps) {
  const [templateCenterMode, setTemplateCenterMode] = useState<TemplateCenterMode>('sections')
  const [metadata, setMetadata] = useState<TemplateCenterMetadata>(fallbackTemplateCenterMetadata)
  const [activeSectionId, setActiveSectionId] = useState(fallbackTemplateCenterMetadata.sections[0].id)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templateChoiceId, setTemplateChoiceId] = useState('')
  const [draftValues, setDraftValues] = useState<Record<string, string>>({})
  const [templateName, setTemplateName] = useState('')
  const [saveState, setSaveState] = useState({ status: '等待填写', detail: '选择分区后可保存为本次任务或店铺模板。' })
  const pendingTemplateApplyNotice = useRef(false)
  const activeSection = metadata.sections.find((section) => section.id === activeSectionId) ?? metadata.sections[0]
  const sectionTemplates = useMemo(
    () => workspace.templates.filter((template) => template.template_type === activeSection.template_type && template.is_enabled),
    [activeSection.template_type, workspace.templates],
  )
  const activeTemplate = sectionTemplates.find((template) => String(template.id) === selectedTemplateId) ?? sectionTemplates[0] ?? null
  const templateChoice = sectionTemplates.find((template) => String(template.id) === templateChoiceId) ?? activeTemplate
  const selectedProduct = useMemo(() => selectedTaskProduct(workspace, selectedTask), [workspace, selectedTask])
  const currentStore = selectedTask?.payload?.store_name || workspace.stores.find((store) => store.id === selectedTask?.store_id)?.name || workspace.stores[0]?.name || '未选择店铺'
  const currentCategory = selectedProduct?.category_name || selectedTask?.payload?.category_name || '未选择类目'
  const bindingScope = `${currentStore} / ${currentCategory} / AliExpress`
  const previewGroup = configPreview?.fieldGroups.find((group) => group.templateType === activeSection.template_type || group.section === activeSection.template_type)
  const executionSection = configPreview?.executionSections?.find((section) => section.section === activeSection.id || section.section === activeSection.template_type)
  const originalValues = useMemo(
    () => Object.fromEntries(activeSection.fields.map((field) => [field.key, templateFieldValue(activeTemplate, activeSection, field.key)])),
    [activeSection, activeTemplate],
  )
  const hasUnsavedChanges = activeSection.fields.some((field) => String(draftValues[field.key] ?? '') !== String(originalValues[field.key] ?? ''))
    || Boolean(activeTemplate && templateName.trim() && templateName.trim() !== activeTemplate.template_name)
  const executionPreviewFields = executionSection?.fields.slice(0, 6) ?? previewGroup?.fields.slice(0, 6) ?? []
  const executionStatus = configPreviewLoading
    ? '正在检查执行取值'
    : configPreview?.ok
      ? '执行取值已就绪'
      : configPreviewError || '存在缺失字段'
  const executionSummary = configPreviewLoading
    ? '正在读取本次任务最终取值'
    : configPreview?.ok
      ? `本次执行会使用 ${previewGroup?.fields.length ?? 0} 个已校验字段`
      : '本次执行仍有缺失字段，请先补齐并保存'
  const nextTemplateStep = hasUnsavedChanges
    ? '先保存当前分区，保存后才会进入真实执行'
    : configPreview?.ok
      ? '可回到商品箱编辑保存'
      : '补齐缺失字段后保存'
  const sectionSummaries = useMemo(
    () => metadata.sections.map((section) => {
      const templates = workspace.templates.filter((template) => template.template_type === section.template_type && template.is_enabled).length
      const requiredFields = section.fields.filter((field) => field.required).length
      const filledRequiredFields = section.fields.filter((field) => field.required && templateFieldValue(
        workspace.templates.find((template) => template.template_type === section.template_type && template.is_enabled) ?? null,
        section,
        field.key,
      ).trim()).length
      return { section, templates, requiredFields, filledRequiredFields }
    }),
    [metadata.sections, workspace.templates],
  )
  const activeFilledCount = activeSection.fields.filter((field) => String(draftValues[field.key] ?? '').trim()).length
  const activeRequiredCount = activeSection.fields.filter((field) => field.required).length
  const activeFilledRequiredCount = activeSection.fields.filter((field) => field.required && String(draftValues[field.key] ?? '').trim()).length
  useEffect(() => {
    void getJsonOrDefault<TemplateCenterMetadata>('/api/template-center/metadata', fallbackTemplateCenterMetadata).then(setMetadata)
  }, [])

  useEffect(() => {
    const firstTemplateId = sectionTemplates[0]?.id ? String(sectionTemplates[0].id) : ''
    setSelectedTemplateId(firstTemplateId)
    setTemplateChoiceId(firstTemplateId)
  }, [activeSection.id, sectionTemplates])

  useEffect(() => {
    const nextValues = Object.fromEntries(
      activeSection.fields.map((field) => [field.key, templateFieldValue(activeTemplate, activeSection, field.key)]),
    )
    setDraftValues(nextValues)
    setTemplateName(activeTemplate?.template_name || `${activeSection.label}模板`)
    if (pendingTemplateApplyNotice.current) {
      pendingTemplateApplyNotice.current = false
      setSaveState({ status: '已套用到表单', detail: '未保存修改不会进入执行；请核对字段后保存为店铺/类目模板。' })
      return
    }
    setSaveState({ status: activeTemplate ? '已选择模板' : '等待填写', detail: activeTemplate ? `当前套用：${activeTemplate.template_name}` : '当前分区还没有已保存模板。' })
  }, [activeSection, activeTemplate])

  function updateValue(key: string, value: string) {
    setDraftValues((current) => ({ ...current, [key]: value }))
    setSaveState({ status: '未保存修改', detail: '修改后需要保存，执行才会读取最新值。' })
  }

  function applyTemplateChoice() {
    if (!templateChoice) {
      setSaveState({ status: '无法套用模板', detail: '当前分区还没有可用模板；请直接填写字段并保存为店铺或类目模板。' })
      return
    }
    pendingTemplateApplyNotice.current = true
    setSelectedTemplateId(String(templateChoice.id))
  }

  async function saveForTask() {
    if (!selectedTask) {
      setSaveState({ status: '不能保存', detail: '请先在商品箱编辑保存页创建或选择任务；临时覆盖只作为最后兜底。' })
      return
    }
    await saveWithState('正在保存临时覆盖', async () => {
      await patchJson<Task>(`/api/tasks/${selectedTask.id}/config-overrides`, {
        section: activeSection.template_type,
        values: parseSectionValues(activeSection, draftValues),
      })
      setSaveState({ status: '已保存临时覆盖', detail: '只影响当前任务；这是模板无法覆盖时的最后兜底，不作为默认使用方式。' })
    })
  }

  async function saveAsDefaultTemplate(scope: 'store' | 'category', copy = false) {
    const defaultLabel = scope === 'category' ? '类目默认模板' : '店铺默认模板'
    await saveWithState(copy ? '正在另存为新模板' : `正在设为${defaultLabel}`, async () => {
      const body = {
        template_type: activeSection.template_type,
        template_name: copy ? `${templateName || activeSection.label} 副本` : templateName || `${activeSection.label}${defaultLabel}`,
        binding_scope: bindingScope,
        payload: {
          [activeSection.template_type]: parseSectionValues(activeSection, draftValues),
          binding: defaultBinding(scope, currentStore, currentCategory),
          template_scope: scope,
        },
        is_enabled: true,
      }
      const saved = !copy && activeTemplate
        ? await patchJson<Template>(`/api/templates/${activeTemplate.id}`, body)
        : await postJson<Template>('/api/templates', body)
      setSelectedTemplateId(String(saved.id))
      setSaveState({
        status: copy ? '已另存为新模板' : `已设为${defaultLabel}`,
        detail: scope === 'category'
          ? `模板 #${saved.id} ${saved.template_name} 已保存；类目默认会优先用于当前店铺和类目的任务。`
          : `模板 #${saved.id} ${saved.template_name} 已保存；店铺默认会用于当前店铺下没有类目默认的任务。`,
      })
    })
  }

  async function disableCurrentTemplate() {
    if (!activeTemplate) {
      setSaveState({ status: '不能停用', detail: '当前分区还没有选中的已保存模板。' })
      return
    }
    await saveWithState('正在停用当前模板', async () => {
      await patchJson<Template>(`/api/templates/${activeTemplate.id}`, { is_enabled: false })
      setSelectedTemplateId('')
      setSaveState({ status: '已停用当前模板', detail: `${activeTemplate.template_name} 已停用；不会再作为后续任务的启用模板。` })
    })
  }

  async function saveWithState(label: string, action: () => Promise<void>) {
    setSaveState({ status: label, detail: '请等待当前保存动作完成。' })
    try {
      await action()
      await onConfigSaved()
      await onRefreshConfigPreview()
    } catch (error) {
      setSaveState({ status: '保存失败', detail: error instanceof Error ? error.message : '保存失败，请查看实时日志。' })
    }
  }

  return (
    <section className="module-layout template-center-page" aria-label="模板中心">
      <div className="module-card span-3">
        <div className="module-head">
          <div>
            <span className="eyebrow">模板中心</span>
            <h2>{templateCenterMode === 'sections' ? '当前任务配置摘要' : '整批模板组合'}</h2>
            <p>{templateCenterMode === 'sections'
              ? '按店小秘编辑页分区维护多套模板。默认优先使用模板；临时手工覆盖只作为最后兜底。'
              : '从 8 个已校验的分区模板组合一份可冻结的整批编辑模板。'}</p>
          </div>
          {templateCenterMode === 'sections' && (
            <button className="button button--primary" type="button" onClick={onShowDraftEdit}>回到商品箱编辑保存</button>
          )}
        </div>
        <div className="template-center-mode-switch" role="tablist" aria-label="模板中心模式">
          <button type="button" role="tab" aria-selected={templateCenterMode === 'sections'} className={templateCenterMode === 'sections' ? 'is-active' : ''} onClick={() => setTemplateCenterMode('sections')}>分区模板</button>
          <button type="button" role="tab" aria-selected={templateCenterMode === 'batch_bundle'} className={templateCenterMode === 'batch_bundle' ? 'is-active' : ''} onClick={() => setTemplateCenterMode('batch_bundle')}>整批模板</button>
        </div>
        {templateCenterMode === 'sections' && (
          <>
            <div className="template-topline" aria-label="模板中心首屏摘要">
              <span><strong>当前任务</strong><b>{selectedTask?.name || '尚未选择保存任务'}</b></span>
              <span><strong>当前分区</strong><b>{activeSection.label}</b></span>
              <span><strong>可用模板</strong><b>{sectionTemplates.length} 套</b></span>
              <span><strong>保存状态</strong><b>{hasUnsavedChanges ? '有未保存修改' : saveState.status}</b></span>
            </div>
            <div className="template-usage-confirmation" aria-label="模板使用确认">
              <span>
                <strong>当前实际使用</strong>
                <b>{activeTemplate ? activeTemplate.template_name : '还没有保存模板'}</b>
                <small>{activeTemplate ? `本次执行会使用：${activeSection.label} / ${activeTemplate.template_name}` : '当前分区没有可执行模板；请直接填写并保存为店铺或类目模板。'}</small>
              </span>
              <span>
                <strong>保存状态</strong>
                <b>{hasUnsavedChanges ? '有未保存修改' : saveState.status}</b>
                <small>未保存修改不会进入执行。</small>
              </span>
              <span>
                <strong>执行取值</strong>
                <b>{executionStatus}</b>
                <small>{executionSummary}</small>
              </span>
              <span>
                <strong>下一步</strong>
                <b>{nextTemplateStep}</b>
                <small>发布、批量和无人值守仍保持关闭。</small>
              </span>
            </div>
            <small className="template-center-receipt">{saveState.detail} 选择或修改模板只会影响当前表单，保存为模板后才会进入默认执行路径。</small>
          </>
        )}
      </div>

      {templateCenterMode === 'batch_bundle' ? (
        <BatchTemplateComposer
          workspace={workspace}
          selectedTask={selectedTask}
          initialCategoryName={currentCategory}
          onBundleCreated={onConfigSaved}
          onEditSection={(section) => {
            setActiveSectionId(section)
            setTemplateCenterMode('sections')
          }}
          onShowDraftEdit={onShowDraftEdit}
        />
      ) : (
        <>
      <div className="module-card span-1 template-section-panel">
        <div className="module-head">
          <h2>编辑页分区</h2>
          <span>一次只编辑一个分区</span>
        </div>
        <div className="template-section-list" aria-label="店小秘编辑页分区">
          {sectionSummaries.map(({ section, templates, requiredFields, filledRequiredFields }) => (
            <button
              key={section.id}
              type="button"
              className={section.id === activeSection.id ? 'is-active' : ''}
              onClick={() => setActiveSectionId(section.id)}
            >
              <strong>{section.label}</strong>
              <span>{templates} 套模板 · 必填 {filledRequiredFields}/{requiredFields || 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="module-card span-2 template-editor-panel">
        <div className="module-head">
          <div>
            <span className="eyebrow">当前分区表单</span>
            <h2>{activeSection.label}</h2>
            <span>表单正在编辑：{activeSection.label} · 范围：{bindingScope} · 已填写 {activeFilledCount}/{activeSection.fields.length}，必填 {activeFilledRequiredCount}/{activeRequiredCount || 0}</span>
          </div>
        </div>

        <div className="template-active-source" aria-label="当前模板选择">
          <label>
            <span>选择要编辑的模板</span>
            <select value={templateChoice ? String(templateChoice.id) : ''} onChange={(event) => setTemplateChoiceId(event.target.value)} disabled={!sectionTemplates.length}>
              {sectionTemplates.length ? sectionTemplates.map((template) => (
                <option value={String(template.id)} key={template.id}>{template.template_name}</option>
              )) : (
                <option value="">当前分区暂无模板</option>
              )}
            </select>
          </label>
          <label>
            <span>模板名称</span>
            <input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="例如 Dang Kang 立牌类目模板" />
          </label>
          <button className="button button--secondary" type="button" onClick={applyTemplateChoice} disabled={!templateChoice}>套用到表单</button>
        </div>

        <div className="template-field-grid">
          {activeSection.fields.map((field) => {
            const previewField = previewFieldForKey(previewGroup, field.key, field.label)
            return (
              <label key={field.key}>
                <span>{field.label}{field.required ? ' *' : ''}</span>
                {field.value_kind === 'list' ? (
                  <textarea
                    value={draftValues[field.key] ?? ''}
                    onChange={(event) => updateValue(field.key, event.target.value)}
                    placeholder={`每行填写一个${field.label}`}
                    rows={3}
                  />
                ) : (
                  <input
                    value={draftValues[field.key] ?? ''}
                    onChange={(event) => updateValue(field.key, event.target.value)}
                    placeholder={`填写${field.label}`}
                  />
                )}
                <small>{previewField ? `执行取值：${formatValue(previewField.value)} / ${previewField.source}` : '执行取值：等待配置检查'}</small>
              </label>
            )
          })}
        </div>

        <div className="template-execution-preview" aria-label="当前分区执行取值核对">
          <div>
            <strong>当前分区执行取值核对</strong>
            <span>{executionPreviewFields.length ? '保存前请核对这些最终会写入店小秘编辑页的值。' : '等待配置检查后展示本次执行最终取值。'}</span>
          </div>
          {executionPreviewFields.length ? (
            <div className="template-execution-preview__grid">
              {executionPreviewFields.map((field, index) => (
                <span key={`${field.label}-${index}`}>
                  <strong>{field.label}</strong>
                  <b>{formatValue(field.value)}</b>
                  <small>{field.source}</small>
                </span>
              ))}
            </div>
          ) : (
            <small>本次执行优先使用已保存模板；高级临时覆盖只有在你主动保存后才会生效。</small>
          )}
        </div>

        <div className="action-row">
          <button className="button button--primary" type="button" onClick={() => { void saveAsDefaultTemplate('store') }}>保存为店铺模板</button>
          <button className="button button--primary" type="button" onClick={() => { void saveAsDefaultTemplate('category') }}>保存为类目模板</button>
          <button className="button button--quiet" type="button" onClick={() => { void saveAsDefaultTemplate('category', true) }}>另存为新模板</button>
        </div>

        <details className="inline-disclosure">
          <summary>高级兜底：临时覆盖当前任务</summary>
          <p>只有当前模板无法满足这一次真实商品时才使用；默认执行路径仍然优先读取店铺/类目模板。</p>
          <button className="button button--secondary" type="button" onClick={() => { void saveForTask() }} disabled={!selectedTask}>保存为本次任务临时覆盖</button>
        </details>

        <details className="inline-disclosure template-library-details">
          <summary>更多模板管理与模板清单（共 {workspace.templates.length} 套）</summary>
          <div className="template-list">
            {sectionTemplates.length ? sectionTemplates.map((template) => (
              <button
                key={template.id}
                type="button"
                className={String(template.id) === String(activeTemplate?.id) ? 'is-selected' : ''}
                onClick={() => setSelectedTemplateId(String(template.id))}
              >
                <strong>{template.template_name}</strong>
                <span>{template.binding_scope}</span>
              </button>
            )) : (
              <div className="empty-state">
                <strong>当前分区还没有模板</strong>
                <span>请直接填写字段保存为店铺或类目模板；缺失字段会由配置检查阻止执行。</span>
              </div>
            )}
          </div>
          <button className="button button--quiet" type="button" onClick={() => { void disableCurrentTemplate() }} disabled={!activeTemplate}>停用当前模板</button>
        </details>

        <details className="inline-disclosure">
          <summary>执行取值优先级</summary>
          <div className="source-legend">
            {metadata.source_priority.map((item) => <span key={item}>{item}</span>)}
          </div>
        </details>
      </div>
        </>
      )}
    </section>
  )
}

function referenceFieldKey(section: string) {
  return `dxm_reference_templates.${section}.names`
}

function selectedTaskProduct(workspace: DeliveryWorkspace, selectedTask: Task | null) {
  const productId = selectedTask?.payload?.product_ids?.[0]
  return workspace.products.find((product) => product.id === productId) ?? null
}

function templateFieldValue(template: Template | null, section: TemplateCenterSection, key: string) {
  const payload = template?.payload || {}
  const grouped = payload[section.template_type]
  if (isRecord(grouped)) {
    const groupedValue = pathValue(grouped, key)
    if (groupedValue != null) return draftValueText(groupedValue)
    if (grouped[key] != null) return draftValueText(grouped[key])
  }
  const payloadValue = pathValue(payload, key)
  if (payloadValue != null) return draftValueText(payloadValue)
  if (payload[key] != null) return draftValueText(payload[key])
  return ''
}

function parseSectionValues(section: TemplateCenterSection, values: Record<string, string>) {
  const parsed: Record<string, unknown> = {}
  for (const field of section.fields) {
    const raw = values[field.key] ?? ''
    let value: unknown = raw
    if (field.value_kind === 'number') {
      const numberValue = Number(raw)
      value = Number.isFinite(numberValue) && raw.trim() !== '' ? numberValue : raw
    } else if (field.value_kind === 'list') {
      value = raw
        .split(/\r?\n|[，,；;]/)
        .map((item) => item.trim())
        .filter(Boolean)
    }
    setPathValue(parsed, field.key, value)
  }
  return parsed
}

function defaultBinding(scope: 'store' | 'category', storeName: string, categoryName: string) {
  const binding: Record<string, string> = {
    store_name: storeName,
    platform: 'AliExpress',
  }
  if (scope === 'category') {
    binding.category_name = categoryName
  }
  return binding
}

function previewFieldForKey(group: ConfigPreview['fieldGroups'][number] | undefined, key: string, label: string) {
  return group?.fields.find((field) => field.name === key || field.label === label || field.path.endsWith(`.${key}`))
}

function formatValue(value: unknown) {
  if (value == null || value === '') return '未填写'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function pathValue(payload: Record<string, unknown>, path: string) {
  let current: unknown = payload
  for (const part of path.split('.')) {
    if (!isRecord(current)) return undefined
    current = current[part]
  }
  return current
}

function draftValueText(value: unknown) {
  if (Array.isArray(value)) return value.join('\n')
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function setPathValue(target: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split('.')
  let current = target
  for (const part of parts.slice(0, -1)) {
    const existing = current[part]
    if (!isRecord(existing)) {
      current[part] = {}
    }
    current = current[part] as Record<string, unknown>
  }
  current[parts[parts.length - 1]] = value
}
