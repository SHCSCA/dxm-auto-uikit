from __future__ import annotations

import os
import json
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from src.core.config import DATA_DIR
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.services.browser_agent_status import build_browser_hud, normalize_operator_copy


class BrowserAgentRuntime:
    """Persistent in-process owner for visible DXM browser commands."""

    def __init__(self, adapter: Any | None = None) -> None:
        self.adapter = adapter
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-browser-agent")
        self._lock = RLock()
        self._status: dict[str, Any] = {
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
        }
        self.events: list[dict[str, Any]] = []

    def set_adapter(self, adapter: Any | None) -> None:
        with self._lock:
            self.adapter = adapter

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            status["events"] = list(self.events[-20:])
            return status

    def reset(self, adapter: Any | None = None) -> dict[str, Any]:
        self._close_adapter_browser_session()
        with self._lock:
            previous = dict(self._status)
            self._shutdown_executor()
            if adapter is not None:
                self.adapter = adapter
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-browser-agent")
            self._status = {
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
            }
            self.events.clear()
            return {"ok": True, "previousStatus": previous, "browserAgent": self.status()}

    def shutdown(self) -> None:
        self._close_adapter_browser_session()
        with self._lock:
            self._shutdown_executor()
            self._status.update(
                {
                    "status": "stopped",
                    "healthy": True,
                    "active": False,
                    "currentStep": "已停止",
                    "lastEventAt": _now(),
                    "message": "真实浏览器执行器已停止",
                    "nextAction": "需要继续时请重新打开真实浏览器执行器",
                }
            )

    def request_manual_takeover(self) -> dict[str, Any]:
        with self._lock:
            self._status.update(
                {
                    "status": "manual_takeover",
                    "manualTakeover": True,
                    "active": True,
                    "currentStep": "人工接管中",
                    "lastEventAt": _now(),
                    "message": "请在真实浏览器里检查或修正当前页面",
                    "nextAction": "处理完成后在控制台交还自动浏览器",
                }
            )
            self._record_event("manual_takeover", "人工接管中", status="manual_takeover")
            return self.status()

    def release_manual_takeover(self) -> dict[str, Any]:
        return self.resume()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            self._status.update(
                {
                    "status": "idle",
                    "manualTakeover": False,
                    "active": False,
                    "currentStep": "等待继续执行",
                    "lastEventAt": _now(),
                    "message": "真实浏览器已交还自动浏览器",
                    "nextAction": "继续执行或重新启动当前任务",
                }
            )
            self._record_event("resume", "等待继续执行", status="idle")
            return self.status()

    def run(self, command: BrowserAgentCommand, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        with self._lock:
            if self.adapter is None:
                raise RuntimeError("Browser Agent adapter is not configured")
            if self._status.get("manualTakeover"):
                raise RuntimeError("真实浏览器正在人工接管中；请先交还自动浏览器后再继续执行。")
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

        artifacts = _prepare_action_artifacts(command)
        future = self._executor.submit(self._execute_with_hud, adapter, command, hud, artifacts)
        try:
            result = future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            last_event = self._latest_workflow_event(adapter)
            last_step = normalize_operator_copy(self._workflow_event_step(last_event) or command.step_label or command.state)
            failed_hud = self._build_hud(command, status="failed", error=f"{command.action} timed out；最后停在：{last_step}")
            with self._lock:
                self._status.update(
                    {
                        "status": "needs_restart",
                        "healthy": False,
                        "active": False,
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
                self._status.update(
                    {
                        "status": "failed",
                        "healthy": False,
                        "active": False,
                        "browserVisible": True,
                        "currentUrl": result.get("page_url") or result.get("current_url"),
                        "pageTitle": result.get("page_title"),
                        "currentStep": failed_hud.get("title") or command.step_label or command.state,
                        "lastError": error_text,
                        "lastEventAt": _now(),
                        "hud": failed_hud,
                        "message": failed_hud.get("human_action"),
                        "nextAction": failed_hud.get("human_next"),
                    }
                )
                self._record_event(command.action, normalize_operator_copy(command.step_label or command.state), status="failed", error=error_text)
            return result

        with self._lock:
            done_hud = self._build_hud(command, status="success")
            self._status.update(
                {
                    "status": "idle",
                    "healthy": True,
                    "active": False,
                    "browserVisible": True,
                    "currentUrl": result.get("page_url") or result.get("current_url"),
                    "pageTitle": result.get("page_title"),
                    "currentStep": done_hud.get("title") or command.step_label or command.state,
                    "lastError": None,
                    "lastEventAt": _now(),
                    "hud": done_hud,
                    "message": done_hud.get("human_action"),
                    "nextAction": done_hud.get("human_next"),
                }
            )
            self._record_event(command.action, normalize_operator_copy(command.step_label or command.state), status="ok")
        return result

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
        artifacts: dict[str, Path],
    ) -> dict[str, Any]:
        previous_trace_file = os.environ.get("DXM_WORKFLOW_TRACE_FILE")
        os.environ["DXM_WORKFLOW_TRACE_FILE"] = str(artifacts["trace_file"])
        updater = getattr(adapter, "update_live_hud", None)
        defer_page_hud = _defer_page_hud_until_after_action(command)
        if callable(updater) and not defer_page_hud:
            updater(hud)
        try:
            result = execute_browser_agent_action(adapter, command.action, command.params)
            if isinstance(result, dict):
                result.setdefault("workflow_trace_file", str(artifacts["trace_file"]))
                result.setdefault("browser_agent_request_file", str(artifacts["request_file"]))
                result.setdefault("browser_agent_result_file", str(artifacts["result_file"]))
            _write_action_result(artifacts["result_file"], {"ok": True, "result": result})
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
            if previous_trace_file is None:
                os.environ.pop("DXM_WORKFLOW_TRACE_FILE", None)
            else:
                os.environ["DXM_WORKFLOW_TRACE_FILE"] = previous_trace_file

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

    def _shutdown_executor(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=False)

    def _close_adapter_browser_session(self) -> None:
        adapter = self.adapter
        if adapter is None:
            return
        closer = getattr(adapter, "close_browser_session", None)
        if not callable(closer):
            login_flow = getattr(adapter, "login_flow", None)
            closer = getattr(login_flow, "_close_browser_session", None)
        if not callable(closer):
            return
        try:
            future = self._executor.submit(closer)
            future.result(timeout=5)
        except Exception as exc:
            with self._lock:
                self._record_event("shutdown", "关闭真实浏览器失败", status="failed", error=str(exc))


def execute_browser_agent_action(adapter: Any, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params if isinstance(params, dict) else {}
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
        return adapter.claim_from_data_acquisition(
            str(params.get("claim_mark") or ""),
            product_query=_optional_str(params.get("product_query")),
            category_name=_optional_str(params.get("category_name")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
        )
    if action == "verify_draft_box_claim":
        return adapter.verify_draft_box_claim(
            str(params.get("claim_mark") or ""),
            product_query=_optional_str(params.get("product_query")),
            category_name=_optional_str(params.get("category_name")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
        )
    if action == "open_draft_box":
        return adapter.open_draft_box()
    if action == "claim_product":
        return adapter.claim_product(
            str(params.get("note_text") or ""),
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
        )
    if action == "open_editor":
        return adapter.open_editor(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            note_text=_optional_str(params.get("note_text")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
        )
    if action == "verify_edit_ownership":
        return adapter.verify_edit_ownership(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
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
        )
    if action == "enable_semi_managed":
        return adapter.enable_semi_managed(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
        )
    if action == "verify_not_published":
        return adapter.verify_not_published(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
        )
    raise ValueError(f"Unsupported Browser Agent action: {action}")


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = [str(item).strip() for item in value if str(item or "").strip()]
    return result or None


def _prepare_action_artifacts(command: BrowserAgentCommand) -> dict[str, Path]:
    worker_dir = DATA_DIR / "workflow_worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    safe_state = _safe_file_part(command.state or command.action or "UNKNOWN")
    suffix = uuid.uuid4().hex[:12]
    task_id = _safe_file_part(command.task_id if command.task_id is not None else "none")
    job_id = _safe_file_part(command.job_id if command.job_id is not None else "none")
    stem = f"task_{task_id}_job_{job_id}_{safe_state}_{suffix}"
    request_file = worker_dir / f"{stem}.request.json"
    result_file = worker_dir / f"{stem}.result.json"
    trace_file = worker_dir / f"{stem}.trace.jsonl"
    request_file.write_text(json.dumps(command.to_payload(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "request_file": request_file,
        "result_file": result_file,
        "trace_file": trace_file,
    }


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
    for value in (
        result.get("message"),
        result.get("reason"),
        result.get("error"),
        evidence.get("message"),
        evidence.get("reason"),
        evidence.get("error"),
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
