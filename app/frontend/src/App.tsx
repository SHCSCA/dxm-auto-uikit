import { useCallback, useEffect, useMemo, useState } from 'react'
import { getJsonOrDefault, postJson } from './api'
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
import type { DeliveryWorkspace, Evidence, ExceptionItem, LogItem, Product, Report, Store, Task, Template, WorkbenchSection } from './types'
import { composeWorkspace, demoTemplateSeeds, seedRows } from './workspace'

const sourceLabels: Record<DeliveryWorkspace['source'], string> = {
  api: '/api/delivery/workspace',
  fallback: '现有 API 组合',
  mock: '空工作台 / 演示前',
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

  const selectedTask = useMemo(
    () => workspace.tasks.find((task) => task.id === selectedTaskId) ?? workspace.tasks[0] ?? null,
    [selectedTaskId, workspace.tasks],
  )

  const refreshWorkspace = useCallback(async () => {
    const deliveryPath = selectedTaskId ? `/api/delivery/workspace?task_id=${selectedTaskId}` : '/api/delivery/workspace'
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
    ] = await Promise.all([
      getJsonOrDefault<Partial<DeliveryWorkspace> | null>(deliveryPath, null),
      getJsonOrDefault<Store[]>('/api/stores', []),
      getJsonOrDefault<Template[]>('/api/templates', []),
      getJsonOrDefault<Product[]>('/api/products', []),
      getJsonOrDefault<Task[]>('/api/tasks', []),
      getJsonOrDefault<LogItem[]>('/api/logs', []),
      getJsonOrDefault<Evidence[]>('/api/evidences', []),
      getJsonOrDefault<ExceptionItem[]>('/api/exceptions', []),
      getJsonOrDefault<Report[]>('/api/reports', []),
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
    setSelectedTaskId((current) => current ?? nextWorkspace.tasks[0]?.id ?? null)
  }, [selectedTaskId])

  useEffect(() => {
    void refreshWorkspace()
  }, [refreshWorkspace])

  async function bootstrapDemo() {
    setBusy(true)
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
    } finally {
      setBusy(false)
    }
  }

  async function startSelectedTask() {
    if (!selectedTask) return
    setBusy(true)
    try {
      await postJson(`/api/tasks/${selectedTask.id}/start`, {})
      setActiveSection('console')
      await refreshWorkspace()
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
          />
        )
      case 'console':
        return <ExecutionConsole workspace={workspace} selectedTask={selectedTask} />
      case 'evidence':
        return <EvidenceTimeline workspace={workspace} selectedTask={selectedTask} />
      case 'exceptions':
        return <ExceptionQueue workspace={workspace} selectedTask={selectedTask} />
      case 'reports':
        return <ReportCenter workspace={workspace} selectedTask={selectedTask} />
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
      {content}
    </AppShell>
  )
}
