"""E4 task control: operator request + worker acknowledgement (MVP §5.4 / §7.5).

API never pretends pause/stop is complete until the runner acks at a safe point
(after the current product finishes, before the next product is dispatched).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CONTROL_SCHEMA = "dxm_task_worker_control.v1"
PAYLOAD_KEY = "worker_control"

# Operator has asked; worker has not acked yet.
REQUESTED_STATUSES = frozenset({"pause_requested", "stop_requested"})
# Task owns the browser / queue and must block another active start.
ACTIVE_TASK_STATUSES = frozenset(
    {
        "running",
        "pause_requested",
        "stop_requested",
        "paused",
    }
)
# Jobs that must not be re-dispatched on resume.
TERMINAL_SUCCESS_JOB_STATUSES = frozenset({"completed", "succeeded"})
TERMINAL_FAILURE_JOB_STATUSES = frozenset({"failed", "unknown", "cancelled", "skipped"})
SKIP_ON_RESUME_JOB_STATUSES = TERMINAL_SUCCESS_JOB_STATUSES | TERMINAL_FAILURE_JOB_STATUSES


@dataclass(frozen=True)
class TaskControlResult:
    ok: bool
    reason_code: str
    status: str | None = None
    applied: bool = False
    idempotent: bool = False
    worker_control: dict[str, Any] | None = None

    def as_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "reasonCode": self.reason_code,
            "applied": self.applied,
            "idempotent": self.idempotent,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.worker_control is not None:
            payload["workerControl"] = public_worker_control(self.worker_control)
        return payload


def empty_worker_control() -> dict[str, Any]:
    return {
        "schema_version": CONTROL_SCHEMA,
        "request": None,
        "requested_at": None,
        "acked_at": None,
        "ack": None,
        "reason_code": None,
        "detail": None,
    }


def normalize_worker_control(raw: Any) -> dict[str, Any]:
    base = empty_worker_control()
    if not isinstance(raw, Mapping):
        return base
    request = raw.get("request")
    if request in {"pause", "stop"}:
        base["request"] = request
    ack = raw.get("ack")
    if ack in {"paused", "stopped"}:
        base["ack"] = ack
    for key in ("requested_at", "acked_at", "reason_code", "detail"):
        value = raw.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            base[key] = text
    schema = raw.get("schema_version") or raw.get("schema")
    if schema:
        base["schema_version"] = str(schema)
    return base


def public_worker_control(raw: Any) -> dict[str, Any]:
    control = normalize_worker_control(raw)
    return {
        "schemaVersion": control.get("schema_version"),
        "request": control.get("request"),
        "requestedAt": control.get("requested_at"),
        "ackedAt": control.get("acked_at"),
        "ack": control.get("ack"),
        "reasonCode": control.get("reason_code"),
        "detail": control.get("detail"),
        "pending": control.get("request") in {"pause", "stop"} and control.get("ack") is None,
    }


def build_request_control(
    *,
    request: str,
    requested_at: str,
    reason_code: str,
    detail: str | None = None,
) -> dict[str, Any]:
    if request not in {"pause", "stop"}:
        raise ValueError(f"unsupported control request: {request}")
    control = empty_worker_control()
    control["request"] = request
    control["requested_at"] = requested_at
    control["reason_code"] = reason_code
    if detail:
        control["detail"] = " ".join(str(detail).split())
    return control


def build_ack_control(
    previous: Any,
    *,
    ack: str,
    acked_at: str,
    reason_code: str,
    detail: str | None = None,
) -> dict[str, Any]:
    if ack not in {"paused", "stopped"}:
        raise ValueError(f"unsupported control ack: {ack}")
    control = normalize_worker_control(previous)
    control["ack"] = ack
    control["acked_at"] = acked_at
    control["reason_code"] = reason_code
    if detail:
        control["detail"] = " ".join(str(detail).split())
    # Clear pending request after ack so HVD shows settled state.
    control["request"] = None
    return control


def job_should_skip_on_resume(job: Mapping[str, Any] | None) -> bool:
    status = str((job or {}).get("status") or "").strip().lower()
    return status in SKIP_ON_RESUME_JOB_STATUSES


def job_is_terminal_success(job: Mapping[str, Any] | None) -> bool:
    status = str((job or {}).get("status") or "").strip().lower()
    return status in TERMINAL_SUCCESS_JOB_STATUSES


def job_is_dispatchable(job: Mapping[str, Any] | None) -> bool:
    status = str((job or {}).get("status") or "").strip().lower()
    return status in {"pending", "running"}
