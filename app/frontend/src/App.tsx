import { useEffect, useMemo, useState } from 'react'
import { getJson, postJson } from './api'
import type { Evidence, ExceptionItem, LiveEvent, LogItem, Product, Store, Task, Template } from './types'

const seedRows = [
  { title: 'Women Running Shoes Breathable Lightweight', category_name: '运动鞋', price: 29.9, sku_count: 3, image_count: 6 },
  { title: 'Kitchen Storage Rack Multi Layer Organizer', category_name: '厨房收纳', price: 18.5, sku_count: 2, image_count: 5 },
  { title: 'LED Table Lamp Smart Touch Dimmable', category_name: '台灯', price: 24.8, sku_count: 4, image_count: 7 },
]

const flowNav = [
  '官网登录',
  '产品',
  '数据采集',
  '认领到采集箱',
  '采集箱备注',
  '编辑产品',
  '待发布 / 发布',
  '异常协作',
  '模板中心',
]

const navTargetMap: Partial<Record<typeof flowNav[number], string>> = {
  '产品': 'product',
  '数据采集': 'data_acquisition',
  '认领到采集箱': 'draft_box',
  '采集箱备注': 'draft_box',
  '编辑产品': 'draft_box',
  '待发布 / 发布': 'draft_box',
}

type FlowNavItem = typeof flowNav[number]
type StepMeta = { code: string; title: string; desc: string; statusText: string; tagClass: string; active: boolean }
type LoginSummary = {
  stage: 'not_started' | 'waiting_captcha' | 'logged_in' | 'login_problem'
  title: string
  detail: string
  nextAction: string
  userAction: string
  tagClass: string
  stageLabel: string
}
type DemoStage = 'system' | 'waiting_captcha' | 'login_success'
type BrowserMode = 'live' | 'evidence'

export default function App() {
  const [stores, setStores] = useState<Store[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [logs, setLogs] = useState<LogItem[]>([])
  const [evidences, setEvidences] = useState<Evidence[]>([])
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([])
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [liveStatus, setLiveStatus] = useState<any>(null)
  const [loginState, setLoginState] = useState<any>(null)
  const [loginUsername, setLoginUsername] = useState('master-demo')
  const [loginPassword, setLoginPassword] = useState('demo-pass')
  const [activeNav, setActiveNav] = useState<FlowNavItem>('官网登录')
  const [demoStage, setDemoStage] = useState<DemoStage>('system')
  const [manualMode, setManualMode] = useState(false)
  const [browserMode, setBrowserMode] = useState<BrowserMode>('live')
  const [interactionMessage, setInteractionMessage] = useState('先点击左侧真实业务导航或登录动作按钮，演示台现在会即时反馈状态。')
  const [draftNoteText, setDraftNoteText] = useState('AI认领')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const selectedTask = useMemo(() => tasks.find((item) => item.id === selectedTaskId) ?? tasks[0] ?? null, [tasks, selectedTaskId])
  const currentStore = stores[0]
  const currentProduct = products[0]
  const currentStep = liveEvents.find((event) => event.type === 'step_update')
  const currentEvidence = evidences[0]

  async function refreshAll() {
    const [storesData, templatesData, productsData, tasksData, logsData, evidencesData, exceptionsData, liveStatusData, loginStateData] = await Promise.all([
      getJson<Store[]>('/api/stores'),
      getJson<Template[]>('/api/templates'),
      getJson<Product[]>('/api/products'),
      getJson<Task[]>('/api/tasks'),
      getJson<LogItem[]>('/api/logs'),
      getJson<Evidence[]>('/api/evidences'),
      getJson<ExceptionItem[]>('/api/exceptions'),
      getJson<any>('/api/dxm/live-status'),
      getJson<any>('/api/dxm/login-state'),
    ])
    setStores(storesData)
    setTemplates(templatesData)
    setProducts(productsData)
    setTasks(tasksData)
    setLogs(logsData)
    setEvidences(evidencesData)
    setExceptions(exceptionsData)
    setLiveStatus(liveStatusData)
    setLoginState(loginStateData)
    if (!selectedTaskId && tasksData[0]) setSelectedTaskId(tasksData[0].id)
  }

  useEffect(() => {
    void refreshAll()
  }, [])

  useEffect(() => {
    if (!selectedTaskId) return
    const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/tasks/${selectedTaskId}`)
    ws.onopen = () => ws.send('subscribe')
    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data) as LiveEvent
      setLiveEvents((prev) => [payload, ...prev].slice(0, 50))
      void refreshAll()
    }
    return () => ws.close()
  }, [selectedTaskId])

  async function bootstrapDemo() {
    setBusy(true)
    try {
      let store = stores[0]
      if (!store) {
        store = await postJson<Store>('/api/stores/connect', { name: 'Dang Kang', platform: 'AliExpress' })
      }
      if (templates.length === 0) {
        await Promise.all([
          postJson('/api/templates', { template_type: 'title', template_name: '标题模板', binding_scope: '平台 / 店铺 / 类目', payload: { rule: '核心词 + 属性词 + 卖点词' }, is_enabled: true }),
          postJson('/api/templates', { template_type: 'category', template_name: '类目与资质模板', binding_scope: '平台 / 类目', payload: { category: '类目映射 / 品牌资质 / PDF资质' }, is_enabled: true }),
          postJson('/api/templates', { template_type: 'image', template_name: '图片模板', binding_scope: '店铺 / 类目', payload: { content: '主图 / 白底图 / 营销图 / 视频' }, is_enabled: true }),
          postJson('/api/templates', { template_type: 'pricing', template_name: 'SKU/价格模板', binding_scope: '店铺 / 类目 / 物流', payload: { content: '颜色尺码 / 计价 / 基准价' }, is_enabled: true }),
          postJson('/api/templates', { template_type: 'compliance', template_name: '半托管与合规模板', binding_scope: '店铺 / 类目 / 国家站点', payload: { content: '欧盟责任人 / 制造商 / 含税报价' }, is_enabled: true }),
        ])
      }
      let importedProducts = products
      if (importedProducts.length === 0) {
        importedProducts = await postJson<Product[]>('/api/products/import', { rows: seedRows })
      }
      const task = await postJson<Task>('/api/tasks', {
        name: '速卖通真实流程演示批次',
        store_id: store.id,
        mode: 'save_draft',
        publish_scene: 'POP',
        product_ids: importedProducts.map((item) => item.id),
      })
      setSelectedTaskId(task.id)
      await refreshAll()
    } finally {
      setBusy(false)
    }
  }

  async function startSelectedTask() {
    if (!selectedTask) return
    await postJson(`/api/tasks/${selectedTask.id}/start`, {})
    setActiveNav('数据采集')
    setInteractionMessage('任务已启动，演示焦点自动切到“数据采集”，方便用户继续跟踪真实流程。')
    await refreshAll()
  }

  async function handleNavClick(item: FlowNavItem) {
    setActiveNav(item)
    const target = navTargetMap[item]
    if (target) {
      setBusy(true)
      try {
        const result = await postJson<any>('/api/dxm/navigate', { target })
        setLoginState(result)
        setDemoStage(result.stage === 'workflow_navigation' ? 'login_success' : demoStage)
        setInteractionMessage(`已切换到「${item}」并调用真实业务导航，当前页面已尝试进入对应业务节点。`)
      } catch (error) {
        setInteractionMessage(`切换到「${item}」失败：${error instanceof Error ? error.message : '未知错误'}`)
      } finally {
        setBusy(false)
        await refreshAll()
      }
      return
    }
    setInteractionMessage(`已切换到「${item}」视角，演示内容会围绕这个真实业务节点高亮。`)
    if (item === '异常协作') setManualMode(true)
    if (item === '官网登录') setBrowserMode('live')
  }

  async function handleWaitCaptcha() {
    setBusy(true)
    try {
      const result = await postJson<any>('/api/dxm/login/start', {
        username: loginUsername,
        password: loginPassword,
      })
      setLoginState(result)
      setDemoStage('waiting_captcha')
      setActiveNav('官网登录')
      setInteractionMessage('已调用真实登录 start：账号密码状态已提交，界面进入验证码等待态。')
    } finally {
      setBusy(false)
      await refreshAll()
    }
  }

  async function handleContinueLogin() {
    setBusy(true)
    try {
      const result = await postJson<any>('/api/dxm/login/continue', { confirm: true })
      setLoginState(result)
      setDemoStage(result.stage === 'login_success' ? 'login_success' : 'waiting_captcha')
      setActiveNav(result.stage === 'login_success' ? '产品' : '官网登录')
      setManualMode(result.stage !== 'login_success')
      setInteractionMessage(result.stage === 'login_success'
        ? '已调用真实登录 continue：检测到登录成功，界面切到业务流起点。'
        : '已调用真实登录 continue：当前仍未确认登录成功，请检查验证码或人工接管。')
    } finally {
      setBusy(false)
      await refreshAll()
    }
  }

  function handleToggleManualMode() {
    setManualMode((prev) => {
      const next = !prev
      setActiveNav(next ? '异常协作' : activeNav)
      setInteractionMessage(next ? '已开启人工接管视角：界面会强调协作、阻塞原因和下一步建议。' : '已退出人工接管视角，回到自动执行观察模式。')
      return next
    })
  }

  function handleBrowserModeChange(mode: BrowserMode) {
    setBrowserMode(mode)
    setInteractionMessage(mode === 'live' ? '已切回实时页面观察模式。' : '已切到证据观察模式，适合给用户解释为什么系统停在这里。')
  }

  async function handleDraftBoxAction(action: 'remark' | 'edit') {
    setBusy(true)
    try {
      const result = await postJson<any>('/api/dxm/draft-box/action', {
        action,
        note_text: action === 'remark' ? draftNoteText : null,
      })
      setLoginState(result)
      setActiveNav(action === 'remark' ? '采集箱备注' : '编辑产品')
      setDemoStage('login_success')
      setInteractionMessage(action === 'remark'
        ? `已调用真实采集箱备注动作，目标备注：${draftNoteText}`
        : '已调用真实采集箱编辑动作，下一步应进入编辑页链路。')
    } finally {
      setBusy(false)
      await refreshAll()
    }
  }

  const importedCount = products.length || 128
  const pendingManualCount = exceptions.length || 18
  const blockedCount = exceptions.length ? Math.max(1, exceptions.length - 1) : 8
  const passCount = Math.max(0, importedCount - pendingManualCount - blockedCount)
  const steps = buildSteps(currentStep, selectedTask?.status, liveStatus)
  const currentEvidenceUrl = toArtifactUrl((currentEvidence as any)?.file_path_url || currentEvidence?.file_path)
  const liveHomeUrl = toArtifactUrl(liveStatus?.home_screenshot_url || liveStatus?.home_screenshot)
  const liveProductUrl = toArtifactUrl(liveStatus?.product_page?.screenshot_url || liveStatus?.product_page?.screenshot)
  const activeScreenshotUrl = currentEvidenceUrl || liveProductUrl || liveHomeUrl
  const systemLoginSummary = getLoginSummary(loginState, liveStatus)
  const loginSummary = getInteractiveLoginSummary(systemLoginSummary, demoStage, manualMode)
  const coverageData = buildCoverageData(templates, currentStore)
  const selectedTemplateRows = buildTemplateRows(templates)
  const pageTitle = browserMode === 'evidence'
    ? '证据解读视图'
    : liveStatus?.product_page?.title || loginState?.page_title || liveStatus?.title || '店小秘官网 / 登录页'
  const pageUrl = browserMode === 'evidence'
    ? `demo://focus/${encodeURIComponent(activeNav)}`
    : liveStatus?.product_page?.url || loginState?.page_url || liveStatus?.final_url || 'https://www.dianxiaomi.com/'
  const pageFeedback = manualMode
    ? '当前已切到人工协作视角：优先解释阻塞原因、用户动作和恢复路径。'
    : liveStatus?.product_page?.text || liveStatus?.body_text || '当前尚未接入真实页面文本，请从官网登录开始建立会话。'

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo">DX</div>
          <div>
            <h1>店小秘真实流程演示台</h1>
            <small>从用户视角组织登录、认领、采集箱、编辑与发布，不再用猜测页面做演示</small>
          </div>
        </div>
        <div className="status-row">
          <div className="chip ok">设计原则：<strong>先真实，再自动化</strong></div>
          <div className={`chip ${loginSummary.tagClass}`}>登录阶段：<strong>{loginSummary.stageLabel}</strong></div>
          <div className={`chip ${stores.length ? 'ok' : 'warn'}`}>当前店铺：<strong>{currentStore?.name ?? 'Dang Kang'}</strong></div>
          <div className="chip">模板命中：<strong>{selectedTemplateRows.length || 5} 项</strong></div>
          <div className="chip">人工协作：<strong>{pendingManualCount} 项</strong></div>
        </div>
      </header>

      <main className={`main ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
        <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="sidebar-topbar">
            {!sidebarCollapsed && <div className="nav-title">真实业务导航</div>}
            <button className="sidebar-toggle" type="button" onClick={() => setSidebarCollapsed((prev) => !prev)}>
              {sidebarCollapsed ? '☰' : '⇤'}
            </button>
          </div>
          {flowNav.map((item) => (
            <button
              key={item}
              type="button"
              className={`nav-item ${item === activeNav ? 'active' : ''}`}
              onClick={() => handleNavClick(item)}
              title={item}
            >
              {sidebarCollapsed ? item.slice(0, 2) : item}
            </button>
          ))}
          {!sidebarCollapsed && (
            <div className="sidebar-note">
              <strong>产品经理视角</strong>
              <span>桌面版最终会交付 exe，必须让客户首屏就看懂，不靠滚动找信息。</span>
              <span>当前焦点：{activeNav}</span>
            </div>
          )}
        </aside>

        <section className="panel compact-panel">
          <div className="workspace-grid">
            <div className="workspace-card workspace-card--wide">
              <div className="section-head">
                <h2>登录协作</h2>
                <span className={`tag ${loginSummary.tagClass}`}>{loginSummary.stageLabel}</span>
              </div>
              <div className="mini-grid two-col">
                <div className="field">
                  <label>店小秘账号</label>
                  <input className="input control-input" value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} placeholder="请输入账号" />
                </div>
                <div className="field">
                  <label>店小秘密码</label>
                  <input className="input control-input" type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} placeholder="请输入密码" />
                </div>
              </div>
              <div className="stat-line"><strong>当前：</strong>{loginSummary.title}</div>
              <div className="stat-line"><strong>下一步：</strong>{loginSummary.nextAction}</div>
              <div className="button-row compact-row">
                <button className="btn secondary" type="button" onClick={handleWaitCaptcha} disabled={busy || !loginUsername.trim() || !loginPassword.trim()}>等待验证码</button>
                <button className="btn secondary" type="button" onClick={handleContinueLogin} disabled={busy}>继续登录</button>
                <button className="btn warn" type="button" onClick={handleToggleManualMode}>{manualMode ? '退出接管' : '人工接管'}</button>
              </div>
            </div>

            <div className="workspace-card">
              <div className="section-head">
                <h2>业务概览</h2>
              </div>
              <div className="cards cards-compact">
                <div className="card"><div className="k">商品</div><div className="v">{importedCount}</div></div>
                <div className="card green"><div className="k">可推进</div><div className="v">{passCount}</div></div>
                <div className="card yellow"><div className="k">人工</div><div className="v">{pendingManualCount}</div></div>
                <div className="card red"><div className="k">阻塞</div><div className="v">{blockedCount}</div></div>
              </div>
              <div className="mini-list">
                <div><strong>店铺：</strong>{currentStore?.name ?? 'Dang Kang'}</div>
                <div><strong>平台：</strong>速卖通 / 店小秘采集链路</div>
                <div><strong>任务：</strong>{selectedTask?.name ?? '速卖通真实流程演示批次'}</div>
              </div>
            </div>

            <div className="workspace-card">
              <div className="section-head">
                <h2>采集箱动作</h2>
              </div>
              <div className="field">
                <label>备注内容</label>
                <input className="input control-input" value={draftNoteText} onChange={(event) => setDraftNoteText(event.target.value)} placeholder="例如：AI认领" />
              </div>
              <div className="button-row compact-row">
                <button className="btn secondary" type="button" onClick={() => handleDraftBoxAction('remark')} disabled={busy || !draftNoteText.trim()}>备注</button>
                <button className="btn primary" type="button" onClick={() => handleDraftBoxAction('edit')} disabled={busy}>进编辑界面</button>
              </div>
              <div className="mini-list">
                <div><strong>备注动作：</strong>更多 → 添加备注</div>
                <div><strong>编辑动作：</strong>编辑 → 跳过，去编辑产品</div>
              </div>
            </div>

            <div className="workspace-card">
              <div className="section-head">
                <h2>模板 / 合规</h2>
              </div>
              <div className="mini-list">
                {coverageData.slice(0, 4).map((item) => (
                  <div key={item.title}><strong>{item.title}：</strong>{item.status}</div>
                ))}
              </div>
              <div className="mini-tags">
                {selectedTemplateRows.slice(0, 4).map((template, idx) => (
                  <span key={`${template.template_name}-${idx}`} className="tag">{template.template_name}</span>
                ))}
              </div>
            </div>

            <div className="workspace-card workspace-card--wide">
              <div className="section-head">
                <h2>交互反馈</h2>
                <span className="tag">{browserMode === 'live' ? '实时页面' : '证据解读'}</span>
              </div>
              <div className="interaction-bar compact-bar">
                <div><strong>反馈：</strong>{interactionMessage}</div>
                <div className="interaction-meta">
                  <span className={`tag ${manualMode ? 'warning' : 'success'}`}>{manualMode ? '人工接管中' : '自动观察中'}</span>
                  <span className="tag">导航：{activeNav}</span>
                </div>
              </div>
              <div className="button-row compact-row">
                <button className="btn secondary" type="button" onClick={bootstrapDemo} disabled={busy}>{busy ? '准备中...' : '准备演示数据'}</button>
                <button className="btn secondary" type="button" onClick={startSelectedTask} disabled={!selectedTask || busy}>开始执行</button>
                <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('live')}>实时截图</button>
                <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('evidence')}>证据模式</button>
              </div>
            </div>
          </div>
        </section>

        <section className="browser">
          <div className="browser-toolbar">
            <h2>RPA 实时执行区</h2>
            <div className="browser-badges">
              <span className="chip">页面名称：<strong>{pageTitle}</strong></span>
              <span className="chip">当前任务：<strong>{selectedTask ? `批次#${selectedTask.id}` : '未创建'}</strong></span>
              <span className={`chip ${selectedTask?.status === 'running' || selectedTask?.status === 'completed' ? 'ok' : 'warn'}`}>执行状态：<strong>{humanTaskStatus(selectedTask?.status ?? 'draft')}</strong></span>
              <span className={`chip ${loginSummary.tagClass}`}>登录进度：<strong>{loginSummary.stageLabel}</strong></span>
            </div>
          </div>

          <div className="button-row" style={{ marginTop: 0 }}>
            <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('live')}>只看真实截图</button>
            <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('evidence')}>查看证据模式</button>
            <button className="btn secondary" type="button" onClick={() => setInteractionMessage(`已请求重试当前步骤：${currentStep?.stepName ?? activeNav}`)}>重试当前步骤</button>
            <button className="btn secondary" type="button" onClick={() => setInteractionMessage('已记录当前证据视图，方便后续回放与问题复盘。')}>记录证据</button>
            <button className="btn warn" type="button" onClick={handleToggleManualMode}>{manualMode ? '退出人工接管' : '人工接管'}</button>
          </div>

          <div className="rpa-stage">
            <div className="browser-view">
              <div className="browser-top">
                <span className="dot red"></span>
                <span className="dot yellow"></span>
                <span className="dot green"></span>
                <div style={{ marginLeft: 10, color: '#54627f', fontSize: 13 }}>{pageUrl}</div>
              </div>
              <div className="browser-body">
                <div className="overlay-tip">
                  当前阶段：{loginSummary.title}
                  <br />当前动作：{currentStep?.stepName ?? '等待从真实登录开始'}
                  <br />字段域：{humanField(currentStep?.fieldDomain)}
                  <br />来源说明：真实页面读取 + 模板引用 + 用户协作输入
                </div>

                {activeScreenshotUrl ? (
                  <img src={activeScreenshotUrl} alt="真实店小秘执行截图" style={{ width: '100%', borderRadius: 18, display: 'block' }} />
                ) : (
                  <div className="dxm-page dxm-page--login">
                    <div className="dxm-title">店小秘 · 官网登录与流程协作视图</div>
                    <div className="login-placeholder">
                      <div className="login-column">
                        <div className="dxm-field dxm-highlight"><small>账号</small>已由 AI 填写（演示态）</div>
                        <div className="dxm-field"><small>密码</small>已由 AI 填写（演示态）</div>
                        <div className="dxm-field"><small>验证码</small>{loginSummary.stage === 'logged_in' ? '已完成' : '等待用户输入'}</div>
                        <div className="dxm-field"><small>登录结果</small>{loginSummary.stageLabel}</div>
                      </div>
                      <div className="login-column">
                        <div className="dxm-field" style={{ minHeight: 92 }}><small>用户看到的提示</small>{loginSummary.detail}</div>
                        <div className="dxm-field" style={{ minHeight: 92 }}><small>系统下一步</small>{loginSummary.nextAction}</div>
                        <div className="dxm-field" style={{ minHeight: 92 }}><small>为什么这样设计</small>因为用户最怕“不知道系统卡在哪”，所以登录协作和验证码提示必须独立展示。</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="rpa-side">
              <div className="rpa-panel">
                <h3>真实流程步骤树</h3>
                <div className="step-list">
                  {steps.map((step, idx) => (
                    <div key={step.code} className={`step-item ${step.active ? 'active' : ''}`}>
                      <div className="step-no">{idx + 1}</div>
                      <div className="step-main">
                        <strong>{step.title}</strong>
                        <span>{step.desc}</span>
                      </div>
                      <span className={`tag ${step.tagClass}`}>{step.statusText}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rpa-panel">
                <h3>证据与反馈</h3>
                <div className="evidence-grid">
                  <div className="evidence-card">
                    <div className="title">当前截图</div>
                    {activeScreenshotUrl ? (
                      <img className="mini-shot" src={activeScreenshotUrl} alt="当前截图" style={{ width: '100%', objectFit: 'cover' }} />
                    ) : (
                      <div className="mini-shot"></div>
                    )}
                  </div>
                  <div className="evidence-card">
                    <div className="title">当前页面名</div>
                    <div style={{ fontSize: 12, color: '#cbd7f8', lineHeight: 1.6 }}>{pageTitle}</div>
                  </div>
                  <div className="evidence-card">
                    <div className="title">页面反馈</div>
                    <div style={{ fontSize: 12, color: '#cbd7f8', lineHeight: 1.6 }}>{pageFeedback.slice(0, 180)}</div>
                  </div>
                  <div className="evidence-card">
                    <div className="title">用户下一步</div>
                    <div style={{ fontSize: 12, color: '#cbd7f8', lineHeight: 1.6 }}>{loginSummary.userAction}</div>
                  </div>
                </div>
                <div className="manual-alert">
                  产品经理判断标准：用户只看这一栏，也应该知道现在页面在哪、系统在干什么、下一步该谁动手。
                </div>
              </div>
            </div>
          </div>

          <div className="muted">不再展示猜测型“速卖通创建产品”假页面。优先展示真实截图；没接上实时数据时，展示的是围绕真实登录协作设计的过渡视图。</div>
        </section>
      </main>

      <footer className="footer">
        <h2>执行日志 / 用户可读时间线</h2>
        <div className="timeline">
          {(logs.length ? logs : mockLogs).slice(0, 5).map((log, idx) => (
            <div className="log-item" key={idx}>
              <div className="time">{('created_at' in log && log.created_at) ? String(log.created_at).slice(11, 19) : mockTimes[idx]}</div>
              <div>{log.message}</div>
              <div><span className={`tag ${log.level === 'success' ? 'success' : 'warning'}`}>{humanLogStatus(log.level)}</span></div>
            </div>
          ))}
        </div>
      </footer>
    </div>
  )
}

const mockTemplates = [
  { template_name: '标题模板', template_type: 'title', binding_scope: '平台 / 店铺 / 类目', payload: { content: '核心词 + 属性词 + 卖点词' } },
  { template_name: '类目与资质模板', template_type: 'category', binding_scope: '平台 / 类目', payload: { content: '类目映射 / 品牌资质 / PDF资质' } },
  { template_name: '图片模板', template_type: 'image', binding_scope: '店铺 / 类目', payload: { content: '主图 / 白底图 / 营销图 / 视频' } },
  { template_name: 'SKU/价格模板', template_type: 'pricing', binding_scope: '店铺 / 类目 / 物流', payload: { content: '颜色尺码 / 计价 / 基准价 / 运费' } },
  { template_name: '合规模板', template_type: 'compliance', binding_scope: '类目 / 国家站点', payload: { content: '欧盟责任人 / 制造商 / 海关属性' } },
]

const mockLogs = [
  { level: 'success', message: '已按真实流程重排演示界面，登录协作区放到首屏' },
  { level: 'success', message: 'RPA 实时区优先展示真实截图与当前 URL，不再默认展示假想创建页' },
  { level: 'warning', message: '验证码等待态仍需后端提供更细粒度状态' },
  { level: 'warning', message: '模板引用区已改成用户可读结构，等待接入实时字段命中结果' },
  { level: 'warning', message: '下一步建议：补 login/start、login/continue 和 runtime state 接口' },
]
const mockTimes = ['10:31:12', '10:31:18', '10:31:24', '10:31:33', '10:32:08']

function buildCoverageData(templates: Template[], store?: Store) {
  const enabledCount = templates.filter((item) => item.is_enabled).length
  return [
    {
      title: '登录协作域',
      content: '官网登录、验证码等待、记住密码、登录结果回显',
      why: '用户要先看懂系统停在哪，才敢继续协作',
      status: '前端已重构',
      tagClass: 'success',
    },
    {
      title: '店铺与流程域',
      content: `${store?.name ?? 'Dang Kang'} / 数据采集 / 采集箱 / 编辑 / 发布`,
      why: '真实业务路径比抽象功能导航更好理解',
      status: '已切换真实语义',
      tagClass: 'success',
    },
    {
      title: '模板引用域',
      content: `当前可见模板 ${Math.max(enabledCount, 5)} 项，区分实时读取值与模板值`,
      why: '用户最怕 AI 乱填，所以来源必须透明',
      status: '待接实时命中',
      tagClass: 'warning',
    },
    {
      title: '半托管合规域',
      content: '半托管服务、含税报价、欧盟责任人、品牌制造商',
      why: '这些字段风险高，必须单独高亮',
      status: '前端已留位',
      tagClass: 'warning',
    },
  ]
}

function buildTemplateRows(templates: Template[]) {
  return (templates.length ? templates : mockTemplates).slice(0, 5)
}

function getInteractiveLoginSummary(summary: LoginSummary, demoStage: DemoStage, manualMode: boolean): LoginSummary {
  if (manualMode) {
    return {
      stage: 'login_problem',
      title: '人工协作视角已开启',
      detail: '当前界面会优先解释为什么阻塞、用户需要做什么、处理完后怎么继续。',
      nextAction: '处理验证码、弹窗或页面变化后，点击继续登录或切回自动观察。',
      userAction: '人工接管浏览器、确认页面状态、再把流程交还给系统。',
      tagClass: 'warn',
      stageLabel: '人工接管',
    }
  }

  if (demoStage === 'waiting_captcha') {
    return {
      stage: 'waiting_captcha',
      title: '等待用户完成验证码',
      detail: '现在不是系统卡住，而是在明确等待用户完成验证码。这个状态必须让用户一眼看明白。',
      nextAction: '用户输完验证码后，点击“继续登录”。',
      userAction: '在真实浏览器里处理验证码，然后回到演示台继续。',
      tagClass: 'warning',
      stageLabel: '等待验证码',
    }
  }

  if (demoStage === 'login_success') {
    return {
      stage: 'logged_in',
      title: '登录协作已完成，进入业务流',
      detail: '演示台已切到登录后的业务观察视角，后面要重点看数据采集、认领、采集箱和编辑页。',
      nextAction: '继续跟踪真实页面截图、步骤树和模板命中结果。',
      userAction: '当前主要是确认系统动作是否与真实页面一致。',
      tagClass: 'success',
      stageLabel: '已登录',
    }
  }

  return summary
}

function getLoginSummary(loginState: any, liveStatus: any): LoginSummary {
  if (loginState?.stage === 'login_success') {
    return {
      stage: 'logged_in',
      title: '已进入真实店小秘后台',
      detail: loginState.message,
      nextAction: loginState.next_action,
      userAction: '用户当前主要是观察与确认；如遇验证码失效或结构变化，再人工接管。',
      tagClass: 'success',
      stageLabel: loginState.label || '已登录',
    }
  }

  if (loginState?.stage === 'opening_login_page') {
    return {
      stage: 'not_started',
      title: '还没有建立真实登录会话',
      detail: loginState.message,
      nextAction: loginState.next_action,
      userAction: '用户需要在真实浏览器里完成验证码，随后点击继续登录。',
      tagClass: 'warning',
      stageLabel: loginState.label || '待登录',
    }
  }

  if (loginState?.stage === 'waiting_captcha') {
    return {
      stage: 'waiting_captcha',
      title: '正在补齐验证码协作链路',
      detail: loginState.message,
      nextAction: loginState.next_action,
      userAction: '用户视角下，这里必须变成一个明确可操作的“继续登录”协作位。',
      tagClass: 'warning',
      stageLabel: loginState.label || '待确认',
    }
  }

  if (liveStatus?.logged_in) {
    return {
      stage: 'logged_in',
      title: '已进入真实店小秘后台',
      detail: '当前已检测到真实登录态，可以继续进入产品、数据采集、采集箱和编辑流程。',
      nextAction: '继续同步当前页面状态，并把认领 / 备注 / 编辑动作实时展示出来。',
      userAction: '用户当前主要是观察与确认；如遇验证码失效或结构变化，再人工接管。',
      tagClass: 'success',
      stageLabel: '已登录',
    }
  }
  if (liveStatus?.reason === 'cookie_file_missing') {
    return {
      stage: 'not_started',
      title: '还没有建立真实登录会话',
      detail: '系统当前只知道还没拿到店小秘真实会话，符合“必须从官网登录开始”的新要求。',
      nextAction: '打开店小秘官网，先填账号密码，再进入验证码等待态。',
      userAction: '用户需要在真实浏览器里完成验证码，随后点击继续登录。',
      tagClass: 'warning',
      stageLabel: '待登录',
    }
  }
  if (liveStatus?.final_url || liveStatus?.title) {
    return {
      stage: 'login_problem',
      title: '检测到页面，但登录结果不稳定',
      detail: '当前已经能读取页面信息，但还不能可靠判断是否登录成功，说明登录状态流还需要补强。',
      nextAction: '补上 login state 与验证码等待态，再做成功/失败判定。',
      userAction: '用户先不要盲点下一步，等系统明确反馈“已登录”后再继续。',
      tagClass: 'warn',
      stageLabel: '待确认',
    }
  }
  return {
    stage: 'waiting_captcha',
    title: '验证码等待态尚未接入',
    detail: '产品层已经把这个位置留出来，但后端还没把 waiting_captcha 真实状态推给前端。',
    nextAction: '优先接入 login/start、login/continue 与 runtime state。',
    userAction: '用户视角下，这里必须变成一个明确可操作的“继续登录”协作位。',
    tagClass: 'warning',
    stageLabel: '待接入',
  }
}

function buildSteps(currentStep: LiveEvent | undefined, taskStatus?: string, liveStatus?: any): StepMeta[] {
  const base = [
    ['login', '官网登录', '打开店小秘官网，填写账号密码并等待验证码'],
    ['data_acquisition', '进入数据采集', '产品 → 数据采集 → 速卖通'],
    ['claim', '认领到采集箱', '选择店铺并执行认领，回看成功弹窗'],
    ['remark', '采集箱备注', '采集箱 → 更多 → 添加备注（AI认领）'],
    ['edit', '编辑产品', '跳过分类引导，进入真实编辑页'],
    ['publish', '待发布 / 发布', '保存并移入待发布，确认发布条件'],
  ] as const

  const currentCode = mapCurrentCode(currentStep?.stepCode, liveStatus)
  const activeIdx = Math.max(0, base.findIndex((item) => item[0] === currentCode))

  return base.map((item, idx) => {
    let statusText = '待执行'
    let tagClass = ''
    if (idx < activeIdx) {
      statusText = '已通过'
      tagClass = 'success'
    }
    if (idx === activeIdx) {
      statusText = taskStatus === 'completed' && idx === base.length - 1 ? '已完成' : '进行中'
      tagClass = 'warning'
    }
    if (taskStatus === 'completed' && idx >= activeIdx) {
      statusText = '已完成'
      tagClass = 'success'
    }
    return { code: item[0], title: item[1], desc: item[2], statusText, tagClass, active: idx === activeIdx }
  })
}

function mapCurrentCode(stepCode?: string, liveStatus?: any) {
  if (liveStatus?.logged_in && !stepCode) return 'data_acquisition'
  const mapping: Record<string, string> = {
    check_login: 'login',
    open_home: 'login',
    open_create_page: 'data_acquisition',
    switch_store: 'claim',
    load_templates: 'edit',
    fill_title: 'edit',
    fill_category: 'edit',
    upload_images: 'edit',
    fill_sku_price: 'edit',
    select_shipping: 'edit',
    select_shipping_template: 'edit',
    compliance: 'edit',
    save_draft: 'publish',
  }
  return mapping[stepCode ?? ''] || 'login'
}

function humanTaskStatus(status: string) {
  return ({ draft: '待启动', running: '运行中', completed: '已完成', paused: '已暂停', failed: '失败', cancelled: '已停止' } as Record<string, string>)[status] ?? status
}

function humanField(domain?: string) {
  return ({ title: '标题', category: '类目属性', media: '图片 / 视频', pricing: 'SKU 与价格', shipping: '物流与运费', result: '保存与发布', session: '登录态', navigation: '页面跳转' } as Record<string, string>)[domain ?? ''] ?? '登录与流程协作'
}

function humanLogStatus(level: string) {
  return ({ success: '成功', warning: '处理中', info: '执行中', error: '失败' } as Record<string, string>)[level] ?? '等待'
}

function toArtifactUrl(value?: string | null) {
  if (!value) return ''
  if (value.startsWith('/artifacts/')) return value
  const marker = '/data/'
  const idx = value.indexOf(marker)
  if (idx >= 0) return '/artifacts/' + value.slice(idx + marker.length)
  return value
}
