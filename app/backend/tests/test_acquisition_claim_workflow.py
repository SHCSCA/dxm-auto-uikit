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
    assert task["total_jobs"] == 1
    assert len(task["jobs"]) == 1
    assert task["jobs"][0]["product_id"] is None
    assert task["payload"]["stage"] == "pending_acquisition_claim"
    assert task["payload"]["status"] == "pending"


def test_acquisition_claim_request_requires_product_hint(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")

    response = client.post(
        "/api/acquisition/claim-requests",
        json={
            "store_id": store["id"],
            "keyword": "   ",
            "category_name": "",
            "claim_mark": "AI-OPS",
            "template_id": None,
        },
    )

    assert response.status_code == 400
    assert "搜索关键词或认领类目" in response.json()["detail"]


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


def test_single_save_task_rejects_spoofed_claimed_status_without_dxm_source(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "手工伪造采集箱状态商品",
            "source": "manual_import",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "manual_import", "draft_box_verified": True},
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
    assert "真实数据采集认领" in response.json()["detail"]


def test_single_save_task_rejects_claimed_product_without_draft_box_verification(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "未验证采集箱商品",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "draft_box_verified": False},
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
    assert "采集箱验证" in response.json()["detail"]


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


def test_single_save_task_rejects_fixture_even_when_claimed_flags_present(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "QA guarded product",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "source_url": "https://detail.1688.com/offer/fixture.html",
                "draft_box_verified": True,
            },
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
    assert "测试/示例数据" in detail
    assert "数据采集" in detail
    assert "采集箱编辑保存" in detail


def test_single_save_task_snapshots_acquisition_claim_proof(tmp_path, monkeypatch):
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
            "payload": {
                "source": "dxm_data_acquisition",
                "source_url": "https://detail.1688.com/offer/1013604102950.html",
                "claim_task_id": 42,
                "draft_box_verified": True,
            },
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
    task_payload = response.json()["payload"]
    assert task_payload["claimed_product_id"] == product["id"]
    assert task_payload["claimed_product_title"] == "真实采集商品 A"
    assert task_payload["claimed_product_status"] == "claimed_to_draft"
    assert task_payload["claimed_product_source"] == "dxm_data_acquisition"
    assert task_payload["claimed_product_source_url"] == "https://detail.1688.com/offer/1013604102950.html"
    assert task_payload["claimed_product_category_name"] == "立牌类谷子"
    assert task_payload["claim_task_id"] == 42
    assert task_payload["draft_box_verified"] is True


def test_claimed_products_endpoint_returns_only_verified_real_claimed_products(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    valid = repo.create_product(
        {
            "title": "真实采集商品 A",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": "Dang Kang",
                "source_url": "https://detail.1688.com/offer/1013604102950.html",
                "claim_task_id": 42,
                "draft_box_verified": True,
            },
        }
    )
    repo.create_product(
        {
            "title": "手工伪造采集箱状态商品",
            "source": "manual_import",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "manual_import", "draft_box_verified": True},
        }
    )
    repo.create_product(
        {
            "title": "未验证采集箱商品",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "draft_box_verified": False},
        }
    )
    repo.create_product(
        {
            "title": "QA guarded product",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "QA_CATEGORY",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "draft_box_verified": True},
        }
    )

    response = client.get("/api/acquisition/claimed-products")

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data] == [valid["id"]]
    assert data[0]["payload"]["store_id"] == store["id"]
    assert data[0]["payload"]["store_name"] == "Dang Kang"
    assert data[0]["payload"]["draft_box_verified"] is True
