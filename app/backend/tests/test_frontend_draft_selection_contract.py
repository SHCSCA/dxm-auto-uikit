from pathlib import Path
import json


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "app" / "frontend" / "src"
DRAFT_SELECTION_TSX = (
    FRONTEND_SRC / "components" / "workbench" / "DraftSelectionPage.tsx"
)
DRAFT_STATE_TS = FRONTEND_SRC / "draftSelection.ts"
APP_SHELL_TSX = FRONTEND_SRC / "components" / "AppShell.tsx"
STYLES_CSS = FRONTEND_SRC / "styles.css"
PACKAGE_JSON = REPO_ROOT / "app" / "frontend" / "package.json"


def test_draft_selection_uses_only_real_reader_endpoints_and_source_attestation() -> None:
    source = DRAFT_SELECTION_TSX.read_text(encoding="utf-8")

    assert "/api/dxm/draft-reader/shops" in source
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

    assert "MIN_DRAFT_SELECTION = 3" in state_source
    assert "shopId" in state_source
    assert "productIds" in state_source
    assert "planId" in state_source
    assert "buildConfirmedDraftTaskInput" in page_source
    assert "确认任务输入（不启动）" in page_source
    assert "/start" not in page_source
    assert "/approve" not in page_source
    assert "resetSelectionForShopChange" in page_source


def test_primary_navigation_and_shell_keep_frozen_prototype_geometry() -> None:
    shell_source = APP_SHELL_TSX.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")
    mobile_start = styles.index("@media (max-width: 860px)", styles.index(".draft-selection-toolbar"))
    mobile_styles = styles[mobile_start : styles.index(".batch-save-placeholder__grid", mobile_start)]

    for label in (
        "工作台",
        "连接店小秘",
        "采集箱选品",
        "铺货方案",
        "开始批量保存",
        "保存结果",
        "设置",
    ):
        assert f"label: '{label}'" in shell_source
    assert 'className="nav-subitem__short"' in shell_source
    assert ".nav-subitem__short" in styles
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


def test_frontend_behavior_tests_are_in_standard_test_and_build_gates() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "tests/*.test.mjs" in scripts["test"]
    assert "npm run test" in scripts["build"]
