from fastapi.testclient import TestClient
import sys
import threading
import time
import types

from src import db
from src.main import app
from src.repository import Repository
from src.services import agent_console as agent_console_module
from src.services.agent_console import AgentConsoleService


def test_agent_console_service_preview_session_does_not_launch_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()

    status = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=False,
        step={"state": "PRECHECK", "action": "配置预检", "next_step": "打开采集箱"},
    )

    assert status["active"] is True
    assert status["task_id"] == 42
    assert status["browser_visible"] is False
    assert status["hud"]["state"] == "PRECHECK"
    assert status["hud"]["guard"] == "只保存不发布"
    assert str(tmp_path / "profiles") in status["profile_dir"]

    updated = service.update_hud({"state": "SAVE_ONLY", "action": "等待保存证据"})
    assert updated["hud"]["state"] == "SAVE_ONLY"
    assert updated["hud"]["action"] == "等待保存证据"

    stopped = service.stop()
    assert stopped["active"] is False
    assert stopped["browser_visible"] is False


def test_agent_console_can_launch_real_browser_in_background(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    launch_started = threading.Event()
    launch_release = threading.Event()

    def fake_launch(profile_dir, state):
        launch_started.set()
        assert str(profile_dir).startswith(str(tmp_path / "profiles"))
        assert state["target_url"] == "https://www.dianxiaomi.com/"
        launch_release.wait(timeout=5)
        with service._lock:
            service._state["browser_launching"] = False
            service._state["browser_visible"] = True
            service._state["current_url"] = state["target_url"]
            service._state["page_title"] = "店小秘ERP"
            service._state["last_error"] = None

    monkeypatch.setattr(service, "_launch_visible_browser", fake_launch)

    started_at = time.monotonic()
    status = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=True,
        launch_browser_async=True,
    )
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert status["active"] is True
    assert status["browser_launching"] is True
    assert status["browser_visible"] is False
    assert launch_started.wait(timeout=1)
    assert service.status()["browser_launching"] is True

    launch_release.set()
    for _ in range(20):
        status = service.status()
        if status["browser_visible"]:
            break
        time.sleep(0.05)

    assert status["browser_launching"] is False
    assert status["browser_visible"] is True
    assert status["current_url"] == "https://www.dianxiaomi.com/"


def test_agent_console_start_reuses_visible_browser_for_same_task(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    close_calls = []

    original_close = service._close_current_browser

    def close_spy():
        close_calls.append("closed")
        original_close()

    monkeypatch.setattr(service, "_close_current_browser", close_spy)

    initial = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=False,
        step={"state": "WAITING", "action": "等待启动真实浏览器"},
    )
    with service._lock:
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["current_url"] = "https://www.dianxiaomi.com/web/home"
        service._page = object()

    reused = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/web/home",
        launch_browser=True,
        step={"state": "BROWSER_READY", "action": "真实浏览器已打开"},
    )

    assert close_calls == ["closed"]
    assert reused["session_id"] == initial["session_id"]
    assert reused["profile_dir"] == initial["profile_dir"]
    assert reused["task_id"] == 42
    assert reused["browser_visible"] is True
    assert reused["browser_launching"] is False
    assert reused["current_url"] == "https://www.dianxiaomi.com/web/home"
    assert reused["hud"]["state"] == "BROWSER_READY"
    assert reused["hud"]["action"] == "真实浏览器已打开"


def test_agent_console_status_does_not_wait_for_slow_launch_title(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "chrome_launch_options", lambda headless: {})
    page = _SlowTitleLaunchPage()
    fake_playwright = _FakePlaywrightForLaunch(page)
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        types.SimpleNamespace(sync_playwright=lambda: types.SimpleNamespace(start=lambda: fake_playwright)),
    )
    service = AgentConsoleService()

    service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=True,
        launch_browser_async=True,
    )
    assert page.title_started.wait(timeout=1)

    started_at = time.monotonic()
    try:
        status = service.status()
    finally:
        page.title_release.set()
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert status["active"] is True
    assert status["browser_launching"] is True


def test_agent_console_api_lifecycle_uses_preview_mode(tmp_path, monkeypatch):
    client, repo, service = _client_with_temp_repo_and_console(tmp_path, monkeypatch)
    task = _create_task(repo)

    start_response = client.post(
        "/api/agent-console/start",
        json={
            "task_id": task["id"],
            "target_url": "https://www.dianxiaomi.com/",
            "launch_browser": False,
            "step": {
                "title": "Agent Console 待命",
                "state": "WAITING",
                "action": "等待人工启动任务",
                "next_step": "配置预检",
                "store_name": "Dang Kang",
                "guard": "只保存不发布",
            },
        },
    )

    assert start_response.status_code == 200
    started = start_response.json()
    assert started["active"] is True
    assert started["task_id"] == task["id"]
    assert started["browser_visible"] is False
    assert started["hud"]["store_name"] == "Dang Kang"

    hud_response = client.post(
        "/api/agent-console/hud",
        json={"step": {"state": "OPEN_DRAFT_BOX", "action": "打开采集箱", "next_step": "定位备注商品"}},
    )

    assert hud_response.status_code == 200
    assert hud_response.json()["hud"]["state"] == "OPEN_DRAFT_BOX"

    status_response = client.get("/api/agent-console/status")
    assert status_response.status_code == 200
    assert status_response.json()["session_id"] == started["session_id"]

    snapshot_response = client.post("/api/agent-console/snapshot")
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["active"] is True
    assert snapshot_response.json()["screenshot"] is None

    frame_response = client.post("/api/agent-console/frame")
    assert frame_response.status_code == 200
    assert frame_response.json()["active"] is True
    assert frame_response.json()["last_frame_at"] is None
    assert frame_response.json()["network_events"] == []

    stop_response = client.post("/api/agent-console/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["active"] is False

    service.stop()


def test_agent_console_updates_task_step_without_launching_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    result = service.update_task_step(
        task_id=7,
        job_id=11,
        product_id=13,
        step_code="SAVE_ONLY",
        step_name="只点击保存",
        field_domain="save",
        mode="single_save",
        store_name="Dang Kang",
        next_step="记录未发布证明",
        screenshot_path="data/screenshots/save.txt",
    )

    assert result["updated"] is True
    assert result["browser_visible"] is False
    assert result["last_step_code"] == "SAVE_ONLY"
    assert result["hud"]["state"] == "SAVE_ONLY"
    assert result["hud"]["title"] == "只点击保存"
    assert result["hud"]["guard"] == "只保存不发布"
    assert result["hud"]["next_step"] == "记录未发布证明"
    status = service.status()
    assert status["step_history"][-1]["screenshot_path"] == "data/screenshots/save.txt"


def test_agent_console_records_bounded_action_events(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    for index in range(165):
        result = service.record_action_event(
            task_id=7,
            job_id=11,
            product_id=13,
            type="fill",
            action=f"fill_field_{index}",
            label=f"填写字段 {index}",
            state="FILL_BASE_INFO",
            field_domain="base_info",
            status="ok",
            target="商品标题",
            value="ACG Stand Product",
            page_url="https://www.dianxiaomi.com/web/smt/edit",
        )

    assert result["updated"] is True
    status = service.status()
    assert len(status["action_events"]) == 160
    assert status["action_events"][0]["action"] == "fill_field_5"
    assert status["action_events"][-1]["type"] == "fill"
    assert status["action_events"][-1]["target"] == "商品标题"
    assert status["action_events"][-1]["timestamp"] is not None


def test_agent_console_refresh_frame_updates_screenshot_and_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    status = service.refresh_frame()

    assert status["screenshot"].endswith(".png")
    assert (tmp_path / "screenshots" / f"{status['session_id']}.png").exists()
    assert status["last_frame_at"] is not None
    assert status["current_url"] == "https://www.dianxiaomi.com/web/home"
    assert fake_page.screenshot_full_page is False
    assert status["page_title"] == "店小秘 Home"


def test_agent_console_status_uses_cached_browser_state(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    with service._lock:
        service._page = _ThreadBoundFakePage()
        service._state["browser_visible"] = True
        service._state["current_url"] = "https://www.dianxiaomi.com/web/home"
        service._state["page_title"] = "店小秘 Home"
        service._state["last_error"] = None

    status = service.status()

    assert status["current_url"] == "https://www.dianxiaomi.com/web/home"
    assert status["page_title"] == "店小秘 Home"
    assert status["last_error"] is None


def test_agent_console_manual_takeover_brings_real_browser_to_front(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    takeover = service.request_manual_takeover()

    assert takeover["active"] is True
    assert takeover["manual_takeover"] is True
    assert takeover["manual_takeover_started_at"] is not None
    assert fake_page.brought_to_front is True
    assert takeover["action_events"][-1]["type"] == "manual_takeover"

    released = service.release_manual_takeover()

    assert released["manual_takeover"] is False
    assert released["manual_takeover_started_at"] is None
    assert released["action_events"][-1]["action"] == "release_agent"


def test_agent_console_rejects_browser_control_without_live_page(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    result = service.control_browser({"action": "click", "x": 12, "y": 34})

    assert result["ok"] is False
    assert result["reason"] == "browser_page_unavailable"
    assert result["active"] is True


def test_agent_console_controls_live_browser_and_records_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    scrolled = service.control_browser({"action": "scroll", "delta_y": 360})
    navigated = service.control_browser({"action": "goto", "url": "https://www.dianxiaomi.com/web/home"})

    assert scrolled["ok"] is True
    assert navigated["ok"] is True
    assert fake_page.mouse.clicks == []
    assert fake_page.keyboard.typed == []
    assert fake_page.keyboard.pressed == []
    assert fake_page.mouse.wheels == [(0, 360)]
    assert fake_page.goto_calls[-1] == ("https://www.dianxiaomi.com/web/home", "domcontentloaded", 45000)
    status = service.status()
    assert status["current_url"] == "https://www.dianxiaomi.com/web/home"
    assert status["action_events"][-1]["type"] == "browser_control"
    assert status["action_events"][-1]["action"] == "goto"
    assert status["action_events"][-1]["status"] == "ok"
    assert status["last_frame_at"] is not None


def test_agent_console_rejects_untargeted_browser_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    clicked = service.control_browser({"action": "click", "x": 120, "y": 240})
    typed = service.control_browser({"action": "type", "text": "DXM test"})
    pressed = service.control_browser({"action": "press", "key": "Enter"})

    assert clicked["ok"] is False
    assert typed["ok"] is False
    assert pressed["ok"] is False
    assert clicked["reason"] == "browser_control_failed"
    assert "selector-based control" in clicked["error"]
    assert "selector-based control" in typed["error"]
    assert "selector-based control" in pressed["error"]
    assert fake_page.mouse.clicks == []
    assert fake_page.keyboard.typed == []
    assert fake_page.keyboard.pressed == []


def test_agent_console_successful_browser_control_clears_stale_error(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True
        service._state["last_error"] = "Cannot switch to a different thread"

    result = service.control_browser({"action": "goto", "url": "https://www.dianxiaomi.com/web/home"})

    assert result["ok"] is True
    assert result["last_error"] is None
    assert service.status()["last_error"] is None
    assert service.status()["action_events"][-1]["status"] == "ok"


def test_agent_console_controls_live_browser_by_selector_and_records_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    clicked = service.control_browser({"action": "selector_click", "selector": "[data-testid='title']"})
    filled = service.control_browser({"action": "selector_fill", "selector": "[name='title']", "text": "DXM edited title"})

    assert clicked["ok"] is True
    assert filled["ok"] is True
    assert fake_page.locator_calls == ["[data-testid='title']", "[name='title']"]
    assert fake_page.locators["[data-testid='title']"].clicks == [8000]
    assert fake_page.locators["[name='title']"].fills == [("DXM edited title", 8000)]
    status = service.status()
    assert status["action_events"][-1]["type"] == "browser_control"
    assert status["action_events"][-1]["action"] == "selector_fill"
    assert status["action_events"][-1]["target"] == "[name='title']"
    assert status["action_events"][-1]["value"] == "16 chars"


def test_agent_console_rejects_browser_control_when_window_not_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = False

    result = service.control_browser({"action": "type", "text": "DXM test"})

    assert result["ok"] is False
    assert result["reason"] == "browser_window_not_visible"
    assert fake_page.keyboard.typed == []


def test_agent_console_rejects_browser_control_during_manual_takeover(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True
        service._state["manual_takeover"] = True

    result = service.control_browser({"action": "click", "x": 120, "y": 240})

    assert result["ok"] is False
    assert result["reason"] == "manual_takeover_active"
    assert fake_page.mouse.clicks == []


def test_agent_console_rejects_high_risk_selector_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    result = service.control_browser({"action": "selector_click", "selector": "button[data-action='publish']"})

    assert result["ok"] is False
    assert result["reason"] == "browser_control_failed"
    assert "blocked selector target" in result["error"]
    assert fake_page.locator_calls == []
    assert service.status()["action_events"][-1]["status"] == "error"


def test_agent_console_selector_fill_preserves_user_text_spacing(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    result = service.control_browser({"action": "selector_fill", "selector": "[name='title']", "text": "  DXM title  "})

    assert result["ok"] is True
    assert fake_page.locators["[name='title']"].fills == [("  DXM title  ", 8000)]
    assert result["control_result"]["text_length"] == 13
    assert service.status()["action_events"][-1]["value"] == "13 chars"


def test_agent_console_api_manual_takeover_lifecycle(tmp_path, monkeypatch):
    client, repo, service = _client_with_temp_repo_and_console(tmp_path, monkeypatch)
    task = _create_task(repo)
    start_response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": False})
    assert start_response.status_code == 200

    takeover_response = client.post("/api/agent-console/takeover")

    assert takeover_response.status_code == 200
    assert takeover_response.json()["manual_takeover"] is True

    release_response = client.post("/api/agent-console/release")

    assert release_response.status_code == 200
    assert release_response.json()["manual_takeover"] is False
    service.stop()


def test_agent_console_api_rejects_untargeted_browser_control(tmp_path, monkeypatch):
    client, repo, service = _client_with_temp_repo_and_console(tmp_path, monkeypatch)
    task = _create_task(repo)
    start_response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": False})
    assert start_response.status_code == 200
    fake_page = _FakePage()
    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    response = client.post("/api/agent-console/control", json={"action": "type", "text": "hello"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["reason"] == "browser_control_failed"
    assert payload["action_events"][-1]["action"] == "type"
    assert payload["action_events"][-1]["status"] == "error"
    assert "selector-based control" in payload["error"]
    assert fake_page.keyboard.typed == []
    service.stop()


def test_agent_console_records_bounded_network_events(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    for index in range(125):
        service._record_network_event({
            "type": "response",
            "method": "POST",
            "url": f"https://www.dianxiaomi.com/api/popChoiceProduct/add.json?i={index}",
            "status": 200,
        })

    status = service.status()
    assert len(status["network_events"]) == 120
    assert status["network_events"][0]["url"].endswith("i=5")
    assert status["network_events"][-1]["status"] == 200
    assert status["network_events"][-1]["timestamp"] is not None


def test_agent_console_rejects_other_task_step(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    result = service.update_task_step(
        task_id=8,
        step_code="PRECHECK_CONFIG",
        step_name="启动前配置校验",
    )

    assert result["ok"] is False
    assert result["updated"] is False
    assert result["reason"] == "task_mismatch"
    assert result["task_id"] == 7


def test_agent_console_start_rejects_missing_task(tmp_path, monkeypatch):
    client, _repo, service = _client_with_temp_repo_and_console(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent-console/start",
        json={"task_id": 999999, "launch_browser": False},
    )

    assert response.status_code == 404
    service.stop()


def _client_with_temp_repo_and_console(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-console.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    repo = Repository()
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()

    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "agent_console_service", service)
    return TestClient(app), repo, service


def _create_task(repo: Repository):
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "ACG Stand Product",
            "source": "test",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {},
        }
    )
    return repo.create_task(
        {
            "name": "agent console task",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang"},
        }
    )


class _FakePage:
    url = "https://www.dianxiaomi.com/web/home"
    brought_to_front = False

    def __init__(self):
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()
        self.goto_calls = []
        self.locator_calls = []
        self.locators = {}
        self.screenshot_full_page = None

    def title(self):
        return "店小秘 Home"

    def screenshot(self, *, path: str, full_page: bool):
        self.screenshot_full_page = full_page
        with open(path, "wb") as handle:
            handle.write(b"fake-png")

    def bring_to_front(self):
        self.brought_to_front = True

    def goto(self, url: str, *, wait_until: str, timeout: int):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url

    def wait_for_timeout(self, milliseconds: int):
        assert milliseconds >= 0

    def locator(self, selector: str):
        self.locator_calls.append(selector)
        locator = self.locators.get(selector)
        if locator is None:
            locator = _FakeLocator()
            self.locators[selector] = locator
        return locator


class _ThreadBoundFakePage:
    @property
    def url(self):
        raise RuntimeError("Cannot switch to a different thread")

    def title(self):
        raise RuntimeError("Cannot switch to a different thread")


class _SlowTitleLaunchPage:
    url = "https://www.dianxiaomi.com/"

    def __init__(self):
        self.title_started = threading.Event()
        self.title_release = threading.Event()

    def on(self, event_name, callback):
        assert event_name in {"request", "response"}

    def add_init_script(self, script):
        assert script

    def goto(self, url: str, *, wait_until: str, timeout: int):
        self.url = url

    def evaluate(self, script, payload):
        assert payload["state"] == "WAITING"

    def title(self):
        self.title_started.set()
        self.title_release.wait(timeout=5)
        return "店小秘ERP"


class _FakeContextForLaunch:
    def __init__(self, page):
        self.pages = [page]

    def new_page(self):
        return self.pages[0]

    def close(self):
        pass


class _FakeChromiumForLaunch:
    def __init__(self, page):
        self.page = page

    def launch_persistent_context(self, profile_dir, **options):
        return _FakeContextForLaunch(self.page)


class _FakePlaywrightForLaunch:
    def __init__(self, page):
        self.chromium = _FakeChromiumForLaunch(page)

    def stop(self):
        pass


class _FakeMouse:
    def __init__(self):
        self.clicks = []
        self.wheels = []

    def click(self, x: int, y: int):
        self.clicks.append((x, y))

    def wheel(self, delta_x: int, delta_y: int):
        self.wheels.append((delta_x, delta_y))


class _FakeKeyboard:
    def __init__(self):
        self.typed = []
        self.pressed = []

    def type(self, text: str):
        self.typed.append(text)

    def press(self, key: str):
        self.pressed.append(key)


class _FakeLocator:
    def __init__(self):
        self.clicks = []
        self.fills = []

    def click(self, *, timeout: int):
        self.clicks.append(timeout)

    def fill(self, text: str, *, timeout: int):
        self.fills.append((text, timeout))
