from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
APP_TSX = FRONTEND_SRC / "App.tsx"
APP_SHELL_TSX = FRONTEND_SRC / "components" / "AppShell.tsx"
WORKSPACE_TS = FRONTEND_SRC / "workspace.ts"
TYPES_TS = FRONTEND_SRC / "types.ts"
WORKBENCH_MODULES_TSX = FRONTEND_SRC / "components" / "WorkbenchModules.tsx"
HOME_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "HomePage.tsx"
HELP_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "HelpPage.tsx"
RESULTS_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "ResultsPage.tsx"
PRODUCT_TASKS_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "ProductTasksPage.tsx"
SNAPSHOT_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchSavePlaceholderPage.tsx"
DXM_ACCESS_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "DxmAccessPage.tsx"
QA_BROWSER_CHECK = REPO_ROOT / "scripts" / "qa-browser-check.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def active_frontend_source() -> str:
    return "\n".join(read(path) for path in FRONTEND_SRC.rglob("*") if path.suffix in {".ts", ".tsx"})


def test_removed_claim_pages_and_legacy_product_panels_do_not_ship():
    removed = [
        FRONTEND_SRC / "components" / "workbench" / "AcquisitionClaimPage.tsx",
        FRONTEND_SRC / "components" / "workbench" / "DraftEditSavePage.tsx",
        FRONTEND_SRC / "components" / "workbench" / "ProductTaskPanels.tsx",
        FRONTEND_SRC / "sourceUrl.ts",
    ]
    assert all(not path.exists() for path in removed)


def test_active_frontend_has_no_removed_claim_flow_contract():
    source = active_frontend_source()
    for forbidden in (
        "claim_only",
        "data_acquisition",
        "acquisition_claim",
        "twoStageAcceptance",
        "待认领",
        "认领入箱",
        "双目标",
        "第二段",
    ):
        assert forbidden not in source


def test_app_releases_current_controlled_save_modes_without_claim():
    source = read(APP_TSX)
    assert "const RELEASED_REAL_DXM_MUTATION_MODES = new Set(['single_save', 'batch_draft_save'])" in source
    assert "mode: 'probe' | 'single_save'" in read(TYPES_TS)
    assert "request.mode === 'single_save' && products.length !== 1" in source
    assert "taskToStart.mode === 'batch_draft_save'" in source
    assert "batch_draft_save 不能使用旧 manual-approval/start" in source
    assert "'/api/tasks'" in source
    assert "source: 'user_created_real_task'" in source


def test_current_batch_workbench_keeps_reader_selection_and_frozen_plan_models():
    app = read(APP_TSX)
    shell = read(APP_SHELL_TSX)
    types = read(TYPES_TS)
    assert "case 'draft_selection':" in app
    assert "<DraftSelectionPage" in app
    assert "draft_selection: '采集箱选品'" in shell
    assert "export type LocalPlanTemplate" in types
    assert "export type PlanSnapshot" in types
    assert "mode: 'batch_draft_save'" in types


def test_navigation_exposes_product_box_batch_edit_as_the_primary_workflow():
    source = read(APP_SHELL_TSX)
    app = read(APP_TSX)
    assert "draft_edit_save: '商品箱批量编辑'" in source
    assert "受控编辑 · 只保存不发布" in source
    assert "draft_edit_save: 'draft_selection'" in app
    assert "case 'product_tasks':" in app


def test_dxm_navigation_can_only_open_the_product_box():
    app = read(APP_TSX)
    modules = read(WORKBENCH_MODULES_TSX)
    access = read(DXM_ACCESS_PAGE_TSX)
    assert "async function navigateDxmTarget(target: 'draft_box')" in app
    assert "onNavigateDxmTarget: (target: 'draft_box') => void" in modules
    assert "onNavigateDxmTarget('draft_box')" in access
    assert "进入商品箱" in access


def test_readonly_precheck_targets_only_the_product_box():
    modules = read(WORKBENCH_MODULES_TSX)
    workspace = read(WORKSPACE_TS)
    assert "保存前安全检查只读取店小秘商品箱，不修改、不保存、不发布" in modules
    assert "targets : ['draft_box']" not in workspace
    assert "{ id: 'draft_box'" in workspace
    assert "真实店小秘商品箱只读检查；不修改、不保存、不发布。" in workspace


def test_snapshot_freezes_exact_scope_before_one_atomic_approval():
    source = read(SNAPSHOT_PAGE_TSX)
    assert "expected_snapshot_hash: expectedSnapshotHash" in source
    assert "product_ids: taskInput.input.productIds" in source
    assert "冻结为 draft 任务（不启动）" in source
    assert "postJson(request.path, request.body)" in source
    assert "approvalAttemptRef.current = attempt" in source


def test_product_flow_does_not_expose_single_save_as_a_batch_prerequisite():
    app = read(APP_TSX)
    assert "onCreateSingleSave={" not in app
    assert "<DraftSelectionPage" in app
    assert "<BatchSavePlaceholderPage" in app
    assert "draft_edit_save: 'draft_selection'" in app


def test_batch_approval_result_loss_only_polls_and_does_not_redispatch():
    source = read(SNAPSHOT_PAGE_TSX)
    approval = read(FRONTEND_SRC / "batchApproval.ts")
    assert "系统只会继续 GET 轮询，不会重复 POST" in source
    assert "approvalAttemptRef.current" in source
    assert "method: 'GET'" in approval
    assert "unknown_stop_no_retry" in read(WORKSPACE_TS)


def test_results_do_not_fabricate_capability_or_save_receipts():
    source = read(RESULTS_PAGE_TSX)
    assert "prod-001" not in source
    assert "Mock item results" not in source
    assert "缺失数据保持未证明" in source
    assert "不能复用 single_save 证据" in read(WORKSPACE_TS)


def test_single_save_task_requires_config_precheck_and_current_approver():
    source = read(PRODUCT_TASKS_PAGE_TSX)
    assert "currentTask.mode === 'single_save'" in source
    assert "需要保存前检查" in source
    assert "人工确认只保存不发布" in source
    assert "填写批准人后系统会直接批准并启动" in source
    assert "批准并启动只保存" in source


def test_home_and_help_start_from_existing_product_box_scope():
    home = read(HOME_PAGE_TSX)
    help_page = read(HELP_PAGE_TSX)
    assert "选择至少三件真实草稿" in home
    assert "查看历史批次草稿" in home
    assert "直接编辑商品箱现有商品" in help_page
    assert "整批只批准一次，严格串行" in help_page
    assert "结果不确定立即停止并转人工对账" in help_page


def test_results_expose_single_stage_acceptance_and_unpublished_proof():
    source = read(RESULTS_PAGE_TSX)
    types = read(TYPES_TS)
    workspace = read(WORKSPACE_TS)
    assert "SingleSaveAcceptanceCard" in source
    assert "单阶段只保存" in source
    assert "未发布证明" in source
    assert "current_single_save_ready" in types
    assert "single_save_acceptance_matches_expected" in types
    assert "schema: 'dxm_single_save_acceptance.v1'" in workspace


def test_workspace_fallback_keeps_product_box_identity_and_approval_evidence():
    source = read(WORKSPACE_TS)
    assert "product_box_snapshot_valid: false" in source
    assert "single_save_target_bound: false" in source
    assert "manual_approval_consumed: false" in source
    assert "missing_product_box_snapshot" in read(RESULTS_PAGE_TSX)


def test_browser_qa_never_fabricates_or_executes_the_removed_stage():
    source = read(QA_BROWSER_CHECK)
    for forbidden in (
        "claim_only",
        "data_acquisition",
        "claim-product",
        "claim-requests",
        "待认领",
    ):
        assert forbidden not in source
    assert "current_single_save_ready" in source
    assert "single_save_acceptance_matches_expected" in source


def test_frontend_sources_are_split_into_current_operator_pages():
    for path in (
        HOME_PAGE_TSX,
        HELP_PAGE_TSX,
        RESULTS_PAGE_TSX,
        PRODUCT_TASKS_PAGE_TSX,
        SNAPSHOT_PAGE_TSX,
        DXM_ACCESS_PAGE_TSX,
    ):
        assert path.is_file()
        assert read(path).strip()
