from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
APP_TSX = FRONTEND_SRC / "App.tsx"
API_TS = FRONTEND_SRC / "api.ts"
TYPES_TS = FRONTEND_SRC / "types.ts"
BATCH_EDIT_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchEditPage.tsx"
BATCH_RECORDS_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchRecordsPage.tsx"


def test_app_routes_new_batches_to_snapshot_flow_and_keeps_legacy_records_readonly():
    source = APP_TSX.read_text(encoding="utf-8")
    assert not BATCH_EDIT_PAGE_TSX.exists()
    assert "<BatchEditPage" not in source
    assert "draft_edit_save: 'draft_selection'" in source
    assert "<BatchSavePlaceholderPage" in source
    assert "<BatchRecordsPage" in source
    assert "showBatchRecords(batchId)" in source


def test_low_noise_pages_hide_legacy_single_save_safety_bar():
    source = APP_TSX.read_text(encoding="utf-8")
    guard = source[source.index("const showGlobalSafetyStatus"):source.index("const setWorkbenchSection")]
    render = source[source.index("{showGlobalSafetyStatus && ("):source.index('<div className="operation-toast-stack"')]

    for section in ["home", "draft_edit_save", "task_history"]:
        assert f"currentSection !== '{section}'" in guard
    assert "<SafetyStatusBar" in render


def test_active_frontend_contains_no_legacy_batch_mutation_route():
    import re
    for path in FRONTEND_SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"(?:postJson|patchJson|deleteJson)[^\n]*['\"`](/api/edit-batches)", source), path
    snapshot = (FRONTEND_SRC / "components/workbench/BatchSavePlaceholderPage.tsx").read_text(encoding="utf-8")
    assert "plan.path !== 'B'" in snapshot
    assert "postJson<PlanSnapshot>('/api/plan-snapshots'" in snapshot


def test_snapshot_preserves_reader_scope_and_order_before_approval():
    source = (FRONTEND_SRC / "components/workbench/BatchSavePlaceholderPage.tsx").read_text(encoding="utf-8")
    assert "product_ids: taskInput.input.productIds" in source
    assert "session_ref: taskInput.sessionRef" in source
    assert "expected_snapshot_hash: expectedSnapshotHash" in source
    assert "frozen.task_id === createdTask.id" in source
    assert "frozen.path === 'B'" in source


def test_frozen_product_approval_requires_explicit_execution_release():
    source = (FRONTEND_SRC / "components/workbench/BatchSavePlaceholderPage.tsx").read_text(encoding="utf-8")
    assert "frozen?.approval_context.runner_released === true" in source
    assert "执行能力尚未放行" in source
    assert "MIN_DRAFT_SELECTION" in source
    assert "MAX_DRAFT_SELECTION" in source


def test_unknown_batch_errors_do_not_echo_raw_backend_messages():
    records_source = BATCH_RECORDS_PAGE_TSX.read_text(encoding="utf-8")
    records_error = records_source[records_source.index("function humanRecordsError"):records_source.index("function humanBatchStatus")]
    assert "${message ?" not in records_error
    assert "postJson" not in records_source


def test_batch_records_loads_real_summaries_and_details_without_fake_success():
    source = BATCH_RECORDS_PAGE_TSX.read_text(encoding="utf-8")

    assert "getJson<EditBatchSummary[]>('/api/edit-batches')" in source
    assert "getJson<EditBatchDetail>(`/api/edit-batches/${batchId}`)" in source
    assert "旧批次不能批准或启动" in source
    assert "结果不确定待对账" in source
    assert "localStorage" not in source
    assert "mock" not in source.lower()
    assert "status === 'success'" not in source


def test_frontend_batch_types_preserve_backend_immutable_contract_fields():
    source = TYPES_TS.read_text(encoding="utf-8")

    for type_name in [
        "DraftBoxScopeSnapshot",
        "DraftBoxScopeItem",
        "EditBatchSummary",
        "EditBatchDetail",
        "EditBatchItem",
    ]:
        assert f"export type {type_name}" in source
    for field in ["scope_snapshot_id", "template_id", "item_snapshot", "publish_allowed"]:
        assert field in source
    for internal_digest in ["scope_snapshot_digest", "template_snapshot_digest", "policy_digest"]:
        assert internal_digest not in source


def test_frontend_api_extracts_fastapi_nested_detail_message_through_safety_filter():
    source = API_TS.read_text(encoding="utf-8")
    response_error = source[source.index("async function responseError(") : source.index("function safeApiErrorMessage")]

    assert "payload?.detail?.message" in response_error
    assert "safeApiErrorMessage(payload.detail.message" in response_error
