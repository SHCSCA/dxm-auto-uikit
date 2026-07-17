import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db
from src.core import config
from src.main import app
from src.repository import Repository
from src.services import delivery_workspace
from src.services.state_consistency import audit_state_consistency
from src.state_machine.two_stage import (
    canonical_claim_target_identity,
    canonical_source_identity,
)


_MINIMAL_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _evidence_ref(name: str, *, content: bytes | None = None) -> dict:
    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = (config.SCREENSHOT_DIR / name).resolve()
    content = _MINIMAL_VALID_PNG if content is None else content
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


def test_state_consistency_rejects_completed_task_with_failed_job():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 1,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "failed"}],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_TASK_COMPLETED_HAS_FAILED_JOB"]


def test_state_consistency_rejects_success_report_for_failed_job():
    result = audit_state_consistency(
        task={
            "id": 42,
            "status": "failed",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 1,
        },
        jobs=[{"id": 74, "task_id": 42, "status": "failed"}],
        reports=[{"id": 95, "task_id": 42, "job_id": 74, "status": "success"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_FAILED_JOB_HAS_SUCCESS_REPORT"]


def test_state_consistency_rejects_failed_report_for_succeeded_job():
    result = audit_state_consistency(
        task={
            "id": 43,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 75, "task_id": 43, "status": "succeeded"}],
        reports=[{"id": 96, "task_id": 43, "job_id": 75, "status": "failed"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_SUCCEEDED_JOB_HAS_FAILED_REPORT"]


def test_state_consistency_rejects_success_with_open_exception():
    result = audit_state_consistency(
        task={
            "id": 44,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 76, "task_id": 44, "status": "succeeded"}],
        reports=[{"id": 97, "task_id": 44, "job_id": 76, "status": "success"}],
        exceptions=[{"id": 108, "task_id": 44, "job_id": 76, "status": "open"}],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_SUCCESS_HAS_OPEN_EXCEPTION"]


def test_state_consistency_rejects_open_exception_bound_to_unknown_job():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "succeeded"}],
        reports=[{"id": 81, "task_id": 41, "job_id": 73, "status": "success"}],
        exceptions=[{"id": 91, "task_id": 41, "job_id": 999, "status": "open"}],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB",
        "STATE_SUCCESS_HAS_OPEN_EXCEPTION",
    ]


def test_state_consistency_rejects_resolved_exception_bound_to_unknown_job():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "running",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "running"}],
        reports=[],
        exceptions=[
            {"id": 91, "task_id": 41, "job_id": 999, "status": "resolved"}
        ],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB"
    ]


def test_state_consistency_rejects_closed_exception_bound_to_cross_task():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "running",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "running"}],
        reports=[],
        exceptions=[
            {"id": 91, "task_id": 999, "job_id": 73, "status": "closed"}
        ],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB"
    ]


def test_state_consistency_rejects_open_exception_without_job_binding():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "succeeded"}],
        reports=[{"id": 81, "task_id": 41, "job_id": 73, "status": "success"}],
        exceptions=[{"id": 91, "task_id": 41, "job_id": None, "status": "open"}],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB",
        "STATE_SUCCESS_HAS_OPEN_EXCEPTION",
    ]


def test_state_consistency_rejects_cross_task_report_and_exception_bindings():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "succeeded"}],
        reports=[{"id": 81, "task_id": 999, "job_id": 73, "status": "success"}],
        exceptions=[{"id": 91, "task_id": 999, "job_id": 73, "status": "open"}],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_REPORT_REFERENCES_UNKNOWN_JOB",
        "STATE_EXCEPTION_REFERENCES_UNKNOWN_JOB",
        "STATE_SUCCESS_HAS_OPEN_EXCEPTION",
    ]


def test_state_consistency_rejects_task_counter_mismatch():
    result = audit_state_consistency(
        task={
            "id": 45,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[{"id": 77, "task_id": 45, "status": "succeeded"}],
        reports=[{"id": 98, "task_id": 45, "job_id": 77, "status": "success"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_TASK_COUNTER_MISMATCH"]
    assert result["violations"][0]["expected"] == {
        "total_jobs": 1,
        "completed_jobs": 1,
        "failed_jobs": 0,
    }


def test_state_consistency_accepts_matching_terminal_success_facts():
    result = audit_state_consistency(
        task={
            "id": 46,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 78, "task_id": 46, "status": "succeeded"}],
        reports=[{"id": 99, "task_id": 46, "job_id": 78, "status": "success"}],
        exceptions=[],
    )

    assert result == {
        "schema": "dxm_state_consistency.v1",
        "consistent": True,
        "violation_codes": [],
        "violations": [],
        "audited_task_ids": [46],
    }


def test_state_consistency_rejects_success_report_for_pending_job():
    result = audit_state_consistency(
        task={
            "id": 47,
            "status": "draft",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[{"id": 79, "task_id": 47, "status": "pending"}],
        reports=[{"id": 100, "task_id": 47, "job_id": 79, "status": "success"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_SUCCESS_REPORT_REQUIRES_SUCCEEDED_JOB"]


def test_state_consistency_rejects_completed_task_with_pending_job():
    result = audit_state_consistency(
        task={
            "id": 48,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[{"id": 80, "task_id": 48, "status": "pending"}],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_COMPLETED_TASK_REQUIRES_ALL_JOBS_SUCCEEDED"
    ]


def test_state_consistency_rejects_failed_task_with_nonfailed_job():
    result = audit_state_consistency(
        task={
            "id": 49,
            "status": "failed",
            "total_jobs": 2,
            "completed_jobs": 0,
            "failed_jobs": 1,
        },
        jobs=[
            {"id": 81, "task_id": 49, "status": "failed"},
            {"id": 82, "task_id": 49, "status": "pending"},
        ],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_FAILED_TASK_REQUIRES_ALL_JOBS_FAILED"
    ]


def test_state_consistency_rejects_partial_success_without_mixed_terminal_jobs():
    result = audit_state_consistency(
        task={
            "id": 50,
            "status": "partial_success",
            "total_jobs": 2,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[
            {"id": 83, "task_id": 50, "status": "succeeded"},
            {"id": 84, "task_id": 50, "status": "pending"},
        ],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_PARTIAL_SUCCESS_REQUIRES_MIXED_TERMINAL_JOBS"
    ]


def test_state_consistency_rejects_report_that_references_unknown_job():
    result = audit_state_consistency(
        task={
            "id": 51,
            "status": "draft",
            "total_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0,
        },
        jobs=[],
        reports=[{"id": 101, "task_id": 51, "job_id": 999, "status": "success"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_REPORT_REFERENCES_UNKNOWN_JOB"]


def test_state_consistency_rejects_report_without_job_binding():
    result = audit_state_consistency(
        task={
            "id": 41,
            "status": "completed",
            "total_jobs": 1,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[{"id": 73, "task_id": 41, "status": "succeeded"}],
        reports=[{"id": 81, "job_id": None, "status": "success"}],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == ["STATE_REPORT_REFERENCES_UNKNOWN_JOB"]


def test_state_consistency_rejects_running_task_when_all_jobs_are_terminal():
    result = audit_state_consistency(
        task={
            "id": 52,
            "status": "running",
            "total_jobs": 2,
            "completed_jobs": 1,
            "failed_jobs": 1,
        },
        jobs=[
            {"id": 102, "task_id": 52, "status": "succeeded"},
            {"id": 103, "task_id": 52, "status": "failed"},
        ],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is False
    assert result["violation_codes"] == [
        "STATE_NONTERMINAL_TASK_HAS_ALL_TERMINAL_JOBS"
    ]


def test_state_consistency_allows_running_multi_job_task_with_work_remaining():
    result = audit_state_consistency(
        task={
            "id": 53,
            "status": "running",
            "total_jobs": 2,
            "completed_jobs": 1,
            "failed_jobs": 0,
        },
        jobs=[
            {"id": 104, "task_id": 53, "status": "succeeded"},
            {"id": 105, "task_id": 53, "status": "running"},
        ],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is True
    assert result["violation_codes"] == []


def test_state_consistency_treats_needs_manual_review_as_terminal_task_outcome():
    result = audit_state_consistency(
        task={
            "id": 54,
            "status": "needs_manual_review",
            "total_jobs": 1,
            "completed_jobs": 0,
            "failed_jobs": 1,
        },
        jobs=[{"id": 106, "task_id": 54, "status": "failed"}],
        reports=[],
        exceptions=[],
    )

    assert result["consistent"] is True
    assert "STATE_NONTERMINAL_TASK_HAS_ALL_TERMINAL_JOBS" not in result[
        "violation_codes"
    ]


def test_delivery_workspace_blocks_every_ready_surface_on_state_contradiction(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_two_stage_delivery_fixture(repo)
    repo.update_job(fixture["save_job"]["id"], status="failed", error_code="E901")
    repo.update_task_status(
        fixture["save_task"]["id"],
        "failed",
        completed_jobs=0,
        failed_jobs=1,
    )
    repo.add_exception(
        fixture["save_task"]["id"],
        fixture["save_job"]["id"],
        "E901",
        "save",
        "保存失败",
        "真实保存失败后收到迟到成功结果",
        "保持失败并创建新的任务重试",
    )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["state_consistency"]["consistent"] is False
    assert data["state_consistency"]["violation_codes"] == [
        "STATE_FAILED_JOB_HAS_SUCCESS_REPORT",
        "STATE_SUCCESS_HAS_OPEN_EXCEPTION",
    ]
    assert data["delivery_readiness"]["ready"] is False
    assert data["delivery_readiness"]["blocked_by_state_consistency"] is True
    state_gap = next(
        gap for gap in data["acceptanceGaps"] if gap["id"] == "gap-state-consistency"
    )
    assert state_gap["severity"] == "blocker"
    assert "STATE_FAILED_JOB_HAS_SUCCESS_REPORT" in state_gap["detail"]
    assert data["two_stage_acceptance"]["passed"] is False
    assert data["two_stage_acceptance"]["status"] == "inconsistent_state"
    assert "state_consistency" in data["two_stage_acceptance"]["missing_codes"]
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert "STATE_FAILED_JOB_HAS_SUCCESS_REPORT" in l3_gate["detail"]


def test_delivery_workspace_aggregates_linked_claim_task_contradictions(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    claim_job = repo.get_task(fixture["claim_task"]["id"])["jobs"][0]
    repo.update_job(claim_job["id"], status="failed", error_code="E901")
    repo.update_task_status(
        fixture["claim_task"]["id"],
        "failed",
        completed_jobs=0,
        failed_jobs=1,
    )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["state_consistency"]["consistent"] is False
    violation = next(
        item
        for item in data["state_consistency"]["violations"]
        if item["code"] == "STATE_FAILED_JOB_HAS_SUCCESS_REPORT"
    )
    assert violation["task_id"] == fixture["claim_task"]["id"]
    assert data["state_consistency"]["audited_task_ids"] == [
        fixture["save_task"]["id"],
        fixture["claim_task"]["id"],
    ]
    assert data["two_stage_acceptance"]["status"] == "inconsistent_state"
    assert data["two_stage_acceptance"]["passed"] is False


def test_delivery_workspace_requires_completed_save_task_for_all_ready_surfaces(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    repo.update_task_status(
        fixture["save_task"]["id"],
        "running",
        completed_jobs=1,
        failed_jobs=0,
    )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["delivery_readiness"]["task_completed"] is False
    assert data["delivery_readiness"]["blocked_by_task_status"] is True
    assert data["two_stage_acceptance"]["passed"] is False
    assert data["two_stage_acceptance"]["checks"]["save_task_completed"] is False
    assert "save_task_completed" in data["two_stage_acceptance"]["missing_codes"]


def test_two_stage_acceptance_calls_terminal_manual_review_an_incomplete_save_stage(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    repo.update_task_status(
        fixture["save_task"]["id"],
        "needs_manual_review",
        completed_jobs=1,
        failed_jobs=0,
    )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["state_consistency"]["consistent"] is True
    assert data["delivery_readiness"]["ready"] is False
    assert data["two_stage_acceptance"]["passed"] is False
    assert data["two_stage_acceptance"]["status"] == "missing_save_stage"
    assert "save_task_completed" in data["two_stage_acceptance"]["missing_codes"]


def test_delivery_workspace_does_not_lose_task_exception_beyond_global_limit(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    repo.add_exception(
        fixture["save_task"]["id"],
        fixture["save_job"]["id"],
        "E901",
        "save",
        "保存失败历史",
        "成功事实仍保留未处理异常",
        "创建新任务重试",
    )
    for index in range(205):
        repo.add_exception(
            900_000 + index,
            None,
            "ENOISE",
            "unrelated",
            "无关异常",
            f"noise-{index}",
            "ignore",
        )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["state_consistency"]["consistent"] is False
    assert "STATE_SUCCESS_HAS_OPEN_EXCEPTION" in data["state_consistency"]["violation_codes"]
    violation = next(
        item
        for item in data["state_consistency"]["violations"]
        if item["code"] == "STATE_SUCCESS_HAS_OPEN_EXCEPTION"
    )
    assert violation["task_id"] == fixture["save_task"]["id"]


def test_delivery_workspace_does_not_lose_linked_claim_exception_beyond_global_limit(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    claim_job = repo.get_task(fixture["claim_task"]["id"])["jobs"][0]
    repo.add_exception(
        fixture["claim_task"]["id"],
        claim_job["id"],
        "E901",
        "claim",
        "认领失败历史",
        "认领成功事实仍保留未处理异常",
        "创建新任务重试",
    )
    for index in range(205):
        repo.add_exception(
            910_000 + index,
            None,
            "ENOISE",
            "unrelated",
            "无关异常",
            f"claim-noise-{index}",
            "ignore",
        )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    violation = next(
        item
        for item in data["state_consistency"]["violations"]
        if item["code"] == "STATE_SUCCESS_HAS_OPEN_EXCEPTION"
        and item["task_id"] == fixture["claim_task"]["id"]
    )
    assert violation["job_id"] == claim_job["id"]


def _fresh_l2_created_at(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _table_signature() -> dict:
    with db.connection() as conn:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            table: conn.execute(f"PRAGMA table_info({table})").fetchall()
            for table in tables
        }


def _create_verified_claimed_product(
    repo: Repository,
    store: dict,
    *,
    product_title: str,
    category_name: str = "立牌类谷子",
    source_url: str = "https://detail.1688.com/offer/1013604102950.html",
    claim_mark: str = "AI-OPS",
    price: float = 9.9,
    sku_count: int = 1,
    image_count: int = 1,
    test_only: bool = False,
) -> tuple[dict, dict]:
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "store_name": store["name"],
            "source_url": source_url,
            "keyword": product_title,
            "category_name": category_name,
            "claim_mark": claim_mark,
            "template_id": None,
            **(
                {"test_only": True, "data_origin": "test_fixture"}
                if test_only
                else {}
            ),
        }
    )
    claim_job = repo.get_task_private(claim_task["id"])["jobs"][0]
    repo.update_task_status(claim_task["id"], "running")
    repo.update_job(claim_job["id"], status="running")
    source_identity = canonical_source_identity(source_url, [source_url])
    target_identity = canonical_claim_target_identity(
        source_url,
        [source_url],
        keyword=product_title,
        category_name=category_name,
    )
    claim_result = repo.create_claimed_product_and_complete_acquisition(
        claim_task["id"],
        {
            "title": product_title,
            "source": "dxm_data_acquisition",
            "status": "claimed_to_draft",
            "category_name": category_name,
            "price": price,
            "currency": "USD",
            "sku_count": sku_count,
            "image_count": image_count,
            "payload": {
                "source": "dxm_data_acquisition",
                "store_id": store["id"],
                "store_name": store["name"],
                "source_url": source_url,
                "source_urls": [source_url],
                "claim_task_id": claim_task["id"],
                "claim_mark": claim_mark,
                "draft_box_verified": True,
                "source_title": product_title,
                **(
                    {"test_only": True, "data_origin": "test_fixture"}
                    if test_only
                    else {}
                ),
            },
        },
        draft_box_observation={
            "schema": "dxm.draft_box.observation.v1",
            "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
            "action": "verify_draft_box_claim",
            "draft_box_verified": True,
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
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
            "observed_product_identity": product_title,
            "observed_row_identity": f"商品箱行 {product_title} {category_name} {store['name']}",
            "evidence_ref": _evidence_ref(f"claim-{claim_task['id']}.png"),
        },
    )
    assert claim_result.applied is True
    product = claim_result.product
    assert product is not None
    if test_only:
        persisted_claim_task = repo.get_task_private(claim_task["id"])
        marked_payload = dict(persisted_claim_task["payload"])
        marked_payload.update({"test_only": True, "data_origin": "test_fixture"})
        with db.connection() as conn:
            conn.execute(
                "UPDATE tasks SET payload_json=? WHERE id=?",
                (json.dumps(marked_payload, ensure_ascii=False), claim_task["id"]),
            )
        claim_task = repo.get_task_private(claim_task["id"])
    return product, claim_task


def _create_legacy_single_save_task(
    repo: Repository,
    store: dict,
    product: dict,
    *,
    name: str,
    claim_mark: str = "AI-OPS",
    payload: dict | None = None,
) -> dict:
    """Persist a pre-invariant single-save row for read-side compatibility tests."""

    task = repo.create_task(
        {
            "name": name,
            "store_id": store["id"],
            "mode": "dry_run",
            "publish_scene": "DRY_RUN",
            "claim_mark": claim_mark,
            "product_ids": [product["id"]],
            "payload": dict(payload or {}),
        }
    )
    legacy_payload = dict(task["payload"])
    legacy_payload.update(
        {
            "mode": "single_save",
            "execution_mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        }
    )
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET mode='single_save', publish_scene='SMT_SEMI_MANAGED_SAVE_ONLY', payload_json=? WHERE id=?",
            (json.dumps(legacy_payload, ensure_ascii=False), task["id"]),
        )
    return repo.get_task_private(task["id"])


def _create_delivery_fixture(
    repo: Repository,
    *,
    with_network: bool = True,
    with_verify_proof: bool = True,
    with_publish_network: bool = False,
    published_value=False,
) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="ACG Stand Product",
        claim_mark="AI认领",
        price=7.01,
        sku_count=8,
        image_count=8,
    )
    task = repo.create_task(
        {
            "name": "交付工作台任务",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": {
                "store_name": "Dang Kang",
                "dxm_reference_templates": {
                    "freight": {"names": ["40g普货包裹"], "required": True},
                    "description": {"names": [], "required": False},
                },
            },
        }
    )
    job = repo.get_task(task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
    }
    if with_network:
        network_events = [
            {
                "method": "POST",
                "url": "https://www.dianxiaomi.com/api/smt/product/save",
                "status": 200,
            }
        ]
        if with_publish_network:
            network_events.append(
                {
                    "method": "POST",
                    "url": "https://www.dianxiaomi.com/api/smt/product/publish",
                    "status": 200,
                }
            )
        save_result.update(
            {
                "network_save_result": {
                    "ok": True,
                    "method": "POST",
                    "url": "https://www.dianxiaomi.com/api/smt/product/save",
                    "code": 0,
                    "msg": "产品已保存到「待发布」",
                },
                "network_events": network_events,
                "har_summary": {
                    "save_response_seen": True,
                    "path": "data/network_logs/save.har",
                },
            }
        )

    summary = {
        "task_id": task["id"],
        "job_id": job["id"],
        "product_id": product["id"],
        "store_name": "Dang Kang",
        "source_title": "ACG Stand Product",
        "category": "立牌类谷子",
        "claim_mark": f"AI认领-{task['id']}-{job['id']}",
        "mode": "single_save",
        "status": "success",
        "filled_fields": ["base_info", "variants", "media", "compliance", "semi_goods"],
        "empty_fields": ["货品条码：配置允许留空"],
        "evidence_paths": ["data/screenshots/save.txt", "data/screenshots/not_published.txt"],
        "dxm_reference_templates_resolved": {
            "freight": {"names": ["40g普货包裹"], "required": True},
            "description": {"names": [], "required": False},
        },
        "dxm_reference_template_results": {
            "freight": {"ok": True, "section": "freight", "names": ["40g普货包裹"], "required": True},
            "description": {"ok": True, "section": "description", "names": [], "required": False},
        },
        "template_trace": [
            {
                "template_id": 1,
                "template_type": "dxm_reference",
                "template_name": "Dxm Reference",
                "binding_scope": "V1",
            }
        ],
        "workflow_actions": ["save_only", "verify_not_published"],
        "workflow_results": [
            {
                "action": "save_only",
                "ok": True,
                "save_result": save_result,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_save_only.png",
            },
            {
                "action": "verify_not_published",
                "ok": True,
                "published": published_value,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_verify_not_published.png",
            },
        ],
        "published": published_value,
    }
    if not with_verify_proof:
        summary["workflow_results"] = [item for item in summary["workflow_results"] if item["action"] != "verify_not_published"]
    state_evidence_ref = _evidence_ref(f"state-{task['id']}-{job['id']}.png")
    save_evidence_ref = _evidence_ref(f"save-{task['id']}-{job['id']}.png")
    unpublished_evidence_ref = (
        _evidence_ref(f"unpublished-{task['id']}-{job['id']}.png")
        if with_verify_proof
        else None
    )
    repo.add_evidence(
        task["id"],
        job["id"],
        "state_snapshot",
        state_evidence_ref["path"],
        {
            "state": "SAVE_ONLY",
            "field_domain": "save",
            "evidence_ref": state_evidence_ref,
        },
    )
    repo.add_evidence(
        task["id"],
        job["id"],
        "workflow_action",
        save_evidence_ref["path"],
        {
            "state": "SAVE_ONLY",
            "action": "save_only",
            "save_result": save_result,
            "evidence_ref": save_evidence_ref,
        },
    )
    if with_verify_proof:
        repo.add_evidence(
            task["id"],
            job["id"],
            "workflow_action",
            unpublished_evidence_ref["path"],
            {
                "state": "VERIFY_NOT_PUBLISHED",
                "action": "verify_not_published",
                "published": published_value,
                "evidence_ref": unpublished_evidence_ref,
            },
        )
    report = repo.add_report(task["id"], job["id"], product["id"], "success", False, save_result, summary)
    repo.update_job(job["id"], status="succeeded")
    repo.update_task_status(task["id"], "completed", completed_jobs=1, failed_jobs=0)
    return {"task": task, "job": job, "report": report}


def _create_two_stage_delivery_fixture(
    repo: Repository,
    *,
    l3_evidence_descriptors: bool = True,
) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    claim_task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "store_name": store["name"],
            "source_url": source_url,
            "keyword": "Hazbin Hotel 立牌",
            "category_name": "立牌类谷子",
            "claim_mark": "AI-OPS",
            "template_id": None,
        }
    )
    claim_job = repo.get_task(claim_task["id"])["jobs"][0]
    repo.update_task_status(claim_task["id"], "running")
    repo.update_job(claim_job["id"], status="running")
    source_identity = canonical_source_identity(source_url, [source_url])
    target_identity = canonical_claim_target_identity(
        source_url,
        [source_url],
        keyword="Hazbin Hotel 立牌",
        category_name="立牌类谷子",
    )
    claim_result = repo.create_claimed_product_and_complete_acquisition(
        claim_task["id"],
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
            "observed_product_identity": "真实待认领商品 A",
            "observed_row_identity": f"商品箱行 真实待认领商品 A {store['name']}",
            "evidence_ref": _evidence_ref(f"claim-{claim_task['id']}.png"),
        },
    )
    assert claim_result.applied is True
    product = claim_result.product
    assert product is not None
    claim_save_result = {
        "ok": True,
        "message": "已有商品认领已完成，商品已进入采集箱",
        "claimed_product_id": product["id"],
        "draft_box_verified": True,
        "published": False,
    }
    claim_summary = {
        "stage": "claimed_to_draft",
        "status": "success",
        "claimed_product": {
            "id": product["id"],
            "title": product["title"],
            "source": "dxm_data_acquisition",
            "source_url": source_url,
            "draft_box_verified": True,
        },
        "next_action": "进入采集箱编辑保存",
    }
    claim_report = repo.add_report(
        claim_task["id"],
        claim_job["id"],
        product["id"],
        "success",
        False,
        claim_save_result,
        claim_summary,
    )

    save_task = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang - 1 件商品",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI-OPS",
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
        }
    )
    save_job = repo.get_task(save_task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
        "network_save_result": {
            "ok": True,
            "method": "POST",
            "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
            "status": 200,
            "code": 0,
            "msg": "您的产品编辑保存成功！",
        },
    }
    save_summary = {
        "stage": "draft_edit_save",
        "status": "success",
        "product_id": product["id"],
        "claim_task_id": claim_task["id"],
        "claimed_product_id": product["id"],
        "workflow_actions": ["save_only", "verify_not_published"],
        "workflow_results": [
            {
                "action": "save_only",
                "ok": True,
                "save_result": save_result,
                "screenshot_url": "/artifacts/screenshots/save.png",
            },
            {
                "action": "verify_not_published",
                "ok": True,
                "published": False,
                "screenshot_url": "/artifacts/screenshots/not_published.png",
            },
        ],
        "published": False,
    }
    save_evidence_ref = _evidence_ref(f"save-{save_task['id']}-{save_job['id']}.png")
    unpublished_evidence_ref = _evidence_ref(
        f"unpublished-{save_task['id']}-{save_job['id']}.png"
    )
    repo.add_evidence(
        save_task["id"],
        save_job["id"],
        "workflow_action",
        save_evidence_ref["path"],
        {
            "state": "SAVE_ONLY",
            "action": "save_only",
            "save_result": save_result,
            **(
                {"evidence_ref": save_evidence_ref}
                if l3_evidence_descriptors
                else {}
            ),
        },
    )
    repo.add_evidence(
        save_task["id"],
        save_job["id"],
        "workflow_action",
        unpublished_evidence_ref["path"],
        {
            "state": "VERIFY_NOT_PUBLISHED",
            "action": "verify_not_published",
            "published": False,
            **(
                {"evidence_ref": unpublished_evidence_ref}
                if l3_evidence_descriptors
                else {}
            ),
        },
    )
    save_report = repo.add_report(save_task["id"], save_job["id"], product["id"], "success", False, save_result, save_summary)
    repo.update_job(save_job["id"], status="succeeded")
    repo.update_task_status(save_task["id"], "completed", completed_jobs=1, failed_jobs=0)
    return {
        "claim_task": claim_task,
        "claim_report": claim_report,
        "save_task": save_task,
        "save_job": save_job,
        "save_report": save_report,
        "product": product,
    }


def _create_delivery_fixture_with_missing_second_job(repo: Repository) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    products = [
        repo.create_product(
            {
                "title": f"ACG Stand Product {index}",
                "source": "test",
                "category_name": "立牌类谷子",
                "price": 7.01,
                "currency": "USD",
                "sku_count": 8,
                "image_count": 8,
                "payload": {"source_title": f"ACG Stand Product {index}"},
            }
        )
        for index in range(2)
    ]
    task = repo.create_task(
        {
            "name": "交付工作台批量任务",
            "store_id": store["id"],
            "mode": "batch_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"] for product in products],
            "payload": {"store_name": "Dang Kang"},
        }
    )
    first_job = repo.get_task(task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
        "network_save_result": {
            "ok": True,
            "method": "POST",
            "url": "https://www.dianxiaomi.com/api/smt/product/save",
            "code": 0,
            "msg": "产品已保存到「待发布」",
        },
        "har_summary": {"save_response_seen": True, "path": "data/network_logs/save.har"},
    }
    summary = {
        "task_id": task["id"],
        "job_id": first_job["id"],
        "product_id": products[0]["id"],
        "mode": "batch_save",
        "status": "success",
        "workflow_results": [
            {"action": "save_only", "ok": True, "save_result": save_result, "screenshot_url": "/artifacts/screenshots/save.png"},
            {"action": "verify_not_published", "ok": True, "published": False, "screenshot_url": "/artifacts/screenshots/not_published.png"},
        ],
        "published": False,
    }
    save_evidence_ref = _evidence_ref(
        f"batch-save-{task['id']}-{first_job['id']}.png"
    )
    unpublished_evidence_ref = _evidence_ref(
        f"batch-unpublished-{task['id']}-{first_job['id']}.png"
    )
    repo.add_evidence(
        task["id"],
        first_job["id"],
        "workflow_action",
        save_evidence_ref["path"],
        {
            "state": "SAVE_ONLY",
            "action": "save_only",
            "save_result": save_result,
            "evidence_ref": save_evidence_ref,
        },
    )
    repo.add_evidence(
        task["id"],
        first_job["id"],
        "workflow_action",
        unpublished_evidence_ref["path"],
        {
            "state": "VERIFY_NOT_PUBLISHED",
            "action": "verify_not_published",
            "published": False,
            "evidence_ref": unpublished_evidence_ref,
        },
    )
    repo.add_report(task["id"], first_job["id"], products[0]["id"], "success", False, save_result, summary)
    repo.update_job(first_job["id"], status="succeeded")
    repo.update_task_status(task["id"], "running", completed_jobs=1, failed_jobs=0)
    return {"task": task, "first_job": first_job}


def _client_with_temp_repo(tmp_path, monkeypatch):
    db_path = tmp_path / "delivery-workspace.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(delivery_workspace, "L1_REPLAY_DIR", tmp_path / "l1_selector_replay")
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", tmp_path / "runtime_l2_readonly_probe")
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", tmp_path / "l2_readonly_probe")
    db.init_db()
    repo = Repository()
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "_current_browser_session_id", lambda: "test-browser-context-generation")
    return TestClient(app), repo


def _write_l2_probe_result(
    directory,
    target: str,
    *,
    target_url: str,
    final_url: str | None = None,
    ok: bool = True,
    created_at: str | None = None,
    network: dict | None = None,
    run_id: str | None = "run-20260526T000000Z",
    script_sha256: str | None = "a" * 64,
    git_head: str | None = "b" * 40,
    cookie_file_sha256: str | None = "c" * 64,
    dom_html: str | None = None,
):
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or _fresh_l2_created_at()
    network_payload = {
        "request_count": 1,
        "write_request_count": 0,
        "non_read_request_count": 0,
        "blocked_request_count": 0,
        "forbidden_keyword_request_count": 0,
        "websocket_count": 0,
    }
    if network:
        network_payload.update(network)
    screenshot_path = directory / f"{target}.png"
    dom_path = directory / f"{target}.html"
    screenshot_path.write_bytes(f"{target} screenshot evidence".encode("utf-8"))
    dom_path.write_text(dom_html or f"<html><body>{target} dom evidence</body></html>", encoding="utf-8")
    path = directory / f"{target}_{created_at.replace(':', '').replace('-', '')}.json"
    payload = {
                "schema": "dxm_l2_readonly_probe.v1",
                "ok": ok,
                "target": target,
                "target_url": target_url,
                "final_url": final_url or target_url,
                "created_at": created_at,
                "markdown_path": f"data/l2_readonly_probe/{target}.md",
                "screenshot_path": str(screenshot_path),
                "screenshot_sha256": hashlib.sha256(screenshot_path.read_bytes()).hexdigest(),
                "dom_path": str(dom_path),
                "dom_sha256": hashlib.sha256(dom_path.read_bytes()).hexdigest(),
                "network": network_payload,
                "login_state": {
                    "required": True,
                    "cookies_loaded": True,
                    "suspected_login_page": False,
                    "signals": [],
                },
                "safety": {
                    "ok": ok,
                    "mode": "L2_READ_ONLY",
                    "reasons": [] if ok else ["blocked by test"],
                },
    }
    if run_id is not None:
        payload["run_id"] = run_id
    if script_sha256 is not None:
        payload["script_sha256"] = script_sha256
    if git_head is not None:
        payload["git_head"] = git_head
    if cookie_file_sha256 is not None:
        payload["cookie_file_sha256"] = cookie_file_sha256
    if any(payload.get(field) is not None for field in ("run_id", "script_sha256", "git_head", "cookie_file_sha256")):
        payload["evidence_binding"] = {
            "schema": "dxm_l2_evidence_binding.v1",
            "run_id": payload.get("run_id"),
            "target_set": ["data_acquisition", "draft_box"],
            "session_fingerprint_sha256": payload.get("cookie_file_sha256"),
            "script_path": "tools/probes/l2_readonly_probe.py",
            "script_sha256": payload.get("script_sha256"),
            "git_head": payload.get("git_head"),
            "git_dirty": False,
            "git_diff_sha256": None,
        }
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_delivery_workspace_returns_frontend_contract(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    assert set(data) >= {
        "baseline",
        "current_task",
        "stores",
        "templates",
        "products",
        "tasks",
        "steps",
        "evidences",
        "evidence_points",
        "reports",
        "report_summary",
        "template_resolution",
        "dxmReferenceTemplates",
        "publish_guard_state",
        "evidence_grade",
        "regression_gates",
        "acceptanceGaps",
        "safety",
        "l2_probe_plan",
    }
    assert data["baseline"]["schema"] == "delivery_workspace.v1"
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert any(step["state"] == "SAVE_ONLY" and step["has_evidence"] and step["has_workflow_result"] for step in data["steps"])
    assert data["report_summary"]["latest_report"]["save_result"]["ok"] is True
    assert data["report_summary"]["latest_report"]["published"] is False
    assert any(point["kind"] == "network_save_result" for point in data["evidence_points"])
    assert any(point["kind"] == "published_proof" for point in data["evidence_points"])
    for kind in ("save_result", "published_proof", "network_save_result"):
        point = next(point for point in data["evidence_points"] if point["kind"] == kind)
        assert point["task_id"] == fixture["task"]["id"]
        assert point["report_id"] == data["reports"][0]["id"]
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"
    assert [gate["level"] for gate in data["regression_gates"]] == ["L0", "L1", "L2", "L3"]
    assert data["regression_gates"][1]["status"] == "not_run"
    assert data["regression_gates"][2]["status"] == "not_run"
    assert data["regression_gates"][3]["status"] == "blocked"
    assert data["safety"]["evidenceGrade"] == "C"
    assert data["dxmReferenceTemplates"][2]["section"] == "freight"
    assert data["dxmReferenceTemplates"][2]["templateNames"] == ["40g普货包裹"]
    assert data["real_mode_release_plan"]["schema"] == "dxm_real_mode_release_plan.v1"
    assert [item["mode"] for item in data["real_mode_release_plan"]["modes"]] == ["single_save", "claim_only", "batch_save"]


def test_delivery_workspace_exposes_unreleased_real_mode_release_plan(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    plan = response.json()["real_mode_release_plan"]
    assert plan["scope"] == "controlled_claim_and_single_save"
    assert plan["batch_unattended_publish_allowed"] is False
    assert plan["publish_allowed"] is False
    modes = {item["mode"]: item for item in plan["modes"]}
    assert modes["single_save"]["status"] == "blocked_stale_l2"
    assert modes["single_save"]["allowed"] is False
    assert modes["single_save"]["release_scope"] == "single product save-only canary"
    assert modes["single_save"]["blockers"]
    single_save_checklist = {item["id"]: item for item in modes["single_save"]["readiness_checklist"]}
    assert single_save_checklist["l2_dual_target"]["status"] == "blocked"
    assert single_save_checklist["l2_dual_target"]["blocker"] == "fresh L2 existing-claim-list and draft-box readonly proof is missing or stale"
    assert single_save_checklist["l3_single_canary"]["status"] == "passed"
    assert "historical single_save canary" in single_save_checklist["l3_single_canary"]["label"]
    assert modes["claim_only"]["status"] == "blocked_stale_l2"
    assert modes["claim_only"]["allowed"] is False
    assert modes["claim_only"]["release_scope"] == "controlled claim to draft box"
    assert modes["batch_save"]["status"] == "blocked_unreleased"
    assert modes["batch_save"]["allowed"] is False
    assert modes["batch_save"]["release_scope"] == "not released"
    assert any("claim to draft box proof" in item for item in modes["claim_only"]["required_evidence"])
    assert any("batch size limit" in item for item in modes["batch_save"]["required_evidence"])
    operator_release_text = json.dumps(plan, ensure_ascii=False)
    assert "data_acquisition" not in operator_release_text
    assert "unique acquisition product proof" not in operator_release_text
    assert "已有待认领列表" in operator_release_text
    assert "受控待认领入箱" in operator_release_text
    assert any("rollback" in item for item in modes["batch_save"]["required_controls"])
    assert modes["claim_only"]["blockers"]
    assert any("cannot reuse single_save" in item for item in modes["batch_save"]["blockers"])
    for mode in ("batch_save",):
        checklist = modes[mode]["readiness_checklist"]
        assert checklist
        assert all({"id", "label", "required", "status", "evidence_source", "blocker", "detail"} <= set(item) for item in checklist)
        assert all(item["status"] == "missing" for item in checklist)
        assert any(item["blocker"] == "cannot reuse single_save evidence" for item in checklist)
    claim_checklist = {item["id"]: item for item in modes["claim_only"]["readiness_checklist"]}
    assert claim_checklist["l2_dual_target"]["status"] == "blocked"
    assert claim_checklist["claim_ownership_proof"]["status"] == "blocked"
    assert claim_checklist["no_editor_or_save"]["status"] == "passed"
    assert any(item["id"] == "batch_size_limit" for item in modes["batch_save"]["readiness_checklist"])


def test_delivery_workspace_delivery_scope_releases_claim_and_single_save_only(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    plan = data["real_mode_release_plan"]
    modes = {item["mode"]: item for item in plan["modes"]}
    assert plan["scope"] == "controlled_claim_and_single_save"
    assert plan["publish_allowed"] is False
    assert plan["batch_unattended_publish_allowed"] is False
    assert modes["single_save"]["allowed"] is True
    assert modes["single_save"]["status"] == "released_controlled"
    assert modes["single_save"]["release_scope"] == "single product save-only canary"
    assert modes["claim_only"]["allowed"] is True
    assert modes["claim_only"]["status"] == "released_controlled"
    assert modes["batch_save"]["allowed"] is False
    assert modes["batch_save"]["status"] == "blocked_unreleased"
    assert data["publish_guard_state"]["publish_allowed"] is False


def test_delivery_workspace_releases_single_save_start_after_l2_even_before_save_evidence(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="待保存商品",
    )
    task = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang - 1 件商品",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI-OPS",
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
        }
    )

    response = client.get(f"/api/delivery/workspace?task_id={task['id']}")

    assert response.status_code == 200
    data = response.json()
    modes = {item["mode"]: item for item in data["real_mode_release_plan"]["modes"]}
    assert data["delivery_readiness"]["ready"] is False
    assert data["regression_gates"][2]["status"] == "passed"
    assert data["regression_gates"][3]["status"] == "approval_required"
    assert modes["single_save"]["allowed"] is True
    assert modes["single_save"]["status"] == "released_controlled"
    assert modes["single_save"]["blockers"] == []
    assert modes["claim_only"]["allowed"] is True
    assert modes["batch_save"]["allowed"] is False


def test_delivery_workspace_exposes_canonical_l2_probe_plan(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    plan = response.json()["l2_probe_plan"]
    assert plan["schema"] == "dxm_l2_readonly_probe_plan.v1"
    assert plan["requiresApproval"] is True
    assert "已有待认领列表" in plan["purpose"]
    assert "不认领、不备注、不保存、不发布" in plan["purpose"]
    assert plan["runIdCommand"].startswith('$runId = "l2-real-"')
    assert plan["outputDir"] == r"data\l2_readonly_probe"
    assert plan["cookieFile"] == r"data\sessions\dianxiaomi_cookies.json"
    assert plan["desktopCookieFile"] == r"%APPDATA%\DXM Agent Console\data\sessions\dianxiaomi_cookies.json"
    assert "DXM Agent Console\\data\\sessions\\dianxiaomi_cookies.json" in plan["commands"][1]
    assert plan["cookieFileCommand"] == plan["commands"][2]
    assert [target["id"] for target in plan["targets"]] == ["data_acquisition", "draft_box"]
    assert any("--target data_acquisition" in command and "--run-id $runId" in command for command in plan["commands"])
    assert any("--target draft_box" in command and "--run-id $runId" in command for command in plan["commands"])
    assert all("--headed" in command for command in plan["commands"][3:])
    assert all("--cookie-file $cookieFile" in command for command in plan["commands"][3:])
    assert all("--output-dir data\\l2_readonly_probe" in command for command in plan["commands"][3:])
    assert any("同一 run-id" in item for item in plan["acceptanceCriteria"])
    assert not any("数据采集" in item or "采集页" in item for item in [plan["purpose"], *plan["safetyNotes"]])
    assert any("不自动放行真实保存" in item for item in plan["safetyNotes"])


def test_delivery_workspace_reads_l2_probe_from_runtime_data_dir(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    runtime_l2_dir = tmp_path / "runtime_data" / "l2_readonly_probe"
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", runtime_l2_dir, raising=False)
    created_at = _fresh_l2_created_at()
    _write_l2_probe_result(
        runtime_l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=created_at,
    )
    _write_l2_probe_result(
        runtime_l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=created_at,
    )

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert data["evidence_grade"]["blocked_by_l2"] is False
    assert data["safety"]["l2Status"] == "passed"


def test_delivery_workspace_exposes_readonly_claim_candidates_from_l2_dom(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    runtime_l2_dir = tmp_path / "runtime_data" / "l2_readonly_probe"
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", runtime_l2_dir, raising=False)
    created_at = _fresh_l2_created_at()
    _write_l2_probe_result(
        runtime_l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=created_at,
        dom_html="""
        <html><body>
          <table>
            <tr class="vxe-body--row">
              <td><a href="https://detail.1688.com/offer/1057073209777.html" target="_blank">1688</a></td>
              <td><div class="no-new-line4" title="鸣潮二周年线下生日会系列周边爱弥斯达妮娅亚克力立牌">标题</div></td>
              <td><span class="vxe-cell--label">18855640392</span></td>
              <td>2026-07-06 08:28</td>
              <td><a href="javascript:">认领</a></td>
            </tr>
            <tr class="vxe-body--row">
              <td><a href="https://example.com/ignored" target="_blank">其它</a></td>
              <td><div class="no-new-line4" title="没有认领按钮的行">标题</div></td>
              <td><a href="javascript:">编辑</a></td>
            </tr>
          </table>
        </body></html>
        """,
    )
    _write_l2_probe_result(
        runtime_l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=created_at,
    )

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    candidates = response.json()["claim_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["title"] == "鸣潮二周年线下生日会系列周边爱弥斯达妮娅亚克力立牌"
    assert candidates[0]["source"] == "1688"
    assert candidates[0]["source_url"] == "https://detail.1688.com/offer/1057073209777.html"
    assert candidates[0]["store_account"] == "18855640392"
    assert candidates[0]["category_hint"] == "立牌类谷子"
    assert candidates[0]["readonly"] is True


def test_delivery_workspace_l2_gate_reports_probe_source_dir(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    runtime_l2_dir = tmp_path / "runtime_data" / "l2_readonly_probe"
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", runtime_l2_dir, raising=False)
    created_at = _fresh_l2_created_at()
    _write_l2_probe_result(
        runtime_l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=created_at,
    )
    _write_l2_probe_result(
        runtime_l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=created_at,
    )

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    l2_gate = next(gate for gate in response.json()["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert l2_gate["latest"]["selectedProbeResultDir"] == str(runtime_l2_dir)
    assert l2_gate["latest"]["probeResultDirs"][0]["path"] == str(runtime_l2_dir)


def test_delivery_workspace_prioritizes_runtime_l2_over_repo_l2(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    runtime_l2_dir = tmp_path / "runtime_data" / "l2_readonly_probe"
    repo_l2_dir = tmp_path / "repo_data" / "l2_readonly_probe"
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", runtime_l2_dir, raising=False)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", repo_l2_dir, raising=False)
    created_at = _fresh_l2_created_at()
    _write_l2_probe_result(
        runtime_l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=created_at,
    )
    _write_l2_probe_result(
        runtime_l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=created_at,
    )
    _write_l2_probe_result(
        repo_l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(60),
        ok=False,
        network={"write_request_count": 1, "non_read_request_count": 1},
    )
    _write_l2_probe_result(
        repo_l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(60),
        ok=False,
        network={"write_request_count": 1, "non_read_request_count": 1},
    )

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    l2_gate = next(gate for gate in response.json()["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert set(l2_gate["latest"]["realTargets"]) == {"data_acquisition", "draft_box"}
    assert all(
        target["json_path"].startswith(str(runtime_l2_dir))
        for target in l2_gate["latest"]["realTargets"].values()
    )


def test_delivery_workspace_evidence_points_are_isolated_to_requested_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    requested = _create_delivery_fixture(repo, with_network=True)
    other = _create_delivery_fixture(repo, with_network=True)

    response = client.get(f"/api/delivery/workspace?task_id={requested['task']['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == requested["task"]["id"]
    assert data["reports"]
    assert all(report["task_id"] == requested["task"]["id"] for report in data["reports"])
    assert all(point["task_id"] == requested["task"]["id"] for point in data["evidence_points"])
    assert other["task"]["id"] not in {point["task_id"] for point in data["evidence_points"]}
    report_ids = {report["id"] for report in data["reports"]}
    for point in data["evidence_points"]:
        if point["kind"] in {"save_result", "published_proof", "network_save_result", "har_summary"}:
            assert point["report_id"] in report_ids


def test_delivery_workspace_without_task_id_uses_latest_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert data["tasks"][0]["id"] == fixture["task"]["id"]
    assert data["publish_guard_state"]["publish_allowed"] is False


def test_delivery_workspace_without_tasks_returns_recoverable_empty_workspace(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"] is None
    assert data["tasks"] == []
    assert data["reports"] == []
    assert data["evidences"] == []
    assert data["delivery_readiness"]["ready"] is False
    assert any(gap["id"] == "empty-workspace" for gap in data["acceptanceGaps"])


def test_delivery_workspace_keeps_marker_and_fixture_words_visible_as_operator_data(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "测试商品 fixture 示例商品但属于真实业务",
            "source": "test",
            "status": "draft",
            "category_name": "QA_CATEGORY",
            "price": 1,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {
                "test_only": True,
                "data_origin": "test_fixture",
            },
        }
    )
    task = _create_legacy_single_save_task(
        repo,
        store,
        product,
        name="单商品只保存 - Dang Kang - 1 件商品",
        claim_mark="AI认领",
        payload={"store_name": store["name"], "category_name": product["category_name"]},
    )

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == task["id"]
    assert [item["id"] for item in repo.list_products()] == [product["id"]]
    assert [item["id"] for item in data["products"]] == [product["id"]]
    assert [item["id"] for item in data["tasks"]] == [task["id"]]
    assert data["delivery_readiness"]["ready"] is False


def test_delivery_workspace_keeps_explicit_test_marker_task_visible_and_blocked(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="ACG Stand Product 1",
        source_url="https://detail.1688.com/offer/test-1.html",
        claim_mark="QA_TWO_STAGE",
        price=1,
        test_only=True,
    )
    task = repo.create_task(
        {
            "name": "QA two-stage claimed product save task",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "QA_TWO_STAGE",
            "payload": {
                "store_name": store["name"],
                "category_name": product["category_name"],
                "product_ids": [product["id"]],
                "claim_mark": "QA_TWO_STAGE",
                "source_url": "https://detail.1688.com/offer/test-1.html",
                "test_only": True,
                "data_origin": "test_fixture",
            },
        }
    )

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["id"] == task["id"]
    assert any(item["id"] == task["id"] for item in data["tasks"])
    assert any(item["id"] == product["id"] for item in data["products"])
    assert data["delivery_readiness"]["ready"] is False


def test_delivery_workspace_missing_requested_task_fails_closed_without_substituting_ready_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get("/api/delivery/workspace?task_id=999999")

    assert response.status_code == 200
    data = response.json()
    assert fixture["task"]["id"] in {task["id"] for task in repo.list_tasks()}
    assert data["current_task"] is None
    assert data["tasks"] == []
    assert data["requested_task_missing"] is True
    assert data["requested_task_id"] == 999999
    assert data["delivery_readiness"]["ready"] is False
    assert data["two_stage_acceptance"]["passed"] is False
    assert data["state_consistency"]["consistent"] is False


def test_delivery_workspace_without_task_id_prefers_task_with_delivery_evidence_over_newer_draft(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    store = repo.create_store("Dang Kang QA", "AliExpress")
    product = repo.create_product(
        {
            "title": "QA unreleased batch save product",
            "source": "qa",
            "category_name": "QA_CATEGORY",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 1,
            "image_count": 1,
            "payload": {"source_title": "QA unreleased batch save product"},
        }
    )
    newer_draft = repo.create_task(
        {
            "name": "QA unreleased batch_save task",
            "store_id": store["id"],
            "mode": "batch_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "QA_BATCH_BLOCK",
            "payload": {"store_name": store["name"], "category_name": product["category_name"]},
        }
    )

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert newer_draft["id"] > fixture["task"]["id"]
    assert data["tasks"][0]["id"] == newer_draft["id"]
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert data["report_summary"]["latest_report"]["task_id"] == fixture["task"]["id"]
    assert data["publish_guard_state"]["status"] == "safe_unpublished"


def test_delivery_workspace_without_task_id_prefers_newer_actionable_single_save_over_completed_evidence(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="Actionable single save product",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/2026000000001.html",
        price=8.01,
    )
    newer_draft = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang - 1 件商品",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "AI认领",
            "payload": {"store_name": store["name"], "category_name": product["category_name"]},
        }
    )

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert newer_draft["id"] > fixture["task"]["id"]
    assert data["current_task"]["id"] == newer_draft["id"]
    assert data["report_summary"]["latest_report"] is None
    assert any(task["id"] == fixture["task"]["id"] for task in data["tasks"])


def test_delivery_workspace_without_task_id_uses_newer_failed_single_save_as_current_truth(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="Failed single save product",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/2026000000002.html",
        price=8.01,
    )
    failed_task = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang - 上次失败",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "AI认领",
            "payload": {"store_name": store["name"], "category_name": product["category_name"]},
        }
    )
    repo.update_task_status(failed_task["id"], "failed", completed_jobs=0, failed_jobs=1)

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert failed_task["id"] > fixture["task"]["id"]
    assert data["tasks"][0]["id"] == failed_task["id"]
    assert data["current_task"]["id"] == failed_task["id"]
    assert data["current_task"]["status"] == "failed"
    assert data["report_summary"]["latest_report"] is None
    assert data["delivery_readiness"]["ready"] is False
    assert data["state_consistency"]["consistent"] is False
    assert failed_task["id"] in data["state_consistency"]["audited_task_ids"]
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert any(task["id"] == fixture["task"]["id"] for task in data["tasks"])

    explicit = client.get(
        f"/api/delivery/workspace?task_id={fixture['task']['id']}"
    ).json()
    assert explicit["current_task"]["id"] == fixture["task"]["id"]
    assert explicit["report_summary"]["latest_report"]["task_id"] == fixture["task"]["id"]
    assert explicit["delivery_readiness"]["ready"] is True
    assert failed_task["id"] not in explicit["state_consistency"]["audited_task_ids"]


def test_delivery_workspace_does_not_hide_real_task_because_business_text_mentions_fixture(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    historical_success = _create_delivery_fixture(repo, with_network=True)
    store = repo.create_store("Dang Kang Real", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="测试商品 fixture 关键词但属于真实业务",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/2026000000999.html",
        price=8.01,
    )
    current_failure = repo.create_task(
        {
            "name": "单商品只保存 - 真实业务最新失败",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "AI认领",
            "payload": {
                "store_name": store["name"],
                "category_name": product["category_name"],
                "test_only": True,
                "data_origin": "test_fixture",
            },
        }
    )
    repo.update_task_status(
        current_failure["id"],
        "failed",
        completed_jobs=0,
        failed_jobs=1,
    )

    data = client.get("/api/delivery/workspace").json()

    assert current_failure["id"] > historical_success["task"]["id"]
    assert data["current_task"]["id"] == current_failure["id"]
    assert data["current_task"]["status"] == "failed"
    assert data["delivery_readiness"]["ready"] is False
    assert any(task["id"] == current_failure["id"] for task in data["tasks"])


@pytest.mark.parametrize(
    "current_status",
    ["partial_success", "cancelled", "needs_manual_review", "draft"],
)
def test_delivery_workspace_without_task_id_uses_latest_single_save_status_as_current_truth(
    tmp_path,
    monkeypatch,
    current_status,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    historical_success = _create_delivery_fixture(repo, with_network=True)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title=f"Current truth product {current_status}",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/2026000000100.html",
        price=8.01,
    )
    current_task = repo.create_task(
        {
            "name": f"单商品只保存 - Dang Kang - {current_status}",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "AI认领",
            "payload": {"store_name": store["name"], "category_name": product["category_name"]},
        }
    )
    if current_status != "draft":
        repo.update_task_status(
            current_task["id"],
            current_status,
            completed_jobs=0,
            failed_jobs=0,
        )

    data = client.get("/api/delivery/workspace").json()

    assert current_task["id"] > historical_success["task"]["id"]
    assert data["current_task"]["id"] == current_task["id"]
    assert data["current_task"]["status"] == current_status
    assert data["report_summary"]["latest_report"] is None
    assert data["delivery_readiness"]["ready"] is False
    assert current_task["id"] in data["state_consistency"]["audited_task_ids"]
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert any(task["id"] == historical_success["task"]["id"] for task in data["tasks"])


def test_delivery_workspace_without_task_id_ignores_older_draft_when_newer_success_evidence_exists(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="Stale draft product",
        category_name="立牌类谷子",
        source_url="https://detail.1688.com/offer/2026000000003.html",
        price=8.01,
    )
    older_draft = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang - 旧草稿",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "claim_mark": "AI认领",
            "payload": {"store_name": store["name"], "category_name": product["category_name"]},
        }
    )
    fixture = _create_delivery_fixture(repo, with_network=True)

    response = client.get("/api/delivery/workspace")

    assert response.status_code == 200
    data = response.json()
    assert older_draft["id"] < fixture["task"]["id"]
    assert data["current_task"]["id"] == fixture["task"]["id"]
    assert data["report_summary"]["latest_report"]["task_id"] == fixture["task"]["id"]


def test_delivery_workspace_exposes_publish_guard_and_dxm_reference_fields(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["published"] is False
    assert data["publish_guard_state"]["publish_allowed"] is False
    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["template_resolution"]["dxm_reference_templates_resolved"]["freight"]["names"] == ["40g普货包裹"]
    assert data["template_resolution"]["dxm_reference_template_results"]["description"]["required"] is False
    assert data["report_summary"]["dxm_reference_fields"]["freight"]["resolved"]["required"] is True


def test_delivery_workspace_grades_b_without_network_or_har_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "B"
    assert data["evidence_grade"]["has_save_result"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is False


def test_delivery_workspace_does_not_treat_generic_ok_as_network_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)
    report = repo.list_reports(fixture["task"]["id"])[0]
    save_result = report["save_result"]
    save_result["network_save_result"] = {"ok": True}
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        save_result,
        report["summary"],
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["has_network_or_har_save_response"] is False
    assert not any(point["kind"] == "network_save_result" for point in data["evidence_points"])


def test_delivery_workspace_accepts_dxm_add_json_code_zero_as_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)
    report = repo.list_reports(fixture["task"]["id"])[0]
    save_result = report["save_result"]
    save_result["network_save_result"] = {
        "ok": True,
        "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
        "method": "POST",
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑保存成功！",
    }
    save_result["network_events"] = [
        {
            "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
            "method": "POST",
            "resource_type": "xhr",
            "status": 200,
            "json": {"code": 0, "msg": "您的产品编辑保存成功！"},
        }
    ]
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        save_result,
        report["summary"],
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["delivery_readiness"]["jobs"][0]["has_network_or_har_save_response"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is True
    assert any(point["kind"] == "network_save_result" for point in data["evidence_points"])


def test_delivery_workspace_accepts_smt_add_json_nested_success_as_save_response(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=False)
    report = repo.list_reports(fixture["task"]["id"])[0]
    save_result = report["save_result"]
    save_result["network_save_result"] = {
        "ok": True,
        "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
        "method": "POST",
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑成功！",
        "raw": {
            "code": 0,
            "msg": "Successful",
            "data": {
                "msg": "您的产品编辑成功！",
                "code": 0,
                "productId": "130658341327045576",
            },
        },
    }
    save_result["network_events"] = [
        {
            "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
            "method": "POST",
            "resource_type": "xhr",
            "status": 200,
            "json": {
                "code": 0,
                "msg": "Successful",
                "data": {
                    "msg": "您的产品编辑成功！",
                    "code": 0,
                    "productId": "130658341327045576",
                },
            },
        }
    ]
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        save_result,
        report["summary"],
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["delivery_readiness"]["jobs"][0]["has_network_or_har_save_response"] is True
    assert data["evidence_grade"]["has_network_or_har_save_response"] is True
    assert any(
        point["kind"] == "network_save_result"
        and point["network_save_result"]["url"].endswith("/api/smtProduct/add.json")
        for point in data["evidence_points"]
    )


def test_delivery_workspace_marks_acceptance_blocked_when_l2_not_passed(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["blocked_by_l2"] is True
    assert data["safety"]["evidenceGrade"] == "C"
    l2_gap = next(gap for gap in data["acceptanceGaps"] if gap["id"] == "gap-l2-real-probe")
    assert l2_gap["severity"] == "blocker"
    assert "L2" in l2_gap["detail"]


def test_delivery_workspace_marks_batch_incomplete_when_any_job_lacks_delivery_evidence(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture_with_missing_second_job(repo)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["delivery_readiness"]["complete_job_count"] == 1
    assert data["delivery_readiness"]["total_job_count"] == 2
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert l3_gate["evidenceLevel"] == "C"
    assert "Job" in l3_gate["detail"]
    job_gap = next(gap for gap in data["acceptanceGaps"] if gap["id"].startswith("gap-job-"))
    assert job_gap["severity"] == "blocker"
    assert "缺少" in job_gap["detail"]


def test_delivery_workspace_two_stage_acceptance_requires_acquisition_claim_chain(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    product = repo.create_product(
        {
            "title": "真实待认领商品未关联认领任务",
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
    task = _create_legacy_single_save_task(
        repo,
        store,
        product,
        name="单商品只保存 - Dang Kang - 1 件商品",
        payload={"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    )
    job = repo.get_task(task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
        "network_save_result": {
            "ok": True,
            "method": "POST",
            "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
            "status": 200,
            "code": 0,
            "msg": "您的产品编辑保存成功！",
        },
    }
    summary = {
        "status": "success",
        "workflow_results": [
            {"action": "save_only", "ok": True, "save_result": save_result},
            {"action": "verify_not_published", "ok": True, "published": False},
        ],
        "published": False,
    }
    repo.add_report(task["id"], job["id"], product["id"], "success", False, save_result, summary)
    repo.update_job(job["id"], status="succeeded")
    repo.update_task_status(task["id"], "completed", completed_jobs=1, failed_jobs=0)

    data = client.get(f"/api/delivery/workspace?task_id={task['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["passed"] is False
    assert acceptance["status"] == "missing_claim_stage"
    assert "claim_task_id" in acceptance["missing_codes"]
    assert "待认领商品" in acceptance["user_message"] or "已有待认领" in acceptance["user_message"]
    assert "商品箱" in acceptance["user_message"]


def test_delivery_workspace_two_stage_acceptance_rejects_completed_non_claim_task(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    fake_claim_task = repo.create_task(
        {
            "name": "伪造认领完成任务",
            "store_id": store["id"],
            "mode": "dry_run",
            "publish_scene": "DRY_RUN",
            "claim_mark": "AI-OPS",
            "product_ids": [],
            "payload": {
                "stage": "claimed_to_draft",
                "status": "completed",
                "draft_box_verified": True,
            },
        }
    )
    product = repo.create_product(
        {
            "title": "真实待认领商品但认领任务类型不正确",
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
                "claim_task_id": fake_claim_task["id"],
                "draft_box_verified": True,
            },
        }
    )
    with db.connection() as conn:
        payload = dict(fake_claim_task["payload"])
        payload.update(
            {
                "stage": "claimed_to_draft",
                "status": "completed",
                "claimed_product_id": product["id"],
                "draft_box_verified": True,
            }
        )
        conn.execute(
            "UPDATE tasks SET status='completed', completed_jobs=0, failed_jobs=0, payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), fake_claim_task["id"]),
        )
    save_task = _create_legacy_single_save_task(
        repo,
        store,
        product,
        name="单商品只保存 - Dang Kang - 1 件商品",
        payload={"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    )
    job = repo.get_task(save_task["id"])["jobs"][0]
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "success_text": "编辑成功",
        "published": False,
        "network_save_result": {
            "ok": True,
            "method": "POST",
            "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
            "status": 200,
            "code": 0,
            "msg": "您的产品编辑保存成功！",
        },
    }
    summary = {
        "status": "success",
        "workflow_results": [
            {"action": "save_only", "ok": True, "save_result": save_result},
            {"action": "verify_not_published", "ok": True, "published": False},
        ],
        "published": False,
    }
    repo.add_report(save_task["id"], job["id"], product["id"], "success", False, save_result, summary)
    repo.update_job(job["id"], status="succeeded")
    repo.update_task_status(save_task["id"], "completed", completed_jobs=1, failed_jobs=0)

    data = client.get(f"/api/delivery/workspace?task_id={save_task['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["passed"] is False
    assert acceptance["status"] == "missing_claim_stage"
    assert "claim_completed" in acceptance["missing_codes"]
    assert acceptance["checks"]["claim_task_present"] is True
    assert acceptance["checks"]["claim_completed"] is False


def test_delivery_workspace_two_stage_acceptance_passes_when_claim_and_save_share_product(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['save_task']['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["passed"] is True
    assert acceptance["status"] == "passed"
    assert acceptance["claim_task_id"] == fixture["claim_task"]["id"]
    assert acceptance["save_task_id"] == fixture["save_task"]["id"]
    assert acceptance["claimed_product_id"] == fixture["product"]["id"]
    assert acceptance["checks"]["claim_completed"] is True
    assert acceptance["checks"]["draft_box_verified"] is True
    assert acceptance["checks"]["single_save_linked_to_claim"] is True
    assert acceptance["checks"]["save_success"] is True
    assert acceptance["checks"]["unpublished_proof"] is True
    assert acceptance["checks"]["publish_guard_safe"] is True
    assert acceptance["missing_codes"] == []
    assert "两段式" in acceptance["user_message"]


def test_delivery_workspace_blocks_all_ready_surfaces_for_bare_l3_evidence_paths(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(
        repo,
        l3_evidence_descriptors=False,
    )

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["two_stage_acceptance"]["passed"] is False
    assert "save_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]
    assert "unpublished_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]
    l3_gate = next(
        gate for gate in data["regression_gates"] if gate["level"] == "L3"
    )
    assert l3_gate["status"] == "blocked"


def _replace_persisted_action_evidence_ref(
    repo: Repository,
    task_id: int,
    action: str,
    evidence_ref: dict,
) -> None:
    evidence = next(
        item
        for item in repo.list_evidences(task_id)
        if (item.get("meta") or {}).get("action") == action
    )
    meta = dict(evidence["meta"])
    meta["evidence_ref"] = evidence_ref
    with db.connection() as conn:
        conn.execute(
            "UPDATE job_evidences SET file_path=?, meta_json=? WHERE id=?",
            (
                evidence_ref["path"],
                json.dumps(meta, ensure_ascii=False),
                evidence["id"],
            ),
        )


def test_delivery_workspace_rejects_l3_evidence_outside_screenshot_directory(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    task_id = fixture["save_task"]["id"]
    assert client.get(
        f"/api/delivery/workspace?task_id={task_id}"
    ).json()["two_stage_acceptance"]["passed"] is True

    code_path = Path(delivery_workspace.__file__).resolve()
    code_content = code_path.read_bytes()
    forged_ref = {
        "path": str(code_path),
        "sha256": hashlib.sha256(code_content).hexdigest().upper(),
        "size": len(code_content),
    }
    _replace_persisted_action_evidence_ref(repo, task_id, "save_only", forged_ref)

    data = client.get(f"/api/delivery/workspace?task_id={task_id}").json()

    assert data["two_stage_acceptance"]["passed"] is False
    assert "save_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]


@pytest.mark.parametrize("outside_kind", ["traversal", "prefix_collision"])
def test_delivery_workspace_rejects_screenshot_root_escape_paths(
    tmp_path,
    monkeypatch,
    outside_kind,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    task_id = fixture["save_task"]["id"]
    if outside_kind == "traversal":
        outside_path = config.SCREENSHOT_DIR.parent / f"traversal-{task_id}.png"
        descriptor_path = config.SCREENSHOT_DIR / ".." / outside_path.name
    else:
        outside_dir = config.SCREENSHOT_DIR.with_name(
            f"{config.SCREENSHOT_DIR.name}-forged"
        )
        outside_dir.mkdir(parents=True, exist_ok=True)
        outside_path = outside_dir / f"prefix-collision-{task_id}.png"
        descriptor_path = outside_path
    outside_path.write_bytes(_MINIMAL_VALID_PNG)
    forged_ref = {
        "path": str(descriptor_path),
        "sha256": hashlib.sha256(_MINIMAL_VALID_PNG).hexdigest().upper(),
        "size": len(_MINIMAL_VALID_PNG),
    }
    _replace_persisted_action_evidence_ref(repo, task_id, "save_only", forged_ref)

    data = client.get(f"/api/delivery/workspace?task_id={task_id}").json()

    assert data["two_stage_acceptance"]["passed"] is False
    assert "save_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]


def test_delivery_workspace_requires_png_extension_for_l3_evidence(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    task_id = fixture["save_task"]["id"]
    forged_ref = _evidence_ref(f"forged-save-{task_id}.txt")
    _replace_persisted_action_evidence_ref(repo, task_id, "save_only", forged_ref)

    data = client.get(f"/api/delivery/workspace?task_id={task_id}").json()

    assert data["two_stage_acceptance"]["passed"] is False
    assert "save_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]


def test_delivery_workspace_requires_png_signature_for_l3_evidence(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    task_id = fixture["save_task"]["id"]
    forged_ref = _evidence_ref(
        f"forged-unpublished-{task_id}.png",
        content=b"not-a-png-screenshot",
    )
    _replace_persisted_action_evidence_ref(
        repo,
        task_id,
        "verify_not_published",
        forged_ref,
    )

    data = client.get(f"/api/delivery/workspace?task_id={task_id}").json()

    assert data["two_stage_acceptance"]["passed"] is False
    assert "unpublished_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]


def test_delivery_workspace_rechecks_l3_evidence_file_existence_before_ready(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    save_evidence = next(
        evidence
        for evidence in repo.list_evidences(fixture["save_task"]["id"])
        if (evidence.get("meta") or {}).get("action") == "save_only"
    )
    Path(save_evidence["meta"]["evidence_ref"]["path"]).unlink()

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["two_stage_acceptance"]["passed"] is False
    assert "save_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]
    l3_gate = next(
        gate for gate in data["regression_gates"] if gate["level"] == "L3"
    )
    assert l3_gate["status"] == "blocked"


def test_delivery_workspace_rehashes_l3_evidence_before_ready(
    tmp_path,
    monkeypatch,
):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    unpublished_evidence = next(
        evidence
        for evidence in repo.list_evidences(fixture["save_task"]["id"])
        if (evidence.get("meta") or {}).get("action") == "verify_not_published"
    )
    evidence_ref = unpublished_evidence["meta"]["evidence_ref"]
    Path(evidence_ref["path"]).write_bytes(b"x" * evidence_ref["size"])

    data = client.get(
        f"/api/delivery/workspace?task_id={fixture['save_task']['id']}"
    ).json()

    assert data["delivery_readiness"]["ready"] is False
    assert data["two_stage_acceptance"]["passed"] is False
    assert "unpublished_evidence_integrity" in data["two_stage_acceptance"]["missing_codes"]
    l3_gate = next(
        gate for gate in data["regression_gates"] if gate["level"] == "L3"
    )
    assert l3_gate["status"] == "blocked"


def _ready_two_stage_workspace(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_two_stage_delivery_fixture(repo)
    return client, repo, fixture


def _replace_task_payload(task_id: int, payload: dict) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), task_id),
        )


def _replace_product_payload(product_id: int, payload: dict) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), product_id),
        )


def _assert_two_stage_provenance_blocks_ready(data: dict, missing_code: str) -> None:
    acceptance = data["two_stage_acceptance"]
    assert acceptance["passed"] is False
    assert acceptance["status"] == "invalid_claim_provenance"
    assert missing_code in acceptance["missing_codes"]
    assert data["delivery_readiness"]["ready"] is False
    assert data["delivery_readiness"]["blocked_by_two_stage_acceptance"] is True
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "blocked"
    assert "两段式" in l3_gate["detail"]


def test_delivery_workspace_blocks_ready_when_save_task_stage_a_snapshot_drifts(tmp_path, monkeypatch):
    client, repo, fixture = _ready_two_stage_workspace(tmp_path, monkeypatch)
    save_task = repo.get_task_private(fixture["save_task"]["id"])
    tampered_payload = dict(save_task["payload"])
    tampered_stage_a = dict(tampered_payload["stage_a_task_facts"])
    tampered_stage_a["task_id"] = int(tampered_stage_a["task_id"]) + 10_000
    tampered_payload["stage_a_task_facts"] = tampered_stage_a
    _replace_task_payload(save_task["id"], tampered_payload)

    data = client.get(f"/api/delivery/workspace?task_id={save_task['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["checks"]["claim_provenance_valid"] is True
    assert acceptance["checks"]["single_save_claim_snapshot_valid"] is False
    _assert_two_stage_provenance_blocks_ready(data, "single_save_claim_snapshot")


def test_delivery_workspace_blocks_ready_when_save_task_draft_box_proof_fingerprint_drifts(tmp_path, monkeypatch):
    client, repo, fixture = _ready_two_stage_workspace(tmp_path, monkeypatch)
    save_task = repo.get_task_private(fixture["save_task"]["id"])
    tampered_payload = dict(save_task["payload"])
    tampered_payload["draft_box_proof_fingerprint"] = "0" * 64
    _replace_task_payload(save_task["id"], tampered_payload)

    data = client.get(f"/api/delivery/workspace?task_id={save_task['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["checks"]["claim_provenance_valid"] is True
    assert acceptance["checks"]["single_save_claim_snapshot_valid"] is False
    _assert_two_stage_provenance_blocks_ready(data, "single_save_claim_snapshot")


def test_delivery_workspace_blocks_ready_when_claimed_product_source_identity_drifts(tmp_path, monkeypatch):
    client, repo, fixture = _ready_two_stage_workspace(tmp_path, monkeypatch)
    product = repo.get_product(fixture["product"]["id"])
    tampered_payload = dict(product["payload"])
    tampered_payload["source_identity"] = {
        "primary_url": "https://example.invalid/tampered-source",
        "urls": ["https://example.invalid/tampered-source"],
    }
    _replace_product_payload(product["id"], tampered_payload)

    save_task_id = fixture["save_task"]["id"]
    data = client.get(f"/api/delivery/workspace?task_id={save_task_id}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["checks"]["claim_provenance_valid"] is False
    assert acceptance["checks"]["single_save_claim_snapshot_valid"] is False
    _assert_two_stage_provenance_blocks_ready(data, "claim_provenance")


def test_delivery_workspace_rehashes_draft_box_evidence_before_ready(tmp_path, monkeypatch):
    client, repo, fixture = _ready_two_stage_workspace(tmp_path, monkeypatch)
    product = repo.get_product(fixture["product"]["id"])
    evidence_ref = product["payload"]["draft_box_proof"]["proof_content"]["evidence_ref"]
    Path(evidence_ref["path"]).write_bytes(b"tampered-after-proof")

    save_task_id = fixture["save_task"]["id"]
    data = client.get(f"/api/delivery/workspace?task_id={save_task_id}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["checks"]["claim_provenance_valid"] is False
    assert acceptance["checks"]["single_save_claim_snapshot_valid"] is False
    _assert_two_stage_provenance_blocks_ready(data, "claim_provenance")


def test_delivery_workspace_blocks_ready_when_save_task_store_snapshot_drifts(tmp_path, monkeypatch):
    client, repo, fixture = _ready_two_stage_workspace(tmp_path, monkeypatch)
    save_task = repo.get_task_private(fixture["save_task"]["id"])
    tampered_payload = dict(save_task["payload"])
    tampered_payload["store_id"] = int(tampered_payload["store_id"]) + 10_000
    _replace_task_payload(save_task["id"], tampered_payload)

    data = client.get(f"/api/delivery/workspace?task_id={save_task['id']}").json()

    acceptance = data["two_stage_acceptance"]
    assert acceptance["checks"]["claim_provenance_valid"] is True
    assert acceptance["checks"]["single_save_claim_snapshot_valid"] is False
    _assert_two_stage_provenance_blocks_ready(data, "single_save_claim_snapshot")


def test_delivery_workspace_blocks_publish_network_signal(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, with_publish_network=True)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "blocked_published_signal"
    assert data["publish_guard_state"]["safe"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["has_publish_risk"] is True


def test_delivery_workspace_ignores_ambient_publish_buttons_in_body_excerpt(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    report = repo.list_reports(fixture["task"]["id"])[0]
    summary = report["summary"]
    summary["workflow_results"] = [
        {
            "action": "save_only",
            "fill_result": {
                "body_excerpt": "保存并移入待发布 保存 立即发布",
            },
        }
    ]
    repo.add_report(
        fixture["task"]["id"],
        fixture["job"]["id"],
        report["product_id"],
        "success",
        False,
        report["save_result"],
        summary,
    )

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["evidence_grade"]["has_publish_risk"] is False


def test_delivery_workspace_report_published_false_is_not_unpublished_proof_without_verify(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "waiting_for_unpublished_proof"
    assert data["publish_guard_state"]["safe"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["has_published_proof"] is False


def test_delivery_workspace_parses_published_string_false_as_unpublished(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, published_value="false")

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["publish_guard_state"]["safe"] is True
    assert data["evidence_grade"]["grade"] == "C"
    assert data["evidence_grade"]["raw_evidence_grade"] == "A"


def test_delivery_workspace_parses_published_string_true_as_blocked(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True, published_value="true")

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    assert data["publish_guard_state"]["status"] == "blocked_published_signal"
    assert data["publish_guard_state"]["published"] is True
    assert data["evidence_grade"]["grade"] == "C"


def test_delivery_workspace_does_not_change_db_schema(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    fixture = _create_delivery_fixture(repo, with_network=True)
    before = _table_signature()

    response = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}")

    assert response.status_code == 200
    assert _table_signature() == before


def test_delivery_workspace_exposes_latest_l2_probe_evidence(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    l2_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="file:///tmp/mock.html",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "mock_passed"
    assert l2_gate["evidenceLevel"] == "B"
    assert l2_gate["latest"]["mockTargets"]["data_acquisition"]["json_path"] == str(l2_json)
    assert l2_gate["latest"]["mockTargets"]["data_acquisition"]["network"]["write_request_count"] == 0


def test_delivery_workspace_l2_fails_when_latest_real_targets_fail(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    failed_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        final_url="https://www.dianxiaomi.com/web/home?redirected=1",
        ok=False,
        network={"write_request_count": 1, "non_read_request_count": 1, "blocked_request_count": 21},
    )
    failed_payload = json.loads(failed_json.read_text(encoding="utf-8"))
    failed_payload["diagnostics"] = {
        "navigation": {
            "requested_target_path": "/web/productCrawl/dataAcquisition",
            "final_path": "/web/home",
            "left_target_path": True,
            "final_path_class": "home",
        },
        "blocked_request_groups": [
            {
                "count": 21,
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/userInfo.json",
                "resource_type": "xhr",
                "reasons": ["active_or_unknown_resource_type:xhr"],
                "keyword_hits": [],
            }
        ],
    }
    failed_json.write_text(json.dumps(failed_payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        ok=False,
        created_at=_fresh_l2_created_at(-30),
        network={"blocked_request_count": 25, "forbidden_keyword_request_count": 5},
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["evidenceLevel"] == "C"
    assert set(l2_gate["latest"]["failedTargets"]) == {"data_acquisition", "draft_box"}
    assert l2_gate["latest"]["realTargets"]["data_acquisition"]["network"]["write_request_count"] == 1
    diagnostics = l2_gate["latest"]["realTargets"]["data_acquisition"]["diagnostics"]
    assert diagnostics["navigation"]["left_target_path"] is True
    assert diagnostics["blocked_request_groups"][0]["path"] == "/api/userInfo.json"
    assert diagnostics["allowlist_review_candidates"] == [
        {
            "count": 21,
            "method": "GET",
            "host": "www.dianxiaomi.com",
            "path": "/api/userInfo.json",
            "resource_type": "xhr",
            "reasons": ["active_or_unknown_resource_type:xhr"],
            "keyword_hits": [],
            "review_only": True,
            "allowlist_applied": False,
        }
    ]


def test_delivery_workspace_l2_passes_only_when_both_real_targets_are_clean(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert l2_gate["evidenceLevel"] == "A"
    assert set(l2_gate["latest"]["targets"]) == {"data_acquisition", "draft_box"}
    assert l2_gate["latest"]["missingTargets"] == []


def test_delivery_workspace_l2_uses_latest_complete_bound_probe_run(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-120),
        run_id="run-complete",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-90),
        run_id="run-complete",
    )
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-10),
        run_id="run-partial",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "passed"
    assert l2_gate["latest"]["runBinding"]["runIds"] == ["run-complete"]
    assert l2_gate["latest"]["realTargets"]["data_acquisition"]["run_id"] == "run-complete"


def test_delivery_workspace_l2_rejects_missing_or_mismatched_evidence_files(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    bad_json = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    payload = json.loads(bad_json.read_text(encoding="utf-8"))
    payload["screenshot_sha256"] = "0" * 64
    bad_json.write_text(json.dumps(payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l3_waits_for_approval_before_evidence_exists(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    store = repo.create_store("Dang Kang", "AliExpress")
    product, _claim_task = _create_verified_claimed_product(
        repo,
        store,
        product_title="Draft Product",
        price=7.01,
    )
    task = repo.create_task(
        {
            "name": "未启动真实保存任务",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": [product["id"]],
            "payload": {"store_name": "Dang Kang"},
        }
    )

    data = client.get(f"/api/delivery/workspace?task_id={task['id']}").json()

    assert data["delivery_readiness"]["has_l3_evidence"] is False
    assert data["evidence_grade"]["blocked_by_job_readiness"] is False
    l3_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L3")
    assert l3_gate["status"] == "approval_required"


def test_delivery_workspace_l2_rejects_clean_targets_from_different_probe_windows(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        created_at=_fresh_l2_created_at(-7200),
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["evidenceLevel"] == "C"
    assert "时效要求" in l2_gate["detail"]
    assert l2_gate["latest"]["timeWindow"]["ok"] is False


def test_delivery_workspace_l2_rejects_clean_real_targets_from_different_probe_runs(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        run_id="run-a",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
        run_id="run-b",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert "同轮次" in l2_gate["detail"]
    assert l2_gate["latest"]["runBinding"]["ok"] is False
    assert l2_gate["latest"]["runBinding"]["runIds"] == ["run-a", "run-b"]


def test_delivery_workspace_l2_rejects_clean_real_targets_without_probe_run_metadata(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        run_id=None,
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
        run_id=None,
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert "同轮次" in l2_gate["detail"]
    assert l2_gate["latest"]["runBinding"]["ok"] is False
    assert set(l2_gate["latest"]["runBinding"]["missing"]) == {
        "data_acquisition.run_id",
        "draft_box.run_id",
    }


def test_delivery_workspace_l2_rejects_success_without_safety_login_or_target_path(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    unsafe = _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/home",
    )
    payload = json.loads(unsafe.read_text(encoding="utf-8"))
    payload.pop("login_state")
    unsafe.write_text(json.dumps(payload), encoding="utf-8")
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l2_rejects_success_when_final_url_leaves_target_path(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        final_url="https://www.dianxiaomi.com/web/home?redirected=1",
    )
    _write_l2_probe_result(
        l2_dir,
        "draft_box",
        target_url="https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        created_at=_fresh_l2_created_at(-30),
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "failed"
    assert l2_gate["latest"]["failedTargets"] == ["data_acquisition"]


def test_delivery_workspace_l2_partial_when_only_one_real_target_is_clean(tmp_path, monkeypatch):
    l2_dir = tmp_path / "l2_readonly_probe"
    _write_l2_probe_result(
        l2_dir,
        "data_acquisition",
        target_url="https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l2_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L2")
    assert l2_gate["status"] == "partial"
    assert l2_gate["evidenceLevel"] == "C"
    assert l2_gate["latest"]["missingTargets"] == ["draft_box"]


def test_delivery_workspace_exposes_latest_l1_replay_evidence(tmp_path, monkeypatch):
    l1_dir = tmp_path / "l1_selector_replay"
    l1_dir.mkdir()
    l1_json = l1_dir / "l1_selector_replay_20260522T010203Z.json"
    l1_json.write_text(
        """
        {
          "schema": "dxm_l1_selector_replay.v1",
          "ok": true,
          "created_at": "2026-05-22T01:02:03+00:00",
          "markdown_path": "data/l1_selector_replay/replay.md",
          "manifest_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "case_count": 3,
          "passed_count": 3,
          "failed_count": 0,
          "cases": [
            {"id": "draft", "page_key": "smt_draft_list", "ok": true, "failures": []}
          ]
        }
        """,
        encoding="utf-8",
    )
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "L1_REPLAY_DIR", l1_dir)
    fixture = _create_delivery_fixture(repo, with_network=False, with_verify_proof=False)

    data = client.get(f"/api/delivery/workspace?task_id={fixture['task']['id']}").json()

    l1_gate = next(gate for gate in data["regression_gates"] if gate["level"] == "L1")
    assert l1_gate["status"] == "passed"
    assert l1_gate["evidenceLevel"] == "B"
    assert l1_gate["latest"]["json_path"] == str(l1_json)
    assert l1_gate["latest"]["passed_count"] == 3
