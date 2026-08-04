from fastapi.testclient import TestClient
import base64
import hashlib
from pathlib import Path
import pytest

from src import db
from src.core import config
from src.main import app
from src.repository import Repository
from src.state_machine.two_stage import (
    TwoStageContractError,
    build_stage_a_task_facts,
    canonical_claim_target_identity,
    canonical_source_identity,
    verify_draft_box_proof,
)


_MINIMAL_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _client_with_temp_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "acquisition-claim-workflow.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    repo = Repository()
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    return TestClient(app), repo


def _evidence_ref(name: str) -> dict:
    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = (config.SCREENSHOT_DIR / name).resolve()
    content = _MINIMAL_VALID_PNG
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


def _complete_verified_claim(
    repo: Repository,
    *,
    store: dict,
    claim_task: dict,
    title: str,
    category_name: str,
    source_url: str,
):
    job = repo.get_task_private(claim_task["id"])["jobs"][0]
    repo.update_task_status(claim_task["id"], "running")
    repo.update_job(job["id"], status="running")
    source_identity = canonical_source_identity(source_url, [source_url])
    task_payload = repo.get_task_private(claim_task["id"])["payload"]
    target_identity = canonical_claim_target_identity(
        task_payload.get("source_url"),
        task_payload.get("source_urls") or (),
        keyword=task_payload.get("keyword"),
        category_name=task_payload.get("category_name"),
    )
    result = repo.create_claimed_product_and_complete_acquisition(
        claim_task["id"],
        {
            "title": title,
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": category_name,
            "price": 9.9,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": store["name"],
                "source_url": source_url,
                "source_urls": [source_url],
                "claim_task_id": claim_task["id"],
                "claim_mark": "AI-OPS",
                "draft_box_verified": True,
            },
        },
        draft_box_observation={
            "schema": "dxm.draft_box.observation.v1",
            "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
            "action": "verify_draft_box_claim",
            "draft_box_verified": True,
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            "authorized_target_identity": target_identity,
            "authorized_target_fingerprint": target_identity["fingerprint"],
            "observed_source_identity": source_identity,
            "observed_store_identity": {
                "store_id": store["id"],
                "store_name": store["name"],
                "selected": True,
                "selected_store_names": [store["name"]],
                "selection_evidence": {"input_checked": True},
                "draft_box_cell_evidence": {
                    "store_name": store["name"],
                    "cell_text": f"「{store['name']}」",
                    "source": "structured_store_cell",
                },
            },
            "matched_by": ["source_url"],
            "match_evidence": {"source_url": source_identity["primary_url"]},
            "observed_product_identity": title,
            "observed_row_identity": f"商品箱行 {title} {store['name']}",
            "evidence_ref": _evidence_ref(f"claim-{claim_task['id']}.png"),
        },
    )
    assert result.applied is True
    return result


def test_claim_completion_builds_exact_draft_box_proof_in_atomic_product_transaction(tmp_path, monkeypatch):
    _client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "store_name": store["name"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    job = repo.get_task_private(claim_task["id"])["jobs"][0]
    repo.update_task_status(claim_task["id"], "running")
    repo.update_job(job["id"], status="running")
    source_identity = canonical_source_identity(source_url, [source_url])
    target_identity = canonical_claim_target_identity(
        source_url,
        [source_url],
        keyword="真实待认领商品 A",
        category_name="立牌类谷子",
    )
    stage_a_task_facts = build_stage_a_task_facts(
        task_id=claim_task["id"],
        job_id=job["id"],
        store_id=store["id"],
        target_identity=target_identity,
    )
    observation = {
        "schema": "dxm.draft_box.observation.v1",
        "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
        "action": "verify_draft_box_claim",
        "draft_box_verified": True,
        "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
        "authorized_target_identity": target_identity,
        "authorized_target_fingerprint": target_identity["fingerprint"],
        "observed_source_identity": source_identity,
        "observed_store_identity": {
            "store_id": store["id"],
            "store_name": store["name"],
            "selected": True,
            "selected_store_names": [store["name"]],
            "selection_evidence": {"input_checked": True},
            "draft_box_cell_evidence": {
                "store_name": store["name"],
                "cell_text": f"「{store['name']}」",
                "source": "structured_store_cell",
            },
        },
        "matched_by": ["source_url"],
        "match_evidence": {"source_url": source_identity["primary_url"]},
        "observed_product_identity": "真实待认领商品 A",
        "observed_row_identity": f"商品箱行 真实待认领商品 A {store['name']}",
        "evidence_ref": _evidence_ref("claim-proof.png"),
    }

    result = repo.create_claimed_product_and_complete_acquisition(
        claim_task["id"],
        {
            "title": "真实待认领商品 A",
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": "立牌类谷子",
            "price": 0,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 0,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "source_url": source_url,
                "source_urls": [source_url],
                "claim_task_id": claim_task["id"],
                "draft_box_verified": True,
            },
        },
        draft_box_observation=observation,
    )

    assert result.applied is True
    proof = result.product["payload"]["draft_box_proof"]
    assert verify_draft_box_proof(
        proof,
        stage_a_task_facts=stage_a_task_facts,
        product_id=result.product["id"],
    ) == {"ok": True, "reason_code": "OK"}
    task_payload = result.task["payload"]
    assert task_payload["claim_job_id"] == job["id"]
    assert task_payload["store_id"] == store["id"]
    assert task_payload["stage_a_task_facts"] == stage_a_task_facts
    assert task_payload["claim_target_identity"] == target_identity
    assert task_payload["claimed_product_source_identity"] == source_identity
    assert task_payload["draft_box_proof"] == proof
    assert repo.product_has_completed_claim_provenance(result.product) is True

    Path(proof["proof_content"]["evidence_ref"]["path"]).write_bytes(b"tampered")
    assert repo.product_has_completed_claim_provenance(repo.get_product(result.product["id"])) is False


@pytest.mark.parametrize("evidence_kind", ["code_file", "txt_file", "fake_png"])
def test_stage_a_rejects_unscoped_or_non_png_draft_box_evidence(
    tmp_path,
    monkeypatch,
    evidence_kind,
):
    _client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    job = repo.get_task_private(claim_task["id"])["jobs"][0]
    repo.update_task_status(claim_task["id"], "running")
    repo.update_job(job["id"], status="running")
    source_identity = canonical_source_identity(source_url, [source_url])
    target_identity = canonical_claim_target_identity(
        source_url,
        [source_url],
        keyword="真实待认领商品 A",
        category_name="立牌类谷子",
    )
    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if evidence_kind == "code_file":
        evidence_path = Path(__file__).resolve()
        evidence_content = evidence_path.read_bytes()
    elif evidence_kind == "txt_file":
        evidence_path = (config.SCREENSHOT_DIR / "stage-a-evidence.txt").resolve()
        evidence_content = _MINIMAL_VALID_PNG
        evidence_path.write_bytes(evidence_content)
    else:
        evidence_path = (config.SCREENSHOT_DIR / "stage-a-fake.png").resolve()
        evidence_content = b"not a real png"
        evidence_path.write_bytes(evidence_content)
    evidence_ref = {
        "path": str(evidence_path),
        "sha256": hashlib.sha256(evidence_content).hexdigest().upper(),
        "size": len(evidence_content),
    }
    observation = {
        "schema": "dxm.draft_box.observation.v1",
        "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
        "action": "verify_draft_box_claim",
        "draft_box_verified": True,
        "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
        "authorized_target_identity": target_identity,
        "authorized_target_fingerprint": target_identity["fingerprint"],
        "observed_source_identity": source_identity,
        "observed_store_identity": {
            "store_id": store["id"],
            "store_name": store["name"],
            "selected": True,
            "selected_store_names": [store["name"]],
            "selection_evidence": {"input_checked": True},
            "draft_box_cell_evidence": {
                "store_name": store["name"],
                "cell_text": f"「{store['name']}」",
                "source": "structured_store_cell",
            },
        },
        "matched_by": ["source_url"],
        "match_evidence": {"source_url": source_identity["primary_url"]},
        "observed_product_identity": "真实待认领商品 A",
        "observed_row_identity": f"商品箱行 真实待认领商品 A {store['name']}",
        "evidence_ref": evidence_ref,
    }

    with pytest.raises(TwoStageContractError) as raised:
        repo.create_claimed_product_and_complete_acquisition(
            claim_task["id"],
            {
                "title": "真实待认领商品 A",
                "source": "dxm_data_acquisition",
                "status": "claimed_to_draft",
                "category_name": "立牌类谷子",
                "price": 0,
                "currency": "USD",
                "sku_count": 1,
                "image_count": 0,
                "payload": {
                    "source": "dxm_data_acquisition",
                    "store_id": store["id"],
                    "source_url": source_url,
                    "source_urls": [source_url],
                    "claim_task_id": claim_task["id"],
                    "draft_box_verified": True,
                },
            },
            draft_box_observation=observation,
        )
    assert raised.value.reason_code == "CLAIM_PROOF_INVALID"
    assert repo.list_products(include_fixtures=True) == []


def test_acquisition_claim_request_creates_claim_stage_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"

    response = client.post(
        "/api/acquisition/claim-requests",
        json={
            "store_id": store["id"],
            "source_url": source_url,
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
    assert data["source_url"] == source_url
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
    assert task["payload"]["source_url"] == source_url
    assert repo.list_products(include_fixtures=True) == []


def test_mark_acquisition_claim_completed_rejects_late_success_without_rewriting_failure(tmp_path, monkeypatch):
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
            UPDATE tasks
               SET status='failed', completed_jobs=0, failed_jobs=1
             WHERE id=?
            """,
            (claim_task["id"],),
        )
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
    job = repo.get_task_private(claim_task["id"])["jobs"][0]
    repo.add_exception(
        claim_task["id"],
        job["id"],
        "E901",
        "v1_executor",
        "确认商品箱超时",
        "确认商品箱超时",
        "保留现场后重试。",
    )
    repo.add_report(
        claim_task["id"],
        job["id"],
        None,
        "failed",
        False,
        {"ok": False, "error_code": "E901", "message": "确认商品箱超时"},
        {"blocked_reason": "确认商品箱超时"},
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

    task_before = repo.get_task_private(claim_task["id"])
    reports_before = repo.list_reports(claim_task["id"])
    exceptions_before = repo.list_exceptions()

    result = repo.mark_acquisition_claim_completed(claim_task["id"], product)

    assert repo.get_task_private(claim_task["id"]) == task_before
    assert repo.list_reports(claim_task["id"]) == reports_before
    assert repo.list_exceptions() == exceptions_before
    assert result.applied is False
    assert result.idempotent is False
    assert result.conflict_code == "CLAIM_TERMINAL_STATE_CONFLICT"


def test_mark_acquisition_claim_completed_is_idempotent_for_the_same_verified_result(tmp_path, monkeypatch):
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
    first = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/1013604102950.html",
    )
    task_after_first = repo.get_task_private(claim_task["id"])
    second = repo.mark_acquisition_claim_completed(claim_task["id"], first.product)

    assert first.applied is True
    assert first.idempotent is False
    assert first.conflict_code is None
    assert second.applied is False
    assert second.idempotent is True
    assert second.conflict_code is None
    assert repo.get_task_private(claim_task["id"]) == task_after_first


def test_repeat_claim_completion_rejects_tampered_persisted_proof_instead_of_idempotence(tmp_path, monkeypatch):
    _client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    completed = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url=source_url,
    )
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM products WHERE id=?", (completed.product["id"],)).fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["draft_box_proof"]["fingerprint"] = "0" * 64
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps(payload), completed.product["id"]),
        )

    result = repo.mark_acquisition_claim_completed(
        claim_task["id"],
        repo.get_product(completed.product["id"]),
    )

    assert result.applied is False
    assert result.idempotent is False
    assert result.conflict_code == "CLAIM_PROOF_INVALID"


def test_completed_claim_provenance_rejects_tampered_product_proof(tmp_path, monkeypatch):
    _client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    completed = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url=source_url,
    )
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM products WHERE id=?", (completed.product["id"],)).fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["draft_box_proof"]["proof_content"]["observed_row_identity"] = "被篡改的商品箱行"
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps(payload), completed.product["id"]),
        )

    product = repo.get_product(completed.product["id"])

    assert repo.product_has_completed_claim_provenance(product) is False
    assert repo.list_claimed_draft_products() == []


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


def test_acquisition_claim_request_requires_source_url(tmp_path, monkeypatch):
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

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        item["loc"] == ["body", "source_url"] and item["type"] == "missing"
        for item in detail
    )


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
    product = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/1013604102950.html",
    ).product

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


def test_single_save_task_rejects_claim_proof_from_a_different_store(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    claim_store = repo.create_store("Dang Kang", "AliExpress")
    other_store = repo.create_store("Other Store", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": claim_store["id"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product = _complete_verified_claim(
        repo,
        store=claim_store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url=source_url,
    ).product

    response = client.post(
        "/api/tasks",
        json={
            "name": "跨店铺单商品只保存",
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "store_id": other_store["id"],
            "product_ids": [product["id"]],
            "payload": {"store_name": other_store["name"]},
        },
    )

    assert response.status_code == 409
    assert "store" in response.json()["detail"].lower() or "店铺" in response.json()["detail"]


def test_single_save_task_rejects_unproven_product_even_when_claimed_flags_present(tmp_path, monkeypatch):
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
    assert "已完成的待认领商品任务链" in detail
    assert "完成真实认领" in detail
    assert "商品进入商品箱" in detail


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
    product = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/1013604102950.html",
    ).product

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
    product_payload = product["payload"]
    assert task_payload["claim_job_id"] == product_payload["claim_job_id"]
    assert task_payload["store_id"] == product_payload["store_id"]
    assert task_payload["claimed_product_source_identity"] == product_payload["source_identity"]
    assert task_payload["stage_a_task_facts"] == product_payload["stage_a_task_facts"]
    assert task_payload["stage_a_task_facts_fingerprint"] == product_payload["stage_a_task_facts_fingerprint"]
    assert task_payload["claim_target_identity"] == product_payload["claim_target_identity"]
    assert task_payload["claim_target_fingerprint"] == product_payload["claim_target_fingerprint"]
    assert task_payload["draft_box_proof"] == product_payload["draft_box_proof"]
    assert task_payload["draft_box_proof_fingerprint"] == product_payload["draft_box_proof"]["fingerprint"]


def test_stage_b_task_facts_reject_tampered_save_task_snapshot(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "source_url": source_url,
            "keyword": "真实待认领商品 A",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    product = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url=source_url,
    ).product
    response = client.post(
        "/api/tasks",
        json={
            "name": "单商品只保存 - snapshot drift",
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "store_id": store["id"],
            "product_ids": [product["id"]],
            "payload": {"store_name": store["name"]},
        },
    )
    assert response.status_code == 200
    task_id = response.json()["id"]
    with db.connection() as conn:
        row = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
        payload = db.loads(row["payload_json"], {})
        payload["draft_box_proof_fingerprint"] = "0" * 64
        conn.execute("UPDATE tasks SET payload_json=? WHERE id=?", (db.dumps(payload), task_id))

    import src.main as main

    with pytest.raises(main.HTTPException) as exc_info:
        main._build_task_stage_facts(repo.get_task_private(task_id))

    assert exc_info.value.status_code == 409


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
    valid = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="真实待认领商品 A",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/1013604102950.html",
    ).product
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
    product = _complete_verified_claim(
        repo,
        store=store,
        claim_task=claim_task,
        title="正版玩具总动员攀爬吊饰钥匙扣挂件",
        category_name="QA_CATEGORY",
        source_url=source_url,
    ).product

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
