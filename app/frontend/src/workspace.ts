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
  current_task?: Task
  steps?: RunStep[]
  evidence_points?: EvidencePoint[]
  report_summary?: ReportSummary
  template_resolution?: TemplateResolutionResult
  publish_guard_state?: SafetyGuardState
  evidence_grade?: { grade: EvidenceGrade; [key: string]: unknown }
  regression_gates?: RegressionGate[]
  l2_probe_plan?: L2ProbePlan
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
  const stores = chooseList(workspace?.stores, bundle.stores, fallback.stores, Boolean(workspace), apiHasData)
  const templates = chooseList(workspace?.templates, bundle.templates, fallback.templates, Boolean(workspace), apiHasData)
  const products = chooseList(workspace?.products, bundle.products, fallback.products, Boolean(workspace), apiHasData)
  const tasks = chooseList(workspace?.tasks, currentTask ? [currentTask] : bundle.tasks, fallback.tasks, Boolean(workspace), apiHasData)
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
    dxmReferenceTemplates: normalizeReferenceSections(undefined, [], [], null),
    acceptanceGaps: [{
      id: 'empty-workspace',
      title: '尚无真实任务数据',
      severity: 'watch',
      owner: 'workspace',
      detail: '准备演示数据或接入后端任务后，工作台才会展示报告和证据。',
      evidenceLevel: 'C',
    }],
    safety: {
      mode: 'probe / dry_run / claim_only / single_save / batch_save',
      guarantee: '只保存不发布：真实 claim_only/single_save/batch_save 启动前必须有后端人工批准令牌。',
      forbiddenActions: ['发布', '继续发布', '保存并发布', '移入待发布'],
      lastCheckedAt: '等待任务数据',
    },
  }
}

export function buildMockWorkspace(): DeliveryWorkspace {
  const stores: Store[] = [{ id: 1, name: 'Dang Kang', platform: 'AliExpress', status: 'connected' }]
  const templates: Template[] = demoTemplateSeeds.map((item, index) => ({ id: index + 1, ...item }))
  const products: Product[] = [{
    id: 101,
    title: seedRows[0].title,
    category_name: seedRows[0].category_name,
    price: seedRows[0].price,
    currency: 'USD',
    sku_count: seedRows[0].sku_count,
    image_count: seedRows[0].image_count,
    status: 'ready',
    image: seedRows[0].image,
  }]
  const tasks: Task[] = [{
    id: 19,
    name: '本地演示保存核验批次 #19',
    status: 'draft',
    mode: 'dry_run',
    publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
    total_jobs: 1,
    completed_jobs: 0,
    failed_jobs: 0,
    payload: {
      product_ids: [101],
      store_name: 'Dang Kang',
      category_name: '立牌类谷子',
      image: seedRows[0].image,
      dxm_reference_templates: demoDxmReferenceTemplates,
    },
  }]
  const logs: LogItem[] = [
    { id: 1, task_id: 19, job_id: 31, level: 'info', message: '配置已完成预检，等待 L2/L3 门禁复核', context: {}, created_at: '2026-05-22T09:00:00+08:00' },
    { id: 2, task_id: 19, job_id: 31, level: 'warning', message: '后端 /api/delivery/workspace 未接入时，前端使用工作台 fallback 数据', context: {}, created_at: '2026-05-22T09:01:00+08:00' },
  ]
  const evidences: Evidence[] = [
    { id: 676, task_id: 19, job_id: 31, evidence_type: 'state_snapshot', file_path: 'data/screenshots/v1_task_19_job_31_PRECHECK_CONFIG.txt', meta: { grade: 'A', title: '配置预检快照', acceptance: '可追溯到模板与店铺配置' }, created_at: '2026-05-22T01:55:49Z' },
    { id: 677, task_id: 19, job_id: 31, evidence_type: 'workflow_action', file_path: '/artifacts/screenshots/dianxiaomi_save_only.png', meta: { grade: 'B', title: '本地演示截图占位', acceptance: '仅用于降级页面布局，不作为真实 DXM 保存证据' }, created_at: '2026-05-22T01:56:56Z' },
    { id: 680, task_id: 19, job_id: 31, evidence_type: 'workflow_action', file_path: '/artifacts/screenshots/dianxiaomi_verify_not_published.png', meta: { grade: 'C', title: '演示结果隔离核验', acceptance: '缺少真实 L3 金丝雀与独立审计人复核记录' }, created_at: '2026-05-22T01:57:14Z' },
  ]
  const exceptions: ExceptionItem[] = [
    { id: 1, task_id: 19, job_id: 31, error_code: 'GAP-A1', field_domain: 'evidence', title: 'A级证据仍缺浏览器会话指纹', detail: '保存截图已有，但没有浏览器环境、账号、批次三者的同屏绑定。', suggestion: '报告中心需要补充会话摘要和截图哈希。', status: 'open' },
    { id: 2, task_id: 19, job_id: 31, error_code: 'GAP-B2', field_domain: 'template_trace', title: '引用模板命中需要逐段回显', detail: '已展示 dxm_reference_templates 映射，但真实页面选择结果仍需逐段记录。', suggestion: '把 attribute_info、freight、service 等结果写入报告摘要。', status: 'open' },
  ]
  const reports: Report[] = [{
    id: 11,
    task_id: 19,
    title: '本地演示保存核验报告 #19',
    status: 'draft',
    report_type: 'save_only_acceptance',
    summary: '已建立本地演示报告框架，等待真实 L2/L3 放行后补齐执行结果。',
    file_path: null,
    created_at: '2026-05-22T01:57:14Z',
    published: false,
  }]
  const deliverySteps: RunStep[] = [
    { state: 'PRECHECK_CONFIG', label: '配置预检', field_domain: 'config', status: 'completed', has_evidence: true, evidence_count: 1 },
    { state: 'FILL_MEDIA', label: '图片与营销图', field_domain: 'media', status: 'pending', has_evidence: false, evidence_count: 0 },
    { state: 'L3_SAVE_GATE', label: 'L3 保存门禁', field_domain: 'save', status: 'pending', has_evidence: false, evidence_count: 0 },
    { state: 'VERIFY_NOT_PUBLISHED', label: '未发布校验', field_domain: 'publish_guard', status: 'pending', has_evidence: false, evidence_count: 0 },
  ]
  const evidencePoints: EvidencePoint[] = evidences.map((evidence) => ({
    kind: evidence.evidence_type,
    id: evidence.id,
    job_id: evidence.job_id,
    state: String(evidence.meta?.state ?? ''),
    file_path: evidence.file_path,
    created_at: evidence.created_at,
  }))
  const reportSummary: ReportSummary = {
    total_reports: reports.length,
    success_count: 0,
    failed_count: 0,
    published_count: 0,
    latest_report: reports[0],
    save_results: [],
    network_save_results: [],
    har_summaries: [],
    published_proofs: [],
    dxm_reference_fields: {},
  }
  const publishGuardState: SafetyGuardState = {
    status: 'waiting_for_execution',
    safe: true,
    published: false,
    publish_allowed: false,
    report_published_all_false: true,
    has_unpublished_proof: false,
    reasons: [],
  }
  const evidenceGradeValue = { grade: 'C' as EvidenceGrade, has_network_or_har_save_response: false }
  const regressionGates = buildRegressionGates(null, evidenceGradeValue, [])

  return {
    source: 'mock',
    stores,
    templates,
    products,
    tasks,
    logs,
    evidences,
    exceptions,
    reports,
    liveEvents: [],
    deliverySteps,
    evidencePoints,
    reportSummary,
    templateResolution: {
      dxm_reference_templates_resolved: demoDxmReferenceTemplates,
      dxm_reference_template_results: {},
      template_trace: [],
      resolved_defaults: {},
    },
    publishGuardState,
    evidenceGrade: evidenceGradeValue,
    regressionGates,
    l2ProbePlan: buildL2ProbePlan(),
    dxmReferenceTemplates: normalizeReferenceSections(undefined, templates, reports),
    acceptanceGaps: buildAcceptanceGaps(exceptions, evidences, reports, evidenceGradeValue),
    safety: {
      mode: 'dry_run',
      guarantee: '本地演示 dry_run：工作台不提供任何上架入口，真实写入仍需 L2/L3 放行。',
      forbiddenActions: ['立即上架', '继续上架', '保存并上架', '批量上架'],
      lastCheckedAt: '2026-05-22 09:00',
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
  const targets = [
    { id: 'data_acquisition', url: 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', required: true },
    { id: 'draft_box', url: 'https://www.dianxiaomi.com/web/smt/smtProductList/draft', required: true },
  ]
  return {
    schema: 'dxm_l2_readonly_probe_plan.v1',
    requiresApproval: true,
    purpose: '真实店小秘双目标只读诊断；不领取、不备注、不保存、不发布。',
    runIdCommand,
    pythonCommand,
    scriptPath,
    cookieFile,
    outputDir,
    targets,
    commands: [
      runIdCommand,
      ...targets.map((target) => `${pythonCommand} ${scriptPath} --target ${target.id} --run-id $runId --cookie-file ${cookieFile} --output-dir ${outputDir}`),
    ],
    acceptanceCriteria: [
      '两个目标必须使用同一 run-id。',
      '两个目标必须共享同一 session fingerprint、script_sha256 和 git_head。',
      '只读网络计数必须全为 0。',
    ],
    safetyNotes: [
      '运行前必须由操作者明确批准真实 L2 只读探测。',
      'L2 只读探测失败或只产生 mock 证据时不自动放行 L3。',
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
    targets: Array.isArray(plan.targets) ? plan.targets as L2ProbePlan['targets'] : fallback.targets,
    commands: Array.isArray(plan.commands) ? plan.commands.map(String).filter(Boolean) : fallback.commands,
    acceptanceCriteria: Array.isArray(plan.acceptanceCriteria) ? plan.acceptanceCriteria.map(String).filter(Boolean) : fallback.acceptanceCriteria,
    safetyNotes: Array.isArray(plan.safetyNotes) ? plan.safetyNotes.map(String).filter(Boolean) : fallback.safetyNotes,
  }
}

export function humanTaskStatus(status: string) {
  return ({ draft: '待启动', running: '运行中', completed: '已完成', partial_success: '部分成功', paused: '已暂停', failed: '失败', cancelled: '已停止' } as Record<string, string>)[status] ?? status
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
      detail: '报告中心需要汇总配置命中、执行步骤、证据等级和未完成缺口。',
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

function normalizeTask(value: Task | undefined): Task | null {
  if (!value) return null
  return {
    ...value,
    total_jobs: Number(value.total_jobs ?? 0),
    completed_jobs: Number(value.completed_jobs ?? 0),
    failed_jobs: Number(value.failed_jobs ?? 0),
    payload: value.payload ?? {},
  }
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
