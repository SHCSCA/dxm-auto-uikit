from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
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
    assert "本地 dry_run / 真实 single_save" in source


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
