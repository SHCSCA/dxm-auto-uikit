from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ROOT = REPO_ROOT / "app" / "frontend"
VITE_ENTRYPOINT = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"


@pytest.fixture(scope="module")
def vite_origin() -> Iterator[str]:
    node = shutil.which("node")
    if not node or not VITE_ENTRYPOINT.exists():
        pytest.fail("Node/Vite is unavailable for the E1 browser contract")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [
            node,
            str(VITE_ENTRYPOINT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=FRONTEND_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(f"Vite exited before browser tests:\n{output}")
        try:
            with urllib.request.urlopen(origin, timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        process.terminate()
        pytest.fail("Vite did not become ready for the E1 browser contract")
    try:
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def _reader_state() -> dict[str, object]:
    return {
        "session_ref": "session-a",
        "shops_error": False,
        "cross_page_conflict": False,
    }


def _install_reader_routes(page: Page, state: dict[str, object]) -> None:
    def handle(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/dxm/draft-reader/shops":
            if state["shops_error"]:
                route.fulfill(
                    status=409,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": {
                            "reason_code": "BROWSER_SESSION_UNAVAILABLE",
                            "message": "真实 Reader 会话已失效",
                        }
                    }, ensure_ascii=False),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": state["session_ref"],
                    "shops": [{
                        "id": "101",
                        "name": "浏览器测试店铺",
                        "platform": "smt",
                        "shop_type": "POP",
                    }],
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm/draft-reader/products":
            page_no = int(parse_qs(urlparse(route.request.url).query).get("page_no", ["1"])[0])
            page_size = int(parse_qs(urlparse(route.request.url).query).get("page_size", ["100"])[0])
            conflict_page = state["cross_page_conflict"] and page_no == 2
            product_ids = (1001, 2002, 2003) if conflict_page else (1001, 1002, 1003)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": state["session_ref"],
                    "filter": {"shop_id": "101", "dxm_state": "draft"},
                    "pagination": {
                        "page_no": page_no,
                        "page_size": page_size,
                        "total_pages": 2 if state["cross_page_conflict"] else 1,
                        "total_items": 21 if state["cross_page_conflict"] else 3,
                        "has_previous": page_no > 1,
                        "has_next": state["cross_page_conflict"] and page_no == 1,
                    },
                    "items": [
                        {
                            "id": str(product_id),
                            "shop_id": "101",
                            "subject": f"Draft {product_id}",
                            "category_id": (
                                "999"
                                if conflict_page and product_id == 1001
                                else str(300 + product_id)
                            ),
                            "dxm_state": "draft",
                        }
                        for product_id in product_ids
                    ],
                    "deduplicated_count": 0,
                }),
            )
            return
        route.fallback()

    page.route("**/api/dxm/draft-reader/**", handle)


def _confirm_three_products(page: Page, *, expect_confirmed: bool = True) -> None:
    page.get_by_role("button", name="选择本页").click()
    page.locator(".draft-selection-plan select").select_option("9")
    page.get_by_role("button", name="确认任务输入（不启动）").click()
    if expect_confirmed:
        page.get_by_text("任务输入已确认").wait_for()


def test_draft_selection_revokes_parent_input_on_failure_unmount_and_account_change(
    browser: Browser,
    vite_origin: str,
) -> None:
    state = _reader_state()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _install_reader_routes(page, state)
    page.goto(
        f"{vite_origin}/tests/browser/draft-selection-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_text("Draft 1001").wait_for()

    _confirm_three_products(page)
    assert '"sessionRef":"session-a"' in page.get_by_test_id("parent-task-input").inner_text()

    state["shops_error"] = True
    page.get_by_role("button", name="刷新").click()
    page.locator(".draft-selection-alert").wait_for()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"

    state["shops_error"] = False
    page.get_by_role("button", name="刷新").click()
    page.get_by_text("Draft 1001").wait_for()
    _confirm_three_products(page)
    page.get_by_test_id("unmount-selection").click()
    page.get_by_test_id("selection-unmounted").wait_for()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"

    page.get_by_test_id("remount-selection").click()
    page.get_by_text("Draft 1001").wait_for()
    page.get_by_role("button", name="选择本页").click()
    page.locator(".draft-selection-plan select").select_option("9")
    state["session_ref"] = "session-b"
    page.get_by_role("button", name="确认任务输入（不启动）").click()
    page.locator(".draft-selection-alert").wait_for()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"
    assert "会话已变化" in page.locator(".draft-selection-alert").first.inner_text()
    page.close()
def test_rail_is_computed_hidden_at_680px(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 680, "height": 900})
    _install_reader_routes(page, _reader_state())
    page.goto(
        f"{vite_origin}/tests/browser/draft-selection-harness.html",
        wait_until="domcontentloaded",
    )
    page.locator(".sidebar").wait_for(state="attached")

    display = page.locator(".sidebar").evaluate(
        "(element) => getComputedStyle(element).display"
    )
    workspace_box = page.locator(".workspace").bounding_box()

    assert display == "none"
    assert workspace_box is not None
    assert workspace_box["x"] == pytest.approx(0)
    assert workspace_box["width"] == pytest.approx(680)
    page.close()


def test_cross_page_product_identity_drift_fails_closed_in_mounted_component(
    browser: Browser,
    vite_origin: str,
) -> None:
    state = _reader_state()
    state["cross_page_conflict"] = True
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _install_reader_routes(page, state)
    page.goto(
        f"{vite_origin}/tests/browser/draft-selection-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_text("Draft 1001").wait_for()
    page.get_by_text("Draft 1001").click()
    page.get_by_role("button", name="下一页").click()

    alert = page.locator(".draft-selection-alert")
    alert.wait_for()
    assert "冲突身份" in alert.first.inner_text()
    assert "0 件已选择" in page.locator(".draft-selection-receipt").inner_text()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"
    page.close()


def test_confirmed_real_reader_input_advances_to_preview_and_freeze_page(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _install_reader_routes(page, _reader_state())
    page.route(
        "**/api/local-plan-templates/9",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_e2_plan_payload(), ensure_ascii=False),
        ),
    )
    page.goto(
        f"{vite_origin}/tests/browser/draft-selection-harness.html?autoAdvance=1",
        wait_until="domcontentloaded",
    )
    page.get_by_text("Draft 1001").wait_for()

    _confirm_three_products(page, expect_confirmed=False)

    page.get_by_role("heading", name="开始批量保存").wait_for()
    review = page.get_by_label("批量快照预览与冻结")
    preview_button = review.get_by_role("button", name="预览并校验快照")
    page.wait_for_timeout(500)
    assert preview_button.is_enabled(), page.locator("main").inner_text()
    main_text = page.locator("main").inner_text()
    assert "冻结前保持零写" in main_text
    assert "发布始终不允许" in main_text
    page.close()


def test_real_app_start_save_navigation_opens_safe_placeholder(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.route(
        "**/api/**",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"browser contract fixture"}',
        ),
    )
    page.goto(vite_origin, wait_until="domcontentloaded")
    page.locator('button[data-section="start_save"]').click()
    main = page.locator("main")
    page.get_by_role("heading", name="开始批量保存").wait_for()

    assert "只保存 · 不发布" in main.inner_text()
    assert "冻结前保持零写" in main.inner_text()
    assert "浏览器诊断" not in main.inner_text()
    page.close()


def _e2_plan_payload() -> dict[str, object]:
    return {
        "model": "local_plan_template",
        "id": 9,
        "lineage_id": 9,
        "supersedes_id": None,
        "name": "浏览器测试方案",
        "version": "1.0.0",
        "shop_id": "3001",
        "category_ids": ["100"],
        "path": "A",
        "fixed_values": {"publish_allowed": False},
        "fill_rules": {"100": {}},
        "dxm_template_refs": [{
            "ref_id": 31,
            "source_digest": "A" * 64,
        }],
        "field_mappings": {
            "100": {
                "mapping_version": "zh-map-100-v1",
                "entries": [
                    {
                        "ui_label_zh": "英文标题",
                        "field_key": "title",
                        "category_schema_path": "$.properties.title",
                        "ui_binding": "dxm_editor:title",
                    },
                    {
                        "ui_label_zh": "材质",
                        "field_key": "material",
                        "category_schema_path": "$.properties.material",
                        "ui_binding": "dxm_attribute:5301",
                    },
                ],
            }
        },
        "validation_policy": {
            "required_fields": "fail_closed",
            "natural_language": "english_before_save",
        },
        "exception_policy": {"unknown": "stop_batch"},
        "provenance": "operator_reviewed_local_plan",
        "is_active": True,
        "created_at": "2026-07-30T00:00:00Z",
        "updated_at": "2026-07-30T00:00:00Z",
    }


def _e2_snapshot(*, frozen: bool) -> dict[str, object]:
    snapshot_hash = "C" * 64
    return {
        **({"id": 5, "task_id": 17} if frozen else {}),
        "schema": "dxm_batch_draft_save_plan.v1",
        "mode": "batch_draft_save",
        "path": "A",
        "shop_scope": "3001",
        "product_ids": ["70001", "70002", "70003"],
        "local_plan_template": {"id": 9, "version": "1.0.0"},
        "dxm_template_refs": [],
        "fixed_values": {"publish_allowed": False},
        "fill_rules": {"100": {}},
        "session_context": {
            "session_ref": "0123456789abcdef",
            "account_ref_hash": "D" * 64,
            "shop_id": "3001",
        },
        "approval_context": {
            "state": "not_granted",
            "runner_released": False,
            "publish_allowed": False,
        },
        "item_snapshots": [
            {"product_id": product_id}
            for product_id in ("70001", "70002", "70003")
        ],
        "evidence_policy": "three_proofs",
        "failure_policy": {"unknown": "stop_batch"},
        "publish_allowed": False,
        "snapshot_hash": snapshot_hash,
    }


def _install_e2_plan_routes(
    page: Page,
    requests: list[tuple[str, str, object | None]],
    *,
    approval_response_lost: bool = False,
    empty_choice_field: bool = False,
) -> None:
    approval_state = {"dispatched": False}

    def handle(route: Route) -> None:
        path = urlparse(route.request.url).path
        method = route.request.method
        body = (
            route.request.post_data_json
            if method == "POST" and route.request.post_data
            else None
        )
        requests.append((method, path, body))
        if path == "/api/dxm/category/children":
            pcid = parse_qs(urlparse(route.request.url).query).get("pcid", [""])[0]
            records = {
                "": [{"categoryId": "10", "nameZh": "一级测试类目", "isleaf": False, "level": 1}],
                "10": [{"categoryId": "20", "nameZh": "二级测试类目", "pcid": "10", "isleaf": False, "level": 2}],
                "20": [{"categoryId": "100", "nameZh": "测试类目", "pcid": "20", "isleaf": True, "level": 3}],
            }.get(pcid, [])
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(records, ensure_ascii=False),
            )
            return
        if path == "/api/dxm/category/get":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "categoryId": "100",
                    "nameZh": "测试类目",
                    "nodePath": "一级测试类目/二级测试类目/测试类目",
                    "nodePathId": "10/20/100",
                    "pcid": "20",
                    "isleaf": True,
                    "level": 3,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm/draft-reader/shops":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "shops": [{
                        "id": "3001",
                        "name": "浏览器测试店铺",
                        "platform": "smt",
                        "shop_type": "POP",
                    }],
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm/draft-reader/products":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "filter": {"shop_id": "3001", "dxm_state": "draft"},
                    "pagination": {
                        "page_no": 1,
                        "page_size": 100,
                        "total_pages": 1,
                        "total_items": 1,
                        "has_previous": False,
                        "has_next": False,
                    },
                    "items": [{
                        "id": "70001",
                        "shop_id": "3001",
                        "subject": "Draft 70001",
                        "category_id": "100",
                        "category_name": "测试类目",
                        "dxm_state": "draft",
                    }],
                    "deduplicated_count": 0,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/dxm-template-refs/sync":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": "0123456789abcdef",
                    "shop_id": "3001",
                    "category_ids": ["100"],
                    "category_schemas": {
                        "100": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "minLength": 8,
                                    "natural_language": True,
                                    "ui_label_zh": "英文标题",
                                    "ui_binding": "dxm_editor:title",
                                    "ui_section": "basic_info",
                                    "source_api": "/api/smtProduct/edit.json",
                                },
                                "material": {
                                    "type": "string",
                                    "ui_label_zh": "材质",
                                    "ui_binding": "dxm_attribute:5301",
                                    "ui_section": "attribute_info",
                                    "source_api": "/api/smtCategory/attributeList.json",
                                    "values": [
                                        {
                                            "id": "ABS",
                                            "name": "Plastic",
                                            "names": {"zh": "塑料"},
                                        },
                                        {
                                            "id": "Metal",
                                            "name": "Metal",
                                            "names": {"zh": "金属"},
                                        },
                                    ],
                                },
                                "imageURLs": {
                                    "type": "array",
                                    "ui_label_zh": "主图与附图",
                                    "ui_binding": "dxm_editor:imageURLs",
                                    "ui_section": "product_info",
                                    "source_api": "/api/smtProduct/edit.json",
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                },
                                **({
                                    "attr_3": {
                                        "type": "string",
                                        "ui_label_zh": "自定义英文属性",
                                        "ui_binding": "dxm_attribute:3",
                                        "ui_section": "attribute_info",
                                        "source_api": "/api/smtCategory/attributeList.json",
                                        "natural_language": True,
                                        "values": [],
                                        "enum": [],
                                    },
                                } if empty_choice_field else {}),
                            },
                            "required": ["title", "material"],
                        }
                    },
                    "editor_models": {
                        "100": {
                            "schema": "dxm_editor_form.v3",
                            "category_id": "100",
                            "sections": [
                                {
                                    "code": "basic_info",
                                    "label": "基本信息",
                                    "help": "标题与类目基础字段。",
                                    "order": 0,
                                    "field_keys": ["title"],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                },
                                {
                                    "code": "attribute_info",
                                    "label": "属性信息",
                                    "help": "类目属性与属性模板。",
                                    "order": 1,
                                    "field_keys": [
                                        "material",
                                        *(["attr_3"] if empty_choice_field else []),
                                    ],
                                    "templates": [{
                                        "ref_id": 31,
                                        "ref_type": "attribute",
                                        "dxm_template_id": "902",
                                        "display_name": "属性模板甲",
                                        "category_id": "100",
                                        "source_digest": "A" * 64,
                                        "resolved_field_keys": ["material"],
                                        "resolved_values": {"material": "ABS"},
                                    }],
                                    "source_apis": [
                                        "/api/smtAttributeTemplate/pageList.json",
                                        "/api/smtCategory/attributeList.json",
                                    ],
                                },
                                {
                                    "code": "product_info",
                                    "label": "产品信息",
                                    "help": "图片、SKU 与价格字段。",
                                    "order": 2,
                                    "field_keys": ["imageURLs"],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                },
                                {
                                    "code": "description_info",
                                    "label": "描述信息",
                                    "help": "尺码表与新版描述编辑器流程。",
                                    "order": 3,
                                    "field_keys": [],
                                    "templates": [],
                                    "source_apis": ["/api/smtProduct/edit.json"],
                                    "widgets": [{
                                        "kind": "description_editor",
                                        "label": "描述",
                                        "workflow": [
                                            "使用新版编辑器",
                                            "根据 PC 端描述一键生成",
                                            "确认",
                                            "保存",
                                        ],
                                    }],
                                },
                            ],
                        }
                    },
                    "refs": [{
                        "model": "dxm_template_ref",
                        "id": 31,
                        "ref_type": "attribute",
                        "dxm_template_id": "902",
                        "shop_id": "3001",
                        "category_id": "100",
                        "observed_display_name": "属性模板甲",
                        "source_api": "/api/smtAttributeTemplate/pageList.json",
                        "availability": "available",
                        "source_digest": "A" * 64,
                        "resolved_values_hash": "B" * 64,
                        "resolved_field_count": 1,
                        "synced_at": "2026-07-30T00:00:00Z",
                    }],
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates" and method == "POST":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({
                    **_e2_plan_payload(),
                    **(body if isinstance(body, dict) else {}),
                    "id": 10,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates/71" and method == "DELETE":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    **_e2_plan_payload(),
                    "id": 71,
                    "name": "可删除方案",
                    "is_active": False,
                }, ensure_ascii=False),
            )
            return
        if path == "/api/local-plan-templates/9":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_e2_plan_payload(), ensure_ascii=False),
            )
            return
        if path == "/api/plan-snapshots/preview":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_e2_snapshot(frozen=False), ensure_ascii=False),
            )
            return
        if path == "/api/plan-snapshots":
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(_e2_snapshot(frozen=True), ensure_ascii=False),
            )
            return
        if path == "/api/tasks/17" and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": 17,
                    "name": "E2 atomic draft",
                    "status": (
                        "running" if approval_state["dispatched"] else "draft"
                    ),
                    "mode": "batch_draft_save",
                    "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
                    "total_jobs": 3,
                    "completed_jobs": 0,
                    "failed_jobs": 0,
                    "payload": {"runner_released": False},
                }, ensure_ascii=False),
            )
            return
        if path == "/api/tasks/17/approve-and-start" and method == "POST":
            approval_state["dispatched"] = True
            route.fulfill(
                status=503 if approval_response_lost else 200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "detail": "simulated response loss",
                    }
                    if approval_response_lost
                    else {
                        "ok": True,
                        "taskId": 17,
                        "status": "running",
                        "authorizationConsumed": True,
                    },
                    ensure_ascii=False,
                ),
            )
            return
        route.fulfill(
            status=404,
            content_type="application/json",
            body='{"detail":"unexpected E2 browser route"}',
        )

    page.route("**/api/**", handle)


def test_e2_local_plan_uses_structured_schema_controls_in_browser(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_label("新建方案")
    dialog.locator("label").filter(has_text="方案名称").locator("input").fill(
        "浏览器结构化方案"
    )
    dialog.locator("label").filter(has_text="店铺").locator("select").select_option(
        "3001"
    )
    cascade = dialog.get_by_label("适用类目三级联动")
    cascade.locator("select").nth(0).select_option("10")
    cascade.locator("select").nth(1).select_option("20")
    cascade.locator("select").nth(2).select_option("100")
    dialog.get_by_role("button", name="读取类目字段与模板").click()
    dialog.get_by_role("button", name="属性信息").click()
    dialog.get_by_label("属性模板 模板选择").select_option("31")
    assert dialog.get_by_label("材质 方案设置").input_value() == "ABS"
    dialog.get_by_text("已由模板「属性模板甲」带入；仍可在这里调整。").wait_for()
    dialog.get_by_role("button", name="基本信息").click()

    assert dialog.locator("textarea").count() == 0
    dialog.get_by_label("title 方案设置").fill("English Product Title")
    dialog.get_by_role("button", name="产品信息").click()
    dialog.get_by_label("imageURLs 添加一项").click()
    dialog.get_by_label("imageURLs[0] 第 1 项").fill(
        "https://example.invalid/product-main.jpg"
    )
    dialog.get_by_role("button", name="属性信息").click()
    assert dialog.get_by_label("材质 方案设置").locator(
        'option[value="ABS"]'
    ).inner_text() == "塑料 · ABS"
    dialog.get_by_label("材质 方案设置").select_option("ABS")
    dialog.get_by_role("button", name="创建方案").click()
    page.get_by_text("已保存「浏览器结构化方案」").wait_for()

    create_body = next(
        body
        for method, path, body in requests
        if method == "POST" and path == "/api/local-plan-templates"
    )
    assert isinstance(create_body, dict)
    assert create_body["fill_rules"]["100"] == {
        "material": {"value": "ABS"},
        "title": {"value": "English Product Title"},
        "imageURLs": {"value": ["https://example.invalid/product-main.jpg"]},
    }
    assert create_body["fixed_values"] == {
        "publish_allowed": False,
        "field_values": {
            "100": {}
        },
    }
    assert [
        entry["ui_label_zh"]
        for entry in create_body["field_mappings"]["100"]["entries"]
    ] == ["英文标题", "材质", "主图与附图"]
    assert [
        entry["ui_binding"]
        for entry in create_body["field_mappings"]["100"]["entries"]
    ] == [
        "dxm_editor:title",
        "dxm_attribute:5301",
        "dxm_editor:imageURLs",
    ]
    page.close()


def test_e2_empty_schema_choices_render_an_editable_type_control(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests, empty_choice_field=True)
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_label("新建方案")
    dialog.locator("label").filter(has_text="方案名称").locator("input").fill(
        "空枚举方案"
    )
    dialog.locator("label").filter(has_text="店铺").locator("select").select_option(
        "3001"
    )
    cascade = dialog.get_by_label("适用类目三级联动")
    cascade.locator("select").nth(0).select_option("10")
    cascade.locator("select").nth(1).select_option("20")
    cascade.locator("select").nth(2).select_option("100")
    dialog.get_by_role("button", name="读取类目字段与模板").click()
    dialog.get_by_role("button", name="属性信息").click()
    editor = dialog.get_by_label("attr_3 方案设置")
    assert editor.evaluate("element => element.tagName") == "INPUT"
    editor.fill("Handmade acrylic collectible accessory")
    assert editor.input_value() == "Handmade acrylic collectible accessory"
    page.close()


def test_e2_description_uses_explicit_new_editor_workflow_contract(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_label("新建方案")
    dialog.locator("label").filter(has_text="方案名称").locator("input").fill(
        "新版描述方案"
    )
    dialog.locator("label").filter(has_text="店铺").locator("select").select_option("3001")
    cascade = dialog.get_by_label("适用类目三级联动")
    cascade.locator("select").nth(0).select_option("10")
    cascade.locator("select").nth(1).select_option("20")
    cascade.locator("select").nth(2).select_option("100")
    dialog.get_by_role("button", name="读取类目字段与模板").click()
    dialog.get_by_role("button", name="属性信息").click()
    dialog.get_by_label("属性模板 模板选择").select_option("31")
    dialog.get_by_role("button", name="描述信息").click()
    dialog.get_by_role("button", name="使用新版编辑器").click()

    editor = page.get_by_label("新版描述编辑器流程")
    editor.get_by_role("checkbox").check()
    editor.get_by_role("button", name="保存动作配置").click()
    dialog.get_by_role("button", name="创建方案").click()

    create_body = next(
        body
        for method, path, body in requests
        if method == "POST" and path == "/api/local-plan-templates"
    )
    assert isinstance(create_body, dict)
    assert create_body["category_ids"] == ["100"]
    assert create_body["editor_actions"] == {
        "100": {
            "description": {
                "editor": "new",
                "generate_mobile_from_pc": True,
                "confirm_before_save": True,
            }
        }
    }
    page.close()


def test_e2_local_plan_list_exposes_an_explicit_safe_delete_action(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    page.get_by_text("可删除方案", exact=True).wait_for()
    page.locator(".local-plan-card__delete").click()
    page.get_by_role("alertdialog").get_by_role("button", name="确认删除").click()
    page.get_by_text("已删除方案「可删除方案」").wait_for()

    assert ("DELETE", "/api/local-plan-templates/71", None) in requests
    page.close()


def test_e2_preview_freeze_browser_flow_uses_atomic_task_and_idempotency(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    section = page.get_by_label("开始批量保存")
    section.get_by_text("浏览器测试方案 · v1.0.0 · #9").wait_for()
    section.get_by_role("button", name="预览并校验快照").click()
    section.get_by_text("快照预览已通过").wait_for()
    section.get_by_role("button", name="冻结为 draft 任务（不启动）").click()
    section.get_by_text("任务 #17 · 待启动 · 批量只保存").wait_for()

    freeze_body = next(
        body
        for method, path, body in requests
        if method == "POST" and path == "/api/plan-snapshots"
    )
    assert isinstance(freeze_body, dict)
    assert freeze_body["idempotency_key"] == f"e2-freeze-{'c' * 24}"
    assert not any(
        method == "POST" and path.endswith("/tasks")
        for method, path, _body in requests
    )
    assert ("GET", "/api/tasks/17") in [
        (method, path)
        for method, path, _body in requests
    ]
    page.close()


def test_batch_task_atomic_approval_never_reposts_after_response_loss(
    browser: Browser,
    vite_origin: str,
) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 1100})
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(
        page,
        requests,
        approval_response_lost=True,
    )
    page.goto(
        f"{vite_origin}/tests/browser/e2-plan-harness.html",
        wait_until="domcontentloaded",
    )
    section = page.get_by_label("开始批量保存")
    section.get_by_text("浏览器测试方案 · v1.0.0 · #9").wait_for()
    section.get_by_role("button", name="预览并校验快照").click()
    section.get_by_text("快照预览已通过").wait_for()
    section.get_by_role("button", name="冻结为 draft 任务（不启动）").click()

    approval = page.get_by_label("批量只保存一次批准")
    approval.get_by_text("任务", exact=True).wait_for()
    assert "#17" in approval.inner_text()
    assert "C" * 64 in approval.inner_text()
    assert "发布允许\n否" in approval.inner_text()
    approval.get_by_label("批准人").fill("operator-a")
    approval.get_by_label(
        "输入确认短语 CONFIRM_DXM_SAVE_ONLY"
    ).fill("CONFIRM_DXM_SAVE_ONLY")

    approve_button = approval.get_by_role(
        "button", name="一次批准并开始只保存"
    )
    assert approve_button.is_enabled()
    approve_button.evaluate("button => { button.click(); button.click(); }")

    page.get_by_test_id("selected-task-id").get_by_text("17").wait_for()
    page.get_by_test_id("batch-task-destination").get_by_text(
        "monitor"
    ).wait_for()

    approval_posts = [
        (method, path, body)
        for method, path, body in requests
        if method == "POST" and path == "/api/tasks/17/approve-and-start"
    ]
    assert approval_posts == [(
        "POST",
        "/api/tasks/17/approve-and-start",
        {
            "approved_by": "operator-a",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )]
    assert not any(
        method == "POST"
        and path in {
            "/api/tasks/17/manual-approval",
            "/api/tasks/17/start",
        }
        for method, path, _body in requests
    )
    approval_post_index = next(
        index
        for index, (method, path, _body) in enumerate(requests)
        if method == "POST" and path == "/api/tasks/17/approve-and-start"
    )
    assert any(
        method == "GET" and path == "/api/tasks/17"
        for method, path, _body in requests[approval_post_index + 1 :]
    )
    page.close()
