from __future__ import annotations

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
            conflict_page = state["cross_page_conflict"] and page_no == 2
            product_ids = (1001, 2002, 2003) if conflict_page else (1001, 1002, 1003)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "source": "api",
                    "session_bound": True,
                    "session_ref": state["session_ref"],
                    "filter": {"shop_id": "-1", "dxm_state": "draft"},
                    "pagination": {
                        "page_no": page_no,
                        "page_size": 20,
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


def _confirm_three_products(page: Page) -> None:
    page.get_by_role("button", name="选择本页").click()
    page.locator(".draft-selection-plan select").select_option("9")
    page.get_by_role("button", name="确认任务输入（不启动）").click()
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
    page.get_by_role("alert").wait_for()
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
    page.get_by_role("alert").wait_for()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"
    assert "会话已变化" in page.get_by_role("alert").inner_text()
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

    alert = page.get_by_role("alert")
    alert.wait_for()
    assert "冲突身份" in alert.inner_text()
    assert "0 件已选择" in page.locator(".draft-selection-receipt").inner_text()
    assert page.get_by_test_id("parent-task-input").inner_text() == "null"
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

    assert "尚未开放执行" in main.inner_text()
    assert "不会启动保存或发布" in main.inner_text()
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
) -> None:
    def handle(route: Route) -> None:
        path = urlparse(route.request.url).path
        method = route.request.method
        body = (
            route.request.post_data_json
            if method == "POST" and route.request.post_data
            else None
        )
        requests.append((method, path, body))
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
                                },
                                "material": {
                                    "type": "string",
                                    "ui_label_zh": "材质",
                                    "ui_binding": "dxm_attribute:5301",
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
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                },
                            },
                            "required": ["title", "material"],
                        }
                    },
                    "refs": [],
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
        if path == "/api/tasks/17":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": 17,
                    "name": "E2 atomic draft",
                    "status": "draft",
                    "mode": "batch_draft_save",
                    "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
                    "total_jobs": 3,
                    "completed_jobs": 0,
                    "failed_jobs": 0,
                    "payload": {"runner_released": False},
                }, ensure_ascii=False),
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
    workspace = page.get_by_label("E2 铺货方案工作区")
    workspace.locator("label").filter(has_text="方案名称").locator("input").fill(
        "浏览器结构化方案"
    )
    workspace.locator("label").filter(has_text="shopId").locator("input").fill(
        "3001"
    )
    workspace.locator("label").filter(
        has_text="categoryId（逗号分隔）"
    ).locator("input").fill("100")
    workspace.get_by_role("button", name="从当前真实会话同步").click()
    workspace.locator('input[value="英文标题"]').wait_for()

    assert workspace.locator("textarea").count() == 0
    workspace.get_by_label("title 来源策略").select_option("fixed")
    workspace.get_by_label("title 固定值").fill("English Product Title")
    workspace.get_by_label("material 来源策略").select_option("fill")
    assert workspace.get_by_label("material 补差值").locator(
        'option[value="ABS"]'
    ).inner_text() == "塑料 · ABS"
    workspace.get_by_label("material 补差值").select_option("ABS")
    workspace.get_by_label("imageURLs 来源策略").select_option("fixed")
    workspace.get_by_label("imageURLs 添加一项").click()
    workspace.get_by_label("imageURLs[0] 第 1 项").fill(
        "https://example.invalid/product-main.jpg"
    )
    workspace.get_by_text("属性模板甲", exact=True).wait_for()
    workspace.get_by_text("属性模板甲", exact=True).click()
    workspace.get_by_role("button", name="创建本地方案").click()
    workspace.get_by_text("已保存 local_plan_template").wait_for()

    create_body = next(
        body
        for method, path, body in requests
        if method == "POST" and path == "/api/local-plan-templates"
    )
    assert isinstance(create_body, dict)
    assert create_body["fill_rules"]["100"] == {
        "material": {"value": "ABS"},
    }
    assert create_body["fixed_values"] == {
        "publish_allowed": False,
        "field_values": {
            "100": {
                "title": "English Product Title",
                "imageURLs": [
                    "https://example.invalid/product-main.jpg",
                ],
            }
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
    section.get_by_text("任务 #17 · draft · runner 未开放").wait_for()

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
