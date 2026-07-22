from __future__ import annotations

import os
import json
import hashlib
import time
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, RLock
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse

from src.core.config import DATA_DIR, SCREENSHOT_DIR
from src.execution.action_result_contract import (
    ACTION_RESULT_CONTRACTS,
    ACTION_RESULT_SCHEMA_VERSION,
    ActionResultContractError,
    validate_action_result_envelope,
)
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    canonical_frozen_target_identity,
    canonical_mutation_target_payload,
)
from src.services.browser_agent_status import build_browser_hud, normalize_operator_copy
from src.services.evidence_ref import validate_evidence_ref


_RAW_CONTRACT_FACT_KEYS = frozenset(
    {
        "before_values",
        "after_values",
        "postconditions",
        "evidence_observations",
        "failure_code",
        "recoverability",
    }
)
_PROOF_EVIDENCE_KIND_BY_STATE = MappingProxyType(
    {
        "VERIFY_DRAFT_BOX_CLAIM": "draft_box_screenshot",
        "SAVE_ONLY": "save_screenshot",
        "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
    }
)
_MUTATION_ACTION_SEQUENCE_BY_STATE = MappingProxyType(
    {
        "CLAIM_TO_DRAFT_BOX": MappingProxyType(
            {
                "claim_open_dialog_click": 1,
                "claim_confirm_click": 2,
            }
        ),
        "SAVE_ONLY": MappingProxyType({"save_only_click": 1}),
    }
)
_FROZEN_TARGET_REQUIRED_ACTIONS = frozenset(
    {
        "claim_product",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    }
)


@dataclass(frozen=True)
class BrowserAgentExecutionContext:
    """Immutable identity and lifetime boundary for one submitted command."""

    command_id: str
    idempotency_key: str
    runtime_id: str
    browser_session_id: str | None
    expected_page: str
    generation: int
    deadline_monotonic: float | None
    cancel_epoch: int
    task_id: Any
    job_id: Any
    state: str
    mode: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "task_id": self.task_id,
                "job_id": self.job_id,
                "state": self.state,
                "mode": self.mode,
                "command_id": self.command_id,
                "idempotency_key": self.idempotency_key,
                "runtime_id": self.runtime_id,
                "browser_session_id": self.browser_session_id,
                "expected_page": self.expected_page,
                "generation": self.generation,
                "deadline_monotonic": self.deadline_monotonic,
                "cancel_epoch": self.cancel_epoch,
            }
        )


@dataclass
class _ExecutionLease:
    context: BrowserAgentExecutionContext
    authorizer: Any | None
    adapter: Any | None = None
    revoked: bool = False
    worker_finished: bool = False
    outer_finalized: bool = False
    terminalizing: bool = False
    terminal_result: dict[str, Any] | None = None
    terminal_error_type: str | None = None
    terminal_error_message: str | None = None
    mutation_dispatch_inflight: bool = False
    mutation_dispatch_action: str | None = None
    mutation_bound_identity: dict[str, Any] | None = None
    completion_event: Event = field(default_factory=Event)


@dataclass
class _IdempotencyRecord:
    fingerprint: str
    result: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    completed: bool = False


@dataclass
class _CommandReservation:
    command_id: str
    idempotency_key: str
    runtime_id: str
    fingerprint: str
    cancelled: bool = False


@dataclass(frozen=True)
class _LifecycleOwner:
    action: str
    token: int


@dataclass
class _ShutdownFlight:
    completion_event: Event = field(default_factory=Event)
    close_started: bool = False
    result: dict[str, Any] | None = None


_CONTROL_STATE_REJECTIONS = {
    "takeover": {
        "stopped": "BROWSER_AGENT_STOPPED_REQUIRES_RESET",
        "resetting": "BROWSER_AGENT_RESET_IN_PROGRESS",
        "stopping": "BROWSER_AGENT_STOPPING",
    },
    "resume": {
        "stopped": "BROWSER_AGENT_STOPPED_REQUIRES_RESET",
        "resetting": "BROWSER_AGENT_RESET_IN_PROGRESS",
        "stopping": "BROWSER_AGENT_STOPPING",
    },
    "shutdown": {
        "resetting": "BROWSER_AGENT_RESET_IN_PROGRESS",
    },
    "reset": {
        "resetting": "BROWSER_AGENT_RESET_IN_PROGRESS",
        "stopping": "BROWSER_AGENT_STOPPING",
    },
}


class BrowserAgentRuntime:
    """Persistent in-process owner for visible DXM browser commands."""

    def __init__(
        self,
        adapter: Any | None = None,
        *,
        mutation_ledger: Any | None = None,
    ) -> None:
        self.adapter = adapter
        self._runtime_id = uuid.uuid4().hex
        self._mutation_authorizer: Any | None = None
        self._mutation_ledger = mutation_ledger
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-browser-agent")
        self._lock = RLock()
        self._mutation_dispatch_gate = Lock()
        self._generation = 0
        self._cancel_epoch = 0
        self._active_lease: _ExecutionLease | None = None
        self._active_future: Any | None = None
        self._lifecycle_intent: str | None = None
        self._lifecycle_epoch = 0
        self._lifecycle_owner: _LifecycleOwner | None = None
        self._takeover_snapshot: dict[str, Any] | None = None
        self._shutdown_flight: _ShutdownFlight | None = None
        self._idempotency_records: OrderedDict[str, _IdempotencyRecord] = OrderedDict()
        self._idempotency_cache_limit = 128
        self._command_reservations: dict[str, _CommandReservation] = {}
        self._status: dict[str, Any] = {
            "sessionId": None,
            "status": "idle",
            "healthy": True,
            "active": False,
            "browserVisible": False,
            "currentStep": "待启动",
            "lastError": None,
            "lastWorkflowEvent": None,
            "lastEventAt": None,
            "manualTakeover": False,
            "hud": None,
            "message": None,
            "nextAction": None,
            "profile_dir": None,
            "needsRestart": False,
        }
        self.events: list[dict[str, Any]] = []

    @property
    def runtime_id(self) -> str:
        with self._lock:
            return self._runtime_id

    def set_adapter(self, adapter: Any | None) -> None:
        with self._lock:
            self.adapter = adapter

    def set_mutation_authorizer(self, authorizer: Any | None) -> None:
        with self._lock:
            self._mutation_authorizer = authorizer if callable(authorizer) else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._status["sessionId"] = self._adapter_browser_session_id(self.adapter)
            status = dict(self._status)
            status["runtimeId"] = self._runtime_id
            status["reservedCommandCount"] = len(self._command_reservations)
            status["mutationLedgerEnabled"] = self._mutation_ledger is not None
            status["events"] = list(self.events[-20:])
            return status

    def reserve_command(self, command: BrowserAgentCommand) -> dict[str, Any]:
        with self._lock:
            self._validate_command_locked(command, timeout_seconds=None)
            ledger = self._mutation_ledger
            if ledger is not None:
                try:
                    ledger_decision = ledger.reserve_command(command)
                except Exception as exc:
                    return {
                        "ok": False,
                        "reasonCode": "MUTATION_LEDGER_UNAVAILABLE",
                        "detail": str(exc),
                        "runtimeId": self._runtime_id,
                    }
                if getattr(ledger_decision, "ok", False) is not True:
                    return {
                        "ok": False,
                        "reasonCode": str(
                            getattr(ledger_decision, "reason_code", None)
                            or "MUTATION_LEDGER_RESERVATION_REJECTED"
                        ),
                        "runtimeId": self._runtime_id,
                    }
            fingerprint = _command_fingerprint(command)
            existing = self._command_reservations.get(command.command_id)
            if existing is not None:
                if (
                    existing.runtime_id != command.runtime_id
                    or existing.idempotency_key != command.idempotency_key
                    or existing.fingerprint != fingerprint
                ):
                    return {
                        "ok": False,
                        "reasonCode": "BROWSER_AGENT_RESERVATION_CONFLICT",
                        "runtimeId": self._runtime_id,
                    }
                return {
                    "ok": True,
                    "commandId": command.command_id,
                    "runtimeId": self._runtime_id,
                    "status": "cancelled_before_start" if existing.cancelled else "reserved",
                }
            for reservation in self._command_reservations.values():
                if reservation.idempotency_key == command.idempotency_key:
                    if reservation.fingerprint != fingerprint:
                        return {
                            "ok": False,
                            "reasonCode": "BROWSER_AGENT_IDEMPOTENCY_CONFLICT",
                            "runtimeId": self._runtime_id,
                        }
                    return {
                        "ok": False,
                        "reasonCode": "BROWSER_AGENT_COMMAND_ALREADY_RESERVED",
                        "runtimeId": self._runtime_id,
                    }
            self._command_reservations[command.command_id] = _CommandReservation(
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                runtime_id=command.runtime_id,
                fingerprint=fingerprint,
            )
            return {
                "ok": True,
                "commandId": command.command_id,
                "runtimeId": self._runtime_id,
                "status": "reserved",
            }

    def cancel_command(self, command_id: str, runtime_id: str) -> dict[str, Any]:
        with self._lock:
                if str(runtime_id or "") != self._runtime_id:
                    return {
                        "ok": False,
                        "reasonCode": "BROWSER_AGENT_RUNTIME_BINDING_MISMATCH",
                        "runtimeId": self._runtime_id,
                    }
                lease = self._active_lease
                normalized_command_id = str(command_id or "")
                if lease is None or lease.context.command_id != normalized_command_id:
                    reservation = self._command_reservations.get(normalized_command_id)
                    if reservation is not None and reservation.runtime_id == self._runtime_id:
                        reservation.cancelled = True
                        self._record_event(
                            "cancel_command",
                            "已取消等待执行的真实浏览器命令",
                            status="cancelled_before_start",
                        )
                        return {
                            "ok": True,
                            "commandId": normalized_command_id,
                            "runtimeId": self._runtime_id,
                            "status": "cancelled_before_start",
                        }
                    return {
                        "ok": False,
                        "reasonCode": "BROWSER_AGENT_COMMAND_NOT_ACTIVE",
                        "runtimeId": self._runtime_id,
                    }
                dispatch_inflight = lease.mutation_dispatch_inflight
                self._revoke_execution_locked(lease)
                self._status.update(
                    {
                        "status": (
                            "cancel_pending_dispatch_inflight"
                            if dispatch_inflight
                            else "cancelling"
                        ),
                        "healthy": False,
                        "active": True,
                        "currentStep": "正在取消真实浏览器命令",
                        "lastEventAt": _now(),
                        "message": (
                            "真实写入已开始派发，无法声称点击已取消；已撤销后续写入并等待收口"
                            if dispatch_inflight
                            else "命令已撤销，正在等待执行线程完整收口"
                        ),
                        "nextAction": "请等待当前命令结束后再继续",
                        "needsRestart": True,
                    }
                )
                self._record_event(
                    "cancel_command",
                    "正在取消真实浏览器命令",
                    status="cancelling",
                )
                return {
                    "ok": not dispatch_inflight,
                    "commandId": lease.context.command_id,
                    "runtimeId": self._runtime_id,
                    "status": self._status["status"],
                    **(
                        {"reasonCode": "BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT"}
                        if dispatch_inflight
                        else {}
                    ),
                }

    def reset(self, adapter: Any | None = None) -> dict[str, Any]:
        with self._lock:
            self._assert_no_running_execution_locked()
            rejection = self._control_rejection_reason_locked("reset")
            if rejection:
                raise RuntimeError(f"{rejection}: reset is not allowed from the current runtime state")
            reset_owner = self._claim_lifecycle_owner_locked(
                "reset",
                replace_actions={"shutdown", "takeover"},
            )
            self._status["sessionId"] = self._adapter_browser_session_id(self.adapter)
            previous = dict(self._status)
            old_adapter = self.adapter
            old_executor = self._executor
            already_stopped = previous.get("status") == "stopped"
            self._status.update(
                {
                    "status": "resetting",
                    "healthy": False,
                    "active": False,
                    "manualTakeover": False,
                    "currentStep": "正在重置真实浏览器执行器",
                    "lastEventAt": _now(),
                    "message": "正在关闭旧浏览器会话并创建新的执行所有者",
                    "nextAction": "请等待重置完成",
                    "needsRestart": True,
                }
            )

        close_ok, close_error = (True, None)
        if not already_stopped:
            close_ok, close_error = self._close_adapter_browser_session(
                adapter=old_adapter,
                direct=False,
                executor=old_executor,
            )
        self._shutdown_executor(old_executor)

        with self._lock:
            if self._lifecycle_owner != reset_owner:
                raise RuntimeError(
                    "BROWSER_AGENT_LIFECYCLE_OWNER_CHANGED: reset owner changed before commit"
                )
            if not close_ok:
                self._claim_lifecycle_owner_locked("shutdown", replace_actions={"reset"})
                self._set_shutdown_result_locked(ok=False, error=close_error)
                raise RuntimeError(f"BROWSER_AGENT_RESET_CLOSE_FAILED: {close_error or 'unknown close error'}")
            if adapter is not None:
                self.adapter = adapter
            self._runtime_id = uuid.uuid4().hex
            self._idempotency_records.clear()
            self._command_reservations.clear()
            self._takeover_snapshot = None
            self._shutdown_flight = None
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-browser-agent")
            self._release_lifecycle_owner_locked(reset_owner)
            self._status = {
                "sessionId": None,
                "status": "idle",
                "healthy": True,
                "active": False,
                "browserVisible": False,
                "currentStep": "待启动",
                "lastError": None,
                "lastWorkflowEvent": None,
                "lastEventAt": _now(),
                "manualTakeover": False,
                "hud": None,
                "message": None,
                "nextAction": None,
                "profile_dir": previous.get("profile_dir"),
                "needsRestart": False,
            }
            self.events.clear()
            return {
                "ok": True,
                "previousStatus": previous,
                "browserAgent": self._control_response_locked(ok=True),
            }

    def shutdown(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        start_close = False
        dispatch_inflight = False
        with self._lock:
                rejection = self._control_rejection_reason_locked("shutdown")
                if rejection:
                    return self._control_response_locked(
                        ok=False,
                        reason_code=rejection,
                    )
                flight = self._shutdown_flight
                if flight is not None and flight.result is not None:
                    return deepcopy(flight.result)
                if flight is not None:
                    completion_event = flight.completion_event
                    lease = self._active_lease
                    dispatch_inflight = bool(
                        lease is not None and lease.mutation_dispatch_inflight
                    )
                    if dispatch_inflight:
                        return self._control_response_locked(
                            ok=False,
                            reason_code="BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT",
                        )
                elif self._status.get("status") == "stopped" and self._active_lease is None:
                    return self._control_response_locked(ok=True)
                else:
                    self._claim_lifecycle_owner_locked("shutdown", replace_actions={"takeover"})
                    lease = self._active_lease
                    flight = _ShutdownFlight(close_started=lease is None)
                    self._shutdown_flight = flight
                    if lease is not None:
                        dispatch_inflight = lease.mutation_dispatch_inflight
                        self._revoke_execution_locked(lease)
                    self._status.update(
                        {
                            "status": (
                                "shutdown_pending_dispatch_inflight"
                                if dispatch_inflight
                                else "stopping"
                            ),
                            "healthy": False,
                            "active": lease is not None,
                            "manualTakeover": False,
                            "currentStep": "正在安全停止真实浏览器执行器",
                            "lastEventAt": _now(),
                            "message": "正在等待当前浏览器命令完整收口",
                            "nextAction": "若持续未完成，请重启后端并重新检查浏览器状态",
                            "needsRestart": True,
                        }
                    )
                    self._record_event("shutdown", "正在安全停止真实浏览器执行器", status="stopping")
                    completion_event = flight.completion_event
                    start_close = lease is None

                if dispatch_inflight:
                    return self._control_response_locked(
                        ok=False,
                        reason_code="BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT",
                    )

        if start_close:
            self._complete_shutdown_without_execution()
        completion_event.wait(timeout=max(0.0, float(timeout_seconds)))

        with self._lock:
            flight = self._shutdown_flight
            if flight is not None and flight.result is not None:
                return deepcopy(flight.result)
            if self._status.get("status") == "stopped" and self._active_lease is None:
                return self._control_response_locked(ok=True)
            return self._control_response_locked(
                ok=False,
                reason_code="BROWSER_AGENT_STOPPING",
            )

    def request_manual_takeover(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
                rejection = self._control_rejection_reason_locked("takeover")
                if rejection:
                    return self._control_response_locked(
                        ok=False,
                        reason_code=rejection,
                    )
                self._claim_lifecycle_owner_locked("takeover", renew_same_action=True)
                lease = self._active_lease
                if lease is None:
                    self._set_manual_takeover_locked()
                    return self._control_response_locked(ok=True)
                dispatch_inflight = lease.mutation_dispatch_inflight
                self._revoke_execution_locked(lease)
                self._status.update(
                    {
                        "status": (
                            "takeover_pending_dispatch_inflight"
                            if dispatch_inflight
                            else "takeover_pending"
                        ),
                        "healthy": False,
                        "manualTakeover": False,
                        "active": True,
                        "currentStep": "正在安全停止自动浏览器",
                        "lastEventAt": _now(),
                        "message": (
                            "真实写入已开始派发，无法声称点击已取消；已撤销后续写入并等待人工接管"
                            if dispatch_inflight
                            else "自动浏览器仍在收口，尚未进入人工接管"
                        ),
                        "nextAction": "请等待收口；若持续未完成，请重启真实浏览器执行器",
                        "needsRestart": True,
                    }
                )
                self._record_event("manual_takeover", "正在安全停止自动浏览器", status="takeover_pending")
                completion_event = lease.completion_event

                if dispatch_inflight:
                    return self._control_response_locked(
                        ok=False,
                        reason_code="BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT",
                    )

        completion_event.wait(timeout=max(0.0, float(timeout_seconds)))
        with self._lock:
            if self._status.get("status") == "manual_takeover" and self._active_lease is None:
                return self._control_response_locked(ok=True)
            return self._control_response_locked(
                ok=False,
                reason_code="BROWSER_AGENT_TAKEOVER_PENDING",
            )

    def release_manual_takeover(self) -> dict[str, Any]:
        return self.resume()

    def resume(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            rejection = self._control_rejection_reason_locked("resume")
            if rejection:
                return self._control_response_locked(
                    ok=False,
                    reason_code=rejection,
                )
            if self._active_lease is not None or self._status.get("status") == "takeover_pending":
                return self._control_response_locked(
                    ok=False,
                    reason_code="BROWSER_AGENT_TAKEOVER_PENDING",
                )
            runtime_status = str(self._status.get("status") or "")
            if runtime_status == "idle" and self._lifecycle_owner is None:
                return self._control_response_locked(ok=True)
            if runtime_status != "manual_takeover":
                return self._control_response_locked(
                    ok=False,
                    reason_code="BROWSER_AGENT_RESUME_NOT_ALLOWED",
                )
            takeover_owner = self._lifecycle_owner
            if takeover_owner is None or takeover_owner.action != "takeover":
                return self._control_response_locked(
                    ok=False,
                    reason_code="BROWSER_AGENT_LIFECYCLE_OWNER_MISMATCH",
                )
            snapshot = dict(self._takeover_snapshot or {})
            expected_session_id = str(snapshot.get("session_id") or "").strip()
            expected_page_url = str(snapshot.get("page_url") or "").strip()
            expected_page = str(snapshot.get("expected_page") or "").strip()
            if (
                not expected_session_id
                or not expected_page_url
                or expected_page not in {
                    "authenticated_dxm",
                    "data_acquisition",
                    "draft_box",
                    "editor",
                    "semi_managed",
                }
            ):
                return self._resume_reverify_failure_locked(
                    "BROWSER_AGENT_TAKEOVER_SNAPSHOT_INVALID",
                    "人工接管前的浏览器会话或页面快照不完整",
                )
            adapter = self.adapter
            checker = getattr(adapter, "check_login_state", None)
            if adapter is None or not callable(checker):
                return self._resume_reverify_failure_locked(
                    "BROWSER_AGENT_RESUME_REVERIFY_UNAVAILABLE",
                    "真实浏览器登录复核不可用",
                )
            executor = self._executor
            self._status.update(
                {
                    "healthy": False,
                    "currentStep": "正在复核人工接管后的浏览器",
                    "lastEventAt": _now(),
                    "message": "正在确认浏览器会话和页面没有漂移",
                    "nextAction": "请等待复核完成",
                }
            )

        try:
            probe_future = executor.submit(checker)
            probe = probe_future.result(timeout=max(0.0, float(timeout_seconds)))
            observed_session_id = self._adapter_browser_session_id(adapter)
            observed_page_url = str(
                probe.get("page_url") or probe.get("current_url") or ""
            ).strip() if isinstance(probe, Mapping) else ""
            probe_ok = isinstance(probe, Mapping) and probe.get("ok") is True
            page_ok = (
                _page_url_matches_identity(observed_page_url, expected_page)
                and _normalized_page_url(observed_page_url) == _normalized_page_url(expected_page_url)
            )
            session_ok = observed_session_id == expected_session_id
        except FutureTimeoutError:
            probe_ok = page_ok = session_ok = False
            observed_page_url = ""
            failure_code = "BROWSER_AGENT_RESUME_REVERIFY_TIMEOUT"
            failure_detail = "人工接管后的浏览器复核超时"
        except BaseException as exc:
            probe_ok = page_ok = session_ok = False
            observed_page_url = ""
            failure_code = "BROWSER_AGENT_RESUME_REVERIFY_FAILED"
            failure_detail = str(exc)
        else:
            if not probe_ok:
                failure_code = "BROWSER_AGENT_RESUME_LOGIN_NOT_CONFIRMED"
                failure_detail = "登录态复核未显式返回 ok=True"
            elif not session_ok:
                failure_code = "BROWSER_AGENT_RESUME_SESSION_MISMATCH"
                failure_detail = "人工接管期间浏览器会话已变化"
            elif not page_ok:
                failure_code = "BROWSER_AGENT_RESUME_PAGE_MISMATCH"
                failure_detail = f"人工接管期间页面已变化：{observed_page_url or 'missing page_url'}"
            else:
                failure_code = failure_detail = ""

        with self._lock:
            if self._lifecycle_owner != takeover_owner or self._status.get("status") != "manual_takeover":
                return self._control_response_locked(
                    ok=False,
                    reason_code="BROWSER_AGENT_LIFECYCLE_OWNER_CHANGED",
                )
            if failure_code:
                return self._resume_reverify_failure_locked(failure_code, failure_detail)
            self._release_lifecycle_owner_locked(takeover_owner)
            self._takeover_snapshot = None
            self._status.update(
                {
                    "status": "idle",
                    "manualTakeover": False,
                    "active": False,
                    "currentStep": "等待继续执行",
                    "lastEventAt": _now(),
                    "message": "真实浏览器已交还自动浏览器",
                    "nextAction": "继续执行或重新启动当前任务",
                    "needsRestart": False,
                }
            )
            self._record_event("resume", "等待继续执行", status="idle")
            return self._control_response_locked(ok=True)

    def run(self, command: BrowserAgentCommand, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        with self._lock:
            self._consume_command_reservation_locked(command)
            deadline_monotonic = self._validate_command_locked(command, timeout_seconds=timeout_seconds)
            replay = self._find_idempotent_replay_locked(command)
            if replay is not None:
                return replay
            self._assert_no_running_execution_locked()
            if self.adapter is None:
                raise RuntimeError("Browser Agent adapter is not configured")
            runtime_status = str(self._status.get("status") or "")
            if runtime_status == "stopped":
                raise RuntimeError(
                    "BROWSER_AGENT_STOPPED_REQUIRES_RESET: reset the browser runtime before running a command"
                )
            if runtime_status == "resetting":
                raise RuntimeError(
                    "BROWSER_AGENT_RESET_IN_PROGRESS: wait for reset to finish before running a command"
                )
            if runtime_status == "stopping":
                raise RuntimeError(
                    "BROWSER_AGENT_STOPPING: wait for shutdown to finish before running a command"
                )
            if self._status.get("manualTakeover"):
                raise RuntimeError("真实浏览器正在人工接管中；请先交还自动浏览器后再继续执行。")
            if self._lifecycle_intent in {"takeover", "shutdown", "reset"}:
                raise RuntimeError("真实浏览器执行器正在切换生命周期状态；请等待收口或重置后再继续执行。")
            profile_dir = _ensure_visible_workflow_profile_env()
            hud = self._build_hud(command, status="running")
            self._status.update(
                {
                    "status": "running",
                    "healthy": True,
                    "active": True,
                    "browserVisible": True,
                    "currentStep": hud.get("title") or command.step_label or command.state,
                    "lastError": None,
                    "lastEventAt": _now(),
                    "hud": hud,
                    "message": hud.get("human_action"),
                    "nextAction": hud.get("human_next"),
                    "profile_dir": profile_dir,
                }
            )
            self._record_event(command.action, str(hud.get("title") or command.step_label or command.state), status="running")
            adapter = self.adapter
            self._attach_workflow_event_listener(adapter)
            self._generation += 1
            execution_context = BrowserAgentExecutionContext(
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                runtime_id=command.runtime_id,
                browser_session_id=self._adapter_browser_session_id(adapter),
                expected_page=command.expected_page,
                generation=self._generation,
                deadline_monotonic=deadline_monotonic,
                cancel_epoch=self._cancel_epoch,
                task_id=command.task_id,
                job_id=command.job_id,
                state=command.state,
                mode=_mode_for_command(command),
            )
            lease = _ExecutionLease(execution_context, self._mutation_authorizer, adapter=adapter)
            artifacts = _prepare_action_artifacts(command, command_id=execution_context.command_id)
            self._idempotency_records[command.idempotency_key] = _IdempotencyRecord(
                fingerprint=_command_fingerprint(command),
            )
            try:
                future = self._executor.submit(self._execute_with_hud, adapter, command, hud, artifacts, lease)
            except BaseException:
                self._idempotency_records.pop(command.idempotency_key, None)
                self._status.update(
                    {
                        "status": "failed",
                        "healthy": False,
                        "active": False,
                        "lastError": "Browser Agent command submission failed",
                        "lastEventAt": _now(),
                    }
                )
                raise
            self._active_lease = lease
            self._active_future = future
            future.add_done_callback(lambda completed: self._mark_worker_finished(lease, completed))
        terminal_result: dict[str, Any] | None = None
        terminal_error: BaseException | None = None
        try:
            try:
                result = future.result(timeout=_remaining_deadline_seconds(execution_context.deadline_monotonic))
                with self._lock:
                    if lease.revoked:
                        revoke_reason = self._lifecycle_intent or "deadline_or_runtime_cancel"
                        raise RuntimeError(
                            f"BROWSER_AGENT_COMMAND_REVOKED: {revoke_reason}"
                        )
            except FutureTimeoutError as exc:
                self._revoke_execution(lease)
                last_event = self._latest_workflow_event(adapter)
                last_step = normalize_operator_copy(self._workflow_event_step(last_event) or command.step_label or command.state)
                failed_hud = self._build_hud(command, status="failed", error=f"{command.action} timed out；最后停在：{last_step}")
                with self._lock:
                    if self._execution_is_active_locked(lease):
                        self._status.update(
                            {
                                "status": "needs_restart",
                                "healthy": False,
                                "active": False,
                                "outcome": "UNKNOWN",
                                "currentStep": last_step,
                                "lastError": f"{command.action} timed out；最后停在：{last_step}",
                                "lastWorkflowEvent": last_event,
                                "lastEventAt": _now(),
                                "hud": failed_hud,
                                "message": failed_hud.get("human_action"),
                                "nextAction": failed_hud.get("human_next"),
                            }
                        )
                        self._record_event(command.action, last_step, status="timeout")
                raise TimeoutError(f"Browser Agent command timed out: {command.action}") from exc
            except Exception as exc:
                failed_hud = self._build_hud(command, status="failed", error=str(exc))
                with self._lock:
                    if self._execution_may_publish_status_locked(lease):
                        self._status.update(
                            {
                                "status": "failed",
                                "healthy": False,
                                "active": False,
                                "lastError": str(exc),
                                "lastEventAt": _now(),
                                "hud": failed_hud,
                                "message": failed_hud.get("human_action"),
                                "nextAction": failed_hud.get("human_next"),
                            }
                        )
                        self._record_event(command.action, normalize_operator_copy(command.step_label or command.state), status="failed", error=str(exc))
                raise

            if isinstance(result, dict) and result.get("ok") is not True:
                error_text = _result_error_text(result)
                failed_hud = self._build_hud(command, status="failed", error=error_text)
                with self._lock:
                    if self._execution_may_publish_status_locked(lease):
                        self._status.update(
                            {
                                "status": "failed",
                                "healthy": False,
                                "active": False,
                                "browserVisible": True,
                                "currentUrl": _action_result_page_url(result),
                                "pageTitle": _action_result_page_title(result),
                                "currentStep": failed_hud.get("title") or command.step_label or command.state,
                                "lastError": error_text,
                                "lastEventAt": _now(),
                                "hud": failed_hud,
                                "message": failed_hud.get("human_action"),
                                "nextAction": failed_hud.get("human_next"),
                            }
                        )
                        self._record_event(command.action, normalize_operator_copy(command.step_label or command.state), status="failed", error=error_text)
                terminal_result = result
                return result

            with self._lock:
                if self._execution_may_publish_status_locked(lease):
                    self._status["sessionId"] = self._adapter_browser_session_id(adapter)
                    done_hud = self._build_hud(command, status="success")
                    self._status.update(
                        {
                            "status": "idle",
                            "healthy": True,
                            "active": False,
                            "browserVisible": True,
                            "currentUrl": _action_result_page_url(result),
                            "pageTitle": _action_result_page_title(result),
                            "currentStep": done_hud.get("title") or command.step_label or command.state,
                            "lastError": None,
                            "lastEventAt": _now(),
                            "hud": done_hud,
                            "message": done_hud.get("human_action"),
                            "nextAction": done_hud.get("human_next"),
                        }
                    )
                    self._record_event(command.action, normalize_operator_copy(command.step_label or command.state), status="ok")
            terminal_result = result
            return result
        except BaseException as exc:
            terminal_error = exc
            raise
        finally:
            with self._lock:
                lease.terminal_result = deepcopy(terminal_result) if terminal_result is not None else None
                lease.terminal_error_type = type(terminal_error).__name__ if terminal_error is not None else None
                lease.terminal_error_message = str(terminal_error) if terminal_error is not None else None
            self._mark_outer_finalized(lease, future)

    def _validate_command_locked(
        self,
        command: BrowserAgentCommand,
        *,
        timeout_seconds: float | None,
    ) -> float:
        required = {
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "deadline": command.deadline,
            "expected_page": command.expected_page,
            "runtime_id": command.runtime_id,
        }
        missing = [key for key, value in required.items() if not str(value or "").strip()]
        if missing:
            raise RuntimeError(f"BROWSER_AGENT_COMMAND_INVALID: missing {', '.join(missing)}")
        if command.runtime_id != self._runtime_id:
            raise RuntimeError("BROWSER_AGENT_RUNTIME_BINDING_MISMATCH")
        state_contracts = ACTION_RESULT_CONTRACTS.get(command.action)
        action_contract = (
            state_contracts.get(command.state)
            if state_contracts is not None
            else None
        )
        if (
            action_contract is None
            or action_contract.expected_page != command.expected_page
        ):
            raise RuntimeError(
                "BROWSER_AGENT_COMMAND_CONTRACT_MISMATCH: "
                f"unsupported {command.state}/{command.action}/{command.expected_page} binding"
            )
        if command.expected_page not in {
            "authenticated_dxm",
            "data_acquisition",
            "draft_box",
            "editor",
            "semi_managed",
        }:
            raise RuntimeError("BROWSER_AGENT_EXPECTED_PAGE_INVALID")
        try:
            deadline = datetime.fromisoformat(command.deadline.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("BROWSER_AGENT_DEADLINE_INVALID") from exc
        if deadline.tzinfo is None:
            raise RuntimeError("BROWSER_AGENT_DEADLINE_NOT_ABSOLUTE")
        remaining = (deadline.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("BROWSER_AGENT_DEADLINE_EXPIRED")
        if timeout_seconds is not None:
            remaining = min(remaining, max(0.0, float(timeout_seconds)))
        if remaining <= 0:
            raise TimeoutError("BROWSER_AGENT_DEADLINE_EXPIRED")
        return time.monotonic() + remaining

    def _consume_command_reservation_locked(self, command: BrowserAgentCommand) -> None:
        reservation = self._command_reservations.pop(command.command_id, None)
        if reservation is None:
            return
        if (
            reservation.runtime_id != command.runtime_id
            or reservation.idempotency_key != command.idempotency_key
            or reservation.fingerprint != _command_fingerprint(command)
        ):
            raise RuntimeError("BROWSER_AGENT_RESERVATION_CONFLICT")
        if reservation.cancelled:
            self._record_event(
                "cancel_command",
                "已释放取消的真实浏览器命令",
                status="cancelled_before_start",
            )
            raise RuntimeError("BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START")

    def _find_idempotent_replay_locked(
        self,
        command: BrowserAgentCommand,
    ) -> dict[str, Any] | None:
        fingerprint = _command_fingerprint(command)
        record = self._idempotency_records.get(command.idempotency_key)
        if record is None:
            return None
        self._idempotency_records.move_to_end(command.idempotency_key)
        if record.fingerprint != fingerprint:
            raise RuntimeError("BROWSER_AGENT_IDEMPOTENCY_CONFLICT")
        if not record.completed:
            raise RuntimeError("BROWSER_AGENT_COMMAND_IN_PROGRESS")
        if record.error_type:
            error_class = TimeoutError if record.error_type == "TimeoutError" else RuntimeError
            raise error_class(record.error_message or "BROWSER_AGENT_COMMAND_FAILED")
        return deepcopy(record.result or {})

    def _complete_idempotent_lease_locked(self, lease: _ExecutionLease) -> None:
        key = lease.context.idempotency_key
        record = self._idempotency_records.get(key)
        if record is None:
            return
        record.result = deepcopy(lease.terminal_result) if lease.terminal_result is not None else None
        record.error_type = lease.terminal_error_type
        record.error_message = lease.terminal_error_message
        record.completed = True
        self._idempotency_records.move_to_end(key)
        while len(self._idempotency_records) > self._idempotency_cache_limit:
            oldest_key, oldest = next(iter(self._idempotency_records.items()))
            if not oldest.completed:
                break
            self._idempotency_records.pop(oldest_key, None)

    def _build_hud(self, command: BrowserAgentCommand, *, status: str, error: str | None = None) -> dict[str, Any]:
        return build_browser_hud(
            {
                "task_name": _task_name_for_state(command.state),
                "step": command.state,
                "status": status,
                "error": error,
                "store_name": command.params.get("store_name"),
                "title": command.step_label if status == "running" and command.step_label else None,
            }
        )

    def _execute_with_hud(
        self,
        adapter: Any,
        command: BrowserAgentCommand,
        hud: dict[str, Any],
        artifacts: dict[str, Any],
        lease: _ExecutionLease,
    ) -> dict[str, Any]:
        previous_trace_file = os.environ.get("DXM_WORKFLOW_TRACE_FILE")
        os.environ["DXM_WORKFLOW_TRACE_FILE"] = str(artifacts["trace_file"])
        command_context = {
            **dict(lease.context.as_mapping()),
            "command_action": command.action,
            "target_hash": getattr(command, "target_hash", None),
            "mutation_target": dict(command.params),
        }
        mutation_setter = getattr(adapter, "set_mutation_authorizer", None)
        evidence_setter = getattr(adapter, "set_execution_evidence_context", None)
        if callable(mutation_setter):
            mutation_setter(
                lambda mutation_context, operation: self._authorize_mutation(
                    lease,
                    command,
                    mutation_context,
                    operation,
                ),
                command_context,
            )
        if callable(evidence_setter):
            evidence_setter(command_context)
        updater = getattr(adapter, "update_live_hud", None)
        defer_page_hud = _defer_page_hud_until_after_action(command)
        if callable(updater) and not defer_page_hud:
            updater(hud)
        try:
            raw_result = execute_browser_agent_action(adapter, command.action, command.params)
            with self._lock:
                if not self._execution_result_may_publish_locked(lease):
                    raise RuntimeError(
                        "BROWSER_AGENT_LATE_RESULT_IGNORED: command lease was revoked or superseded"
                    )
            result = self._build_action_result_envelope(
                adapter,
                command,
                lease.context,
                raw_result,
            )
            _write_action_result(
                artifacts["result_file"],
                {
                    "ok": True,
                    "result": result,
                    "transport": {
                        "command_id": command.command_id,
                        "idempotency_key": command.idempotency_key,
                        "runtime_id": command.runtime_id,
                        "workflow_trace_file": str(artifacts["trace_file"]),
                        "browser_agent_request_file": str(artifacts["request_file"]),
                        "browser_agent_result_file": str(artifacts["result_file"]),
                    },
                },
            )
            if isinstance(result, dict) and result.get("ok") is not True:
                return result
            if callable(updater) and not defer_page_hud:
                updater(self._build_hud(command, status="success"))
            return result
        except Exception as exc:
            _write_action_result(
                artifacts["result_file"],
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                    "workflow_trace_file": str(artifacts["trace_file"]),
                },
            )
            raise
        finally:
            mutation_clearer = getattr(adapter, "clear_mutation_authorizer", None)
            if callable(mutation_clearer):
                mutation_clearer()
            evidence_clearer = getattr(adapter, "clear_execution_evidence_context", None)
            if callable(evidence_clearer):
                evidence_clearer()
            if previous_trace_file is None:
                os.environ.pop("DXM_WORKFLOW_TRACE_FILE", None)
            else:
                os.environ["DXM_WORKFLOW_TRACE_FILE"] = previous_trace_file

    def _build_action_result_envelope(
        self,
        adapter: Any,
        command: BrowserAgentCommand,
        context: BrowserAgentExecutionContext,
        raw_result: Any,
    ) -> dict[str, Any]:
        raw, contract_facts = _require_raw_action_result_contract(raw_result)
        _validate_reported_action_result_identity(raw, command, context)
        if command.action in _FROZEN_TARGET_REQUIRED_ACTIONS:
            command_store = command.params.get("store_name")
            if not isinstance(command_store, str) or command_store != " ".join(command_store.split()) or not command_store:
                _raise_action_result_contract_failure(
                    "frozen target command requires canonical store_name"
                )
            command_target = canonical_frozen_target_identity(
                command.params.get("target_identity"),
                store_name=command_store,
            )
            before_values = contract_facts.get("before_values")
            if not isinstance(before_values, Mapping):
                _raise_action_result_contract_failure(
                    "frozen target result requires structured before_values"
                )
            before_store = before_values.get("store_name")
            before_target = before_values.get("target_identity")
            if before_store != command_store or before_target != command_target:
                _raise_action_result_contract_failure(
                    "contract_facts.before_values target_identity/store_name do not match the command"
                )
            if raw.get("ok") is True and (
                raw.get("store_name") != command_store
                or raw.get("target_identity") != command_target
            ):
                _raise_action_result_contract_failure(
                    "successful action result target_identity/store_name do not match the command"
                )

        cached_session_id = context.browser_session_id
        current_session_id = self._adapter_browser_session_id(adapter)
        if current_session_id != cached_session_id:
            _raise_action_result_contract_failure(
                "browser session changed during BrowserAgent command execution"
            )
        if raw["ok"] is True and not cached_session_id:
            _raise_action_result_contract_failure(
                "successful action result requires a cached browser_session_id"
            )

        page_url = _reported_action_result_page_url(raw)
        if raw["ok"] is True:
            if not _page_url_matches_identity(page_url, command.expected_page):
                _raise_action_result_contract_failure(
                    f"expected exact {command.expected_page} DXM page URL, "
                    f"observed {page_url or 'missing page URL'}"
                )
            page_kind: str | None = command.expected_page
        elif page_url:
            page_kind = _controlled_page_identity(page_url)
            if page_kind is None:
                _raise_action_result_contract_failure(
                    "failed action result reported an uncontrolled page URL"
                )
        else:
            page_kind = None

        evidence_refs = _validated_action_result_evidence_refs(
            raw,
            state=command.state,
        )
        envelope = {
            "schema_version": ACTION_RESULT_SCHEMA_VERSION,
            "ok": raw["ok"],
            "action": command.action,
            "attempted_state": command.state,
            "before_values": contract_facts["before_values"],
            "after_values": contract_facts["after_values"],
            "postconditions": contract_facts["postconditions"],
            "evidence": {
                "observations": contract_facts["evidence_observations"],
                "refs": evidence_refs,
            },
            "page_identity": {
                "kind": page_kind,
                "url": page_url or None,
                "runtime_id": context.runtime_id,
                "browser_session_id": cached_session_id,
            },
            "failure_code": contract_facts["failure_code"],
            "recoverability": contract_facts["recoverability"],
        }
        try:
            return validate_action_result_envelope(
                envelope,
                expected_state=command.state,
                expected_action=command.action,
                expected_runtime_id=context.runtime_id,
                expected_browser_session_id=cached_session_id,
            )
        except ActionResultContractError as exc:
            _raise_action_result_contract_failure(
                f"{exc.reason_code}: {exc}"
            )

    def _authorize_mutation(
        self,
        lease: _ExecutionLease,
        command: BrowserAgentCommand,
        mutation_context: Any,
        operation: Any,
    ) -> dict[str, Any]:
        context = lease.context
        if not callable(operation):
            return {
                "ok": False,
                "executed": False,
                "reason": "browser_agent_mutation_operation_invalid",
                "command_id": context.command_id,
            }
        authorizer = lease.authorizer
        if not callable(authorizer):
            return {
                "ok": False,
                "executed": False,
                "reason": "browser_agent_mutation_authorizer_missing",
                "command_id": context.command_id,
            }
        pre_dispatch_guard = (
            mutation_context.get("_pre_dispatch_guard")
            if isinstance(mutation_context, Mapping)
            else None
        )
        public_mutation_context = (
            {
                key: value
                for key, value in mutation_context.items()
                if key != "_pre_dispatch_guard"
            }
            if isinstance(mutation_context, Mapping)
            else mutation_context
        )
        with self._mutation_dispatch_gate:
            with self._lock:
                initial_rejection = self._mutation_dispatch_rejection_locked(
                    lease,
                    public_mutation_context,
                )
        if initial_rejection is not None:
            return {
                **initial_rejection,
                "ok": False,
                "executed": False,
            }
        bound_identity, identity_rejection = self._bound_mutation_identity(
            lease,
            command,
        )
        if identity_rejection is not None:
            return {
                **identity_rejection,
                "ok": False,
                "executed": False,
                "command_id": context.command_id,
            }

        if (
            getattr(lease.adapter, "requires_persistent_browser_agent", False) is True
            and self._mutation_ledger is None
        ):
            return {
                "ok": False,
                "executed": False,
                "reason": "browser_agent_mutation_ledger_missing",
                "reason_code": "MUTATION_LEDGER_REQUIRED",
                "command_id": context.command_id,
            }
        mutation_action = str(
            public_mutation_context.get("mutation_action")
            if isinstance(public_mutation_context, Mapping)
            else ""
        ).strip()
        ledger = self._mutation_ledger
        ledger_started = False
        ledger_entry: dict[str, Any] | None = None
        final_identity: dict[str, Any] | None = None
        with self._mutation_dispatch_gate:
            final_identity, identity_rejection = self._bound_mutation_identity(
                lease,
                command,
                expected_identity=bound_identity,
            )
            if identity_rejection is not None:
                return {
                    **identity_rejection,
                    "ok": False,
                    "executed": False,
                    "zero_click_proven": True,
                    "outcome": "CANCELLED_BEFORE_DISPATCH",
                    "command_id": context.command_id,
                }
            if callable(pre_dispatch_guard):
                try:
                    preflight_result = pre_dispatch_guard()
                except BaseException as exc:
                    return {
                        "ok": False,
                        "executed": False,
                        "zero_click_proven": True,
                        "outcome": "CANCELLED_BEFORE_DISPATCH",
                        "reason": "browser_agent_mutation_final_preflight_failed",
                        "reason_code": str(
                            getattr(exc, "reason_code", None)
                            or getattr(exc, "error_code", None)
                            or "MUTATION_TARGET_DRIFT"
                        ),
                        "detail": str(exc),
                        "command_id": context.command_id,
                    }
                preflight_ok = preflight_result is True or (
                    isinstance(preflight_result, Mapping)
                    and preflight_result.get("ok") is True
                )
                if not preflight_ok:
                    return {
                        "ok": False,
                        "executed": False,
                        "zero_click_proven": True,
                        "outcome": "CANCELLED_BEFORE_DISPATCH",
                        "reason": "browser_agent_mutation_final_preflight_rejected",
                        "reason_code": "MUTATION_TARGET_DRIFT",
                        "detail": (
                            str(preflight_result.get("reason") or "final target readback rejected")
                            if isinstance(preflight_result, Mapping)
                            else "final target readback rejected"
                        ),
                        "command_id": context.command_id,
                    }
            with self._lock:
                rejection = self._mutation_dispatch_rejection_locked(
                    lease,
                    public_mutation_context,
                )
                if rejection is not None:
                    return {
                        **rejection,
                        "ok": False,
                        "executed": False,
                    }
                authorization = authorizer(command, public_mutation_context)
                if not isinstance(authorization, Mapping) or authorization.get("ok") is not True:
                    diagnostics = dict(authorization) if isinstance(authorization, Mapping) else {}
                    return {
                        **diagnostics,
                        "ok": False,
                        "executed": False,
                        "reason": diagnostics.get("reason") or "browser_agent_mutation_not_authorized",
                        "command_id": context.command_id,
                    }
                diagnostics = dict(authorization)
                if ledger is not None:
                    try:
                        ledger_decision = ledger.begin_dispatch(
                            command,
                            mutation_action,
                            identity=dict(final_identity or bound_identity or {}),
                        )
                    except Exception as exc:
                        return {
                            **diagnostics,
                            "ok": False,
                            "executed": False,
                            "reason": "browser_agent_mutation_ledger_unavailable",
                            "reason_code": "MUTATION_LEDGER_UNAVAILABLE",
                            "detail": str(exc),
                            "command_id": context.command_id,
                        }
                    if getattr(ledger_decision, "ok", False) is not True:
                        reason_code = str(
                            getattr(ledger_decision, "reason_code", None)
                            or "MUTATION_LEDGER_DISPATCH_REJECTED"
                        )
                        return {
                            **diagnostics,
                            "ok": False,
                            "executed": False,
                            "reason": "browser_agent_mutation_ledger_rejected",
                            "reason_code": reason_code,
                            "command_id": context.command_id,
                        }
                    ledger_started = True
                    entry = getattr(ledger_decision, "entry", None)
                    ledger_entry = dict(entry) if isinstance(entry, Mapping) else None
                lease.mutation_dispatch_inflight = True
                lease.mutation_dispatch_action = mutation_action or None
                lease.mutation_bound_identity = dict(final_identity or bound_identity or {})
        try:
            operation_result = operation()
        except BaseException as exc:
            if ledger_started:
                try:
                    ledger.mark_unknown(
                        command,
                        mutation_action,
                        {
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
            raise
        else:
            dispatch_confirmed = operation_result is True or (
                isinstance(operation_result, Mapping)
                and (
                    operation_result.get("dispatched") is True
                    if "dispatched" in operation_result
                    else operation_result.get("ok") is True
                )
            )
            if not dispatch_confirmed:
                if ledger_started:
                    try:
                        ledger.mark_unknown(
                            command,
                            mutation_action,
                            {
                                "phase": "operation_result",
                                "reason_code": "MUTATION_DISPATCH_NOT_CONFIRMED",
                                "operation_result": operation_result,
                            },
                        )
                    except Exception:
                        pass
                raise RuntimeError(
                    "MUTATION_OUTCOME_UNKNOWN: mutation operation did not prove dispatch"
                )
            if ledger_started:
                try:
                    dispatch_decision = ledger.mark_dispatched(
                        command,
                        mutation_action,
                        operation_result,
                    )
                except Exception as exc:
                    try:
                        ledger.mark_unknown(
                            command,
                            mutation_action,
                            {
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                                "phase": "mark_dispatched",
                            },
                        )
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"MUTATION_LEDGER_COMMIT_FAILED: {exc}"
                    ) from exc
                if getattr(dispatch_decision, "ok", False) is not True:
                    reason_code = str(
                        getattr(dispatch_decision, "reason_code", None)
                        or "MUTATION_LEDGER_COMMIT_REJECTED"
                    )
                    try:
                        ledger.mark_unknown(
                            command,
                            mutation_action,
                            {"reason_code": reason_code, "phase": "mark_dispatched"},
                        )
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"MUTATION_LEDGER_COMMIT_FAILED: {reason_code}"
                    )
        finally:
            with self._lock:
                lease.mutation_dispatch_inflight = False
                lease.mutation_dispatch_action = None
        return {
            **diagnostics,
            "ok": True,
            "executed": True,
            "operation_result": operation_result,
            "command_id": context.command_id,
            **(
                {
                    "mutation_id": ledger_entry.get("mutation_id"),
                    "mutation_status": "DISPATCHED",
                }
                if ledger_entry is not None
                else {}
            ),
        }

    def _bound_mutation_identity(
        self,
        lease: _ExecutionLease,
        command: BrowserAgentCommand,
        *,
        expected_identity: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Read and validate live page identity without holding runtime locks.

        The first read binds the exact URL for this dispatch attempt. The final
        read happens before the JIT grant is consumed and before the ledger can
        enter DISPATCHING; it must match byte-for-byte after URL normalization,
        including session generation and target hash.
        """

        identity = self._adapter_current_mutation_identity(lease.adapter, command)
        if not isinstance(identity, Mapping):
            return None, {"reason": "browser_agent_mutation_identity_unavailable"}
        browser_session_id = str(identity.get("browser_session_id") or "").strip() or None
        page_url = _normalized_page_url(str(identity.get("page_url") or "").strip())
        page_kind = str(identity.get("page_kind") or "").strip()
        target_hash = str(identity.get("target_hash") or "").strip().casefold() or None
        normalized = {
            "browser_session_id": browser_session_id,
            "page_url": page_url,
            "page_kind": page_kind,
            "target_hash": target_hash,
        }
        strict_identity = getattr(lease.adapter, "requires_persistent_browser_agent", False) is True
        command_target_hash = str(getattr(command, "target_hash", None) or "").strip().casefold() or None
        if browser_session_id != lease.context.browser_session_id:
            return None, {"reason": "browser_agent_mutation_session_drift"}
        if not page_url or not _page_url_matches_identity(page_url, command.expected_page):
            return None, {"reason": "browser_agent_mutation_page_url_drift"}
        if page_kind != command.expected_page:
            return None, {"reason": "browser_agent_mutation_page_kind_drift"}
        if strict_identity and not command_target_hash:
            return None, {"reason": "browser_agent_mutation_target_hash_missing"}
        if command_target_hash is not None and target_hash != command_target_hash:
            return None, {"reason": "browser_agent_mutation_target_drift"}
        if expected_identity is not None and normalized != dict(expected_identity):
            if normalized["browser_session_id"] != expected_identity.get("browser_session_id"):
                reason = "browser_agent_mutation_session_drift"
            elif normalized["page_url"] != expected_identity.get("page_url"):
                reason = "browser_agent_mutation_page_url_drift"
            elif normalized["page_kind"] != expected_identity.get("page_kind"):
                reason = "browser_agent_mutation_page_kind_drift"
            else:
                reason = "browser_agent_mutation_target_drift"
            return None, {"reason": reason}
        return normalized, None

    def _adapter_current_mutation_identity(
        self,
        adapter: Any | None,
        command: BrowserAgentCommand,
    ) -> dict[str, Any] | None:
        getter = getattr(adapter, "current_mutation_identity", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                return None
            return dict(value) if isinstance(value, Mapping) else None
        if getattr(adapter, "requires_persistent_browser_agent", False) is True:
            return None
        # Compatibility for small unit-test adapters. Real DXM adapters declare
        # ``requires_persistent_browser_agent`` and must expose a live identity.
        default_urls = {
            "data_acquisition": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "editor": "https://www.dianxiaomi.com/web/smt/edit?id=test",
            "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
            "authenticated_dxm": "https://www.dianxiaomi.com/web/home",
        }
        return {
            "browser_session_id": self._adapter_browser_session_id(adapter),
            "page_url": default_urls.get(command.expected_page),
            "page_kind": command.expected_page,
            "target_hash": getattr(command, "target_hash", None),
        }

    def _mutation_dispatch_rejection_locked(
        self,
        lease: _ExecutionLease,
        mutation_context: Any,
    ) -> dict[str, Any] | None:
        context = lease.context
        deadline_expired = (
            context.deadline_monotonic is not None
            and time.monotonic() >= context.deadline_monotonic
        )
        if deadline_expired and not lease.revoked:
            self._revoke_execution_locked(lease)
        if (
            lease.revoked
            or context.cancel_epoch != self._cancel_epoch
            or self._lifecycle_intent is not None
        ):
            return {
                "reason": "browser_agent_command_revoked",
                "command_id": context.command_id,
            }
        if self._active_lease is not lease:
            return {
                "reason": "browser_agent_command_not_active",
                "command_id": context.command_id,
            }
        if not isinstance(mutation_context, Mapping):
            return {
                "reason": "browser_agent_command_context_invalid",
                "command_id": context.command_id,
            }
        mutation_action = str(mutation_context.get("mutation_action") or "").strip()
        allowed_mutations = _MUTATION_ACTION_SEQUENCE_BY_STATE.get(context.state, {})
        if mutation_action not in allowed_mutations:
            return {
                "reason": "browser_agent_mutation_action_not_allowed",
                "command_id": context.command_id,
            }
        expected = context.as_mapping()
        for key, value in expected.items():
            if mutation_context.get(key) != value:
                return {
                    "reason": "browser_agent_command_context_mismatch",
                    "command_id": context.command_id,
                }
        return None

    def _revoke_execution(self, lease: _ExecutionLease) -> None:
        with self._lock:
            self._revoke_execution_locked(lease)

    def _revoke_execution_locked(self, lease: _ExecutionLease) -> None:
        if lease.revoked:
            return
        lease.revoked = True
        self._cancel_epoch += 1

    def _execution_may_publish_status_locked(self, lease: _ExecutionLease) -> bool:
        return bool(
            self._execution_is_active_locked(lease)
            and self._execution_result_may_publish_locked(lease)
        )

    def _execution_is_active_locked(self, lease: _ExecutionLease) -> bool:
        return self._active_lease is lease

    def _execution_result_may_publish_locked(self, lease: _ExecutionLease) -> bool:
        return bool(
            lease.revoked is False
            and lease.context.cancel_epoch == self._cancel_epoch
            and self._lifecycle_intent is None
        )

    def _mark_worker_finished(self, lease: _ExecutionLease, future: Any) -> None:
        lifecycle_action = None
        with self._lock:
            if self._active_lease is not lease or self._active_future is not future:
                return
            lease.worker_finished = True
            lifecycle_action = self._begin_execution_terminalization_locked(lease, future)
        if lifecycle_action == "shutdown":
            self._complete_shutdown_after_execution(lease, close_directly=True)

    def _mark_outer_finalized(self, lease: _ExecutionLease, future: Any) -> None:
        lifecycle_action = None
        with self._lock:
            if self._active_lease is not lease or self._active_future is not future:
                return
            lease.outer_finalized = True
            lifecycle_action = self._begin_execution_terminalization_locked(lease, future)
        if lifecycle_action == "shutdown":
            self._complete_shutdown_after_execution(lease, close_directly=False)

    def _begin_execution_terminalization_locked(self, lease: _ExecutionLease, future: Any) -> str | None:
        if lease.terminalizing or not lease.worker_finished or not lease.outer_finalized:
            return None
        lease.terminalizing = True
        if self._lifecycle_intent == "shutdown":
            flight = self._shutdown_flight
            if flight is not None:
                flight.close_started = True
            return "shutdown"
        if self._active_lease is lease and self._active_future is future:
            self._active_lease = None
            self._active_future = None
        if self._lifecycle_intent == "takeover":
            self._set_manual_takeover_locked()
        self._complete_idempotent_lease_locked(lease)
        lease.completion_event.set()
        return None

    def _complete_shutdown_after_execution(self, lease: _ExecutionLease, *, close_directly: bool) -> None:
        close_ok, close_error = self._close_adapter_browser_session(
            adapter=lease.adapter,
            direct=close_directly,
        )
        self._shutdown_executor()
        with self._lock:
            if self._active_lease is lease:
                self._active_lease = None
                self._active_future = None
            self._set_shutdown_result_locked(ok=close_ok, error=close_error)
            self._complete_idempotent_lease_locked(lease)
            lease.completion_event.set()

    def _complete_shutdown_without_execution(self) -> None:
        close_ok, close_error = self._close_adapter_browser_session(adapter=self.adapter, direct=False)
        self._shutdown_executor()
        with self._lock:
            self._set_shutdown_result_locked(ok=close_ok, error=close_error)

    def _set_shutdown_result_locked(self, *, ok: bool, error: str | None) -> None:
        if ok:
            self._status.update(
                {
                    "status": "stopped",
                    "healthy": True,
                    "active": False,
                    "browserVisible": False,
                    "manualTakeover": False,
                    "currentStep": "已停止",
                    "lastError": None,
                    "lastEventAt": _now(),
                    "message": "真实浏览器执行器已停止",
                    "nextAction": "需要继续时请重置并重新打开真实浏览器执行器",
                    "needsRestart": False,
                }
            )
            self._record_event("shutdown", "真实浏览器执行器已停止", status="stopped")
            self._complete_shutdown_flight_locked(ok=True)
            return
        self._status.update(
            {
                "status": "stopping",
                "healthy": False,
                "active": False,
                "manualTakeover": False,
                "currentStep": "真实浏览器仍需重启",
                "lastError": error or "关闭真实浏览器失败",
                "lastEventAt": _now(),
                "message": "真实浏览器未能安全关闭",
                "nextAction": "请重启后端并重新检查浏览器状态",
                "needsRestart": True,
            }
        )
        self._complete_shutdown_flight_locked(ok=False)

    def _complete_shutdown_flight_locked(self, *, ok: bool) -> None:
        flight = self._shutdown_flight
        if flight is None or flight.result is not None:
            return
        flight.result = self._control_response_locked(
            ok=ok,
            reason_code=None if ok else "BROWSER_AGENT_STOPPING",
        )
        flight.completion_event.set()

    def _set_manual_takeover_locked(self) -> None:
        page_url = str(self._status.get("currentUrl") or "").strip()
        self._takeover_snapshot = {
            "session_id": self._adapter_browser_session_id(self.adapter),
            "page_url": page_url,
            "expected_page": _controlled_page_identity(page_url),
            "runtime_id": self._runtime_id,
        }
        self._status.update(
            {
                "status": "manual_takeover",
                "healthy": False,
                "manualTakeover": True,
                "active": True,
                "currentStep": "人工接管中",
                "lastEventAt": _now(),
                "message": "请在真实浏览器里检查或修正当前页面",
                "nextAction": "处理完成后在控制台交还自动浏览器",
                "needsRestart": False,
            }
        )
        self._record_event("manual_takeover", "人工接管中", status="manual_takeover")

    def _resume_reverify_failure_locked(self, reason_code: str, detail: str) -> dict[str, Any]:
        self._status.update(
            {
                "status": "manual_takeover",
                "healthy": False,
                "manualTakeover": True,
                "active": True,
                "currentStep": "人工接管复核未通过",
                "lastError": detail,
                "lastEventAt": _now(),
                "message": "浏览器会话或页面未通过安全复核",
                "nextAction": "请保持人工接管并重置真实浏览器执行器",
                "needsRestart": True,
            }
        )
        self._record_event("resume", "人工接管复核未通过", status="failed", error=detail)
        return self._control_response_locked(ok=False, reason_code=reason_code)

    def _control_response_locked(self, *, ok: bool, reason_code: str | None = None) -> dict[str, Any]:
        response = dict(self._status)
        response["runtimeId"] = self._runtime_id
        response["events"] = list(self.events[-20:])
        response["ok"] = ok
        if reason_code:
            response["reasonCode"] = reason_code
        return response

    def _control_rejection_reason_locked(self, action: str) -> str | None:
        runtime_status = str(self._status.get("status") or "")
        rejection = _CONTROL_STATE_REJECTIONS.get(action, {}).get(runtime_status)
        if rejection:
            return rejection
        owner = self._lifecycle_owner
        if owner is None or owner.action == action:
            return None
        if action == "resume" and owner.action == "takeover":
            return None
        allowed_replacements = {
            "shutdown": {"takeover"},
            "reset": {"shutdown", "takeover"},
        }
        if owner.action in allowed_replacements.get(action, set()):
            return None
        return "BROWSER_AGENT_LIFECYCLE_BUSY"

    def _claim_lifecycle_owner_locked(
        self,
        action: str,
        *,
        replace_actions: set[str] | None = None,
        renew_same_action: bool = False,
    ) -> _LifecycleOwner:
        current = self._lifecycle_owner
        if current is not None and current.action == action and not renew_same_action:
            return current
        replace_actions = replace_actions or set()
        if (
            current is not None
            and current.action != action
            and current.action not in replace_actions
        ):
            raise RuntimeError(
                f"BROWSER_AGENT_LIFECYCLE_BUSY: {current.action} owns lifecycle token {current.token}"
            )
        self._lifecycle_epoch += 1
        owner = _LifecycleOwner(action=action, token=self._lifecycle_epoch)
        self._lifecycle_owner = owner
        self._lifecycle_intent = action
        return owner

    def _release_lifecycle_owner_locked(self, owner: _LifecycleOwner) -> None:
        if self._lifecycle_owner != owner:
            raise RuntimeError(
                "BROWSER_AGENT_LIFECYCLE_OWNER_CHANGED: lifecycle owner changed before release"
            )
        self._lifecycle_owner = None
        self._lifecycle_intent = None

    def _assert_no_running_execution_locked(self) -> None:
        future = self._active_future
        if future is None:
            return
        raise RuntimeError(
            "BROWSER_AGENT_COMMAND_STILL_RUNNING: "
            "the previous browser command has not fully finalized; reset and new commands are refused"
        )

    def _adapter_browser_session_id(self, adapter: Any | None) -> str | None:
        if adapter is None:
            return None
        getter = getattr(adapter, "browser_session_id", None)
        if not callable(getter):
            login_flow = getattr(adapter, "login_flow", None)
            getter = getattr(login_flow, "browser_session_id", None)
        if not callable(getter):
            return None
        try:
            value = getter()
        except Exception:
            return None
        text = str(value or "").strip()
        return text or None

    def _record_event(self, action: str, step: str | None, *, status: str, error: str | None = None) -> None:
        self.events.append(
            {
                "action": action,
                "step": step,
                "status": status,
                "error": error,
                "timestamp": _now(),
            }
        )
        del self.events[:-50]

    def _attach_workflow_event_listener(self, adapter: Any) -> None:
        setter = getattr(adapter, "set_workflow_event_listener", None)
        if not callable(setter):
            return

        def _on_workflow_event(record: dict[str, Any]) -> None:
            event = dict(record) if isinstance(record, dict) else {"event": str(record)}
            step = normalize_operator_copy(self._workflow_event_step(event) or "执行中")
            with self._lock:
                if self._status.get("status") != "running":
                    return
                self._status.update(
                    {
                        "currentStep": step,
                        "lastWorkflowEvent": event,
                        "lastEventAt": _now(),
                    }
                )
                self._record_event("workflow_trace", step, status="running")

        try:
            setter(_on_workflow_event)
        except Exception:
            return

    def _latest_workflow_event(self, adapter: Any) -> dict[str, Any] | None:
        status_event = self._status.get("lastWorkflowEvent")
        if isinstance(status_event, dict):
            return dict(status_event)
        recent = getattr(adapter, "recent_workflow_events", None)
        if callable(recent):
            try:
                events = recent()
            except Exception:
                events = []
            if isinstance(events, list) and events:
                last = events[-1]
                if isinstance(last, dict):
                    return dict(last)
        return None

    def _workflow_event_step(self, event: dict[str, Any] | None) -> str | None:
        if not isinstance(event, dict):
            return None
        for key in ("human_step", "step", "label", "event"):
            value = str(event.get(key) or "").strip()
            if value:
                return value
        return None

    def _shutdown_executor(self, executor: ThreadPoolExecutor | None = None) -> None:
        target = self._executor if executor is None else executor
        try:
            target.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            target.shutdown(wait=False)

    def _close_adapter_browser_session(
        self,
        *,
        adapter: Any | None = None,
        direct: bool = False,
        executor: ThreadPoolExecutor | None = None,
    ) -> tuple[bool, str | None]:
        adapter = self.adapter if adapter is None else adapter
        if adapter is None:
            return True, None
        closer = getattr(adapter, "close_browser_session", None)
        if not callable(closer):
            login_flow = getattr(adapter, "login_flow", None)
            closer = getattr(login_flow, "_close_browser_session", None)
        if not callable(closer):
            return True, None
        try:
            if direct:
                closer()
            else:
                target_executor = self._executor if executor is None else executor
                future = target_executor.submit(closer)
                future.result(timeout=5)
            return True, None
        except Exception as exc:
            with self._lock:
                self._record_event("shutdown", "关闭真实浏览器失败", status="failed", error=str(exc))
            return False, str(exc)


def execute_browser_agent_action(adapter: Any, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params if isinstance(params, dict) else {}
    raw_target_identity = params.get("target_identity")
    target_identity_kwargs: dict[str, Any] = {}
    if action in _FROZEN_TARGET_REQUIRED_ACTIONS and raw_target_identity is None:
        raise ValueError(f"{action} requires a frozen exact target_identity")
    if raw_target_identity is not None:
        if not isinstance(raw_target_identity, Mapping):
            raise ValueError("target_identity must be a structured mapping")
        raw_store_name = params.get("store_name")
        if not isinstance(raw_store_name, str):
            raise ValueError("frozen target commands require an exact string store_name")
        store_name = " ".join(raw_store_name.split())
        if not store_name or raw_store_name != store_name:
            raise ValueError("frozen target commands require a canonical store_name")
        normalized_target = canonical_frozen_target_identity(
            dict(raw_target_identity),
            store_name=store_name,
        )
        if normalized_target is None:
            raise ValueError("target_identity validation unexpectedly returned empty")
        target_identity_kwargs = {"target_identity": normalized_target}
    if action == "update_live_hud":
        updater = getattr(adapter, "update_live_hud", None)
        if not callable(updater):
            return {"ok": True, "updated": False, "reason": "live_hud_unavailable"}
        hud = params.get("hud") if isinstance(params.get("hud"), dict) else {}
        return updater(hud)
    if action == "check_login_state":
        return adapter.check_login_state()
    if action == "open_data_acquisition":
        return adapter.open_data_acquisition()
    if action == "claim_from_data_acquisition":
        claim_target = canonical_mutation_target_payload("claim_from_data_acquisition", params)
        return adapter.claim_from_data_acquisition(
            str(claim_target["claim_mark"]),
            product_query=_optional_str(claim_target.get("product_query")),
            category_name=_optional_str(claim_target.get("category_name")),
            store_name=str(claim_target["store_name"]),
            target_source_urls=list(claim_target["target_source_urls"]),
        )
    if action == "verify_draft_box_claim":
        claim_target = canonical_mutation_target_payload("claim_from_data_acquisition", params)
        return adapter.verify_draft_box_claim(
            str(claim_target["claim_mark"]),
            product_query=_optional_str(claim_target.get("product_query")),
            category_name=_optional_str(claim_target.get("category_name")),
            store_name=str(claim_target["store_name"]),
            target_source_urls=list(claim_target["target_source_urls"]),
        )
    if action == "open_draft_box":
        return adapter.open_draft_box()
    if action == "claim_product":
        return adapter.claim_product(
            str(params.get("note_text") or ""),
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
            **target_identity_kwargs,
        )
    if action == "open_editor":
        return adapter.open_editor(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            note_text=_optional_str(params.get("note_text")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
            **target_identity_kwargs,
        )
    if action == "verify_edit_ownership":
        return adapter.verify_edit_ownership(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
            **target_identity_kwargs,
        )
    if action in {
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
    }:
        method = getattr(adapter, action)
        return method(
            defaults=params.get("defaults") if isinstance(params.get("defaults"), dict) else {},
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    if action == "enable_semi_managed":
        return adapter.enable_semi_managed(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    if action == "verify_not_published":
        return adapter.verify_not_published(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    raise ValueError(f"Unsupported Browser Agent action: {action}")


def _require_raw_action_result_contract(
    value: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, Mapping):
        _raise_action_result_contract_failure("raw action result must be a mapping")
    result = dict(value)
    if type(result.get("ok")) is not bool:
        raise RuntimeError(
            "BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE: raw ok must be an exact boolean"
        )
    contract_facts = result.get("contract_facts")
    if not isinstance(contract_facts, Mapping) or frozenset(contract_facts) != _RAW_CONTRACT_FACT_KEYS:
        raise RuntimeError(
            "BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE: contract_facts must contain exactly "
            f"{sorted(_RAW_CONTRACT_FACT_KEYS)}"
        )
    return result, dict(contract_facts)


def _validate_reported_action_result_identity(
    raw: Mapping[str, Any],
    command: BrowserAgentCommand,
    context: BrowserAgentExecutionContext,
) -> None:
    reported_action = raw.get("action")
    if reported_action is not None and reported_action != command.action:
        _raise_action_result_contract_failure(
            "producer action does not match the authoritative command"
        )
    for field in ("attempted_state", "state"):
        reported_state = raw.get(field)
        if reported_state is not None and reported_state != command.state:
            _raise_action_result_contract_failure(
                "producer state does not match the authoritative command"
            )

    page_identity = raw.get("page_identity")
    if page_identity is not None and not isinstance(page_identity, Mapping):
        _raise_action_result_contract_failure("producer page_identity must be a mapping")
    reported_page_identity = dict(page_identity or {})
    for reported_runtime_id in (
        raw.get("runtime_id"),
        reported_page_identity.get("runtime_id"),
    ):
        if reported_runtime_id is not None and reported_runtime_id != context.runtime_id:
            _raise_action_result_contract_failure(
                "producer runtime_id does not match the authoritative runtime"
            )
    for reported_session_id in (
        raw.get("browser_session_id"),
        reported_page_identity.get("browser_session_id"),
    ):
        if (
            reported_session_id is not None
            and reported_session_id != context.browser_session_id
        ):
            _raise_action_result_contract_failure(
                "producer browser_session_id does not match the cached session"
            )
    reported_kind = reported_page_identity.get("kind")
    if reported_kind is not None and reported_kind != command.expected_page:
        _raise_action_result_contract_failure(
            "producer page kind does not match the authoritative command"
        )


def _reported_action_result_page_url(raw: Mapping[str, Any]) -> str:
    page_identity = raw.get("page_identity")
    reported_page_identity = dict(page_identity) if isinstance(page_identity, Mapping) else {}
    candidates = [
        str(value).strip()
        for value in (
            raw.get("page_url"),
            raw.get("current_url"),
            reported_page_identity.get("url"),
        )
        if value is not None and str(value).strip()
    ]
    if not candidates:
        return ""
    normalized = {_normalized_page_url(value) for value in candidates}
    if "" in normalized or len(normalized) != 1:
        _raise_action_result_contract_failure(
            "producer page URL observations conflict or are invalid"
        )
    return candidates[0]


def _validated_action_result_evidence_refs(
    raw: Mapping[str, Any],
    *,
    state: str,
) -> list[dict[str, Any]]:
    state_specific_field = {
        "SAVE_ONLY": "save_evidence_ref",
        "VERIFY_NOT_PUBLISHED": "unpublished_evidence_ref",
    }.get(state)
    candidate_fields = ["evidence_ref"]
    if state_specific_field is not None:
        candidate_fields.append(state_specific_field)
        if raw.get("ok") is True and raw.get(state_specific_field) is None:
            _raise_action_result_contract_failure(
                f"successful {state} action result requires {state_specific_field}"
            )
    candidates = [raw.get(field) for field in candidate_fields if raw.get(field) is not None]
    required_kind = _PROOF_EVIDENCE_KIND_BY_STATE.get(state)
    if not candidates:
        if raw.get("ok") is True and required_kind is not None:
            _raise_action_result_contract_failure(
                f"successful {state} action result requires a live evidence_ref"
            )
        return []
    first = candidates[0]
    if any(candidate != first for candidate in candidates[1:]):
        _raise_action_result_contract_failure(
            "producer evidence_ref fields disagree"
        )
    validation = validate_evidence_ref(
        first,
        screenshot_root=Path(SCREENSHOT_DIR),
    )
    if validation.get("ok") is not True:
        reason_code = str(validation.get("reason_code") or "EVIDENCE_REF_INVALID")
        _raise_action_result_contract_failure(
            f"evidence_ref live-file validation failed: {reason_code}"
        )
    evidence_path = Path(str(validation["path"]))
    try:
        evidence_stat = evidence_path.stat()
        captured_at = datetime.fromtimestamp(
            evidence_stat.st_mtime,
            timezone.utc,
        ).isoformat()
    except OSError as exc:
        _raise_action_result_contract_failure(
            f"evidence_ref captured_at unavailable: {exc}"
        )
    if state == "VERIFY_NOT_PUBLISHED" and raw.get("ok") is True:
        save_ref = raw.get("save_evidence_ref")
        if not isinstance(save_ref, Mapping):
            _raise_action_result_contract_failure(
                "successful VERIFY_NOT_PUBLISHED requires the preceding save_evidence_ref"
            )
        save_validation = validate_evidence_ref(
            save_ref,
            screenshot_root=Path(SCREENSHOT_DIR),
        )
        if save_validation.get("ok") is not True:
            reason_code = str(save_validation.get("reason_code") or "EVIDENCE_REF_INVALID")
            _raise_action_result_contract_failure(
                f"save_evidence_ref live-file validation failed: {reason_code}"
            )
        save_path = Path(str(save_validation["path"]))
        if save_path.resolve() == evidence_path.resolve():
            _raise_action_result_contract_failure(
                "VERIFY_NOT_PUBLISHED must use a different evidence path from SAVE_ONLY"
            )
        try:
            save_stat = save_path.stat()
        except OSError as exc:
            _raise_action_result_contract_failure(
                f"save_evidence_ref captured_at unavailable: {exc}"
            )
        if evidence_stat.st_mtime_ns <= save_stat.st_mtime_ns:
            _raise_action_result_contract_failure(
                "VERIFY_NOT_PUBLISHED evidence must be captured after SAVE_ONLY evidence"
            )
    return [{
        "path": validation["path"],
        "sha256": validation["sha256"],
        "size": validation["size"],
        "kind": required_kind or "screenshot",
        "captured_at": captured_at,
    }]


def _raise_action_result_contract_failure(message: str) -> None:
    raise RuntimeError(f"BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE: {message}")


def _action_result_page_url(result: Mapping[str, Any]) -> str | None:
    page_identity = result.get("page_identity")
    if not isinstance(page_identity, Mapping):
        return None
    value = str(page_identity.get("url") or "").strip()
    return value or None


def _action_result_page_title(result: Mapping[str, Any]) -> str | None:
    evidence = result.get("evidence")
    observations = evidence.get("observations") if isinstance(evidence, Mapping) else None
    if not isinstance(observations, Mapping):
        return None
    value = str(observations.get("page_title") or "").strip()
    return value or None


def _page_url_matches_identity(page_url: str, expected_page: str) -> bool:
    if not page_url:
        return False
    try:
        parsed = urlparse(page_url)
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").casefold()
    if hostname != "dianxiaomi.com" and not hostname.endswith(".dianxiaomi.com"):
        return False
    path = str(parsed.path or "").rstrip("/").casefold()
    if expected_page == "authenticated_dxm":
        return path.startswith("/web/") and "/login" not in path
    if expected_page == "data_acquisition":
        return path == "/web/productcrawl/dataacquisition"
    if expected_page == "draft_box":
        return path == "/web/smt/smtproductlist/draft"
    if expected_page == "editor":
        return path == "/web/smt/edit"
    if expected_page == "semi_managed":
        return path == "/web/smt/editfromsmt"
    return False


def _controlled_page_identity(page_url: str) -> str | None:
    for identity in (
        "data_acquisition",
        "draft_box",
        "semi_managed",
        "editor",
        "authenticated_dxm",
    ):
        if _page_url_matches_identity(page_url, identity):
            return identity
    return None


def _normalized_page_url(page_url: str) -> str:
    try:
        parsed = urlparse(page_url)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").casefold()
    path = str(parsed.path or "").rstrip("/")
    return f"{parsed.scheme.casefold()}://{hostname}{path}?{parsed.query}".rstrip("?")


def _command_fingerprint(command: BrowserAgentCommand) -> str:
    payload = command.to_payload()
    for transport_field in ("command_id", "idempotency_key", "deadline", "step_label"):
        payload.pop(transport_field, None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _remaining_deadline_seconds(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return max(0.0, deadline_monotonic - time.monotonic())


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        raise ValueError("target_source_urls must be a canonical string list")
    result = list(value)
    return result or None


def _prepare_action_artifacts(command: BrowserAgentCommand, *, command_id: str | None = None) -> dict[str, Any]:
    worker_dir = DATA_DIR / "workflow_worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    safe_state = _safe_file_part(command.state or command.action or "UNKNOWN")
    suffix = str(command_id or uuid.uuid4().hex[:12])
    task_id = _safe_file_part(command.task_id if command.task_id is not None else "none")
    job_id = _safe_file_part(command.job_id if command.job_id is not None else "none")
    stem = f"task_{task_id}_job_{job_id}_{safe_state}_{suffix}"
    request_file = worker_dir / f"{stem}.request.json"
    result_file = worker_dir / f"{stem}.result.json"
    trace_file = worker_dir / f"{stem}.trace.jsonl"
    request_file.write_text(json.dumps(command.to_payload(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "command_id": suffix,
        "request_file": request_file,
        "result_file": result_file,
        "trace_file": trace_file,
    }


def _mode_for_command(command: BrowserAgentCommand) -> str:
    if command.state == "CLAIM_TO_DRAFT_BOX":
        return "claim_only"
    if command.state == "SAVE_ONLY":
        return "single_save"
    return ""


def _write_action_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _safe_file_part(value: Any) -> str:
    text = str(value or "").strip() or "none"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return safe[:80] or "none"


def _defer_page_hud_until_after_action(command: BrowserAgentCommand) -> bool:
    return command.action in {
        "check_login_state",
        "open_data_acquisition",
        "claim_from_data_acquisition",
        "verify_draft_box_claim",
        "open_draft_box",
        "claim_product",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    }


def _result_error_text(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    observations = (
        evidence.get("observations")
        if isinstance(evidence.get("observations"), dict)
        else {}
    )
    recoverability = (
        result.get("recoverability")
        if isinstance(result.get("recoverability"), dict)
        else {}
    )
    for value in (
        result.get("message"),
        result.get("reason"),
        result.get("error"),
        evidence.get("message"),
        evidence.get("reason"),
        evidence.get("error"),
        observations.get("message"),
        observations.get("reason"),
        observations.get("error"),
        recoverability.get("reason"),
        result.get("failure_code"),
        result.get("stage"),
    ):
        text = str(value or "").strip()
        if text:
            return text[:500]
    return "真实浏览器动作未完成"


def _ensure_visible_workflow_profile_env() -> str:
    os.environ["DXM_WORKFLOW_PERSISTENT_PROFILE"] = "1"
    configured = os.environ.get("DXM_WORKFLOW_PROFILE_DIR", "").strip()
    if configured:
        profile_dir = Path(configured).expanduser().resolve()
    else:
        data_dir = Path(os.environ.get("DXM_DATA_DIR") or DATA_DIR).expanduser().resolve()
        profile_dir = data_dir / "browser_profiles" / "dxm_workflow"
        os.environ["DXM_WORKFLOW_PROFILE_DIR"] = str(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_name_for_state(state: str) -> str:
    normalized = str(state or "").upper()
    if normalized in {"OPEN_DATA_ACQUISITION", "CLAIM_TO_DRAFT_BOX", "VERIFY_DRAFT_BOX_CLAIM"}:
        return "待认领商品"
    return "商品箱编辑保存"
