import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getJson, getJsonOrDefault, postJson, withDxmSessionBusyRetry } from './api'
import { AppShell } from './components/AppShell'
import { SafetyStatusBar } from './components/SafetyStatusBar'
import { AgentExecutionPage as ExecutionConsole } from './components/workbench/AgentExecutionPage'
import { AcquisitionClaimPage } from './components/workbench/AcquisitionClaimPage'
import { BatchEditPage } from './components/workbench/BatchEditPage'
import { BatchRecordsPage } from './components/workbench/BatchRecordsPage'
import { DraftSelectionPage } from './components/workbench/DraftSelectionPage'
import { BatchSavePlaceholderPage } from './components/workbench/BatchSavePlaceholderPage'
import { HelpPage } from './components/workbench/HelpPage'
import { HomePage as Dashboard } from './components/workbench/HomePage'
import { ProductTasksPage as TaskCenter } from './components/workbench/ProductTasksPage'
import { DxmTemplateLibraryPage } from './components/workbench/DxmTemplateLibraryPage'
import { TemplateCenterPage, type TemplateCenterMode } from './components/workbench/TemplateCenterPage'
import {
  DxmAccessPage,
  EvidenceTimeline,
  ExceptionQueue,
  ReportCenter,
  SystemSettings,
} from './components/WorkbenchModules'
import { OperationAuditTimeline } from './components/workbench/OperationAuditTimeline'
import { humanOperatorMessage } from './components/workbench/workbenchCopy'
import { DxmShopProvider } from './dxmShopContext'
import type { ConfirmedDraftTaskInput } from './draftSelection'
import { isSupportedSourceProductUrl } from './sourceUrl'
import type { AcquisitionClaimCreateRequest, AcquisitionClaimResponse, AgentConsoleControlCommand, AgentConsoleControlResponse, AgentConsoleSession, ConfigPreview, DeliveryWorkspace, DesktopRuntimeInfo, DraftBoxScopeSnapshot, DxmCredentialSaveResult, DxmDraftShop, DxmDraftShopsResponse, DxmTemplateRef, EditBatchSummary, Evidence, ExceptionItem, FinalDeliveryCheckSummary, LegacyWorkbenchSection, LocalPlanTemplate, LogItem, Product, RealTaskCreateRequest, Report, RuntimeControlAction, RuntimeControlResponse, RuntimeLogResponse, RuntimeLogSource, RuntimeStatus, Store, Task, Template, WorkbenchSection } from './types'
import { isTaskControlActive } from './taskControl'
import { composeWorkspace } from './workspace'

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
  data_acquisition: '已有待认领列表',
  draft_box: '商品箱',
}
const AGENT_CONSOLE_NAVIGATION_SETTLE_MS = 2500
const REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save', 'batch_save', 'batch_draft_save'])
const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'single_save', 'batch_draft_save'])
const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['batch_save'])
const DXM_READY_SESSION_STATUSES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])
const CLAIM_ONLY_CONFIRMATION = '确认将该已有商品认领到商品箱'
const L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'
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
    tasks: 'product_tasks',
    product_tasks: 'product_tasks',
    current_task: 'product_tasks',
    task_history: 'task_history',
    config: 'template_center',
    edit_config: 'template_center',
    config_basic: 'template_center',
    config_category_title: 'template_center',
    config_price_stock: 'template_center',
    config_images: 'template_center',
    config_logistics: 'template_center',
    config_compliance: 'template_center',
    console: 'start_save',
    preflight: 'start_save',
    real_browser: 'start_save',
    manual_takeover: 'start_save',
    reports: 'results',
    exceptions: 'issues',
    issues: 'issues',
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
  const [dxmShops, setDxmShops] = useState<DxmDraftShop[]>([])
  const [dxmShopsSnapshot, setDxmShopsSnapshot] = useState<DxmDraftShopsResponse | null>(null)
  const [selectedDxmShopId, setSelectedDxmShopId] = useState('')
  const [dxmShopsLoading, setDxmShopsLoading] = useState(false)
  const [dxmShopsError, setDxmShopsError] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('home')
  const [activeEditBatchId, setActiveEditBatchId] = useState<number | null>(null)
  const [activeScopeSnapshot, setActiveScopeSnapshot] = useState<DraftBoxScopeSnapshot | null>(null)
  const [draftTaskInput, setDraftTaskInput] = useState<ConfirmedDraftTaskInput | null>(null)
  const [editBatches, setEditBatches] = useState<EditBatchSummary[]>([])
  const [localPlans, setLocalPlans] = useState<LocalPlanTemplate[]>([])
  const [dxmTemplateRefs, setDxmTemplateRefs] = useState<DxmTemplateRef[]>([])
  const [editBatchStateAvailable, setEditBatchStateAvailable] = useState(false)
  const [templateCenterEntryMode, setTemplateCenterEntryMode] = useState<TemplateCenterMode>('sections')
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(initialTaskIdFromUrl)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dxmLoginRequestPending, setDxmLoginRequestPending] = useState(false)
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
    message: '等待运行保存前安全检查',
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
  // refreshWorkspace is called by page entry, background polling and sync
  // completion.  An older Promise.all can finish after a newer template sync
  // and overwrite its 35 refs with its earlier empty snapshot.  Only the
  // newest refresh is allowed to commit UI state.
  const workspaceRefreshGenerationRef = useRef(0)
  const dxmShopRefreshPromiseRef = useRef<Promise<DxmDraftShopsResponse | null> | null>(null)

  const refreshDxmShops = useCallback(async (force = false): Promise<DxmDraftShopsResponse | null> => {
    if (!force && dxmShopsSnapshot) return dxmShopsSnapshot
    if (dxmShopRefreshPromiseRef.current) return dxmShopRefreshPromiseRef.current

    const refreshPromise = (async (): Promise<DxmDraftShopsResponse | null> => {
      setDxmShopsLoading(true)
      setDxmShopsError(null)
      try {
        const response = await withDxmSessionBusyRetry(
          () => getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops'),
        )
        setDxmShopsSnapshot(response)
        setDxmShops(response.shops)
        setSelectedDxmShopId((current) => (
          current && response.shops.some((shop) => shop.id === current)
            ? current
            : response.shops[0]?.id ?? ''
        ))
        return response
      } catch (error) {
        // Keep the last verified shop list during a transient login/session
        // busy window; an empty response must never silently switch shops.
        setDxmShopsError(error instanceof Error ? error.message : '店铺列表读取失败，请稍后重试。')
        return null
      } finally {
        setDxmShopsLoading(false)
      }
    })()
    dxmShopRefreshPromiseRef.current = refreshPromise
    try {
      return await refreshPromise
    } finally {
      if (dxmShopRefreshPromiseRef.current === refreshPromise) {
        dxmShopRefreshPromiseRef.current = null
      }
    }
  }, [dxmShopsSnapshot])

  const selectedTask = useMemo(
    () => workspace.tasks.find((task) => task.id === selectedTaskId) ?? workspace.tasks[0] ?? null,
    [selectedTaskId, workspace.tasks],
  )
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const visibleOperationError = selectedTaskCompleted && operationError?.includes('保存前安全检查')
    ? null
    : operationError

  useEffect(() => {
    if (selectedTaskCompleted && operationError?.includes('保存前安全检查')) {
      setOperationError(null)
    }
  }, [operationError, selectedTaskCompleted])

  useEffect(() => {
    void postJson('/api/operation-audit/client-events', {
      action: 'page_switch',
      component: 'workbench',
      phase: 'completed',
      status: 'ok',
      correlation_id: `page-${activeSection}`,
      root_correlation_id: 'workbench',
      input: { section: activeSection },
    }).catch(() => undefined)
  }, [activeSection])

  const refreshWorkspace = useCallback(async (options?: { silent?: boolean }) => {
    const refreshGeneration = workspaceRefreshGenerationRef.current + 1
    workspaceRefreshGenerationRef.current = refreshGeneration
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

    if (!options?.silent) {
      setWorkspaceNotice((current) => current?.kind === 'degraded'
        ? current
        : {
          kind: 'loading',
          title: '正在加载 DXM 自动化工作台',
          detail: '正在读取任务、店铺、商品、证据和报告状态。',
        })
    }
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
      batchSummaries,
      fetchedLocalPlans,
      fetchedDxmTemplateRefs,
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
      loadOrFallback<EditBatchSummary[]>('/api/edit-batches', []),
      loadOrFallback<LocalPlanTemplate[]>('/api/local-plan-templates', []),
      loadOrFallback<DxmTemplateRef[]>('/api/dxm-template-refs', []),
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
    if (refreshGeneration !== workspaceRefreshGenerationRef.current) {
      return nextWorkspace
    }
    const editBatchStateFailed = failures.some((failure) => failure.path === '/api/edit-batches')
    setWorkspace(nextWorkspace)
    if (!editBatchStateFailed) setEditBatches(batchSummaries)
    setLocalPlans(fetchedLocalPlans)
    setDxmTemplateRefs(fetchedDxmTemplateRefs)
    setEditBatchStateAvailable(!editBatchStateFailed)
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
        detail: '上次选择的任务已不存在或已归档。系统已切回当前可用任务；如仍不能继续，请在“待认领商品”或“商品箱编辑保存”重新创建任务。',
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

  const workspaceHasRunningTask = workspace.tasks.some((task) => isTaskControlActive(task.status))
  const workspaceHasRunningBatch = editBatches.some((batch) => batch.status === 'running' || batch.status === 'stop_requested')
  const runningEditBatch = editBatches.find((batch) => batch.status === 'running' || batch.status === 'stop_requested') ?? null
  const runningMutationTask = workspace.tasks.find((task) => isTaskControlActive(task.status) && REAL_DXM_MUTATION_MODES.has(task.mode)) ?? null

  useEffect(() => {
    if (!workspaceHasRunningTask && !workspaceHasRunningBatch && !agentConsole?.active) return
    const timer = window.setInterval(() => {
      void refreshWorkspace({ silent: true })
    }, 1500)
    return () => window.clearInterval(timer)
  }, [agentConsole?.active, refreshWorkspace, workspaceHasRunningBatch, workspaceHasRunningTask])

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
      setL2RunnerState({ status: 'passed', runId, exitCode, message: '保存前安全检查通过，已刷新状态', line, updatedAt: new Date().toISOString() })
      return
    }
    const message = runnerSucceeded ? '保存前安全检查已运行，但状态未刷新通过' : '保存前安全检查失败，真实保存仍阻断'
    const userLine = '保存前安全检查未通过：请确认已登录并能打开已有待认领列表、商品箱页面后重试。'
    setL2RunnerState({ status: 'failed', runId, exitCode, message, line: userLine, updatedAt: new Date().toISOString() })
    setOperationError(`${message}；请确认真实店小秘已登录，再重新运行保存前安全检查。系统不会保存或发布。`)
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
      setL2RunnerState({ status: 'running', runId, exitCode: null, message: '正在运行双目标保存前安全检查', line: runnerEvent.line, updatedAt: new Date().toISOString() })
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
      const modeLabel = request.mode === 'probe' ? '保存前安全检查' : '单商品只保存'
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
    if (!isSupportedSourceProductUrl(request.sourceUrl)) {
      setOperationError('请提供 1688、拼多多或 AliExpress 的精确商品详情 URL。关键词和类目不能单独用于真实认领。')
      setActiveSection('acquisition_claim')
      return
    }
    setBusy(true)
    setOperationError(null)
    setOperationNotice(null)
    try {
      const result = await postJson<AcquisitionClaimResponse>('/api/acquisition/claim-requests', {
        store_id: request.storeId,
        keyword: request.keyword,
        source_url: request.sourceUrl.trim(),
        category_name: request.categoryName,
        claim_mark: request.claimMark,
        template_id: request.templateId ?? null,
      })
      setLastAcquisitionClaimRequest(result)
      if (result.task_id) {
        setSelectedTaskId(result.task_id)
        syncSelectedTaskIdUrl(result.task_id)
      }
      setActiveSection('product_tasks')
      setOperationNotice('商品认领任务已创建。下一步在“当前保存任务”完成安全检查、关闭旧诊断浏览器并填写批准人，然后直接批准并启动认领。')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(humanAcquisitionClaimError(error instanceof Error ? error.message : '创建认领任务失败'))
    } finally {
      setBusy(false)
    }
  }

  async function startSelectedTask(taskId?: number) {
    const taskToStart = typeof taskId === 'number'
      ? workspace.tasks.find((task) => task.id === taskId) ?? null
      : selectedTask
    if (!taskToStart) return
    if (taskToStart.mode === 'batch_draft_save') {
      setSelectedTaskId(taskToStart.id)
      syncSelectedTaskIdUrl(taskToStart.id)
      setOperationError('batch_draft_save 不能使用旧 manual-approval/start；请在“开始批量保存”核对冻结事实并一次原子批准。')
      setActiveSection('start_save')
      return
    }
    setBusy(true)
    setOperationError(null)
    try {
      if (REAL_DXM_MUTATION_MODES.has(taskToStart.mode)) {
        if (UNRELEASED_REAL_DXM_MUTATION_MODES.has(taskToStart.mode)) {
          setOperationError('旧版批量保存入口已关闭。请使用“商品箱批量编辑”的范围冻结、一次批准和严格串行流程。')
          return
        }
        if (!RELEASED_REAL_DXM_MUTATION_MODES.has(taskToStart.mode)) {
          setOperationError(`当前执行模式 ${taskToStart.mode} 未发布，禁止启动真实 DXM 写入。`)
          return
        }
        if (!editBatchStateAvailable) {
          setOperationError('批次占用状态暂时无法确认。为避免并发真实写入，本次任务没有启动；请刷新工作台后重试。')
          return
        }
        const conflictingBatch = editBatches.find((batch) => batch.status === 'running' || batch.status === 'stop_requested')
        if (conflictingBatch) {
          setActiveEditBatchId(conflictingBatch.id)
          setOperationError(`批次 #${conflictingBatch.id} 正在占用全局执行位。一次只允许一个真实写入流程；请先查看该批次。`)
          setActiveSection('task_history')
          return
        }
        const conflictingTask = workspace.tasks.find((task) => (
          task.id !== taskToStart.id
          && task.status === 'running'
          && REAL_DXM_MUTATION_MODES.has(task.mode)
        ))
        if (conflictingTask) {
          setOperationError('已有真实写入任务正在执行。一次只允许一个真实写入流程；请等待当前任务结束后再启动。')
          setActiveSection('product_tasks')
          return
        }
        const latestRuntimeStatus = await getJson<RuntimeStatus>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`)
        setRuntimeStatus(latestRuntimeStatus)
        if (latestRuntimeStatus.agentConsole?.active === true) {
          setOperationError('旧浏览器诊断窗口仍在运行。请先到“浏览器诊断”关闭该窗口，再回来批准并启动真实任务。系统尚未签发本次批准。')
          setActiveSection('start_save')
          return
        }
        const dxmLoginStatus = latestRuntimeStatus.dxmLogin?.status ?? ''
        if (!DXM_READY_SESSION_STATUSES.has(dxmLoginStatus)) {
          setOperationError(`请先完成真实 DXM 登录；当前登录状态：${dxmLoginStatus || '未知'}。`)
          setActiveSection('dxm_access')
          return
        }
        const approvedBy = l3ApprovedBy.trim()
        if (!approvedBy) {
          const approvalCopy = taskToStart.mode === 'claim_only' ? CLAIM_ONLY_CONFIRMATION : '确认本次只保存不发布'
          setOperationError(`请填写批准人标识；${approvalCopy}。`)
          setActiveSection('product_tasks')
          return
        }
        if (taskToStart.mode === 'single_save') {
          const latestConfigPreview = await refreshConfigPreview(taskToStart.id)
          if (!latestConfigPreview || !latestConfigPreview.ok) {
            setOperationError(`配置检查未通过：${latestConfigPreview?.missing.slice(0, 6).join('、') || '请补齐填写编辑页配置'}`)
            setActiveSection('edit_config')
            return
          }
        }
        const approvalConfirmation = taskToStart.mode === 'claim_only' ? CLAIM_ONLY_CONFIRMATION : L3_CONFIRMATION
        const approval = await postJson<ManualApprovalResponse>(`/api/tasks/${taskToStart.id}/manual-approval`, {
          approved_by: approvedBy,
          confirmation: approvalConfirmation,
        })
        await postJson(`/api/tasks/${taskToStart.id}/start`, {
          manual_approval: true,
          approval_token: approval.approvalToken,
          approved_by: approvedBy,
          confirmation: approval.confirmation || approvalConfirmation,
        })
      } else {
        await postJson(`/api/tasks/${taskToStart.id}/start`, {})
      }
      setSelectedTaskId(taskToStart.id)
      syncSelectedTaskIdUrl(taskToStart.id)
      if (taskToStart.mode === 'claim_only') {
        setActiveSection('acquisition_claim')
      } else {
        setActiveSection('product_tasks')
      }
      await refreshWorkspace()
    } catch (error) {
      setOperationError(humanOperationError(error instanceof Error ? error.message : '启动保存核验任务失败'))
    } finally {
      setBusy(false)
    }
  }

  async function controlTask(taskId: number, action: 'pause' | 'resume' | 'stop') {
    setBusy(true)
    setOperationError(null)
    try {
      const result = await postJson<{
        ok?: boolean
        status?: string
        message?: string
        reasonCode?: string
        workerControl?: Task['workerControl']
      }>(`/api/tasks/${taskId}/${action}`, {})
      setSelectedTaskId(taskId)
      syncSelectedTaskIdUrl(taskId)
      const statusLabel = result.status || action
      const message = result.message
        || (action === 'pause'
          ? '暂停已请求，等待 worker 确认'
          : action === 'resume'
            ? '已从暂停点继续'
            : '停止已请求，等待 worker 确认')
      setWorkspaceNotice({
        kind: 'degraded',
        title: `任务 #${taskId} · ${statusLabel}`,
        detail: message,
      })
      await refreshWorkspace()
    } catch (error) {
      setOperationError(humanOperationError(error instanceof Error ? error.message : `任务${action}失败`))
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
    setDxmLoginRequestPending(true)
    setOperationError(null)
    try {
      // Never reuse a previous account's shop snapshot while a new visible
      // login is being opened.  The successful continuation below is the
      // only place that repopulates this account-scoped source of truth.
      setDxmShops([])
      setDxmShopsSnapshot(null)
      setSelectedDxmShopId('')
      setDxmShopsError(null)
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
      // The backend has handed the visible browser to the operator.  Release
      // the global UI lock before the read-only refresh fan-out below; a slow
      // log/workspace refresh must not disable the captcha-complete action.
      setBusy(false)
      setDxmLoginRequestPending(false)
      setOperationNotice(humanDxmLoginFlowNotice(loginStart, '已打开真实店小秘登录页；请在弹出的真实浏览器中完成验证码。'))
      if (!dxmLoginDraft.rememberCredential) {
        setDxmLoginDraft((current) => ({ ...current, password: '' }))
      }
      setActiveSection('dxm_access')
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
      setDxmLoginRequestPending(false)
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

  async function logoutDxm(clearAccount = false) {
    setBusy(true)
    setDxmLoginRequestPending(true)
    setOperationError(null)
    setOperationNotice(null)
    try {
      const result = await postJson<Record<string, unknown>>('/api/dxm/logout', {})
      if (clearAccount) {
        await clearSavedDxmCredential(false)
      }
      setDxmLoginDraft((current) => ({
        ...current,
        username: clearAccount ? '' : current.username,
        password: '',
        rememberCredential: clearAccount ? false : current.rememberCredential,
      }))
      // A logout invalidates every shop-scoped reader/template/plan view. Do
      // not leave the previous account's shop selected while the next login
      // is being established.
      setDxmShops([])
      setDxmShopsSnapshot(null)
      setSelectedDxmShopId('')
      setDxmShopsError(null)
      setOperationNotice(String(result.message ?? (clearAccount ? '已退出并清除当前账号，可以切换新账号。' : '已退出店小秘登录态。')))
      setActiveSection('dxm_access')
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      const message = error instanceof Error ? error.message : '退出店小秘登录态失败'
      setOperationError(humanDxmLoginError(message))
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } finally {
      setBusy(false)
      setDxmLoginRequestPending(false)
    }
  }

  async function continueDxmLogin() {
    setBusy(true)
    setDxmLoginRequestPending(true)
    setOperationError(null)
    try {
      const loginResult = await postJson<Record<string, unknown>>('/api/dxm/login/continue', { confirm: true })
      const stage = String(loginResult.stage ?? '')
      const reasonCode = String(loginResult.reason_code ?? '')
      const readerReady = loginResult.logged_in === true
        && loginResult.reader_ready === true
        && reasonCode === 'LOGIN_READER_READY'
      const message = humanDxmLoginFlowNotice(loginResult, '已检测店小秘登录态。')
      const loginFailed = stage === 'login_failed' || stage.includes('failed') || !readerReady
      if (loginFailed) {
        setOperationError(message)
        setActiveSection('dxm_access')
      } else {
        // Login success is the boundary at which the account's shopMap becomes
        // authoritative. Read it before entering any shop-scoped page; the
        // sidebar selector is the single source of truth afterwards.
        const shops = await refreshDxmShops(true)
        if (!shops) {
          setOperationError('店小秘已登录，但店铺列表暂未读到。不会把它误判成“暂无店铺”；请留在本页点击“重新读取店铺”后再进入采集箱。')
          setActiveSection('dxm_access')
        } else if (!shops.shops.length) {
          setOperationError('店小秘已登录且店铺列表读取成功，但该账号没有返回可用店铺。请在真实店小秘确认店铺授权后再重试。')
          setActiveSection('dxm_access')
        } else {
          setOperationNotice(`${message} 已读取 ${shops.shops.length} 个店铺，正在进入真实采集箱选品；不会保存或发布。`)
          setActiveSection('draft_selection')
        }
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
      setDxmLoginRequestPending(false)
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
      const message = '保存前安全检查未通过，暂不能启动浏览器现场。请先运行保存前安全检查；系统不会保存或发布。'
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
      const message = error instanceof Error ? error.message : '交还自动浏览器失败'
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
          message: '正在运行双目标保存前安全检查',
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
          message: '保存前安全检查启动失败，真实保存仍阻断',
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
    setL2RunnerState({ status: 'running', runId: null, exitCode: null, message: '正在运行双目标保存前安全检查', line: null, updatedAt: new Date().toISOString() })
    setActiveSection('start_save')
    await runRuntimeControl('run_l2_readonly_probe')
  }

  const currentSection = normalizeWorkbenchSection(activeSection)
  const showGlobalSafetyStatus = currentSection !== 'home'
    && currentSection !== 'draft_selection'
    && currentSection !== 'draft_edit_save'
    && currentSection !== 'task_history'
    && currentSection !== 'template_center'
    && currentSection !== 'dxm_templates'
    && currentSection !== 'template_management'
    && currentSection !== 'results'
    && currentSection !== 'issues'
  const startNewEditBatch = () => {
    setActiveEditBatchId(null)
    setActiveScopeSnapshot(null)
    setActiveSection('draft_edit_save')
  }
  const showBatchRecords = (batchId?: number) => {
    setActiveScopeSnapshot(null)
    setActiveEditBatchId(batchId ?? null)
    setActiveSection('task_history')
  }
  const openBatchForApproval = (batchId: number) => {
    setActiveScopeSnapshot(null)
    setActiveEditBatchId(batchId)
    setActiveSection('draft_edit_save')
  }
  const showSelectedTaskResults = () => {
    setActiveEditBatchId(null)
    setActiveSection('results')
  }
  const showSelectedTaskIssues = () => {
    setActiveEditBatchId(null)
    setActiveSection('issues')
  }
  const setWorkbenchSection = useCallback((section: WorkbenchSection) => {
    if (section === 'template_center') setTemplateCenterEntryMode('e2_plan')
    setActiveSection(normalizeWorkbenchSection(section))
  }, [])
  const persistedAcquisitionClaimRequest = useMemo(
    () => taskToAcquisitionClaimResponse(pickLatestAcquisitionClaimTask(workspace.tasks)),
    [workspace.tasks],
  )
  const visibleAcquisitionClaimRequest = persistedAcquisitionClaimRequest ?? lastAcquisitionClaimRequest
  const content = (() => {
    switch (currentSection) {
      case 'edit_config':
      case 'config_basic':
      case 'config_category_title':
      case 'config_price_stock':
      case 'config_images':
      case 'config_logistics':
      case 'config_compliance':
      case 'dxm_templates':
        return (
          <DxmTemplateLibraryPage
            refs={dxmTemplateRefs}
            onChanged={async () => { await refreshWorkspace() }}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowPlans={() => {
              setTemplateCenterEntryMode('e2_plan')
              setActiveSection('template_center')
            }}
          />
        )
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
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            batchScopeStoreName={activeScopeSnapshot?.store_identity.store_name ?? null}
            localPlans={localPlans}
            dxmTemplateRefs={dxmTemplateRefs}
            initialMode={templateCenterEntryMode}
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
            loginRequestPending={dxmLoginRequestPending}
            onDxmLoginDraftChange={setDxmLoginDraft}
            onClearSavedDxmCredential={() => { void clearSavedDxmCredential() }}
            onOpenDxmLogin={openDxmLogin}
            onContinueDxmLogin={continueDxmLogin}
            onLogoutDxm={() => { void logoutDxm(false) }}
            onSwitchDxmAccount={() => { void logoutDxm(true) }}
            onNavigateDxmTarget={navigateDxmTarget}
            onShowConsole={() => setActiveSection('draft_selection')}
          />
        )
      case 'acquisition_claim':
        return (
          <AcquisitionClaimPage
            stores={workspace.stores}
            claimCandidates={workspace.claimCandidates}
            busy={busy}
            lastRequest={visibleAcquisitionClaimRequest}
            onCreateClaimRequest={(request) => { void createAcquisitionClaimRequest(request) }}
            onShowDraftEdit={startNewEditBatch}
            onShowTasks={() => setActiveSection('product_tasks')}
          />
        )
      case 'draft_selection':
        return (
          <DraftSelectionPage
            plans={workspace.templates}
            localPlans={localPlans}
            taskInput={draftTaskInput}
            onTaskInputChange={setDraftTaskInput}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowPlans={() => {
              setTemplateCenterEntryMode('e2_plan')
              setActiveSection('template_center')
            }}
            onReviewSnapshot={() => { setActiveSection('start_save'); return true }}
          />
        )
      case 'product_tasks':
      case 'current_task':
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
            l3ApprovedBy={l3ApprovedBy}
            onL3ApprovedByChange={setL3ApprovedBy}
            onRunL2Probe={runL2ReadonlyProbe}
            onStartTask={(taskId) => startSelectedTask(taskId)}
            onPauseTask={(taskId) => { void controlTask(taskId, 'pause') }}
            onResumeTask={(taskId) => { void controlTask(taskId, 'resume') }}
            onStopTask={(taskId) => { void controlTask(taskId, 'stop') }}
            onShowAcquisition={() => setActiveSection('acquisition_claim')}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onSelectTask={(taskId) => {
              setActiveEditBatchId(null)
              setSelectedTaskId(taskId)
              syncSelectedTaskIdUrl(taskId)
              void refreshConfigPreview(taskId)
            }}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowDraftEdit={startNewEditBatch}
            onShowConsole={() => setActiveSection('start_save')}
            onShowReports={showSelectedTaskResults}
          />
        )
      case 'task_history':
        return (
          <BatchRecordsPage
            initialBatchId={activeEditBatchId}
            onCreateBatch={startNewEditBatch}
            onOpenBatch={openBatchForApproval}
          />
        )
      case 'draft_edit_save':
        return (
          <BatchEditPage
            stores={workspace.stores}
            templates={workspace.templates}
            scopeSnapshot={activeScopeSnapshot}
            initialBatchId={activeEditBatchId}
            activeExecution={runningEditBatch
              ? { kind: 'batch', id: runningEditBatch.id, label: `批次 #${runningEditBatch.id}` }
              : runningMutationTask
                ? { kind: 'task', id: runningMutationTask.id, label: `真实任务 #${runningMutationTask.id}` }
                : null}
            batchStateAvailable={editBatchStateAvailable}
            dxmReady={Boolean(runtimeStatus && DXM_READY_SESSION_STATUSES.has(runtimeStatus.dxmLogin.status))}
            diagnosticBrowserActive={runtimeStatus?.agentConsole?.active === true}
            onScopeSnapshotChange={setActiveScopeSnapshot}
            onBatchSelected={(batchId) => {
              setActiveEditBatchId(batchId)
              if (batchId) {
                setActiveScopeSnapshot(null)
                void refreshWorkspace({ silent: true })
              }
            }}
            onShowTemplates={() => {
              setTemplateCenterEntryMode('batch_bundle')
              setActiveSection('template_center')
            }}
            onShowRecords={(batchId) => {
              showBatchRecords(batchId)
              void refreshWorkspace({ silent: true })
            }}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowConsole={() => setActiveSection('start_save')}
            onShowTasks={() => setActiveSection('product_tasks')}
            onRefreshStatus={() => { void refreshWorkspace(); void refreshRuntimeStatus() }}
          />
        )
      case 'start_save':
        return (
          <BatchSavePlaceholderPage
            taskInput={draftTaskInput}
            controlledTask={selectedTask?.mode === 'batch_draft_save' ? selectedTask : null}
            busy={busy}
            onShowSelection={() => setActiveSection('draft_selection')}
            onShowPlans={() => {
              setTemplateCenterEntryMode('e2_plan')
              setActiveSection('template_center')
            }}
            onTaskSelected={(task) => {
              setSelectedTaskId(task.id)
              syncSelectedTaskIdUrl(task.id)
              void refreshWorkspace({ silent: true })
            }}
            onPauseTask={(taskId) => { void controlTask(taskId, 'pause') }}
            onResumeTask={(taskId) => { void controlTask(taskId, 'resume') }}
            onStopTask={(taskId) => { void controlTask(taskId, 'stop') }}
            onShowTaskMonitor={() => setActiveSection('product_tasks')}
            onShowResults={() => setActiveSection('results')}
          />
        )
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
            onShowDraftEdit={() => setActiveSection('draft_edit_save')}
            onShowConfig={() => setActiveSection('edit_config')}
            onShowEvidence={() => setActiveSection('evidence')}
            onShowReports={showSelectedTaskResults}
          />
        )
      case 'evidence':
        return <EvidenceTimeline workspace={workspace} selectedTask={selectedTask} onShowTasks={() => setActiveSection('product_tasks')} onShowConsole={() => setActiveSection('start_save')} />
      case 'issues':
        return (
          <ExceptionQueue
            workspace={workspace}
            editBatches={editBatches}
            activeBatchId={activeEditBatchId}
            selectedTask={selectedTask}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowDraftEdit={startNewEditBatch}
            onShowBatchRecords={showBatchRecords}
            onOpenBatch={openBatchForApproval}
          />
        )
      case 'results':
        return (
          <>
            <OperationAuditTimeline />
            <ReportCenter workspace={workspace} editBatches={editBatches} activeBatchId={activeEditBatchId} selectedTask={selectedTask} finalCheck={finalCheck} onShowDraftEdit={startNewEditBatch} onShowBatchRecords={showBatchRecords} onOpenBatch={openBatchForApproval} onShowEvidence={() => setActiveSection('evidence')} onShowTasks={() => setActiveSection('product_tasks')} onShowExceptions={showSelectedTaskIssues} />
          </>
        )
      case 'help':
        return (
          <HelpPage
            selectedTask={selectedTask}
            runtimeStatus={runtimeStatus}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onShowAcquisition={() => setActiveSection('acquisition_claim')}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowDraftEdit={startNewEditBatch}
            onShowBatchRecords={() => showBatchRecords()}
            onShowResults={() => setActiveSection('results')}
            onShowIssues={showSelectedTaskIssues}
          />
        )
      case 'settings':
        return <SystemSettings workspace={workspace} selectedTask={selectedTask} finalCheck={finalCheck} runtimeStatus={runtimeStatus} desktopRuntime={desktopRuntime} />
      case 'home':
      default:
        return (
          <Dashboard
            workspace={workspace}
            editBatches={editBatches}
            selectedTask={selectedTask}
            runtimeStatus={runtimeStatus}
            currentShopId={selectedDxmShopId}
            currentShopName={dxmShops.find((shop) => shop.id === selectedDxmShopId)?.name ?? null}
            shopLoading={dxmShopsLoading}
            shopError={dxmShopsError}
            onShowDxmAccess={() => setActiveSection('dxm_access')}
            onRefreshShops={() => { void refreshDxmShops(true) }}
            onShowDraftEdit={startNewEditBatch}
            onShowTasks={() => setActiveSection('product_tasks')}
            onShowConsole={() => setActiveSection('start_save')}
            onShowBatchRecords={showBatchRecords}
            onOpenBatch={openBatchForApproval}
          />
        )
    }
  })()

  return (
    <DxmShopProvider
      value={{
        shops: dxmShops,
        snapshot: dxmShopsSnapshot,
        selectedShopId: selectedDxmShopId,
        loading: dxmShopsLoading,
        error: dxmShopsError,
        setSelectedShopId: setSelectedDxmShopId,
        refresh: refreshDxmShops,
      }}
    >
      <AppShell
        activeSection={currentSection}
        onSectionChange={setWorkbenchSection}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        sourceLabel={sourceLabels[workspace.source]}
      >
      {showGlobalSafetyStatus && (
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
      )}
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
    </DxmShopProvider>
  )
}

function runtimeControlSuccessMessage(action: RuntimeControlAction) {
  return ({
    stop_agent_console: '自动浏览器已停止。',
    reset_workflow_runtime: '真实浏览器执行器已重启，请重新打开执行浏览器后再启动任务。',
    browser_agent_takeover: '已进入人工接管；请在真实浏览器里检查或修正当前页面。',
    browser_agent_resume: '真实浏览器已交还自动浏览器，可继续执行。',
    clear_stuck_tasks: '已提交清理卡住任务请求。',
    mark_real_task_manual_review: '已将真实写入任务转入人工复核。不会取消真实浏览器进程，请查看任务日志确认现场。',
    restart_backend: '已提交后端重启请求，请查看启动器日志。',
    restart_frontend: '已提交前端重启请求，请查看启动器日志。',
    run_l2_readonly_probe: '已启动保存前安全检查，请在“实时浏览器”查看实时日志。',
  } as Record<RuntimeControlAction, string>)[action]
}

function humanOperationError(message: string) {
  const runtimeStatusMessage = humanRuntimeStatusError(message)
  if (runtimeStatusMessage !== message) return runtimeStatusMessage
  if (message.includes('L2 readonly probe resources are missing')) {
    return `保存前安全检查组件未安装完整，请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${checkedPathHint(message)}`
  }
  if (message.includes('L2 readonly probe runner is missing')) {
    return `保存前安全检查组件未安装完整：缺少安全检查启动器。请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${searchedPathHint(message)}`
  }
  if (message.includes('L2 readonly probe script is missing')) {
    return `保存前安全检查组件未安装完整：缺少安全检查脚本。请关闭旧进程并重新打开完整免安装目录版。已阻止真实保存，不会发布。${searchedPathHint(message)}`
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
  return '暂时无法读取完整任务数据。请查看“实时浏览器”的实时日志；系统不会用本地演示结果替代真实保存。'
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

function humanAcquisitionClaimError(message: string) {
  const normalized = message.toLowerCase()
  if (
    normalized.includes('source url')
    || normalized.includes('source product url')
    || normalized.includes('商品详情页')
    || normalized.includes('来源 url')
  ) {
    return '仅支持 1688、拼多多或 AliExpress 的精确商品详情链接；关键词和类目只能辅助定位。系统没有执行认领、保存或发布。'
  }
  if (
    normalized.includes('internal server error')
    || normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
    || normalized.includes('traceback')
  ) {
    return '商品认领任务创建失败：请确认本机工作台服务正常、店铺信息已读取，并重新填写已有待认领商品条件后重试；系统只处理已有待认领商品，不会保存或发布。'
  }
  return message || '商品认领任务创建失败：请重新检查店铺和已有待认领商品条件后重试；系统只处理已有待认领商品，不会保存或发布。'
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
  if (normalized.includes('dxm_account_switch_failed') || normalized.includes('账号会话未能安全清理')) {
    return `当前真实浏览器仍绑定旧店小秘账号，系统没有把它冒充成新账号。请关闭旧的真实浏览器窗口后，再点击“切换账号”或重新打开登录页。${commonTail}`
  }
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
  const commonTail = '浏览器现场只会在保存前安全检查和人工确认通过后接入真实店小秘页面；不会自动发布。'
  const browserRuntimeMessage = humanBrowserRuntimeError(message)
  if (browserRuntimeMessage) return `${browserRuntimeMessage}${commonTail}`
  if (
    message.includes('Internal Server Error')
    || normalized.includes('post /api/agent-console/start failed')
  ) {
    return `真实浏览器现场启动失败：本机后端返回异常。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试；如果仍失败，重开免安装 EXE。${commonTail}`
  }
  if (
    normalized.includes('browser has been closed')
    || message.includes('Target page, context or browser has been closed')
    || normalized.includes('context or browser has been closed')
  ) {
    return `真实浏览器现场已关闭或启动后立即退出。请保留新打开的真实浏览器窗口，或关闭旧进程后回到“浏览器现场”重新打开。${commonTail}`
  }
  if (
    normalized.includes('user data directory is already in use')
    || normalized.includes('profile')
    || normalized.includes('locked')
  ) {
    return `真实浏览器现场数据目录被旧进程占用。请关闭旧的 DXM Agent Console 或旧浏览器进程后重试。${commonTail}`
  }
  if (
    normalized.includes('executable')
    || normalized.includes('playwright')
    || normalized.includes('chromium')
  ) {
    return `真实浏览器现场依赖缺失或不可启动。请重新打开完整免安装目录版，并查看“浏览器现场”的实时日志。${commonTail}`
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
  if (deliveryTask && isDefaultSelectableOperatorTask(deliveryTask)) {
    return deliveryTask.id
  }
  return tasks.find(isActionableClaimTask)?.id
    ?? tasks.find(isActionableSingleSaveTask)?.id
    ?? (deliveryTask && isDefaultSelectableOperatorTask(deliveryTask) ? deliveryTask.id : null)
    ?? tasks.find((task) => task.mode === 'single_save')?.id
    ?? tasks.find(isDefaultSelectableClaimTask)?.id
    ?? tasks.find(isSafeDefaultFallbackTask)?.id
    ?? null
}

function pickTaskIdForOperatorPath(currentTaskId: number | null, deliveryWorkspace: DeliveryWorkspaceResponse | null, tasks: Task[]): number | null {
  const currentTask = currentTaskId ? tasks.find((task) => task.id === currentTaskId) : null
  if (currentTask && isDefaultSelectableOperatorTask(currentTask)) return currentTask.id
  if (currentTask && isActionableSingleSaveTask(currentTask)) return currentTask.id
  return pickDefaultTaskId(deliveryWorkspace, tasks)
}

function isActionableClaimTask(task: Task) {
  return task.mode === 'claim_only' && !['completed', 'cancelled', 'archived'].includes(String(task.status || ''))
}

function isActionableSingleSaveTask(task: Task) {
  return task.mode === 'single_save' && !['completed', 'cancelled', 'archived'].includes(String(task.status || ''))
}

function isDefaultSelectableOperatorTask(task: Task) {
  return (task.mode === 'claim_only' || task.mode === 'single_save') && !['cancelled', 'archived'].includes(String(task.status || ''))
}

function isDefaultSelectableClaimTask(task: Task) {
  return task.mode === 'claim_only' && !['cancelled', 'archived'].includes(String(task.status || ''))
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
    title: '准备执行只保存',
    state: 'READY_FOR_SINGLE_SAVE',
    action: '真实浏览器已打开，等待按任务流程执行',
    next_step: '人工确认后由自动浏览器输入编辑页内容并只点击保存',
    store_name: storeName,
    guard: '只保存，不发布',
    phase: '开始任务',
    progress_index: 1,
    progress_total: 12,
    human_title: '准备执行只保存',
    human_action: '真实浏览器已打开，自动浏览器将按步骤操作店小秘编辑页',
    human_next: '人工确认后开始输入标题、选择分类、设置价格库存并只保存',
    requires_user_action: true,
    severity: 'warning',
  }
}

function pickLatestAcquisitionClaimTask(tasks: Task[]): Task | null {
  return tasks.find((task) => task.mode === 'claim_only' && !['cancelled', 'archived'].includes(String(task.status || ''))) ?? null
}

function taskToAcquisitionClaimResponse(task: Task | null): AcquisitionClaimResponse | null {
  if (!task || task.mode !== 'claim_only') return null
  const payload = task.payload ?? {}
  return {
    id: task.id,
    task_id: task.id,
    stage: String(payload.stage ?? 'pending_acquisition_claim'),
    status: String(payload.status ?? task.status ?? 'pending'),
    store_id: Number(task.store_id ?? payload.store_id ?? 0),
    keyword: typeof payload.keyword === 'string' ? payload.keyword : null,
    source_url: typeof payload.source_url === 'string' ? payload.source_url : null,
    category_name: typeof payload.category_name === 'string' ? payload.category_name : null,
    claim_mark: String(payload.claim_mark ?? 'AI-OPS'),
    template_id: typeof payload.template_id === 'number' ? payload.template_id : null,
    claimed_product_id: typeof payload.claimed_product_id === 'number' ? payload.claimed_product_id : null,
    claimed_product_title: typeof payload.claimed_product_title === 'string' ? payload.claimed_product_title : null,
    claimed_product_status: typeof payload.claimed_product_status === 'string' ? payload.claimed_product_status : null,
    claimed_product_source: typeof payload.claimed_product_source === 'string' ? payload.claimed_product_source : null,
    claimed_product_source_url: typeof payload.claimed_product_source_url === 'string' ? payload.claimed_product_source_url : null,
    claimed_product_category_name: typeof payload.claimed_product_category_name === 'string' ? payload.claimed_product_category_name : null,
    draft_box_verified: typeof payload.draft_box_verified === 'boolean' ? payload.draft_box_verified : null,
    next_step: typeof payload.next_step === 'string' ? payload.next_step : null,
    completed_at: typeof payload.completed_at === 'string' ? payload.completed_at : null,
    task_status: task.status,
  }
}

