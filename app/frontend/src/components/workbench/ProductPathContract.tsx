import { frontendConfig } from '../../config/frontendConfig'

export function ProductPathContract({ path }: { path: 'A' | 'B' }) {
  return (
    <section className="lp-path-choice product-path-contract" aria-label="完整产品执行路径">
      <strong>主编辑页 + 半托管 · Path {frontendConfig.product.path}</strong>
      <p>每件商品必须完成视频、批发、翻译、回滚准备及两阶段只保存。保存方案不代表执行能力已放行。</p>
      <p>半托管资格仅在运行时点击“编辑半托管信息”后，由店小秘原生门裁决。目录、店铺类型和只读模板不用于资格预判。</p>
      {path === 'A' && (
        <p role="status">当前是历史 Path A 诊断方案，只能查看；不能用于完整商品批量任务。点击“改新版”按 Path B 重新配置。</p>
      )}
    </section>
  )
}
