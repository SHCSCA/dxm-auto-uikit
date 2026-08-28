from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.db import connection, dumps, loads


GENESIS_HASH = "0" * 64
SECRET_KEY_RE = re.compile(
    r"(password|passwd|passphrase|cookie|set-cookie|authorization|token|csrf|"
    r"xsrf|secret|api[_-]?key|sessionid|jsessionid)",
    re.IGNORECASE,
)
OMIT_KEY_RE = re.compile(r"(html|raw_?html|raw_?response|raw_body|page_source)", re.IGNORECASE)
REDACTED = "[REDACTED]"
OMITTED = "[OMITTED]"


class OperationAuditError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def utc_micros() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _bounded_length(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (bytes, str, dict, list, tuple)):
        return len(value)
    return len(str(value))


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("bearer ")
        or "jsessionid=" in lowered
        or lowered.startswith("sk-")
        or "dxm_s=" in lowered
    )


def redact_value(value: Any) -> Any:
    if _is_mapping(value):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if SECRET_KEY_RE.search(name):
                redacted[name] = REDACTED
            elif OMIT_KEY_RE.search(name):
                redacted[name] = {
                    "omitted": OMITTED,
                    "type": type(item).__name__,
                    "length": _bounded_length(item),
                }
            else:
                redacted[name] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _looks_like_secret(value):
        return REDACTED
    return value


def _row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": row["seq"],
        "recorded_at": row["recorded_at"],
        "event_id": row["event_id"],
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "root_correlation_id": row["root_correlation_id"],
        "session_id": row["session_id"],
        "runtime_id": row["runtime_id"],
        "browser_id": row["browser_id"],
        "actor": row["actor"],
        "component": row["component"],
        "action": row["action"],
        "phase": row["phase"],
        "task_id": row["task_id"],
        "job_id": row["job_id"],
        "batch_id": row["batch_id"],
        "item_id": row["item_id"],
        "product_id": row["product_id"],
        "store_id": row["store_id"],
        "category_id": row["category_id"],
        "snapshot_id": row["snapshot_id"],
        "command_id": row["command_id"],
        "mutation_id": row["mutation_id"],
        "lease_id": row["lease_id"],
        "build_id": row["build_id"],
        "reason": row["reason"],
        "status": row["status"],
        "input_summary": loads(row["input_summary_json"], {}),
        "output_summary": loads(row["output_summary_json"], {}),
        "evidence_refs": loads(row["evidence_refs_json"], []),
        "prev_hash": row["prev_hash"],
        "event_hash": row["event_hash"],
        "idempotency_key": row["idempotency_key"],
        "degraded": bool(row["degraded"]),
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    return _sha256_text(_canonical(payload))


class OperationAuditService:
    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = event.get("idempotency_key")
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if isinstance(idempotency_key, str) and idempotency_key.strip():
                existing = conn.execute(
                    "SELECT * FROM operation_audit_events WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return _row_to_event(existing)
            last = conn.execute(
                "SELECT seq, event_hash FROM operation_audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = 1 if last is None else int(last["seq"]) + 1
            prev_hash = GENESIS_HASH if last is None else str(last["event_hash"])
            recorded_at = utc_micros()
            event_id = str(event.get("event_id") or uuid.uuid4())
            correlation_id = str(event.get("correlation_id") or event_id)
            root_correlation_id = str(event.get("root_correlation_id") or correlation_id)
            input_summary = redact_value(event.get("input") or event.get("input_summary") or {})
            output_summary = redact_value(event.get("output") or event.get("output_summary") or {})
            evidence_refs = redact_value(event.get("evidence_refs") or [])
            payload = {
                "seq": seq,
                "recorded_at": recorded_at,
                "event_id": event_id,
                "correlation_id": correlation_id,
                "causation_id": event.get("causation_id"),
                "root_correlation_id": root_correlation_id,
                "session_id": event.get("session_id"),
                "runtime_id": event.get("runtime_id"),
                "browser_id": event.get("browser_id"),
                "actor": str(event.get("actor") or "system"),
                "component": str(event.get("component") or "unknown"),
                "action": str(event.get("action") or "unknown"),
                "phase": str(event.get("phase") or "completed"),
                "task_id": _optional_text(event.get("task_id")),
                "job_id": _optional_text(event.get("job_id")),
                "batch_id": _optional_text(event.get("batch_id")),
                "item_id": _optional_text(event.get("item_id")),
                "product_id": _optional_text(event.get("product_id")),
                "store_id": _optional_text(event.get("store_id")),
                "category_id": _optional_text(event.get("category_id")),
                "snapshot_id": _optional_text(event.get("snapshot_id")),
                "command_id": _optional_text(event.get("command_id")),
                "mutation_id": _optional_text(event.get("mutation_id")),
                "lease_id": _optional_text(event.get("lease_id")),
                "build_id": _optional_text(event.get("build_id")),
                "reason": event.get("reason"),
                "status": str(event.get("status") or "ok"),
                "input_summary": input_summary,
                "output_summary": output_summary,
                "evidence_refs": evidence_refs,
                "prev_hash": prev_hash,
                "idempotency_key": idempotency_key,
                "degraded": bool(event.get("degraded") or False),
            }
            event_hash = _hash_payload(payload)
            conn.execute(
                """
                INSERT INTO operation_audit_events (
                    seq, recorded_at, event_id, correlation_id, causation_id,
                    root_correlation_id, session_id, runtime_id, browser_id,
                    actor, component, action, phase, task_id, job_id, batch_id,
                    item_id, product_id, store_id, category_id, snapshot_id,
                    command_id, mutation_id, lease_id, build_id, reason, status,
                    input_summary_json, output_summary_json, evidence_refs_json,
                    prev_hash, event_hash, idempotency_key, degraded
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    seq,
                    recorded_at,
                    event_id,
                    correlation_id,
                    payload["causation_id"],
                    root_correlation_id,
                    payload["session_id"],
                    payload["runtime_id"],
                    payload["browser_id"],
                    payload["actor"],
                    payload["component"],
                    payload["action"],
                    payload["phase"],
                    payload["task_id"],
                    payload["job_id"],
                    payload["batch_id"],
                    payload["item_id"],
                    payload["product_id"],
                    payload["store_id"],
                    payload["category_id"],
                    payload["snapshot_id"],
                    payload["command_id"],
                    payload["mutation_id"],
                    payload["lease_id"],
                    payload["build_id"],
                    payload["reason"],
                    payload["status"],
                    dumps(input_summary),
                    dumps(output_summary),
                    dumps(evidence_refs),
                    prev_hash,
                    event_hash,
                    idempotency_key,
                    int(payload["degraded"]),
                ),
            )
            row = conn.execute(
                "SELECT * FROM operation_audit_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        return _row_to_event(row)

    def list_events(
        self,
        *,
        status: str | None = None,
        task_id: str | None = None,
        product_id: str | None = None,
        component: str | None = None,
        phase: str | None = None,
        reason: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["1=1"]
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if task_id:
            clauses.append("task_id=?")
            params.append(str(task_id))
        if product_id:
            clauses.append("product_id=?")
            params.append(str(product_id))
        if component:
            clauses.append("component=?")
            params.append(component)
        if phase:
            clauses.append("phase=?")
            params.append(phase)
        if reason:
            clauses.append("reason=?")
            params.append(reason)
        where = " AND ".join(clauses)
        with connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM operation_audit_events WHERE {where}",
                params,
            ).fetchone()["n"]
            rows = conn.execute(
                f"""
                SELECT * FROM operation_audit_events
                 WHERE {where}
                 ORDER BY seq ASC
                 LIMIT ? OFFSET ?
                """,
                [*params, max(1, min(int(limit), 1000)), max(0, int(offset))],
            ).fetchall()
        return {"total": int(total), "events": [_row_to_event(row) for row in rows]}

    def verify_chain(self) -> dict[str, Any]:
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM operation_audit_events ORDER BY seq ASC"
            ).fetchall()
        expected_prev = GENESIS_HASH
        expected_seq = 1
        for row in rows:
            event = _row_to_event(row)
            if int(event["seq"]) != expected_seq or event["prev_hash"] != expected_prev:
                return {
                    "ok": False,
                    "reason_code": "AUDIT_HASH_CHAIN_GAP",
                    "event_count": len(rows),
                    "broken_seq": event["seq"],
                }
            payload = {
                key: event[key]
                for key in (
                    "seq",
                    "recorded_at",
                    "event_id",
                    "correlation_id",
                    "causation_id",
                    "root_correlation_id",
                    "session_id",
                    "runtime_id",
                    "browser_id",
                    "actor",
                    "component",
                    "action",
                    "phase",
                    "task_id",
                    "job_id",
                    "batch_id",
                    "item_id",
                    "product_id",
                    "store_id",
                    "category_id",
                    "snapshot_id",
                    "command_id",
                    "mutation_id",
                    "lease_id",
                    "build_id",
                    "reason",
                    "status",
                    "input_summary",
                    "output_summary",
                    "evidence_refs",
                    "prev_hash",
                    "idempotency_key",
                    "degraded",
                )
            }
            if _hash_payload(payload) != event["event_hash"]:
                return {
                    "ok": False,
                    "reason_code": "AUDIT_HASH_CHAIN_GAP",
                    "event_count": len(rows),
                    "broken_seq": event["seq"],
                }
            expected_prev = event["event_hash"]
            expected_seq += 1
        return {"ok": True, "reason_code": None, "event_count": len(rows)}

    def run_authorized_mutation(
        self,
        event: dict[str, Any],
        *,
        persist: Callable[[], Any],
        click: Callable[[], Any],
    ) -> Any:
        try:
            persist()
            self.append_event(
                {
                    **event,
                    "phase": event.get("phase") or "authorized",
                    "status": "ok",
                }
            )
        except OperationAuditError:
            raise
        except Exception as exc:
            raise OperationAuditError(
                "AUDIT_WRITE_FAILED",
                "真实点击前审计未能持久化，已停止点击。",
            ) from exc
        return click()

    def record_post_mutation_uncertainty(self, event: dict[str, Any]) -> dict[str, Any]:
        stored = self.append_event(
            {
                **event,
                "status": "UNKNOWN",
                "reason": event.get("reason") or "POST_MUTATION_EVIDENCE_UNCERTAIN",
                "phase": event.get("phase") or "dispatched",
            }
        )
        return {
            "status": "UNKNOWN",
            "stop_batch": True,
            "retry_allowed": False,
            "event": stored,
        }

    def export_diagnostic_zip(self, dest: str | Path) -> dict[str, Any]:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        listed = self.list_events(limit=10000)
        chain = self.verify_chain()
        events_text = "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in listed["events"]
        )
        manifest = {
            "schema": "dxm_operation_audit_export.v1",
            "event_count": listed["total"],
            "chain": chain,
            "redacted": True,
        }
        redaction_report = {
            "secrets_omitted": True,
            "html_omitted": True,
            "raw_responses_omitted": True,
        }
        files = {
            "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            "events.jsonl": events_text.encode("utf-8"),
            "redaction-report.json": json.dumps(
                redaction_report, ensure_ascii=False, indent=2
            ).encode("utf-8"),
        }
        checksums = {
            name: hashlib.sha256(body).hexdigest().upper() for name, body in files.items()
        }
        files["SHA256SUMS.txt"] = (
            "\n".join(f"{digest}  {name}" for name, digest in checksums.items()) + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return {
            "path": str(dest_path),
            "sha256": hashlib.sha256(dest_path.read_bytes()).hexdigest().upper(),
            "event_count": listed["total"],
            "chain_ok": chain["ok"],
        }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_SERVICE: OperationAuditService | None = None


def get_audit_service() -> OperationAuditService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = OperationAuditService()
    return _SERVICE


def record_best_effort(event: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_audit_service().append_event(event)
    except Exception as exc:
        return {
            "degraded": True,
            "status": "AUDIT_DEGRADED",
            "reason": getattr(exc, "reason_code", None) or type(exc).__name__,
        }
