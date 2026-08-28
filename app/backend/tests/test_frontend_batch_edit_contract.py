from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
APP_TSX = FRONTEND_SRC / "App.tsx"
API_TS = FRONTEND_SRC / "api.ts"
TYPES_TS = FRONTEND_SRC / "types.ts"
BATCH_EDIT_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchEditPage.tsx"
BATCH_RECORDS_PAGE_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchRecordsPage.tsx"


def test_app_routes_live_batch_builder_and_batch_records_without_legacy_aliasing():
    source = APP_TSX.read_text(encoding="utf-8")

    assert "from './components/workbench/BatchEditPage'" in source
    assert "from './components/workbench/BatchRecordsPage'" in source
    assert "case 'task_history':" in source
    assert "<BatchRecordsPage" in source[source.index("case 'task_history':") :]
    assert "case 'draft_edit_save':" in source
    assert "<BatchEditPage" in source[source.index("case 'draft_edit_save':") :]
    assert "task_history: 'product_tasks'" not in source
    assert "onShowDraftEdit={() => setActiveSection('draft_edit_save')}" in source


def test_low_noise_pages_hide_legacy_single_save_safety_bar():
    source = APP_TSX.read_text(encoding="utf-8")
    guard = source[source.index("const showGlobalSafetyStatus"):source.index("const setWorkbenchSection")]
    render = source[source.index("{showGlobalSafetyStatus && ("):source.index('<div className="operation-toast-stack"')]

    for section in ["home", "draft_edit_save", "task_history"]:
        assert f"currentSection !== '{section}'" in guard
    assert "<SafetyStatusBar" in render


def test_batch_builder_uses_only_live_backend_scope_and_enabled_bundle_templates():
    source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")

    assert "postJson<DraftBoxScopeSnapshot>('/api/dxm/draft-box/scope-snapshots'" in source
    assert "postJson<EditBatchDetail>('/api/edit-batches'" in source
    assert "template.template_type === 'edit_batch_bundle'" in source
    assert "template.is_enabled" in source
    assert "scope_snapshot_id: scopeSnapshot.id" in source
    assert "template_id: selectedTemplate.id" in source
    assert "范围已冻结，等待一次批准" in source
    assert "CONFIRM_DXM_BATCH_SAVE_ONLY" in source
    assert "一次批准后严格串行处理，每件只保存、不发布" in source
    assert "检查模板中心" in source
    assert "localStorage" not in source
    assert "mock" not in source.lower()
    assert "/approve-and-start" in source
    # No publish API call or action handler (publishguard CSS class is a safe guard)
    import re as _re
    publish_action = _re.findall(
        r"(?<!publishguard-)publish(?![a-z])", source, _re.IGNORECASE
    )
    assert not publish_action, f"Unexpected publish references: {publish_action[:5]}"


def test_batch_builder_shows_frozen_order_and_live_scope_evidence():
    source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")

    for field in [
        "scopeSnapshot.items",
        "scopeSnapshot.store_identity",
        "scopeSnapshot.filter_state",
        "scopeSnapshot.sort_state",
        "scopeSnapshot.page_state",
        "scopeSnapshot.zero_write_proof",
    ]:
        assert field in source
    assert "item.ordinal" in source
    assert "item.title" in source
    assert "item.dxm_product_id" in source


def test_batch_builder_handles_nullable_page_facts_and_proves_all_zero_write_dimensions():
    page_source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")
    zero_write = page_source[page_source.index("function isZeroWriteProven"):]
    capture = page_source[page_source.index("async function captureLiveScope"):page_source.index("async function createDraftBatch")]

    for field in ["current_page", "page_size", "total_items"]:
        assert f"{field}: number | null" in types_source
    for field in ["navigation_attempted", "interactive_action_attempted", "mutation_dispatch_attempted"]:
        assert f"proof.{field} === false" in zero_write
    assert "if (!selectedTemplate)" not in capture
    assert "不影响只读范围读取" in page_source
    assert '<details className="batch-scope-review">' in page_source
    assert "第 {scopeSnapshot.page_state.current_page} 页" not in page_source


def test_unknown_batch_errors_do_not_echo_raw_backend_messages():
    page_source = BATCH_EDIT_PAGE_TSX.read_text(encoding="utf-8")
    records_source = BATCH_RECORDS_PAGE_TSX.read_text(encoding="utf-8")
    batch_error = page_source[page_source.index("function humanBatchError"):page_source.index("function templateVersion")]
    records_error = records_source[records_source.index("function humanRecordsError"):records_source.index("function humanBatchStatus")]

    assert "${message ?" not in batch_error
    assert "${message ?" not in records_error


def test_batch_records_loads_real_summaries_and_details_without_fake_success():
    source = BATCH_RECORDS_PAGE_TSX.read_text(encoding="utf-8")

    assert "getJson<EditBatchSummary[]>('/api/edit-batches')" in source
    assert "getJson<EditBatchDetail>(`/api/edit-batches/${batchId}`)" in source
    assert "范围和模板已冻结，尚未开始处理商品" in source
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
