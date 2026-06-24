export type Store = { id: number; name: string; platform: string; status: string }
export type DesktopRuntimeInfo = {
  repoRoot?: string | null
  backendPort?: number | null
  backendInstanceId?: string | null
  apiBase?: string | null
  frontendPath?: string | null
  backendLogPath?: string | null
  desktopLogPath?: string | null
  lastError?: string | null
}
export type DxmStoredCredential = {
  username: string
  password: string
  updatedAt?: string | null
}
export type DxmCredentialLoadResult = {
  ok: boolean
  available: boolean
  credential?: DxmStoredCredential | null
  error?: string | null
}
export type DxmCredentialSaveResult = {
  ok: boolean
  available: boolean
  updatedAt?: string | null
  error?: string | null
}

declare global {
  interface Window {
    dxmDesktop?: {
      getRuntimeInfo: () => Promise<DesktopRuntimeInfo>
      loadDxmCredential?: () => Promise<DxmCredentialLoadResult>
      saveDxmCredential?: (credential: { username: string; password: string }) => Promise<DxmCredentialSaveResult>
      clearDxmCredential?: () => Promise<DxmCredentialSaveResult>
    }
  }
}

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
export type TemplateCenterField = {
  key: string
  label: string
  required: boolean
  value_kind?: 'text' | 'number' | 'list' | string
}
export type TemplateCenterSection = {
  id: string
  label: string
  template_type: string
  fields: TemplateCenterField[]
}
export type TemplateCenterMetadata = {
  sections: TemplateCenterSection[]
  source_priority: string[]
  actions: string[]
}
export type Product = { id: number; title: string; category_name: string; price: number; currency: string; sku_count: number; image_count: number; status: string; image?: { eu_outer_package_filename?: string } }
export type TaskJob = { id: number; task_id?: number; product_id?: number | null; status: string; current_step_code?: string | null; current_step_name?: string | null; error_code?: string | null; error_message?: string | null; [key: string]: unknown }
export type Task = { id: number; name: string; status: string; mode: string; publish_scene: string; store_id?: number | null; total_jobs: number; completed_jobs: number; failed_jobs: number; payload: { product_ids?: number[]; store_name?: string; category_name?: string; image?: { eu_outer_package_filename?: string }; [key: string]: unknown }; jobs?: TaskJob[] }
export type RealTaskCreateRequest = { storeId: number; mode: 'probe' | 'single_save'; productIds: number[] }
export type AcquisitionClaimCreateRequest = { storeId: number; keyword?: string; categoryName?: string; claimMark: string; templateId?: number | null }
export type AcquisitionClaimResponse = {
  id: number
  task_id: number
  stage: string
  status: string
  store_id: number
  keyword?: string | null
  category_name?: string | null
  claim_mark: string
  template_id?: number | null
  claimed_product_id?: number | null
  claimed_product_title?: string | null
  claimed_product_status?: string | null
  next_step?: string | null
  completed_at?: string | null
  task_status?: string | null
}
export type LogItem = { id: number; task_id: number; job_id: number | null; level: string; message: string; context: Record<string, unknown>; created_at: string }
export type RuntimeLogSource = 'backend' | 'frontend' | 'launcher' | 'npm' | 'task' | 'agent'
export type RuntimeLogItem = { line: string; level: 'info' | 'warning' | 'error' | string; tags: string[] }
export type RuntimeLogResponse = { source: string; path: string; exists: boolean; cursor: number; nextCursor: number; lines: string[]; items?: RuntimeLogItem[]; truncated?: boolean; modifiedAt?: string | null; ageSeconds?: number | null; stale?: boolean; fetchedAt?: string; error?: string }
export type RuntimeStatus = {
  backend: { status: string; url?: string; port?: number | null; instanceId?: string | null; detail?: string }
  frontend: { status: string; url?: string; port?: number | null; detail?: string }
  agentConsole: { status: string; active: boolean; browserVisible: boolean; browserLaunching?: boolean; currentUrl?: string | null; profileDir?: string | null; lastError?: string | null }
  dxmLogin: { status: string; currentUrl?: string | null; lastError?: string | null }
  l2ReadonlyProbe?: {
    running: boolean
    stale?: boolean
    runId?: string | null
    taskId?: number | null
    pid?: number | null
    createdAt?: string | null
    lockFile?: string | null
  }
  dependencies: Record<string, { status: string; path?: string | null; checkedPaths?: string[]; label?: string; requiredFor?: string; userMessage?: string; repairAction?: string; repairSteps?: string[] }>
  runtimeControl?: {
    owner?: 'start_mvp' | 'desktop' | 'direct' | string
    managedByLauncher: boolean
    managedByDesktop?: boolean
    restartAvailable: boolean
    commandFile?: string | null
    detail?: string | null
  }
  paths?: {
    data_dir?: string
    dataDir?: string
    l2_readonly_probe_dir?: string
    l2ReadonlyProbeDir?: string
    resource_root?: string
    resourceRoot?: string
  }
}
export type RuntimeControlAction = 'stop_agent_console' | 'clear_stuck_tasks' | 'mark_real_task_manual_review' | 'restart_backend' | 'restart_frontend' | 'run_l2_readonly_probe'
export type RuntimeControlResponse = {
  ok: boolean
  action: RuntimeControlAction | string
  message?: string
  clearedTaskIds?: number[]
  clearedTasks?: Array<Record<string, unknown>>
  skippedTasks?: Array<Record<string, unknown>>
  markedTasks?: Array<Record<string, unknown>>
  runId?: string
  logPath?: string
  targets?: string[]
  agentConsole?: AgentConsoleSession
}
export type ConfigPreviewField = {
  path: string
  name: string
  label: string
  value: unknown
  source: string
  required: boolean
  missing: boolean
}
export type ConfigPreviewGroup = {
  section: string
  label: string
  templateType: string
  required: boolean
  templatePresent: boolean
  complete: boolean
  missing: string[]
  fields: ConfigPreviewField[]
}
export type ConfigPreview = {
  ok: boolean
  mode: string | null
  taskId: number | null
  productId: number | null
  missing: string[]
  warnings: string[]
  fieldGroups: ConfigPreviewGroup[]
  templateTrace: Array<Record<string, unknown>>
  resolvedDefaults: Record<string, unknown>
}
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
  task_id?: number
  taskId?: number
  evidence_id?: number
  evidenceId?: number
  report_id?: number | string
  reportId?: number | string
  job_id?: number | null
  jobId?: number | null
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
export type AgentConsoleHud = {
  title?: string
  label?: string
  state?: string
  code?: string
  action?: string
  detail?: string
  line1?: string
  line2?: string
  next_step?: string
  phase?: string
  progress_index?: number
  progress_total?: number
  severity?: 'info' | 'success' | 'warning' | 'error' | string
  human_title?: string
  human_action?: string
  human_next?: string
  recent_actions?: string[]
  requires_user_action?: boolean
  maintenance_detail?: string
  store_name?: string
  guard?: string
  updated_at?: string
}
export type AgentConsoleNetworkEvent = {
  type?: string
  method?: string
  url?: string
  status?: number
  timestamp?: string
}
export type AgentConsoleActionEvent = {
  type: 'workflow_action' | 'click' | 'fill' | 'select' | 'upload' | 'wait' | 'save' | string
  action?: string
  label?: string
  state?: string
  step_code?: string
  task_id?: number
  job_id?: number
  product_id?: number
  field_domain?: string
  status?: 'ok' | 'failed' | string
  target?: string
  value?: string
  page_url?: string
  screenshot_url?: string
  save_result?: Record<string, unknown>
  timestamp?: string
}
export type AgentConsoleControlAction = 'scroll' | 'goto'
export type AgentConsoleControlCommand = {
  action: AgentConsoleControlAction
  x?: number
  y?: number
  selector?: string
  text?: string
  key?: string
  url?: string
  delta_x?: number
  delta_y?: number
}
export type AgentConsoleSession = {
  active: boolean
  session_id: string | null
  task_id: number | null
  job_id?: number | null
  product_id?: number | null
  profile_dir: string | null
  launch_browser: boolean
  browser_launching?: boolean
  browser_visible: boolean
  target_url: string | null
  current_url: string | null
  page_title: string | null
  hud: AgentConsoleHud
  field_domain?: string | null
  mode?: string | null
  last_step_code?: string | null
  last_step_name?: string | null
  step_history?: Array<Record<string, unknown>>
  action_events?: AgentConsoleActionEvent[]
  network_events?: AgentConsoleNetworkEvent[]
  manual_takeover?: boolean
  manual_takeover_started_at?: string | null
  screenshot: string | null
  screenshot_url?: string | null
  last_frame_at?: string | null
  created_at: string | null
  updated_at: string | null
  last_error: string | null
}
export type AgentConsoleHudStep = AgentConsoleHud
export type AgentConsoleStatus = AgentConsoleSession
export type AgentConsoleControlResponse = AgentConsoleSession & {
  ok?: boolean
  reason?: string
  control_result?: Record<string, unknown>
  error?: string
}
export type FinalDeliveryCheckSummary = {
  status: 'available' | 'not_run' | 'unreadable' | string
  checked_at?: string | null
  local_workbench_check?: string | null
  real_dxm_write_readiness?: string | null
  current_real_dxm_write_readiness?: string | null
  current_real_dxm_write_blocked_reason?: string | null
  current_l2_gate_status?: string | null
  current_l3_gate_status?: string | null
  final_check_runtime_gate_matches_report?: boolean | null
  final_check_runtime_gate_freshness?: string | null
  effective_real_dxm_write_readiness?: string | null
  effective_real_dxm_write_blocked_reason?: string | null
  effective_real_dxm_mutation_allowed?: boolean | null
  effective_real_dxm_mutation_scope?: string | null
  effective_real_dxm_write_readiness_matches_expected?: boolean | null
  production_real_write_ready?: boolean | null
  real_dxm_write_blocked_reason?: string | null
  l3_evidence_readiness?: Record<string, unknown> | null
  ok_scope?: string | null
  real_dxm_mutation_allowed?: boolean | null
  real_dxm_mutation_scope?: string | null
  controlled_single_save_ready?: boolean | null
  batch_unattended_publish_allowed?: boolean | null
  expected_real_dxm_write_readiness?: string | null
  real_dxm_write_readiness_matches_expected?: boolean | null
  source_package_readiness?: string | null
  source_package_check?: string | null
  require_clean_worktree?: boolean | null
  git_head?: string | null
  current_git_head?: string | null
  current_git_status_short?: string | null
  current_git_is_dirty?: boolean | null
  final_check_matches_current_worktree?: boolean | null
  final_check_freshness?: string | null
  browser_qa_ok?: boolean | null
  browser_qa_checked_at?: string | null
  browser_qa_git_head?: string | null
  browser_qa_git_status_short?: string | null
  browser_qa_matches_report_git_head?: boolean | null
  browser_qa_screenshot_hashes?: Record<string, string> | null
  post_final_report_qa_ok?: boolean | null
  post_final_report_qa_checked_at?: string | null
  post_final_report_qa_screenshot_hashes?: Record<string, string> | null
  l2_allowlist_review_template_state?: string | null
  l2_allowlist_review_template_candidate_count?: number | null
  l2_allowlist_review_template_markdown_path?: string | null
  l2_allowlist_review_template_json_path?: string | null
  l2_allowlist_review_template_markdown_sha256?: string | null
  l2_allowlist_review_template_json_sha256?: string | null
  qa_services?: Record<string, unknown> | null
  gates?: Record<string, unknown> | null
  summary_path?: string | null
  final_report_center_screenshot_path?: string | null
  post_final_report_qa_json_path?: string | null
  json_path?: string | null
  error?: string | null
}
export type WorkbenchSection =
  | 'home'
  | 'dxm_access'
  | 'acquisition_claim'
  | 'draft_edit_save'
  | 'template_center'
  | 'start_save'
  | 'results'
  | 'issues'
  | 'help'
  | 'settings'
  | 'product_tasks'
  | 'current_task'
  | 'task_history'
  | 'edit_config'
  | 'config_basic'
  | 'config_category_title'
  | 'config_price_stock'
  | 'config_images'
  | 'config_logistics'
  | 'config_compliance'
  | 'template_management'
  | 'preflight'
  | 'real_browser'
  | 'manual_takeover'
  | 'evidence'

export type LegacyWorkbenchSection =
  | 'agent_execution'
  | 'browser'
  | 'dashboard'
  | 'guide'
  | 'config'
  | 'tasks'
  | 'console'
  | 'start_save'
  | 'real_browser'
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

export type RegressionGate = {
  level: 'L0' | 'L1' | 'L2' | 'L3' | string
  title: string
  status: 'ready' | 'not_run' | 'mock_passed' | 'partial' | 'passed' | 'failed' | 'blocked' | 'approval_required' | string
  evidenceLevel: EvidenceGrade
  requiresApproval: boolean
  command?: string
  detail: string
  latest?: Record<string, unknown> | null
}

export type L2ProbePlan = {
  schema: string
  requiresApproval: boolean
  purpose: string
  runIdCommand: string
  pythonCommand: string
  scriptPath: string
  cookieFile: string
  outputDir: string
  allowlistFile?: string
  targets: Array<{ id: string; url: string; required: boolean }>
  commands: string[]
  acceptanceCriteria: string[]
  safetyNotes: string[]
}
export type RealModeReleaseItem = {
  mode: 'single_save' | 'claim_only' | 'batch_save' | string
  label: string
  status: 'released_controlled' | 'blocked_unreleased' | string
  allowed: boolean
  release_scope: string
  required_evidence: string[]
  required_controls: string[]
  blockers: string[]
  readiness_checklist?: Array<{
    id: string
    label: string
    required: boolean
    status: 'passed' | 'missing' | 'blocked' | string
    evidence_source: string
    blocker?: string | null
    detail: string
  }>
}
export type RealModeReleasePlan = {
  schema: string
  scope: string
  publish_allowed: boolean
  batch_unattended_publish_allowed: boolean
  modes: RealModeReleaseItem[]
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
  regressionGates: RegressionGate[]
  l2ProbePlan: L2ProbePlan
  realModeReleasePlan: RealModeReleasePlan
  dxmReferenceTemplates: DxmReferenceTemplateSection[]
  acceptanceGaps: AcceptanceGap[]
  safety: {
    mode: string
    guarantee: string
    forbiddenActions: string[]
    lastCheckedAt: string
    evidenceGrade?: EvidenceGrade
    blockedByL2?: boolean
    l2Status?: string | null
  }
}
