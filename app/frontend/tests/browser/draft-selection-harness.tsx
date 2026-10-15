import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { AppShell } from '../../src/components/AppShell'
import { BatchSavePlaceholderPage } from '../../src/components/workbench/BatchSavePlaceholderPage'
import { DraftSelectionPage } from '../../src/components/workbench/DraftSelectionPage'
import { getJson } from '../../src/api'
import { DxmShopProvider } from '../../src/dxmShopContext'
import type { ConfirmedDraftTaskInput } from '../../src/draftSelection'
import type { DxmDraftShopsResponse, LocalPlanTemplate, WorkbenchSection } from '../../src/types'
import '../../src/styles.css'

const plans: LocalPlanTemplate[] = [{
  model: 'local_plan_template', id: 9, lineage_id: 9, supersedes_id: null,
  name: 'E1 browser plan', version: '1.0.0', shop_id: '101', category_ids: ['100'],
  path: 'B', scope_contract: 'single_target_category.v2', status: 'draft',
  fixed_values: { publish_allowed: false }, fill_rules: { '100': {} }, dxm_template_refs: [], field_mappings: {},
  validation_policy: { required_fields: 'fail_closed', natural_language: 'english_before_save' },
  exception_policy: { unknown: 'stop_batch' }, provenance: 'browser_fixture', is_active: true,
  created_at: '2026-10-15T00:00:00Z', updated_at: '2026-10-15T00:00:00Z',
}]

function BrowserHarness() {
  const [activeSection, setActiveSection] = useState<WorkbenchSection>('draft_selection')
  const [taskInput, setTaskInput] = useState<ConfirmedDraftTaskInput | null>(null)
  const [selectionMounted, setSelectionMounted] = useState(true)
  const [shopSnapshot, setShopSnapshot] = useState<DxmDraftShopsResponse | null>(null)
  const [selectedShopId, setSelectedShopId] = useState('')
  const [shopReadError, setShopReadError] = useState<string | null>(null)
  const autoAdvance = new URLSearchParams(window.location.search).get('autoAdvance') === '1'
  const refreshShops = useCallback(async (force = false) => {
    if (!force && shopSnapshot) return shopSnapshot
    setShopReadError(null)
    try {
      const next = await getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops')
      setShopSnapshot(next)
      setSelectedShopId((current) => current || next.shops[0]?.id || '')
      return next
    } catch (caught) {
      setShopReadError(caught instanceof Error ? caught.message : '店铺读取失败')
      return null
    }
  }, [shopSnapshot])

  return (
    <DxmShopProvider value={{
      shops: shopSnapshot?.shops ?? [],
      snapshot: shopSnapshot,
      selectedShopId,
      loading: false,
      error: shopReadError,
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
                localPlans={plans}
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
