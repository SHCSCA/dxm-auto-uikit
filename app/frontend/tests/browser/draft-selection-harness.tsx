import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { AppShell } from '../../src/components/AppShell'
import { BatchSavePlaceholderPage } from '../../src/components/workbench/BatchSavePlaceholderPage'
import { DraftSelectionPage } from '../../src/components/workbench/DraftSelectionPage'
import { getJson } from '../../src/api'
import { DxmShopProvider } from '../../src/dxmShopContext'
import type { ConfirmedDraftTaskInput } from '../../src/draftSelection'
import type { DxmDraftShopsResponse, Template, WorkbenchSection } from '../../src/types'
import '../../src/styles.css'

const plans: Template[] = [{
  id: 9,
  template_type: 'edit_batch_bundle',
  template_name: 'E1 browser plan',
  binding_scope: 'draft',
  payload: {},
  is_enabled: true,
}]

function BrowserHarness() {
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('draft_selection')
  const [taskInput, setTaskInput] = useState<ConfirmedDraftTaskInput | null>(null)
  const [selectionMounted, setSelectionMounted] = useState(true)
  const [shopSnapshot, setShopSnapshot] = useState<DxmDraftShopsResponse | null>(null)
  const [selectedShopId, setSelectedShopId] = useState('')
  const autoAdvance = new URLSearchParams(window.location.search).get('autoAdvance') === '1'
  const refreshShops = useCallback(async (force = false) => {
    if (!force && shopSnapshot) return shopSnapshot
    const next = await getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops')
    setShopSnapshot(next)
    setSelectedShopId((current) => current || next.shops[0]?.id || '')
    return next
  }, [shopSnapshot])

  return (
    <DxmShopProvider value={{
      shops: shopSnapshot?.shops ?? [],
      snapshot: shopSnapshot,
      selectedShopId,
      loading: false,
      error: null,
      setSelectedShopId,
      refresh: refreshShops,
    }}>
      <div className="browser-harness-controls">
        <output data-testid="parent-task-input">{taskInput ? JSON.stringify(taskInput) : 'null'}</output>
        <button data-testid="unmount-selection" type="button" onClick={() => setSelectionMounted(false)}>
          unmount selection
        </button>
        <button data-testid="remount-selection" type="button" onClick={() => setSelectionMounted(true)}>
          remount selection
        </button>
      </div>
      <AppShell
        activeSection={activeSection}
        onSectionChange={setActiveSection}
        sidebarCollapsed={false}
        onToggleSidebar={() => undefined}
        sourceLabel="E1 browser contract"
      >
        {activeSection === 'start_save'
          ? (
            <BatchSavePlaceholderPage
              taskInput={taskInput}
              onShowSelection={() => setActiveSection('draft_selection')}
              onShowPlans={() => setActiveSection('template_center')}
              onTaskSelected={() => undefined}
              onShowTaskMonitor={() => setActiveSection('product_tasks')}
              onShowResults={() => setActiveSection('results')}
            />
            )
          : selectionMounted
            ? (
              <DraftSelectionPage
                plans={plans}
                taskInput={taskInput}
                onTaskInputChange={setTaskInput}
                onShowDxmAccess={() => setActiveSection('dxm_access')}
                onShowPlans={() => setActiveSection('template_center')}
                onReviewSnapshot={() => {
                  if (!autoAdvance) return false
                  setActiveSection('start_save')
                  return true
                }}
              />
              )
            : <div data-testid="selection-unmounted">selection unmounted</div>}
      </AppShell>
    </DxmShopProvider>
  )
}

createRoot(document.getElementById('root')!).render(<BrowserHarness />)
