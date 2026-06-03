from fastapi.testclient import TestClient

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
    assert status["page_title"] == "店小秘 Home"


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

    def title(self):
        return "店小秘 Home"

    def screenshot(self, *, path: str, full_page: bool):
        assert full_page is True
        with open(path, "wb") as handle:
            handle.write(b"fake-png")

    def bring_to_front(self):
        self.brought_to_front = True
