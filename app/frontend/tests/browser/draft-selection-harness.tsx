import { useState } from 'react'
import { createRoot } from 'react-dom/client'

import { AppShell } from '../../src/components/AppShell'
import { BatchSavePlaceholderPage } from '../../src/components/workbench/BatchSavePlaceholderPage'
import { DraftSelectionPage } from '../../src/components/workbench/DraftSelectionPage'
import type { ConfirmedDraftTaskInput } from '../../src/draftSelection'
import type { Template, WorkbenchSection } from '../../src/types'
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

  return (
    <>
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
              />
              )
            : <div data-testid="selection-unmounted">selection unmounted</div>}
      </AppShell>
    </>
  )
}

createRoot(document.getElementById('root')!).render(<BrowserHarness />)
