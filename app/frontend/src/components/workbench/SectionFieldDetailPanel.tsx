import type { PlanFieldDetail, PathBPlanSectionCode } from '../../types'

type SectionFieldDetailPanelProps = {
  sectionCode: PathBPlanSectionCode
  sectionLabel: string
  fields: PlanFieldDetail[]
  onFieldClick?: (field: PlanFieldDetail) => void
}

const RISK_LABELS: Record<PlanFieldDetail['risk'], string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}

const SOURCE_LABELS: Record<PlanFieldDetail['source'], string> = {
  fixed: '固定值',
  fill: '填写值',
  dxm_template_ref: '店小秘模板引用',
  current_value: '当前值',
}

function FieldValueDisplay({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="field-value is-empty">未设置</span>
  }
  if (typeof value === 'boolean') {
    return <span className="field-value is-boolean">{value ? '是' : '否'}</span>
  }
  if (typeof value === 'number') {
    return <span className="field-value is-number">{value}</span>
  }
  if (typeof value === 'string') {
    const displayValue = value.length > 50 ? `${value.slice(0, 50)}...` : value
    return <span className="field-value is-string">{displayValue}</span>
  }
  if (Array.isArray(value)) {
    return <span className="field-value is-array">{value.length} 项</span>
  }
  if (typeof value === 'object') {
    return <span className="field-value is-object">对象</span>
  }
  return <span className="field-value">{String(value)}</span>
}

export function SectionFieldDetailPanel({
  sectionCode,
  sectionLabel,
  fields,
  onFieldClick,
}: SectionFieldDetailPanelProps) {
  const fieldsWithGap = fields.filter((f) => f.has_gap)
  const fieldsWithDiff = fields.filter(
    (f) => f.target_value !== undefined && f.current_value !== undefined && f.target_value !== f.current_value,
  )

  return (
    <div className="section-field-detail-panel" data-section={sectionCode}>
      <div className="section-field-detail-panel__header">
        <h4>{sectionLabel}</h4>
        <div className="section-field-detail-panel__stats">
          <span>{fields.length} 个字段</span>
          {fieldsWithGap.length > 0 && (
            <span className="stat-badge is-warning" title="存在缺口">
              {fieldsWithGap.length} 个缺口
            </span>
          )}
          {fieldsWithDiff.length > 0 && (
            <span className="stat-badge is-diff" title="值有变化">
              {fieldsWithDiff.length} 个变化
            </span>
          )}
        </div>
      </div>

      <div className="section-field-detail-panel__fields">
        {fields.map((field) => {
          const hasDiff = field.target_value !== undefined && field.current_value !== undefined && field.target_value !== field.current_value
          const hasGap = field.has_gap

          return (
            <div
              key={field.field_key}
              className={[
                'field-detail-row',
                hasGap ? 'has-gap' : '',
                hasDiff ? 'has-diff' : '',
                field.risk === 'high' ? 'is-high-risk' : field.risk === 'medium' ? 'is-medium-risk' : '',
              ].filter(Boolean).join(' ')}
              onClick={() => onFieldClick?.(field)}
              role={onFieldClick ? 'button' : undefined}
              tabIndex={onFieldClick ? 0 : undefined}
            >
              <div className="field-detail-row__main">
                <span className="field-label">
                  {field.ui_label_zh}
                  {field.required && <span className="required-mark">*</span>}
                </span>
                <span className="field-source">{SOURCE_LABELS[field.source]}</span>
                {hasGap && (
                  <span className="field-warning" title="缺少绑定或未解析值">
                    ⚠ 缺口
                  </span>
                )}
                {field.risk === 'high' && (
                  <span className="field-risk-badge is-high">高风险</span>
                )}
                {field.risk === 'medium' && (
                  <span className="field-risk-badge is-medium">中风险</span>
                )}
              </div>

              <div className="field-detail-row__values">
                {field.binding ? (
                  <span className="field-binding" title={`绑定: ${field.binding}`}>
                    绑定: {field.binding}
                  </span>
                ) : (
                  <span className="field-binding is-empty">无绑定</span>
                )}

                <div className="field-value-group">
                  {field.current_value !== undefined && (
                    <div className="field-value-item">
                      <span className="value-label">当前值:</span>
                      <FieldValueDisplay value={field.current_value} />
                    </div>
                  )}
                  {field.target_value !== undefined && (
                    <div className="field-value-item">
                      <span className="value-label">目标值:</span>
                      <FieldValueDisplay value={field.target_value} />
                    </div>
                  )}
                </div>
              </div>

              {field.condition && (
                <div className="field-detail-row__condition">
                  <span className="condition-label">条件:</span>
                  <span className="condition-value">{field.condition}</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export type { PlanFieldDetail }
