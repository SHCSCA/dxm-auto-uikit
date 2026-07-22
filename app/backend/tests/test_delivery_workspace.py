from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import db, repository as repository_module
from src.core import config
from src.execution.action_result_contract import (
    validate_independent_save_verification_pair,
)
from src.repository import Repository
from src.services import delivery_workspace
from src.services.state_consistency import audit_state_consistency


_MINIMAL_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_SEMI_MANAGED_URL = "https://www.dianxiaomi.com/web/smt/editFromSmt"
_SAVE_URL = "https://www.dianxiaomi.com/api/popChoiceProduct/add.json"


def _canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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


def _immutable_action_ref(ref: dict, *, kind: str, captured_at: str) -> dict:
    return {
        **ref,
        "kind": kind,
        "captured_at": captured_at,
    }


def _repo(tmp_path, monkeypatch) -> Repository:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "delivery-workspace.db")
    screenshot_dir = tmp_path / "screenshots"
    monkeypatch.setattr(config, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(delivery_workspace, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", screenshot_dir)
    db.init_db()
    return Repository()


def _passed_l2_gate() -> dict:
    return {
        "status": "passed",
        "evidenceLevel": "A",
        "detail": "fresh product-box readonly proof passed",
        "latest": {
            "requiredTargets": ["draft_box"],
            "targets": {"draft_box": {"ok": True}},
            "missingTargets": [],
        },
    }


def _write_l2_probe_result(
    directory,
    *,
    created_at: str | None = None,
    final_url: str | None = None,
    run_id: str = "run-20260722T080000Z",
    script_sha256: str = "A" * 64,
    git_head: str = "B" * 40,
    cookie_file_sha256: str = "C" * 64,
    network: dict | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    target_url = "https://www.dianxiaomi.com/web/smt/smtProductList/draft"
    screenshot_path = directory / "draft_box.png"
    dom_path = directory / "draft_box.html"
    screenshot_path.write_bytes(b"draft box screenshot")
    dom_path.write_text("<html><body>draft box</body></html>", encoding="utf-8")
    network_payload = {
        "request_count": 1,
        "write_request_count": 0,
        "non_read_request_count": 0,
        "blocked_request_count": 0,
        "forbidden_keyword_request_count": 0,
        "websocket_count": 0,
    }
    network_payload.update(network or {})
    payload = {
        "schema": "dxm_l2_readonly_probe.v1",
        "ok": True,
        "target": "draft_box",
        "target_url": target_url,
        "final_url": final_url or target_url,
        "created_at": created_at,
        "run_id": run_id,
        "script_sha256": script_sha256,
        "git_head": git_head,
        "cookie_file_sha256": cookie_file_sha256,
        "evidence_binding": {
            "schema": "dxm_l2_evidence_binding.v1",
            "run_id": run_id,
            "target_set": ["draft_box"],
            "session_fingerprint_sha256": cookie_file_sha256,
            "script_path": "tools/probes/l2_readonly_probe.py",
            "script_sha256": script_sha256,
            "git_head": git_head,
            "git_dirty": False,
            "git_diff_sha256": None,
        },
        "markdown_path": str(directory / "draft_box.md"),
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
            "ok": True,
            "mode": "L2_READ_ONLY",
            "reasons": [],
        },
    }
    path = directory / "draft_box.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _create_product_box_task(repo: Repository) -> dict:
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    product_box_ref = _evidence_ref("product-box.png")
    product = repo.create_product(
        {
            "title": "ACG Stand Product",
            "source": "dxm_draft_box",
            "status": "ready_for_edit",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 8,
            "image_count": 8,
            "payload": {
                "source": "dxm_draft_box",
                "store_id": store["id"],
                "store_name": store["name"],
                "source_url": source_url,
                "source_urls": [source_url],
                "draft_box_verified": True,
                "product_box_observed_at": "2026-07-22T08:00:00+00:00",
                "product_box_evidence_ref": product_box_ref,
            },
        }
    )
    task = repo.create_task(
        {
            "name": "单商品只保存 - Dang Kang",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product["id"]],
            "payload": {
                "store_name": store["name"],
                "category_name": product["category_name"],
            },
        }
    )
    task = repo.get_task_private(task["id"])
    return {
        "store": store,
        "product": product,
        "task": task,
        "job": task["jobs"][0],
    }


def _mark_manual_approval_consumed(repo: Repository, task_id: int) -> None:
    task = repo.get_task_private(task_id)
    payload = dict(task["payload"])
    payload["manual_approval"] = {
        "approved": True,
        "approved_by": "ops-owner",
        "approved_at": "2026-07-22T08:00:00+00:00",
        "source": "server",
        "confirmation": "CONFIRM_DXM_SAVE_ONLY",
        "consumed": True,
        "consumed_at": "2026-07-22T08:00:01+00:00",
        "token_hash": "A" * 64,
    }
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task_id),
        )


def _strict_save_result(*, target_identity: dict, store_name: str) -> dict:
    target_digest = _canonical_sha256(target_identity)
    integrity = {
        "ok": True,
        "kind": "structured_nonempty_form_state",
        "field_count": 12,
        "nonempty_field_count": 12,
        "sha256": "C" * 64,
    }
    authorization = {
        "ok": True,
        "executed": True,
        "mutation_action": "save_only_click",
        "mutation_status": "DISPATCHED",
        "mutation_id": "mutation-1",
    }
    pre_dispatch = {
        "ok": True,
        "required_readback_complete": True,
        "write_attempted": False,
        "phase": "before_ledger_begin_dispatch",
        "exact_save_target": {
            "ok": True,
            "text": "保存",
            "exact_save_count": 1,
        },
        "identity": {
            "ok": True,
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
            "target_identity": target_identity,
            "target_identity_sha256": target_digest,
            "expected_store_name": store_name,
        },
        "baseline_field_integrity": integrity,
        "current_field_integrity": dict(integrity),
    }
    network = {
        "ok": True,
        "receipt_complete": True,
        "receipt_count": 1,
        "method": "POST",
        "url": _SAVE_URL,
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑保存成功！",
    }
    network_audit = {
        "scope": "same_origin_write_window",
        "complete": True,
        "window_closed": True,
        "registered_listener_count": 2,
        "removed_listener_count": 2,
        "mutation_request_count": 1,
        "save_request_count": 1,
        "other_mutation_request_count": 0,
        "publish_request_count": 0,
    }
    publish_signal = {
        "detected": False,
        "kind": "network_route_classification",
        "request_count": 0,
    }
    page_save_result = {
        "ok": True,
        "success_text": "保存成功",
        "status_transition": {
            "kind": "new_or_changed_structured_save_status",
            "entry": {"text": "保存成功", "kind": "toast"},
        },
    }
    return {
        "ok": True,
        "published": False,
        "exact_save_target": True,
        "save_click_dispatched": True,
        "clicked": True,
        "publish_action_clicked": False,
        "text": "保存",
        "exact_save_count": 1,
        "click_method": "native_exact_save",
        "network_save_success": True,
        "page_save_success": True,
        "mutation_authorization": authorization,
        "pre_dispatch_readback": pre_dispatch,
        "network_save_result": network,
        "network_audit": network_audit,
        "publish_signal": publish_signal,
        "page_save_result": page_save_result,
        "save_decision": {
            "ok": True,
            "rule": "page_success_and_network_success",
            "page_ok": True,
            "network_ok": True,
            "network_receipt_ok": True,
            "network_audit_ok": True,
        },
    }


def _unpublished_proof(*, target_digest: str) -> dict:
    return {
        "ok": True,
        "published": False,
        "proof_kind": "structured_unpublished_status",
        "status_text": "待发布",
        "verified_on_current_page": True,
        "status_scope_unique": True,
        "bound_candidate_count": 1,
        "structured_candidate_count": 1,
        "target_bound": True,
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "identity_binding_kind": "frozen_target_structured_page_readback",
        "publish_risk_term": None,
        "target_identity_sha256": target_digest,
        "page_url": _SEMI_MANAGED_URL,
        "identity_readback": {
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
        },
    }


def _action_result_pair(
    *,
    target_identity: dict,
    store_name: str,
    save_ref: dict,
    unpublished_ref: dict,
) -> tuple[dict, dict, dict]:
    target_digest = _canonical_sha256(target_identity)
    save_result = _strict_save_result(
        target_identity=target_identity,
        store_name=store_name,
    )
    proof = _unpublished_proof(target_digest=target_digest)
    page_identity = {
        "kind": "semi_managed",
        "url": _SEMI_MANAGED_URL,
        "runtime_id": "runtime-1",
        "browser_session_id": "browser-session-1",
    }
    recoverability = {
        "kind": "none",
        "retryable": False,
        "requires_page_reverify": False,
        "reason": None,
    }
    save = {
        "schema_version": "dxm.action-result.v1",
        "ok": True,
        "action": "save_only",
        "attempted_state": "SAVE_ONLY",
        "before_values": {
            "target_identity": target_identity,
            "store_name": store_name,
        },
        "after_values": {
            "exact_save_target": True,
            "save_click_dispatched": True,
            "published": False,
            "mutation_authorization": save_result["mutation_authorization"],
            "pre_dispatch_readback": save_result["pre_dispatch_readback"],
            "network_save_result": save_result["network_save_result"],
            "network_audit": save_result["network_audit"],
            "publish_signal": save_result["publish_signal"],
            "page_save_result": save_result["page_save_result"],
        },
        "postconditions": {
            "mutation_authorized": True,
            "exact_save_target": True,
            "save_click_dispatched": True,
            "network_save_success": True,
            "page_save_success": True,
            "published_false": True,
            "publish_action_not_clicked": True,
        },
        "evidence": {
            "observations": {
                "save_result": save_result,
                "exact_save_target": {
                    "text": "保存",
                    "exact_save_count": 1,
                    "click_method": save_result["click_method"],
                },
                "save_click_dispatched": True,
                "mutation_authorization": save_result["mutation_authorization"],
                "pre_dispatch_readback": save_result["pre_dispatch_readback"],
                "network_save_result": save_result["network_save_result"],
                "network_audit": save_result["network_audit"],
                "publish_signal": save_result["publish_signal"],
                "page_save_result": save_result["page_save_result"],
            },
            "refs": [
                _immutable_action_ref(
                    save_ref,
                    kind="save_screenshot",
                    captured_at="2026-07-22T08:00:02+00:00",
                )
            ],
        },
        "page_identity": page_identity,
        "failure_code": None,
        "recoverability": recoverability,
    }
    observed_target = {
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "target_bound": True,
        "target_identity_sha256": target_digest,
    }
    verify = {
        "schema_version": "dxm.action-result.v1",
        "ok": True,
        "action": "verify_not_published",
        "attempted_state": "VERIFY_NOT_PUBLISHED",
        "before_values": {"target_identity": target_identity},
        "after_values": {
            "published": False,
            "fresh_probe": proof,
            "target_identity": observed_target,
            "identity_readback": proof["identity_readback"],
        },
        "postconditions": {
            "independent_probe": True,
            "product_identity_match": True,
            "unpublished_verified": True,
            "publish_status_absent_or_false": True,
            "save_evidence_not_reused": True,
        },
        "evidence": {
            "observations": {
                "fresh_probe": proof,
                "target_identity": observed_target,
                "identity_readback": proof["identity_readback"],
            },
            "refs": [
                _immutable_action_ref(
                    unpublished_ref,
                    kind="unpublished_screenshot",
                    captured_at="2026-07-22T08:00:03+00:00",
                )
            ],
        },
        "page_identity": page_identity,
        "failure_code": None,
        "recoverability": recoverability,
    }
    validate_independent_save_verification_pair(save, verify)
    return save, verify, save_result


def _complete_single_save(repo: Repository, fixture: dict) -> dict:
    task = repo.get_task_private(fixture["task"]["id"])
    target_identity = task["payload"]["product_box_snapshot"]["target_identity"]
    save_ref = _evidence_ref(f"save-{task['id']}.png")
    unpublished_ref = _evidence_ref(f"unpublished-{task['id']}.png")
    save, verify, save_result = _action_result_pair(
        target_identity=target_identity,
        store_name=fixture["store"]["name"],
        save_ref=save_ref,
        unpublished_ref=unpublished_ref,
    )
    job = task["jobs"][0]
    repo.add_evidence(
        task["id"],
        job["id"],
        "workflow_action",
        save_ref["path"],
        {
            "state": "SAVE_ONLY",
            "action": "save_only",
            "save_result": save_result,
            "evidence_ref": save_ref,
        },
    )
    repo.add_evidence(
        task["id"],
        job["id"],
        "workflow_action",
        unpublished_ref["path"],
        {
            "state": "VERIFY_NOT_PUBLISHED",
            "action": "verify_not_published",
            "published": False,
            "evidence_ref": unpublished_ref,
        },
    )
    report = repo.add_report(
        task["id"],
        job["id"],
        fixture["product"]["id"],
        "success",
        False,
        {
            "save_result": save_result,
            "workflow_results": [save, verify],
        },
        {
            "stage": "product_box_edit_save",
            "status": "success",
            "product_id": fixture["product"]["id"],
            "workflow_actions": ["save_only", "verify_not_published"],
            "workflow_results": [save, verify],
            "published": False,
        },
    )
    repo.update_job(job["id"], status="succeeded")
    repo.update_task_status(
        task["id"],
        "completed",
        completed_jobs=1,
        failed_jobs=0,
    )
    return {
        **fixture,
        "task": repo.get_task_private(task["id"]),
        "job": repo.get_task_private(task["id"])["jobs"][0],
        "report": report,
        "save_ref": save_ref,
        "unpublished_ref": unpublished_ref,
    }


@pytest.mark.parametrize(
    ("task", "jobs", "reports", "exceptions", "expected_code"),
    [
        (
            {"id": 1, "status": "completed", "total_jobs": 1, "completed_jobs": 0, "failed_jobs": 1},
            [{"id": 11, "task_id": 1, "status": "failed"}],
            [],
            [],
            "STATE_TASK_COMPLETED_HAS_FAILED_JOB",
        ),
        (
            {"id": 2, "status": "failed", "total_jobs": 1, "completed_jobs": 0, "failed_jobs": 1},
            [{"id": 12, "task_id": 2, "status": "failed"}],
            [{"id": 21, "task_id": 2, "job_id": 12, "status": "success"}],
            [],
            "STATE_FAILED_JOB_HAS_SUCCESS_REPORT",
        ),
        (
            {"id": 3, "status": "completed", "total_jobs": 1, "completed_jobs": 1, "failed_jobs": 0},
            [{"id": 13, "task_id": 3, "status": "succeeded"}],
            [{"id": 22, "task_id": 3, "job_id": 13, "status": "success"}],
            [{"id": 31, "task_id": 3, "job_id": 13, "status": "open"}],
            "STATE_SUCCESS_HAS_OPEN_EXCEPTION",
        ),
        (
            {"id": 4, "status": "completed", "total_jobs": 1, "completed_jobs": 0, "failed_jobs": 0},
            [{"id": 14, "task_id": 4, "status": "pending"}],
            [],
            [],
            "STATE_COMPLETED_TASK_REQUIRES_ALL_JOBS_SUCCEEDED",
        ),
        (
            {"id": 5, "status": "draft", "total_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
            [],
            [{"id": 23, "task_id": 5, "job_id": 999, "status": "success"}],
            [],
            "STATE_REPORT_REFERENCES_UNKNOWN_JOB",
        ),
    ],
)
def test_state_consistency_rejects_contradictory_persisted_facts(
    task,
    jobs,
    reports,
    exceptions,
    expected_code,
):
    result = audit_state_consistency(
        task=task,
        jobs=jobs,
        reports=reports,
        exceptions=exceptions,
    )

    assert result["consistent"] is False
    assert expected_code in result["violation_codes"]


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


def test_empty_workspace_exposes_single_save_contract_without_claim_surface(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)

    data = delivery_workspace.build_delivery_workspace(repo)

    assert data["current_task"] is None
    assert data["single_save_acceptance"]["schema"] == "dxm_single_save_acceptance.v1"
    assert data["single_save_acceptance"]["status"] == "no_task"
    assert data["delivery_readiness"]["single_save_missing_codes"] == ["task"]
    assert "two_stage_acceptance" not in data
    assert "claim_candidates" not in data


def test_product_box_snapshot_is_frozen_when_single_save_task_is_created(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    fixture = _create_product_box_task(repo)
    task = fixture["task"]

    snapshot = task["payload"]["product_box_snapshot"]
    assert snapshot["product_id"] == fixture["product"]["id"]
    assert snapshot["store_id"] == fixture["store"]["id"]
    assert snapshot["product_title"] == fixture["product"]["title"]
    assert task["payload"]["product_box_snapshot_fingerprint"] == snapshot["fingerprint"]
    assert repo.single_save_product_box_snapshot_error(task, fixture["product"]) is None


def test_single_save_waits_for_server_approval_before_any_save_evidence(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["status"] == "approval_required"
    assert acceptance["checks"]["product_box_snapshot_valid"] is True
    assert acceptance["checks"]["single_save_target_bound"] is True
    assert acceptance["checks"]["manual_approval_consumed"] is False
    assert "manual_approval_consumed" in acceptance["missing_codes"]
    assert data["delivery_readiness"]["ready"] is False


def test_complete_product_box_single_save_passes_acceptance_and_readiness(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["passed"] is True
    assert acceptance["status"] == "passed"
    assert acceptance["missing_codes"] == []
    assert all(acceptance["checks"].values())
    assert data["delivery_readiness"]["ready"] is True
    assert data["publish_guard_state"]["status"] == "safe_unpublished"
    assert data["evidence_grade"]["grade"] == "A"


def test_single_save_snapshot_fingerprint_drift_blocks_every_ready_surface(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)
    task = repo.get_task_private(fixture["task"]["id"])
    payload = dict(task["payload"])
    payload["product_box_snapshot_fingerprint"] = "F" * 64
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task["id"]),
        )

    data = delivery_workspace.build_delivery_workspace(repo, task["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["status"] == "missing_product_box_snapshot"
    assert acceptance["checks"]["product_box_snapshot_valid"] is False
    assert "product_box_snapshot" in acceptance["missing_codes"]
    assert data["delivery_readiness"]["ready"] is False
    assert data["evidence_grade"]["grade"] == "C"
    assert data["regression_gates"][-1]["status"] == "blocked"


def test_current_product_identity_drift_blocks_saved_task(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET title='DRIFTED PRODUCT' WHERE id=?",
            (fixture["product"]["id"],),
        )

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["passed"] is False
    assert acceptance["checks"]["product_box_snapshot_valid"] is False
    assert "no longer matches" in acceptance["product_box_snapshot_error"]


def test_l3_evidence_is_rehashed_before_ready(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)
    Path(fixture["save_ref"]["path"]).write_bytes(b"tampered")

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["status"] == "invalid_l3_evidence"
    assert acceptance["checks"]["save_evidence_integrity"] is False
    assert "save_evidence_integrity" in acceptance["missing_codes"]
    assert data["delivery_readiness"]["ready"] is False


def test_report_published_false_is_not_proof_without_independent_readback(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)
    report = repo.get_report(fixture["report"]["id"])
    save_result = deepcopy(report["save_result"])
    summary = deepcopy(report["summary"])
    save_result["workflow_results"] = [save_result["workflow_results"][0]]
    summary["workflow_results"] = [summary["workflow_results"][0]]
    summary.pop("published", None)
    with db.connection() as conn:
        conn.execute(
            "UPDATE reports SET save_result_json=?, summary_json=? WHERE id=?",
            (db.dumps(save_result), db.dumps(summary), report["id"]),
        )

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    acceptance = data["single_save_acceptance"]
    assert acceptance["passed"] is False
    assert acceptance["checks"]["unpublished_proof"] is False
    assert "unpublished_proof" in acceptance["missing_codes"]
    assert data["publish_guard_state"]["safe"] is False


def test_workspace_l2_passes_with_one_fresh_bound_draft_box_probe(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    fixture = _create_product_box_task(repo)
    l2_dir = tmp_path / "l2"
    _write_l2_probe_result(l2_dir)
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", l2_dir)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    l2 = next(item for item in data["regression_gates"] if item["level"] == "L2")
    assert l2["status"] == "passed"
    assert l2["latest"]["requiredTargets"] == ["draft_box"]
    assert l2["latest"]["missingTargets"] == []
    assert l2["latest"]["runBinding"]["runIds"] == ["run-20260722T080000Z"]


def test_workspace_l2_rejects_stale_draft_box_probe(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    fixture = _create_product_box_task(repo)
    l2_dir = tmp_path / "l2"
    stale_at = (
        datetime.now(timezone.utc)
        - timedelta(seconds=delivery_workspace.L2_REAL_TARGET_MAX_AGE_SECONDS + 10)
    ).isoformat()
    _write_l2_probe_result(l2_dir, created_at=stale_at)
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", l2_dir)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    l2 = next(item for item in data["regression_gates"] if item["level"] == "L2")
    assert l2["status"] == "failed"
    assert l2["latest"]["timeWindow"]["ok"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("evidence_binding"),
        lambda payload: payload["evidence_binding"].update(
            {"target_set": ["data_acquisition", "draft_box"]}
        ),
        lambda payload: payload["evidence_binding"].update(
            {"script_sha256": "D" * 64}
        ),
        lambda payload: payload.update({"screenshot_sha256": "0" * 64}),
        lambda payload: payload.update(
            {"final_url": "https://www.dianxiaomi.com/web/index.htm"}
        ),
    ],
)
def test_workspace_l2_fails_closed_on_invalid_binding_or_evidence(
    tmp_path,
    monkeypatch,
    mutate,
):
    repo = _repo(tmp_path, monkeypatch)
    fixture = _create_product_box_task(repo)
    l2_dir = tmp_path / "l2"
    result_path = _write_l2_probe_result(l2_dir)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    mutate(payload)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(delivery_workspace, "L2_RUNTIME_PROBE_DIR", l2_dir)
    monkeypatch.setattr(delivery_workspace, "L2_PROBE_DIR", l2_dir)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    l2 = next(item for item in data["regression_gates"] if item["level"] == "L2")
    assert l2["status"] == "failed"
    assert l2["latest"]["failedTargets"] == ["draft_box"]


def test_persisted_state_contradiction_blocks_completed_single_save(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    _mark_manual_approval_consumed(repo, fixture["task"]["id"])
    fixture = _complete_single_save(repo, fixture)
    repo.update_job(fixture["job"]["id"], status="failed", error_code="E901")
    repo.update_task_status(
        fixture["task"]["id"],
        "failed",
        completed_jobs=0,
        failed_jobs=1,
    )

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    assert data["state_consistency"]["consistent"] is False
    assert data["single_save_acceptance"]["status"] == "inconsistent_state"
    assert data["delivery_readiness"]["ready"] is False
    assert data["evidence_grade"]["grade"] == "C"


def test_real_mode_release_plan_has_no_claim_mode_and_never_allows_publish(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)

    data = delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])
    plan = data["real_mode_release_plan"]
    modes = {item["mode"]: item for item in plan["modes"]}

    assert plan["scope"] == "controlled_single_save_and_edit_batch"
    assert plan["publish_allowed"] is False
    assert set(modes) == {"single_save", "controlled_edit_batch", "batch_save"}
    assert modes["single_save"]["allowed"] is True
    assert modes["controlled_edit_batch"]["allowed"] is True
    assert modes["batch_save"]["allowed"] is False
    assert data["l2_probe_plan"]["targets"] == [
        {
            "id": "draft_box",
            "url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "required": True,
        }
    ]
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    assert "claim_only" not in serialized
    assert "claim_candidates" not in serialized


def test_missing_requested_task_fails_closed_without_substitution(
    tmp_path,
    monkeypatch,
):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)

    data = delivery_workspace.build_delivery_workspace(repo, 999999)

    assert data["current_task"] is None
    assert data["requested_task_missing"] is True
    assert data["requested_task_id"] == 999999
    assert data["single_save_acceptance"]["status"] == "no_task"
    assert all(task["id"] != fixture["task"]["id"] for task in data["tasks"])


def test_workspace_read_does_not_change_database_schema(tmp_path, monkeypatch):
    repo = _repo(tmp_path, monkeypatch)
    monkeypatch.setattr(delivery_workspace, "_l2_probe_gate", _passed_l2_gate)
    fixture = _create_product_box_task(repo)
    with db.connection() as conn:
        before = {
            row["name"]: conn.execute(f"PRAGMA table_info({row['name']})").fetchall()
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }

    delivery_workspace.build_delivery_workspace(repo, fixture["task"]["id"])

    with db.connection() as conn:
        after = {
            row["name"]: conn.execute(f"PRAGMA table_info({row['name']})").fetchall()
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
    assert after == before


def test_action_pair_fixture_rejects_target_drift(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    target = {"kind": "source_url", "value": "https://example.test/product/1"}
    save_ref = _evidence_ref("pair-save.png")
    unpublished_ref = _evidence_ref("pair-unpublished.png")
    save, verify, _ = _action_result_pair(
        target_identity=target,
        store_name="Dang Kang",
        save_ref=save_ref,
        unpublished_ref=unpublished_ref,
    )
    verify = deepcopy(verify)
    verify["before_values"]["target_identity"] = {
        "kind": "source_url",
        "value": "https://example.test/product/2",
    }

    with pytest.raises(Exception, match="target identity must match"):
        validate_independent_save_verification_pair(save, verify)
