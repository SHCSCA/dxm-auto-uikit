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
import type { AgentConsoleControlCommand, AgentConsoleControlResponse, AgentConsoleSession, ConfigPreview, DeliveryWorkspace, DesktopRuntimeInfo, DxmCredentialSaveResult, Evidence, ExceptionItem, FinalDeliveryCheckSummary, LogItem, Product, RealTaskCreateRequest, Report, RuntimeControlAction, RuntimeControlResponse, RuntimeLogResponse, RuntimeLogSource, RuntimeStatus, Store, Task, Template, WorkbenchSection } from './types'
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
const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])
const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'batch_save'])
const DXM_READY_SESSION_STATUSES = new Set(['login_success', 'logged_in', 'not_published_verified'])
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
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(initialTaskIdFromUrl)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [agentConsole, setAgentConsole] = useState<AgentConsoleSession | null>(null)
  const [finalCheck, setFinalCheck] = useState<FinalDeliveryCheckSummary | null>(null)
  const [agentConsoleError, setAgentConsoleError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [operationNotice, setOperationNotice] = useState<string | null>(null)
  const [runtimeLogSource, setRuntimeLogSource] = useState<RuntimeLogSource>('launcher')
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
  const [desktopRuntime, setDesktopRuntime] = useState<DesktopRuntimeInfo | null>(null)
  const [configPreview, setConfigPreview] = useState<ConfigPreview | null>(null)
  const [configPreviewLoading, setConfigPreviewLoading] = useState(false)
  const [dxmLoginDraft, setDxmLoginDraft] = useState({ username: '', password: '', rememberCredential: true })
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
    setSelectedTaskId((current) => current ?? pickDefaultTaskId(deliveryWorkspace, nextWorkspace.tasks))
    if (failures.length) {
      const firstFailure = failures[0]
      const taskMissing = Boolean(firstFailure?.path.startsWith('/api/delivery/workspace') && /task not found/i.test(firstFailure.message))
      setWorkspaceNotice({
        kind: 'degraded',
        title: taskMissing ? '当前任务需要重新选择' : '工作台服务连接异常',
        detail: taskMissing
          ? '上次选择的任务已不存在或已归档。请在任务中心重新选择或创建单商品只保存任务；真实保存前仍会重新校验。'
          : `暂时无法读取完整任务数据。请查看执行控制台日志；系统不会用本地演示结果替代真实保存。${firstFailure?.message ?? ''}`,
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
    const timer = window.setInterval(() => {
      void refreshAgentConsole(Boolean(agentConsole?.browser_visible))
    }, 3500)
    return () => window.clearInterval(timer)
  }, [agentConsole?.active, agentConsole?.browser_visible, refreshAgentConsole])

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
    const status = await getJsonOrDefault<RuntimeStatus | null>(`/api/runtime/status?frontend_url=${encodeURIComponent(window.location.origin)}`, null)
    setRuntimeStatus(status)
  }, [])

  useEffect(() => {
    const launcherItems = runtimeLogs.launcher?.items ?? []
    const completion = [...launcherItems]
      .reverse()
      .find((item) => item.line.includes('[l2-readonly-runner] finished') && item.line.includes('exit_code=0'))
    if (!completion) return

    const completionKey = completion.line.match(/run_id=([^\s]+)/)?.[1] ?? completion.line
    if (lastObservedL2CompletionRef.current === completionKey) return
    lastObservedL2CompletionRef.current = completionKey
    void refreshWorkspace()
    void refreshRuntimeStatus()
  }, [refreshRuntimeStatus, refreshWorkspace, runtimeLogs.launcher])

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
            message: `已从本机加密存储载入账号${result.credential.updatedAt ? `，保存时间 ${new Date(result.credential.updatedAt).toLocaleString()}` : ''}。`,
          })
          return
        }
        setDxmCredentialState({
          available: result.available,
          loaded: false,
          saved: false,
          message: result.available ? '可记住账号密码；密码会写入本机加密存储。' : '本机加密存储不可用；不会保存密码。',
        })
      } catch (error) {
        if (cancelled) return
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
        setActiveSection('tasks')
        return
      }
      if (!products.length) {
        setOperationError('请至少选择一个真实商品。')
        setActiveSection('tasks')
        return
      }
      if (request.mode === 'single_save' && products.length !== 1) {
        setOperationError(`单商品只保存一次只能选择 1 个商品；当前已选 ${products.length} 个。请取消多余商品后再创建。`)
        setActiveSection('tasks')
        return
      }
      const firstProduct = products[0]
      const modeLabel = request.mode === 'probe' ? '只读页面检查' : '单商品只保存'
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
          setOperationError('当前仅开放单商品只保存；认领和批量保存必须重新验收后再放行。')
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
          setActiveSection('guide')
          return
        }
        const latestConfigPreview = await refreshConfigPreview(selectedTask.id)
        if (!latestConfigPreview || !latestConfigPreview.ok) {
          setOperationError(`配置预检未通过：${latestConfigPreview?.missing.slice(0, 6).join('、') || '请补齐 DXM 编辑页配置'}`)
          setActiveSection('config')
          return
        }
        const approvedBy = l3ApprovedBy.trim()
        if (!approvedBy) {
          setOperationError('请填写批准人标识；将只启动单商品只保存任务，不会发布。')
          setActiveSection('guide')
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
    const username = dxmLoginDraft.username.trim()
    if (!username) {
      setOperationError('请先在页面内填写店小秘账号，再打开真实店小秘登录页。')
      setActiveSection('guide')
      return
    }
    if (!dxmLoginDraft.password) {
      setOperationError('请先在页面内填写店小秘密码；密码只用于本次真实登录请求，不写入配置中心。')
      setActiveSection('guide')
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
      await postJson('/api/dxm/login/start', {
        username,
        password: dxmLoginDraft.password,
      })
      if (!dxmLoginDraft.rememberCredential) {
        setDxmLoginDraft((current) => ({ ...current, password: '' }))
      }
      setActiveSection('console')
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '打开真实店小秘登录页失败')
      await refreshRuntimeStatus()
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
        message: `账号密码已保存到本机加密存储${result.updatedAt ? `，保存时间 ${new Date(result.updatedAt).toLocaleString()}` : ''}。`,
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
      await postJson('/api/dxm/login/continue', { confirm: true })
      setActiveSection('console')
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '继续检测店小秘登录态失败')
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
          const message = status.error || status.reason || `执行浏览器进入${targetLabel}失败`
          setAgentConsoleError(message)
          setOperationError(message)
          return
        }
        await waitForAgentConsoleNavigationSettle()
        const settledStatus = await refreshAgentConsole(true) ?? status
        setAgentConsoleError(null)
        if (currentUrlMatchesDxmTarget(settledStatus.current_url, target)) {
          setOperationNotice(`执行浏览器已进入${targetLabel}`)
        } else {
          setOperationError(`执行浏览器已发送进入${targetLabel}指令，但店小秘当前停留在 ${compactDxmUrl(settledStatus.current_url)}。请确认登录态后重试。`)
        }
      } else {
        await postJson('/api/dxm/navigate', { target })
        setOperationNotice(`已请求店小秘登录流进入${targetLabel}`)
      }
      setActiveSection('console')
      await refreshAgentConsole(true)
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '进入店小秘业务页失败')
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
      setActiveSection('console')
      return
    }
    const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
    if (l2Gate?.status !== 'passed') {
      const message = `只读复验未通过，真实浏览器自动化不可启动：${l2Gate?.detail ?? '真实只读检查未通过'}`
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

  async function controlAgentConsoleBrowser(command: AgentConsoleControlCommand) {
    setBusy(true)
    setAgentConsoleError(null)
    try {
      const status = await postJson<AgentConsoleControlResponse>('/api/agent-console/control', command)
      setAgentConsole(status)
      if (status.ok === false) {
        const message = status.error || status.reason || '页面内浏览器控制失败'
        setAgentConsoleError(message)
        setOperationError(message)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '页面内浏览器控制失败'
      setAgentConsoleError(message)
      setOperationError(message)
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
      if (result.agentConsole) setAgentConsole(result.agentConsole)
      setOperationNotice(result.message ?? runtimeControlSuccessMessage(action))
      await refreshWorkspace()
      await refreshRuntimeStatus()
      await refreshRuntimeLogs()
    } catch (error) {
      const message = error instanceof Error ? error.message : '运行时维护动作失败'
      setOperationError(message)
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
    setActiveSection('console')
    await runRuntimeControl('run_l2_readonly_probe')
  }

  const content = (() => {
    switch (activeSection) {
      case 'config':
        return <ConfigCenter workspace={workspace} selectedTask={selectedTask} configPreview={configPreview} configPreviewLoading={configPreviewLoading} onConfigSaved={async () => { await refreshWorkspace(); await refreshConfigPreview() }} onRefreshConfigPreview={async () => { await refreshConfigPreview(); await refreshWorkspace() }} />
      case 'guide':
        return (
          <GuideCenter
            workspace={workspace}
            selectedTask={selectedTask}
            configPreview={configPreview}
            runtimeStatus={runtimeStatus}
            dxmLoginDraft={dxmLoginDraft}
            dxmCredentialState={dxmCredentialState}
            l3ApprovedBy={l3ApprovedBy}
            busy={busy}
            onDxmLoginDraftChange={setDxmLoginDraft}
            onClearSavedDxmCredential={() => { void clearSavedDxmCredential() }}
            onL3ApprovedByChange={setL3ApprovedBy}
            onRunL2Probe={runL2ReadonlyProbe}
            onOpenDxmLogin={openDxmLogin}
            onContinueDxmLogin={continueDxmLogin}
            onNavigateDxmTarget={navigateDxmTarget}
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
            l3ApprovedBy={l3ApprovedBy}
            onL3ApprovedByChange={setL3ApprovedBy}
            onRunL2Probe={runL2ReadonlyProbe}
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
            runtimeStatus={runtimeStatus}
            runtimeLogs={runtimeLogs}
            runtimeLogSource={runtimeLogSource}
            runtimeLogError={runtimeLogError}
            runtimeLogLevel={runtimeLogLevel}
            runtimeLogQuery={runtimeLogQuery}
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
        desktopRuntime={desktopRuntime}
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
          <strong>操作需要重试</strong>
          <span>{operationError}</span>
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
      {content}
    </AppShell>
  )
}

function runtimeControlSuccessMessage(action: RuntimeControlAction) {
  return ({
    stop_agent_console: '浏览器 Agent 已停止。',
    clear_stuck_tasks: '已提交清理卡住任务请求。',
    restart_backend: '已提交后端重启请求，请查看启动器日志。',
    restart_frontend: '已提交前端重启请求，请查看启动器日志。',
    run_l2_readonly_probe: '已启动只读复验，请在执行控制台查看启动器日志。',
  } as Record<RuntimeControlAction, string>)[action]
}

function pickDefaultTaskId(deliveryWorkspace: DeliveryWorkspaceResponse | null, tasks: Task[]) {
  const deliveryTaskId = deliveryWorkspace?.current_task?.id
  if (typeof deliveryTaskId === 'number' && tasks.some((task) => task.id === deliveryTaskId)) {
    return deliveryTaskId
  }
  return tasks.find((task) => task.mode === 'single_save')?.id ?? tasks[0]?.id ?? null
}

function buildAgentConsoleHudStep(workspace: DeliveryWorkspace, selectedTask: Task): AgentConsoleSession['hud'] {
  const storeName = String(selectedTask.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺')
  return {
    title: '只读复验待命',
    state: 'READONLY_DIAGNOSTIC',
    action: '打开真实店小秘浏览器，不启动保存',
    next_step: '复核只读证据和人工确认',
    store_name: storeName,
    guard: '复验观察，不保存不发布',
  }
}
