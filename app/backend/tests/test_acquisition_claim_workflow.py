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
    assert repo.list_products(include_fixtures=True) == []


def test_mark_acquisition_claim_completed_updates_failed_job_state(tmp_path, monkeypatch):
    _client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    with db.connection() as conn:
        conn.execute(
            """
            UPDATE jobs
               SET status='failed',
                   current_step_code='FAILED',
                   current_step_name='执行失败',
                   error_code='E901',
                   error_message='确认商品箱超时'
             WHERE task_id=?
            """,
            (claim_task["id"],),
        )
    product = repo.create_product(
        {
            "title": "真实待认领商品 A",
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
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )

    refreshed = repo.mark_acquisition_claim_completed(claim_task["id"], product)

    assert refreshed["status"] == "completed"
    assert refreshed["completed_jobs"] == 1
    assert refreshed["failed_jobs"] == 0
    assert refreshed["jobs"][0]["status"] == "completed"
    assert refreshed["jobs"][0]["current_step_code"] == "VERIFY_DRAFT_BOX_CLAIM"
    assert refreshed["jobs"][0]["error_code"] is None
    assert refreshed["jobs"][0]["error_message"] is None


def test_acquisition_claim_request_accepts_source_url_only_match_hint(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"

    response = client.post(
        "/api/acquisition/claim-requests",
        json={
            "store_id": store["id"],
            "source_url": source_url,
            "claim_mark": "AI-OPS",
            "template_id": None,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "pending_acquisition_claim"
    assert data["source_url"] == source_url
    assert data["keyword"] is None
    assert data["category_name"] is None
    task = repo.get_task_private(data["task_id"])
    assert task["mode"] == "claim_only"
    assert task["payload"]["source_url"] == source_url
    assert repo.list_products(include_fixtures=True) == []


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
    assert "已有待认领商品" in response.json()["detail"]
    assert "商品关键词" in response.json()["detail"]
    assert "商品类目" in response.json()["detail"]
    assert "选择一条待认领商品" in response.json()["detail"]
    assert "来源链接" not in response.json()["detail"]


def test_single_save_task_requires_claimed_draft_product(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "真实待认领商品 A",
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
    assert "待认领商品" in detail or "已有待认领" in detail
    assert "商品箱" in detail


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
    assert "已有待认领商品" in response.json()["detail"]


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
    assert "商品箱" in response.json()["detail"]


def test_single_save_task_accepts_claimed_draft_product(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": None,
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product = repo.create_product(
        {
            "title": "真实待认领商品 A",
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
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )
    repo.mark_acquisition_claim_completed(claim_task["id"], product)

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
    assert "已有待认领列表" in detail
    assert "商品箱编辑保存" in detail


def test_single_save_task_snapshots_acquisition_claim_proof(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": None,
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product = repo.create_product(
        {
            "title": "真实待认领商品 A",
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
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )
    repo.mark_acquisition_claim_completed(claim_task["id"], product)

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
    assert task_payload["claimed_product_title"] == "真实待认领商品 A"
    assert task_payload["claimed_product_status"] == "claimed_to_draft"
    assert task_payload["claimed_product_source"] == "dxm_data_acquisition"
    assert task_payload["claimed_product_source_url"] == "https://detail.1688.com/offer/1013604102950.html"
    assert task_payload["claimed_product_category_name"] == "立牌类谷子"
    assert task_payload["claim_task_id"] == claim_task["id"]
    assert task_payload["draft_box_verified"] is True


def test_claimed_products_endpoint_returns_only_verified_real_claimed_products(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": None,
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    valid = repo.create_product(
        {
            "title": "真实待认领商品 A",
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
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )
    repo.mark_acquisition_claim_completed(claim_task["id"], valid)
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
    repo.create_product(
        {
            "title": "无源链接采集商品",
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
                "claim_task_id": 43,
                "draft_box_verified": True,
            },
        }
    )

    response = client.get("/api/acquisition/claimed-products")

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data] == [valid["id"]]
    assert data[0]["payload"]["store_id"] == store["id"]
    assert data[0]["payload"]["store_name"] == "Dang Kang"
    assert data[0]["payload"]["draft_box_verified"] is True
    assert data[0]["lifecycle_state"] == "editable"
    assert data[0]["lifecycle_label"] == "可编辑商品"
    assert data[0]["source_status_label"] == "店小秘已有待认领商品"
    assert data[0]["draft_box_verification_label"] == "已确认进入商品箱"
    assert data[0]["source_url"] == "https://detail.1688.com/offer/1013604102950.html"
    assert data[0]["claim_task_id"] == claim_task["id"]
    assert data[0]["store_name"] == "Dang Kang"


def test_claimed_products_keeps_verified_real_claim_with_qa_category_placeholder(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1057791519266.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": source_url,
            "keyword": "正版玩具总动员攀爬吊饰钥匙扣挂件",
            "category_name": "QA_CATEGORY",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product = repo.create_product(
        {
            "title": "正版玩具总动员攀爬吊饰钥匙扣挂件",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "QA_CATEGORY",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": "Dang Kang",
                "source_url": source_url,
                "source_urls": [source_url],
                "claim_task_id": claim_task["id"],
                "claim_mark": "AI-OPS",
                "draft_box_verified": True,
            },
        }
    )
    repo.mark_acquisition_claim_completed(claim_task["id"], product)

    products = repo.list_products()
    claimed = repo.list_claimed_draft_products()
    response = client.get("/api/acquisition/claimed-products")

    assert [item["id"] for item in products] == [product["id"]]
    assert [item["id"] for item in claimed] == [product["id"]]
    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data] == [product["id"]]
    assert data[0]["source_status_label"] == "店小秘已有待认领商品"
    assert data[0]["lifecycle_state"] == "editable"


def test_claimed_products_endpoint_requires_completed_claim_task_provenance(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "keyword": None,
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product_without_claim_task = repo.create_product(
        {
            "title": "缺少认领任务链商品",
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
                "draft_box_verified": True,
            },
        }
    )
    product_with_pending_claim_task = repo.create_product(
        {
            "title": "认领任务未完成商品",
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
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )

    response = client.get("/api/acquisition/claimed-products")

    assert response.status_code == 200
    product_ids = [item["id"] for item in response.json()]
    assert product_without_claim_task["id"] not in product_ids
    assert product_with_pending_claim_task["id"] not in product_ids


def test_single_save_task_rejects_product_without_completed_claim_task_provenance(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "伪造采集链商品",
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
    assert "待认领商品任务链" in response.json()["detail"] or "已完成的待认领商品任务" in response.json()["detail"]


def test_products_endpoint_returns_customer_lifecycle_labels(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    repo.create_product(
        {
            "title": "待认领商品",
            "source": "dxm_data_acquisition",
            "status": "draft",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "store_name": "Dang Kang"},
        }
    )
    repo.create_product(
        {
            "title": "已认领待验证商品",
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
                "source_url": "https://detail.1688.com/offer/100.html",
                "claim_task_id": 100,
                "draft_box_verified": False,
            },
        }
    )
    repo.create_product(
        {
            "title": "可编辑商品",
            "source": "dxm_data_acquisition",
            "status": "ready_for_edit",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": "Dang Kang",
                "source_url": "https://detail.1688.com/offer/101.html",
                "claim_task_id": 101,
                "draft_box_verified": True,
            },
        }
    )
    repo.create_product(
        {
            "title": "已保存结果",
            "source": "dxm_data_acquisition",
            "status": "saved",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": "Dang Kang",
                "source_url": "https://detail.1688.com/offer/102.html",
                "draft_box_verified": True,
            },
        }
    )

    response = client.get("/api/products")

    assert response.status_code == 200
    by_title = {item["title"]: item for item in response.json()}
    assert by_title["待认领商品"]["lifecycle_state"] == "awaiting_claim"
    assert by_title["待认领商品"]["lifecycle_label"] == "待认领商品"
    assert by_title["已认领待验证商品"]["lifecycle_state"] == "claimed"
    assert by_title["已认领待验证商品"]["lifecycle_label"] == "已认领商品"
    assert by_title["可编辑商品"]["lifecycle_state"] == "editable"
    assert by_title["可编辑商品"]["lifecycle_label"] == "可编辑商品"
    assert by_title["可编辑商品"]["draft_box_verification_label"] == "已确认进入商品箱"
    assert by_title["可编辑商品"]["source_status_label"] == "店小秘已有待认领商品"
    assert by_title["可编辑商品"]["source_url"] == "https://detail.1688.com/offer/101.html"
    assert by_title["已保存结果"]["lifecycle_state"] == "saved"
    assert by_title["已保存结果"]["lifecycle_label"] == "已保存结果"
