from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Browser, Page, Route, expect

from frontend_browser_fixtures import _install_e2_plan_routes
from test_frontend_e1_browser import browser, vite_origin, _install_reader_routes, _reader_state


def _install_deep_catalog(page: Page, *, conflicting_leaf: bool = False) -> None:
    ids = ["10", "20", "30", "40", "100"]
    records = {category_id: {
        "categoryId": category_id,
        "nameZh": f"第{index + 1}级目录",
        "pcid": ids[index - 1] if index else "0",
        "nodePathId": "/".join(ids[:index + 1]),
        "isleaf": index == len(ids) - 1,
        "executableLeaf": index == len(ids) - 1 and not conflicting_leaf,
    } for index, category_id in enumerate(ids)}

    def handle(route: Route) -> None:
        parsed = urlparse(route.request.url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/children"):
            parent = query.get("pcid", ["0"])[0]
            payload = [record for record in records.values() if record["pcid"] == parent]
        elif parsed.path.endswith("/search"):
            payload = [{**records["100"], "executableLeaf": True}]
        else:
            payload = records.get(query.get("category_id", [""])[0])
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    page.route("**/api/dxm/category/**", handle)


def test_five_level_picker_does_not_accept_third_level_branch(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page()
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    _install_deep_catalog(page)
    page.goto(f"{vite_origin}/tests/browser/e2-plan-harness.html")
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_role("dialog", name="新建方案", exact=True)
    cascade = dialog.get_by_label("适用类目逐级选择")
    for index, category_id in enumerate(["10", "20", "30"]):
        cascade.locator("select").nth(index).select_option(category_id)
    expect(cascade.locator("select")).to_have_count(4)
    expect(dialog.get_by_label("已选适用类目")).to_contain_text("尚未选择")
    cascade.locator("select").nth(3).select_option("40")
    cascade.locator("select").nth(4).select_option("100")
    expect(dialog.get_by_label("已选适用类目")).to_contain_text("第5级目录")
    expect(cascade.locator("select")).to_have_count(5)
    assert not any(method != "GET" for method, _path, _body in requests)
    page.close()


def test_search_hit_is_rejected_when_current_catalog_marks_leaf_conflicting(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page()
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    _install_deep_catalog(page, conflicting_leaf=True)
    page.goto(f"{vite_origin}/tests/browser/e2-plan-harness.html")
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_role("dialog", name="新建方案", exact=True)
    dialog.get_by_placeholder("按中文名称搜索类目").fill("目录")
    dialog.get_by_role("button", name="搜索", exact=True).click()
    dialog.locator(".category-cascade-picker__results button").click()
    expect(dialog.get_by_role("alert")).to_contain_text("可执行末级类目")
    expect(dialog.get_by_label("已选适用类目")).to_contain_text("尚未选择")
    assert not any(method != "GET" for method, _path, _body in requests)
    page.close()


def test_one_and_two_drafts_cannot_confirm_product_batch(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page()
    _install_reader_routes(page, _reader_state())
    page.goto(f"{vite_origin}/tests/browser/draft-selection-harness.html")
    page.locator(".draft-selection-plan select").select_option("9")
    checkboxes = page.locator('.draft-selection-list input[type="checkbox"]')
    checkboxes.nth(0).check()
    confirm = page.get_by_role("button", name="确认任务输入（不启动）")
    expect(confirm).to_be_disabled()
    checkboxes.nth(1).check()
    expect(confirm).to_be_disabled()
    checkboxes.nth(2).check()
    expect(confirm).to_be_enabled()
    page.close()


def test_unreleased_path_b_freeze_does_not_enable_approval(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page()
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(f"{vite_origin}/tests/browser/e2-plan-harness.html")
    section = page.get_by_label("开始批量保存")
    section.get_by_role("button", name="预览并校验快照").click()
    section.get_by_role("button", name="冻结为 draft 任务（不启动）").click()
    expect(section.get_by_role("alert")).to_contain_text("执行能力尚未放行")
    expect(section.get_by_role("button", name="一次批准并开始只保存")).to_have_count(0)
    assert not any(path.endswith("/approve-and-start") for _method, path, _body in requests)
    page.close()


def test_reader_failure_stays_stopped_until_operator_refresh(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page()
    state = _reader_state()
    state["shops_error"] = True
    _install_reader_routes(page, state)
    reads: list[str] = []
    page.on("request", lambda request: reads.append(request.url) if request.url.endswith("/api/dxm/draft-reader/shops") else None)
    page.goto(f"{vite_origin}/tests/browser/draft-selection-harness.html")
    expect(page.get_by_text("真实草稿读取已停止")).to_be_visible()
    page.wait_for_timeout(400)
    assert len(reads) == 1
    page.get_by_role("button", name="重新读取草稿").click()
    expect(page.get_by_role("button", name="重新读取草稿")).to_be_enabled()
    page.wait_for_timeout(400)
    assert len(reads) == 2
    page.close()


def test_narrow_screen_keeps_navigation_and_plan_sections_usable(browser: Browser, vite_origin: str) -> None:
    page = browser.new_page(viewport={"width": 680, "height": 900})
    _install_reader_routes(page, _reader_state())
    page.goto(f"{vite_origin}/tests/browser/draft-selection-harness.html")
    navigation = page.get_by_role("combobox", name="切换工作台页面")
    expect(navigation).to_be_visible()
    navigation.select_option("start_save")
    expect(page.get_by_role("heading", name="开始批量保存")).to_be_visible()
    requests: list[tuple[str, str, object | None]] = []
    _install_e2_plan_routes(page, requests)
    page.goto(f"{vite_origin}/tests/browser/e2-plan-harness.html")
    page.get_by_role("button", name="新建方案").click()
    dialog = page.get_by_role("dialog", name="新建方案", exact=True)
    rail = dialog.get_by_role("navigation", name="店小秘编辑分区").bounding_box()
    form = dialog.locator(".lp-section-form").bounding_box()
    assert rail and form and rail["y"] + rail["height"] <= form["y"] + 1
    assert form["width"] > 500
    page.close()
