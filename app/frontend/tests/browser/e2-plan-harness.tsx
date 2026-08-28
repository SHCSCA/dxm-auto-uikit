import { useState } from 'react'
import { createRoot } from 'react-dom/client'

import { BatchSavePlaceholderPage } from '../../src/components/workbench/BatchSavePlaceholderPage'
import { LocalPlanWorkspace } from '../../src/components/workbench/LocalPlanWorkspace'
import type { ConfirmedDraftTaskInput } from '../../src/draftSelection'
import type { DxmTemplateRef, LocalPlanTemplate } from '../../src/types'
import '../../src/styles.css'

const taskInput: ConfirmedDraftTaskInput = {
  sessionRef: '0123456789abcdef',
  input: {
    planId: 9,
    shopId: '3001',
    productIds: ['70001', '70002', '70003'],
    items: [
      { productId: '70001', shopId: '3001', categoryId: '100', title: 'Draft 1' },
      { productId: '70002', shopId: '3001', categoryId: '100', title: 'Draft 2' },
      { productId: '70003', shopId: '3001', categoryId: '100', title: 'Draft 3' },
    ],
  },
}

const activePlan: LocalPlanTemplate = {
  model: 'local_plan_template',
  id: 71,
  lineage_id: 71,
  supersedes_id: null,
  name: '可删除方案',
  version: '1.0.0',
  shop_id: '3001',
  category_ids: ['100'],
  path: 'A',
  fixed_values: { publish_allowed: false },
  fill_rules: { '100': {} },
  dxm_template_refs: [],
  field_mappings: {},
  validation_policy: { required_fields: 'fail_closed', natural_language: 'english_before_save' },
  exception_policy: { unknown: 'stop_batch' },
  provenance: 'browser_fixture',
  is_active: true,
  created_at: '2026-08-20T00:00:00Z',
  updated_at: '2026-08-20T00:00:00Z',
}

function E2PlanHarness() {
  const [refs, setRefs] = useState<DxmTemplateRef[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [destination, setDestination] = useState<'idle' | 'monitor' | 'results'>('idle')

  return (
    <main className="workspace-content">
      <LocalPlanWorkspace
        plans={[activePlan]}
        dxmTemplateRefs={refs}
        onChanged={() => {
          setRefs([{
            model: 'dxm_template_ref',
            id: 31,
            ref_type: 'attribute',
            dxm_template_id: '902',
            shop_id: '3001',
            category_id: '100',
            observed_display_name: '属性模板甲',
            source_api: '/api/smtAttributeTemplate/pageList.json',
            availability: 'available',
            source_digest: 'A'.repeat(64),
            resolved_values_hash: 'B'.repeat(64),
            resolved_field_count: 1,
            synced_at: '2026-07-30T00:00:00Z',
          }])
        }}
      />
      <BatchSavePlaceholderPage
        taskInput={taskInput}
        onShowSelection={() => undefined}
        onShowPlans={() => undefined}
        onTaskSelected={(task) => setSelectedTaskId(task.id)}
        onShowTaskMonitor={() => setDestination('monitor')}
        onShowResults={() => setDestination('results')}
      />
      <output data-testid="selected-task-id">{selectedTaskId ?? 'none'}</output>
      <output data-testid="batch-task-destination">{destination}</output>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<E2PlanHarness />)
