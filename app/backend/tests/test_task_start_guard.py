from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository


class DummyRunner:
    def __init__(self):
        self.calls: list[int] = []

    async def run_task(self, task_id: int):
        self.calls.append(task_id)


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


def test_single_save_start_requires_manual_approval(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 403
    assert runner.calls == []


def test_single_save_start_accepts_matching_manual_approval_token(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, approval={"approved": True, "token": "l3-token"})

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
