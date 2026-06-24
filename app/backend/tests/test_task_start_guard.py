import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from src import db
from src.execution.v1_runner import V1TaskRunner
from src.main import app
from src.repository import Repository
from src.services.config_defaults import ConfigDefaultsResolver

REPO_ROOT = Path(__file__).resolve().parents[1]


class DummyRunner:
    def __init__(self):
        self.calls: list[int] = []

    async def run_task(self, task_id: int):
        self.calls.append(task_id)


class DummyDxmLoginFlow:
    def __init__(self):
        self.draft_box_actions: list[tuple[str, str | None, str | None, str | None, list[str] | None]] = []

    def perform_draft_box_action(
        self,
        action,
        note_text=None,
        product_query=None,
        store_name=None,
        target_source_urls=None,
    ):
        self.draft_box_actions.append((action, note_text, product_query, store_name, target_source_urls))
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


def _create_task(
    repo: Repository,
    *,
    mode: str = "single_save",
    store_name: str = "Dang Kang",
    approval: dict | None = None,
    product_title: str = "ACG Stand Product",
    product_status: str = "claimed_to_draft",
    publish_scene: str = "SMT_SEMI_MANAGED_SAVE_ONLY",
):
    store = repo.create_store(store_name, "AliExpress")
    product = repo.create_product(
        {
            "title": product_title,
            "source": "dxm_data_acquisition",
            "status": product_status,
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition", "draft_box_verified": product_status == "claimed_to_draft"},
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
            "publish_scene": publish_scene,
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": payload,
        }
    )


def _create_claim_request(repo: Repository, *, store_name: str = "Dang Kang"):
    store = repo.create_store(store_name, "AliExpress")
    return repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "keyword": "Hazbin Hotel 立牌",
            "category_name": "立牌类谷子",
            "claim_mark": "AI认领",
            "template_id": None,
        }
    )


def _approve_task(repo: Repository, task_id: int, token: str):
    repo.set_task_manual_approval(task_id, approved=True, token=token)


def _create_required_save_templates(repo: Repository, *, omit_override_backed_fields: bool = False) -> None:
    template_payloads = [
        (
            "category",
            "类目模板",
            {
                "dxm_reference_templates": {
                    "attribute_info": {"names": ["立牌类谷子"]},
                    "description": {"names": ["详情模板"]},
                    "freight": {"names": ["40g普货包裹"]},
                    "service": {"names": ["Service Template for New Sellers"]},
                    "eu_responsible": {"names": ["Jacqueiline Marti"]},
                    "manufacturer": {"names": ["jiyang county thunder"]},
                    "compliance": {"names": ["合规模板"]},
                    "semi_managed": {"names": ["半托管模板"]},
                },
                "category": {"category_keyword": "立牌", "category_match": "ACG Stand"},
            },
        ),
        ("sku", "SKU模板", {"sku": {"sku_code": "610274761685-DK-AD-10CM"}}),
        ("pricing", "价格模板", {"pricing": {"declared_value": "1", "stock": "200", "retail_price": "9.99"}}),
        (
            "logistics",
            "包装物流模板",
            {
                "logistics": {
                    "weight": "0.03",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "delivery_days": "7",
                    "freight_template_priorities": ["40g普货包裹"],
                    "service_template_priorities": ["Service Template for New Sellers"],
                    "logistics_attribute": "普货",
                    "is_original_box": "否",
                }
            },
        ),
        (
            "image",
            "图片模板",
            {
                "image": {
                    "eu_outer_package_filename": "template-eu.jpg",
                    "marketing_images_strategy": "generate",
                }
            },
        ),
        (
            "compliance",
            "合规模板",
            {
                "compliance": {
                    "material": "ABS",
                    "eu_responsible_priorities": ["Jacqueiline Marti"],
                    "manufacturer_priorities": ["jiyang county thunder"],
                    "customs_product_name_priorities": ["钥匙扣", "keychain"],
                }
            },
        ),
        (
            "semi_managed",
            "半托管模板",
            {
                "semi_managed": {
                    "supply_price": "4.20",
                    "jit_stock": "100",
                    "is_original_box": "否",
                    "length": "10",
                    "width": "10",
                    "height": "2",
                    "goods_code_strategy": "allow_blank",
                    "barcode_strategy": "allow_blank",
                }
            },
        ),
    ]
    if omit_override_backed_fields:
        for template_type, _template_name, payload in template_payloads:
            if template_type == "image":
                payload["image"].pop("marketing_images_strategy", None)
            if template_type == "semi_managed":
                payload["semi_managed"].pop("supply_price", None)
                payload["semi_managed"].pop("goods_code_strategy", None)

    for template_type, template_name, payload in template_payloads:
        repo.create_template(
            {
                "template_type": template_type,
                "template_name": template_name,
                "binding_scope": "Dang Kang",
                "payload": payload,
                "is_enabled": True,
            }
        )


def test_create_single_save_rejects_multiple_products(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product_ids = [
        repo.create_product({
            "title": f"Product {index}",
            "source": "test",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {},
        })["id"]
        for index in range(2)
    ]

    response = client.post(
        "/api/tasks",
        json={
            "name": "invalid multi product single save",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": product_ids,
        },
    )

    assert response.status_code == 400
    assert "single_save requires exactly one product" in response.json()["detail"]


def test_main_runner_reuses_login_flow_executor_for_thread_bound_playwright():
    main_source = (REPO_ROOT / "src" / "main.py").read_text(encoding="utf-8")
    runner_section = main_source[main_source.index("runner = V1TaskRunner("):main_source.index("REAL_DXM_MUTATION_MODES")]

    assert "login_flow_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dxm-login-flow')" in main_source
    assert "workflow_executor=login_flow_executor" in runner_section


def test_create_task_api_rejects_unreleased_or_wrong_scene_real_modes(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
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

    claim_response = client.post(
        "/api/tasks",
        json={
            "name": "wrong scene claim",
            "store_id": store["id"],
            "mode": "claim_only",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
        },
    )
    assert claim_response.status_code == 403
    assert "claim-to-draft scene" in claim_response.json()["detail"]

    batch_response = client.post(
        "/api/tasks",
        json={
            "name": "blocked batch",
            "store_id": store["id"],
            "mode": "batch_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
        },
    )
    assert batch_response.status_code == 403
    assert "Only controlled claim_only and single_save are released" in batch_response.json()["detail"]


def test_create_task_api_rejects_claim_only_with_existing_product_ids(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "ACG Stand Product",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {},
        }
    )

    response = client.post(
        "/api/tasks",
        json={
            "name": "wrong claim task",
            "store_id": store["id"],
            "mode": "claim_only",
            "publish_scene": "CONTROLLED_CLAIM_TO_DRAFT_ONLY",
            "product_ids": [product["id"]],
        },
    )

    assert response.status_code == 400
    assert "without existing product_ids" in response.json()["detail"]


def test_start_single_save_rejects_historical_multiple_products(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product_ids = [
        repo.create_product({
            "title": f"Legacy Product {index}",
            "source": "test",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {},
        })["id"]
        for index in range(2)
    ]
    task = repo.create_task({
        "name": "legacy multi product single save",
        "store_id": store["id"],
        "mode": "single_save",
        "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        "claim_mark": "AI认领",
        "product_ids": product_ids,
        "payload": {"store_name": "Dang Kang"},
    })

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 409
    assert "single_save requires exactly one product" in response.json()["detail"]
    assert runner.calls == []


def test_single_save_start_requires_manual_approval(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 403
    assert runner.calls == []


def test_single_save_start_rejects_legacy_non_claimed_product_before_real_browser(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, product_status="draft")

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "采集认领" in detail
    assert "采集箱" in detail
    assert runner.calls == []


def test_claim_only_start_requires_l2_readonly_gate(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "not_run"})
    task = _create_claim_request(repo)

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 403
    assert "L2 readonly probe gate is not passed: not_run" in response.json()["detail"]
    assert runner.calls == []


def test_claim_only_start_is_released_for_controlled_acquisition_claim(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_claim_request(repo)

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert runner.calls == [task["id"]]


def test_claim_only_start_rejects_existing_product_job_shape(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(
        repo,
        mode="claim_only",
        publish_scene="CONTROLLED_CLAIM_TO_DRAFT_ONLY",
    )

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 409
    assert "cannot use existing product_ids" in response.json()["detail"]
    assert runner.calls == []


def test_claim_only_start_allows_any_real_store_after_l2_gate(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_claim_request(repo, store_name="Other Store")

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert repo.get_task(task["id"])["status"] == "running"


def test_unreleased_real_modes_reject_manual_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})

    for mode in ("batch_save",):
        task = _create_task(repo, mode=mode)

        response = client.post(
            f"/api/tasks/{task['id']}/manual-approval",
            json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
        )

        assert response.status_code == 403
        detail = response.json()["detail"].lower()
        assert "controlled claim_only and single_save" in detail
        assert "released" in detail


def test_unreleased_real_modes_cannot_start_after_approval_and_l2_passed(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})

    for mode in ("batch_save",):
        task = _create_task(repo, mode=mode)
        _approve_task(repo, task["id"], f"{mode}-token")

        response = client.post(
            f"/api/tasks/{task['id']}/start",
            json={
                "manual_approval": True,
                "approval_token": f"{mode}-token",
                "approved_by": "ops-owner",
                "confirmation": "CONFIRM_DXM_SAVE_ONLY",
            },
        )

        assert response.status_code == 403
        detail = response.json()["detail"].lower()
        assert "controlled claim_only and single_save" in detail
        assert "released" in detail
        assert task["id"] not in runner.calls
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


def test_single_save_start_rejects_qa_fixture_product_before_real_browser(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, product_title="QA guarded product")
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

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "测试/示例数据" in detail
    assert "数据采集" in detail
    assert "采集箱编辑保存" in detail
    assert runner.calls == []


def test_products_api_hides_fixture_products_in_production(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    repo.create_product(
        {
            "title": "QA guarded product",
            "source": "test",
            "category_name": "QA_CATEGORY",
            "price": 1,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"fixture": True},
        }
    )
    repo.create_product(
        {
            "title": "真实采集商品 A",
            "source": "dxm_data_acquisition",
            "category_name": "立牌类谷子",
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source": "dxm_data_acquisition"},
        }
    )

    response = client.get("/api/products")

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert "真实采集商品 A" in titles
    assert "QA guarded product" not in titles


def test_single_save_start_accepts_task_template_overrides_for_required_fields(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo)
    _create_required_save_templates(repo, omit_override_backed_fields=True)

    missing_before = client.get(f"/api/config/preview?task_id={task['id']}").json()["missing"]
    assert "image.marketing_images_strategy" in missing_before
    assert "semi_managed.product_price_or_supply_price" in missing_before
    assert "semi_managed.goods_code_strategy" in missing_before

    image_response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={"section": "image", "values": {"marketing_images_strategy": "使用商品图补齐营销图"}},
    )
    semi_response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "semi_managed",
            "values": {
                "product_price": "7.01",
                "goods_code_strategy": "沿用店小秘生成",
            },
        },
    )
    assert image_response.status_code == 200
    assert semi_response.status_code == 200

    missing_after = client.get(f"/api/config/preview?task_id={task['id']}").json()["missing"]
    assert "image.marketing_images_strategy" not in missing_after
    assert "semi_managed.product_price_or_supply_price" not in missing_after
    assert "semi_managed.goods_code_strategy" not in missing_after

    approval_response = client.post(
        f"/api/tasks/{task['id']}/manual-approval",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )
    assert approval_response.status_code == 200

    start_response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": approval_response.json()["approvalToken"],
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert start_response.status_code == 200
    assert start_response.json()["ok"] is True
    assert runner.calls == [task["id"]]


def test_manual_approval_endpoint_generates_server_token_and_start_accepts_it(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, store_name="Other Store")

    approval_response = client.post(
        f"/api/tasks/{task['id']}/manual-approval",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )

    assert approval_response.status_code == 200
    approval_payload = approval_response.json()
    token = approval_payload["approvalToken"]
    assert len(token) >= 24
    assert approval_payload["manualApproval"]["approved"] is True
    assert approval_payload["manualApproval"]["source"] == "server"
    assert "token_hash" not in approval_payload["manualApproval"]
    assert "token" not in approval_payload["manualApproval"]

    stored_payload = client.get(f"/api/tasks/{task['id']}").json()["payload"]
    assert "token_hash" not in stored_payload["manual_approval"]

    start_response = client.post(
        f"/api/tasks/{task['id']}/start",
        json={
            "manual_approval": True,
            "approval_token": token,
            "approved_by": "ops-owner",
            "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        },
    )

    assert start_response.status_code == 200
    assert start_response.json()["ok"] is True


def test_manual_approval_endpoint_requires_l2_passed(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})
    task = _create_task(repo)

    response = client.post(
        f"/api/tasks/{task['id']}/manual-approval",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )

    assert response.status_code == 403
    assert "L2 readonly probe gate is not passed: failed" in response.json()["detail"]


def test_manual_approval_endpoint_rejects_non_real_mode(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, mode="dry_run")

    response = client.post(
        f"/api/tasks/{task['id']}/manual-approval",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )

    assert response.status_code == 400
    assert "only available for real DXM mutation modes" in response.json()["detail"]


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


def test_running_real_save_task_cannot_be_stopped_without_worker_ack(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, approval={"approved": True, "token": "l3-token"})
    repo.update_task_status(task["id"], "running")

    response = client.post(f"/api/tasks/{task['id']}/stop")

    assert response.status_code == 409
    assert "stop is disabled" in response.json()["detail"]
    assert repo.get_task(task["id"])["status"] == "running"


def test_stop_task_requires_existing_task(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)

    response = client.post("/api/tasks/999/stop")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_dry_run_task_can_be_stopped(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")
    repo.update_task_status(task["id"], "running")

    response = client.post(f"/api/tasks/{task['id']}/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert repo.get_task(task["id"])["status"] == "cancelled"


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
    task = _create_task(repo, mode="single_save")

    response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

    assert response.status_code == 403
    assert "Agent console browser start requires passed L2" in response.json()["detail"]


def test_agent_console_execution_browser_rejects_non_draft_real_task(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, mode="single_save")
    repo.update_task_status(task["id"], "failed")

    response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

    assert response.status_code == 409
    assert "Task cannot start execution browser from status: failed" in response.json()["detail"]


def test_agent_console_execution_browser_rejects_unreleased_and_non_real_modes(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})

    for mode in ("dry_run", "batch_save"):
        task = _create_task(repo, mode=mode)

        response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

        assert response.status_code == 403
        assert "Only controlled claim_only and single_save are released" in response.json()["detail"]


def test_agent_console_execution_browser_allows_controlled_claim_only_task(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    class DummyAgentConsoleService:
        def start(self, **payload):
            return {"active": True, **payload}

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    monkeypatch.setattr(main, "agent_console_service", DummyAgentConsoleService())
    task = _create_claim_request(repo)

    response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active"] is True
    assert payload["task_id"] == task["id"]


def test_agent_console_execution_browser_allows_claim_only_for_any_real_store(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    class DummyAgentConsoleService:
        def start(self, **payload):
            return {"active": True, **payload}

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    monkeypatch.setattr(main, "agent_console_service", DummyAgentConsoleService())
    task = _create_claim_request(repo, store_name="Other Store")

    response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["active"] is True
    assert payload["task_id"] == task["id"]


def test_runtime_logs_tail_known_log_sources(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    backend_log = tmp_path / "backend.log"
    backend_log.write_text("\n".join(f"line {index}" for index in range(160)), encoding="utf-8")
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"backend": backend_log})

    response = client.get("/api/runtime/logs?source=backend&limit=3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "backend"
    assert payload["exists"] is True
    assert payload["lines"] == ["line 157", "line 158", "line 159"]
    assert [item["line"] for item in payload["items"]] == payload["lines"]
    assert payload["nextCursor"] == backend_log.stat().st_size
    assert payload["modifiedAt"]
    assert payload["ageSeconds"] >= 0
    assert payload["stale"] is False


def test_runtime_logs_flag_stale_launcher_log_without_hiding_tail(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    launcher_log = tmp_path / "start-mvp.log"
    launcher_log.write_text("\n".join([
        "[2026-06-11T01:44:37.738Z] Starting backend on stale port",
        "[2026-06-11T01:44:39.296Z] Loaded frontend from stale build",
    ]), encoding="utf-8")
    stale_mtime = time.time() - (main.RUNTIME_LOG_STALE_SECONDS + 120)
    os.utime(launcher_log, (stale_mtime, stale_mtime))
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"launcher": launcher_log})

    response = client.get("/api/runtime/logs?source=launcher&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "launcher"
    assert payload["exists"] is True
    assert payload["lines"][-1].endswith("Loaded frontend from stale build")
    assert payload["modifiedAt"]
    assert payload["ageSeconds"] >= main.RUNTIME_LOG_STALE_SECONDS
    assert payload["stale"] is True


def test_backend_runtime_startup_records_current_log_marker(tmp_path, monkeypatch):
    import src.main as main

    backend_log = tmp_path / "backend.log"
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"backend": backend_log})

    with TestClient(app) as client:
        response = client.get("/api/runtime/logs?source=backend&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert any("DXM backend runtime started" in line for line in payload["lines"])
    assert payload["stale"] is False


def test_runtime_logs_filter_by_level_and_query_with_tags(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    backend_log = tmp_path / "backend.log"
    backend_log.write_text(
        "\n".join([
            "INFO starting backend",
            "WARNING save response blocked",
            "ERROR failed add.json save",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"backend": backend_log})

    response = client.get("/api/runtime/logs?source=backend&level=error&q=add.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lines"] == ["ERROR failed add.json save"]
    assert payload["items"][0]["level"] == "error"
    assert "保存" in payload["items"][0]["tags"]


def test_runtime_logs_tag_access_polling_noise_without_losing_raw_line(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    backend_log = tmp_path / "backend.log"
    backend_log.write_text(
        "\n".join([
            'INFO:     127.0.0.1:2292 - "GET /api/runtime/logs?source=backend&cursor=1&limit=120 HTTP/1.1" 200 OK',
            'INFO:     127.0.0.1:2292 - "GET /api/tasks HTTP/1.1" 200 OK',
            "ERROR failed add.json save",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"backend": backend_log})

    response = client.get("/api/runtime/logs?source=backend&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["line"].startswith("INFO:")
    assert "access" in payload["items"][0]["tags"]
    assert "polling" in payload["items"][0]["tags"]
    assert "access" in payload["items"][1]["tags"]
    assert "polling" not in payload["items"][1]["tags"]
    assert payload["items"][2]["level"] == "error"


def test_runtime_logs_expose_task_job_logs_with_cursor_and_filter(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")
    repo.add_log(task["id"], None, "info", "配置校验通过", {"step_code": "PRECHECK_CONFIG"})
    repo.add_log(task["id"], 42, "error", "保存失败 add.json", {"action": "save_only"})

    response = client.get(f"/api/runtime/logs?source=task&task_id={task['id']}&level=error&q=add.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "task"
    assert payload["exists"] is True
    assert payload["path"] == f"job_logs?task_id={task['id']}"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["level"] == "error"
    assert "task#" in payload["items"][0]["line"]
    assert "job#42" in payload["items"][0]["line"]
    assert "保存" in payload["items"][0]["tags"]
    next_cursor = payload["nextCursor"]

    repo.add_log(task["id"], None, "warning", "点击重试", {"action": "click"})
    cursor_response = client.get(f"/api/runtime/logs?source=task&task_id={task['id']}&cursor={next_cursor}")

    assert cursor_response.status_code == 200
    cursor_payload = cursor_response.json()
    assert cursor_payload["lines"] == [line for line in cursor_payload["lines"] if "点击重试" in line]
    assert cursor_payload["nextCursor"] > next_cursor


def test_runtime_logs_expose_browser_agent_history(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    task = _create_task(repo, mode="dry_run")
    start_response = client.post("/api/agent-console/start", json={"task_id": task["id"], "launch_browser": False})
    assert start_response.status_code == 200

    main.agent_console_service.update_task_step(
        task_id=task["id"],
        job_id=7,
        product_id=11,
        step_code="SAVE_ONLY",
        step_name="点击保存",
        field_domain="semi_managed",
        mode="single_save",
    )
    main.agent_console_service.record_action_event(
        task_id=task["id"],
        job_id=7,
        product_id=11,
        type="save",
        action="save_only",
        label="只点击保存",
        state="SAVE_ONLY",
        field_domain="save",
        status="ok",
        target="保存",
    )

    response = client.get("/api/runtime/logs?source=agent&q=status=ok")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "agent"
    assert payload["path"] == "agent_console.events"
    assert payload["exists"] is True
    assert payload["lines"] == [line for line in payload["lines"] if "SAVE_ONLY" in line and "save_only" in line]
    assert "保存" in payload["items"][0]["tags"]


def test_runtime_status_reports_services_agent_and_dependencies(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)

    response = client.get("/api/runtime/status?frontend_url=http://127.0.0.1:9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"]["status"] == "ok"
    assert payload["frontend"]["status"] == "down"
    assert payload["frontend"]["port"] == 9
    assert payload["agentConsole"]["status"] in {"idle", "running"}
    assert "dxmLogin" in payload
    assert payload["dependencies"]["python"]["status"] == "ok"


def test_runtime_status_exposes_backend_data_dir_and_instance_id(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "RUNTIME_BACKEND_INSTANCE_ID", "desktop-instance-test")

    response = client.get("/api/runtime/status?frontend_url=http://127.0.0.1:9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backend"]["instanceId"] == "desktop-instance-test"
    assert payload["paths"]["data_dir"] == str(main.DATA_DIR)
    assert payload["paths"]["l2_readonly_probe_dir"] == str(main.L2_READONLY_PROBE_OUTPUT_DIR)


def test_runtime_status_treats_electron_file_frontend_as_desktop_page(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)

    response = client.get("/api/runtime/status?frontend_url=file%3A%2F%2F")

    assert response.status_code == 200
    frontend = response.json()["frontend"]
    assert frontend["status"] == "ok"
    assert frontend["url"] == "file://"
    assert frontend["port"] is None
    assert "桌面内置页面" in frontend["detail"]


def test_runtime_status_defaults_to_desktop_frontend_in_desktop_mode(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "RUNTIME_DESKTOP_MODE", True)
    monkeypatch.delenv("DXM_FRONTEND_URL", raising=False)

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    frontend = response.json()["frontend"]
    assert frontend["status"] == "ok"
    assert frontend["url"] == "file://"
    assert frontend["port"] is None
    assert "桌面内置页面" in frontend["detail"]


def test_runtime_status_uses_login_page_url_for_current_url(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(main.login_flow, "get_state", lambda: {
        "stage": "waiting_captcha",
        "page_url": "https://www.dianxiaomi.com/login.htm",
        "last_error": None,
    })

    response = client.get("/api/runtime/status?frontend_url=http://127.0.0.1:9")

    assert response.status_code == 200
    assert response.json()["dxmLogin"]["currentUrl"] == "https://www.dianxiaomi.com/login.htm"


def test_runtime_status_unifies_visible_dxm_flow_browser_even_when_agent_console_idle(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(main.login_flow, "get_state", lambda: {
        "stage": "workflow_navigation",
        "label": "数据采集",
        "message": "已进入数据采集页，可以继续认领产品。",
        "next_action": "继续切换到速卖通采集箱或执行认领。",
        "page_title": "店小秘--数据采集",
        "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "browser_visible": True,
        "last_error": None,
    })
    monkeypatch.setattr(main.agent_console_service, "status", lambda: {
        "active": False,
        "browser_visible": False,
        "browser_launching": False,
        "target_url": "https://www.dianxiaomi.com/",
        "current_url": None,
        "profile_dir": None,
        "last_error": None,
    })

    response = client.get("/api/runtime/status?frontend_url=http://127.0.0.1:9")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentConsole"]["active"] is False
    assert payload["realBrowser"]["active"] is True
    assert payload["realBrowser"]["browserVisible"] is True
    assert payload["realBrowser"]["source"] == "dxm_flow"
    assert payload["realBrowser"]["currentUrl"].endswith("/web/productCrawl/dataAcquisition")
    assert payload["realBrowser"]["pageTitle"] == "店小秘--数据采集"
    assert payload["realBrowser"]["currentStep"] == "数据采集"


def test_runtime_status_exposes_agent_browser_launch_diagnostics(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")

    start_response = client.post(
        "/api/agent-console/start",
        json={"task_id": task["id"], "launch_browser": False},
    )
    assert start_response.status_code == 200

    response = client.get("/api/runtime/status?frontend_url=http://127.0.0.1:9")

    assert response.status_code == 200
    agent_console = response.json()["agentConsole"]
    assert agent_console["profileDir"]
    assert agent_console["browserLaunching"] is False
    assert "agent-" in agent_console["profileDir"]


def test_runtime_control_stops_agent_console_and_records_log(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")

    start_response = client.post(
        "/api/agent-console/start",
        json={"task_id": task["id"], "launch_browser": False},
    )
    assert start_response.status_code == 200

    response = client.post("/api/runtime/control", json={"action": "stop_agent_console"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "stop_agent_console"
    assert payload["agentConsole"]["active"] is False
    logs = repo.list_logs(task["id"])
    assert any("运行时控制：已停止浏览器 Agent" in item["message"] for item in logs)


def test_runtime_control_clears_only_non_real_stuck_tasks(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    dry_run = _create_task(repo, mode="dry_run")
    single_save = _create_task(repo, mode="single_save")
    repo.update_task_status(dry_run["id"], "running")
    repo.update_task_status(single_save["id"], "running")

    response = client.post("/api/runtime/control", json={"action": "clear_stuck_tasks"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["clearedTaskIds"] == [dry_run["id"]]
    assert repo.get_task(dry_run["id"])["status"] == "cancelled"
    assert repo.get_task(single_save["id"])["status"] == "running"
    assert any(item["id"] == single_save["id"] and item["reason"] == "real_write_protected" for item in payload["skippedTasks"])


def test_runtime_control_marks_real_task_for_manual_review_without_cancelling_worker(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    repo.update_task_status(task["id"], "paused")

    response = client.post(
        "/api/runtime/control",
        json={"action": "mark_real_task_manual_review", "task_id": task["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "mark_real_task_manual_review"
    assert payload["markedTasks"] == [
        {
            "id": task["id"],
            "mode": "single_save",
            "previousStatus": "paused",
            "status": "needs_manual_review",
            "reason": "manual_review_requested",
        }
    ]
    assert repo.get_task(task["id"])["status"] == "needs_manual_review"
    logs = repo.list_logs(task["id"])
    assert any("运行时控制：真实写入任务已转人工复核" in item["message"] for item in logs)


def test_runtime_control_queues_launcher_managed_backend_restart(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    command_file = tmp_path / "runtime-control-command.json"
    monkeypatch.setattr(main, "RUNTIME_CONTROL_COMMAND_FILE", command_file)
    monkeypatch.setattr(main, "RUNTIME_CONTROL_MANAGED_BY_LAUNCHER", True)

    response = client.post("/api/runtime/control", json={"action": "restart_backend"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "restart_backend"
    assert "启动器" in payload["message"]
    command = json.loads(command_file.read_text(encoding="utf-8"))
    assert command["action"] == "restart_backend"
    assert command["source"] == "backend-api"


def test_runtime_control_queues_launcher_managed_frontend_restart(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    command_file = tmp_path / "runtime-control-command.json"
    monkeypatch.setattr(main, "RUNTIME_CONTROL_COMMAND_FILE", command_file)
    monkeypatch.setattr(main, "RUNTIME_CONTROL_MANAGED_BY_LAUNCHER", True)

    response = client.post("/api/runtime/control", json={"action": "restart_frontend"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "restart_frontend"
    command = json.loads(command_file.read_text(encoding="utf-8"))
    assert command["action"] == "restart_frontend"


def test_runtime_control_rejects_restart_when_not_launcher_managed(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    command_file = tmp_path / "runtime-control-command.json"
    monkeypatch.setattr(main, "RUNTIME_CONTROL_COMMAND_FILE", command_file)
    monkeypatch.setattr(main, "RUNTIME_CONTROL_MANAGED_BY_LAUNCHER", False)

    response = client.post("/api/runtime/control", json={"action": "restart_backend"})

    assert response.status_code == 409
    assert "start-mvp" in response.json()["detail"]
    assert not command_file.exists()


def test_runtime_status_reports_launcher_managed_restart_availability(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    command_file = tmp_path / "runtime-control-command.json"
    monkeypatch.setattr(main, "RUNTIME_CONTROL_COMMAND_FILE", command_file)
    monkeypatch.setattr(main, "RUNTIME_CONTROL_MANAGED_BY_LAUNCHER", True)
    monkeypatch.setattr(main, "RUNTIME_DESKTOP_MODE", False, raising=False)

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    runtime_control = response.json()["runtimeControl"]
    assert runtime_control["managedByLauncher"] is True
    assert runtime_control["restartAvailable"] is True
    assert runtime_control["commandFile"] == str(command_file)
    assert "start-mvp" in runtime_control["detail"]


def test_runtime_status_reports_desktop_exe_as_desktop_managed(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    command_file = tmp_path / "runtime-control-command.json"
    monkeypatch.setattr(main, "RUNTIME_CONTROL_COMMAND_FILE", command_file)
    monkeypatch.setattr(main, "RUNTIME_CONTROL_MANAGED_BY_LAUNCHER", False)
    monkeypatch.setattr(main, "RUNTIME_DESKTOP_MODE", True, raising=False)

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    runtime_control = response.json()["runtimeControl"]
    assert runtime_control["owner"] == "desktop"
    assert runtime_control["managedByDesktop"] is True
    assert runtime_control["restartAvailable"] is False
    assert "DXM Agent Console 免安装版" in runtime_control["detail"]
    assert "scripts/start-mvp.bat" not in runtime_control["detail"]


def test_runtime_status_reports_l2_probe_resource_readiness_from_resource_root(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    missing_root = tmp_path / "missing-repo-root"
    resource_root = tmp_path / "desktop-resources"
    runner_script = resource_root / "tools" / "probes" / "l2_readonly_probe_runner.py"
    probe_script = resource_root / "tools" / "probes" / "l2_readonly_probe.py"
    allowlist_file = resource_root / "config" / "l2_readonly_allowlist.json"
    runner_script.parent.mkdir(parents=True)
    allowlist_file.parent.mkdir(parents=True)
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    allowlist_file.write_text('{"schema":"dxm_l2_readonly_allowlist.v1"}', encoding="utf-8")
    monkeypatch.setenv("DXM_RESOURCE_ROOT", str(resource_root))
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", missing_root / "tools" / "probes" / "l2_readonly_probe_runner.py")
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", missing_root / "tools" / "probes" / "l2_readonly_probe.py")
    monkeypatch.setattr(main, "L2_READONLY_PROBE_ALLOWLIST_FILE", missing_root / "config" / "l2_readonly_allowlist.json")

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    dependencies = response.json()["dependencies"]
    assert dependencies["l2_readonly_probe_runner"]["status"] == "ok"
    assert dependencies["l2_readonly_probe_runner"]["path"] == str(runner_script)
    assert str(runner_script) in dependencies["l2_readonly_probe_runner"]["checkedPaths"]
    assert dependencies["l2_readonly_probe_script"]["status"] == "ok"
    assert dependencies["l2_readonly_probe_script"]["path"] == str(probe_script)
    assert str(probe_script) in dependencies["l2_readonly_probe_script"]["checkedPaths"]
    assert dependencies["l2_readonly_probe_allowlist"]["status"] == "ok"
    assert dependencies["l2_readonly_probe_allowlist"]["path"] == str(allowlist_file)
    assert str(allowlist_file) in dependencies["l2_readonly_probe_allowlist"]["checkedPaths"]


def test_runtime_status_reports_l2_probe_checked_paths_when_resource_missing(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    missing_root = tmp_path / "missing-repo-root"
    resource_root = tmp_path / "empty-desktop-resources"
    resource_root.mkdir()
    monkeypatch.setenv("DXM_RESOURCE_ROOT", str(resource_root))
    monkeypatch.setattr(main, "_resource_root_candidates", lambda: [resource_root, missing_root])
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", missing_root / "tools" / "probes" / "l2_readonly_probe_runner.py")

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    runner = response.json()["dependencies"]["l2_readonly_probe_runner"]
    assert runner["status"] == "missing"
    assert runner["path"] == str(missing_root / "tools" / "probes" / "l2_readonly_probe_runner.py")
    assert str(resource_root / "tools" / "probes" / "l2_readonly_probe_runner.py") in runner["checkedPaths"]
    assert str(missing_root / "tools" / "probes" / "l2_readonly_probe_runner.py") in runner["checkedPaths"]
    assert runner["label"] == "只读页面检查启动器"
    assert runner["requiredFor"] == "运行真实只读检查（只读，不保存）"
    assert runner["userMessage"] == "真实只读检查组件未安装完整：缺少只读页面检查启动器。"
    assert runner["repairAction"] == "关闭旧后台进程后重新打开免安装版"
    assert "使用 Portable 单文件版时，直接重新打开 exe；不要继续操作残留窗口。" in runner["repairSteps"]
    assert "使用目录版时，必须保留同目录 resources 文件夹。" in runner["repairSteps"]


def test_runtime_status_reports_l2_probe_runner_lock_state(tmp_path, monkeypatch):
    import src.main as main

    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    lock_file = tmp_path / "runner.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(
        json.dumps({
            "schema": "dxm_l2_readonly_probe_lock.v1",
            "run_id": "l2-real-existing",
            "task_id": 42,
            "pid": 2468,
            "created_at": "2099-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    probe = response.json()["l2ReadonlyProbe"]
    assert probe["running"] is True
    assert probe["stale"] is False
    assert probe["runId"] == "l2-real-existing"
    assert probe["taskId"] == 42
    assert probe["pid"] == 2468
    assert probe["lockFile"] == str(lock_file)


def test_runtime_control_starts_l2_readonly_probe_runner_without_real_write(tmp_path, monkeypatch):
    import src.main as main

    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    launcher_log = tmp_path / "start-mvp.log"
    runner_script = tmp_path / "l2_readonly_probe_runner.py"
    probe_script = tmp_path / "l2_readonly_probe.py"
    lock_file = tmp_path / "runner.lock"
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"launcher": launcher_log})
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", runner_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", probe_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)

    popen_calls = []

    class FakeProcess:
        pid = 4321

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    response = client.post("/api/runtime/control", json={"action": "run_l2_readonly_probe", "task_id": task["id"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action"] == "run_l2_readonly_probe"
    assert payload["pid"] == 4321
    assert payload["targets"] == ["data_acquisition", "draft_box"]
    assert payload["runId"].startswith("l2-real-")
    assert len(popen_calls) == 1
    command = popen_calls[0]["command"]
    assert str(runner_script) in command
    assert "--run-id" in command
    assert "--script" in command
    assert str(probe_script) in command
    assert "--cookie-file" in command
    assert "--output-dir" in command
    assert "--allowlist-file" in command
    assert "--lock-file" in command
    assert "--headed" in command
    assert str(lock_file) in command
    assert "claim_only" not in command
    assert "single_save" not in command
    assert "batch_save" not in command
    assert "started L2 readonly dual-target probe" in launcher_log.read_text(encoding="utf-8")
    lock_payload = json.loads(lock_file.read_text(encoding="utf-8"))
    assert lock_payload["run_id"] == payload["runId"]
    assert lock_payload["pid"] == 4321


def test_runtime_control_resolves_l2_runner_from_desktop_resource_root(tmp_path, monkeypatch):
    import src.main as main

    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    launcher_log = tmp_path / "start-mvp.log"
    missing_root = tmp_path / "missing-repo-root"
    resource_root = tmp_path / "desktop-resources"
    runner_script = resource_root / "tools" / "probes" / "l2_readonly_probe_runner.py"
    probe_script = resource_root / "tools" / "probes" / "l2_readonly_probe.py"
    allowlist_file = resource_root / "config" / "l2_readonly_allowlist.json"
    lock_file = tmp_path / "runner.lock"
    runner_script.parent.mkdir(parents=True)
    allowlist_file.parent.mkdir(parents=True)
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    allowlist_file.write_text('{"schema":"dxm_l2_readonly_allowlist.v1"}', encoding="utf-8")
    monkeypatch.setenv("DXM_RESOURCE_ROOT", str(resource_root))
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"launcher": launcher_log})
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", missing_root / "tools" / "probes" / "l2_readonly_probe_runner.py")
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", missing_root / "tools" / "probes" / "l2_readonly_probe.py")
    monkeypatch.setattr(main, "L2_READONLY_PROBE_ALLOWLIST_FILE", missing_root / "config" / "l2_readonly_allowlist.json")
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)

    popen_calls = []

    class FakeProcess:
        pid = 9876

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    response = client.post("/api/runtime/control", json={"action": "run_l2_readonly_probe", "task_id": task["id"]})

    assert response.status_code == 200
    command = popen_calls[0]["command"]
    assert str(runner_script) in command
    assert str(probe_script) in command
    assert str(allowlist_file) in command


def test_runtime_control_rejects_l2_probe_when_allowlist_resource_missing(tmp_path, monkeypatch):
    import src.main as main

    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    runner_script = tmp_path / "l2_readonly_probe_runner.py"
    probe_script = tmp_path / "l2_readonly_probe.py"
    missing_allowlist_file = tmp_path / "missing" / "l2_readonly_allowlist.json"
    empty_resource_root = tmp_path / "empty-resource-root"
    lock_file = tmp_path / "runner.lock"
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    empty_resource_root.mkdir()
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", runner_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", probe_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_ALLOWLIST_FILE", missing_allowlist_file)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)
    monkeypatch.setattr(main, "_resource_root_candidates", lambda: [empty_resource_root])

    popen_calls = []

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, "kwargs": kwargs})
        raise AssertionError("readonly probe runner must not start without allowlist")

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)

    response = client.post("/api/runtime/control", json={"action": "run_l2_readonly_probe", "task_id": task["id"]})

    assert response.status_code == 424
    detail = response.json()["detail"]
    assert "L2 readonly probe resources are missing" in detail
    assert "allowlist" in detail
    assert str(missing_allowlist_file) in detail
    assert popen_calls == []
    assert not lock_file.exists()


def test_runtime_control_stops_l2_probe_process_when_pid_lock_write_fails(tmp_path, monkeypatch):
    import src.main as main

    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    launcher_log = tmp_path / "start-mvp.log"
    runner_script = tmp_path / "l2_readonly_probe_runner.py"
    probe_script = tmp_path / "l2_readonly_probe.py"
    allowlist_file = tmp_path / "l2_readonly_allowlist.json"
    lock_file = tmp_path / "runner.lock"
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    allowlist_file.write_text('{"schema":"dxm_l2_readonly_allowlist.v1"}', encoding="utf-8")
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"launcher": launcher_log})
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", runner_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", probe_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_ALLOWLIST_FILE", allowlist_file)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)

    class FakeProcess:
        pid = 2468

        def __init__(self):
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

    fake_process = FakeProcess()
    monkeypatch.setattr(main.subprocess, "Popen", lambda *args, **kwargs: fake_process)

    def fail_write_lock(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(main, "_write_l2_probe_lock", fail_write_lock)

    response = client.post("/api/runtime/control", json={"action": "run_l2_readonly_probe", "task_id": task["id"]})

    assert response.status_code == 500
    assert "Could not record L2 readonly probe lock" in response.json()["detail"]
    assert "disk full" in response.json()["detail"]
    assert fake_process.terminated is True
    assert fake_process.waited is True
    assert not lock_file.exists()


def test_runtime_control_rejects_parallel_l2_readonly_probe(tmp_path, monkeypatch):
    import src.main as main

    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="single_save")
    launcher_log = tmp_path / "start-mvp.log"
    runner_script = tmp_path / "l2_readonly_probe_runner.py"
    probe_script = tmp_path / "l2_readonly_probe.py"
    lock_file = tmp_path / "runner.lock"
    runner_script.write_text("print('runner')", encoding="utf-8")
    probe_script.write_text("print('probe')", encoding="utf-8")
    lock_file.write_text(
        json.dumps({
            "schema": "dxm_l2_readonly_probe_lock.v1",
            "run_id": "l2-real-existing",
            "task_id": task["id"],
            "pid": 1111,
            "created_at": "2099-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "RUNTIME_LOG_SOURCES", {"launcher": launcher_log})
    monkeypatch.setattr(main, "L2_READONLY_PROBE_RUNNER", runner_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_SCRIPT", probe_script)
    monkeypatch.setattr(main, "L2_READONLY_PROBE_LOCK_FILE", lock_file)

    popen_calls = []
    monkeypatch.setattr(main.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    response = client.post("/api/runtime/control", json={"action": "run_l2_readonly_probe", "task_id": task["id"]})

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]
    assert popen_calls == []


def test_runtime_logs_reject_unknown_source(tmp_path, monkeypatch):
    client, _repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)

    response = client.get("/api/runtime/logs?source=unknown")

    assert response.status_code == 400
    assert "Unknown runtime log source" in response.json()["detail"]


def test_template_update_persists_edit_page_section_payload(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    template = repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "包装物流",
            "binding_scope": "Dang Kang / 立牌类谷子",
            "payload": {"weight": "0.03"},
            "is_enabled": True,
        }
    )

    response = client.patch(
        f"/api/templates/{template['id']}",
        json={
            "payload": {
                "weight": "0.05",
                "length": "12",
                "width": "10",
                "height": "3",
                "logistics_attribute": "普货",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["template_type"] == "logistics"
    assert payload["payload"]["weight"] == "0.05"
    assert repo.list_templates()[0]["payload"]["length"] == "12"


def test_config_preview_reports_missing_edit_page_sections(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.get(f"/api/config/preview?task_id={task['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["mode"] == "single_save"
    assert "sku" in data["missing"]
    assert "pricing" in data["missing"]
    assert "image.eu_outer_package_filename" in data["missing"]
    groups = {group["section"]: group for group in data["fieldGroups"]}
    assert groups["logistics"]["templatePresent"] is False
    assert groups["image"]["complete"] is False
    assert any(field["missing"] for field in groups["image"]["fields"])


def test_config_preview_shows_effective_values_and_sources(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    base_task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "包装物流模板",
            "binding_scope": "Dang Kang",
            "payload": {"weight": "0.03", "length": "10", "width": "10", "height": "2"},
            "is_enabled": True,
        }
    )
    base_payload = repo.get_task_private(base_task["id"])["payload"]
    override_task = repo.create_task(
        {
            "name": "override source task",
            "store_id": base_task["store_id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": base_payload["product_ids"],
            "payload": {
                **base_payload,
                "template_overrides": {"logistics": {"weight": "0.05"}},
            },
        }
    )

    response = client.get(f"/api/config/preview?task_id={override_task['id']}")

    assert response.status_code == 200
    groups = {group["section"]: group for group in response.json()["fieldGroups"]}
    logistics_fields = {field["path"]: field for field in groups["logistics"]["fields"]}
    assert logistics_fields["logistics.weight"]["value"] == "0.05"
    assert logistics_fields["logistics.weight"]["source"] == "任务覆盖"
    assert logistics_fields["logistics.length"]["value"] == "10"
    assert logistics_fields["logistics.length"]["source"] == "模板：包装物流模板"


def test_config_preview_does_not_mark_other_store_template_present(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, store_name="Dang Kang")
    repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "其它店铺包装物流模板",
            "binding_scope": "Other Store / 立牌类谷子",
            "payload": {
                "binding": {"store_name": "Other Store", "category_name": "立牌类谷子", "platform": "AliExpress"},
                "weight": "0.03",
                "length": "10",
                "width": "10",
                "height": "2",
            },
            "is_enabled": True,
        }
    )

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    groups = {group["section"]: group for group in preview["fieldGroups"]}
    logistics_fields = {field["path"]: field for field in groups["logistics"]["fields"]}

    assert groups["logistics"]["templatePresent"] is False
    assert "logistics" in preview["missing"]
    assert logistics_fields["logistics.weight"]["value"] == ""
    assert logistics_fields["logistics.weight"]["source"] == "未设置"


def test_config_preview_and_runner_prefer_specific_template_over_global_template(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, store_name="Dang Kang")
    product = repo.list_products()[0]
    repo.create_template(
        {
            "template_type": "category",
            "template_name": "全局类目模板",
            "binding_scope": "全部店铺",
            "payload": {
                "category": {
                    "category_keyword": "global-keyword",
                    "template_category_id": "global-category",
                }
            },
            "is_enabled": True,
        }
    )
    repo.create_template(
        {
            "template_type": "category",
            "template_name": "Dang Kang 立牌类谷子模板",
            "binding_scope": "Dang Kang / 立牌类谷子",
            "payload": {
                "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子", "platform": "AliExpress"},
                "category": {
                    "category_keyword": "specific-keyword",
                    "template_category_id": "specific-category",
                },
            },
            "is_enabled": True,
        }
    )

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    runner_defaults = V1TaskRunner(repo, object())._execution_defaults(repo.get_task_private(task["id"]), product)
    category_group = {group["section"]: group for group in preview["fieldGroups"]}["category"]
    fields = {field["path"]: field for field in category_group["fields"]}

    assert fields["category.category_keyword"]["value"] == "specific-keyword"
    assert fields["category.category_keyword"]["source"] == "模板：Dang Kang 立牌类谷子模板"
    assert preview["resolvedDefaults"]["category"]["template_category_id"] == "specific-category"
    assert runner_defaults["category"]["template_category_id"] == "specific-category"
    assert [item["template_name"] for item in preview["templateTrace"] if item["template_type"] == "category"] == [
        "全局类目模板",
        "Dang Kang 立牌类谷子模板",
    ]


def test_config_defaults_resolver_prefers_specific_template_even_when_input_order_is_unstable():
    resolver = ConfigDefaultsResolver()
    task = {
        "id": 1,
        "name": "single save task",
        "platform": "AliExpress",
        "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    }
    product = {"id": 1, "title": "ACG Stand", "category_name": "立牌类谷子", "payload": {}}
    templates = [
        {
            "id": 1,
            "template_type": "category",
            "template_name": "全局类目模板",
            "binding_scope": "全部店铺",
            "payload": {"category": {"category_keyword": "global-keyword", "template_category_id": "global-category"}},
            "is_enabled": True,
        },
        {
            "id": 2,
            "template_type": "category",
            "template_name": "Dang Kang 立牌类谷子模板",
            "binding_scope": "Dang Kang / 立牌类谷子",
            "payload": {
                "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子", "platform": "AliExpress"},
                "category": {"category_keyword": "specific-keyword", "template_category_id": "specific-category"},
            },
            "is_enabled": True,
        },
    ]

    result = resolver.resolve(templates, task, product)

    assert result.defaults["category"]["category_keyword"] == "specific-keyword"
    assert result.sources["category"]["category_keyword"] == "模板：Dang Kang 立牌类谷子模板"
    assert [item["template_name"] for item in result.template_trace] == [
        "全局类目模板",
        "Dang Kang 立牌类谷子模板",
    ]


def test_config_preview_covers_dxm_edit_page_sections_and_reference_templates(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "dxm_reference",
            "template_name": "DXM 引用模板",
            "binding_scope": "Dang Kang",
            "payload": {
                "freight_template_priorities": "半托管运费模板",
                "service_template_priorities": "无忧服务模板",
                "eu_responsible_names": "EU Responsible Person",
                "manufacturer_names": "默认制造商",
            },
            "is_enabled": True,
        }
    )

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    groups = {group["section"]: group for group in preview["fieldGroups"]}

    assert "task_basic" in groups
    assert "dxm_reference" in groups
    task_fields = {field["path"]: field for field in groups["task_basic"]["fields"]}
    assert task_fields["store_name"]["source"].startswith("任务：")
    assert task_fields["execution_mode"]["value"] == "single_save"
    reference_fields = {field["path"]: field for field in groups["dxm_reference"]["fields"]}
    assert reference_fields["dxm_reference_templates_resolved.freight.names"]["value"] == ["半托管运费模板"]
    assert reference_fields["dxm_reference_templates_resolved.service.names"]["source"] == "模板：DXM 引用模板"
    assert "sku.jit_stock" in {field["path"] for field in groups["sku"]["fields"]}
    assert "pricing.price_multiplier" in {field["path"] for field in groups["pricing"]["fields"]}
    assert "image.local_asset_path" in {field["path"] for field in groups["image"]["fields"]}
    assert "logistics.freight_template" in {field["path"] for field in groups["logistics"]["fields"]}
    assert "compliance.brand" in {field["path"] for field in groups["compliance"]["fields"]}


def test_config_preview_does_not_mark_optional_category_name_missing_when_keyword_is_set(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "category",
            "template_name": "类目关键词模板",
            "binding_scope": "Dang Kang",
            "payload": {"category": {"category_keyword": "立牌"}},
            "is_enabled": True,
        }
    )

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    category_group = {group["section"]: group for group in preview["fieldGroups"]}["category"]
    fields = {field["path"]: field for field in category_group["fields"]}

    assert fields["category.category_keyword"]["required"] is True
    assert fields["category.category_keyword"]["missing"] is False
    assert fields["category.category_name"]["required"] is False
    assert fields["category.category_name"]["missing"] is False


def test_config_preview_shows_semi_managed_supply_price_as_execution_value(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    payload = repo.get_task_private(task["id"])["payload"]
    payload["semi_managed"] = {
        "supply_price": "5.60",
        "jit_stock": "100",
        "is_original_box": "否",
        "length": "10",
        "width": "10",
        "height": "2",
        "goods_code_strategy": "allow_blank",
        "barcode_strategy": "allow_blank",
    }
    repo.update_task_template_override(task["id"], "semi_managed", payload["semi_managed"])

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    semi_group = {group["section"]: group for group in preview["fieldGroups"]}["semi_managed"]
    fields = {field["path"]: field for field in semi_group["fields"]}

    assert fields["semi_managed.product_price"]["required"] is False
    assert fields["semi_managed.product_price"]["missing"] is False
    assert fields["semi_managed.supply_price"]["value"] == "5.60"
    assert fields["semi_managed.supply_price"]["source"] == "任务覆盖"
    assert fields["semi_managed.goods_code_strategy"]["required"] is True
    assert fields["semi_managed.barcode_strategy"]["required"] is True


def test_config_preview_uses_resolved_dxm_reference_template_sections(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "dxm_reference",
            "template_name": "DXM 八段引用模板",
            "binding_scope": "Dang Kang",
            "payload": {
                "dxm_reference_templates": {
                    "attribute_info": {"names": ["属性模板 A"]},
                    "description": {"names": ["描述模板 A"], "required": False},
                    "freight": {"names": ["半托管运费模板"]},
                    "service": {"names": ["无忧服务模板"]},
                    "eu_responsible": {"names": ["EU Responsible Person"]},
                    "manufacturer": {"names": ["默认制造商"]},
                    "compliance": {"names": ["合规模板"]},
                    "semi_managed": {"names": ["半托管模板"]},
                }
            },
            "is_enabled": True,
        }
    )

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    group = {group["section"]: group for group in preview["fieldGroups"]}["dxm_reference"]
    fields = {field["path"]: field for field in group["fields"]}

    assert group["complete"] is True
    assert set(fields) == {
        "dxm_reference_templates_resolved.attribute_info.names",
        "dxm_reference_templates_resolved.description.names",
        "dxm_reference_templates_resolved.freight.names",
        "dxm_reference_templates_resolved.service.names",
        "dxm_reference_templates_resolved.eu_responsible.names",
        "dxm_reference_templates_resolved.manufacturer.names",
        "dxm_reference_templates_resolved.compliance.names",
        "dxm_reference_templates_resolved.semi_managed.names",
    }
    assert fields["dxm_reference_templates_resolved.attribute_info.names"]["value"] == ["属性模板 A"]
    assert fields["dxm_reference_templates_resolved.description.names"]["required"] is False
    assert fields["dxm_reference_templates_resolved.freight.names"]["source"] == "模板：DXM 八段引用模板"


def test_config_preview_keeps_publish_allowed_out_of_editable_value_fields(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    task_fields = {field["path"] for group in preview["fieldGroups"] if group["section"] == "task_basic" for field in group["fields"]}

    assert "publish_allowed" not in task_fields


def test_config_preview_and_runner_use_same_resolved_defaults(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    base_task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "包装物流模板",
            "binding_scope": "Dang Kang",
            "payload": {"weight": "0.03", "length": "10", "width": "10", "height": "2"},
            "is_enabled": True,
        }
    )
    base_payload = repo.get_task_private(base_task["id"])["payload"]
    task = repo.create_task(
        {
            "name": "same resolver task",
            "store_id": base_task["store_id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": base_payload["product_ids"],
            "payload": {
                **base_payload,
                "template_overrides": {"logistics": {"weight": "0.05"}},
            },
        }
    )
    product = repo.list_products()[0]

    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    runner = V1TaskRunner(repo, object())
    execution_defaults = runner._execution_defaults(repo.get_task_private(task["id"]), product)

    assert preview["resolvedDefaults"] == execution_defaults
    assert preview["resolvedDefaults"]["logistics"]["weight"] == "0.05"
    assert preview["resolvedDefaults"]["logistics"]["length"] == "10"


def test_task_config_override_endpoint_updates_preview_and_runner_defaults(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "包装物流模板",
            "binding_scope": "Dang Kang",
            "payload": {"weight": "0.03", "length": "10", "width": "10", "height": "2"},
            "is_enabled": True,
        }
    )

    response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={"section": "logistics", "values": {"weight": "0.08", "length": "12", "width": ""}},
    )

    assert response.status_code == 200
    public_payload = response.json()["payload"]
    assert public_payload["template_overrides"]["logistics"] == {"weight": "0.08", "length": "12"}
    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    groups = {group["section"]: group for group in preview["fieldGroups"]}
    logistics_fields = {field["path"]: field for field in groups["logistics"]["fields"]}
    assert logistics_fields["logistics.weight"]["value"] == "0.08"
    assert logistics_fields["logistics.weight"]["source"] == "任务覆盖"
    assert logistics_fields["logistics.length"]["value"] == "12"
    assert logistics_fields["logistics.length"]["source"] == "任务覆盖"
    assert logistics_fields["logistics.height"]["value"] == "2"
    assert logistics_fields["logistics.height"]["source"] == "模板：包装物流模板"

    runner = V1TaskRunner(repo, object())
    execution_defaults = runner._execution_defaults(repo.get_task_private(task["id"]), repo.list_products()[0])
    assert execution_defaults["logistics"]["weight"] == "0.08"
    assert execution_defaults["logistics"]["height"] == "2"


def test_config_preview_recovers_when_legacy_section_payload_is_scalar(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    private_task = repo.get_task_private(task["id"])
    legacy_payload = {
        **private_task["payload"],
        "logistics": "legacy bad scalar",
        "template_overrides": {
            "logistics": {
                "weight": "0.08",
                "length": "12",
            },
        },
    }
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (json.dumps(legacy_payload, ensure_ascii=False), task["id"]),
        )

    response = client.get(f"/api/config/preview?task_id={task['id']}")

    assert response.status_code == 200
    preview = response.json()
    assert preview["resolvedDefaults"]["logistics"] == {
        "weight": "0.08",
        "length": "12",
    }
    groups = {group["section"]: group for group in preview["fieldGroups"]}
    logistics_fields = {field["path"]: field for field in groups["logistics"]["fields"]}
    assert logistics_fields["logistics.weight"]["source"] == "任务覆盖"


def test_task_config_override_endpoint_updates_semi_managed_runner_defaults(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "semi_managed",
            "values": {
                "supply_price": "6.66",
                "jit_stock": "88",
                "is_original_box": "否",
                "length": "12",
                "width": "9",
                "height": "3",
                "goods_code_strategy": "use_sku",
                "barcode_strategy": "allow_blank",
            },
        },
    )

    assert response.status_code == 200
    public_payload = response.json()["payload"]
    assert public_payload["template_overrides"]["semi_managed"]["supply_price"] == "6.66"
    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    groups = {group["section"]: group for group in preview["fieldGroups"]}
    semi_fields = {field["path"]: field for field in groups["semi_managed"]["fields"]}
    assert semi_fields["semi_managed.supply_price"]["value"] == "6.66"
    assert semi_fields["semi_managed.supply_price"]["source"] == "任务覆盖"
    assert semi_fields["semi_managed.jit_stock"]["value"] == "88"
    assert semi_fields["semi_managed.jit_stock"]["source"] == "任务覆盖"

    runner = V1TaskRunner(repo, object())
    execution_defaults = runner._execution_defaults(repo.get_task_private(task["id"]), repo.list_products()[0])
    assert execution_defaults["semi_managed"]["supply_price"] == "6.66"
    assert execution_defaults["semi_managed"]["jit_stock"] == "88"
    assert execution_defaults["semi_managed"]["goods_code_strategy"] == "use_sku"


def test_task_config_override_endpoint_updates_sku_code_runner_defaults(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "sku",
            "values": {
                "sku_code": "SKU-UI-001",
                "jit_stock": "66",
            },
        },
    )

    assert response.status_code == 200
    public_payload = response.json()["payload"]
    assert public_payload["template_overrides"]["sku"]["sku_code"] == "SKU-UI-001"
    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    groups = {group["section"]: group for group in preview["fieldGroups"]}
    sku_fields = {field["path"]: field for field in groups["sku"]["fields"]}
    assert sku_fields["sku.sku_code"]["value"] == "SKU-UI-001"
    assert sku_fields["sku.sku_code"]["source"] == "任务覆盖"
    assert sku_fields["sku.jit_stock"]["value"] == "66"
    assert sku_fields["sku.jit_stock"]["source"] == "任务覆盖"

    runner = V1TaskRunner(repo, object())
    execution_defaults = runner._execution_defaults(repo.get_task_private(task["id"]), repo.list_products()[0])
    assert execution_defaults["sku"]["sku_code"] == "SKU-UI-001"
    assert execution_defaults["sku"]["jit_stock"] == "66"


def test_task_config_override_endpoint_can_clear_section(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    first = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={"section": "logistics", "values": {"weight": "0.08"}},
    )
    assert first.status_code == 200

    cleared = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={"section": "logistics", "values": {"weight": ""}},
    )

    assert cleared.status_code == 200
    assert "template_overrides" not in repo.get_task_private(task["id"])["payload"]


def test_task_config_override_endpoint_prunes_empty_nested_values(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)
    first = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "dxm_reference",
            "values": {
                "dxm_reference_templates": {
                    "freight": {"names": "半托管运费模板"},
                    "service": {"names": ""},
                }
            },
        },
    )
    assert first.status_code == 200
    assert repo.get_task_private(task["id"])["payload"]["template_overrides"]["dxm_reference"] == {
        "dxm_reference_templates": {"freight": {"names": ["半托管运费模板"]}}
    }

    cleared = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "dxm_reference",
            "values": {
                "dxm_reference_templates": {
                    "freight": {"names": ""},
                    "service": {"names": ""},
                }
            },
        },
    )

    assert cleared.status_code == 200
    assert "template_overrides" not in repo.get_task_private(task["id"])["payload"]


def test_task_config_override_normalizes_dxm_reference_names_to_arrays(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={
            "section": "dxm_reference",
            "values": {
                "dxm_reference_templates": {
                    "freight": {"names": "半托管运费模板 / 普货模板\n半托管运费模板"},
                    "service": {"names": ["无忧服务", ""]},
                }
            },
        },
    )

    assert response.status_code == 200
    stored = repo.get_task_private(task["id"])["payload"]["template_overrides"]["dxm_reference"]
    assert stored["dxm_reference_templates"]["freight"]["names"] == ["半托管运费模板", "普货模板"]
    assert stored["dxm_reference_templates"]["service"]["names"] == ["无忧服务"]
    preview = client.get(f"/api/config/preview?task_id={task['id']}").json()
    resolved = preview["resolvedDefaults"]["dxm_reference_templates_resolved"]
    assert resolved["freight"]["names"] == ["半托管运费模板", "普货模板"]
    assert resolved["service"]["names"] == ["无忧服务"]


def test_template_api_normalizes_dxm_reference_names_to_arrays(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)

    created = client.post(
        "/api/templates",
        json={
            "template_type": "dxm_reference",
            "template_name": "DXM 引用模板",
            "binding_scope": "Dang Kang",
            "payload": {
                "dxm_reference_templates": {
                    "freight": {"names": "半托管运费模板 / 普货模板\n半托管运费模板"},
                    "service": {"names": ["无忧服务", ""]},
                }
            },
            "is_enabled": True,
        },
    )

    assert created.status_code == 200
    created_payload = created.json()["payload"]["dxm_reference_templates"]
    assert created_payload["freight"]["names"] == ["半托管运费模板", "普货模板"]
    assert created_payload["service"]["names"] == ["无忧服务"]

    updated = client.patch(
        f"/api/templates/{created.json()['id']}",
        json={
            "payload": {
                "dxm_reference_templates": {
                    "freight": {"names": "升级模板，兜底模板"},
                }
            },
        },
    )

    assert updated.status_code == 200
    updated_payload = repo.list_templates()[0]["payload"]["dxm_reference_templates"]
    assert updated_payload["freight"]["names"] == ["升级模板", "兜底模板"]


def test_task_config_override_endpoint_rejects_unknown_section(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo)

    response = client.patch(
        f"/api/tasks/{task['id']}/config-overrides",
        json={"section": "publish", "values": {"enabled": True}},
    )

    assert response.status_code == 400


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
        for mode in ("single_save",):
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
    task = _create_task(repo, mode="single_save")
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


def test_direct_real_dxm_mutation_rejects_unreleased_modes_even_after_l2_and_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    monkeypatch.setattr(main, "login_flow", flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})

    endpoints = (
        "/api/dxm/draft-box/action",
        "/api/dxm/workflow/claim-product",
        "/api/dxm/workflow/open-editor",
    )
    for mode in ("batch_save",):
        task = _create_task(repo, mode=mode)
        token = f"{mode}-direct-token"
        _approve_task(repo, task["id"], token)
        for endpoint in endpoints:
            response = client.post(
                endpoint,
                json={
                    "action": "remark",
                    "note_text": "AI认领",
                    "task_id": task["id"],
                    "manual_approval": True,
                    "approval_token": token,
                    "approved_by": "ops-owner",
                    "confirmation": "CONFIRM_DXM_SAVE_ONLY",
                    "store_name": "Dang Kang",
                },
            )

            assert response.status_code == 403
            detail = response.json()["detail"].lower()
            assert "controlled claim_only and single_save" in detail
            assert "released" in detail
    assert flow.draft_box_actions == []


def test_direct_real_dxm_mutation_rejects_even_after_l2_and_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    flow = DummyDxmLoginFlow()
    task = _create_task(repo, mode="single_save")
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


def test_single_save_start_allows_any_real_store_after_approval_and_l2_gate(tmp_path, monkeypatch):
    client, repo, runner = _client_with_temp_repo(tmp_path, monkeypatch)
    import src.main as main

    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    task = _create_task(repo, store_name="Other Store")
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


def test_dry_run_can_start_without_manual_approval(tmp_path, monkeypatch):
    client, repo, _runner = _client_with_temp_repo(tmp_path, monkeypatch)
    task = _create_task(repo, mode="dry_run")

    response = client.post(f"/api/tasks/{task['id']}/start", json={})

    assert response.status_code == 200


def test_dxm_flow_dismisses_feature_guide_next_step_modal():
    source = (Path(__file__).resolve().parents[1] / "src" / "execution" / "dxm_login_flow.py").read_text(encoding="utf-8")

    assert "['跳过','下一步','完成','我知道了','知道了','关闭','取消']" in source
    assert "['跳过','下一步','完成','我知道了','知道了','关闭','确定','下一条']" in source
    assert "page.wait_for_timeout(1200)\n            self._dismiss_blocking_modals(page)" in source
