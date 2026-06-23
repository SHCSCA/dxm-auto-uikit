import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getJson, getJsonOrDefault, postJson } from './api'
import { AppShell } from './components/AppShell'
import { SafetyStatusBar } from './components/SafetyStatusBar'
import { AgentExecutionPage as ExecutionConsole } from './components/workbench/AgentExecutionPage'
import { AcquisitionClaimPage } from './components/workbench/AcquisitionClaimPage'
import { DraftEditSavePage } from './components/workbench/DraftEditSavePage'
import { HelpPage } from './components/workbench/HelpPage'
import { HomePage as Dashboard } from './components/workbench/HomePage'
import { ProductTasksPage as TaskCenter } from './components/workbench/ProductTasksPage'
import { TemplateCenterPage } from './components/workbench/TemplateCenterPage'
import {
  DxmAccessPage,
  EvidenceTimeline,
  ExceptionQueue,
  ReportCenter,
  SystemSettings,
} from './components/WorkbenchModules'
import { humanOperatorMessage } from './components/workbench/workbenchCopy'
import type { AcquisitionClaimCreateRequest, AcquisitionClaimResponse, AgentConsoleControlCommand, AgentConsoleControlResponse, AgentConsoleSession, ConfigPreview, DeliveryWorkspace, DesktopRuntimeInfo, DxmCredentialSaveResult, Evidence, ExceptionItem, FinalDeliveryCheckSummary, LegacyWorkbenchSection, LogItem, Product, RealTaskCreateRequest, Report, RuntimeControlAction, RuntimeControlResponse, RuntimeLogResponse, RuntimeLogSource, RuntimeStatus, Store, Task, Template, WorkbenchSection } from './types'
import { composeWorkspace, demoTemplateSeeds, seedRows } from './workspace'

const AGENT_CONSOLE_TARGET_URL = 'https://www.dianxiaomi.com/'
const DXM_TARGET_URLS = {
  data_acquisition: 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
  draft_box: 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
} as const
const DXM_TARGET_PATHS: Record<keyof typeof DXM_TARGET_URLS, string> = {
  data_acquisition: '/web/productCrawl/dataAcquisition',
  draft_box: '/web/smt/smtProductList/draft',
}
const DXM_TARGET_LABELS: Record<keyof typeof DXM_TARGET_URLS, string> = {
  data_acquisition: '采集页',
  draft_box: '采集箱',
}
const AGENT_CONSOLE_NAVIGATION_SETTLE_MS = 2500
const REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save', 'batch_save'])
const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save'])
const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['batch_save'])
const CLAIMED_DRAFT_PRODUCT_STATUSES = new Set(['claimed_to_draft', 'ready_for_edit'])
const DXM_READY_SESSION_STATUSES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])
const L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'
const DEMO_ENABLED = new URLSearchParams(window.location.search).get('dev') === '1'
  || (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_DXM_ENABLE_DEMO === '1'
const initialTaskIdFromUrl = (() => {
  const rawTaskId = new URLSearchParams(window.location.search).get('task_id')
  const taskId = Number(rawTaskId)
  return Number.isInteger(taskId) && taskId > 0 ? taskId : null
})()

const sourceLabels: Record<DeliveryWorkspace['source'], string> = {
  api: '工作台数据已连接',
  fallback: '本机工作台服务部分连接',
  mock: '正在连接本机工作台服务',
}
type DeliveryWorkspaceResponse = Partial<DeliveryWorkspace> & {
  current_task?: Task | null
  requested_task_missing?: boolean
  requested_task_id?: number | null
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

type DxmCredentialState = {
  available: boolean
  loaded: boolean
  saved: boolean
  message: string
}

type L2RunnerState = {
  status: 'idle' | 'running' | 'passed' | 'failed'
  runId: string | null
  exitCode: number | null
  message: string
  line: string | null
  updatedAt: string | null
}

type ManualApprovalResponse = {
  ok: boolean
  approvalToken: string
  confirmation: string
}

const runtimeLogSources: RuntimeLogSource[] = ['backend', 'frontend', 'launcher', 'npm', 'task', 'agent']

function compactDxmUrl(value: string | null | undefined) {
  if (!value) return '未知页面'
  try {
    const url = new URL(value)
    return `${url.hostname}${url.pathname}${url.search}`
  } catch {
    return value
  }
}
function currentUrlMatchesDxmTarget(value: string | null | undefined, target: keyof typeof DXM_TARGET_URLS) {
  if (!value) return false
  try {
    return new URL(value).pathname.startsWith(DXM_TARGET_PATHS[target])
  } catch {
    return value.includes(DXM_TARGET_PATHS[target])
  }
}

function waitForAgentConsoleNavigationSettle() {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, AGENT_CONSOLE_NAVIGATION_SETTLE_MS)
  })
}

function syncSelectedTaskIdUrl(taskId: number | null) {
  const url = new URL(window.location.href)
  if (taskId) {
    url.searchParams.set('task_id', String(taskId))
  } else {
    url.searchParams.delete('task_id')
  }
  window.history.replaceState(window.history.state, '', url.toString())
}

function normalizeWorkbenchSection(section: WorkbenchSection | LegacyWorkbenchSection): WorkbenchSection {
  const sectionAliases: Partial<Record<string, WorkbenchSection>> = {
    agent_execution: 'start_save',
    browser: 'start_save',
    dashboard: 'home',
    guide: 'help',
    tasks: 'acquisition_claim',
    product_tasks: 'acquisition_claim',
    current_task: 'acquisition_claim',
    task_history: 'acquisition_claim',
    config: 'template_center',
    edit_config: 'template_center',
    config_basic: 'template_center',
    config_category_title: 'template_center',
    config_price_stock: 'template_center',
    config_images: 'template_center',
    config_logistics: 'template_center',
    config_compliance: 'template_center',
    template_management: 'template_center',
    console: 'start_save',
    preflight: 'start_save',
    real_browser: 'start_save',
    manual_takeover: 'start_save',
    evidence: 'results',
    reports: 'results',
    exceptions: 'issues',
  }
  return sectionAliases[String(section)] ?? section as WorkbenchSection
}

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
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('home')
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(initialTaskIdFromUrl)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [agentConsole, setAgentConsole] = useState<AgentConsoleSession | null>(null)
  const [finalCheck, setFinalCheck] = useState<FinalDeliveryCheckSummary | null>(null)
  const [agentConsoleError, setAgentConsoleError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [operationNotice, setOperationNotice] = useState<string | null>(null)
  const [lastAcquisitionClaimRequest, setLastAcquisitionClaimRequest] = useState<AcquisitionClaimResponse | null>(null)
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
  const [l2RunnerState, setL2RunnerState] = useState<L2RunnerState>({
    status: 'idle',
    runId: null,
    exitCode: null,
    message: '等待运行真实只读检查',
    line: null,
    updatedAt: null,
  })
  const [lastRuntimeControlResult, setLastRuntimeControlResult] = useState<RuntimeControlResponse | null>(null)
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null)
  const [runtimeStatusError, setRuntimeStatusError] = useState<string | null>(null)
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeInfo | null>(null)
  const [configPreview, setConfigPreview] = useState<ConfigPreview | null>(null)
  const [configPreviewError, setConfigPreviewError] = useState<string | null>(null)
  const [configPreviewLoading, setConfigPreviewLoading] = useState(false)
  const [dxmLoginDraft, setDxmLoginDraft] = useState({ username: '', password: '', rememberCredential: false })
  const [dxmCredentialState, setDxmCredentialState] = useState<DxmCredentialState>({
    available: false,
    loaded: false,
    saved: false,
    message: '桌面安全存储检测中',
  })
  const [l3ApprovedBy, setL3ApprovedBy] = useState('')
  const [workspaceNotice, setWorkspaceNotice] = useState<WorkspaceNotice | null>({
    kind: 'loading',
    title: '正在加载 DXM 自动化工作台',
    detail: '正在读取任务、店铺、商品、证据和报告状态。',
  })
  const runtimeLogCursorRef = useRef<Record<RuntimeLogSource, number>>({
    backend: 0,
    frontend: 0,
    launcher: 0,
    npm: 0,
    task: 0,
    agent: 0,
  })
  const lastObservedL2CompletionRef = useRef<string | null>(null)

  const selectedTask = useMemo(
    () => workspace.tasks.find((task) => task.id === selectedTaskId) ?? workspace.tasks[0] ?? null,
    [selectedTaskId, workspace.tasks],
  )
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const visibleOperationError = selectedTaskCompleted && operationError?.includes('真实只读检查')
    ? null
    : operationError

  useEffect(() => {
    if (selectedTaskCompleted && operationError?.includes('真实只读检查')) {
      setOperationError(null)
    }
  }, [operationError, selectedTaskCompleted])

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
        detail: '正在读取任务、店铺、商品、证据和报告状态。',
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
      loadOrFallback<DeliveryWorkspaceResponse | null>(deliveryPath, null),
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
    const taskMissing = Boolean(deliveryWorkspace?.requested_task_missing)
      || failures.some((failure) => failure.path.startsWith('/api/delivery/workspace') && /task not found/i.test(failure.message))
    if (taskMissing) {
      const recoveredTaskId = pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks)
      setSelectedTaskId(recoveredTaskId)
      syncSelectedTaskIdUrl(recoveredTaskId)
    } else {
      setSelectedTaskId((current) => pickTaskIdForOperatorPath(current, deliveryWorkspace, nextWorkspace.tasks))
    }
    if (taskMissing) {
      setWorkspaceNotice({
        kind: 'degraded',
        title: '当前任务需要重新选择',
        detail: '上次选择的任务已不存在或已归档。系统已切回当前可用任务；如仍不能继续，请在“数据采集认领”或“采集箱编辑保存”重新创建任务。',
      })
    } else if (failures.length) {
      const firstFailure = failures[0]
      setWorkspaceNotice({
        kind: 'degraded',
        title: '工作台服务连接异常',
        detail: humanWorkspaceFetchError(firstFailure?.message),
      })
    } else {
      setWorkspaceNotice(null)
    }
    return nextWorkspace
  }, [selectedTaskId])

  useEffect(() => {
    void refreshWorkspace()
  }, [refreshWorkspace])

  const refreshConfigPreview = useCallback(async (taskId: number | null = selectedTask?.id ?? null) => {
    if (!taskId) {
      setConfigPreview(null)
      setConfigPreviewError(null)
      return null
    }
    setConfigPreviewLoading(true)
    try {
      const preview = await getJson<ConfigPreview>(`/api/config/preview?task_id=${taskId}`)
      setConfigPreview(preview)
      setConfigPreviewError(null)
      return preview
    } catch (error) {
      setConfigPreviewError(humanConfigPreviewError(error instanceof Error ? error.message : '配置检查接口不可用'))
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
        return status
      } catch {
        // Fall back to the lightweight status contract when the frame endpoint is not available.
      }
    }
    const status = await getJsonOrDefault<AgentConsoleSession | null>('/api/agent-console/status', null)
    setAgentConsole(status)
    return status
  }, [])

  useEffect(() => {
    if (!agentConsole?.active) return
    const normalizedSection = normalizeWorkbenchSection(activeSection)
    const shouldRefreshFrame = normalizedSection === 'start_save' && Boolean(agentConsole?.browser_visible)
    const timer = window.setInterval(() => {
      void refreshAgentConsole(shouldRefreshFrame)
    }, 3500)
    return () => window.clearInterval(timer)
  }, [activeSection, agentConsole?.active, agentConsole?.browser_visible, refreshAgentConsole])

  const refreshRuntimeLogs = useCallback(async () => {
    const loaded = await Promise.all(runtimeLogSources.map(async (source) => {
      try {
        const params = new URLSearchParams({
          source,
          cursor: String(runtimeLogCursorRef.current[source] ?? 0),
          limit: '120',
        })
        if (source === 'task' && selectedTask?.id) params.set('task_id', String(selectedTask.id))
        if (runtimeLogLevel !== 'all') params.set('level', runtimeLogLevel)
        if (runtimeLogQuery.trim()) params.set('q', runtimeLogQuery.trim())
        const response = await getJson<RuntimeLogResponse>(`/api/runtime/logs?${params.toString()}`)
        return { source, response, ok: true as const }
      } catch (error) {
        const message = error instanceof Error ? error.message : '读取运行日志失败'
        const cursor = runtimeLogCursorRef.current[source] ?? 0
        const response: RuntimeLogResponse = {
          source,
          path: 'runtime-log-fetch',
          exists: true,
          cursor,
          nextCursor: cursor,
          lines: [`${source} 日志读取失败：${message}`],
          items: [{ line: `${source} 日志读取失败：${message}`, level: 'error', tags: ['fetch_failed'] }],
          error: message,
        }
        return { source, response, ok: false as const, error: message }
      }
    }))
    const fetchedAt = new Date().toISOString()
    setRuntimeLogs((current) => {
      const next = { ...current }
      loaded.forEach(({ source, response, ok }) => {
        if (ok) runtimeLogCursorRef.current[source] = response.nextCursor
        const existing = current[source]
        const shouldAppend = ok && response.cursor > 0 && existing && existing.source === response.source
        const existingItems = existing?.items ?? existing?.lines.map((line) => ({ line, level: 'info', tags: [] })) ?? []
        const responseItems = response.items ?? response.lines.map((line) => ({ line, level: 'info', tags: [] }))
        const items = shouldAppend ? [...existingItems, ...responseItems].slice(-400) : responseItems
        next[source] = { ...response, fetchedAt, items, lines: items.map((item) => item.line) }
      })
      return next
    })
    const failed = loaded.filter((item) => !item.ok)
    setRuntimeLogError(failed.length
      ? `部分日志源读取失败：${failed.map((item) => item.source).join('、')}；其他日志继续刷新。`
      : null)
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
    try {
      const status = await getJson<RuntimeStatus>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`)
      setRuntimeStatus(status)
      setRuntimeStatusError(null)
    } catch (error) {
      setRuntimeStatus(null)
      setRuntimeStatusError(humanRuntimeStatusError(error instanceof Error ? error.message : '运行状态接口不可用'))
    }
  }, [])

  const handleL2RunnerFinished = useCallback(async ({
    runnerSucceeded,
    runId,
    exitCode,
    line,
  }: {
    runnerSucceeded: boolean
    runId: string | null
    exitCode: number | null
    line: string
  }) => {
    const refreshedWorkspace = await refreshWorkspace()
    await refreshRuntimeStatus()
    const refreshedL2Gate = refreshedWorkspace.regressionGates.find((gate) => gate.level === 'L2')
    const gatePassed = runnerSucceeded && refreshedL2Gate?.status === 'passed'
    if (gatePassed) {
      setL2RunnerState({ status: 'passed', runId, exitCode, message: '真实只读检查通过，已刷新门禁', line, updatedAt: new Date().toISOString() })
      return
    }
    const message = runnerSucceeded ? '真实只读检查已运行，但门禁未刷新通过' : '真实只读检查失败，真实保存仍阻断'
    const userLine = '真实只读检查未通过：请确认已登录并能打开商品采集页、草稿箱页后重试。'
    setL2RunnerState({ status: 'failed', runId, exitCode, message, line: userLine, updatedAt: new Date().toISOString() })
    setOperationError(`${message}；请确认真实店小秘已登录，再重新运行真实只读检查。系统不会保存或发布。`)
  }, [refreshRuntimeStatus, refreshWorkspace])

  useEffect(() => {
    const launcherItems = runtimeLogs.launcher?.items ?? []
    const runnerEvent = [...launcherItems]
      .reverse()
      .find((item) => item.line.includes('[l2-readonly-runner]'))
    if (!runnerEvent) return

    const runId = runnerEvent.line.match(/run_id=([^\s]+)/)?.[1] ?? null
    const exitCodeRaw = runnerEvent.line.match(/exit_code=([^\s]+)/)?.[1] ?? null
    const exitCode = exitCodeRaw !== null ? Number(exitCodeRaw) : null
    const eventKey = `${runId ?? 'no-run'}:${exitCodeRaw ?? 'running'}:${runnerEvent.line}`
    if (lastObservedL2CompletionRef.current === eventKey) return
    lastObservedL2CompletionRef.current = eventKey

    if (runnerEvent.line.includes('[l2-readonly-runner] finished')) {
      const runnerSucceeded = runnerEvent.line.includes('exit_code=0') || exitCode === 0
      void handleL2RunnerFinished({
        runnerSucceeded,
        runId,
        exitCode,
        line: runnerEvent.line,
      })
      return
    }

    if (runnerEvent.line.includes('[l2-readonly-runner] started')) {
      setL2RunnerState({ status: 'running', runId, exitCode: null, message: '正在运行双目标真实只读检查', line: runnerEvent.line, updatedAt: new Date().toISOString() })
    }
  }, [handleL2RunnerFinished, runtimeLogs.launcher])

  useEffect(() => {
    void refreshRuntimeStatus()
    const timer = window.setInterval(() => {
      void refreshRuntimeStatus()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [refreshRuntimeStatus])

  useEffect(() => {
    let cancelled = false
    async function loadDesktopRuntime() {
      const runtime = await window.dxmDesktop?.getRuntimeInfo?.()
      if (!cancelled && runtime) setDesktopRuntime(runtime)
    }
    void loadDesktopRuntime()
    const timer = window.setInterval(() => {
      void loadDesktopRuntime()
    }, 5000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function loadSavedCredential() {
      const loader = window.dxmDesktop?.loadDxmCredential
      if (!loader) {
        setDxmLoginDraft((current) => ({ ...current, rememberCredential: false }))
        setDxmCredentialState({
          available: false,
          loaded: false,
          saved: false,
          message: '当前不是桌面安全存储环境；不会保存密码。',
        })
        return
      }
      try {
        const result = await loader()
        if (cancelled) return
        if (result.ok && result.credential) {
          setDxmLoginDraft((current) => ({
            ...current,
            username: result.credential?.username ?? current.username,
            password: result.credential?.password ?? current.password,
            rememberCredential: true,
          }))
          setDxmCredentialState({
            available: result.available,
            loaded: true,
            saved: true,
            message: `已从本机加密保存载入账号${result.credential.updatedAt ? `，保存时间 ${new Date(result.credential.updatedAt).toLocaleString()}` : ''}。`,
          })
          return
        }
        setDxmCredentialState({
          available: result.available,
          loaded: false,
          saved: false,
          message: result.available ? '可记住账号密码；密码会写入本机加密保存。' : '本机加密保存不可用；不会保存密码。',
        })
        setDxmLoginDraft((current) => ({ ...current, rememberCredential: false }))
      } catch (error) {
        if (cancelled) return
        setDxmLoginDraft((current) => ({ ...current, rememberCredential: false }))
        setDxmCredentialState({
          available: false,
          loaded: false,
          saved: false,
          message: error instanceof Error ? error.message : '读取已保存账号失败',
        })
      }
    }
    void loadSavedCredential()
    return () => {
      cancelled = true
    }
  }, [])

  async function createRealTask(request: RealTaskCreateRequest) {
    setBusy(true)
    setOperationError(null)
    try {
      const store = workspace.stores.find((item) => item.id === request.storeId)
      const products = workspace.products.filter((item) => request.productIds.includes(item.id))
      if (!store) {
        setOperationError('请先连接真实店铺，再创建任务。')
        setActiveSection('product_tasks')
        return
      }
      if (!products.length) {
        setOperationError('请至少选择一个真实商品。')
        setActiveSection('product_tasks')
        return
      }
      if (request.mode === 'single_save' && products.length !== 1) {
        setOperationError(`单商品只保存一次只能选择 1 个商品；当前已选 ${products.length} 个。请取消多余商品后再创建。`)
        setActiveSection('product_tasks')
        return
      }
      const firstProduct = products[0]
      const modeLabel = request.mode === 'probe' ? '真实只读检查' : '单商品只保存'
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
      syncSelectedTaskIdUrl(task.id)
      setActiveSection(request.mode === 'single_save' ? 'draft_edit_save' : 'product_tasks')
      await refreshWorkspace()
      await refreshConfigPreview(task.id)
    } catch (error) {
      const message = error instanceof Error ? error.message : '创建真实任务失败'
      setOperationError(humanTaskCreateError(message))
    } finally {
      setBusy(false)
    }
  }

  async function createAcquisitionClaimRequest(request: AcquisitionClaimCreateRequest) {
    setBusy(true)
    setOperationError(null)
    setOperationNotice(null)
    try {
      const result = await postJson<AcquisitionClaimResponse>('/api/acquisition/claim-requests', {
        store_id: request.storeId,
        keyword: request.keyword,
        category_name: request.categoryName,
        claim_mark: request.claimMark,
        template_id: request.templateId ?? null,
      })
      setLastAcquisitionClaimRequest(result)
      if (result.task_id) {
        setSelectedTaskId(result.task_id)
        syncSelectedTaskIdUrl(result.task_id)
      }
      setOperationNotice('采集认领请求已创建。请打开真实数据采集页，按认领标记处理商品到采集箱。')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '创建采集认领请求失败')
    } finally {
      setBusy(false)
    }
  }

  async function bootstrapDemo() {
    if (!DEMO_ENABLED) {
      setOperationError('开发自检数据只在 dev=1 模式可用；真实使用请创建单商品只保存任务并运行真实只读检查。')
      return
    }
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
      syncSelectedTaskIdUrl(task.id)
      setActiveSection('product_tasks')
      await refreshWorkspace()
    } catch (error) {
      const message = error instanceof Error ? error.message : '准备演示数据失败'
      setOperationError(humanTaskCreateError(message))
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
          setOperationError('当前仅开放采集认领和单商品只保存；批量保存必须重新验收后再放行。')
          return
        }
        if (!RELEASED_REAL_DXM_MUTATION_MODES.has(selectedTask.mode)) {
          setOperationError(`当前执行模式 ${selectedTask.mode} 未发布，禁止启动真实 DXM 写入。`)
          return
        }
        const latestRuntimeStatus = await getJson<RuntimeStatus>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`)
        setRuntimeStatus(latestRuntimeStatus)
        const dxmLoginStatus = latestRuntimeStatus.dxmLogin?.status ?? ''
        if (!DXM_READY_SESSION_STATUSES.has(dxmLoginStatus)) {
          setOperationError(`请先完成真实 DXM 登录；当前登录状态：${dxmLoginStatus || '未知'}。`)
          setActiveSection('dxm_access')
          return
        }
        if (selectedTask.mode === 'claim_only') {
          await postJson(`/api/tasks/${selectedTask.id}/start`, {})
          setActiveSection('acquisition_claim')
          await refreshWorkspace()
          return
        }
        const latestConfigPreview = await refreshConfigPreview(selectedTask.id)
        if (!latestConfigPreview || !latestConfigPreview.ok) {
          setOperationError(`配置检查未通过：${latestConfigPreview?.missing.slice(0, 6).join('、') || '请补齐填写编辑页配置'}`)
          setActiveSection('edit_config')
          return
        }
        const approvedBy = l3ApprovedBy.trim()
        if (!approvedBy) {
          setOperationError('请填写批准人标识；将只启动单商品只保存任务，不会发布。')
          setActiveSection('product_tasks')
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
      setActiveSection('start_save')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(humanOperationError(error instanceof Error ? error.message : '启动保存核验任务失败'))
    } finally {
      setBusy(false)
    }
  }

  async function openDxmLogin() {
    const username = dxmLoginDraft.username.trim()
    if (!username) {
      setOperationError('请先在页面内填写店小秘账号，再打开真实店小秘登录页。')
      setActiveSection('dxm_access')
      return
    }
    if (!dxmLoginDraft.password) {
      setOperationError('请先在页面内填写店小秘密码；密码只用于本次真实登录请求，不写入编辑页配置。')
      setActiveSection('dxm_access')
      return
    }
    setBusy(true)
    setOperationError(null)
    try {
      if (dxmLoginDraft.rememberCredential) {
        const saver = window.dxmDesktop?.saveDxmCredential
        if (saver) {
          const saveResult = await saver({ username, password: dxmLoginDraft.password })
          setDxmCredentialState(credentialStateFromSave(saveResult))
        } else {
          setDxmCredentialState({
            available: false,
            loaded: false,
            saved: false,
            message: '当前不是桌面安全存储环境；本次不会保存密码。',
          })
        }
      } else {
        await clearSavedDxmCredential(false)
      }
      const loginStart = await postJson<Record<string, unknown>>('/api/dxm/login/start', {
        username,
        password: dxmLoginDraft.password,
      })
      setOperationNotice(humanDxmLoginFlowNotice(loginStart, '已打开真实店小秘登录页；请在弹出的真实浏览器中完成验证码。'))
      if (!dxmLoginDraft.rememberCredential) {
        setDxmLoginDraft((current) => ({ ...current, password: '' }))
      }
      const stage = String(loginStart.stage ?? '')
      setActiveSection(stage === 'waiting_captcha' ? 'dxm_access' : 'start_save')
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      const message = error instanceof Error ? error.message : '打开真实店小秘登录页失败'
      const humanMessage = humanDxmLoginError(message)
      setOperationError(humanMessage)
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      if (!dxmLoginDraft.rememberCredential) {
        setDxmLoginDraft((current) => ({ ...current, password: '' }))
      }
      setBusy(false)
    }
  }

  function credentialStateFromSave(result: DxmCredentialSaveResult): DxmCredentialState {
    if (result.ok) {
      return {
        available: result.available,
        loaded: true,
        saved: true,
        message: `账号密码已保存到本机加密保存${result.updatedAt ? `，保存时间 ${new Date(result.updatedAt).toLocaleString()}` : ''}。`,
      }
    }
    return {
      available: result.available,
      loaded: false,
      saved: false,
      message: result.error || '账号密码保存失败。',
    }
  }

  async function clearSavedDxmCredential(clearDraft = true) {
    const clearer = window.dxmDesktop?.clearDxmCredential
    if (clearer) {
      const result = await clearer()
      setDxmCredentialState({
        available: result.available,
        loaded: false,
        saved: false,
        message: result.ok ? '已清除本机保存的店小秘账号密码。' : result.error || '清除已保存账号失败。',
      })
    } else {
      setDxmCredentialState({
        available: false,
        loaded: false,
        saved: false,
        message: '当前不是桌面安全存储环境；没有可清除的本机密码。',
      })
    }
    if (clearDraft) {
      setDxmLoginDraft((current) => ({ ...current, password: '', rememberCredential: false }))
    }
  }

  async function continueDxmLogin() {
    setBusy(true)
    setOperationError(null)
    try {
      const loginResult = await postJson<Record<string, unknown>>('/api/dxm/login/continue', { confirm: true })
      const stage = String(loginResult.stage ?? '')
      const message = humanDxmLoginFlowNotice(loginResult, '已检测店小秘登录态。')
      const loginFailed = stage === 'login_failed' || stage.includes('failed')
      if (loginFailed) {
        setOperationError(message)
        setActiveSection('dxm_access')
      } else {
        setOperationNotice(message)
        setActiveSection(stage === 'waiting_captcha' ? 'dxm_access' : 'start_save')
      }
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      const message = error instanceof Error ? error.message : '继续检测店小秘登录态失败'
      const humanMessage = humanDxmLoginError(message)
      setOperationError(humanMessage)
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      setBusy(false)
    }
  }

  async function navigateDxmTarget(target: 'data_acquisition' | 'draft_box') {
    const targetUrl = DXM_TARGET_URLS[target]
    const targetLabel = DXM_TARGET_LABELS[target]
    setBusy(true)
    setOperationError(null)
    setOperationNotice(null)
    try {
      if (agentConsole?.active && agentConsole.browser_visible && !agentConsole.manual_takeover) {
        const status = await postJson<AgentConsoleControlResponse>('/api/agent-console/control', {
          action: 'goto',
          url: targetUrl,
        })
        setAgentConsole(status)
        if (status.ok === false) {
          const message = status.error || status.reason || `真实浏览器进入${targetLabel}失败`
          const humanMessage = humanDxmNavigationError(message, targetLabel)
          setAgentConsoleError(humanMessage)
          setOperationError(humanMessage)
          return
        }
        await waitForAgentConsoleNavigationSettle()
        const settledStatus = await refreshAgentConsole(true) ?? status
        setAgentConsoleError(null)
        if (currentUrlMatchesDxmTarget(settledStatus.current_url, target)) {
          setOperationNotice(`真实浏览器已进入${targetLabel}`)
        } else {
          setOperationError(`真实浏览器已发送进入${targetLabel}指令，但店小秘当前停留在 ${compactDxmUrl(settledStatus.current_url)}。请确认登录态后重试。`)
        }
      } else {
        const navigationResult = await postJson<Record<string, unknown>>('/api/dxm/navigate', { target })
        const navigationStage = String(navigationResult.stage ?? '')
        if (navigationStage.includes('failed')) {
          setOperationError(humanDxmNavigationNotice(navigationResult, `进入${targetLabel}失败`))
          setActiveSection('start_save')
          return
        }
        setOperationNotice(`已请求店小秘登录流进入${targetLabel}`)
      }
      setActiveSection('start_save')
      await refreshAgentConsole(true)
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      const message = error instanceof Error ? error.message : '进入店小秘业务页失败'
      setOperationError(humanDxmNavigationError(message, targetLabel))
      setOperationNotice(null)
      await refreshAgentConsole(true)
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      setBusy(false)
    }
  }

  async function startAgentConsole() {
    if (!selectedTask) {
      setAgentConsoleError('请先选择一个保存核验任务')
      setActiveSection('start_save')
      return
    }
    const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
    if (l2Gate?.status !== 'passed') {
      const message = '真实只读检查未通过，暂不能启动执行浏览器。请先运行真实只读检查；系统不会保存或发布。'
      setAgentConsoleError(message)
      setOperationError(message)
      setActiveSection('start_save')
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
      setActiveSection('start_save')
    } catch (error) {
      const message = error instanceof Error ? error.message : '打开 Agent Console 失败'
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
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
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
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
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
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
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
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
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
      await refreshAgentConsole()
    } finally {
      setBusy(false)
    }
  }

  async function controlAgentConsoleBrowser(command: AgentConsoleControlCommand) {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleControlResponse>('/api/agent-console/control', command)
      setAgentConsole(status)
      if (status.ok === false) {
        const message = status.error || status.reason || '页面内浏览器控制失败'
        const humanMessage = humanAgentConsoleError(message)
        setAgentConsoleError(humanMessage)
        setOperationError(humanMessage)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '页面内浏览器控制失败'
      const humanMessage = humanAgentConsoleError(message)
      setAgentConsoleError(humanMessage)
      setOperationError(humanMessage)
      await refreshAgentConsole(true)
    } finally {
      setBusy(false)
    }
  }

  async function runRuntimeControl(action: RuntimeControlAction) {
    setBusy(true)
    setOperationError(null)
    setOperationNotice(null)
    try {
      const result = await postJson<RuntimeControlResponse>('/api/runtime/control', { action, task_id: selectedTask?.id ?? null })
      setLastRuntimeControlResult(result)
      if (result.agentConsole) setAgentConsole(result.agentConsole)
      if (action === 'run_l2_readonly_probe' && result.runId) {
        setL2RunnerState({
          status: 'running',
          runId: result.runId,
          exitCode: null,
          message: '正在运行双目标真实只读检查',
          line: result.logPath ?? null,
          updatedAt: new Date().toISOString(),
        })
      }
      setOperationNotice(result.message ?? runtimeControlSuccessMessage(action))
      await refreshWorkspace()
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } catch (error) {
      const message = error instanceof Error ? error.message : '运行时维护动作失败'
      const humanMessage = humanOperationError(message)
      if (action === 'run_l2_readonly_probe') {
        setL2RunnerState({
          status: 'failed',
          runId: null,
          exitCode: null,
          message: '真实只读检查启动失败，真实保存仍阻断',
          line: humanMessage,
          updatedAt: new Date().toISOString(),
        })
      }
      setOperationError(humanMessage)
      setOperationNotice(null)
      await refreshWorkspace()
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      setBusy(false)
    }
  }

  async function runL2ReadonlyProbe() {
    setRuntimeLogSource('launcher')
    setL2RunnerState({ status: 'running', runId: null, exitCode: null, message: '正在运行双目标真实只读检查', line: null, updatedAt: new Date().toISOString() })
    setActiveSection('start_save')
    await runRuntimeControl('run_l2_readonly_probe')
  }

  const currentSection = normalizeWorkbenchSection(activeSection)
  const setWorkbenchSection = useCallback((section: WorkbenchSection) => {
    setActiveSection(normalizeWorkbenchSection(section))
  }, [])
  const claimedDraftProducts = useMemo(
    () => workspace.products.filter((product) => CLAIMED_DRAFT_PRODUCT_STATUSES.has(product.status)),
    [workspace.products],
  )
  const selectedEditSaveTask = selectedTask?.mode === 'single_save' ? selectedTask : null

  const content = (() => {
    switch (currentSection) {
      case 'edit_config':
      case 'config_basic':
      case 'config_category_title':
      case 'config_price_stock':
      case 'config_images':
      case 'config_logistics':
      case 'config_compliance':
      case 'template_center':
      case 'template_management':
        return (
          <TemplateCenterPage
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            configPreviewError={configPreviewError}
            configPreviewLoading={configPreviewLoading}
            onConfigSaved={async () => { await refreshWorkspace(); await refreshConfigPreview() }}
            onRefreshConfigPreview={async () => { await refreshConfigPreview(); await refreshWorkspace() }}
            onShowDraftEdit={() => setActiveSection('draft_edit_save')}
          />
        )
      case 'dxm_access':
        return (
          <DxmAccessPage
            runtimeStatus={runtimeStatus}
            runtimeStatusError={runtimeStatusError}
            dxmLoginDraft={dxmLoginDraft}
            dxmCredentialState={dxmCredentialState}
            busy={busy}
            onDxmLoginDraftChange={setDxmLoginDraft}
            onClearSavedDxmCredential={() => { void clearSavedDxmCredential() }}
            onOpenDxmLogin={openDxmLogin}
            onContinueDxmLogin={continueDxmLogin}
            onNavigateDxmTarget={navigateDxmTarget}
            onShowConsole={() => setActiveSection('start_save')}
          />
        )
      case 'acquisition_claim':
        return (
          <AcquisitionClaimPage
            stores={workspace.stores}
            templates={workspace.templates}
            busy={busy}
            lastRequest={lastAcquisitionClaimRequest}
            onCreateClaimRequest={(request) => { void createAcquisitionClaimRequest(request) }}
            onNavigateDataAcquisition={() => { void navigateDxmTarget('data_acquisition') }}
            onShowDraftEdit={() => setActiveSection('draft_edit_save')}
            onShowExecutionConsole={() => setActiveSection('start_save')}
          />
        )
      case 'product_tasks':
      case 'current_task':
      case 'task_history':
        return (
          <TaskCenter
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            configPreviewError={configPreviewError}
            configPreviewLoading={configPreviewLoading}
            runtimeStatus={runtimeStatus}
            runtimeStatusError={runtimeStatusError}
            busy={busy}
            demoEnabled={DEMO_ENABLED}
            l3ApprovedBy={l3ApprovedBy}
            onL3ApprovedByChange={setL3ApprovedBy}
            onRunL2Probe={runL2ReadonlyProbe}
            onSelectTask={(taskId) => {
              setSelectedTaskId(taskId)
              syncSelectedTaskIdUrl(taskId)
              void refreshConfigPreview(taskId)
            }}
            onCreateRealTask={createRealTask}
            onBootstrapDemo={bootstrapDemo}
            onStartTask={startSelectedTask}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowConsole={() => setActiveSection('start_save')}
            onShowEvidence={() => setActiveSection('results')}
            onShowReports={() => setActiveSection('results')}
          />
        )
      case 'draft_edit_save':
        return (
          <DraftEditSavePage
            claimedProducts={claimedDraftProducts}
            selectedTask={selectedEditSaveTask}
            busy={busy}
            onCreateSaveTask={(productId) => {
              const storeId = workspace.stores[0]?.id
              if (!storeId) {
                setOperationError('请先登录并连接真实店铺，再创建编辑保存任务。')
                setActiveSection('dxm_access')
                return
              }
              void createRealTask({ storeId, mode: 'single_save', productIds: [productId] })
            }}
            onShowAcquisition={() => setActiveSection('acquisition_claim')}
            onShowTemplates={() => setActiveSection('template_center')}
            onShowExecutionConsole={() => setActiveSection('start_save')}
          />
        )
      case 'start_save':
      case 'preflight':
      case 'real_browser':
      case 'manual_takeover':
        return (
          <ExecutionConsole
            workspace={workspace}
            selectedTask={selectedTask}
            agentConsole={agentConsole}
            agentConsoleError={agentConsoleError}
            configPreview={configPreview}
            configPreviewError={configPreviewError}
            configPreviewLoading={configPreviewLoading}
            runtimeStatus={runtimeStatus}
            runtimeStatusError={runtimeStatusError}
            desktopRuntime={desktopRuntime}
            runtimeLogs={runtimeLogs}
            runtimeLogSource={runtimeLogSource}
            runtimeLogError={runtimeLogError}
            runtimeLogLevel={runtimeLogLevel}
            runtimeLogQuery={runtimeLogQuery}
            l2RunnerState={l2RunnerState}
            lastRuntimeControlResult={lastRuntimeControlResult}
            busy={busy}
            dxmLoginDraft={dxmLoginDraft}
            dxmCredentialState={dxmCredentialState}
            onDxmLoginDraftChange={setDxmLoginDraft}
            onClearSavedDxmCredential={() => { void clearSavedDxmCredential() }}
            onRuntimeLogSourceChange={setRuntimeLogSource}
            onRuntimeLogLevelChange={setRuntimeLogLevel}
            onRuntimeLogQueryChange={setRuntimeLogQuery}
            onStartAgentConsole={startAgentConsole}
            onOpenDxmLogin={openDxmLogin}
            onContinueDxmLogin={continueDxmLogin}
            onNavigateDxmTarget={navigateDxmTarget}
            onStopAgentConsole={stopAgentConsole}
            onSnapshotAgentConsole={snapshotAgentConsole}
            onRequestAgentConsoleTakeover={requestAgentConsoleTakeover}
            onReleaseAgentConsoleTakeover={releaseAgentConsoleTakeover}
            onControlAgentConsoleBrowser={controlAgentConsoleBrowser}
            onRuntimeControl={runRuntimeControl}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowEvidence={() => setActiveSection('results')}
            onShowReports={() => setActiveSection('results')}
          />
        )
      case 'evidence':
        return <EvidenceTimeline workspace={workspace} selectedTask={selectedTask} onShowTasks={() => setActiveSection('product_tasks')} onShowConsole={() => setActiveSection('start_save')} />
      case 'issues':
        return <ExceptionQueue workspace={workspace} selectedTask={selectedTask} />
      case 'results':
        return <ReportCenter workspace={workspace} selectedTask={selectedTask} finalCheck={finalCheck} onShowEvidence={() => setActiveSection('results')} onShowConsole={() => setActiveSection('start_save')} onShowExceptions={() => setActiveSection('issues')} />
      case 'help':
        return (
          <HelpPage
            selectedTask={selectedTask}
            runtimeStatus={runtimeStatus}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowConsole={() => setActiveSection('start_save')}
            onShowResults={() => setActiveSection('results')}
            onShowIssues={() => setActiveSection('issues')}
          />
        )
      case 'settings':
        return <SystemSettings workspace={workspace} selectedTask={selectedTask} finalCheck={finalCheck} runtimeStatus={runtimeStatus} desktopRuntime={desktopRuntime} />
      case 'home':
      default:
        return (
          <Dashboard
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            runtimeStatus={runtimeStatus}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowConsole={() => setActiveSection('start_save')}
            onShowReports={() => setActiveSection('results')}
          />
        )
    }
  })()

  return (
    <AppShell
      activeSection={currentSection}
      onSectionChange={setWorkbenchSection}
      sidebarCollapsed={sidebarCollapsed}
      onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      sourceLabel={sourceLabels[workspace.source]}
    >
      <SafetyStatusBar
        workspace={workspace}
        selectedTask={selectedTask}
        configPreview={configPreview}
        configPreviewError={configPreviewError}
        configPreviewLoading={configPreviewLoading}
        runtimeStatus={runtimeStatus}
        runtimeStatusError={runtimeStatusError}
        desktopRuntime={desktopRuntime}
        busy={busy}
        onRefresh={() => { void refreshWorkspace(); void refreshRuntimeStatus(); void refreshRuntimeLogs(); void refreshConfigPreview() }}
        onShowDxmAccess={() => setActiveSection('dxm_access')}
        onShowConfig={() => setActiveSection('edit_config')}
        onShowTasks={() => setActiveSection('product_tasks')}
        onShowConsole={() => setActiveSection('start_save')}
        onShowReports={() => setActiveSection('results')}
      />
      <div className="operation-toast-stack" aria-live="polite">
        {workspaceNotice && (
          <details className={`workspace-alert workspace-alert--${workspaceNotice.kind}`} role={workspaceNotice.kind === 'degraded' ? 'alert' : 'status'} data-testid="workspace-notice">
            <summary className="workspace-alert__summary">
              <strong>{workspaceNotice.title}</strong>
              <span>查看详情</span>
            </summary>
            <p className="workspace-alert__detail">{workspaceNotice.detail}</p>
            <div className="workspace-alert__actions">
              <button className="button button--quiet" type="button" onClick={() => { void refreshWorkspace(); void refreshRuntimeStatus() }}>
                刷新状态
              </button>
              <button className="button button--quiet" type="button" onClick={() => setWorkspaceNotice(null)}>
                暂时收起
              </button>
            </div>
          </details>
        )}
        {visibleOperationError && (
          <div className="operation-alert" role="alert">
            <strong>操作需要重试</strong>
            <span>{visibleOperationError}</span>
            <button className="button button--quiet" type="button" onClick={() => setOperationError(null)}>
              知道了
            </button>
          </div>
        )}
        {operationNotice && (
          <div className="operation-alert operation-alert--ok" role="status" data-testid="operation-notice">
            <strong>操作已提交</strong>
            <span>{operationNotice}</span>
            <button className="button button--quiet" type="button" onClick={() => setOperationNotice(null)}>
              知道了
            </button>
          </div>
        )}
      </div>
      {content}
    </AppShell>
  )
}

function runtimeControlSuccessMessage(action: RuntimeControlAction) {
  return ({
    stop_agent_console: '浏览器 Agent 已停止。',
    clear_stuck_tasks: '已提交清理卡住任务请求。',
    mark_real_task_manual_review: '已将真实写入任务转入人工复核。不会取消真实浏览器进程，请查看任务日志确认现场。',
    restart_backend: '已提交后端重启请求，请查看启动器日志。',
    restart_frontend: '已提交前端重启请求，请查看启动器日志。',
    run_l2_readonly_probe: '已启动真实只读检查，请在“开始只保存”查看实时日志。',
  } as Record<RuntimeControlAction, string>)[action]
}

function humanOperationError(message: string) {
  const runtimeStatusMessage = humanRuntimeStatusError(message)
  if (runtimeStatusMessage !== message) return runtimeStatusMessage
  if (message.includes('L2 readonly probe resources are missing')) {
    return `真实只读检查组件未安装完整，请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${checkedPathHint(message)}`
  }
  if (message.includes('L2 readonly probe runner is missing')) {
    return `真实只读检查组件未安装完整：缺少真实只读检查启动器。请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${searchedPathHint(message)}`
  }
  if (message.includes('L2 readonly probe script is missing')) {
    return `真实只读检查组件未安装完整：缺少真实只读检查脚本。请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${searchedPathHint(message)}`
  }
  const operatorMessage = humanOperatorMessage(message)
  if (operatorMessage !== message) return operatorMessage
  return message
}

function humanConfigPreviewError(message: string) {
  const runtimeStatusMessage = humanRuntimeStatusError(message)
  if (runtimeStatusMessage !== message) return `配置检查失败：${runtimeStatusMessage}`
  const operatorMessage = humanOperatorMessage(message)
  if (operatorMessage !== message) return `配置检查失败：${operatorMessage}`
  const normalized = message.toLowerCase()
  if (
    normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
  ) {
    return '配置检查失败：本机工作台服务暂时不可用，请重新打开免安装版或确认后端服务正在运行。'
  }
  return message
}

function humanWorkspaceFetchError(message?: string) {
  const normalized = (message ?? '').toLowerCase()
  if (
    normalized.includes('/api/delivery/workspace')
    || normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
    || normalized.includes('failed (500)')
  ) {
    return '暂时无法读取完整任务数据。请重新打开 DXM Agent Console 免安装版；开发模式请确认后端服务正在运行。真实保存不会启动或发布。'
  }
  return '暂时无法读取完整任务数据。请查看“开始只保存”的实时日志；系统不会用本地演示结果替代真实保存。'
}

function humanRuntimeStatusError(message: string) {
  const normalized = message.toLowerCase()
  if (
    normalized.includes('get /api/runtime/status')
    || normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
  ) {
    return '本机后端未连接：请重新打开 DXM Agent Console 免安装版；开发模式请先启动后端服务。真实保存不会启动或发布。'
  }
  return message
}

function humanTaskCreateError(message: string) {
  const normalized = message.toLowerCase()
  if (
    normalized.includes('internal server error')
    || normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
    || normalized.includes('traceback')
  ) {
    return '任务创建失败：请确认本机工作台服务正常、店铺和商品数据完整后重试；真实保存不会启动。'
  }
  if (normalized.includes('publish') || message.includes('发布')) {
    return '任务创建失败：当前只允许单商品只保存，不开放发布、批量或无人值守。'
  }
  return message
}

function humanDxmNavigationError(message: string, targetLabel: string) {
  const browserRuntimeMessage = humanBrowserRuntimeError(message)
  if (browserRuntimeMessage) {
    return `真实浏览器进入${targetLabel}失败：${browserRuntimeMessage}系统不会保存或发布。`
  }
  const normalized = message.toLowerCase()
  if (
    normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
  ) {
    return `真实浏览器进入${targetLabel}失败：本机后端暂时不可用，请重新打开 DXM Agent Console 免安装版后重试。系统不会保存或发布。`
  }
  return `真实浏览器进入${targetLabel}失败：请确认店小秘窗口仍打开且已登录；必要时关闭旧控制台后重试。系统不会保存或发布。`
}

function humanDxmLoginError(message: string) {
  const normalized = message.toLowerCase()
  const commonTail = '账号密码不会用于保存或发布；可在右侧实时日志查看后端和启动器细节。'
  const browserRuntimeMessage = humanBrowserRuntimeError(message)
  if (browserRuntimeMessage) return `${browserRuntimeMessage}${commonTail}`
  if (
    message.includes('Internal Server Error')
    || normalized.includes('post /api/dxm/login/start failed')
    || normalized.includes('post /api/dxm/login/continue failed')
  ) {
    return `真实店小秘登录浏览器启动失败：本机后端返回异常。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试；如果仍失败，重开免安装 EXE。${commonTail}`
  }
  if (
    normalized.includes('browser has been closed')
    || message.includes('Target page, context or browser has been closed')
    || normalized.includes('context or browser has been closed')
  ) {
    return `真实店小秘登录浏览器已关闭或被占用。请保留新打开的真实浏览器窗口，或重新点击“打开真实登录页”。${commonTail}`
  }
  if (
    normalized.includes('user data directory is already in use')
    || normalized.includes('profile')
    || normalized.includes('locked')
  ) {
    return `真实店小秘登录浏览器数据目录被旧进程占用。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试。${commonTail}`
  }
  if (
    normalized.includes('executable')
    || normalized.includes('playwright')
    || normalized.includes('chromium')
  ) {
    return `真实店小秘登录浏览器依赖缺失或不可启动。请重新打开完整免安装目录版，并查看实时日志中的依赖安装结果。${commonTail}`
  }
  if (normalized.includes('login_failed')) {
    return `真实店小秘登录未完成。请在可见浏览器窗口内修正验证码或账号密码，再点击“验证码完成后检测登录状态”。${commonTail}`
  }
  return message
}

function humanAgentConsoleError(message: string) {
  const normalized = message.toLowerCase()
  const commonTail = '执行浏览器只会在真实只读检查和人工确认通过后接入真实店小秘页面；不会自动发布。'
  const browserRuntimeMessage = humanBrowserRuntimeError(message)
  if (browserRuntimeMessage) return `${browserRuntimeMessage}${commonTail}`
  if (
    message.includes('Internal Server Error')
    || normalized.includes('post /api/agent-console/start failed')
  ) {
    return `真实执行浏览器启动失败：本机后端返回异常。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试；如果仍失败，重开免安装 EXE。${commonTail}`
  }
  if (
    normalized.includes('browser has been closed')
    || message.includes('Target page, context or browser has been closed')
    || normalized.includes('context or browser has been closed')
  ) {
    return `真实执行浏览器已关闭或启动后立即退出。请保留新打开的真实浏览器窗口，或关闭旧进程后回到“开始只保存”重新打开。${commonTail}`
  }
  if (
    normalized.includes('user data directory is already in use')
    || normalized.includes('profile')
    || normalized.includes('locked')
  ) {
    return `真实执行浏览器数据目录被旧进程占用。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试。${commonTail}`
  }
  if (
    normalized.includes('executable')
    || normalized.includes('playwright')
    || normalized.includes('chromium')
  ) {
    return `真实执行浏览器依赖缺失或不可启动。请重新打开完整免安装目录版，并查看“开始只保存”的实时日志。${commonTail}`
  }
  return message
}

function humanBrowserRuntimeError(message: string) {
  const normalized = message.toLowerCase()
  if (
    message.includes('Cannot switch to a different thread')
    || message.includes('Playwright Sync API')
    || normalized.includes('greenlet')
  ) {
    return '浏览器会话冲突：请保留当前真实店小秘窗口，关闭旧的 DXM Agent Console 或旧浏览器进程后重新检测。'
  }
  if (
    normalized.includes('browser has been closed')
    || message.includes('Target page, context or browser has been closed')
    || normalized.includes('context or browser has been closed')
  ) {
    return '真实浏览器窗口已关闭或被旧进程接管：请重新打开真实登录页，完成登录后再检测。'
  }
  if (
    normalized.includes('internal server error')
    || normalized.includes('failed (500)')
  ) {
    return '本机后端执行失败：请关闭旧进程后重新打开 DXM Agent Console 免安装版，再继续当前流程。'
  }
  return ''
}

function searchedPathHint(message: string) {
  const marker = 'Searched:'
  const index = message.indexOf(marker)
  if (index < 0) return ''
  const paths = message
    .slice(index + marker.length)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 3)
  return paths.length ? ` 已检查：${paths.join('；')}` : ''
}

function checkedPathHint(message: string) {
  const marker = 'Checked:'
  const index = message.indexOf(marker)
  if (index < 0) return ''
  const paths = message
    .slice(index + marker.length)
    .split(';')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 4)
  return paths.length ? ` 已检查：${paths.join('；')}` : ''
}

function humanDxmLoginFlowNotice(result: Record<string, unknown>, fallback: string) {
  const stage = String(result.stage ?? '').trim()
  const message = String(result.message ?? '').trim()
  const nextAction = String(result.next_action ?? '').trim()
  if (stage === 'waiting_captcha') {
    return '等待验证码不是失败：已打开可见浏览器窗口；请在真实店小秘页面完成验证码。下一步：完成后点击“验证码完成后检测登录状态”。'
  }
  if (stage === 'login_failed' || stage.includes('failed')) {
    return `登录还没完成，不是系统故障：${message || '未检测到有效登录态。'} 下一步：${nextAction || '请打开着真实浏览器，修正验证码或账号密码后再次检测。'}`
  }
  if (message && nextAction) return `${message} 下一步：${nextAction}`
  return message || nextAction || fallback
}

function humanDxmNavigationNotice(result: Record<string, unknown>, fallback: string) {
  const message = String(result.message ?? '').trim()
  const nextAction = String(result.next_action ?? '').trim()
  const rawError = String(result.raw_error ?? '').trim()
  const summary = message || '真实店小秘业务页进入失败。'
  const next = nextAction || '请确认真实浏览器窗口仍然打开且已登录；必要时重新打开真实登录页。'
  const rawRecovery = rawError ? humanBrowserRuntimeError(rawError) : ''
  return `${summary} 下一步：${next}${rawRecovery ? ` 处理：${rawRecovery}` : ''}`.trim()
}

function pickDefaultTaskId(deliveryWorkspace: DeliveryWorkspaceResponse | null, tasks: Task[]): number | null {
  const deliveryTaskId = deliveryWorkspace?.current_task?.id
  const deliveryTask = typeof deliveryTaskId === 'number'
    ? tasks.find((task) => task.id === deliveryTaskId)
    : null
  if (deliveryTask && isDefaultSelectableSingleSaveTask(deliveryTask)) {
    return deliveryTask.id
  }
  return tasks.find(isActionableSingleSaveTask)?.id
    ?? (deliveryTask && isDefaultSelectableSingleSaveTask(deliveryTask) ? deliveryTask.id : null)
    ?? tasks.find((task) => task.mode === 'single_save')?.id
    ?? tasks.find(isSafeDefaultFallbackTask)?.id
    ?? null
}

function pickTaskIdForOperatorPath(currentTaskId: number | null, deliveryWorkspace: DeliveryWorkspaceResponse | null, tasks: Task[]): number | null {
  const currentTask = currentTaskId ? tasks.find((task) => task.id === currentTaskId) : null
  if (currentTask && isActionableSingleSaveTask(currentTask)) return currentTask.id
  return pickDefaultTaskId(deliveryWorkspace, tasks)
}

function isActionableSingleSaveTask(task: Task) {
  return task.mode === 'single_save' && !['completed', 'cancelled', 'archived'].includes(String(task.status || ''))
}

function isDefaultSelectableSingleSaveTask(task: Task) {
  return task.mode === 'single_save' && !['cancelled', 'archived'].includes(String(task.status || ''))
}

function isSafeDefaultFallbackTask(task: Task) {
  return !UNRELEASED_REAL_DXM_MUTATION_MODES.has(String(task.mode))
}

function buildAgentConsoleHudStep(workspace: DeliveryWorkspace, selectedTask: Task): AgentConsoleSession['hud'] {
  const storeName = String(selectedTask.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺')
  return {
    title: '准备开始只保存',
    state: 'READY_FOR_SINGLE_SAVE',
    action: '真实浏览器已打开，等待按任务流程执行',
    next_step: '人工确认后由 Agent 输入编辑页内容并只点击保存',
    store_name: storeName,
    guard: '只保存，不发布',
    phase: '开始任务',
    progress_index: 1,
    progress_total: 12,
    human_title: '准备开始只保存',
    human_action: '真实浏览器已打开，Agent 将按步骤操作店小秘编辑页',
    human_next: '人工确认后开始输入标题、选择分类、设置价格库存并只保存',
    requires_user_action: true,
    severity: 'warning',
  }
}
