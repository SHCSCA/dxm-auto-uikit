import type {
  AcceptanceGap,
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
}

export const seedRows = [
  {
    title: 'Wind Breaker Anime Acrylic Stand Hot Spring Battle Charm',
    source_title: '防风铃x空座温泉云蒸决战阵防风少年',
    category_name: '立牌类谷子',
    price: 7.01,
    sku_count: 8,
    image_count: 8,
    image: { eu_outer_package_filename: '微信图片_202504092228421.jpg' },
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
  attribute_info: { names: ['立牌类谷子属性模板'], required: true },
  description: { names: ['详情描述模板-ACG立牌'], required: true },
  freight: { names: ['石油40g普货包裹.', '40g普货包裹'], required: true },
  service: { names: ['Service Template for New Sellers'], required: true },
  eu_responsible: { names: ['Jacqueiline Marti'], required: true },
  manufacturer: { names: ['jiyang county thunder', 'Jiyang County thunder'], required: true },
  compliance: { names: ['合规模板', '钥匙扣', 'keychain'], required: true },
  semi_managed: { names: ['半托管模板'], required: true },
}

export const demoTemplateSeeds = [
  { template_type: 'title', template_name: '标题模板', binding_scope: '平台 / 店铺 / 类目', payload: { rule: '核心词 + 属性词 + 卖点词' }, is_enabled: true },
  { template_type: 'category', template_name: '立牌类谷子属性模板', binding_scope: '平台 / 店铺 / 类目', payload: { category: { category_keyword: '立牌', category_match: 'ACG Stand', attribute_template_priorities: ['立牌类谷子属性模板'] } }, is_enabled: true },
  { template_type: 'sku', template_name: 'SKU/货品编码模板', binding_scope: '店铺 / 类目', payload: { sku: { goods_code_strategy: '沿用店小秘生成', barcode_strategy: '留空' } }, is_enabled: true },
  { template_type: 'pricing', template_name: '价格库存模板', binding_scope: '店铺 / 类目 / 物流', payload: { pricing: { declared_value: '1', stock: '200' } }, is_enabled: true },
  { template_type: 'logistics', template_name: '包装物流模板', binding_scope: '店铺 / 类目', payload: { logistics: { weight: '0.03', length: '10', width: '10', height: '2', freight_templates: ['石油40g普货包裹.', '40g普货包裹'], service_templates: ['Service Template for New Sellers'] } }, is_enabled: true },
  { template_type: 'image', template_name: '图片银行模板', binding_scope: '店铺 / 类目', payload: { image: { source: '图片银行（速卖通）', eu_outer_package_filename: '微信图片_202504092228421.jpg' } }, is_enabled: true },
  { template_type: 'semi_managed', template_name: '半托管模板', binding_scope: '店铺 / 类目 / 国家站点', payload: { semi_managed: { countries: '全选', original_box: '否', jit_stock: '100', barcode_strategy: '留空' } }, is_enabled: true },
  { template_type: 'compliance', template_name: '合规模板', binding_scope: '类目 / 国家站点', payload: { compliance: { eu_responsible_names: ['Jacqueiline Marti'], manufacturer_names: ['jiyang county thunder', 'Jiyang County thunder'], customs_product_names: ['钥匙扣', 'keychain'] } }, is_enabled: true },
  { template_type: 'dxm_reference', template_name: '店小秘引用模板映射', binding_scope: '店铺 / 类目 / 国家站点', payload: { dxm_reference_templates: demoDxmReferenceTemplates }, is_enabled: true },
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
  const stores = chooseList(workspace?.stores, bundle.stores, fallback.stores, Boolean(workspace), apiHasData)
  const templates = chooseList(workspace?.templates, bundle.templates, fallback.templates, Boolean(workspace), apiHasData)
  const products = chooseList(workspace?.products, bundle.products, fallback.products, Boolean(workspace), apiHasData)
  const tasks = mergeCurrentTaskIntoTasks(
    currentTask,
    chooseList(nonEmptyList(workspace?.tasks), currentTask ? [currentTask, ...bundle.tasks] : bundle.tasks, fallback.tasks, Boolean(workspace), apiHasData),
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
      mode: 'probe / dry_run / claim_only / single_save / batch_save',
      guarantee: '只保存不发布：当前仅受控 single_save 可在后端人工批准令牌下启动；claim_only/batch_save 未发布。',
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
      title: '真实登录态只读 probe',
      status: l2Ok ? 'mock_passed' : 'not_run',
      evidenceLevel: l2Ok ? 'B' : 'C',
      requiresApproval: true,
      command: 'tools/probes/l2_readonly_probe.py',
      detail: l2Ok ? '仅有离线/mock L2 证据；不满足真实页面 L2 放行条件。' : '尚未运行真实 L2 只读 probe。',
      latest: latestL2,
    },
    {
      level: 'L3',
      title: '单商品 save-only 金丝雀',
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
  const outputDir = 'data\\l2_readonly_probe'
  const allowlistFile = 'config\\l2_readonly_allowlist.json'
  const targets = [
    { id: 'data_acquisition', url: 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', required: true },
    { id: 'draft_box', url: 'https://www.dianxiaomi.com/web/smt/smtProductList/draft', required: true },
  ]
  return {
    schema: 'dxm_l2_readonly_probe_plan.v1',
    requiresApproval: true,
    purpose: '真实店小秘采集页和采集箱只读检查；不领取、不备注、不保存、不发布。',
    runIdCommand,
    pythonCommand,
    scriptPath,
    cookieFile,
    outputDir,
    allowlistFile,
    targets,
    commands: [
      runIdCommand,
      ...targets.map((target) => `${pythonCommand} ${scriptPath} --target ${target.id} --run-id $runId --cookie-file ${cookieFile} --output-dir ${outputDir} --allowlist-file ${allowlistFile}`),
    ],
    acceptanceCriteria: [
      '两个目标必须使用同一 run-id。',
      '两个目标必须共享同一 session fingerprint、script_sha256 和 git_head。',
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
    'publish_allowed=false',
    '禁止发布、继续发布、保存并发布、移入待发布',
    '人工批准令牌',
    '失败停止并人工接管',
  ]
  return {
    schema: 'dxm_real_mode_release_plan.v1',
    scope: 'controlled_single_save_only',
    publish_allowed: false,
    batch_unattended_publish_allowed: false,
    modes: [
      {
        mode: 'single_save',
        label: '受控单商品只保存已放行',
        status: 'released_controlled',
        allowed: true,
        release_scope: 'single product save-only canary',
        required_evidence: [
          '采集页和采集箱真实只读检查通过',
          '店小秘返回保存成功',
          '未发布状态证明',
          '保存成功回包和页面记录',
        ],
        required_controls: sharedControls,
        blockers: [],
        readiness_checklist: [
          checklist('l2_dual_target', '采集页和采集箱真实只读检查通过', 'passed'),
          checklist('l3_single_canary', '单商品只保存证据', 'passed'),
          checklist('published_false', '未发布状态证明', 'passed'),
          checklist('publish_guard', '发布隔离无风险信号', 'passed'),
        ],
      },
      {
        mode: 'claim_only',
        label: '只认领当前未开放',
        status: 'blocked_unreleased',
        allowed: false,
        release_scope: 'not released',
        required_evidence: [
          '独立 claim_only L2/L3 证据',
          'claim ownership proof',
          '不打开编辑页、不触发保存请求证明',
          '领取锁定与释放审计链',
        ],
        required_controls: [
          ...sharedControls,
          'claim 标记可回退',
          '人工释放/恢复计划',
        ],
        blockers: [
          'cannot reuse single_save evidence',
          '不能复用 single_save 证据',
          '缺少 claim ownership proof',
        ],
        readiness_checklist: [
          checklist('dedicated_l2_l3', '独立 claim_only L2/L3 证据', 'missing', 'cannot reuse single_save evidence', 'claim_only 会改变草稿归属状态，不能复用 single_save 金丝雀。'),
          checklist('claim_ownership_proof', 'claim ownership proof', 'missing', 'missing claim ownership proof', '需要证明命中的是目标店铺、目标商品和目标来源链接。'),
          checklist('no_editor_or_save', '不打开编辑页、不触发保存请求证明', 'missing', 'missing negative save proof', 'claim_only 不能触发编辑页保存接口。'),
          checklist('rollback_release', '归属释放或人工回滚路径', 'missing', 'missing ownership rollback proof', '误领或中断时必须有人工恢复路径。'),
        ],
      },
      {
        mode: 'batch_save',
        label: '批量只保存当前未开放',
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
      detail: '结果报告需要汇总配置命中、执行步骤、证据等级和未完成缺口。',
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
    mode: 'single_save / batch_save / claim_only / dry_run / probe',
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

function nonEmptyList<T>(value: T[] | undefined): T[] | undefined {
  return Array.isArray(value) && value.length > 0 ? value : undefined
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
