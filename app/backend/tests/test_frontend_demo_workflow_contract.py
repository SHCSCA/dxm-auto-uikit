from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
WORKSPACE_TS = REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts"
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
SAFETY_STATUS_BAR_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "SafetyStatusBar.tsx"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"


def test_demo_batch_creation_uses_dry_run_for_local_startable_user_path():
    source = APP_TSX.read_text(encoding="utf-8")
    bootstrap_section = source[source.index("async function bootstrapDemo"):source.index("async function startSelectedTask")]

    assert "mode: 'dry_run'" in bootstrap_section
    assert "mode: 'single_save'" not in bootstrap_section
    assert "本地演示核验批次" in bootstrap_section


def test_task_center_does_not_apply_l3_real_write_block_to_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "const l3BlocksStart = needsRealL2 && l3Gate?.status === 'blocked'" in source
    assert "启动本地演示任务" in source
    assert "真实 single_save" in source
    assert "普通模式不展示本地演示入口" in source
    assert "创建本地 dry_run 演示批次" in source
    assert "不触达 DXM" in source


def test_frontend_loads_config_preview_and_blocks_real_start_when_incomplete():
    source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]

    assert "ConfigPreview" in source
    assert "setConfigPreview" in source
    assert "/api/config/preview?task_id=" in source
    assert "配置预检未通过" in start_section
    assert "setActiveSection('config')" in start_section
    assert "configBlocksStart" in workbench_source
    assert "配置未完成，禁止启动" in workbench_source
    assert "去配置中心" in workbench_source


def test_config_center_prioritizes_missing_sections_and_sources():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "ConfigReadinessPanel" in source
    assert "NextRequiredConfigFields" in config_section
    assert "下一步必填字段" in source
    assert "只显示当前最需要处理的字段" in source
    assert "DXM 编辑页配置" in config_section
    assert "默认只展开待补分区" in config_section
    assert "config-focus-card" in config_section
    assert "sectionsNeedingAttention" in config_section
    assert "查看已就绪分区" in config_section
    assert "previewSection: 'semi_managed'" in source
    assert "templateType: 'sku'" in source
    assert "templateType: 'pricing'" in source
    assert "fieldSourceText" in source
    assert "当前值：" in source
    assert "来源：" in source
    assert "缺失：" in source
    assert "open={openByDefault}" in config_section


def test_config_center_matches_dxm_edit_page_sections_and_value_preview():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "店铺与任务基础" in config_section
    assert "类目与标题" in config_section
    assert "SKU / 价格 / 库存" in config_section
    assert "价格策略" in config_section
    assert "图片与素材" in config_section
    assert "包装物流" in config_section
    assert "合规 / 海关" in config_section
    assert "半托管" in config_section
    assert "店小秘引用模板" in config_section
    assert "本次任务实际取值预览" in config_section
    assert "任务覆盖" in config_section
    assert "商品 payload" in config_section
    assert "店铺/类目模板" in config_section
    assert "系统默认值" in config_section
    assert "dxm_reference_templates.attribute_info.names" in config_section
    assert "dxm_reference_templates.freight.names" in config_section
    assert "dxm_reference_templates.service.names" in config_section
    assert "dxm_reference_templates.eu_responsible.names" in config_section
    assert "dxm_reference_templates.manufacturer.names" in config_section
    assert "setNestedConfigValue" in config_section
    assert "尺码模板" in config_section
    assert "publish_allowed" not in config_section
    assert "price_multiplier" in config_section
    assert "local_asset_path" in config_section
    assert "brand" in config_section


def test_config_center_marks_direct_and_advisory_config_fields():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "usage:" in source
    assert "直接填入 DXM" in config_section
    assert "模板匹配" in config_section
    assert "策略/备用" in config_section
    assert "field-usage" in config_section


def test_config_center_can_save_task_level_overrides_separately_from_templates():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]
    main_source = (REPO_ROOT / "app" / "backend" / "src" / "main.py").read_text(encoding="utf-8")
    models_source = (REPO_ROOT / "app" / "backend" / "src" / "models.py").read_text(encoding="utf-8")
    repo_source = (REPO_ROOT / "app" / "backend" / "src" / "repository.py").read_text(encoding="utf-8")

    assert "buildEditableConfigDraft(workspace.templates, configPreview)" in config_section
    assert "scope: 'template' | 'task'" in config_section
    assert "`/api/tasks/${selectedTask.id}/config-overrides`" in config_section
    assert "findSelectedTaskProduct(workspace.products, selectedTask)" in config_section
    assert "buildCurrentTemplateBinding(workspace, selectedTask, product)" in config_section
    assert "payload: withTemplateBinding(payload, currentTemplateBinding)" in config_section
    assert "findScopedTemplate(workspace.templates, section.templateType, currentTemplateBinding)" in config_section
    assert "当前模板范围" in config_section
    assert "仅本次任务使用" in config_section
    assert "保存为店铺模板" in config_section
    assert "当前任务会优先使用这些值" in config_section
    assert "@app.patch('/api/tasks/{task_id}/config-overrides')" in main_source
    assert "TaskConfigOverrideRequest" in models_source
    assert "update_task_template_override" in repo_source


def test_config_center_preserves_multi_value_reference_template_fields():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    config_section = source[source.index("export function ConfigCenter"):source.index("export function TaskCenter")]

    assert "valueKind?: 'text' | 'list'" in source
    assert "valueKind: 'list'" in source
    assert "parseEditableConfigFieldValue" in config_section
    assert "function editableConfigDraftValue" in source
    assert "value.join('\\n')" in source
    assert "<textarea" in config_section
    assert "每行一个" in config_section


def test_browser_qa_verifies_config_center_task_override_controls():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "taskOverrideSave" in source
    assert "templateSave" in source
    assert "nextRequiredConfig" in source
    assert "configReadySummary" in source
    assert "currentTemplateScope" in source
    assert "configHasTemplateScope" in source
    assert "onePerLine" in source
    assert "configHasListEditor" in source
    assert "loginManualBrowser" in source
    assert "consoleRealBrowserLoginEntry" in source
    assert "fieldSource" in source
    assert "configCenterTaskOverrideControls" in source
    assert "qa-config-center" in source
    assert "configShot" in source


def test_browser_qa_rejects_desktop_horizontal_overflow():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "desktopReflow" in source
    assert "desktopOverflow" in source
    assert "desktopNoHorizontalOverflow" in source
    assert "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1" in source
    assert ".effective-value-item" in source


def test_frontend_has_stateful_operation_guide_entry():
    app_source = APP_TSX.read_text(encoding="utf-8")
    shell_source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "useState<WorkbenchSection>('guide')" in app_source
    assert "{ id: 'guide', label: '操作引导', short: '导' }" in shell_source
    assert "case 'guide'" in app_source
    assert "GuideCenter" in app_source
    assert "export function GuideCenter" in workbench_source
    assert "确认服务运行" in workbench_source
    assert "打开真实 DXM 浏览器并确认登录" in workbench_source
    assert "填写编辑页配置" in workbench_source
    assert "运行只读检查" in workbench_source
    assert "人工确认真实保存" in workbench_source
    assert "申请并启动 single_save" in workbench_source
    assert "观察实时浏览器执行" in workbench_source
    assert "查看报告与证据" in workbench_source
    assert "查看证据中心" in workbench_source
    assert "查看异常池" in workbench_source
    assert "guide-step.is-current" in styles_source
    assert "guide-step.is-blocked" in styles_source
    assert "data-guide-step" in workbench_source
    assert "reason:" in workbench_source


def test_guide_center_can_start_real_dxm_login_without_l2_gate():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "async function openDxmLogin" in app_source
    assert "async function continueDxmLogin" in app_source
    assert "async function navigateDxmTarget" in app_source
    assert "/api/dxm/login/start" in app_source
    assert "/api/dxm/login/continue" in app_source
    assert "/api/dxm/navigate" in app_source
    assert "onOpenDxmLogin={openDxmLogin}" in app_source
    assert "onContinueDxmLogin={continueDxmLogin}" in app_source
    assert "onNavigateDxmTarget={navigateDxmTarget}" in app_source
    assert "onOpenDxmLogin: () => void" in workbench_source
    assert "onContinueDxmLogin: () => void" in workbench_source
    assert "onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void" in workbench_source
    assert "action: '打开登录页'" in workbench_source
    assert "验证码已完成，检测登录态" in workbench_source
    assert "进入采集箱" in workbench_source
    assert "onAction: onOpenDxmLogin" in workbench_source
    assert "账号密码只用于本次真实店小秘登录" in workbench_source
    assert "DXM 登录状态" in workbench_source


def test_execution_console_defaults_to_operator_focus_and_collapses_advanced_noise():
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function AgentBrowserFrame")]

    assert "ConsoleFocusPanel" in console_section
    assert "title=\"真实浏览器\"" in console_section
    assert "className=\"module-card span-2 agent-console-stage\"" in console_section
    assert "className=\"module-card console-log-card console-log-card--live\"" in console_section
    assert "RuntimeLogPreview" in console_section
    assert "最近日志" in console_section
    assert "summary>完整日志中心</summary>" in console_section
    assert console_section.index("RuntimeLogPreview") < console_section.index("summary>完整日志中心</summary>")
    assert console_section.index("RuntimeLogPanel") > console_section.index("summary>完整日志中心</summary>")
    assert "summary>辅助面板：运行维护 / 自动操作轨迹</summary>" in console_section
    assert "summary>执行步骤明细</summary>" in console_section
    assert "summary>任务执行日志</summary>" in console_section
    assert "登录/人工处理真实浏览器" in workbench_source
    assert "验证码已完成，检测登录态" in workbench_source
    assert "进入采集箱" in workbench_source
    assert "启动执行观察" in workbench_source
    assert "不会发布" in workbench_source
    assert "console-focus-panel" in styles_source
    assert ".console-advanced" in styles_source
    assert ".console-support-grid" in styles_source


def test_execution_console_log_center_autofollows_and_surfaces_sources():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    log_panel_section = workbench_source[workbench_source.index("function RuntimeLogPanel"):workbench_source.index("function RuntimeLogLine")]

    assert "window.setInterval" in app_source
    assert "1500" in app_source
    assert "实时日志中心" in workbench_source
    assert "每 1.5 秒刷新" in workbench_source
    assert "自动跟随最新日志" in log_panel_section
    assert "setAutoFollow" in log_panel_section
    assert "logViewRef" in log_panel_section
    assert "scrollTop = logViewRef.current.scrollHeight" in log_panel_section
    assert "onScroll" in log_panel_section
    assert "data-testid=\"runtime-log-view\"" in log_panel_section
    assert "启动器" in log_panel_section
    assert "依赖安装" in log_panel_section
    assert "浏览器 Agent" in log_panel_section
    assert "打开 DXM" in workbench_source
    assert "网络响应" in workbench_source
    assert ".console-log-card--live" in styles_source
    assert ".runtime-log-toolbar" in styles_source


def test_agent_console_uses_live_frame_and_network_event_contract():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("function AgentBrowserFrame"):workbench_source.index("function AgentConsoleControls")]

    assert "/api/agent-console/frame" in app_source
    assert "Boolean(agentConsole?.browser_visible)" in app_source
    assert "last_frame_at?: string | null" in types_source
    assert "network_events?: AgentConsoleNetworkEvent[]" in types_source
    assert "withCacheBust(toArtifactUrl(agentConsole.screenshot_url ?? agentConsole.screenshot), agentConsole.last_frame_at)" in workbench_source
    assert "网络响应" in console_section
    assert "等待网络响应" in console_section
    assert "getRecentNetworkEvents(agentConsole)" in console_section
    assert "自动刷新画面" in workbench_source
    assert "真实窗口是主要操控界面" in console_section
    assert "截图只作为证据缩略图" in console_section
    assert "刷新当前画面" in workbench_source


def test_execution_console_exposes_manual_takeover_for_real_browser():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function RuntimeControlPanel")]

    assert "async function requestAgentConsoleTakeover" in app_source
    assert "/api/agent-console/takeover" in app_source
    assert "/api/agent-console/release" in app_source
    assert "onOpenDxmLogin={openDxmLogin}" in app_source
    assert "onOpenDxmLogin" in console_section
    assert "登录/人工处理真实浏览器" in workbench_source
    assert "登录和人工处理不要求 L2" in workbench_source
    assert "onRequestAgentConsoleTakeover={requestAgentConsoleTakeover}" in app_source
    assert "onReleaseAgentConsoleTakeover={releaseAgentConsoleTakeover}" in app_source
    assert "manual_takeover?: boolean" in types_source
    assert "manual_takeover_started_at?: string | null" in types_source
    assert "人工接管真实浏览器" in workbench_source
    assert "交还 Agent" in workbench_source
    assert "用户正在真实浏览器中接管" in workbench_source


def test_execution_console_exposes_runtime_control_and_agent_action_timeline():
    app_source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    console_section = workbench_source[workbench_source.index("export function ExecutionConsole"):workbench_source.index("function ConsoleFocusPanel")]

    assert "async function runRuntimeControl" in app_source
    assert "/api/runtime/control" in app_source
    assert "onRuntimeControl={runRuntimeControl}" in app_source
    assert "console-support-drawer" in console_section
    assert "ModuleHead title=\"运行时维护\"" in console_section
    assert "RuntimeControlPanel" in console_section
    assert "停止浏览器 Agent" in workbench_source
    assert "清理卡住任务" in workbench_source
    assert "重启后端" in workbench_source
    assert "启动器托管提示" in workbench_source
    assert "ModuleHead title=\"自动操作轨迹\"" in console_section
    assert "AgentActionTimeline" in console_section
    assert "export type AgentConsoleActionEvent" in types_source
    assert "action_events?: AgentConsoleActionEvent[]" in types_source
    assert "getAgentActionTimelineEvents" in workbench_source
    assert "agentConsole?.action_events" in workbench_source
    assert "agentConsole?.step_history" in workbench_source
    assert "save: '保存'" in workbench_source
    assert "fill: '填写'" in workbench_source
    assert ".runtime-control-panel" in styles_source
    assert ".agent-action-timeline" in styles_source


def test_browser_qa_verifies_demo_is_hidden_from_default_user_path():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = source[source.index("async function ensureRealMutationTask"):source.index("async function screenshot")]

    assert "demoBatchHiddenByDefault" in source
    assert "demoBatchButton" in source
    assert "localDemoStart" in source
    assert "realMutationTask" in source
    assert "async function waitForTextGone(fragment" in source
    assert "await waitForTextGone(text.workspaceLoading" in source
    assert "clickSelector('[data-section=\"tasks\"]')" in source
    assert "clickSelector('[data-section=\"console\"]')" in source
    assert "clickSelector('[data-section=\"reports\"]')" in source
    assert "taskTextAfterDefaultDemoCheck" in source
    assert "!taskTextAfterDefaultDemoCheck.includes(text.demoBatchButton)" in source
    assert "fetchJson('/api/stores')" in ensure_section
    assert "fetchJson('/api/products')" in ensure_section
    assert "existingStores.find(store => store?.name === 'Dang Kang')" in ensure_section
    assert "/api/delivery/workspace" not in ensure_section


def test_browser_qa_uses_browser_launch_fallbacks_and_logs_failures():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "function Find-BrowserCandidates" in source
    assert "function Test-DebugPortAvailable" in source
    assert "[System.Net.Sockets.TcpListener]::new" in source
    assert "function Find-QaDebugPort" in source
    assert "@(15000, 20000, 30000, 40000, 50000)" in source
    assert "Port $Port is unavailable or reserved; using $selectedPort instead" in source
    assert "function Start-QaCdpBrowser" in source
    assert "qa-browser-launch-attempts.json" in source
    assert "qa-browser-stderr" in source
    assert "ms-playwright" in source
    assert "chrome-win64" in source
    assert "--headless=new" in source
    assert "--headless" in source
    assert "HeadlessMode" in source
    assert "Chrome DevTools endpoint did not start after trying" in source
    assert "qa-browser-error.json" in source
    assert "unhandledRejection" in source
    assert "uncaughtException" in source


def test_report_center_uses_backend_l2_probe_plan_contract():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "workspace.l2ProbePlan" in report_center_section
    assert "l2ProbePlan.commands.map" in report_center_section
    assert "l2ProbePlan.acceptanceCriteria" in report_center_section
    assert "normalizeL2ProbePlan" in workspace_source
    assert "Array.isArray(plan.commands)" in workspace_source
    assert "Array.isArray(plan.acceptanceCriteria)" in workspace_source
    assert "Array.isArray(plan.safetyNotes)" in workspace_source


def test_report_center_shows_allowlist_review_before_l2_recheck_commands():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "app" / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "l2AllowlistReviewItems" in report_center_section
    assert "L2 allowlist 候选处理" in report_center_section
    assert "先评审，再复跑 L2" in report_center_section
    assert "review_only=true / allowlist_applied=false" in report_center_section
    assert "未完成人工评审前，不运行下方 L2 复验命令" in report_center_section
    assert "l2_allowlist_review_template_state" in source
    assert "l2_allowlist_review_template_markdown_path" in source
    assert "l2_allowlist_review_template_markdown_sha256" in source
    assert "l2_allowlist_review_template_json_sha256" in source
    assert "l2_allowlist_review_template_candidate_count" in types_source
    assert "ok_scope" in source
    assert "real_dxm_mutation_allowed" in source
    assert "real_dxm_write_blocked_reason" in source
    assert "expected_real_dxm_write_readiness" in source
    assert "real_dxm_write_readiness_matches_expected" in source
    assert "预期真实写入" in source
    assert "真实写入允许 false" in source


def test_final_delivery_card_explains_blocked_to_ready_prerequisites():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    final_card_section = source[source.index("function FinalDeliveryCheckCard"):source.index("function SourcePackageCheckRow")]
    qa_script = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "真实写入放行前置" in final_card_section
    assert "L2 双目标真实只读通过" in source
    assert "人工批准 L3 金丝雀" in source
    assert "保存成功、未发布证明、截图和 network/HAR" in source
    assert "不能用 allowlist 模板替代 L2 通过" in source
    assert "delivery-check-card__release-gates" in final_card_section
    assert "realWriteReleasePrerequisites" in source
    assert "reportRealWriteReleasePrerequisites" in qa_script


def test_report_center_treats_missing_l3_evidence_as_expected_when_real_write_blocked():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    report_center_section = source[source.index("export function ReportCenter"):source.index("function FinalDeliveryCheckCard")]

    assert "realWriteExpectedBlocked" in report_center_section
    assert "EvidenceCheckRow" in report_center_section
    assert "BusinessReportCheckRow" in report_center_section
    assert "PostL3ReportCheckRow" in report_center_section
    assert "label=\"保存结果\"" in source
    assert "label=\"未发布证明\"" in source
    assert "label=\"网络/HAR\"" in source
    assert "业务保存报告 0 份（L3 后置，预期阻断）" in source
    assert "（预期阻断）" in source
    assert "state={'locked'}" in source
    assert "state === 'locked' ? 'locked'" in source
    assert "state === 'locked' ? 'LOCK'" in source
    assert "ok={true} state={'locked'}" not in source
    assert "L3 未放行前不要求生成真实保存证据" in source
    assert "真实写入 BLOCKED 时不要求生成业务保存报告" in source
    assert "L3 后置报告必须覆盖" in source
    assert "L3 放行后要求" in source
    assert "CheckRow label={`报告 ${reportSummary?.total_reports ?? reports.length} 份`}" not in report_center_section


def test_safety_bar_downgrades_l3_post_evidence_gaps_when_real_write_blocked():
    source = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "l3PostEvidenceGapIds" in source
    assert "visibleBlockerGaps" in source
    assert "l3PostEvidenceGapCount" in source
    assert "gap-save-result" in source
    assert "gap-unpublished-proof" in source
    assert "gap-network-save-response" in source
    assert "保存后证据" in source
    assert "预期阻断" in source
    assert "blockerGaps.slice(0, 2)" not in source


def test_dashboard_and_exception_gap_lists_present_l3_post_evidence_as_locked_scope():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    dashboard_section = source[source.index("export function Dashboard"):source.index("function RegressionGateGrid")]
    exception_section = source[source.index("export function ExceptionQueue"):source.index("export function ReportCenter")]
    gap_list_section = source[source.index("function GapList"):source.index("function CheckRow")]

    assert "presentAcceptanceGaps" in source
    assert "isRealWriteExpectedBlocked" in source
    assert "l3PostEvidenceGapIds" in source
    assert "presentedAcceptanceGaps" in dashboard_section
    assert "presentedAcceptanceGaps" in exception_section
    assert "GapList gaps={presentedAcceptanceGaps" in dashboard_section
    assert "GapList gaps={presentedAcceptanceGaps}" in exception_section
    assert "L3 后置：" in source
    assert "真实写入放行后再补齐" in source
    assert "severity: 'watch'" in source
    assert "data-gap-id={gap.id}" in gap_list_section
    assert "data-severity={gap.severity}" in gap_list_section


def test_task_and_evidence_center_describe_l3_blocked_as_expected_lock():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]
    evidence_timeline_section = source[source.index("export function EvidenceTimeline"):source.index("function EvidencePointCard")]

    assert "真实保存必须停止并复核 publish guard" not in task_center_section
    assert "解除发布隔离风险" not in task_center_section
    assert "齐全后才会形成 A/B/C 证据等级" not in evidence_timeline_section

    assert "L3 当前按门禁锁定" in task_center_section
    assert "L2 未 passed 或人工批准未完成前" in task_center_section
    assert "不启动未发布 claim_only/batch_save" in task_center_section
    assert "仅受控 single_save 可在 L2 passed + 人工批准后进入 runner" in task_center_section
    assert "L3 保持锁定，禁止启动" in task_center_section
    assert "当前真实写入未放行时" in evidence_timeline_section
    assert "0 条是预期阻断" in evidence_timeline_section
    assert "只有 L3 金丝雀完成后才生成可验收证据等级" in evidence_timeline_section


def test_task_center_only_uses_demo_ready_copy_for_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "selectedTask?.mode === 'dry_run'" in task_center_section
    assert "demoEnabled && selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span>本地演示批次仅用于开发验收" in task_center_section
    assert "{selectedTask?.status === 'draft' && <span>本地演示批次已可用于验收门禁" not in task_center_section
    assert "当前真实任务保持门禁控制，请先处理上方阻断原因。" in task_center_section


def test_task_center_exposes_real_task_creation_instead_of_demo_first_flow():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "onCreateRealTask" in task_center_section
    assert "创建真实任务" in task_center_section
    assert "L2 只读检查" in task_center_section
    assert "L3 single_save" in task_center_section
    assert "批量保存未放行" in task_center_section
    assert "发布动作未开放" in task_center_section
    assert "SMT_SEMI_MANAGED_SAVE_ONLY" in task_center_section
    assert "data-testid=\"real-task-create\"" in task_center_section
    assert "postJson<Task>('/api/tasks'" in app_source
    assert "mode: request.mode" in app_source
    assert "publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY'" in app_source
    assert "onCreateRealTask={createRealTask}" in app_source


def test_task_center_surfaces_l2_allowlist_review_candidates_as_manual_review_only():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "reviewCandidateRequests" in source
    assert "只读依赖人工评审清单" in source
    assert "manual review only" in source
    assert "allowlist_applied=false" in source
    assert "不自动放行 L2/L3" in source
    assert "onShowReports" in source
    assert "查看 L2 评审与复验计划" in source
    assert "onShowReports={() => setActiveSection('reports')}" in app_source


def test_frontend_blocks_unreleased_real_modes_before_l3_manual_approval():
    source = APP_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    start_section = source[source.index("async function startSelectedTask"):source.index("async function startAgentConsole")]
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    no_old_action_copy_start = qa_source.index("noOldActionCopy:")
    no_old_action_copy_section = qa_source[no_old_action_copy_start:qa_source.index("noConsoleErrors:", no_old_action_copy_start)]

    assert "const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])" in source
    assert "const UNRELEASED_REAL_DXM_MUTATION_MODES = new Set(['claim_only', 'batch_save'])" in source
    assert "UNRELEASED_REAL_DXM_MUTATION_MODES.has(selectedTask.mode)" in start_section
    assert "当前真实 DXM 写入仅发布受控 single_save" in start_section
    assert "claim_only/batch_save 必须重新建立 L2/L3 证据后再放行" in start_section
    assert "将只启动受控 single_save save-only 金丝雀" in start_section
    assert "将只启动 save-only/claim-only 受控任务" not in start_section
    assert "const selectedTaskIsUnreleasedRealMode = selectedTask ? isUnreleasedRealDxmMutationTask(selectedTask) : false" in workbench_source
    assert "startDisabled = busy || !selectedTask || selectedTaskIsUnreleasedRealMode || configBlocksStart || l2BlocksStart || l3BlocksStart" in workbench_source
    assert "未发布，禁止启动" in workbench_source
    assert "function isReleasedRealDxmMutationTask" in workbench_source
    assert "function isUnreleasedRealDxmMutationTask" in workbench_source
    assert "当前按钮策略：L2 非 passed 或 L3 blocked 时保持阻断；single_save 仍需后端人工批准；claim_only/batch_save 当前未发布。" in workbench_source
    assert "unreleasedRealModeCopy" in qa_source
    assert "unreleasedRealModeButtonDisabled" in qa_source
    assert "async function ensureUnreleasedRealModeTask()" in qa_source
    assert "const unreleasedRealModeTask = reportOnlyFinal || qaExpectedReady ? null : await ensureUnreleasedRealModeTask();" in qa_source
    assert "mode: 'claim_only'" in qa_source
    assert "QA unreleased claim_only task" in qa_source
    assert "async function clickTaskByName(name)" in qa_source
    assert "await clickTaskByName(unreleasedRealModeTask.name)" in qa_source
    assert "await clickText(unreleasedRealModeTask.name)" not in qa_source
    assert "unreleasedRealModeTaskSelected:" in qa_source
    assert "unreleasedRealModeStartButtonDisabled" in qa_source
    assert "qaExpectedReady || unreleasedRealModeStartButtonDisabled" in qa_source
    assert "taskStartDisabled && taskText.includes(text.unreleasedRealModeButtonDisabled)" in qa_source
    assert "\\u0063\\u006c\\u0061\\u0069\\u006d\\u005f\\u006f\\u006e\\u006c\\u0079/\\u0062\\u0061\\u0074\\u0063\\u0068\\u005f\\u0073\\u0061\\u0076\\u0065 \\u5f53\\u524d\\u672a\\u53d1\\u5e03" in qa_source
    assert "\\u672a\\u53d1\\u5e03\\uff0c\\u7981\\u6b62\\u542f\\u52a8" in qa_source
    assert "\\u4ec5\\u53d7\\u63a7 single_save" in qa_source
    assert "oldSaveOnly" not in qa_source
    assert "\\u53ea\\u4fdd\\u5b58\\u4e0d\\u53d1\\u5e03" not in no_old_action_copy_section
    assert "oldWaitSave" in no_old_action_copy_section
    assert "oldVisibleBrowser" in no_old_action_copy_section
    assert "oldAutomation" in no_old_action_copy_section
    assert "SAVE_ONLY" in no_old_action_copy_section


def test_task_center_surfaces_real_mode_release_readiness_without_releasing_modes():
    workspace_source = WORKSPACE_TS.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    styles_source = (REPO_ROOT / "app" / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    task_center_section = workbench_source[workbench_source.index("export function TaskCenter"):workbench_source.index("export function ExecutionConsole")]

    assert "real_mode_release_plan?: RealModeReleasePlan" in workspace_source
    assert "workspace?.real_mode_release_plan" in workspace_source
    assert "buildRealModeReleasePlan" in workspace_source
    assert "normalizeRealModeReleasePlan" in workspace_source
    assert "normalizeReadinessChecklistItem" in workspace_source
    assert "readiness_checklist" in workspace_source
    assert "RealModeReleasePlanPanel" in task_center_section
    assert "claim_only / batch_save 放行准备" in workbench_source
    assert "claim_only 当前未发布" in workbench_source
    assert "batch_save 当前未发布" in workbench_source
    assert "不能复用 single_save 证据" in workbench_source
    assert "批量大小上限" in workbench_source
    assert "回滚/人工接管" in workbench_source
    assert "batch_save 不进入 runner" in workbench_source
    assert "仅受控 single_save" in workbench_source
    assert "humanReadinessCheckLabel" in workbench_source
    assert "humanReleaseBlocker" in workbench_source
    assert "独立 L2/L3 证据链" in workbench_source
    assert "目标草稿领取归属证明" in workbench_source
    assert "逐商品保存结果与 published=false" in workbench_source
    assert "RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save'])" in (REPO_ROOT / "app" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "real-mode-release-panel" in styles_source
    assert "real-mode-release-panel__grid" in styles_source
    assert "realModeReleasePlanVisible" in qa_source


def test_frontend_does_not_expose_developer_fallback_copy():
    workspace_source = WORKSPACE_TS.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "前端使用工作台 fallback 数据" not in workspace_source
    assert "前端使用工作台默认数据" in workspace_source
    assert "section.source === 'legacy' ? '旧字段兼容' : 'fallback'" not in workbench_source
    assert "默认规则" in workbench_source
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    assert "fallbackCopyPatterns" in qa_source
    assert "fallback \\u6570\\u636e" in qa_source
    assert "\\u6765\\u6e90\\uff1afallback" in qa_source


def test_frontend_surfaces_runtime_status_and_log_filters():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")

    assert "/api/runtime/status?frontend_url=" in app_source
    assert "encodeURIComponent(window.location.origin)" in app_source
    assert "runtimeStatus={runtimeStatus}" in app_source
    assert "`后端：${runtimeStatus.backend.status === 'ok' ? '运行中' : '异常'}`" in safety_bar
    assert "`前端：${runtimeStatus.frontend.status === 'ok' ? '运行中' : '异常'}`" in safety_bar
    assert "runtimeEndpointLine" in safety_bar
    assert "后端端口" in safety_bar
    assert "前端端口" in safety_bar
    assert "safety-bar__runtime-endpoints" in safety_bar
    assert "自动浏览器" in safety_bar
    assert "DXM 登录" in safety_bar
    assert "safety-bar__meta-details" in safety_bar
    assert "primaryStatus" in safety_bar
    assert "primaryActionLabel" in safety_bar
    assert "onShowTasks" in safety_bar
    assert "runtimeLogLevel" in app_source
    assert "runtimeLogQuery" in app_source
    assert "RuntimeLogSource" in app_source
    assert "['backend', 'frontend', 'launcher', 'npm', 'task', 'agent']" in app_source
    assert "source === 'task' && selectedTask?.id" in app_source
    assert "params.set('task_id', String(selectedTask.id))" in app_source
    assert "runtimeLogLevel !== 'all'" in app_source
    assert "params.set('q', runtimeLogQuery.trim())" in app_source
    assert "RuntimeLogLine" in workbench_source
    assert "task: '任务'" in workbench_source
    assert "agent: '浏览器 Agent'" in workbench_source
    assert "级别" in workbench_source
    assert "搜索" in workbench_source
    assert "item.tags.slice(0, 3)" in workbench_source


def test_frontend_first_screen_names_dxm_automation_delivery():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    shell = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "DXM 自动化工作台" in source
    assert "真实写入只允许在 L2 passed 和 L3 人工批准后由受控 runner 执行" in source
    assert "aria-label=\"验收结论\"" in source
    assert "自动化工作台</strong><b>可交付" in source
    assert "真实 DXM 写入</strong><b>{realWriteReady ? '受控 READY' : 'L3 受控'}" in source
    assert "当前范围' : '下一步'" in source
    assert "single_save READY" in source
    assert "单商品金丝雀" in source
    assert "真实写入门禁未通过" in safety_bar
    assert "配置 / 任务 / 真实浏览器执行" in shell
    assert "\\u0044\\u0058\\u004d \\u81ea\\u52a8\\u5316\\u5de5\\u4f5c\\u53f0" in qa_source
    assert "\\u73b0\\u5728\\u53ea\\u505a\\u8fd9\\u4e00\\u6b65" in qa_source
    assert "\\u67e5\\u770b\\u5b8c\\u6574 9 \\u6b65\\u6d41\\u7a0b" in qa_source
    assert "半托管保存交付工作台" not in source
    assert "保存核验 / 证据复盘" not in shell


def test_mock_workspace_uses_dry_run_demo_language_not_real_single_save():
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    mock_section = workspace_source[workspace_source.index("export function buildMockWorkspace"):workspace_source.index("function buildRegressionGates")]

    assert "name: '本地演示保存核验批次 #19'" in mock_section
    assert "mode: 'dry_run'" in mock_section
    assert "演示截图占位" in mock_section
    assert "本地演示保存核验报告 #19" in mock_section
    assert "buildRegressionGates(null, evidenceGradeValue, [])" in mock_section
    assert "file:///mock/l2.html" not in mock_section
    assert "mode: 'single_save'" not in mock_section
    assert "保存动作截图" not in mock_section


def test_frontend_labels_mock_l2_as_evidence_not_passed():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")

    assert "mock_passed: '离线证据'" in source
    assert "mock_passed: '离线证据'" in safety_bar
    assert "仅有离线/mock L2 证据；不满足真实页面 L2 放行条件。" in workspace_source
    assert "已有离线/mock L2 证据；真实页面仍需批准执行。" not in workspace_source
