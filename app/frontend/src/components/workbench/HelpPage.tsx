import type { RuntimeStatus, Task } from '../../types'

type HelpPageProps = {
  selectedTask: Task | null
  runtimeStatus: RuntimeStatus | null
  onShowDxmAccess: () => void
  onShowAcquisition: () => void
  onShowTasks: () => void
  onShowDraftEdit: () => void
  onShowBatchRecords: () => void
  onShowResults: () => void
  onShowIssues: () => void
}

const DXM_LOGGED_IN_STATES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])

export function HelpPage({
  selectedTask,
  runtimeStatus,
  onShowDxmAccess,
  onShowAcquisition,
  onShowTasks,
  onShowDraftEdit,
  onShowBatchRecords,
  onShowResults,
  onShowIssues,
}: HelpPageProps) {
  const dxmLoggedIn = DXM_LOGGED_IN_STATES.has(runtimeStatus?.dxmLogin?.status ?? '')
  const hasTask = Boolean(selectedTask)
  const nextAction = !dxmLoggedIn
    ? { label: '登录店小秘', action: onShowDxmAccess, detail: '先在可见浏览器完成登录和验证码。' }
    : !hasTask
      ? { label: '认领已有商品', action: onShowAcquisition, detail: '提供真实来源商品链接，把已有商品认领到商品箱。' }
      : { label: '创建商品箱批次', action: onShowDraftEdit, detail: '读取真实范围，选择店铺级模板并创建待批准草稿。' }

  return (
    <section className="module-layout guide-layout" aria-label="使用帮助">
      <div className="module-card span-3">
        <ModuleHead title="使用帮助" meta="受控商品箱整批流程" />
        <div className="guide-step guide-step--primary">
          <span aria-hidden="true">1</span>
          <div>
            <strong>目标只有一个：把已有来源商品认领进商品箱，再按店铺级模板逐件只保存。</strong>
            <div className="guide-step__summary-line">
              <small>{nextAction.detail}</small>
              <em>整批只批准一次，严格串行；结果不确定立即停止并转人工对账。</em>
            </div>
          </div>
          <div className="guide-step__actions">
            <button className="button button--primary" type="button" onClick={nextAction.action}>{nextAction.label}</button>
          </div>
        </div>
      </div>

      <div className="module-card span-2">
        <ModuleHead title="第一次使用怎么走" meta="按顺序完成" />
        <div className="guide-step-list">
          <GuideStep
            index="1"
            state={dxmLoggedIn ? 'is-done' : 'is-current'}
            title="登录店小秘"
            detail="打开可见的真实店小秘浏览器，输入验证码或手动处理登录问题。"
            action="打开登录页"
            onAction={onShowDxmAccess}
          />
          <GuideStep
            index="2"
            state={hasTask ? 'is-done' : dxmLoggedIn ? 'is-current' : undefined}
            title="待认领商品认领到商品箱"
            detail="必须提供支持站点的真实 HTTP(S) 商品链接；关键词和类目只用于辅助定位，不能单独发起真实认领。"
            action="创建认领任务"
            onAction={onShowAcquisition}
          />
          <GuideStep
            index="3"
            state={hasTask ? 'is-current' : undefined}
            title="冻结范围并选择店铺级模板"
            detail="从真实商品箱读取当前店铺范围，选择不绑定类目的整批模板；店小秘引用只采用 5 个可精确选择并读回的控件。"
            action="创建整批草稿"
            onAction={onShowDraftEdit}
          />
          <GuideStep
            index="4"
            title="一次批准并启动"
            detail="核对冻结范围后一次批准；系统按商品严格串行只保存。运行中的旧诊断浏览器必须先关闭，但不需要先打开它。"
            action="查看批次记录"
            onAction={onShowBatchRecords}
          />
        </div>
      </div>

      <div className="module-card">
        <ModuleHead title="每批怎么走" meta="日常操作" />
        <ol className="operation-guide">
          <li className={dxmLoggedIn ? 'is-done' : undefined}>
            <span aria-hidden="true">1</span>
            <strong>确认店小秘已登录</strong>
          </li>
          <li className={hasTask ? 'is-done' : undefined}>
            <span aria-hidden="true">2</span>
            <strong>用真实来源链接把已有商品认领到商品箱</strong>
          </li>
          <li>
            <span aria-hidden="true">3</span>
            <strong>读取当前商品箱范围，选择店铺级整批模板</strong>
          </li>
          <li>
            <span aria-hidden="true">4</span>
            <strong>一次批准后观察串行进度，完成后查看结果</strong>
          </li>
        </ol>
        <button className="button button--secondary" type="button" onClick={onShowTasks}>查看当前认领与单商品任务</button>
      </div>

      <div className="module-card">
        <ModuleHead title="失败后先看哪里" meta="恢复路径" />
        <div className="guide-step-list">
          <GuideStep
            index="1"
            title="看失败处理"
            detail="这里会用普通语言说明发生了什么、为什么不能继续、下一步点哪里。"
            action="查看失败处理"
            onAction={onShowIssues}
          />
          <GuideStep
            index="2"
            title="看保存结果"
            detail="如果任务已经执行过，先确认保存是否成功、有没有发布、证据是否生成。"
            action="查看保存结果"
            onAction={onShowResults}
          />
        </div>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="系统不会做什么" meta="安全边界" />
        <div className="settings-summary-grid">
          <div className="settings-summary-card">
            <span>不会发布</span>
            <strong>发布入口关闭</strong>
            <small>主流程只允许保存，不提供发布按钮。</small>
          </div>
          <div className="settings-summary-card">
            <span>不会并发写入</span>
            <strong>严格串行</strong>
            <small>整批范围一次批准，但始终逐件处理。</small>
          </div>
          <div className="settings-summary-card">
            <span>停止语义明确</span>
            <strong>零写入或人工对账</strong>
            <small>保存前安全停止无需对账；结果不确定才转人工对账，且不自动重试。</small>
          </div>
        </div>
      </div>
    </section>
  )
}

function ModuleHead({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="module-head">
      <h2>{title}</h2>
      <span>{meta}</span>
    </div>
  )
}

function GuideStep({
  index,
  title,
  detail,
  action,
  state,
  onAction,
}: {
  index: string
  title: string
  detail: string
  action: string
  state?: string
  onAction: () => void
}) {
  return (
    <div className={`guide-step ${state ?? ''}`}>
      <span aria-hidden="true">{index}</span>
      <div>
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
      <div className="guide-step__actions">
        <button className="button button--secondary" type="button" onClick={onAction}>{action}</button>
      </div>
    </div>
  )
}
