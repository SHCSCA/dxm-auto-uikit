import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getJson, getJsonOrDefault, postJson } from './api'
import { AppShell } from './components/AppShell'
import { SafetyStatusBar } from './components/SafetyStatusBar'
import {
  ConfigCenter,
  Dashboard,
  EvidenceTimeline,
  ExceptionQueue,
  ExecutionConsole,
  GuideCenter,
  ReportCenter,
  TaskCenter,
} from './components/WorkbenchModules'
import type { AgentConsoleSession, ConfigPreview, DeliveryWorkspace, Evidence, ExceptionItem, FinalDeliveryCheckSummary, LogItem, Product, RealTaskCreateRequest, Report, RuntimeControlAction, RuntimeControlResponse, RuntimeLogResponse, RuntimeLogSource, RuntimeStatus, Store, Task, Template, WorkbenchSection } from './types'
import { composeWorkspace, demoTemplateSeeds, seedRows } from './workspace'

const AGENT_CONSOLE_TARGET_URL = 'https://www.dianxiaomi.com/'
const REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save', 'batch_save'])
const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])
const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'batch_save'])
const L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'
const DEMO_ENABLED = new URLSearchParams(window.location.search).get('dev') === '1'
  || (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_DXM_ENABLE_DEMO === '1'

const sourceLabels: Record<DeliveryWorkspace['source'], string> = {
  api: '/api/delivery/workspace',
  fallback: '现有 API 组合',
  mock: '空工作台 / 演示前',
}

type ApiFailure = {
  path: string
  message: string
}

type WorkspaceNotice = {
  kind: 'loading' | 'degraded'
  title: string
  detail: string
}

type ManualApprovalResponse = {
  ok: boolean
  approvalToken: string
  confirmation: string
}

const runtimeLogSources: RuntimeLogSource[] = ['backend', 'frontend', 'launcher', 'npm', 'task', 'agent']

export default function App() {
  const [workspace, setWorkspace] = useState<DeliveryWorkspace>(() => composeWorkspace({
    stores: [],
    templates: [],
    products: [],
    tasks: [],
    logs: [],
    evidences: [],
    exceptions: [],
    reports: [],
  }))
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('guide')
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [agentConsole, setAgentConsole] = useState<AgentConsoleSession | null>(null)
  const [finalCheck, setFinalCheck] = useState<FinalDeliveryCheckSummary | null>(null)
  const [agentConsoleError, setAgentConsoleError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [runtimeLogSource, setRuntimeLogSource] = useState<RuntimeLogSource>('backend')
  const [runtimeLogs, setRuntimeLogs] = useState<Record<RuntimeLogSource, RuntimeLogResponse | null>>({
    backend: null,
    frontend: null,
    launcher: null,
    npm: null,
    task: null,
    agent: null,
  })
  const [runtimeLogError, setRuntimeLogError] = useState<string | null>(null)
  const [runtimeLogLevel, setRuntimeLogLevel] = useState<'all' | 'info' | 'warning' | 'error'>('all')
  const [runtimeLogQuery, setRuntimeLogQuery] = useState('')
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null)
  const [configPreview, setConfigPreview] = useState<ConfigPreview | null>(null)
  const [configPreviewLoading, setConfigPreviewLoading] = useState(false)
  const [workspaceNotice, setWorkspaceNotice] = useState<WorkspaceNotice | null>({
    kind: 'loading',
    title: '正在加载 DXM 自动化工作台',
    detail: '正在读取 /api/delivery/workspace 与关联接口。',
  })
  const runtimeLogCursorRef = useRef<Record<RuntimeLogSource, number>>({
    backend: 0,
    frontend: 0,
    launcher: 0,
    npm: 0,
    task: 0,
    agent: 0,
  })

  const selectedTask = useMemo(
    () => workspace.tasks.find((task) => task.id === selectedTaskId) ?? workspace.tasks[0] ?? null,
    [selectedTaskId, workspace.tasks],
  )

  const refreshWorkspace = useCallback(async () => {
    const deliveryPath = selectedTaskId ? `/api/delivery/workspace?task_id=${selectedTaskId}` : '/api/delivery/workspace'
    const failures: ApiFailure[] = []
    const loadOrFallback = async <T,>(path: string, fallback: T): Promise<T> => {
      try {
        return await getJson<T>(path)
      } catch (error) {
        failures.push({ path, message: error instanceof Error ? error.message : '接口请求失败' })
        return fallback
      }
    }

    setWorkspaceNotice((current) => current?.kind === 'degraded'
      ? current
      : {
        kind: 'loading',
        title: '正在加载 DXM 自动化工作台',
        detail: `正在读取 ${deliveryPath} 与关联接口。`,
      })
    const [
      deliveryWorkspace,
      stores,
      templates,
      products,
      tasks,
      logs,
      evidences,
      exceptions,
      reports,
      consoleStatus,
      finalCheckSummary,
    ] = await Promise.all([
      loadOrFallback<Partial<DeliveryWorkspace> | null>(deliveryPath, null),
      loadOrFallback<Store[]>('/api/stores', []),
      loadOrFallback<Template[]>('/api/templates', []),
      loadOrFallback<Product[]>('/api/products', []),
      loadOrFallback<Task[]>('/api/tasks', []),
      loadOrFallback<LogItem[]>('/api/logs', []),
      loadOrFallback<Evidence[]>('/api/evidences', []),
      loadOrFallback<ExceptionItem[]>('/api/exceptions', []),
      loadOrFallback<Report[]>('/api/reports', []),
      loadOrFallback<AgentConsoleSession | null>('/api/agent-console/status', null),
      loadOrFallback<FinalDeliveryCheckSummary | null>('/api/delivery/final-check', null),
    ])
    const nextWorkspace = composeWorkspace({
      workspace: deliveryWorkspace,
      stores,
      templates,
      products,
      tasks,
      logs,
      evidences,
      exceptions,
      reports,
    })
    setWorkspace(nextWorkspace)
    setAgentConsole(consoleStatus)
    setFinalCheck(finalCheckSummary)
    setSelectedTaskId((current) => current ?? nextWorkspace.tasks[0]?.id ?? null)
    if (failures.length) {
      const failedPaths = failures.map((failure) => failure.path).join('、')
      setWorkspaceNotice({
        kind: 'degraded',
        title: 'DXM 自动化接口不可用，正在显示只读降级数据',
        detail: `失败接口：${failedPaths}。${failures[0]?.message ?? '请检查后端服务状态。'}`,
      })
    } else {
      setWorkspaceNotice(null)
    }
  }, [selectedTaskId])

  useEffect(() => {
    void refreshWorkspace()
  }, [refreshWorkspace])

  const refreshConfigPreview = useCallback(async (taskId: number | null = selectedTask?.id ?? null) => {
    if (!taskId) {
      setConfigPreview(null)
      return null
    }
    setConfigPreviewLoading(true)
    try {
      const preview = await getJson<ConfigPreview>(`/api/config/preview?task_id=${taskId}`)
      setConfigPreview(preview)
      return preview
    } catch {
      setConfigPreview(null)
      return null
    } finally {
      setConfigPreviewLoading(false)
    }
  }, [selectedTask?.id])

  useEffect(() => {
    void refreshConfigPreview()
  }, [refreshConfigPreview])

  const refreshAgentConsole = useCallback(async (useFrameEndpoint = false) => {
    if (useFrameEndpoint) {
      try {
        const status = await postJson<AgentConsoleSession | null>('/api/agent-console/frame', {})
        setAgentConsole(status)
        return
      } catch {
        // Fall back to the lightweight status contract when the frame endpoint is not available.
      }
    }
    const status = await getJsonOrDefault<AgentConsoleSession | null>('/api/agent-console/status', null)
    setAgentConsole(status)
  }, [])

  useEffect(() => {
    if (!agentConsole?.active) return
    const timer = window.setInterval(() => {
      void refreshAgentConsole(Boolean(agentConsole?.browser_visible))
    }, 3500)
    return () => window.clearInterval(timer)
  }, [agentConsole?.active, agentConsole?.browser_visible, refreshAgentConsole])

  const refreshRuntimeLogs = useCallback(async () => {
    try {
      const loaded = await Promise.all(runtimeLogSources.map(async (source) => {
        const params = new URLSearchParams({
          source,
          cursor: String(runtimeLogCursorRef.current[source] ?? 0),
          limit: '120',
        })
        if (source === 'task' && selectedTask?.id) params.set('task_id', String(selectedTask.id))
        if (runtimeLogLevel !== 'all') params.set('level', runtimeLogLevel)
        if (runtimeLogQuery.trim()) params.set('q', runtimeLogQuery.trim())
        const response = await getJson<RuntimeLogResponse>(`/api/runtime/logs?${params.toString()}`)
        return [source, response] as const
      }))
      setRuntimeLogs((current) => {
        const next = { ...current }
        loaded.forEach(([source, response]) => {
          runtimeLogCursorRef.current[source] = response.nextCursor
          const existing = current[source]
          const shouldAppend = response.cursor > 0 && existing && existing.source === response.source
          const existingItems = existing?.items ?? existing?.lines.map((line) => ({ line, level: 'info', tags: [] })) ?? []
          const responseItems = response.items ?? response.lines.map((line) => ({ line, level: 'info', tags: [] }))
          const items = shouldAppend ? [...existingItems, ...responseItems].slice(-400) : responseItems
          next[source] = { ...response, items, lines: items.map((item) => item.line) }
        })
        return next
      })
      setRuntimeLogError(null)
    } catch (error) {
      setRuntimeLogError(error instanceof Error ? error.message : '读取运行日志失败')
    }
  }, [runtimeLogLevel, runtimeLogQuery, selectedTask?.id])

  useEffect(() => {
    runtimeLogCursorRef.current = { backend: 0, frontend: 0, launcher: 0, npm: 0, task: 0, agent: 0 }
    setRuntimeLogs({ backend: null, frontend: null, launcher: null, npm: null, task: null, agent: null })
  }, [runtimeLogLevel, runtimeLogQuery, selectedTask?.id])

  useEffect(() => {
    void refreshRuntimeLogs()
    const timer = window.setInterval(() => {
      void refreshRuntimeLogs()
    }, 1500)
    return () => window.clearInterval(timer)
  }, [refreshRuntimeLogs])

  const refreshRuntimeStatus = useCallback(async () => {
    const status = await getJsonOrDefault<RuntimeStatus | null>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`, null)
    setRuntimeStatus(status)
  }, [])

  useEffect(() => {
    void refreshRuntimeStatus()
    const timer = window.setInterval(() => {
      void refreshRuntimeStatus()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [refreshRuntimeStatus])

  async function createRealTask(request: RealTaskCreateRequest) {
    setBusy(true)
    setOperationError(null)
    try {
      const store = workspace.stores.find((item) => item.id === request.storeId)
      const products = workspace.products.filter((item) => request.productIds.includes(item.id))
      if (!store) {
        setOperationError('请先连接真实店铺，再创建任务。')
        setActiveSection('tasks')
        return
      }
      if (!products.length) {
        setOperationError('请至少选择一个真实商品。')
        setActiveSection('tasks')
        return
      }
      const firstProduct = products[0]
      const modeLabel = request.mode === 'probe' ? 'L2 只读检查' : 'L3 single_save'
      const task = await postJson<Task>('/api/tasks', {
        name: `${modeLabel} - ${store.name} - ${products.length} 件商品`,
        store_id: store.id,
        mode: request.mode,
        publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
        product_ids: products.map((item) => item.id),
        claim_mark: 'AI认领',
        payload: {
          store_name: store.name,
          category_name: firstProduct?.category_name ?? '未指定类目',
          image: firstProduct?.image,
          source: 'user_created_real_task',
          product_count: products.length,
        },
      })
      setSelectedTaskId(task.id)
      setActiveSection('tasks')
      await refreshWorkspace()
      await refreshConfigPreview(task.id)
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '创建真实任务失败')
    } finally {
      setBusy(false)
    }
  }

  async function bootstrapDemo() {
    const confirmed = window.confirm('这会向本地后端写入演示店铺、模板、商品和本地演示核验批次；不会访问店小秘，也不会启动真实保存。继续？')
    if (!confirmed) return
    setBusy(true)
    setOperationError(null)
    try {
      let stores = workspace.stores
      if (!stores.length || workspace.source === 'mock') {
        const store = await postJson<Store>('/api/stores/connect', { name: 'Dang Kang', platform: 'AliExpress' })
        stores = [store]
      }

      const existingTemplateTypes = new Set(workspace.templates.map((item) => item.template_type))
      const missingTemplates = demoTemplateSeeds.filter((item) => !existingTemplateTypes.has(item.template_type))
      if (missingTemplates.length) {
        await Promise.all(missingTemplates.map((template) => postJson('/api/templates', template)))
      }

      let products = workspace.products
      if (!products.length || workspace.source === 'mock') {
        products = await postJson<Product[]>('/api/products/import', { rows: seedRows })
      }

      const store = stores[0]
      const task = await postJson<Task>('/api/tasks', {
        name: '本地演示核验批次',
        store_id: store.id,
        mode: 'dry_run',
        publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
        product_ids: products.map((item) => item.id),
        claim_mark: 'AI认领',
        payload: {
          store_name: store.name,
          category_name: products[0]?.category_name ?? '立牌类谷子',
          image: products[0]?.image ?? seedRows[0].image,
        },
      })
      setSelectedTaskId(task.id)
      setActiveSection('tasks')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '准备演示数据失败')
    } finally {
      setBusy(false)
    }
  }

  async function startSelectedTask() {
    if (!selectedTask) return
    setBusy(true)
    setOperationError(null)
    try {
      if (REAL_DXM_MUTATION_MODES.has(selectedTask.mode)) {
        if (UNRELEASED_REAL_DXM_MUTATION_MODES.has(selectedTask.mode)) {
          setOperationError('当前真实 DXM 写入仅发布受控 single_save；claim_only/batch_save 必须重新建立 L2/L3 证据后再放行。')
          return
        }
        if (!RELEASED_REAL_DXM_MUTATION_MODES.has(selectedTask.mode)) {
          setOperationError(`当前执行模式 ${selectedTask.mode} 未发布，禁止启动真实 DXM 写入。`)
          return
        }
        const latestConfigPreview = await refreshConfigPreview(selectedTask.id)
        if (!latestConfigPreview || !latestConfigPreview.ok) {
          setOperationError(`配置预检未通过：${latestConfigPreview?.missing.slice(0, 6).join('、') || '请补齐 DXM 编辑页配置'}`)
          setActiveSection('config')
          return
        }
        const approvedBy = window.prompt('输入 L3 批准人标识。将只启动受控 single_save save-only 金丝雀，不会发布。', 'ops-owner')
        if (!approvedBy?.trim()) {
          setOperationError('已取消：真实任务启动必须填写 L3 批准人。')
          return
        }
        const approval = await postJson<ManualApprovalResponse>(`/api/tasks/${selectedTask.id}/manual-approval`, {
          approved_by: approvedBy.trim(),
          confirmation: L3_CONFIRMATION,
        })
        await postJson(`/api/tasks/${selectedTask.id}/start`, {
          manual_approval: true,
          approval_token: approval.approvalToken,
          approved_by: approvedBy.trim(),
          confirmation: approval.confirmation || L3_CONFIRMATION,
        })
      } else {
        await postJson(`/api/tasks/${selectedTask.id}/start`, {})
      }
      setActiveSection('console')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '启动保存核验任务失败')
    } finally {
      setBusy(false)
    }
  }

  async function openDxmLogin() {
    const username = window.prompt('输入店小秘账号。账号密码只用于本次真实店小秘登录，不会保存到配置中心。', '')
    if (!username?.trim()) {
      setOperationError('已取消：打开真实店小秘登录页需要账号。')
      return
    }
    const password = window.prompt('输入店小秘密码。后端只会记录脱敏状态，登录后请在真实浏览器处理验证码。', '')
    if (!password) {
      setOperationError('已取消：打开真实店小秘登录页需要密码。')
      return
    }
    setBusy(true)
    setOperationError(null)
    try {
      await postJson('/api/dxm/login/start', {
        username: username.trim(),
        password,
      })
      setActiveSection('console')
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '打开真实店小秘登录页失败')
      await refreshRuntimeStatus()
    } finally {
      setBusy(false)
    }
  }

  async function startAgentConsole() {
    if (!selectedTask) {
      setAgentConsoleError('请先选择一个保存核验任务')
      setActiveSection('console')
      return
    }
    const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
    if (l2Gate?.status !== 'passed') {
      const message = `只读诊断不可启动：${l2Gate?.detail ?? 'L2 真实只读 probe 未通过'}`
      setAgentConsoleError(message)
      setOperationError(message)
      setActiveSection('console')
      return
    }
    const step = buildAgentConsoleHudStep(workspace, selectedTask)
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleSession>('/api/agent-console/start', {
        task_id: selectedTask.id,
        target_url: AGENT_CONSOLE_TARGET_URL,
        launch_browser: true,
        step,
      })
      setAgentConsole(status)
      const hudStatus = await postJson<AgentConsoleSession>('/api/agent-console/hud', { step })
      setAgentConsole(hudStatus)
      setActiveSection('console')
    } catch (error) {
      const message = error instanceof Error ? error.message : '打开 Agent Console 失败'
      setAgentConsoleError(message)
      setOperationError(message)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function stopAgentConsole() {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleSession>('/api/agent-console/stop', {})
      setAgentConsole(status)
    } catch (error) {
      const message = error instanceof Error ? error.message : '关闭 Agent Console 失败'
      setAgentConsoleError(message)
      setOperationError(message)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function snapshotAgentConsole() {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleSession>('/api/agent-console/snapshot', {})
      setAgentConsole(status)
    } catch (error) {
      const message = error instanceof Error ? error.message : '抓取 Agent Console 截图失败'
      setAgentConsoleError(message)
      setOperationError(message)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function requestAgentConsoleTakeover() {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleSession>('/api/agent-console/takeover', {})
      setAgentConsole(status)
    } catch (error) {
      const message = error instanceof Error ? error.message : '人工接管真实浏览器失败'
      setAgentConsoleError(message)
      setOperationError(message)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function releaseAgentConsoleTakeover() {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleSession>('/api/agent-console/release', {})
      setAgentConsole(status)
    } catch (error) {
      const message = error instanceof Error ? error.message : '交还 Agent 失败'
      setAgentConsoleError(message)
      setOperationError(message)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function runRuntimeControl(action: RuntimeControlAction) {
    setBusy(true)
    setOperationError(null)
    try {
      const result = await postJson<RuntimeControlResponse>('/api/runtime/control', { action, task_id: selectedTask?.id ?? null })
      if (result.agentConsole) setAgentConsole(result.agentConsole)
      await refreshWorkspace()
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } catch (error) {
      const message = error instanceof Error ? error.message : '运行时维护动作失败'
      setOperationError(message)
      await refreshWorkspace()
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      setBusy(false)
    }
  }

  const content = (() => {
    switch (activeSection) {
      case 'config':
        return <ConfigCenter workspace={workspace} selectedTask={selectedTask} configPreview={configPreview} configPreviewLoading={configPreviewLoading} onConfigSaved={async () => { await refreshWorkspace(); await refreshConfigPreview() }} />
      case 'guide':
        return (
          <GuideCenter
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            runtimeStatus={runtimeStatus}
            onOpenDxmLogin={openDxmLogin}
            onStartTask={startSelectedTask}
            onShowConfig={() => setActiveSection('config')}
            onShowTasks={() => setActiveSection('tasks')}
            onShowConsole={() => setActiveSection('console')}
            onShowEvidence={() => setActiveSection('evidence')}
            onShowReports={() => setActiveSection('reports')}
            onShowExceptions={() => setActiveSection('exceptions')}
          />
        )
      case 'tasks':
        return (
          <TaskCenter
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            configPreviewLoading={configPreviewLoading}
            busy={busy}
            demoEnabled={DEMO_ENABLED}
            onSelectTask={(taskId) => {
              setSelectedTaskId(taskId)
              void refreshConfigPreview(taskId)
            }}
            onCreateRealTask={createRealTask}
            onBootstrapDemo={bootstrapDemo}
            onStartTask={startSelectedTask}
            onShowConfig={() => setActiveSection('config')}
            onShowConsole={() => setActiveSection('console')}
            onShowEvidence={() => setActiveSection('evidence')}
            onShowReports={() => setActiveSection('reports')}
          />
        )
      case 'console':
        return (
          <ExecutionConsole
            workspace={workspace}
            selectedTask={selectedTask}
            agentConsole={agentConsole}
            agentConsoleError={agentConsoleError}
            runtimeLogs={runtimeLogs}
            runtimeLogSource={runtimeLogSource}
            runtimeLogError={runtimeLogError}
            runtimeLogLevel={runtimeLogLevel}
            runtimeLogQuery={runtimeLogQuery}
            busy={busy}
            onRuntimeLogSourceChange={setRuntimeLogSource}
            onRuntimeLogLevelChange={setRuntimeLogLevel}
            onRuntimeLogQueryChange={setRuntimeLogQuery}
            onStartAgentConsole={startAgentConsole}
            onStopAgentConsole={stopAgentConsole}
            onSnapshotAgentConsole={snapshotAgentConsole}
            onRequestAgentConsoleTakeover={requestAgentConsoleTakeover}
            onReleaseAgentConsoleTakeover={releaseAgentConsoleTakeover}
            onRuntimeControl={runRuntimeControl}
            onShowTasks={() => setActiveSection('tasks')}
            onShowEvidence={() => setActiveSection('evidence')}
            onShowReports={() => setActiveSection('reports')}
          />
        )
      case 'evidence':
        return <EvidenceTimeline workspace={workspace} selectedTask={selectedTask} onShowTasks={() => setActiveSection('tasks')} onShowConsole={() => setActiveSection('console')} />
      case 'exceptions':
        return <ExceptionQueue workspace={workspace} selectedTask={selectedTask} />
      case 'reports':
        return <ReportCenter workspace={workspace} selectedTask={selectedTask} finalCheck={finalCheck} onShowEvidence={() => setActiveSection('evidence')} onShowConsole={() => setActiveSection('console')} />
      case 'dashboard':
      default:
        return <Dashboard workspace={workspace} selectedTask={selectedTask} />
    }
  })()

  return (
    <AppShell
      activeSection={activeSection}
      onSectionChange={setActiveSection}
      sidebarCollapsed={sidebarCollapsed}
      onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      sourceLabel={sourceLabels[workspace.source]}
    >
      <SafetyStatusBar
        workspace={workspace}
        selectedTask={selectedTask}
        runtimeStatus={runtimeStatus}
        busy={busy}
        onRefresh={() => { void refreshWorkspace(); void refreshRuntimeStatus(); void refreshRuntimeLogs(); void refreshConfigPreview() }}
        onShowTasks={() => setActiveSection('tasks')}
        onShowConsole={() => setActiveSection('console')}
      />
      {workspaceNotice && (
        <div className={`workspace-alert workspace-alert--${workspaceNotice.kind}`} role={workspaceNotice.kind === 'degraded' ? 'alert' : 'status'}>
          <strong>{workspaceNotice.title}</strong>
          <span>{workspaceNotice.detail}</span>
        </div>
      )}
      {operationError && (
        <div className="operation-alert" role="alert">
          <strong>操作未完成</strong>
          <span>{operationError}</span>
          <button className="button button--quiet" type="button" onClick={() => setOperationError(null)}>
            知道了
          </button>
        </div>
      )}
      {content}
    </AppShell>
  )
}

function buildAgentConsoleHudStep(workspace: DeliveryWorkspace, selectedTask: Task): AgentConsoleSession['hud'] {
  const storeName = String(selectedTask.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺')
  return {
    title: '只读诊断待命',
    state: 'READONLY_DIAGNOSTIC',
    action: '打开真实店小秘浏览器，不启动保存',
    next_step: '复核只读检查和人工确认',
    store_name: storeName,
    guard: '诊断观察，不保存不发布',
  }
}
