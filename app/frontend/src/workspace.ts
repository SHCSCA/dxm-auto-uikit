import type {
  AcceptanceGap,
  ClaimCandidate,
  DeliveryWorkspace,
  DxmReferenceSectionCode,
  DxmReferenceTemplateMap,
  DxmReferenceTemplateSection,
  Evidence,
  EvidenceGrade,
  EvidencePoint,
  ExceptionItem,
  L2ProbePlan,
  LiveEvent,
  LogItem,
  Product,
  RealModeReleasePlan,
  Report,
  ReportSummary,
  RegressionGate,
  RunStep,
  SafetyGuardState,
  Store,
  Task,
  TemplateResolutionResult,
  Template,
  TwoStageAcceptance,
} from './types'

export type WorkspaceApiBundle = {
  workspace?: DeliveryWorkspaceApi | null
  stores: Store[]
  templates: Template[]
  products: Product[]
  tasks: Task[]
  logs: LogItem[]
  evidences: Evidence[]
  exceptions: ExceptionItem[]
  reports: Report[]
}

type DeliveryWorkspaceApi = Partial<DeliveryWorkspace> & {
  current_task?: Task | null
  steps?: RunStep[]
  evidence_points?: EvidencePoint[]
  report_summary?: ReportSummary
  template_resolution?: TemplateResolutionResult
  publish_guard_state?: SafetyGuardState
  evidence_grade?: { grade: EvidenceGrade; [key: string]: unknown }
  regression_gates?: RegressionGate[]
  l2_probe_plan?: L2ProbePlan
  real_mode_release_plan?: RealModeReleasePlan
  two_stage_acceptance?: unknown
  claim_candidates?: ClaimCandidate[]
}

export const seedRows = [
  {
    title: 'LOCAL DEMO ONLY - DO NOT EXECUTE',
    source_title: '本地演示占位商品（禁止真实执行）',
    category_name: '本地演示类目（禁止真实执行）',
    price: 0,
    sku_count: 1,
    image_count: 0,
    image: { eu_outer_package_filename: 'DEMO_ONLY_DO_NOT_EXECUTE.jpg' },
  },
]

export const referenceSectionLabels: Record<DxmReferenceSectionCode, string> = {
  attribute_info: '属性信息',
  description: '详情描述',
  freight: '运费模板',
  service: '服务模板',
  eu_responsible: '欧盟责任人',
  manufacturer: '制造商',
  compliance: '合规模板',
  semi_managed: '半托管模板',
}

export const referenceSections = Object.keys(referenceSectionLabels) as DxmReferenceSectionCode[]

export const demoDxmReferenceTemplates: DxmReferenceTemplateMap = {
  attribute_info: { names: [], required: true },
  description: { names: [], required: false },
  freight: { names: [], required: true },
  service: { names: [], required: true },
  eu_responsible: { names: [], required: true },
  manufacturer: { names: [], required: true },
  compliance: { names: [], required: false },
  semi_managed: { names: [], required: false },
}

export const demoTemplateSeeds = [
  { template_type: 'title', template_name: '[本地演示·禁止执行] 标题', binding_scope: '仅 dev=1 本地演示', payload: {}, is_enabled: false },
  { template_type: 'category', template_name: '[本地演示·禁止执行] 类目', binding_scope: '仅 dev=1 本地演示', payload: { category: {} }, is_enabled: false },
  { template_type: 'sku', template_name: '[本地演示·禁止执行] SKU', binding_scope: '仅 dev=1 本地演示', payload: { sku: {} }, is_enabled: false },
  { template_type: 'pricing', template_name: '[本地演示·禁止执行] 价格库存', binding_scope: '仅 dev=1 本地演示', payload: { pricing: {} }, is_enabled: false },
  { template_type: 'logistics', template_name: '[本地演示·禁止执行] 包装物流', binding_scope: '仅 dev=1 本地演示', payload: { logistics: {} }, is_enabled: false },
  { template_type: 'image', template_name: '[本地演示·禁止执行] 图片', binding_scope: '仅 dev=1 本地演示', payload: { image: {} }, is_enabled: false },
  { template_type: 'semi_managed', template_name: '[本地演示·禁止执行] 半托管', binding_scope: '仅 dev=1 本地演示', payload: { semi_managed: {} }, is_enabled: false },
  { template_type: 'compliance', template_name: '[本地演示·禁止执行] 合规', binding_scope: '仅 dev=1 本地演示', payload: { compliance: {} }, is_enabled: false },
  { template_type: 'dxm_reference', template_name: '[本地演示·禁止执行] 店小秘引用', binding_scope: '仅 dev=1 本地演示', payload: { dxm_reference_templates: demoDxmReferenceTemplates }, is_enabled: false },
] satisfies Array<Omit<Template, 'id'>>

export function composeWorkspace(bundle: WorkspaceApiBundle): DeliveryWorkspace {
  const fallback = buildEmptyWorkspace()
  const workspace = bundle.workspace ?? null
  const apiHasData = hasAnyApiData(bundle)
  const currentTask = normalizeTask(workspace?.current_task)
  const deliverySteps = chooseList(workspace?.deliverySteps ?? workspace?.steps, [], fallback.deliverySteps, Boolean(workspace), apiHasData)
  const evidencePoints = chooseList(workspace?.evidencePoints ?? workspace?.evidence_points, [], fallback.evidencePoints, Boolean(workspace), apiHasData)
  const reportSummary = workspace?.reportSummary ?? workspace?.report_summary ?? fallback.reportSummary
  const templateResolution = workspace?.templateResolution ?? workspace?.template_resolution ?? fallback.templateResolution
  const publishGuardState = workspace?.publishGuardState ?? workspace?.publish_guard_state ?? fallback.publishGuardState
  const evidenceGradeValue = workspace?.evidenceGrade ?? workspace?.evidence_grade ?? fallback.evidenceGrade
  const regressionGates = firstList(workspace?.regressionGates, workspace?.regression_gates, fallback.regressionGates)
  const l2ProbePlan = normalizeL2ProbePlan(workspace?.l2ProbePlan ?? workspace?.l2_probe_plan, fallback.l2ProbePlan)
  const realModeReleasePlan = normalizeRealModeReleasePlan(workspace?.realModeReleasePlan ?? workspace?.real_mode_release_plan, fallback.realModeReleasePlan)
  const twoStageAcceptance = normalizeTwoStageAcceptance(workspace?.twoStageAcceptance ?? workspace?.two_stage_acceptance, fallback.twoStageAcceptance)
  const claimCandidates = chooseList(workspace?.claimCandidates ?? workspace?.claim_candidates, [], fallback.claimCandidates, Boolean(workspace), apiHasData)
    .map(normalizeClaimCandidate)
  const stores = chooseList(workspace?.stores, bundle.stores, fallback.stores, Boolean(workspace), apiHasData)
  const templates = chooseList(workspace?.templates, bundle.templates, fallback.templates, Boolean(workspace), apiHasData)
  const products = chooseList(workspace?.products, bundle.products, fallback.products, Boolean(workspace), apiHasData)
  const deliveryTasks = Array.isArray(workspace?.tasks) ? workspace.tasks : undefined
  const tasks = mergeCurrentTaskIntoTasks(
    currentTask,
    chooseList(deliveryTasks, currentTask ? [currentTask, ...bundle.tasks] : bundle.tasks, fallback.tasks, Boolean(workspace), apiHasData),
  )
  const logs = chooseList(workspace?.logs, bundle.logs, fallback.logs, Boolean(workspace), apiHasData)
  const evidences = chooseList(workspace?.evidences, bundle.evidences, fallback.evidences, Boolean(workspace), apiHasData)
  const exceptions = chooseList(workspace?.exceptions, bundle.exceptions, fallback.exceptions, Boolean(workspace), apiHasData)
  const reports = chooseList(workspace?.reports, reportSummary?.latest_report ? [reportSummary.latest_report] : bundle.reports, fallback.reports, Boolean(workspace), apiHasData)

  return {
    source: workspace ? 'api' : apiHasData ? 'fallback' : 'mock',
    stores,
    templates,
    products,
    tasks,
    logs,
    evidences,
    exceptions,
    reports,
    liveEvents: chooseList(workspace?.liveEvents, [], fallback.liveEvents, Boolean(workspace), apiHasData),
    deliverySteps,
    evidencePoints,
    reportSummary,
    templateResolution,
    publishGuardState,
    evidenceGrade: evidenceGradeValue,
    regressionGates,
    l2ProbePlan,
    realModeReleasePlan,
    twoStageAcceptance,
    claimCandidates,
    dxmReferenceTemplates: normalizeReferenceSections(workspace?.dxmReferenceTemplates, templates, reports, templateResolution),
    acceptanceGaps: firstList(workspace?.acceptanceGaps, buildAcceptanceGaps(exceptions, evidences, reports, evidenceGradeValue), fallback.acceptanceGaps),
    safety: workspace?.safety ?? safetyFromGuard(publishGuardState, evidenceGradeValue) ?? fallback.safety,
  }
}

export function buildEmptyWorkspace(): DeliveryWorkspace {
  const reportSummary: ReportSummary = {
    total_reports: 0,
    success_count: 0,
    failed_count: 0,
    published_count: 0,
    latest_report: null,
    save_results: [],
    network_save_results: [],
    har_summaries: [],
    published_proofs: [],
    dxm_reference_fields: {},
  }
  return {
    source: 'mock',
    stores: [],
    templates: [],
    products: [],
    tasks: [],
    logs: [],
    evidences: [],
    exceptions: [],
    reports: [],
    liveEvents: [],
    deliverySteps: [],
    evidencePoints: [],
    reportSummary,
    templateResolution: {
      dxm_reference_templates_resolved: {},
      dxm_reference_template_results: {},
      template_trace: [],
      resolved_defaults: {},
    },
    publishGuardState: {
      status: 'empty',
      safe: false,
      published: false,
      publish_allowed: false,
      report_published_all_false: false,
      has_unpublished_proof: false,
      reasons: [],
    },
    evidenceGrade: { grade: 'C' },
    regressionGates: buildRegressionGates(null, { grade: 'C' }, []),
    l2ProbePlan: buildL2ProbePlan(),
    realModeReleasePlan: buildRealModeReleasePlan(),
    twoStageAcceptance: buildEmptyTwoStageAcceptance(),
    claimCandidates: [],
    dxmReferenceTemplates: normalizeReferenceSections(undefined, [], [], null),
    acceptanceGaps: [{
      id: 'empty-workspace',
      title: '尚无真实任务数据',
      severity: 'watch',
      owner: 'workspace',
      detail: '接入后端任务或导入真实商品后，工作台才会展示报告和证据。',
      evidenceLevel: 'C',
    }],
    safety: {
      mode: '商品箱范围 -> 一次批准 -> 严格串行逐件只保存',
      guarantee: '受控逐件商品箱批次已开放；旧版 batch_save、无人值守和发布仍关闭。',
      forbiddenActions: ['发布', '继续发布', '保存并发布', '移入待发布'],
      lastCheckedAt: '等待任务数据',
    },
  }
}

function buildRegressionGates(
  reportSummary: ReportSummary | null,
  grade: { grade: EvidenceGrade; [key: string]: unknown } | null,
  l2Results: Array<Record<string, unknown>>,
): RegressionGate[] {
  const hasSave = Boolean(reportSummary?.save_results?.length)
  const hasProof = Boolean(reportSummary?.published_proofs?.length)
  const hasNetwork = Boolean(reportSummary?.network_save_results?.length || reportSummary?.har_summaries?.length)
  const latestL2 = l2Results[0] ?? null
  const l2Ok = latestL2?.ok === true
  return [
    {
      level: 'L0',
      title: '单测与 fake adapter',
      status: 'ready',
      evidenceLevel: 'B',
      requiresApproval: false,
      command: 'pytest app/backend/tests -q',
      detail: '不访问店小秘，验证配置、发布隔离、runner 和报告聚合。',
    },
    {
      level: 'L1',
      title: '离线 DOM/fixture replay',
      status: 'ready',
      evidenceLevel: 'B',
      requiresApproval: false,
      command: 'selector profile / DOM fixture replay',
      detail: '验证关键选择器和页面片段，不触碰真实页面。',
    },
    {
      level: 'L2',
      title: '保存前安全检查',
      status: l2Ok ? 'mock_passed' : 'not_run',
      evidenceLevel: l2Ok ? 'B' : 'C',
      requiresApproval: true,
      command: 'tools/probes/l2_readonly_probe.py',
      detail: l2Ok ? '仅有离线检查证据；还不能放行真实保存。' : '尚未运行真实店小秘保存前安全检查。',
      latest: latestL2,
    },
    {
      level: 'L3',
      title: '单商品只保存验收',
      status: hasSave && hasProof ? 'passed' : 'approval_required',
      evidenceLevel: hasSave && hasProof && hasNetwork ? 'A' : hasSave && hasProof ? 'B' : (grade?.grade ?? 'C'),
      requiresApproval: true,
      command: 'single_save with manual approval token',
      detail: hasSave && hasProof ? '已有保存结果和未发布证明。' : '真实写操作必须由用户批准，只保存不发布。',
    },
  ]
}

function buildL2ProbePlan(): L2ProbePlan {
  const runIdCommand = '$runId = "l2-real-" + (Get-Date -Format "yyyyMMddTHHmmssZ")'
  const pythonCommand = 'app\\backend\\.venv\\Scripts\\python.exe'
  const scriptPath = 'tools\\probes\\l2_readonly_probe.py'
  const cookieFile = 'data\\sessions\\dianxiaomi_cookies.json'
  const desktopCookieFile = '%APPDATA%\\DXM Agent Console\\data\\sessions\\dianxiaomi_cookies.json'
  const desktopCookieCommand = '$desktopCookieFile = Join-Path $env:APPDATA "DXM Agent Console\\data\\sessions\\dianxiaomi_cookies.json"'
  const cookieFileCommand = `$cookieFile = if (Test-Path $desktopCookieFile) { $desktopCookieFile } else { "${cookieFile}" }`
  const outputDir = 'data\\l2_readonly_probe'
  const allowlistFile = 'config\\l2_readonly_allowlist.json'
  const targets = [
    { id: 'data_acquisition', url: 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', required: true },
    { id: 'draft_box', url: 'https://www.dianxiaomi.com/web/smt/smtProductList/draft', required: true },
  ]
  return {
    schema: 'dxm_l2_readonly_probe_plan.v1',
    requiresApproval: true,
    purpose: '真实店小秘已有待认领列表和商品箱只读检查；不认领、不备注、不保存、不发布。',
    runIdCommand,
    pythonCommand,
    scriptPath,
    cookieFile,
    desktopCookieFile,
    cookieFileCommand,
    outputDir,
    allowlistFile,
    targets,
    commands: [
      runIdCommand,
      desktopCookieCommand,
      cookieFileCommand,
      ...targets.map((target) => `${pythonCommand} ${scriptPath} --target ${target.id} --run-id $runId --cookie-file $cookieFile --output-dir ${outputDir} --allowlist-file ${allowlistFile} --headed`),
    ],
    acceptanceCriteria: [
      '两个目标必须属于同一次人工批准的检查记录。',
      '两个目标必须来自同一检查会话和同一代码版本。',
      '只读网络计数必须全为 0。',
    ],
    safetyNotes: [
      '运行前必须由操作者明确批准真实只读检查。',
      '真实只读检查失败或只有离线证据时，不自动放行真实保存。',
    ],
  }
}

export function buildRealModeReleasePlan(): RealModeReleasePlan {
  const checklist = (
    id: string,
    label: string,
    status: 'passed' | 'missing' = 'missing',
    blocker: string | null = null,
    detail = '',
  ) => ({
    id,
    label,
    required: true,
    status,
    evidence_source: status === 'passed' ? 'current delivery evidence chain' : 'mode-specific evidence',
    blocker,
    detail,
  })
  const sharedControls = [
    '发布入口固定关闭',
    '禁止发布、继续发布、保存并发布、移入待发布',
    '一次人工批准',
    '失败停止并人工接管',
  ]
  return {
    schema: 'dxm_real_mode_release_plan.v1',
    scope: 'controlled_claim_and_single_save',
    publish_allowed: false,
    batch_unattended_publish_allowed: false,
    modes: [
      {
        mode: 'single_save',
        label: '受控单商品只保存已放行',
        status: 'released_controlled',
        allowed: true,
        release_scope: '受控单商品只保存验收',
        required_evidence: [
          '已有待认领列表和商品箱真实只读检查通过',
          '店小秘返回保存成功',
          '未发布状态证明',
          '保存成功回包和页面记录',
        ],
        required_controls: sharedControls,
        blockers: [],
        readiness_checklist: [
          checklist('l2_dual_target', '已有待认领列表和商品箱真实只读检查通过', 'passed'),
          checklist('l3_single_canary', '单商品只保存证据', 'passed'),
          checklist('published_false', '未发布状态证明', 'passed'),
          checklist('publish_guard', '发布隔离无风险信号', 'passed'),
        ],
      },
      {
        mode: 'claim_only',
        label: '受控待认领入箱待后端确认',
        status: 'blocked_stale_l2',
        allowed: false,
        release_scope: 'controlled claim to draft box',
        required_evidence: [
          '已有待认领列表和商品箱真实只读检查通过',
          '待认领商品唯一命中证明',
          '进入商品箱成功证明',
          '不打开编辑页、不触发保存请求证明',
        ],
        required_controls: [
          ...sharedControls,
          '只放进商品箱，不保存、不发布',
          '失败时人工接管',
        ],
        blockers: [
          '等待后端真实 L2 只读检查结果',
        ],
        readiness_checklist: [
          checklist('l2_dual_target', '已有待认领列表和商品箱真实只读检查通过', 'missing', '等待后端真实 L2 只读检查结果'),
          checklist('claim_target_unique', '待认领商品唯一命中证明', 'missing', '等待真实认领任务生成证据'),
          checklist('claim_to_draft', '进入商品箱成功证明', 'missing', '等待真实任务生成证据'),
          checklist('no_editor_or_save', '不打开编辑页、不触发保存请求证明', 'missing', '等待真实认领任务生成证据'),
        ],
      },
      {
        mode: 'edit_batch',
        label: '商品箱受控逐件批次已开放',
        status: 'released_controlled',
        allowed: true,
        release_scope: 'immutable draft-box scope with strict sequential save-only execution',
        required_evidence: [
          '真实商品箱范围与店铺身份冻结',
          '整批模板完整且按精确店铺绑定',
          '逐商品保存结果和未发布证明',
          '不确定结果停止且不自动重试',
        ],
        required_controls: [
          ...sharedControls,
          '全局并发为 1',
          '范围或身份变化立即停止',
        ],
        blockers: [],
        readiness_checklist: [
          checklist('immutable_scope', '商品箱范围与店铺身份已冻结', 'passed'),
          checklist('atomic_approval_start', '一次批准并原子启动', 'passed'),
          checklist('strict_sequential', '逐商品严格串行', 'passed'),
          checklist('unknown_stop_no_retry', '不确定结果停止且不重试', 'passed'),
        ],
      },
      {
        mode: 'batch_save',
        label: '旧版 batch_save 仍关闭',
        status: 'blocked_unreleased',
        allowed: false,
        release_scope: 'not released',
        required_evidence: [
          '独立批量真实检查和保存验收',
          '批量数量上限证明',
          '逐商品保存结果和未发布证明',
          '逐商品保存成功回包和页面记录',
          '部分失败报告与重试边界',
        ],
        required_controls: [
          ...sharedControls,
          '批量大小上限',
          '发现发布风险立即停止',
          '回滚/人工接管',
        ],
        blockers: [
          'cannot reuse single_save evidence',
          '不能复用 single_save 证据',
          '缺少批量大小上限、回滚和部分失败验收',
        ],
        readiness_checklist: [
          checklist('dedicated_l2_l3', '独立批量真实检查和保存验收', 'missing', 'cannot reuse single_save evidence', '批量行为必须单独验证，不能用单品证据替代。'),
          checklist('batch_size_limit', '批量大小上限', 'missing', 'missing batch size cap acceptance', 'UI 和 runner 都必须强制小批量上限。'),
          checklist('per_job_save_and_unpublished', '逐商品保存结果和未发布证明', 'missing', 'missing per-job evidence', '每个商品都需要保存结果、未发布证明和报告链路。'),
          checklist('partial_failure_rollback', '部分失败报告与回滚/人工接管', 'missing', 'missing partial failure rollback proof', '任一失败必须安全停止并给出接管路径。'),
        ],
      },
    ],
  }
}

function normalizeClaimCandidate(value: unknown): ClaimCandidate {
  const item = asRecord(value)
  const title = stringOr(item.title, '待认领商品')
  const sourceUrl = stringOr(item.sourceUrl ?? item.source_url, '')
  const storeAccount = stringOr(item.storeAccount ?? item.store_account, '')
  const createdAt = stringOr(item.createdAt ?? item.created_at, '')
  const categoryHint = stringOr(item.categoryHint ?? item.category_hint, '')
  const textExcerpt = stringOr(item.textExcerpt ?? item.text_excerpt, '')
  const runId = stringOr(item.runId ?? item.run_id, '')
  const capturedAt = stringOr(item.capturedAt ?? item.captured_at, '')
  return {
    id: stringOr(item.id, `${sourceUrl || title}-${createdAt || runId || 'candidate'}`),
    title,
    source: stringOr(item.source, ''),
    sourceUrl,
    source_url: sourceUrl,
    storeAccount,
    store_account: storeAccount,
    createdAt,
    created_at: createdAt,
    categoryHint,
    category_hint: categoryHint,
    textExcerpt,
    text_excerpt: textExcerpt,
    runId,
    run_id: runId,
    capturedAt,
    captured_at: capturedAt,
    readonly: item.readonly !== false,
  }
}

function normalizeL2ProbePlan(value: L2ProbePlan | undefined, fallback: L2ProbePlan): L2ProbePlan {
  const plan = asRecord(value)
  return {
    ...fallback,
    schema: stringOr(plan.schema, fallback.schema),
    requiresApproval: typeof plan.requiresApproval === 'boolean' ? plan.requiresApproval : fallback.requiresApproval,
    purpose: stringOr(plan.purpose, fallback.purpose),
    runIdCommand: stringOr(plan.runIdCommand, fallback.runIdCommand),
    pythonCommand: stringOr(plan.pythonCommand, fallback.pythonCommand),
    scriptPath: stringOr(plan.scriptPath, fallback.scriptPath),
    cookieFile: stringOr(plan.cookieFile, fallback.cookieFile),
    desktopCookieFile: stringOr(plan.desktopCookieFile, fallback.desktopCookieFile ?? ''),
    cookieFileCommand: stringOr(plan.cookieFileCommand, fallback.cookieFileCommand ?? ''),
    outputDir: stringOr(plan.outputDir, fallback.outputDir),
    allowlistFile: stringOr(plan.allowlistFile, fallback.allowlistFile ?? ''),
    targets: Array.isArray(plan.targets) ? plan.targets as L2ProbePlan['targets'] : fallback.targets,
    commands: Array.isArray(plan.commands) ? plan.commands.map(String).filter(Boolean) : fallback.commands,
    acceptanceCriteria: Array.isArray(plan.acceptanceCriteria) ? plan.acceptanceCriteria.map(String).filter(Boolean) : fallback.acceptanceCriteria,
    safetyNotes: Array.isArray(plan.safetyNotes) ? plan.safetyNotes.map(String).filter(Boolean) : fallback.safetyNotes,
  }
}

function normalizeRealModeReleasePlan(value: RealModeReleasePlan | undefined, fallback: RealModeReleasePlan): RealModeReleasePlan {
  const plan = asRecord(value)
  return {
    ...fallback,
    schema: stringOr(plan.schema, fallback.schema),
    scope: stringOr(plan.scope, fallback.scope),
    publish_allowed: typeof plan.publish_allowed === 'boolean' ? plan.publish_allowed : fallback.publish_allowed,
    batch_unattended_publish_allowed: typeof plan.batch_unattended_publish_allowed === 'boolean' ? plan.batch_unattended_publish_allowed : fallback.batch_unattended_publish_allowed,
    modes: Array.isArray(plan.modes)
      ? plan.modes.map((item, index) => normalizeRealModeReleaseItem(item, fallback.modes[index] ?? fallback.modes[0])).filter(Boolean)
      : fallback.modes,
  }
}

function normalizeRealModeReleaseItem(value: unknown, fallback: RealModeReleasePlan['modes'][number]): RealModeReleasePlan['modes'][number] {
  const item = asRecord(value)
  return {
    ...fallback,
    mode: stringOr(item.mode, fallback.mode),
    label: stringOr(item.label, fallback.label),
    status: stringOr(item.status, fallback.status),
    allowed: typeof item.allowed === 'boolean' ? item.allowed : fallback.allowed,
    release_scope: stringOr(item.release_scope, fallback.release_scope),
    required_evidence: Array.isArray(item.required_evidence) ? item.required_evidence.map(String).filter(Boolean) : fallback.required_evidence,
    required_controls: Array.isArray(item.required_controls) ? item.required_controls.map(String).filter(Boolean) : fallback.required_controls,
    blockers: Array.isArray(item.blockers) ? item.blockers.map(String).filter(Boolean) : fallback.blockers,
    readiness_checklist: Array.isArray(item.readiness_checklist)
      ? item.readiness_checklist.map((entry, index) => normalizeReadinessChecklistItem(entry, fallback.readiness_checklist?.[index])).filter(Boolean)
      : fallback.readiness_checklist,
  }
}

function normalizeReadinessChecklistItem(
  value: unknown,
  fallback?: NonNullable<RealModeReleasePlan['modes'][number]['readiness_checklist']>[number],
): NonNullable<RealModeReleasePlan['modes'][number]['readiness_checklist']>[number] {
  const item = asRecord(value)
  const safeFallback = fallback ?? {
    id: '',
    label: '',
    required: true,
    status: 'missing',
    evidence_source: '',
    blocker: null,
    detail: '',
  }
  return {
    id: stringOr(item.id, safeFallback.id),
    label: stringOr(item.label, safeFallback.label),
    required: typeof item.required === 'boolean' ? item.required : safeFallback.required,
    status: stringOr(item.status, safeFallback.status),
    evidence_source: stringOr(item.evidence_source, safeFallback.evidence_source),
    blocker: item.blocker === null ? null : stringOr(item.blocker, safeFallback.blocker ?? ''),
    detail: stringOr(item.detail, safeFallback.detail),
  }
}

function buildEmptyTwoStageAcceptance(): TwoStageAcceptance {
  return {
    schema: 'dxm_two_stage_acceptance.v1',
    passed: false,
    status: 'no_task',
    userMessage: '请选择店小秘已有待认领商品，并确认进入商品箱后，再执行单商品只保存。',
    claimTaskId: null,
    saveTaskId: null,
    claimedProductId: null,
    missingCodes: ['task'],
    checks: {
      claim_task_present: false,
      claim_completed: false,
      claimed_product_present: false,
      claim_product_matches: false,
      draft_box_verified: false,
      single_save_linked_to_claim: false,
      save_success: false,
      unpublished_proof: false,
      publish_guard_safe: false,
    },
  }
}

function normalizeTwoStageAcceptance(value: unknown, fallback: TwoStageAcceptance): TwoStageAcceptance {
  const item = asRecord(value)
  const checks = asRecord(item.checks)
  return {
    ...fallback,
    schema: stringOr(item.schema, fallback.schema),
    passed: typeof item.passed === 'boolean' ? item.passed : fallback.passed,
    status: stringOr(item.status, fallback.status),
    userMessage: stringOr(item.userMessage ?? item.user_message, fallback.userMessage),
    claimTaskId: numberOrNull(item.claimTaskId ?? item.claim_task_id, fallback.claimTaskId),
    saveTaskId: numberOrNull(item.saveTaskId ?? item.save_task_id, fallback.saveTaskId),
    claimedProductId: numberOrNull(item.claimedProductId ?? item.claimed_product_id, fallback.claimedProductId),
    missingCodes: Array.isArray(item.missingCodes)
      ? item.missingCodes.map(String).filter(Boolean)
      : Array.isArray(item.missing_codes)
        ? item.missing_codes.map(String).filter(Boolean)
        : fallback.missingCodes,
    checks: Object.fromEntries(
      Object.entries({ ...fallback.checks, ...checks }).map(([key, raw]) => [key, raw === true]),
    ),
  }
}

export function humanTaskStatus(status: string) {
  return ({
    draft: '待启动',
    running: '运行中',
    completed: '已完成',
    partial_success: '部分成功',
    paused: '已暂停',
    failed: '失败',
    cancelled: '已停止',
    needs_manual_review: '待人工复核',
  } as Record<string, string>)[status] ?? status
}

export function humanLevel(level: string) {
  return ({ success: '成功', warning: '需关注', info: '记录', error: '失败' } as Record<string, string>)[level] ?? level
}

export function evidenceGrade(evidence: Evidence): 'A' | 'B' | 'C' {
  const grade = String(evidence.meta?.grade ?? '').toUpperCase()
  return grade === 'A' || grade === 'B' || grade === 'C' ? grade : evidence.file_path ? 'B' : 'C'
}

export function toArtifactUrl(value?: string | null) {
  if (!value) return ''
  if (value.startsWith('/artifacts/')) return value
  const marker = '/data/'
  const idx = value.indexOf(marker)
  if (idx >= 0) return '/artifacts/' + value.slice(idx + marker.length)
  return value
}

function normalizeReferenceSections(
  sections: DxmReferenceTemplateSection[] | undefined,
  templates: Template[],
  reports: Report[],
  templateResolution?: TemplateResolutionResult | null,
): DxmReferenceTemplateSection[] {
  const fromWorkspace = Array.isArray(sections) && sections.length ? sections : []
  const merged = new Map<DxmReferenceSectionCode, DxmReferenceTemplateSection>()
  for (const section of fromWorkspace) {
    merged.set(section.section, { ...section, templateNames: unique(section.templateNames) })
  }

  for (const [section, config] of Object.entries(resolveReferenceTemplateMap(templates, reports, templateResolution)) as Array<[DxmReferenceSectionCode, { names: string[]; required: boolean }]>) {
    if (!merged.has(section)) {
      merged.set(section, {
        section,
        label: referenceSectionLabels[section],
        templateNames: config.names,
        required: config.required,
        source: config.names.length ? 'new' : 'fallback',
      })
    }
  }

  return referenceSections.map((section) => merged.get(section) ?? {
    section,
    label: referenceSectionLabels[section],
    templateNames: [],
    required: true,
    source: 'fallback',
  })
}

function resolveReferenceTemplateMap(templates: Template[], reports: Report[], templateResolution?: TemplateResolutionResult | null): DxmReferenceTemplateMap {
  const resolved = emptyReferenceMap()
  mergeReferenceMap(resolved, asRecord(templateResolution?.dxm_reference_templates_resolved))
  for (const report of reports) {
    mergeReferenceMap(resolved, asRecord(asRecord(report.summary).dxm_reference_templates_resolved))
  }
  for (const template of templates) {
    mergeReferenceMap(resolved, asRecord(asRecord(template.payload).dxm_reference_templates))
    mergeLegacyReferenceMap(resolved, template)
  }
  return resolved
}

function mergeReferenceMap(target: DxmReferenceTemplateMap, mapping: Record<string, unknown>) {
  for (const section of referenceSections) {
    const raw = asRecord(mapping[section])
    const names = namesFromValue(raw.names ?? raw.templates ?? raw.template_names ?? raw.name ?? mapping[section])
    if (names.length) target[section].names = unique([...target[section].names, ...names])
    if (typeof raw.required === 'boolean') target[section].required = raw.required
  }
}

function mergeLegacyReferenceMap(target: DxmReferenceTemplateMap, template: Template) {
  const payload = asRecord(template.payload)
  const category = asRecord(payload.category)
  const logistics = asRecord(payload.logistics)
  const compliance = asRecord(payload.compliance)
  const semiManaged = asRecord(payload.semi_managed)

  if (template.template_type === 'category') appendNames(target.attribute_info, namesFromValue(category.attribute_template_priorities ?? template.template_name))
  if (template.template_type === 'title') appendNames(target.description, [template.template_name])
  appendNames(target.freight, namesFromValue(logistics.freight_templates ?? logistics.freight_template_priorities))
  appendNames(target.service, namesFromValue(logistics.service_templates ?? logistics.service_template_priorities))
  appendNames(target.eu_responsible, namesFromValue(compliance.eu_responsible_names ?? compliance.eu_responsible_priorities))
  appendNames(target.manufacturer, namesFromValue(compliance.manufacturer_names ?? compliance.manufacturer_priorities))
  if (template.template_type === 'compliance') appendNames(target.compliance, unique([template.template_name, ...namesFromValue(compliance.customs_product_names)]))
  if (template.template_type === 'semi_managed') appendNames(target.semi_managed, unique([template.template_name, ...namesFromValue(semiManaged.template_name)]))
}

function buildAcceptanceGaps(
  exceptions: ExceptionItem[],
  evidences: Evidence[],
  reports: Report[],
  grade?: { grade: EvidenceGrade; [key: string]: unknown } | null,
): AcceptanceGap[] {
  const gaps = exceptions.slice(0, 4).map((item, index) => ({
    id: String(item.id),
    title: item.title || item.error_code,
    severity: index === 0 ? 'blocker' as const : 'risk' as const,
    owner: item.field_domain || 'operations',
    detail: item.detail || item.suggestion,
    evidenceLevel: index === 0 ? 'A' as const : 'B' as const,
  }))

  const hasAGrade = grade?.grade === 'A' || evidences.some((item) => evidenceGrade(item) === 'A')
  const hasReport = reports.length > 0
  return [
    ...gaps,
    ...(!hasAGrade ? [{
      id: 'gap-evidence-a',
      title: '缺少 A 级保存隔离证据',
      severity: 'blocker' as const,
      owner: 'evidence',
      detail: '需要同屏包含任务、账号、商品、保存结果和隔离声明的证据。',
      evidenceLevel: 'A' as const,
    }] : []),
    ...(!hasReport ? [{
      id: 'gap-report',
      title: '缺少可交付验收报告',
      severity: 'risk' as const,
      owner: 'report',
      detail: '结果与问题需要汇总配置命中、执行步骤、证据等级和未完成缺口。',
      evidenceLevel: 'B' as const,
    }] : []),
    {
      id: 'gap-human-review',
      title: '真实验收缺口：人工复核签收未接入',
      severity: 'watch',
      owner: 'ops-review',
      detail: '当前前端能展示缺口，但最终签收人、复核时间和复核结论仍待后端数据化。',
      evidenceLevel: 'C',
    },
  ]
}

function safetyFromGuard(
  guard: SafetyGuardState | null | undefined,
  grade?: { grade: EvidenceGrade; [key: string]: unknown } | null,
): DeliveryWorkspace['safety'] | null {
  if (!guard) return null
  const checked = guard.status === 'safe_unpublished' ? 'published=false 已确认' : guard.status
  return {
    mode: '待认领商品 -> 商品箱 -> 编辑保存只保存',
    guarantee: guard.safe
      ? '只保存不发布：发布隔离已开启，工作台没有发布动作入口。'
      : '只保存不发布：检测到发布风险信号，任务必须停止复核。',
    forbiddenActions: ['发布', '继续发布', '保存并发布', '移入待发布'],
    lastCheckedAt: `${checked}${grade?.grade ? ` / 证据 ${grade.grade}` : ''}`,
  }
}

function normalizeTask(value: Task | null | undefined): Task | null {
  if (!value) return null
  return {
    ...value,
    total_jobs: Number(value.total_jobs ?? 0),
    completed_jobs: Number(value.completed_jobs ?? 0),
    failed_jobs: Number(value.failed_jobs ?? 0),
    payload: value.payload ?? {},
  }
}

function mergeCurrentTaskIntoTasks(currentTask: Task | null, tasks: Task[]): Task[] {
  if (!currentTask) return tasks
  return [currentTask, ...tasks.filter((task) => task.id !== currentTask.id)]
}

function firstList<T>(...lists: Array<T[] | undefined>): T[] {
  return lists.find((list) => Array.isArray(list) && list.length > 0) ?? []
}

function chooseList<T>(
  workspaceList: T[] | undefined,
  apiList: T[],
  fallbackList: T[],
  hasWorkspace: boolean,
  hasApiData: boolean,
): T[] {
  if (hasWorkspace && Array.isArray(workspaceList)) return workspaceList
  if (hasWorkspace) return apiList
  if (hasApiData) return apiList
  return fallbackList
}

function hasAnyApiData(bundle: WorkspaceApiBundle) {
  return [bundle.stores, bundle.templates, bundle.products, bundle.tasks, bundle.logs, bundle.evidences, bundle.exceptions, bundle.reports]
    .some((list) => list.length > 0)
}

function emptyReferenceMap(): DxmReferenceTemplateMap {
  return referenceSections.reduce((acc, section) => {
    acc[section] = { names: [], required: true }
    return acc
  }, {} as DxmReferenceTemplateMap)
}

function appendNames(target: { names: string[] }, names: string[]) {
  if (names.length) target.names = unique([...target.names, ...names])
}

function namesFromValue(value: unknown): string[] {
  if (!value) return []
  if (typeof value === 'string' || typeof value === 'number') return [String(value)]
  if (Array.isArray(value)) return unique(value.flatMap((item) => namesFromValue(item)))
  const record = asRecord(value)
  return namesFromValue(record.names ?? record.templates ?? record.template_names ?? record.templateName ?? record.template_name ?? record.name)
}

function unique(values: string[]) {
  return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean)))
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function stringOr(value: unknown, fallback: string) {
  return typeof value === 'string' && value ? value : fallback
}

function numberOrNull(value: unknown, fallback: number | null) {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
