export type Store = { id: number; name: string; platform: string; status: string }
export type DxmReferenceSectionCode =
  | 'attribute_info'
  | 'description'
  | 'freight'
  | 'service'
  | 'eu_responsible'
  | 'manufacturer'
  | 'compliance'
  | 'semi_managed'
export type DxmReferenceTemplateSection = {
  section: DxmReferenceSectionCode
  label: string
  templateNames: string[]
  required: boolean
  source: 'new' | 'legacy' | 'fallback'
}
export type Template = { id: number; template_type: string; template_name: string; binding_scope: string; payload: Record<string, unknown>; is_enabled: boolean }
export type Product = { id: number; title: string; category_name: string; price: number; currency: string; sku_count: number; image_count: number; status: string; image?: { eu_outer_package_filename?: string } }
export type Task = { id: number; name: string; status: string; mode: string; publish_scene: string; total_jobs: number; completed_jobs: number; failed_jobs: number; payload: { product_ids?: number[]; store_name?: string; category_name?: string; image?: { eu_outer_package_filename?: string }; [key: string]: unknown } }
export type LogItem = { id: number; task_id: number; job_id: number | null; level: string; message: string; context: Record<string, unknown>; created_at: string }
export type Evidence = { id: number; task_id: number; job_id: number | null; evidence_type: string; file_path: string | null; meta: Record<string, unknown>; created_at: string }
export type ExceptionItem = { id: number; task_id: number; job_id: number | null; error_code: string; field_domain: string; title: string; detail: string; suggestion: string; status: string }
export type Report = { id: number | string; task_id?: number; title?: string; status?: string; report_type?: string; summary?: string; file_path?: string | null; file_path_url?: string | null; created_at?: string; [key: string]: unknown }
export type LiveEvent = { type: string; taskId: number; jobId?: number; productId?: number; stepCode?: string; stepName?: string; fieldDomain?: string; screenshotPath?: string; timestamp?: string; status?: string; completedJobs?: number; failedJobs?: number }

export type EvidenceGrade = 'A' | 'B' | 'C'
export type RunStep = {
  state: string
  label: string
  field_domain?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  has_evidence?: boolean
  evidence_count?: number
  has_workflow_result?: boolean
  workflow_actions?: string[]
  evidence_ids?: Array<number | string | null>
}
export type SafetyGuardState = {
  status: string
  safe: boolean
  published: boolean
  publish_allowed: boolean
  report_published_all_false?: boolean
  has_unpublished_proof?: boolean
  reasons?: string[]
}
export type DxmReferenceTemplateResult = {
  ok?: boolean
  section?: DxmReferenceSectionCode | string
  names?: string[]
  selected?: string
  matched_template?: string
  template_name?: string
  reason?: string
  [key: string]: unknown
}
export type TemplateResolutionResult = {
  template_trace?: unknown[]
  dxm_reference_templates_resolved?: Record<string, unknown>
  dxm_reference_template_results?: Record<string, DxmReferenceTemplateResult>
  resolved_defaults?: Record<string, unknown>
}
export type EvidencePoint = {
  kind: string
  id?: number
  job_id?: number | null
  state?: string
  action?: string
  file_path?: string | null
  file_path_url?: string | null
  created_at?: string
  ok?: boolean
  [key: string]: unknown
}
export type ReportSummary = {
  total_reports: number
  success_count: number
  failed_count: number
  published_count: number
  latest_report?: Report | null
  save_results?: unknown[]
  network_save_results?: unknown[]
  har_summaries?: unknown[]
  published_proofs?: unknown[]
  dxm_reference_fields?: Record<string, unknown>
}
export type ExceptionResolutionAction = 'retry' | 'stop' | 'handoff' | 'mark_reviewed'
export type WorkbenchSection =
  | 'dashboard'
  | 'config'
  | 'tasks'
  | 'console'
  | 'evidence'
  | 'exceptions'
  | 'reports'

export type DxmReferenceTemplateMap = Record<DxmReferenceSectionCode, { names: string[]; required: boolean }>

export type AcceptanceGap = {
  id: string
  title: string
  severity: 'blocker' | 'risk' | 'watch'
  owner: string
  detail: string
  evidenceLevel: EvidenceGrade
}

export type DeliveryWorkspace = {
  source: 'api' | 'fallback' | 'mock'
  stores: Store[]
  templates: Template[]
  products: Product[]
  tasks: Task[]
  logs: LogItem[]
  evidences: Evidence[]
  exceptions: ExceptionItem[]
  reports: Report[]
  liveEvents: LiveEvent[]
  deliverySteps: RunStep[]
  evidencePoints: EvidencePoint[]
  reportSummary: ReportSummary | null
  templateResolution: TemplateResolutionResult | null
  publishGuardState: SafetyGuardState | null
  evidenceGrade: { grade: EvidenceGrade; [key: string]: unknown } | null
  dxmReferenceTemplates: DxmReferenceTemplateSection[]
  acceptanceGaps: AcceptanceGap[]
  safety: {
    mode: string
    guarantee: string
    forbiddenActions: string[]
    lastCheckedAt: string
  }
}
