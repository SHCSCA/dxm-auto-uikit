export function DiagnosticPathNotice({ mode }: { mode?: string }) {
  if (mode !== 'single_save') return null
  return (
    <div className="gate-note" role="note">
      <strong>历史 Path A 诊断任务</strong>
      <span>单商品只保存仅用于兼容与诊断，不能代替至少三件商品、五项必经能力和 Path B 两阶段保存，也不提供完整产品批量授权。</span>
    </div>
  )
}
