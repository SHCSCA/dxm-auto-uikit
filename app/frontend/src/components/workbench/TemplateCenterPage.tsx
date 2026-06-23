import { useEffect, useMemo, useState } from 'react'
import { getJsonOrDefault, patchJson, postJson } from '../../api'
import type { ConfigPreview, DeliveryWorkspace, Task, Template, TemplateCenterMetadata, TemplateCenterSection } from '../../types'

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
    { id: 'basis', label: '店铺与任务基础', template_type: 'task_basic', fields: [
      { key: 'store_name', label: '店铺', required: true, value_kind: 'text' },
      { key: 'category_name', label: '绑定类目', required: true, value_kind: 'text' },
      { key: 'claim_mark', label: '认领标记', required: true, value_kind: 'text' },
    ] },
    { id: 'title', label: '类目与标题', template_type: 'category', fields: [
      { key: 'title_prefix', label: '标题前缀', required: false, value_kind: 'text' },
      { key: 'title_suffix', label: '标题后缀', required: false, value_kind: 'text' },
      { key: 'title_cleaning_rule', label: '标题清洗规则', required: false, value_kind: 'text' },
    ] },
    { id: 'sku_price_stock', label: 'SKU / 价格 / 库存', template_type: 'sku', fields: [
      { key: 'stock', label: '库存', required: false, value_kind: 'number' },
      { key: 'price_strategy', label: '价格策略', required: false, value_kind: 'text' },
      { key: 'price_multiplier', label: '价格倍率', required: false, value_kind: 'number' },
    ] },
    { id: 'media', label: '图片与素材', template_type: 'image', fields: [
      { key: 'main_image_policy', label: '主图处理', required: false, value_kind: 'text' },
      { key: 'eu_outer_package_image', label: '欧盟外包装图', required: true, value_kind: 'text' },
      { key: 'marketing_images_strategy', label: '营销图策略', required: false, value_kind: 'text' },
    ] },
    { id: 'logistics', label: '包装物流', template_type: 'logistics', fields: [
      { key: 'logistics_type', label: '物流属性', required: true, value_kind: 'text' },
      { key: 'package_weight', label: '包裹重量', required: false, value_kind: 'number' },
      { key: 'freight_template', label: '运费模板', required: false, value_kind: 'text' },
    ] },
    { id: 'compliance', label: '合规 / 海关', template_type: 'compliance', fields: [
      { key: 'customs_cn_name', label: '海关中文名', required: false, value_kind: 'text' },
      { key: 'customs_en_name', label: '海关英文名', required: false, value_kind: 'text' },
      { key: 'brand', label: '品牌', required: false, value_kind: 'text' },
    ] },
    { id: 'semi_managed', label: '半托管', template_type: 'semi_managed', fields: [
      { key: 'semi_managed_template', label: '半托管模板', required: true, value_kind: 'text' },
      { key: 'supply_price', label: '供货价', required: false, value_kind: 'number' },
    ] },
    { id: 'dxm_reference', label: '店小秘引用模板', template_type: 'dxm_reference', fields: [
      { key: 'dxm_product_template_name', label: '产品引用模板', required: false, value_kind: 'text' },
      { key: 'dxm_logistics_template_name', label: '物流引用模板', required: false, value_kind: 'text' },
      { key: 'dxm_service_template_name', label: '服务引用模板', required: false, value_kind: 'text' },
    ] },
  ],
  source_priority: ['本次任务覆盖', '手动选择模板', '类目默认模板', '店铺默认模板', '系统默认模板', '商品原始数据'],
  actions: ['仅本次任务使用', '保存为店铺模板', '另存为新模板', '套用默认测试模板'],
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
  const [metadata, setMetadata] = useState<TemplateCenterMetadata>(fallbackTemplateCenterMetadata)
  const [activeSectionId, setActiveSectionId] = useState(fallbackTemplateCenterMetadata.sections[0].id)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [draftValues, setDraftValues] = useState<Record<string, string>>({})
  const [templateName, setTemplateName] = useState('')
  const [saveState, setSaveState] = useState({ status: '等待填写', detail: '选择分区后可保存为本次任务或店铺模板。' })
  const activeSection = metadata.sections.find((section) => section.id === activeSectionId) ?? metadata.sections[0]
  const sectionTemplates = useMemo(
    () => workspace.templates.filter((template) => template.template_type === activeSection.template_type && template.is_enabled),
    [activeSection.template_type, workspace.templates],
  )
  const activeTemplate = sectionTemplates.find((template) => String(template.id) === selectedTemplateId) ?? sectionTemplates[0] ?? null
  const selectedProduct = useMemo(() => selectedTaskProduct(workspace, selectedTask), [workspace, selectedTask])
  const currentStore = selectedTask?.payload?.store_name || workspace.stores.find((store) => store.id === selectedTask?.store_id)?.name || workspace.stores[0]?.name || '未选择店铺'
  const currentCategory = selectedProduct?.category_name || selectedTask?.payload?.category_name || '未选择类目'
  const bindingScope = `${currentStore} / ${currentCategory} / AliExpress`
  const previewGroup = configPreview?.fieldGroups.find((group) => group.templateType === activeSection.template_type || group.section === activeSection.template_type)
  const executionStatus = configPreviewLoading
    ? '正在检查执行取值'
    : configPreview?.ok
      ? '执行取值已就绪'
      : configPreviewError || '存在缺失字段'

  useEffect(() => {
    void getJsonOrDefault<TemplateCenterMetadata>('/api/template-center/metadata', fallbackTemplateCenterMetadata).then(setMetadata)
  }, [])

  useEffect(() => {
    setSelectedTemplateId(sectionTemplates[0]?.id ? String(sectionTemplates[0].id) : '')
  }, [activeSection.id, sectionTemplates])

  useEffect(() => {
    const nextValues = Object.fromEntries(
      activeSection.fields.map((field) => [field.key, templateFieldValue(activeTemplate, activeSection, field.key)]),
    )
    setDraftValues(nextValues)
    setTemplateName(activeTemplate?.template_name || `${activeSection.label}模板`)
    setSaveState({ status: activeTemplate ? '已选择模板' : '等待填写', detail: activeTemplate ? `当前套用：${activeTemplate.template_name}` : '当前分区还没有已保存模板。' })
  }, [activeSection, activeTemplate])

  function updateValue(key: string, value: string) {
    setDraftValues((current) => ({ ...current, [key]: value }))
    setSaveState({ status: '未保存修改', detail: '修改后需要保存，执行才会读取最新值。' })
  }

  async function saveForTask() {
    if (!selectedTask) {
      setSaveState({ status: '不能保存', detail: '请先在采集箱编辑保存页创建或选择任务。' })
      return
    }
    await saveWithState('正在保存到本次任务', async () => {
      await patchJson<Task>(`/api/tasks/${selectedTask.id}/config-overrides`, {
        section: activeSection.template_type,
        values: parseSectionValues(activeSection, draftValues),
      })
      setSaveState({ status: '已保存到本次任务', detail: '本次任务会优先读取这些值，不影响其他任务。' })
    })
  }

  async function saveAsStoreTemplate(copy = false) {
    await saveWithState(copy ? '正在另存为新模板' : '正在保存店铺模板', async () => {
      const body = {
        template_type: activeSection.template_type,
        template_name: copy ? `${templateName || activeSection.label} 副本` : templateName || `${activeSection.label}模板`,
        binding_scope: bindingScope,
        payload: {
          [activeSection.template_type]: parseSectionValues(activeSection, draftValues),
          binding: { store_name: currentStore, category_name: currentCategory, platform: 'AliExpress' },
        },
        is_enabled: true,
      }
      const saved = !copy && activeTemplate
        ? await patchJson<Template>(`/api/templates/${activeTemplate.id}`, body)
        : await postJson<Template>('/api/templates', body)
      setSelectedTemplateId(String(saved.id))
      setSaveState({ status: copy ? '已另存为新模板' : '已保存为店铺模板', detail: `模板 #${saved.id} ${saved.template_name} 已保存，后续匹配当前店铺/类目的任务可复用。` })
    })
  }

  function applyDefaultTemplate() {
    setDraftValues(defaultValuesForSection(activeSection))
    setTemplateName(`默认测试模板 - ${activeSection.label}`)
    setSaveState({ status: '已套用默认测试模板', detail: '这是之前测试用的示例值，执行前仍需按真实商品确认。' })
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
            <h2>多套模板管理与执行取值</h2>
            <p>按店小秘编辑页分区维护模板。执行前请确认当前任务使用哪套模板、是否已保存、最终会填写哪些值。</p>
          </div>
          <button className="button button--primary" type="button" onClick={onShowDraftEdit}>回到采集箱编辑保存</button>
        </div>
        <div className="status-grid">
          <span><strong>当前模板</strong><b>{activeTemplate?.template_name || templateName || '未选择模板'}</b></span>
          <span><strong>保存状态</strong><b>{saveState.status}</b></span>
          <span><strong>执行取值</strong><b>{executionStatus}</b></span>
        </div>
        <small className="template-center-receipt">{saveState.detail}</small>
      </div>

      <div className="module-card span-1 template-library-panel">
        <div className="module-head">
          <h2>模板清单</h2>
          <span>{workspace.templates.length} 套模板</span>
        </div>
        <label>
          <span>模板名称</span>
          <input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="例如 Dang Kang 立牌类目模板" />
        </label>
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
              <span>可套用默认测试模板后另存，或直接填写字段保存。</span>
            </div>
          )}
        </div>
      </div>

      <div className="module-card span-2 template-editor-panel">
        <div className="template-section-tabs" role="tablist" aria-label="店小秘编辑页分区">
          {metadata.sections.map((section) => (
            <button
              key={section.id}
              type="button"
              role="tab"
              aria-selected={section.id === activeSection.id}
              className={section.id === activeSection.id ? 'is-active' : ''}
              onClick={() => setActiveSectionId(section.id)}
            >
              {section.label}
            </button>
          ))}
        </div>

        <div className="module-head">
          <div>
            <h2>{activeSection.label}</h2>
            <span>范围：{bindingScope}</span>
          </div>
          <button className="button button--quiet" type="button" onClick={applyDefaultTemplate}>套用默认测试模板</button>
        </div>

        <div className="template-field-grid">
          {activeSection.fields.map((field) => {
            const previewField = previewFieldForKey(previewGroup, field.key, field.label)
            return (
              <label key={field.key}>
                <span>{field.label}{field.required ? ' *' : ''}</span>
                <input
                  value={draftValues[field.key] ?? ''}
                  onChange={(event) => updateValue(field.key, event.target.value)}
                  placeholder={`填写${field.label}`}
                />
                <small>{previewField ? `执行取值：${formatValue(previewField.value)} / ${previewField.source}` : '执行取值：等待配置检查'}</small>
              </label>
            )
          })}
        </div>

        <div className="action-row">
          <button className="button button--secondary" type="button" onClick={() => { void saveForTask() }} disabled={!selectedTask}>仅本次任务使用</button>
          <button className="button button--primary" type="button" onClick={() => { void saveAsStoreTemplate(false) }}>保存为店铺模板</button>
          <button className="button button--quiet" type="button" onClick={() => { void saveAsStoreTemplate(true) }}>另存为新模板</button>
        </div>

        <details className="inline-disclosure">
          <summary>执行取值优先级</summary>
          <div className="source-legend">
            {metadata.source_priority.map((item) => <span key={item}>{item}</span>)}
          </div>
        </details>
      </div>
    </section>
  )
}

function selectedTaskProduct(workspace: DeliveryWorkspace, selectedTask: Task | null) {
  const productId = selectedTask?.payload?.product_ids?.[0]
  return workspace.products.find((product) => product.id === productId) ?? null
}

function templateFieldValue(template: Template | null, section: TemplateCenterSection, key: string) {
  const payload = template?.payload || {}
  const grouped = payload[section.template_type]
  if (isRecord(grouped) && grouped[key] != null) return String(grouped[key])
  if (payload[key] != null) return String(payload[key])
  return ''
}

function parseSectionValues(section: TemplateCenterSection, values: Record<string, string>) {
  return Object.fromEntries(section.fields.map((field) => {
    const raw = values[field.key] ?? ''
    if (field.value_kind === 'number') {
      const numberValue = Number(raw)
      return [field.key, Number.isFinite(numberValue) && raw.trim() !== '' ? numberValue : raw]
    }
    return [field.key, raw]
  }))
}

function defaultValuesForSection(section: TemplateCenterSection) {
  return Object.fromEntries(section.fields.map((field) => [field.key, defaultValueForField(field.label)]))
}

function defaultValueForField(label: string) {
  const defaults: Record<string, string> = {
    店铺: 'Dang Kang',
    绑定类目: '立牌类谷子',
    认领标记: 'AI-OPS',
    主图处理: '保留合格 800x800 主图，异常图自动修复',
    欧盟外包装图: 'template-eu.jpg',
    物流属性: '普货',
    半托管模板: 'SMT 半托管只保存模板',
    海关中文名: '亚克力立牌',
    海关英文名: 'Acrylic stand',
  }
  return defaults[label] ?? ''
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
