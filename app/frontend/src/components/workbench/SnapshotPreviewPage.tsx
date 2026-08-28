import type {
  PlanSnapshotPreview,
  SnapshotDriftWarning,
  PathBPlanSectionCode,
} from '../../types'

type SnapshotPreviewPageProps = {
  preview: PlanSnapshotPreview
  warnings: SnapshotDriftWarning[]
  onConfirmFreeze: () => void
  onCancel: () => void
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

const CAPABILITY_LABELS: Record<string, string> = {
  video: '视频生成',
  translation: '一键翻译',
  wholesale: '批发配置',
  semiManaged: '半托管 Path B',
  rollbackPreparation: '回滚准备',
}

const DRIFT_WARNING_LABELS: Record<string, string> = {
  plan_expired: '计划已过期',
  category_drift: '类目漂移',
  schema_drift: 'schema漂移',
  catalog_drift: '目录漂移',
  draft_missing: '草稿缺失',
}

export function SnapshotPreviewPage({
  preview,
  warnings,
  onConfirmFreeze,
  onCancel,
}: SnapshotPreviewPageProps) {
  const hasBlockingWarning = warnings.some((w) => w.blocking)
  const blockingWarnings = warnings.filter((w) => w.blocking)

  return (
    <section className="module-card span-3 snapshot-preview-page" aria-label="快照预览">
      <div className="snapshot-preview-page__header">
        <div>
          <span className="eyebrow">Path B 计划冻结</span>
          <h2>确认快照预览</h2>
        </div>
      </div>

      {hasBlockingWarning && (
        <div className="snapshot-preview-page__blocking-banner" role="alert">
          <strong>阻断警告</strong>
          <p>以下问题阻止快照冻结：</p>
          <ul>
            {blockingWarnings.map((warning) => (
              <li key={warning.code}>
                <span className="warning-badge is-blocking">{DRIFT_WARNING_LABELS[warning.code] || warning.code}</span>
                <span>{warning.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.filter((w) => !w.blocking).length > 0 && (
        <div className="snapshot-preview-page__warning-banner" role="status">
          <strong>非阻断警告</strong>
          <ul>
            {warnings.filter((w) => !w.blocking).map((warning) => (
              <li key={warning.code}>
                <span className="warning-badge is-warning">{DRIFT_WARNING_LABELS[warning.code] || warning.code}</span>
                <span>{warning.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="snapshot-preview-page__content">
        <div className="snapshot-preview-page__meta">
          <h3>快照标识</h3>
          <dl>
            <dt>内容 SHA256</dt>
            <dd><code className="sha256-display">{preview.plan_content_sha256}</code></dd>
            <dt>快照实例 ID</dt>
            <dd><code className="uuid-display">{preview.snapshot_instance_id}</code></dd>
          </dl>
        </div>

        <div className="snapshot-preview-page__constraints">
          <h3>执行约束</h3>
          <dl>
            <dt>Schema 漂移策略</dt>
            <dd className={`policy-badge is-${preview.execution_constraints.schema_drift_policy}`}>
              {preview.execution_constraints.schema_drift_policy === 'block' ? '阻断' :
               preview.execution_constraints.schema_drift_policy === 'warn' ? '警告' : '允许'}
            </dd>
            <dt>目录漂移策略</dt>
            <dd className={`policy-badge is-${preview.execution_constraints.catalog_drift_policy}`}>
              {preview.execution_constraints.catalog_drift_policy === 'block' ? '阻断' :
               preview.execution_constraints.catalog_drift_policy === 'warn' ? '警告' : '允许'}
            </dd>
            <dt>最大有效期</dt>
            <dd>{preview.execution_constraints.max_age_hours} 小时</dd>
          </dl>
        </div>

        <div className="snapshot-preview-page__capabilities">
          <h3>强制能力 (不可关闭)</h3>
          <div className="capability-badges">
            {(Object.entries(preview.mandatory_capabilities) as [keyof typeof preview.mandatory_capabilities, boolean][]).map(
              ([cap, enabled]) => (
                <span
                  key={cap}
                  className={`capability-badge ${enabled ? 'is-enabled' : 'is-disabled'}`}
                >
                  {CAPABILITY_LABELS[cap] || cap}
                  {enabled ? ' ✓' : ' ✗'}
                </span>
              ),
            )}
          </div>
        </div>

        <div className="snapshot-preview-page__rollback">
          <h3>回滚计划</h3>
          <p>{preview.rollback_plan}</p>
        </div>

        <div className="snapshot-preview-page__evidence-policy">
          <h3>证据策略</h3>
          <span className="evidence-policy-badge">
            两阶段三证明 (Path B)
          </span>
        </div>

        <div className="snapshot-preview-page__items">
          <h3>计划商品 ({preview.ordered_items.length} 件)</h3>
          <table className="items-table">
            <thead>
              <tr>
                <th>#</th>
                <th>商品标题</th>
                <th>类目</th>
                <th>目标叶子类目</th>
              </tr>
            </thead>
            <tbody>
              {preview.ordered_items.map((item) => (
                <tr key={item.ordinal}>
                  <td>{item.ordinal}</td>
                  <td className="item-title">{item.product_title}</td>
                  <td>{item.category}</td>
                  <td>{item.target_leaf}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="snapshot-preview-page__actions">
        <button
          className="button button--secondary"
          type="button"
          onClick={onCancel}
        >
          取消
        </button>
        <button
          className="button button--primary"
          type="button"
          onClick={onConfirmFreeze}
          disabled={hasBlockingWarning}
          title={hasBlockingWarning ? '存在阻断问题，无法冻结快照' : '确认冻结快照'}
        >
          确认冻结快照
        </button>
      </div>
    </section>
  )
}

export { SECTION_LABELS }
