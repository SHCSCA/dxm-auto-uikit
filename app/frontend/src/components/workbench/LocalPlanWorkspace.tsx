import { useMemo, useState } from 'react'

import { deleteJson, postJson } from '../../api'
import type {
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

export function LocalPlanWorkspace({
  plans,
  dxmTemplateRefs,
  onChanged,
}: LocalPlanWorkspaceProps) {
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(plans[0]?.id ?? null)
  const [supersedesId, setSupersedesId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [version, setVersion] = useState('1.0.0')
  const [shopId, setShopId] = useState('')
  const [categoryIdsText, setCategoryIdsText] = useState('')
  const [categorySchemas, setCategorySchemas] = useState<Record<string, E2CategorySchema>>({})
  const [fieldDrafts, setFieldDrafts] = useState<SchemaFieldDrafts>({})
  const [selectedRefIds, setSelectedRefIds] = useState<number[]>([])
  const [provenance, setProvenance] = useState('operator_reviewed_local_plan')
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [syncingRefs, setSyncingRefs] = useState(false)

  const selectedPlan = useMemo(
    () => plans.find((plan) => plan.id === selectedPlanId) ?? plans[0] ?? null,
    [plans, selectedPlanId],
  )
  const availableRefs = dxmTemplateRefs.filter((ref) => ref.availability === 'available')

  function beginVersion(plan: LocalPlanTemplate) {
    setSelectedPlanId(plan.id)
    setSupersedesId(plan.id)
    setName(plan.name)
    setVersion(nextPatchVersion(plan.version))
    setShopId(plan.shop_id)
    setCategoryIdsText(plan.category_ids.join(', '))
    if (Object.keys(categorySchemas).length) {
      setFieldDrafts(buildFieldDrafts(categorySchemas, plan))
    }
    setSelectedRefIds(plan.dxm_template_refs.map((binding) => binding.ref_id))
    setProvenance(plan.provenance)
    setMessage(null)
  }

  function toggleRef(refId: number) {
    setSelectedRefIds((current) => current.includes(refId)
      ? current.filter((value) => value !== refId)
      : [...current, refId])
  }

  async function savePlan() {
    setSubmitting(true)
    setMessage(null)
    try {
      const categoryIds = categoryIdsText
        .split(/[\s,，;；]+/)
        .map((value) => value.trim())
        .filter(Boolean)
      if (
        categoryIds.length === 0
        || categoryIds.some((categoryId) => !categorySchemas[categoryId])
      ) {
        throw new Error('请先从当前真实会话同步全部类目 Schema')
      }
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
        version: version.trim(),
        shop_id: shopId.trim(),
        category_ids: categoryIds,
        path: 'A',
        fixed_values: {
          publish_allowed: false,
          field_values: fixedFieldValues,
        },
        fill_rules: fillRules,
        dxm_template_refs: refs,
        field_mappings: fieldMappings,
        validation_policy: {
          required_fields: 'fail_closed',
          natural_language: 'english_before_save',
        },
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
        text: `已保存 local_plan_template #${created.id} · ${created.version}。旧版本未被修改。`,
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

  async function syncReadonlyRefs() {
    setSyncingRefs(true)
    setMessage(null)
    try {
      const categoryIds = parseCategoryIds(categoryIdsText)
      const normalizedShopId = shopId.trim()
      if (!/^[1-9][0-9]*$/.test(normalizedShopId)) {
        throw new Error('只读同步前必须填写稳定的真实 shopId')
      }
      const result = await postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync', {
        shop_id: normalizedShopId,
        category_ids: categoryIds,
      })
      setCategorySchemas(result.category_schemas)
      setFieldDrafts(buildFieldDrafts(
        result.category_schemas,
        supersedesId ? selectedPlan : null,
      ))
      await onChanged()
      setMessage({
        tone: 'success',
        text: `已从当前真实会话同步 ${result.refs.length} 个只读引用；session_ref ${result.session_ref}。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '店小秘只读引用同步失败。',
      })
    } finally {
      setSyncingRefs(false)
    }
  }

  async function archiveSelectedPlan() {
    if (!selectedPlan || !selectedPlan.is_active) return
    if (!window.confirm(`确认归档“${selectedPlan.name} · v${selectedPlan.version}”吗？已冻结任务不会改变。`)) {
      return
    }
    setSubmitting(true)
    setMessage(null)
    try {
      const archived = await deleteJson<LocalPlanTemplate>(
        `/api/local-plan-templates/${selectedPlan.id}`,
      )
      await onChanged()
      setMessage({
        tone: 'success',
        text: `已归档 local_plan_template #${archived.id}；内容与既有任务快照仍保留。`,
      })
    } catch (error) {
      setMessage({
        tone: 'error',
        text: error instanceof Error ? error.message : '本地方案归档失败。',
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
          ...(current[categoryId]?.[fieldKey] ?? {
            uiLabelZh: '',
            strategy: 'inherit',
            value: undefined,
          }),
          ...patch,
        },
      },
    }))
  }

  return (
    <div className="e2-plan-workspace span-3" aria-label="E2 铺货方案工作区">
      <section className="module-card e2-plan-library" aria-label="本地铺货方案版本">
        <div className="module-head">
          <div>
            <span className="eyebrow">local_plan_template · 可编辑 / 可版本化</span>
            <h2>本地铺货方案</h2>
            <p>方案变更创建新版本；已经冻结的任务不会跟随变化。</p>
          </div>
          <div className="e2-ref-sync-actions">
            <button
              className="button button--secondary"
              type="button"
              disabled={!selectedPlan}
              onClick={() => selectedPlan && beginVersion(selectedPlan)}
            >
              基于所选版本新建
            </button>
            <button
              className="button button--quiet"
              type="button"
              disabled={!selectedPlan?.is_active || submitting}
              onClick={() => { void archiveSelectedPlan() }}
            >
              归档所选版本
            </button>
          </div>
        </div>
        <div className="e2-plan-version-list">
          {plans.length ? plans.map((plan) => (
            <button
              type="button"
              key={plan.id}
              className={plan.id === selectedPlan?.id ? 'is-selected' : ''}
              onClick={() => setSelectedPlanId(plan.id)}
            >
              <strong>{plan.name}</strong>
              <span>v{plan.version} · 店铺 {plan.shop_id} · {plan.is_active ? '可用' : '已归档'}</span>
              <small>类目 {plan.category_ids.join('、')} · #{plan.id}</small>
            </button>
          )) : (
            <div className="empty-state">
              <strong>还没有本地方案</strong>
              <span>右侧创建首个 Path A 方案；不会写入店小秘模板。</span>
            </div>
          )}
        </div>
        {selectedPlan && (
          <dl className="e2-plan-review">
            <div><dt>固定路径</dt><dd>Path A · 只保存不发布</dd></div>
            <div><dt>自然语言</dt><dd>保存前必须检测为英文</dd></div>
            <div><dt>异常策略</dt><dd>UNKNOWN 停批</dd></div>
            <div><dt>来源</dt><dd>{selectedPlan.provenance}</dd></div>
          </dl>
        )}
      </section>

      <section className="module-card e2-ref-library" aria-label="店小秘只读模板引用">
        <div className="module-head">
          <div>
            <span className="eyebrow">dxm_template_ref · 只读</span>
            <h2>店小秘模板引用</h2>
            <p>显示名仅供人工确认；执行身份使用模板 ID、店铺/类目作用域与来源摘要。</p>
          </div>
          <div className="e2-ref-sync-actions">
            <span className="status-pill neutral">不提供修改接口</span>
            <button
              className="button button--secondary"
              type="button"
              disabled={syncingRefs}
              onClick={() => { void syncReadonlyRefs() }}
            >
              {syncingRefs ? '正在只读同步…' : '从当前真实会话同步'}
            </button>
          </div>
        </div>
        <div className="e2-ref-list">
          {dxmTemplateRefs.length ? dxmTemplateRefs.map((ref) => (
            <label key={ref.id} className={ref.availability === 'available' ? '' : 'is-drifted'}>
              <input
                type="checkbox"
                checked={selectedRefIds.includes(ref.id)}
                disabled={ref.availability !== 'available'}
                onChange={() => toggleRef(ref.id)}
              />
              <span>
                <strong>{ref.observed_display_name}</strong>
                <small>{ref.ref_type} · DXM #{ref.dxm_template_id}</small>
                <small>shopId {ref.shop_id} · categoryId {ref.category_id ?? '店铺级'}</small>
                <small>已解析字段 {ref.resolved_field_count} · 值 hash {ref.resolved_values_hash.slice(0, 12)}</small>
              </span>
              <b>{ref.availability === 'available' ? '可用' : '漂移 / 不可用'}</b>
            </label>
          )) : (
            <div className="empty-state">
              <strong>没有已同步的只读引用</strong>
              <span>先通过受控只读同步取得真实模板 ID；不得手填显示名冒充引用。</span>
            </div>
          )}
        </div>
      </section>

      <section className="module-card e2-plan-editor" aria-label="创建本地方案版本">
        <div className="module-head">
          <div>
            <span className="eyebrow">{supersedesId ? `新版本 · 基于 #${supersedesId}` : '新方案'}</span>
            <h2>方案内容</h2>
            <p>界面与映射使用中文；自动写入的标题、描述等自然语言值必须填英文。</p>
          </div>
        </div>
        <div className="e2-plan-editor__grid">
          <label><span>方案名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 普货英语补差方案" /></label>
          <label><span>版本</span><input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0.0" /></label>
          <label><span>shopId</span><input value={shopId} onChange={(event) => setShopId(event.target.value)} placeholder="真实店铺 ID" /></label>
          <label><span>categoryId（逗号分隔）</span><input value={categoryIdsText} onChange={(event) => setCategoryIdsText(event.target.value)} placeholder="例如 100, 200" /></label>
          <div className="span-2 e2-structured-plan" aria-label="按类目结构化配置">
            <div className="e2-structured-plan__head">
              <span>
                <strong>类目字段与补差值</strong>
                <small>Schema 来自当前真实会话；留空表示优先沿用当前值或店小秘只读模板。</small>
              </span>
              <span className="status-pill neutral">
                {Object.keys(categorySchemas).length
                  ? `${Object.keys(categorySchemas).length} 个类目已同步`
                  : '等待只读同步'}
              </span>
            </div>
            {Object.entries(categorySchemas).map(([categoryId, schema]) => (
              <section
                className="e2-category-fields"
                key={categoryId}
                aria-label={`类目 ${categoryId} 字段`}
              >
                <header>
                  <span>
                    <strong>categoryId {categoryId}</strong>
                    <small>
                      必填 {schema.required.length} 项 · 字段 {Object.keys(schema.properties).length} 项
                    </small>
                    {schema.price_policy && (
                      <small>
                        价格关系已冻结：SKU 货值不得高于 SKU 售价；SKU 售价须在最低/最高价范围内。
                      </small>
                    )}
                  </span>
                  <span className="status-pill neutral">独立映射</span>
                </header>
                <div className="e2-category-fields__rows">
                  {Object.entries(schema.properties).map(([fieldKey, definition], index) => {
                    const draft = fieldDrafts[categoryId]?.[fieldKey] ?? {
                      uiLabelZh: schemaLabel(definition, index),
                      strategy: 'inherit' as const,
                      value: undefined,
                    }
                    const required = schema.required.includes(fieldKey)
                    return (
                      <div className="e2-schema-field" key={fieldKey}>
                        <div className="e2-schema-field__identity">
                          <label>
                            <span>中文字段名</span>
                            <input
                              value={draft.uiLabelZh}
                              onChange={(event) => updateFieldDraft(
                                categoryId,
                                fieldKey,
                                { uiLabelZh: event.target.value },
                              )}
                            />
                          </label>
                          <span>
                            <code>{fieldKey}</code>
                            {required && <b>必填</b>}
                            {definition.natural_language === true && <b>英文内容</b>}
                          </span>
                        </div>
                        <div className="e2-schema-field__configuration">
                          <label className="e2-schema-field__strategy">
                            <span>来源策略</span>
                            <select
                              aria-label={`${fieldKey} 来源策略`}
                              value={draft.strategy}
                              onChange={(event) => updateFieldDraft(
                                categoryId,
                                fieldKey,
                                {
                                  strategy: event.target.value as SchemaFieldDraft['strategy'],
                                },
                              )}
                            >
                              <option value="inherit">继承（店小秘模板 → 商品当前值）</option>
                              <option value="fill">补差规则（覆盖继承值）</option>
                              <option value="fixed">固定值（最高优先）</option>
                            </select>
                          </label>
                          {draft.strategy === 'inherit' && (
                            <div className="e2-schema-field__readonly">
                              <span>执行时先取店小秘只读模板，再回退商品当前值</span>
                              <small>此字段不会写入本地固定值或补差规则。</small>
                            </div>
                          )}
                          {draft.strategy !== 'inherit' && (
                            <SchemaValueEditor
                              definition={definition}
                              fieldKey={fieldKey}
                              value={draft.value}
                              valueLabel={draft.strategy === 'fixed' ? '固定值' : '补差值'}
                              onChange={(value) => updateFieldDraft(
                                categoryId,
                                fieldKey,
                                { value },
                              )}
                            />
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            ))}
            {!Object.keys(categorySchemas).length && (
              <div className="empty-state">
                <strong>尚未取得类目 Schema</strong>
                <span>填写 shopId 与 categoryId 后，点击上方“从当前真实会话同步”。</span>
              </div>
            )}
          </div>
          <label className="span-2"><span>来源说明</span><input value={provenance} onChange={(event) => setProvenance(event.target.value)} /></label>
        </div>
        <div className="e2-plan-editor__footer">
          <span>
            <strong>硬门禁</strong>
            <small>Path A · publish_allowed=false · 必填 fail-closed · 英文保存前校验</small>
          </span>
          <button className="button button--primary" type="button" disabled={submitting} onClick={() => { void savePlan() }}>
            {submitting ? '正在校验…' : supersedesId ? '创建新版本' : '创建本地方案'}
          </button>
        </div>
        {message && <p className={`e2-plan-message ${message.tone}`} role="status">{message.text}</p>}
      </section>
    </div>
  )
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
  return Object.fromEntries(
    Object.entries(schemas).map(([categoryId, schema]) => {
      const existingRules = plan?.fill_rules[categoryId] ?? {}
      const fixedByCategory = plan?.fixed_values.field_values
      const existingFixed = (
        fixedByCategory
        && typeof fixedByCategory === 'object'
        && !Array.isArray(fixedByCategory)
        && typeof (fixedByCategory as Record<string, unknown>)[categoryId] === 'object'
        && !Array.isArray((fixedByCategory as Record<string, unknown>)[categoryId])
      )
        ? (fixedByCategory as Record<string, Record<string, unknown>>)[categoryId]
        : {}
      const existingLabels = new Map(
        (plan?.field_mappings[categoryId]?.entries ?? []).map((entry) => [
          entry.field_key,
          entry.ui_label_zh,
        ]),
      )
      return [
        categoryId,
        Object.fromEntries(
          Object.entries(schema.properties).map(([fieldKey, definition], index) => [
            fieldKey,
            {
              uiLabelZh: existingLabels.get(fieldKey) ?? schemaLabel(definition, index),
              strategy: Object.prototype.hasOwnProperty.call(existingFixed, fieldKey)
                ? 'fixed'
                : existingRules[fieldKey]
                  ? 'fill'
                  : 'inherit',
              value: Object.prototype.hasOwnProperty.call(existingFixed, fieldKey)
                ? existingFixed[fieldKey]
                : existingRules[fieldKey]?.value,
            },
          ]),
        ),
      ]
    }),
  )
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
    if (!schema) throw new Error(`类目 ${categoryId} 缺少当前真实 Schema`)
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
      const uiLabelZh = draft.uiLabelZh.trim()
      if (!/[\u3400-\u9fff]/.test(uiLabelZh)) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 缺少中文字段名`)
      }
      if (draft.strategy !== 'inherit' && !isConfiguredValue(draft.value)) {
        throw new Error(
          `类目 ${categoryId} 字段 ${fieldKey} 已选择${draft.strategy === 'fixed' ? '固定值' : '补差规则'}但没有操作值`,
        )
      }
      if (draft.strategy === 'fill' && isConfiguredValue(draft.value)) {
        fillRules[categoryId][fieldKey] = { value: draft.value }
      }
      if (draft.strategy === 'fixed' && isConfiguredValue(draft.value)) {
        fixedFieldValues[categoryId][fieldKey] = draft.value
      }
      const uiBinding = definition.ui_binding
      if (
        typeof uiBinding !== 'string'
        || !/^dxm_(?:editor:[A-Za-z][A-Za-z0-9_]*|attribute:[1-9][0-9]*)$/.test(uiBinding)
      ) {
        throw new Error(`类目 ${categoryId} 字段 ${fieldKey} 缺少后端验证的 UI binding`)
      }
      return {
        ui_label_zh: uiLabelZh,
        field_key: fieldKey,
        category_schema_path: `$.properties.${fieldKey}`,
        ui_binding: uiBinding,
      }
    })
    fieldMappings[categoryId] = {
      mapping_version: `zh-map-${categoryId}-ui-v1`,
      entries,
    }
  }
  return { fillRules, fixedFieldValues, fieldMappings }
}

function schemaLabel(definition: E2CategorySchemaProperty, index: number) {
  const label = typeof definition.ui_label_zh === 'string'
    ? definition.ui_label_zh.trim()
    : ''
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
  const values = Array.isArray(definition.values)
    ? definition.values
    : null
  const enumValues = Array.isArray(definition.enum)
    ? definition.enum
    : null
  if (values || enumValues) {
    const options = values
      ? values.map((item) => ({
        value: String(item.id),
        label: item.names?.zh
          ? `${item.names.zh} · ${item.id}`
          : item.name
            ? `${item.name} · ${item.id}`
            : String(item.id),
      }))
      : (enumValues ?? []).map((item) => ({
        value: String(item),
        label: String(item),
      }))
    return (
      <label className="e2-schema-field__value">
        <span>{valueLabel}</span>
        <select
          aria-label={`${fieldKey} ${valueLabel}`}
          multiple={definition.type === 'array'}
          value={definition.type === 'array'
            ? Array.isArray(value)
              ? value.map(String)
              : []
            : value == null
              ? ''
              : String(value)}
          onChange={(event) => onChange(
            definition.type === 'array'
              ? Array.from(event.target.selectedOptions).map(
                (option) => option.value,
              )
              : event.target.value || undefined,
          )}
        >
          {definition.type !== 'array' && (
            <option value="">沿用当前值 / 只读模板</option>
          )}
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
          onChange={(event) => onChange(
            event.target.value === ''
              ? undefined
              : event.target.value === 'true',
          )}
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
          onChange={(event) => onChange(
            event.target.value === ''
              ? undefined
              : Number(event.target.value),
          )}
        />
      </label>
    )
  }
  if (definition.type === 'object' && definition.properties) {
    const objectValue = (
      typeof value === 'object'
      && value !== null
      && !Array.isArray(value)
    ) ? value as Record<string, unknown> : {}
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
          onClick={() => onChange([
            ...arrayValue,
            emptyValueForSchema(definition.items as E2CategorySchemaProperty),
          ])}
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
        placeholder={definition.natural_language === true
          ? '只填英文；留空沿用当前值 / 模板'
          : '留空沿用当前值 / 只读模板'}
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
