import { useCallback, useEffect, useMemo, useState } from 'react'
import { getJson, getJsonOrDefault, postJson } from './api'
import { AppShell } from './components/AppShell'
import { SafetyStatusBar } from './components/SafetyStatusBar'
import {
  ConfigCenter,
  Dashboard,
  EvidenceTimeline,
  ExceptionQueue,
  ExecutionConsole,
  ReportCenter,
  TaskCenter,
} from './components/WorkbenchModules'
import type { AgentConsoleSession, DeliveryWorkspace, Evidence, ExceptionItem, LogItem, Product, Report, Store, Task, Template, WorkbenchSection } from './types'
import { composeWorkspace, demoTemplateSeeds, seedRows } from './workspace'

const AGENT_CONSOLE_TARGET_URL = 'https://www.dianxiaomi.com/'

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
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('dashboard')
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [agentConsole, setAgentConsole] = useState<AgentConsoleSession | null>(null)
  const [agentConsoleError, setAgentConsoleError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [workspaceNotice, setWorkspaceNotice] = useState<WorkspaceNotice | null>({
    kind: 'loading',
    title: '正在加载交付工作台',
    detail: '正在读取 /api/delivery/workspace 与关联接口。',
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
        title: '正在加载交付工作台',
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
    setSelectedTaskId((current) => current ?? nextWorkspace.tasks[0]?.id ?? null)
    if (failures.length) {
      const failedPaths = failures.map((failure) => failure.path).join('、')
      setWorkspaceNotice({
        kind: 'degraded',
        title: '交付工作台接口不可用，正在显示只读降级数据',
        detail: `失败接口：${failedPaths}。${failures[0]?.message ?? '请检查后端服务状态。'}`,
      })
    } else {
      setWorkspaceNotice(null)
    }
  }, [selectedTaskId])

  useEffect(() => {
    void refreshWorkspace()
  }, [refreshWorkspace])

  const refreshAgentConsole = useCallback(async () => {
    const status = await getJsonOrDefault<AgentConsoleSession | null>('/api/agent-console/status', null)
    setAgentConsole(status)
  }, [])

  useEffect(() => {
    if (!agentConsole?.active) return
    const timer = window.setInterval(() => {
      void refreshAgentConsole()
    }, 4000)
    return () => window.clearInterval(timer)
  }, [agentConsole?.active, refreshAgentConsole])

  async function bootstrapDemo() {
    const confirmed = window.confirm('这会向本地后端写入演示店铺、模板、商品和保存核验批次；不会访问店小秘，也不会启动真实保存。继续？')
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
        name: '半托管保存核验批次',
        store_id: store.id,
        mode: 'single_save',
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
      await postJson(`/api/tasks/${selectedTask.id}/start`, {})
      setActiveSection('console')
      await refreshWorkspace()
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '启动保存核验任务失败')
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

  const content = (() => {
    switch (activeSection) {
      case 'config':
        return <ConfigCenter workspace={workspace} selectedTask={selectedTask} />
      case 'tasks':
        return (
          <TaskCenter
            workspace={workspace}
            selectedTask={selectedTask}
            busy={busy}
            onSelectTask={setSelectedTaskId}
            onBootstrapDemo={bootstrapDemo}
            onStartTask={startSelectedTask}
            onShowConsole={() => setActiveSection('console')}
            onShowEvidence={() => setActiveSection('evidence')}
          />
        )
      case 'console':
        return (
          <ExecutionConsole
            workspace={workspace}
            selectedTask={selectedTask}
            agentConsole={agentConsole}
            agentConsoleError={agentConsoleError}
            busy={busy}
            onStartAgentConsole={startAgentConsole}
            onStopAgentConsole={stopAgentConsole}
            onSnapshotAgentConsole={snapshotAgentConsole}
            onShowTasks={() => setActiveSection('tasks')}
            onShowEvidence={() => setActiveSection('evidence')}
          />
        )
      case 'evidence':
        return <EvidenceTimeline workspace={workspace} selectedTask={selectedTask} onShowTasks={() => setActiveSection('tasks')} onShowConsole={() => setActiveSection('console')} />
      case 'exceptions':
        return <ExceptionQueue workspace={workspace} selectedTask={selectedTask} />
      case 'reports':
        return <ReportCenter workspace={workspace} selectedTask={selectedTask} onShowEvidence={() => setActiveSection('evidence')} onShowConsole={() => setActiveSection('console')} />
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
      <SafetyStatusBar workspace={workspace} selectedTask={selectedTask} busy={busy} onRefresh={refreshWorkspace} />
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
    action: '打开只读诊断浏览器，不启动保存',
    next_step: '复核 L2/L3 门禁',
    store_name: storeName,
    guard: '诊断观察，不保存不发布',
  }
}
