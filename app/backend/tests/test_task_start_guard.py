from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository


class DummyRunner:
    def __init__(self):
        self.calls: list[int] = []

    async def run_task(self, task_id: int):
        self.calls.append(task_id)


class DummyDxmLoginFlow:
    def __init__(self):
        self.draft_box_actions: list[tuple[str, str | None, str | None, str | None]] = []

    def perform_draft_box_action(self, action, note_text=None, product_query=None, store_name=None):
        self.draft_box_actions.append((action, note_text, product_query, store_name))
        return {"stage": "draft_box_action", "action": action}


def _client_with_temp_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "task-start-guard.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    repo = Repository()
    runner = DummyRunner()
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "runner", runner)
    return TestClient(app), repo, runner


def _create_task(repo: Repository, *, mode: str = "single_save", store_name: str = "Dang Kang", approval: dict | None = None):
    store = repo.create_store(store_name, "AliExpress")
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
    payload = {"store_name": store_name}
    if approval is not None:
        payload["manual_approval"] = approval
    return repo.create_task(
        {
            "name": "guarded task",
            "store_id": store["id"],
            "mode": mode,
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": payload,
        }
    )


def _approve_task(repo: Repository, task_id: int, token: str):
    repo.set_task_manual_approval(task_id, approved=True, token=token)


def test_single_save_start_requires_manual_approval(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 403
    assert runner.calls == []


def test_claim_only_start_requires_same_real_mutation_gate(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "not_run"})
    task = _create_task(repo, mode="claim_only")

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 403
    assert "Manual approval is required" in response.json()["detail"]
    assert runner.calls == []


def test_claim_only_start_rejects_when_l2_gate_not_passed_after_approval(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})
    task = _create_task(repo, mode="claim_only")
    _approve_task(repo, task["id"], "claim-token")

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "claim-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 403
    assert "L2 readonly probe gate is not passed: failed" in response.json()["detail"]
    assert runner.calls == []


def test_single_save_start_accepts_matching_manual_approval_token(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert repo.get_task(task["id"])["status"] == "running"


def test_real_save_start_cannot_be_triggered_twice(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")
    payload = {
        "manual_approval": True,
        "approval_token": "l3-token",
        "approved_by": "ops-owner",
        "confirmation": "CONFIRM_DXM_SAVE_ONLY",
    }

    first = client.post(f"/api/tasks/{task['id']}/start", json=payload)
    second = client.post(f"/api/tasks/{task['id']}/start", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Task is already running"


def test_completed_real_save_task_cannot_be_restarted(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")
    repo.update_task_status(task["id"], "completed")

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert runner.calls == []


def test_completed_real_save_task_cannot_be_paused_then_restarted(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")
    repo.update_task_status(task["id"], "completed")
    payload = {
        "manual_approval": True,
        "approval_token": "l3-token",
        "approved_by": "ops-owner",
        "confirmation": "CONFIRM_DXM_SAVE_ONLY",
    }

    pause_response = client.post(f"/api/tasks/{task['id']}/pause")
    start_response = client.post(f"/api/tasks/{task['id']}/start", json=payload)

    assert pause_response.status_code == 409
    assert "pause is disabled" in pause_response.json()["detail"]
    assert start_response.status_code == 409
    assert repo.get_task(task["id"])["status"] == "completed"
    assert runner.calls == []


def test_running_real_save_task_cannot_be_paused_or_restarted(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")
    first = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )
    pause_response = client.post(f"/api/tasks/{task['id']}/pause")
    second = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert first.status_code == 200
    assert pause_response.status_code == 409
    assert "pause is disabled" in pause_response.json()["detail"]
    assert second.status_code == 409
    assert repo.get_task(task["id"])["status"] == "running"
    assert runner.calls == [task["id"]]


def test_resume_is_disabled_without_worker_acknowledgement(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")
    repo.update_task_status(task["id"], "paused")

    response = client.post(f"/api/tasks/{task['id']}/resume")

    assert response.status_code == 409
    assert "Resume is disabled" in response.json()["detail"]


def test_agent_console_start_requires_passed_l2_gate(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})
    task = _create_task(repo, mode="dry_run")

    response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

    assert response.status_code == 403
    assert "Agent console browser start requires passed L2" in response.json()["detail"]


def test_manual_approval_token_is_not_exposed_by_read_apis(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "secret-l3-token")

    task_payload = client.get(f"/api/tasks/{task['id']}").json()["payload"]
    list_payload = client.get("/api/tasks").json()[0]["payload"]
    workspace_payload = client.get(f"/api/delivery/workspace?task_id={task['id']}").json()["current_task"]["payload"]

    for payload in (task_payload, list_payload, workspace_payload):
        approval = payload.get("manual_approval") or {}
        assert approval.get("approved") is True
        assert "token" not in approval
        assert "token_hash" not in approval

    leaked_fields = dict(workspace_payload.get("manual_approval") or {})
    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": leaked_fields.get("token"),
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 403
    assert runner.calls == []


def test_paused_real_save_task_cannot_be_restarted_with_current_gate_and_approval(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _approve_task(repo, task["id"], "l3-token")
    repo.update_task_status(task["id"], "paused")

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 409
    assert repo.get_task(task["id"])["status"] == "paused"
    assert runner.calls == []


def test_create_task_payload_cannot_preapprove_real_save(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, approval={"approved": True, "token": "user-injected-token"})

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "user-injected-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 403
    assert runner.calls == []


def test_existing_payload_approval_without_server_source_is_rejected(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    from src import db

    payload = repo.get_task(task["id"])["payload"]
    payload["manual_approval"] = {"approved": True, "token": "legacy-token"}
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task["id"]),
        )

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "legacy-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 403
    assert runner.calls == []


def test_real_save_start_rejects_when_l2_gate_not_passed(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    for status in ("not_run", "mock_passed", "partial", "failed"):
        monkeypatch.setattr(main, "l2_real_probe_gate", lambda status=status: {"status": status})
        for mode in ("claim_only", "single_save", "batch_save"):
            task = _create_task(repo, mode=mode)
            _approve_task(repo, task["id"], f"l3-token-{status}-{mode}")

            response = client.post(
                f"/api/tasks/{task['id']}/start",
                json={
                    "manual_approval": True,
                    "approval_token": f"l3-token-{status}-{mode}",
                    "approved_by": "ops-owner",
                    "confirmation": "CONFIRM_DXM_SAVE_ONLY",
                },
            )

            assert response.status_code == 403
            assert f"L2 readonly probe gate is not passed: {status}" in response.json()["detail"]
            assert task["id"] not in runner.calls


def test_direct_draft_box_action_rejects_when_l2_gate_not_passed(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    monkeypatch.setattr(main, "login_flow", flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})

    response = client.post(
        "/api/dxm/draft-box/action",
        json={"action": "remark", "note_text": "AI认领", "store_name": "Dang Kang"},
    )

    assert response.status_code == 403
    assert "Direct real DXM mutation requires an approved guarded task" in response.json()["detail"]
    assert flow.draft_box_actions == []


def test_direct_claim_product_rejects_when_l2_gate_not_passed(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    monkeypatch.setattr(main, "login_flow", flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})

    response = client.post(
        "/api/dxm/workflow/claim-product",
        json={"action": "remark", "note_text": "AI认领", "store_name": "Dang Kang"},
    )

    assert response.status_code == 403
    assert "Direct real DXM mutation requires an approved guarded task" in response.json()["detail"]
    assert flow.draft_box_actions == []


def test_direct_real_dxm_mutation_rejects_approved_task_when_l2_gate_not_passed(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    task = _create_task(repo, mode="claim_only")
    _approve_task(repo, task["id"], "direct-token")
    monkeypatch.setattr(main, "login_flow", flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})

    approval = {
        "task_id": task["id"],
        "manual_approval": True,
        "approval_token": "direct-token",
        "approved_by": "ops-owner",
        "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        "store_name": "Dang Kang",
    }

    draft_response = client.post(
        "/api/dxm/draft-box/action",
        json={"action": "remark", "note_text": "AI认领", **approval},
    )
    claim_response = client.post(
        "/api/dxm/workflow/claim-product",
        json={"action": "remark", "note_text": "AI认领", **approval},
    )

    assert draft_response.status_code == 403
    assert claim_response.status_code == 403
    assert "L2 readonly probe gate is not passed: failed" in draft_response.json()["detail"]
    assert "L2 readonly probe gate is not passed: failed" in claim_response.json()["detail"]
    assert flow.draft_box_actions == []


def test_direct_real_dxm_mutation_rejects_even_after_l2_and_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    task = _create_task(repo, mode="claim_only")
    _approve_task(repo, task["id"], "direct-token")
    monkeypatch.setattr(main, "login_flow", flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})

    response = client.post(
        "/api/dxm/draft-box/action",
        json={
            "action": "remark",
            "note_text": "AI认领",
            "task_id": task["id"],
            "manual_approval": True,
            "approval_token": "direct-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
            "store_name": "Dang Kang",
        },
    )

    assert response.status_code == 403
    assert "task runner evidence chain" in response.json()["detail"]
    assert flow.draft_box_actions == []


def test_direct_open_editor_rejects_without_guarded_runner(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    monkeypatch.setattr(main, "login_flow", flow)

    response = client.post("/api/dxm/workflow/open-editor", json={"action": "edit"})

    assert response.status_code == 403
    assert flow.draft_box_actions == []


def test_single_save_start_rejects_non_dang_kang_store(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, store_name="Other Store", approval={"approved": True, "token": "l3-token"})

    response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": "l3-token",
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert response.status_code == 403
    assert runner.calls == []


def test_dry_run_can_start_without_manual_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 200
