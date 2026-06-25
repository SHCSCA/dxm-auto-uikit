from fastapi.testclient import TestClient
from pathlib import Path
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
            service._page = _FakePage()
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


def test_agent_console_preview_update_preserves_visible_browser_for_same_task(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()

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
        service._page = _FakePage()

    close_calls = []
    monkeypatch.setattr(service, "_close_current_browser", lambda: close_calls.append("closed"))

    preview = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/web/home",
        launch_browser=False,
        step={"state": "SAVE_ONLY", "action": "等待人工确认只保存"},
    )

    assert close_calls == []
    assert preview["session_id"] == initial["session_id"]
    assert preview["profile_dir"] == initial["profile_dir"]
    assert preview["task_id"] == 42
    assert preview["browser_visible"] is True
    assert preview["browser_launching"] is False
    assert preview["current_url"] == "https://www.dianxiaomi.com/web/home"
    assert preview["hud"]["state"] == "SAVE_ONLY"
    assert preview["hud"]["human_action"] == "等待人工确认只保存"


def test_agent_console_preview_for_other_task_does_not_close_or_rebind_visible_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()

    initial = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=False,
        step={"state": "CLAIM_TO_DRAFT_BOX"},
    )
    with service._lock:
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["current_url"] = "https://www.dianxiaomi.com/web/home"
        service._page = _FakePage()

    close_calls = []
    monkeypatch.setattr(service, "_close_current_browser", lambda: close_calls.append("closed"))

    preview = service.start(
        task_id=99,
        target_url="https://www.dianxiaomi.com/web/home",
        launch_browser=False,
        step={"state": "SAVE_ONLY"},
    )

    assert close_calls == []
    assert preview["session_id"] == initial["session_id"]
    assert preview["task_id"] == 42
    assert preview["browser_visible"] is True
    assert preview["hud"]["state"] == "CLAIM_TO_DRAFT_BOX"
    assert "已有真实浏览器正在执行任务 #42" in preview["last_error"]


def test_agent_console_launch_for_other_task_does_not_close_visible_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()

    initial = service.start(
        task_id=42,
        target_url="https://www.dianxiaomi.com/",
        launch_browser=False,
        step={"state": "CLAIM_TO_DRAFT_BOX"},
    )
    fake_page = _FakePage()
    with service._lock:
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["current_url"] = "https://www.dianxiaomi.com/web/home"
        service._page = fake_page

    close_calls = []
    monkeypatch.setattr(service, "_close_current_browser", lambda: close_calls.append("closed"))

    blocked = service.start(
        task_id=99,
        target_url="https://www.dianxiaomi.com/web/home",
        launch_browser=True,
        step={"state": "SAVE_ONLY"},
    )

    assert close_calls == []
    assert blocked["session_id"] == initial["session_id"]
    assert blocked["task_id"] == 42
    assert blocked["browser_visible"] is True
    assert blocked["browser_launching"] is False
    assert blocked["hud"]["state"] == "BROWSER_BUSY"
    assert blocked["hud"]["requires_user_action"] is True
    assert "已有真实浏览器正在执行任务 #42" in blocked["last_error"]
    assert fake_page.evaluate_calls


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
        json={
            "step": {
                "state": "OPEN_DRAFT_BOX",
                "action": "打开采集箱",
                "line1": "进入店小秘采集箱",
                "line2": "店铺：Dang Kang",
                "next_step": "定位备注商品",
                "maintenance_detail": "api accepted extended hud fields",
            }
        },
    )

    assert hud_response.status_code == 200
    hud = hud_response.json()["hud"]
    assert hud["state"] == "OPEN_DRAFT_BOX"
    assert hud["line1"] == "进入店小秘采集箱"
    assert hud["line2"] == "店铺：Dang Kang"
    assert hud["maintenance_detail"] == "api accepted extended hud fields"

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
        guard="只保存不发布",
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


def test_agent_console_hud_extends_old_payload_with_chinese_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()

    status = service.start(
        task_id=7,
        launch_browser=False,
        step={"state": "SAVE_ONLY", "action": "等待保存证据", "next_step": "确认未发布"},
    )

    hud = status["hud"]
    assert hud["title"] == "正在只保存"
    assert hud["state"] == "SAVE_ONLY"
    assert hud["phase"] == "第二段：采集箱编辑保存"
    assert hud["severity"] == "running"
    assert hud["line1"] == "只点击保存，不发布"
    assert hud["human_title"] == "正在只保存"
    assert hud["human_action"] == "等待保存证据"
    assert hud["human_next"] == "确认未发布"
    assert hud["recent_actions"] == []
    assert hud["requires_user_action"] is False


def test_agent_console_hud_script_renders_black_top_left_business_progress():
    script = agent_console_module.HUD_INIT_SCRIPT

    assert "'left:12px'" in script
    assert "'top:max(86px, env(safe-area-inset-top, 0px))'" in script
    assert "'width:min(280px, calc(100vw - 24px))'" in script
    assert "'max-height:min(230px, calc(100vh - 110px))'" in script
    assert "'box-sizing:border-box'" in script
    assert "'overflow:hidden'" in script
    assert "'background:rgba(13,17,23,.94)'" in script
    assert "'right:18px'" not in script
    assert "'top:14px'" not in script
    assert "'width:330px'" not in script
    assert "pointer-events:none" in script
    assert "human_title" in script
    assert "human_action" in script
    assert "human_next" in script
    assert "recent_actions" in script
    assert "progress_index" in script
    assert "progress_total" in script
    assert "DXM Agent" in script
    assert "自动执行中" in script
    assert "等待人工处理" in script
    assert "只保存不发布" in script


def test_agent_console_hud_persists_latest_business_progress_across_navigation():
    script = agent_console_module.HUD_INIT_SCRIPT
    source = (Path(__file__).resolve().parents[1] / "src" / "services" / "agent_console.py").read_text(encoding="utf-8")

    assert "__dxmAgentHudPersistedState" in script
    assert "sessionStorage.getItem('__dxmAgentHudPersistedState')" in script
    assert "localStorage.getItem('__dxmAgentHudPersistedState')" in script
    assert "sessionStorage.setItem('__dxmAgentHudPersistedState'" in source
    assert "localStorage.setItem('__dxmAgentHudPersistedState'" in source
    assert "window.__dxmAgentHudState = persisted || window.__dxmAgentHudState || {}" in script
    assert "window.__dxmAgentHudObserver" in script
    assert "new MutationObserver" in script
    assert "window.__dxmAgentHudWatchdog" in script
    assert "window.setInterval" in script
    assert "root.dataset.dxmAgentHud = 'active'" in script
    assert "root.dataset.dxmAgentHud !== 'active'" in script
    assert "root.style.cssText = rootStyle" in script
    assert "const hudNeedsRepair" in script
    assert "window.getComputedStyle(root)" in script
    assert "root.getBoundingClientRect()" in script
    assert "style.display === 'none'" in script
    assert "style.visibility === 'hidden'" in script
    assert "Number(style.opacity || 0) < 0.1" in script
    assert "zIndex < 2147483000" in script
    assert "rect.width < 120" in script
    assert "rect.height < 60" in script
    assert "if (root) root.remove()" in script
    assert "page.evaluate(HUD_INIT_SCRIPT)" in source


def test_agent_console_reinjects_hud_on_new_pages_and_navigation():
    source = (Path(__file__).resolve().parents[1] / "src" / "services" / "agent_console.py").read_text(encoding="utf-8")

    assert 'context.on("page"' in source
    assert '"framenavigated"' in source
    assert '"domcontentloaded"' in source
    assert "_reapply_hud_to_page" in source
    assert "_attach_page_runtime_listeners" in source


def test_agent_console_records_recent_actions_on_hud(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    for index in range(5):
        service.record_action_event(
            task_id=7,
            action=f"fill_field_{index}",
            label=f"填写字段 {index}",
            state="FILL_BASE_INFO",
            status="ok",
        )

    hud = service.status()["hud"]
    assert hud["recent_actions"] == ["填写字段 2", "填写字段 3", "填写字段 4"]


def test_agent_console_hud_maps_required_user_actions_to_business_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)

    captcha = service.update_hud({"state": "WAITING_CAPTCHA"})["hud"]
    assert captcha["requires_user_action"] is True
    assert captcha["severity"] == "warning"
    assert captcha["human_title"] == "需要你处理验证码"
    assert captcha["human_action"] == "请在真实店小秘浏览器里完成验证码或二次确认"

    approval = service.update_hud({"state": "MANUAL_APPROVAL_REQUIRED"})["hud"]
    assert approval["requires_user_action"] is True
    assert approval["severity"] == "warning"
    assert approval["human_title"] == "需要你人工确认只保存"
    assert approval["human_next"] == "确认后才会启动真实浏览器保存"

    takeover = service.update_hud({"state": "MANUAL_TAKEOVER"})["hud"]
    assert takeover["requires_user_action"] is True
    assert takeover["severity"] == "warning"
    assert takeover["human_title"] == "需要你接管真实浏览器"
    assert takeover["human_next"] == "处理完成后在控制台交还 Agent"


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


def test_agent_console_status_marks_closed_browser_not_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()
    fake_page.closed = True

    with service._lock:
        service._page = fake_page
        service._state["active"] = True
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["last_error"] = None

    status = service.status()

    assert status["active"] is True
    assert status["browser_visible"] is False
    assert status["browser_launching"] is False
    assert "真实浏览器窗口已关闭" in status["last_error"]
    assert status["hud"]["state"] == "BROWSER_CLOSED"
    assert status["hud"]["requires_user_action"] is True
    assert status["hud"]["human_next"] == "回到执行浏览器重新打开"


def test_agent_console_browser_close_event_marks_closed_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_context = _FakeLifecycleTarget()
    fake_page = _FakeLifecyclePage()

    with service._lock:
        service._context = fake_context
        service._page = fake_page
        service._state["active"] = True
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["last_error"] = None

    service._attach_browser_lifecycle_listeners(fake_context, fake_page)
    fake_page.emit("close")
    status = service.status()

    assert status["browser_visible"] is False
    assert status["browser_launching"] is False
    assert status["last_error"] == "真实浏览器窗口已关闭，请重新打开执行浏览器。"
    assert status["hud"]["state"] == "BROWSER_CLOSED"
    assert status["hud"]["human_title"] == "真实浏览器窗口已关闭"


def test_agent_console_rebinds_current_page_when_dxm_opens_new_page(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False, step={"state": "OPEN_DRAFT_LIST"})
    fake_context = _FakeLifecycleTarget()
    old_page = _FakeLifecyclePage()
    new_page = _FakeLifecyclePage()
    new_page.url = "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0"

    with service._lock:
        service._context = fake_context
        service._page = old_page
        service._state["active"] = True
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["last_error"] = None

    service._attach_page_runtime_listeners(fake_context, old_page)
    fake_context.emit("page", new_page)
    status = service.status()

    assert service._page is new_page
    assert status["browser_visible"] is True
    assert status["current_url"] == new_page.url
    assert new_page.evaluate_calls
    assert status["last_error"] is None


def test_agent_console_does_not_mark_browser_closed_when_old_page_closes_after_rebind(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False, step={"state": "OPEN_DRAFT_LIST"})
    fake_context = _FakeLifecycleTarget()
    old_page = _FakeLifecyclePage()
    new_page = _FakeLifecyclePage()

    with service._lock:
        service._context = fake_context
        service._page = old_page
        service._state["active"] = True
        service._state["browser_visible"] = True
        service._state["browser_launching"] = False
        service._state["last_error"] = None

    service._attach_page_runtime_listeners(fake_context, old_page)
    fake_context.emit("page", new_page)
    old_page.closed = True
    old_page.emit("close")
    status = service.status()

    assert service._page is new_page
    assert status["browser_visible"] is True
    assert status["last_error"] is None
    assert status["hud"]["state"] != "BROWSER_CLOSED"


def test_agent_console_rejects_browser_control_after_window_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()
    fake_page.closed = True

    with service._lock:
        service._page = fake_page
        service._state["active"] = True
        service._state["browser_visible"] = True

    result = service.control_browser({"action": "scroll", "delta_y": 360})

    assert result["ok"] is False
    assert result["reason"] == "browser_window_not_visible"
    assert result["browser_visible"] is False
    assert fake_page.mouse.wheels == []


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
    assert takeover["hud"]["state"] == "MANUAL_TAKEOVER"
    assert takeover["hud"]["requires_user_action"] is True
    assert takeover["hud"]["human_title"] == "需要你接管真实浏览器"

    released = service.release_manual_takeover()

    assert released["manual_takeover"] is False
    assert released["manual_takeover_started_at"] is None
    assert released["action_events"][-1]["action"] == "release_agent"
    assert released["hud"]["requires_user_action"] is False


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
    assert "approved task flow or manual takeover" in clicked["error"]
    assert "approved task flow or manual takeover" in typed["error"]
    assert "approved task flow or manual takeover" in pressed["error"]
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


def test_agent_console_rejects_selector_browser_controls_until_guarded(tmp_path, monkeypatch):
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

    assert clicked["ok"] is False
    assert filled["ok"] is False
    assert clicked["reason"] == "browser_control_failed"
    assert filled["reason"] == "browser_control_failed"
    assert "selector browser controls are disabled" in clicked["error"]
    assert "selector browser controls are disabled" in filled["error"]
    assert fake_page.locator_calls == []
    status = service.status()
    assert status["action_events"][-1]["type"] == "browser_control"
    assert status["action_events"][-1]["action"] == "selector_fill"
    assert status["action_events"][-1]["status"] == "error"
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
    assert "selector browser controls are disabled" in result["error"]
    assert fake_page.locator_calls == []
    assert service.status()["action_events"][-1]["status"] == "error"


def test_agent_console_rejected_selector_fill_preserves_user_text_length_in_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_console_module, "PROFILE_ROOT", tmp_path / "profiles")
    monkeypatch.setattr(agent_console_module, "SCREENSHOT_ROOT", tmp_path / "screenshots")
    service = AgentConsoleService()
    service.start(task_id=7, launch_browser=False)
    fake_page = _FakePage()

    with service._lock:
        service._page = fake_page
        service._state["browser_visible"] = True

    result = service.control_browser({"action": "selector_fill", "selector": "[name='title']", "text": "  DXM title  "})

    assert result["ok"] is False
    assert result["reason"] == "browser_control_failed"
    assert "text_length=13" in result["error"]
    assert fake_page.locator_calls == []
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
    assert "approved task flow or manual takeover" in payload["error"]
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
        self.closed = False

    def is_closed(self):
        return self.closed

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

    def add_init_script(self, script):
        assert script

    def evaluate(self, script, payload=None):
        if not hasattr(self, "evaluate_calls"):
            self.evaluate_calls = []
        self.evaluate_calls.append((script, payload))
        return None

    def locator(self, selector: str):
        self.locator_calls.append(selector)
        locator = self.locators.get(selector)
        if locator is None:
            locator = _FakeLocator()
            self.locators[selector] = locator
        return locator


class _FakeLifecycleTarget:
    def __init__(self):
        self.handlers = {}

    def on(self, event_name, callback):
        self.handlers.setdefault(event_name, []).append(callback)

    def emit(self, event_name, *args):
        for callback in self.handlers.get(event_name, []):
            callback(*args)


class _FakeLifecyclePage(_FakePage, _FakeLifecycleTarget):
    def __init__(self):
        _FakePage.__init__(self)
        _FakeLifecycleTarget.__init__(self)


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
