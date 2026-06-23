from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository


def _client_with_temp_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "acquisition-claim-workflow.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    repo = Repository()
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    return TestClient(app), repo


def test_acquisition_claim_request_creates_claim_stage_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")

    response = client.post(
        "/api/acquisition/claim-requests",
        json={
            "store_id": store["id"],
            "keyword": "Hazbin Hotel",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "pending_acquisition_claim"
    assert data["status"] == "pending"
    assert data["store_id"] == store["id"]
    assert data["keyword"] == "Hazbin Hotel"
    assert data["category_name"] == "立牌类谷子"
    assert data["claim_mark"] == "AI-OPS"
    assert data["task_id"] > 0

    task = repo.get_task_private(data["task_id"])
    assert task["mode"] == "claim_only"
    assert task["payload"]["stage"] == "pending_acquisition_claim"
    assert task["payload"]["status"] == "pending"


def test_single_save_task_requires_claimed_draft_product(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "真实采集商品 A",
            "source": "manual_import",
            "status": "draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "manual_import"},
        }
    )

    response = client.post(
        "/api/tasks",
        json={
            "name": "单商品只保存 - Dang Kang - 1 件商品",
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "store_id": store["id"],
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "采集认领" in detail
    assert "采集箱" in detail


def test_single_save_task_accepts_claimed_draft_product(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "真实采集商品 A",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "draft_box_verified": True},
        }
    )

    response = client.post(
        "/api/tasks",
        json={
            "name": "单商品只保存 - Dang Kang - 1 件商品",
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "store_id": store["id"],
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
        },
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "single_save"
