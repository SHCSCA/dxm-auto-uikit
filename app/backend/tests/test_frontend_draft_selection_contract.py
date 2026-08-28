from pathlib import Path
import json


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
DRAFT_SELECTION_TSX = (
    FRONTEND_SRC / "components" / "workbench" / "DraftSelectionPage.tsx"
)
DXM_ACCESS_TSX = FRONTEND_SRC / "components" / "workbench" / "DxmAccessPage.tsx"
SAFETY_STATUS_BAR_TSX = FRONTEND_SRC / "components" / "SafetyStatusBar.tsx"
API_TS = FRONTEND_SRC / "api.ts"
DRAFT_STATE_TS = FRONTEND_SRC / "draftSelection.ts"
DXM_SHOP_CONTEXT_TSX = FRONTEND_SRC / "dxmShopContext.tsx"
APP_SHELL_TSX = FRONTEND_SRC / "components" / "AppShell.tsx"
LOCAL_PLAN_WORKSPACE_TSX = FRONTEND_SRC / "components" / "workbench" / "LocalPlanWorkspace.tsx"
STYLES_CSS = FRONTEND_SRC / "styles.css"
PACKAGE_JSON = REPO_ROOT / "app" / "frontend" / "package.json"


def test_draft_selection_uses_only_real_reader_endpoints_and_source_attestation() -> None:
    source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    shop_context = DXM_SHOP_CONTEXT_TSX.read_text(encoding="utf-8")

    assert "useDxmShop" in source
    assert "/api/dxm/draft-reader/shops" in shop_context
    assert "/api/dxm/draft-reader/products?" in source
    assert "assertRealDraftShopsResponse" in source
    assert "assertRealDraftPageResponse" in source
    assert "invalidateDraftSelectionState" in source
    assert "'page_remount'" in source
    assert "'reader_failure'" in source
    assert "'browser_session_change'" in source
    assert "getJsonOrDefault" not in source
    assert "postJson" not in source
    assert "localStorage" not in source


def test_draft_selection_builds_reviewable_input_without_starting_a_runner() -> None:
    page_source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    state_source = DRAFT_STATE_TS.read_text(encoding="utf-8")

    assert "MIN_DRAFT_SELECTION = 1" in state_source
    assert "shopId" in state_source
    assert "productIds" in state_source
    assert "planId" in state_source
    assert "buildConfirmedDraftTaskInput" in page_source
    assert "确认任务输入（不启动）" in page_source
    assert "/start" not in page_source
    assert "/approve" not in page_source
    assert "resetSelectionForShopChange" in page_source


def test_batch_save_ui_uses_the_same_one_to_one_hundred_item_contract() -> None:
    batch_source = (
        FRONTEND_SRC / "components" / "workbench" / "BatchSavePlaceholderPage.tsx"
    ).read_text(encoding="utf-8")

    assert "MIN_DRAFT_SELECTION" in batch_source
    assert "MAX_DRAFT_SELECTION" in batch_source
    assert "当前批量快照需绑定" in batch_source
    assert "plan_item_count_invalid" in batch_source
    assert "readonly dxm template reference has drifted" in batch_source
    assert "保存为新版本后重新预览" in batch_source


def test_draft_selection_target_category_cascade_feeds_snapshot_request() -> None:
    page_source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    state_source = DRAFT_STATE_TS.read_text(encoding="utf-8")
    batch_source = (
        FRONTEND_SRC / "components" / "workbench" / "BatchSavePlaceholderPage.tsx"
    ).read_text(encoding="utf-8")

    assert "/api/dxm/category/children?" in page_source
    assert "/api/dxm/category/search?" in page_source
    assert "targetCategoryId" in state_source
    assert "targetCategoryName" in state_source
    assert "targetCategoryMatch" in state_source
    assert "target_category_id" in batch_source
    assert "target_category_name" in batch_source
    assert "target_category_match" in batch_source
    assert "统一目标类目" in page_source
    assert "/start" not in page_source


def test_primary_navigation_and_shell_keep_frozen_prototype_geometry() -> None:
    shell_source = APP_SHELL_TSX.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    mobile_start = styles.index("@media (max-width: 860px)", styles.index(".draft-selection-toolbar"))
    mobile_styles = styles[mobile_start : styles.index(".batch-save-placeholder__grid", mobile_start)]

    for label in (
        "工作台",
        "连接店小秘",
        "采集箱选品",
        "普货方案",
        "开始批量保存",
        "保存结果",
        "设置",
    ):
        assert f"label: '{label}'" in shell_source
    assert 'className="nav-item__icon"' in shell_source
    assert "NavigationGlyph" in shell_source
    assert ".nav-item__icon" in styles
    assert "grid-template-columns: 240px minmax(0, 1fr)" in styles
    assert "grid-template-rows: 56px minmax(0, 1fr)" in styles
    assert "--brand: #4f46e5" in styles
    assert "--radius: 16px" in styles
    assert "@media (max-width: 1100px)" in styles
    assert "@media (max-width: 860px)" in styles
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_styles
    assert ".sidebar {\n    display: none;\n  }" in mobile_styles
    assert "width: 64px;" not in mobile_styles
    assert "theme-${theme}" in shell_source
    assert ".theme-dark" in styles


def test_workbench_shell_keeps_sidebar_and_content_scroll_regions_separate() -> None:
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert ".app-shell {" in styles
    assert "height: 100vh;" in styles
    assert "overflow: hidden;" in styles
    assert ".sidebar {" in styles
    assert "overflow-y: auto;" in styles
    assert ".workspace-body {" in styles
    assert "overflow-y: auto;" in styles
    assert ".draft-selection-list {" in styles
    assert "scrollbar-gutter: stable;" in styles
    assert ".draft-selection-pagination {" in styles
    assert "position: sticky;" in styles


def test_category_and_template_controls_have_operator_facing_fallbacks_and_pagination() -> None:
    page_source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    template_source = (
        FRONTEND_SRC / "components" / "workbench" / "DxmTemplateLibraryPage.tsx"
    ).read_text(encoding="utf-8")
    batch_source = (
        FRONTEND_SRC / "components" / "workbench" / "BatchSavePlaceholderPage.tsx"
    ).read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "mergeCategorySearchLevels" in page_source
    assert "搜索结果会自动补全可选的三级路径" in page_source
    assert "draft-selection-target__cascade" in styles
    assert "待复核输入" in page_source
    assert "这三项决定本次批量保存" in page_source
    assert "本地普货方案" in page_source
    assert "类目编号" in page_source
    assert "PAGE_SIZES = [20, 50, 100, 200]" in page_source
    assert "TEMPLATE_PAGE_SIZES" in template_source
    assert "dxm-template-pagination" in template_source
    assert "/api/dxm-template-refs/sync-shop" in template_source
    assert "同步编号" in template_source
    assert "dxm-template-list-card" in styles
    assert "普货方案" in batch_source
    assert "humanBatchSaveError" in batch_source


def test_dxm_access_layout_keeps_login_and_status_cards_in_separate_columns() -> None:
    access_source = DXM_ACCESS_TSX.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert 'className="module-card dxm-access-card"' in access_source
    assert 'className="module-card span-2 dxm-access-card"' not in access_source
    assert ".dxm-access-layout" in styles
    assert "grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.55fr);" in styles


def test_dxm_template_sync_exposes_busy_retry_and_explicit_shop_read_state() -> None:
    template_source = (
        FRONTEND_SRC / "components" / "workbench" / "DxmTemplateLibraryPage.tsx"
    ).read_text(encoding="utf-8")

    assert "withDxmSessionBusyRetry" in template_source
    assert "shopsLoading" in template_source
    assert "shopReadError" in template_source
    assert "重新读取店铺" in template_source
    assert "正在读取店铺" in template_source
    assert "店小秘读取已完成，但返回 0 条模板记录" in template_source
    assert "当前店铺没有已同步模板" in template_source
    assert "暂无店铺，请先登录" not in template_source


def test_template_sync_does_not_show_empty_while_reading_or_commit_stale_refresh() -> None:
    template_source = (
        FRONTEND_SRC / "components" / "workbench" / "DxmTemplateLibraryPage.tsx"
    ).read_text(encoding="utf-8")
    app_source = (FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")

    assert "dxm-template-library__sync-status" in template_source
    assert "完成前不把当前列表判定为“无模板”" in template_source
    assert "workspaceRefreshGenerationRef" in app_source
    assert "if (refreshGeneration !== workspaceRefreshGenerationRef.current)" in app_source


def test_reader_selection_retries_busy_sessions_and_offers_explicit_refresh() -> None:
    draft_source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")
    api_source = API_TS.read_text(encoding="utf-8")

    assert "withDxmSessionBusyRetry" in api_source
    assert "withDxmSessionBusyRetry" in draft_source
    assert "真实草稿读取已停止" in draft_source
    assert "重新读取草稿" in draft_source


def test_navigation_actions_remain_available_after_reader_login() -> None:
    access_source = DXM_ACCESS_TSX.read_text(encoding="utf-8")
    safety_source = SAFETY_STATUS_BAR_TSX.read_text(encoding="utf-8")

    assert "disabled={!dxmLoggedIn && busy}" in access_source
    assert "onClick={handlePrimaryAction} disabled={busy}" not in safety_source


def test_logged_in_access_exposes_logout_and_account_switch() -> None:
    access_source = DXM_ACCESS_TSX.read_text(encoding="utf-8")
    app_source = (FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")

    assert "退出登录" in access_source
    assert "切换账号" in access_source
    assert "/api/dxm/logout" in app_source
    assert "onLogoutDxm" in access_source
    assert "status === 'logged_out'" in access_source
    assert "dxm_account_switch_failed" in app_source
    assert "setDxmShopsSnapshot(null)" in app_source


def test_local_plan_workspace_exposes_safe_delete_and_renders_backend_editor_json() -> None:
    source = LOCAL_PLAN_WORKSPACE_TSX.read_text(encoding="utf-8")

    assert "\u5220\u9664\u65b9\u6848" in source
    assert "planPendingArchive" in source
    assert "ArchiveConfirmation" in source
    assert "\u786e\u8ba4\u5220\u9664" in source
    assert "editor_models" in source
    assert "activeEditorModel" in source
    assert "section.templates" in source
    assert "section.field_keys" in source
    assert "DXM_EDITOR_SECTIONS" not in source
    assert "dxmEditorSectionOfField" not in source
    assert "\u65b9\u6848\u8bbe\u7f6e" in source


def test_frontend_behavior_tests_are_in_standard_test_and_build_gates() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "tests/*.test.mjs" in scripts["test"]
    assert "npm run test" in scripts["build"]
