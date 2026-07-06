import type { RuntimeStatus, Task } from '../../types'

type HelpPageProps = {
  selectedTask: Task | null
  runtimeStatus: RuntimeStatus | null
  onShowDxmAccess: () => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowResults: () => void
  onShowIssues: () => void
}

const DXM_LOGGED_IN_STATES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])

export function HelpPage({
  selectedTask,
  runtimeStatus,
  onShowDxmAccess,
  onShowTasks,
  onShowConfig,
  onShowConsole,
  onShowResults,
  onShowIssues,
}: HelpPageProps) {
  const dxmLoggedIn = DXM_LOGGED_IN_STATES.has(runtimeStatus?.dxmLogin?.status ?? '')
  const hasTask = Boolean(selectedTask)

  return (
    <section className="module-layout guide-layout" aria-label="使用帮助">
      <div className="module-card span-3">
        <ModuleHead title="使用帮助" meta="普通用户操作指南" />
        <div className="guide-step guide-step--primary">
          <span aria-hidden="true">1</span>
          <div>
            <strong>目标只有一个：先把已有待认领商品放进商品箱，再让 Agent 只点击保存，不发布。</strong>
            <div className="guide-step__summary-line">
              <small>你按页面顺序完成登录、待认领商品认领到商品箱、填写编辑页配置，然后在真实浏览器里检查并执行只保存。</small>
              <em>发布、批量和无人值守提交不会出现在主流程里。</em>
            </div>
          </div>
          <div className="guide-step__actions">
            <button className="button button--primary" type="button" onClick={onShowDxmAccess}>从登录开始</button>
            <button className="button button--secondary" type="button" onClick={onShowTasks}>去待认领入箱</button>
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
            detail="先选择店小秘已有待认领商品，启动真实浏览器把它认领到商品箱；这里不会填写产品网址或创建新商品。"
            action="待认领入箱"
            onAction={onShowTasks}
          />
          <GuideStep
            index="3"
            state={hasTask ? 'is-current' : undefined}
            title="填写编辑页配置"
            detail="商品进入商品箱后，按店小秘编辑页分区填写店铺、类目、价格、图片、包装物流等模板取值。"
            action="填写配置"
            onAction={onShowConfig}
          />
          <GuideStep
            index="4"
            title="启动只保存"
            detail="第二段保存前先做安全检查，再在真实浏览器里人工确认页面，最后让 Agent 只点击保存。"
            action="进入执行"
            onAction={onShowConsole}
          />
        </div>
      </div>

      <div className="module-card">
        <ModuleHead title="每次只保存怎么走" meta="日常操作" />
        <ol className="operation-guide">
          <li className={dxmLoggedIn ? 'is-done' : undefined}>
            <span aria-hidden="true">1</span>
            <strong>确认店小秘已登录</strong>
          </li>
          <li className={hasTask ? 'is-done' : undefined}>
            <span aria-hidden="true">2</span>
            <strong>把已有待认领商品认领到商品箱</strong>
          </li>
          <li>
            <span aria-hidden="true">3</span>
            <strong>从商品箱创建编辑保存任务，检查模板会用哪些值</strong>
          </li>
          <li>
            <span aria-hidden="true">4</span>
            <strong>观察真实浏览器左上角进度，完成保存后查看结果</strong>
          </li>
        </ol>
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
            <span>不会批量提交</span>
            <strong>一次一个商品</strong>
            <small>当前交付范围是单商品只保存。</small>
          </div>
          <div className="settings-summary-card">
            <span>不会隐藏操作</span>
            <strong>真实浏览器可见</strong>
            <small>Agent 的关键动作会在浏览器进度中显示。</small>
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
