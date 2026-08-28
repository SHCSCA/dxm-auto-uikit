from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
APP_TSX = FRONTEND_SRC / "App.tsx"
TYPES_TS = FRONTEND_SRC / "types.ts"
TEMPLATE_CENTER_TSX = FRONTEND_SRC / "components" / "workbench" / "TemplateCenterPage.tsx"
LOCAL_PLAN_TSX = FRONTEND_SRC / "components" / "workbench" / "LocalPlanWorkspace.tsx"
SNAPSHOT_TSX = FRONTEND_SRC / "components" / "workbench" / "BatchSavePlaceholderPage.tsx"
BATCH_APPROVAL_TS = FRONTEND_SRC / "batchApproval.ts"
SCHEMA_VALUE_EDITOR_TS = FRONTEND_SRC / "schemaValueEditor.ts"
DRAFT_SELECTION_TSX = FRONTEND_SRC / "components" / "workbench" / "DraftSelectionPage.tsx"
CATEGORY_CASCADE_TSX = FRONTEND_SRC / "components" / "workbench" / "CategoryCascadePicker.tsx"
APP_SHELL_TSX = FRONTEND_SRC / "components" / "AppShell.tsx"
API_TS = FRONTEND_SRC / "api.ts"


def test_e2_ui_keeps_local_plan_and_dxm_ref_models_visibly_separate():
    types = TYPES_TS.read_text(encoding="utf-8")
    template_center = TEMPLATE_CENTER_TSX.read_text(encoding="utf-8")
    workspace = LOCAL_PLAN_TSX.read_text(encoding="utf-8")
    app = APP_TSX.read_text(encoding="utf-8")

    assert "model: 'local_plan_template'" in types
    assert "model: 'dxm_template_ref'" in types
    assert "'e2_plan'" in template_center
    assert '<span className="eyebrow">普货方案</span>' in template_center
    assert "<LocalPlanWorkspace" in template_center
    assert "店小秘只读同步" in workspace
    assert "选择后立即带入模板值；保存方案不会修改店小秘中的原模板。" in workspace
    assert "representative_product_ids" not in workspace
    assert "当前商品：" not in workspace
    assert "single_target_category.v2" in workspace
    assert "/api/local-plan-templates" in workspace
    assert "deleteJson<LocalPlanTemplate>" in workspace
    assert "删除方案" in workspace
    assert "postJson<DxmTemplateRefSyncResult>('/api/dxm-template-refs/sync'" in workspace
    assert "category_schemas" in types
    assert "result.category_schemas" in workspace
    assert 'className="e2-schema-field"' in workspace
    assert "reviewed:${fieldKey}" not in workspace
    assert "definition.ui_binding" in workspace
    schema_editor = SCHEMA_VALUE_EDITOR_TS.read_text(encoding="utf-8")
    assert "names.zh" in schema_editor
    assert "resolveSchemaChoiceOptions" in workspace
    assert "price_policy?:" in types
    assert "sku_prices_within_range: true" in types
    assert "sku_cargo_not_above_sale: true" in types
    assert "title 来源策略" not in workspace
    assert "'auto' | 'current' | 'template' | 'fill' | 'fixed'" in workspace
    assert "沿用每件商品原值" in workspace
    assert "最终值来源" not in workspace
    assert "留空时沿用每件商品的原标题" in workspace
    assert "同步${label}选项" in workspace
    assert "representative_product_ids" not in workspace
    assert "主编辑页 + 半托管" in workspace
    assert "PLAN_PATH_EXECUTION_NOT_RELEASED" in (
        REPO_ROOT / "app" / "backend" / "src" / "batch_edit" / "plan_snapshot_compiler.py"
    ).read_text(encoding="utf-8")
    assert "fixedFieldValues" in workspace
    assert "field_values: fixedFieldValues" in workspace
    assert "使用新版编辑器" in workspace
    assert "根据 PC 端描述一键生成" in workspace
    assert "普货方案" in template_center
    assert "新建、查看、改版本、归档" in template_center
    assert "<textarea" not in workspace
    assert "补差规则 JSON" not in workspace
    assert "中文字段映射 JSON" not in workspace
    assert "records:" not in workspace
    assert "patchJson" not in workspace
    assert "localStorage" not in workspace
    assert "loadOrFallback<LocalPlanTemplate[]>('/api/local-plan-templates'" in app
    assert "loadOrFallback<DxmTemplateRef[]>('/api/dxm-template-refs'" in app


def test_local_plan_uses_explicit_three_level_category_scope_and_fail_closed_fields():
    workspace = LOCAL_PLAN_TSX.read_text(encoding="utf-8")
    cascade = CATEGORY_CASCADE_TSX.read_text(encoding="utf-8")
    shell = APP_SHELL_TSX.read_text(encoding="utf-8")

    assert "<CategoryCascadePicker" in workspace
    assert "读取类目字段与模板" in workspace
    assert "/api/dxm/category/get?category_id=" in workspace
    assert "不能生成空的分类规则" in workspace
    assert "一个普货方案必须且只能选择一个末级类目" in workspace
    assert "方案类目（仅 1 个）" in workspace
    assert "setCategoryRecords([record])" in workspace
    assert "/api/dxm/category/children?" in cascade
    assert "/api/dxm/category/search?" in cascade
    assert "适用类目三级联动" in cascade
    assert "中文类目名称待读取" in cascade
    assert "frontendPackage.version" in shell
    assert "NavigationGlyph" in shell
    api = API_TS.read_text(encoding="utf-8")
    assert "readOnlyPost = fallback.includes('/api/dxm-template-refs/sync')" in api
    assert "店小秘类目字段与模板读取失败" in api


def test_e2_ui_carries_per_item_category_and_freezes_before_atomic_batch_approval():
    draft_selection = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    snapshot = SNAPSHOT_TSX.read_text(encoding="utf-8")
    approval = BATCH_APPROVAL_TS.read_text(encoding="utf-8")

    assert "products: selectedIds" in draft_selection
    assert "e2LocalPlans?.filter((plan) => plan.is_active)" in draft_selection
    assert "localPlans={localPlans}" in APP_TSX.read_text(encoding="utf-8")
    assert "/api/plan-snapshots/preview" in snapshot
    assert "postJson<PlanSnapshot>('/api/plan-snapshots'" in snapshot
    assert "/api/plan-snapshots/${snapshot.id}/tasks" not in snapshot
    assert "/api/tasks/${snapshot.task_id}" in snapshot
    assert "idempotency_key:" in snapshot
    assert "/manual-approval" not in snapshot
    assert "postJson(request.path, request.body)" in snapshot
    assert "CONFIRM_DXM_SAVE_ONLY" in approval
    assert "`/api/tasks/${input.taskId}/approve-and-start`" in approval
    assert "method: 'GET'" in approval
    assert "`/api/tasks/${input.taskId}`" in approval
    assert "冻结为 draft 任务（不启动）" in snapshot
    assert "session_ref: taskInput.sessionRef" in snapshot
    assert "product_ids: taskInput.input.productIds" in snapshot
    assert "expected_snapshot_hash: expectedSnapshotHash" in snapshot
    assert "buildSnapshotRequest(preview.snapshot_hash)" in snapshot
    assert "category_schema" not in snapshot
    assert "expected_schema_hash" not in snapshot
    assert "current_values" not in snapshot
    assert "schemaTextByCategory" not in snapshot
    assert "<textarea" not in snapshot
    assert "canonicalSha256" not in snapshot
    assert "后端重新读取当前草稿、模板与类目字段" in snapshot
    assert "冻结前保持零写" in snapshot
    assert "发布始终不允许" in snapshot
    assert "发布允许" in snapshot


def test_legacy_manual_approval_start_path_routes_batch_tasks_to_atomic_review():
    app = APP_TSX.read_text(encoding="utf-8")

    batch_guard = app.index("if (taskToStart.mode === 'batch_draft_save')")
    legacy_manual_approval = app.index("/manual-approval", batch_guard)
    assert batch_guard < legacy_manual_approval
    assert "不能使用旧 manual-approval/start" in app[batch_guard:legacy_manual_approval]
    assert "setActiveSection('start_save')" in app[batch_guard:legacy_manual_approval]
