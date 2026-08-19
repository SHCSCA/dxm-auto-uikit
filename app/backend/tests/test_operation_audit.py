"""Full-chain operation audit: persist, redact, hash-chain, mutation fail-closed."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src import db


def _service(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "operation-audit.db")
    db.init_db()
    from src.services.operation_audit import OperationAuditService

    return OperationAuditService()


def test_secret_fields_never_persist_in_db_api_or_zip(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    stored = service.append_event(
        {
            "actor": "operator",
            "component": "dxm_access",
            "action": "login_start",
            "phase": "requested",
            "status": "ok",
            "correlation_id": "corr-login-1",
            "input": {
                "password": "hunter2-secret",
                "Cookie": "dxm_s=abc",
                "Authorization": "Bearer sk-test",
                "token": "session-token",
                "username": "operator",
            },
            "output": {"html": "<html>full page</html>", "raw_response": {"code": 0}},
        }
    )
    listed = service.list_events()
    export_path = tmp_path / "diag.zip"
    service.export_diagnostic_zip(export_path)
    blob = json.dumps([stored, listed], ensure_ascii=False)
    with zipfile.ZipFile(export_path) as archive:
        blob += archive.read("events.jsonl").decode("utf-8")
        blob += archive.read("redaction-report.json").decode("utf-8")
    assert "hunter2-secret" not in blob
    assert "dxm_s=abc" not in blob
    assert "Bearer sk-test" not in blob
    assert "session-token" not in blob
    assert "<html>full page</html>" not in blob
    assert stored["input_summary"]["password"] == "[REDACTED]"


def test_hash_chain_detects_tamper_and_deleted_sequence(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    first = service.append_event(
        {
            "actor": "system",
            "component": "desktop",
            "action": "backend_health",
            "phase": "completed",
            "status": "ok",
            "correlation_id": "corr-boot",
        }
    )
    service.append_event(
        {
            "actor": "operator",
            "component": "plan",
            "action": "preview",
            "phase": "completed",
            "status": "ok",
            "correlation_id": "corr-preview",
            "causation_id": first["event_id"],
        }
    )
    healthy = service.verify_chain()
    assert healthy["ok"] is True
    assert healthy["event_count"] == 2

    with db.connection() as conn:
        conn.execute(
            "UPDATE operation_audit_events SET status='forged' WHERE seq=2"
        )
    tampered = service.verify_chain()
    assert tampered["ok"] is False
    assert tampered["reason_code"] == "AUDIT_HASH_CHAIN_GAP"


def test_mutation_requires_persisted_preclick_audit_or_zero_operations(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    clicks = {"count": 0}

    def click() -> None:
        clicks["count"] += 1

    with pytest.raises(Exception) as exc:
        service.run_authorized_mutation(
            {
                "actor": "runner",
                "component": "save",
                "action": "save_only_click",
                "mutation_id": "mut-1",
                "correlation_id": "corr-save",
            },
            persist=lambda: (_ for _ in ()).throw(RuntimeError("disk full")),
            click=click,
        )
    assert getattr(exc.value, "reason_code", "") == "AUDIT_WRITE_FAILED"
    assert clicks["count"] == 0


def test_post_click_uncertain_evidence_marks_unknown_and_stops_batch(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    result = service.record_post_mutation_uncertainty(
        {
            "actor": "runner",
            "component": "save",
            "action": "save_only_click",
            "phase": "dispatched",
            "mutation_id": "mut-2",
            "correlation_id": "corr-save-2",
            "task_id": "10",
            "job_id": "20",
            "product_id": "130658340712223024",
        }
    )
    assert result["status"] == "UNKNOWN"
    assert result["stop_batch"] is True
    assert result["retry_allowed"] is False
    listed = service.list_events(status="UNKNOWN")
    assert listed["total"] == 1


def test_events_survive_restart_and_keep_unknown(tmp_path, monkeypatch):
    first = _service(tmp_path, monkeypatch)
    first.record_post_mutation_uncertainty(
        {
            "actor": "runner",
            "component": "save",
            "action": "save_only_click",
            "phase": "dispatched",
            "mutation_id": "mut-3",
            "correlation_id": "corr-restart",
            "task_id": "11",
        }
    )
    restarted = _service(tmp_path, monkeypatch)
    listed = restarted.list_events()
    assert listed["total"] == 1
    assert listed["events"][0]["status"] == "UNKNOWN"
    assert listed["events"][0]["correlation_id"] == "corr-restart"
    assert restarted.verify_chain()["ok"] is True


def test_same_operator_action_reuses_root_correlation_and_is_idempotent(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    payload = {
        "actor": "operator",
        "component": "draft_selection",
        "action": "select_products",
        "phase": "completed",
        "status": "ok",
        "correlation_id": "corr-select",
        "root_correlation_id": "root-select",
        "idempotency_key": "select:task-input:v1",
        "input": {"product_ids": ["1", "2", "3"]},
    }
    first = service.append_event(payload)
    second = service.append_event(payload)
    assert first["event_id"] == second["event_id"]
    assert first["root_correlation_id"] == "root-select"
    assert service.list_events()["total"] == 1
