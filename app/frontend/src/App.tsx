import { useEffect, useMemo, useState } from 'react'
import { getJson, getJsonOrDefault, postJson } from './api'
import type { Evidence, ExceptionItem, LiveEvent, LogItem, Product, Report, Store, Task, Template } from './types'

const seedRows = [
  {
    title: 'Wind Breaker Anime Acrylic Stand Hot Spring Battle Charm',
    source_title: '防风铃x空座温泉云蒸决战阵防风少年',
    category_name: '立牌类谷子',
    price: 7.01,
    sku_count: 8,
    image_count: 8,
    image: { eu_outer_package_filename: '微信图片_202504092228421.jpg' },
  },
]

const flowNav = [
  '登录态',
  '采集箱',
  '领取',
  '普通编辑',
  '半托管',
  '保存',
  '报告',
  '模板中心',
]

const navTargetMap: Partial<Record<typeof flowNav[number], string>> = {
  '采集箱': 'draft_box',
  '领取': 'data_acquisition',
  '普通编辑': 'draft_box',
  '半托管': 'draft_box',
  '保存': 'draft_box',
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
type ExecutionConfig = {
  storeName: string
  categoryName: string
  categoryTemplate: string
  referenceTemplate: string
  imageBankSource: string
  euOuterPackageFilename: string
  logisticsTemplate: string
  freightTemplates: string[]
  serviceTemplates: string[]
  jitStock: string
  barcodeStrategy: string
  saveMode: string
  publishScene: string
  publishPolicy: string
}

export default function App() {
  const [stores, setStores] = useState<Store[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [logs, setLogs] = useState<LogItem[]>([])
  const [evidences, setEvidences] = useState<Evidence[]>([])
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([])
  const [reports, setReports] = useState<Report[]>([])
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [liveStatus, setLiveStatus] = useState<any>(null)
  const [loginState, setLoginState] = useState<any>(null)
  const [loginUsername, setLoginUsername] = useState('master-demo')
  const [loginPassword, setLoginPassword] = useState('demo-pass')
  const [activeNav, setActiveNav] = useState<FlowNavItem>('登录态')
  const [demoStage, setDemoStage] = useState<DemoStage>('system')
  const [manualMode, setManualMode] = useState(false)
  const [browserMode, setBrowserMode] = useState<BrowserMode>('live')
  const [interactionMessage, setInteractionMessage] = useState('V1 执行器只保存不发布：先确认登录态，再进入采集箱、领取、普通编辑、半托管、保存和报告链路。')
  const [draftNoteText, setDraftNoteText] = useState('AI认领')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const selectedTask = useMemo(() => tasks.find((item) => item.id === selectedTaskId) ?? tasks[0] ?? null, [tasks, selectedTaskId])
  const currentStore = stores[0]
  const currentProduct = products[0]
  const currentStep = liveEvents.find((event) => event.type === 'step_update')
  const currentEvidence = evidences[0]

  async function refreshAll() {
    const [storesData, templatesData, productsData, tasksData, logsData, evidencesData, exceptionsData, reportsData, liveStatusData, loginStateData] = await Promise.all([
      getJson<Store[]>('/api/stores'),
      getJson<Template[]>('/api/templates'),
      getJson<Product[]>('/api/products'),
      getJson<Task[]>('/api/tasks'),
      getJson<LogItem[]>('/api/logs'),
      getJson<Evidence[]>('/api/evidences'),
      getJson<ExceptionItem[]>('/api/exceptions'),
      getJsonOrDefault<Report[]>('/api/reports', []),
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
    setReports(reportsData)
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
      const templateSeeds = [
        { template_type: 'title', template_name: '标题模板', binding_scope: '平台 / 店铺 / 类目', payload: { rule: '核心词 + 属性词 + 卖点词' }, is_enabled: true },
        { template_type: 'category', template_name: '立牌类谷子属性模板', binding_scope: '平台 / 店铺 / 类目', payload: { binding: { store_name: 'Dang Kang', category_name: '立牌类谷子' }, category: { category_keyword: '立牌', category_match: 'ACG Stand', attribute_template_priorities: ['立牌类谷子'] } }, is_enabled: true },
        { template_type: 'sku', template_name: 'SKU/货品编码模板', binding_scope: '店铺 / 类目', payload: { sku: { goods_code_strategy: '沿用店小秘生成', barcode_strategy: '留空' } }, is_enabled: true },
        { template_type: 'pricing', template_name: '价格库存模板', binding_scope: '店铺 / 类目 / 物流', payload: { pricing: { declared_value: '1', stock: '200' } }, is_enabled: true },
        { template_type: 'logistics', template_name: '包装物流模板', binding_scope: '店铺 / 类目', payload: { logistics: { weight: '0.03', length: '10', width: '10', height: '2', attribute: '普货', is_original_box: '否', freight_templates: ['石油40g普货包裹.', '40g普货包裹'], service_templates: ['Service Template for New Sellers'] } }, is_enabled: true },
        { template_type: 'image', template_name: '图片银行模板', binding_scope: '店铺 / 类目', payload: { image: { source: '图片银行（速卖通）', eu_outer_package_filename: '微信图片_202504092228421.jpg', slots: [{ slot_key: 'eu_outer_package', label: '外包装/标签实拍图-欧盟', filename: '微信图片_202504092228421.jpg', source: 'smt_image_bank' }] } }, is_enabled: true },
        { template_type: 'semi_managed', template_name: '半托管模板', binding_scope: '店铺 / 类目 / 国家站点', payload: { semi_managed: { countries: '全选', original_box: '否', logistics_attribute: '普货', jit_stock: '100', barcode_strategy: '留空' } }, is_enabled: true },
        { template_type: 'compliance', template_name: '合规模板', binding_scope: '类目 / 国家站点', payload: { compliance: { eu_responsible_names: ['Jacqueiline Marti'], manufacturer_names: ['jiyang county thunder', 'Jiyang County thunder'], customs_product_names: ['钥匙扣', 'keychain'] } }, is_enabled: true },
      ]
      const existingTemplateTypes = new Set(templates.map((item) => item.template_type))
      const missingTemplateSeeds = templateSeeds.filter((item) => !existingTemplateTypes.has(item.template_type))
      if (missingTemplateSeeds.length) {
        await Promise.all(missingTemplateSeeds.map((template) => postJson('/api/templates', template)))
      }
      let importedProducts = products
      if (importedProducts.length === 0) {
        importedProducts = await postJson<Product[]>('/api/products/import', { rows: seedRows })
      }
      const task = await postJson<Task>('/api/tasks', {
        name: 'V1 半托管保存执行批次',
        store_id: store.id,
        mode: 'single_save',
        publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
        product_ids: importedProducts.map((item) => item.id),
        claim_mark: 'AI认领',
        payload: {
          store_name: 'Dang Kang',
          category_name: '立牌类谷子',
          image: { eu_outer_package_filename: '微信图片_202504092228421.jpg' },
        },
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
    setActiveNav('采集箱')
    setInteractionMessage('任务已启动，演示焦点自动切到“采集箱”。本批次只保存不发布，保存后进入报告复盘。')
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
    if (item === '报告') setBrowserMode('evidence')
    if (item === '登录态') setBrowserMode('live')
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
      setActiveNav('登录态')
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
      setActiveNav(result.stage === 'login_success' ? '采集箱' : '登录态')
      setManualMode(result.stage !== 'login_success')
      setInteractionMessage(result.stage === 'login_success'
        ? '已调用真实登录 continue：检测到登录成功，界面切到半托管只保存业务流起点。'
        : '已调用真实登录 continue：当前仍未确认登录成功，请检查验证码或人工接管。')
    } finally {
      setBusy(false)
      await refreshAll()
    }
  }

  function handleToggleManualMode() {
    setManualMode((prev) => {
      const next = !prev
      setActiveNav(next ? '报告' : activeNav)
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
        product_query: currentProduct?.title,
        store_name: currentStore?.name ?? 'Dang Kang',
      })
      setLoginState(result)
      setActiveNav(action === 'remark' ? '采集箱' : '普通编辑')
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
  const executionConfig = useMemo(
    () => buildExecutionConfig(templates, currentStore, currentProduct, selectedTask),
    [templates, currentStore, currentProduct, selectedTask],
  )
  const pageTitle = browserMode === 'evidence'
    ? '保存报告与证据视图'
    : liveStatus?.product_page?.title || loginState?.page_title || liveStatus?.title || '店小秘登录态 / 半托管保存页'
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
            <h1>V1 半托管保存执行器</h1>
            <small>登录态、采集箱、领取、普通编辑、半托管、保存、报告；只保存不发布</small>
          </div>
        </div>
        <div className="status-row">
          <div className="chip ok">执行原则：<strong>只保存不发布</strong></div>
          <div className={`chip ${loginSummary.tagClass}`}>登录阶段：<strong>{loginSummary.stageLabel}</strong></div>
          <div className={`chip ${stores.length ? 'ok' : 'warn'}`}>当前店铺：<strong>{currentStore?.name ?? 'Dang Kang'}</strong></div>
          <div className="chip">模板命中：<strong>{selectedTemplateRows.length || 5} 项</strong></div>
          <div className="chip">V1覆盖：<strong>{coverageData.length} 域</strong></div>
          <div className="chip">报告：<strong>{reports.length} 份</strong></div>
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
              <span>V1 是半托管保存执行器，客户首屏必须看懂当前批次不会发布。</span>
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
                <h2>保存执行概览</h2>
              </div>
              <div className="cards cards-compact">
                <div className="card"><div className="k">商品</div><div className="v">{importedCount}</div></div>
                <div className="card green"><div className="k">可推进</div><div className="v">{passCount}</div></div>
                <div className="card yellow"><div className="k">人工</div><div className="v">{pendingManualCount}</div></div>
                <div className="card red"><div className="k">阻塞</div><div className="v">{blockedCount}</div></div>
              </div>
              <div className="mini-list">
                <div><strong>店铺：</strong>{currentStore?.name ?? 'Dang Kang'}</div>
                <div><strong>平台：</strong>速卖通 / 店小秘半托管保存链路</div>
                <div><strong>任务：</strong>{selectedTask?.name ?? 'V1 半托管保存执行批次'}</div>
                <div><strong>模式：</strong>{selectedTask?.mode ?? 'single_save'} / {selectedTask?.publish_scene ?? 'SMT_SEMI_MANAGED_SAVE_ONLY'}</div>
              </div>
            </div>

            <div className="workspace-card workspace-card--wide config-review-card">
              <div className="section-head">
                <h2>启动前配置确认</h2>
                <span className="tag success">{executionConfig.publishPolicy}</span>
              </div>
              <div className="config-grid">
                <div className="config-item">
                  <span>店铺 / 类目</span>
                  <strong>{executionConfig.storeName}</strong>
                  <small>{executionConfig.categoryName}，本批次只面向 Dang Kang 店铺执行</small>
                </div>
                <div className="config-item">
                  <span>类目模板 / 引用模板</span>
                  <strong>{executionConfig.categoryTemplate}</strong>
                  <small>{executionConfig.referenceTemplate}</small>
                </div>
                <div className="config-item">
                  <span>图片银行欧盟外包装</span>
                  <strong>{executionConfig.euOuterPackageFilename}</strong>
                  <small>{executionConfig.imageBankSource}</small>
                </div>
                <div className="config-item">
                  <span>物流模板</span>
                  <strong>{executionConfig.logisticsTemplate}</strong>
                  <small>货运：{executionConfig.freightTemplates.join(' / ')}</small>
                </div>
                <div className="config-item">
                  <span>半托管 JIT 库存</span>
                  <strong>{executionConfig.jitStock}</strong>
                  <small>半托管货品库存，启动后按模板填入</small>
                </div>
                <div className="config-item">
                  <span>条码策略</span>
                  <strong>{executionConfig.barcodeStrategy}</strong>
                  <small>SKU / 半托管条码保持留空</small>
                </div>
              </div>
              <div className="config-guard">
                <span className="tag success">保存模式：{executionConfig.saveMode}</span>
                <span className="tag">场景：{executionConfig.publishScene}</span>
                <span className="tag warning">服务模板：{executionConfig.serviceTemplates.join(' / ')}</span>
              </div>
            </div>

            <div className="workspace-card">
              <div className="section-head">
                <h2>采集箱 / 领取</h2>
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
                <div><strong>备注动作：</strong>更多 → 添加备注，标记半托管保存批次</div>
                <div><strong>编辑动作：</strong>编辑 → 跳过，去编辑产品</div>
              </div>
            </div>

            <div className="workspace-card">
              <div className="section-head">
                <h2>报告</h2>
              </div>
              <div className="mini-list">
                {(reports.length ? reports : mockReports).slice(0, 4).map((report) => (
                  <div key={String(report.id)}><strong>{humanReportTitle(report)}：</strong>{humanReportSummary(report)}</div>
                ))}
              </div>
              <div className="mini-tags">
                <span className="tag success">只保存不发布</span>
                <span className="tag">reports: {reports.length}</span>
                <span className="tag">保存后复盘</span>
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
                <button className="btn secondary" type="button" onClick={startSelectedTask} disabled={!selectedTask || busy}>开始只保存执行</button>
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
              <span className="chip ok">发布策略：<strong>只保存不发布</strong></span>
              <span className={`chip ${selectedTask?.status === 'running' || selectedTask?.status === 'completed' ? 'ok' : 'warn'}`}>执行状态：<strong>{humanTaskStatus(selectedTask?.status ?? 'draft')}</strong></span>
              <span className={`chip ${loginSummary.tagClass}`}>登录进度：<strong>{loginSummary.stageLabel}</strong></span>
            </div>
          </div>

          <div className="button-row" style={{ marginTop: 0 }}>
            <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('live')}>只看真实截图</button>
            <button className="btn secondary" type="button" onClick={() => handleBrowserModeChange('evidence')}>查看证据模式</button>
            <button className="btn secondary" type="button" onClick={() => setInteractionMessage(`已请求重试当前步骤：${currentStep?.stepName ?? activeNav}`)}>重试当前步骤</button>
            <button className="btn secondary" type="button" onClick={() => setInteractionMessage('已记录当前证据视图，保存后报告会用于回放与问题复盘。')}>记录证据</button>
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
                  <br />发布策略：只保存不发布
                </div>

                {activeScreenshotUrl ? (
                  <img src={activeScreenshotUrl} alt="真实店小秘执行截图" style={{ width: '100%', borderRadius: 18, display: 'block' }} />
                ) : (
                  <div className="dxm-page dxm-page--login">
                    <div className="dxm-title">店小秘 · 登录态与半托管保存协作视图</div>
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
                  产品经理判断标准：用户只看这一栏，也应该知道现在页面在哪、系统在干什么，以及本次只保存不发布。
                </div>
              </div>
            </div>
          </div>

          <div className="muted">V1 不执行发布动作。优先展示真实截图；没接上实时数据时，展示围绕登录态、采集箱、领取、普通编辑、半托管、保存、报告的过渡视图。</div>
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
  { level: 'success', message: '已按 V1 半托管保存链路重排演示界面，登录态放到首屏' },
  { level: 'success', message: 'RPA 实时区优先展示真实截图与当前 URL，执行策略为只保存不发布' },
  { level: 'warning', message: '验证码等待态仍需后端提供更细粒度状态' },
  { level: 'warning', message: '报告区已兼容 /api/reports 空数组，等待后端接入真实报告' },
  { level: 'warning', message: '下一步建议：补 reports、login/start、login/continue 和 runtime state 接口' },
]
const mockTimes = ['10:31:12', '10:31:18', '10:31:24', '10:31:33', '10:32:08']
const mockReports: Report[] = [
  { id: 'local-save-policy', title: '保存策略', status: 'draft', summary: 'single_save / SMT_SEMI_MANAGED_SAVE_ONLY，只保存不发布' },
  { id: 'local-step-report', title: '步骤报告', status: 'draft', summary: '登录态、采集箱、领取、普通编辑、半托管、保存、报告' },
  { id: 'local-evidence', title: '证据报告', status: 'draft', summary: '保存后汇总截图、日志和人工协作原因' },
]

function buildExecutionConfig(templates: Template[], store?: Store, product?: Product, task?: Task | null): ExecutionConfig {
  const categoryTemplate = findTemplate(templates, 'category')
  const logisticsTemplate = findTemplate(templates, 'logistics')
  const imageTemplate = findTemplate(templates, 'image')
  const skuTemplate = findTemplate(templates, 'sku')
  const semiManagedTemplate = findTemplate(templates, 'semi_managed')
  const taskPayload = asRecord(task?.payload)
  const taskImage = asRecord(taskPayload.image)
  const categoryPayload = asRecord(categoryTemplate?.payload)
  const categoryData = asRecord(categoryPayload.category)
  const categoryBinding = asRecord(categoryPayload.binding)
  const logisticsData = asRecord(asRecord(logisticsTemplate?.payload).logistics)
  const imageData = asRecord(asRecord(imageTemplate?.payload).image)
  const skuData = asRecord(asRecord(skuTemplate?.payload).sku)
  const semiManagedData = asRecord(asRecord(semiManagedTemplate?.payload).semi_managed)

  return {
    storeName: asText(taskPayload.store_name, store?.name ?? asText(categoryBinding.store_name, 'Dang Kang')),
    categoryName: asText(taskPayload.category_name, product?.category_name ?? asText(categoryBinding.category_name, '立牌类谷子')),
    categoryTemplate: categoryTemplate?.template_name ?? '立牌类谷子属性模板',
    referenceTemplate: `类目：${asText(categoryData.category_match, 'ACG Stand')} / 引用：${asTextList(categoryData.attribute_template_priorities, ['立牌类谷子']).join(' / ')}`,
    imageBankSource: asText(imageData.source, '图片银行（速卖通）'),
    euOuterPackageFilename: asText(taskImage.eu_outer_package_filename, product?.image?.eu_outer_package_filename ?? asText(imageData.eu_outer_package_filename, '微信图片_202504092228421.jpg')),
    logisticsTemplate: logisticsTemplate?.template_name ?? '包装物流模板',
    freightTemplates: asTextList(logisticsData.freight_templates, ['石油40g普货包裹.', '40g普货包裹']),
    serviceTemplates: asTextList(logisticsData.service_templates, ['Service Template for New Sellers']),
    jitStock: asText(semiManagedData.jit_stock, '100'),
    barcodeStrategy: asText(semiManagedData.barcode_strategy, asText(skuData.barcode_strategy, '留空')),
    saveMode: task?.mode ?? 'single_save',
    publishScene: task?.publish_scene ?? 'SMT_SEMI_MANAGED_SAVE_ONLY',
    publishPolicy: '只保存不发布',
  }
}

function findTemplate(templates: Template[], templateType: string) {
  return templates.find((item) => item.template_type === templateType && item.is_enabled) ?? templates.find((item) => item.template_type === templateType)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asText(value: unknown, fallback: string) {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function asTextList(value: unknown, fallback: string[]) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : fallback
}

function buildCoverageData(templates: Template[], store?: Store) {
  const enabledCount = templates.filter((item) => item.is_enabled).length
  return [
    {
      title: '登录协作域',
      content: '登录态、验证码等待、记住密码、登录结果回显',
      why: '用户要先看懂系统停在哪，才敢继续协作',
      status: '前端已重构',
      tagClass: 'success',
    },
    {
      title: '店铺与流程域',
      content: `${store?.name ?? 'Dang Kang'} / 采集箱 / 领取 / 普通编辑 / 半托管 / 保存 / 报告`,
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
      detail: '演示台已切到登录后的业务观察视角，后面要重点看采集箱、领取、普通编辑、半托管、保存和报告。',
      nextAction: '继续跟踪真实页面截图、步骤树、模板命中和保存报告。',
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
      detail: '当前已检测到真实登录态，可以继续进入采集箱、领取、普通编辑、半托管保存流程。',
      nextAction: '继续同步当前页面状态，并把领取 / 备注 / 编辑 / 保存动作实时展示出来。',
      userAction: '用户当前主要是观察与确认；如遇验证码失效或结构变化，再人工接管。',
      tagClass: 'success',
      stageLabel: '已登录',
    }
  }
  if (liveStatus?.reason === 'cookie_file_missing') {
    return {
      stage: 'not_started',
      title: '还没有建立真实登录会话',
      detail: '系统当前只知道还没拿到店小秘真实会话，符合“必须先确认登录态”的新要求。',
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
    ['login', '登录态', '确认店小秘真实会话，必要时等待验证码'],
    ['draft_box', '采集箱', '进入采集箱并确认待处理商品'],
    ['claim', '领取', '选择店铺并领取到采集箱，回看成功弹窗'],
    ['edit', '普通编辑', '跳过分类引导，进入真实编辑页并完成基础字段'],
    ['semi_managed', '半托管', '补齐半托管服务、含税报价和合规字段'],
    ['save', '保存', '执行保存动作，只保存不发布'],
    ['report', '报告', '生成保存结果、证据和异常复盘报告'],
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
  if (liveStatus?.logged_in && !stepCode) return 'draft_box'
  const mapping: Record<string, string> = {
    PRECHECK_CONFIG: 'login',
    PRECHECK_SESSION: 'login',
    PRECHECK_SELECTOR_PROFILE: 'login',
    PRECHECK_PUBLISH_GUARD: 'login',
    OPEN_DRAFT_LIST: 'draft_box',
    FIND_PRODUCT: 'draft_box',
    ITEM_LOCKING: 'claim',
    ITEM_LOCKED: 'claim',
    CLAIM_PRODUCT: 'claim',
    VERIFY_LIST_OWNERSHIP: 'claim',
    OPEN_EDIT_PAGE: 'edit',
    VERIFY_EDIT_OWNERSHIP: 'edit',
    FILL_BASE_INFO: 'edit',
    FILL_VARIANTS: 'edit',
    FILL_MEDIA: 'edit',
    FILL_COMPLIANCE: 'edit',
    ENABLE_SEMI_MANAGED: 'semi_managed',
    OPEN_SEMI_MANAGED_PAGE: 'semi_managed',
    FILL_SEMI_GOODS: 'semi_managed',
    FILL_SEMI_VARIANTS: 'semi_managed',
    PRE_SAVE_GUARD_CHECK: 'save',
    SAVE_ONLY: 'save',
    VERIFY_SAVE_RESULT: 'save',
    VERIFY_NOT_PUBLISHED: 'save',
    WRITE_REPORT: 'report',
    RELEASE_LOCK: 'report',
    DONE: 'report',
    check_login: 'login',
    open_home: 'login',
    open_create_page: 'draft_box',
    switch_store: 'claim',
    load_templates: 'edit',
    fill_title: 'edit',
    fill_category: 'edit',
    upload_images: 'edit',
    fill_sku_price: 'edit',
    select_shipping: 'edit',
    select_shipping_template: 'edit',
    compliance: 'semi_managed',
    save_draft: 'save',
    single_save: 'save',
    report: 'report',
  }
  return mapping[stepCode ?? ''] || 'login'
}

function humanTaskStatus(status: string) {
  return ({ draft: '待启动', running: '运行中', completed: '已完成', partial_success: '部分成功', paused: '已暂停', failed: '失败', cancelled: '已停止' } as Record<string, string>)[status] ?? status
}

function humanField(domain?: string) {
  return ({
    config: '配置预检',
    publish_guard: '发布隔离',
    ownership: '商品归属',
    editor: '普通编辑页',
    base_info: '标题与基础属性',
    variants: '变种表格',
    semi_goods: '半托管货品',
    semi_variants: '半托管变种',
    title: '标题',
    category: '类目属性',
    media: '图片 / 视频',
    pricing: 'SKU 与价格',
    shipping: '物流与运费',
    result: '保存结果',
    session: '登录态',
    navigation: '页面跳转',
  } as Record<string, string>)[domain ?? ''] ?? '登录与流程协作'
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

function humanReportTitle(report: Report) {
  return String(report.title ?? report.report_type ?? `报告 #${report.id}`)
}

function humanReportSummary(report: Report) {
  const summary = report.summary
  if (typeof summary === 'string') return summary
  if (summary && typeof summary === 'object') {
    const data = summary as Record<string, unknown>
    const status = data.status ? humanTaskStatus(String(data.status)) : humanTaskStatus(String(report.status ?? 'draft'))
    const claim = data.claim_mark ? `，领取标记 ${data.claim_mark}` : ''
    const published = data.published === false ? '，未发布' : ''
    return `${status}${claim}${published}`
  }
  const saveResult = report.save_result
  if (saveResult && typeof saveResult === 'object') {
    const data = saveResult as Record<string, unknown>
    return String(data.msg ?? data.message ?? humanTaskStatus(String(report.status ?? 'draft')))
  }
  return humanTaskStatus(String(report.status ?? 'draft'))
}
