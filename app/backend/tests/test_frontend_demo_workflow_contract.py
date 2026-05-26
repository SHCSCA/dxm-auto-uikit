from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
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
    assert "本地 dry_run；真实 single_save 当前 BLOCKED" in source


def test_browser_qa_covers_demo_batch_startable_user_path():
    source = QA_BROWSER_CHECK.read_text(encoding="utf-8")
    ensure_section = source[source.index("async function ensureRealMutationTask"):source.index("async function screenshot")]

    assert "demoBatchCanStartLocally" in source
    assert "demoBatchButton" in source
    assert "localDemoStart" in source
    assert "realMutationTask" in source
    assert "demoCreatedTask" in source
    assert "newTasks.find(item => item.id > maxTaskIdBeforeDemo" in source
    assert "fetchJson('/api/stores')" in ensure_section
    assert "fetchJson('/api/products')" in ensure_section
    assert "existingStores.find(store => store?.name === 'Dang Kang')" in ensure_section
    assert "/api/delivery/workspace" not in ensure_section


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
    assert "L3 后置证据" in source
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
    assert "不启动真实 claim_only/single_save/batch_save" in task_center_section
    assert "L3 保持锁定，禁止启动" in task_center_section
    assert "当前真实写入未放行时" in evidence_timeline_section
    assert "0 条是预期阻断" in evidence_timeline_section
    assert "只有 L3 金丝雀完成后才生成可验收证据等级" in evidence_timeline_section


def test_task_center_only_uses_demo_ready_copy_for_dry_run_tasks():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    task_center_section = source[source.index("export function TaskCenter"):source.index("export function ExecutionConsole")]

    assert "selectedTask?.mode === 'dry_run'" in task_center_section
    assert "selectedTaskIsDryRun && selectedTask?.status === 'draft' && <span>本地演示批次已可用于验收门禁" in task_center_section
    assert "{selectedTask?.status === 'draft' && <span>本地演示批次已可用于验收门禁" not in task_center_section
    assert "当前真实任务保持阻断，可创建本地 dry_run 演示批次完成工作台验收。" in task_center_section


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


def test_frontend_first_screen_names_local_safety_diagnostic_delivery():
    source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    shell = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    safety_bar = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")
    qa_source = QA_BROWSER_CHECK.read_text(encoding="utf-8")

    assert "本地安全诊断工作台" in source
    assert "本地 PASS 仅代表工作台自检通过，真实 DXM 写入仍 BLOCKED" in source
    assert "本地工作台可交付，真实写入预期 BLOCKED" in safety_bar
    assert "真实写入门禁未通过" in safety_bar
    assert "本地验收 / L2 只读诊断 / L3 阻断复核" in shell
    assert "\\u672c\\u5730\\u5b89\\u5168\\u8bca\\u65ad\\u5de5\\u4f5c\\u53f0" in qa_source
    assert "\\u672c\\u5730\\u5de5\\u4f5c\\u53f0\\u53ef\\u4ea4\\u4ed8" in qa_source
    assert "半托管保存交付工作台" not in source
    assert "保存核验 / 证据复盘" not in shell


def test_mock_workspace_uses_dry_run_demo_language_not_real_single_save():
    workspace_source = (REPO_ROOT / "app" / "frontend" / "src" / "workspace.ts").read_text(encoding="utf-8")
    mock_section = workspace_source[workspace_source.index("export function buildMockWorkspace"):workspace_source.index("function buildRegressionGates")]

    assert "name: '本地演示保存核验批次 #19'" in mock_section
    assert "mode: 'dry_run'" in mock_section
    assert "演示截图占位" in mock_section
    assert "本地演示保存核验报告 #19" in mock_section
    assert "mode: 'single_save'" not in mock_section
    assert "保存动作截图" not in mock_section
