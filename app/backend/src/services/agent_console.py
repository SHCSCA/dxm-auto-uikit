from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import DATA_DIR
from src.execution.browser_runtime import chrome_launch_options
from src.services.browser_agent_status import build_browser_hud


PROFILE_ROOT = DATA_DIR / "browser_profiles" / "agent_console"
SCREENSHOT_ROOT = DATA_DIR / "screenshots" / "agent_console"
DEFAULT_TARGET_URL = "https://www.dianxiaomi.com/"
MAX_NETWORK_EVENTS = 120
MAX_ACTION_EVENTS = 160
MAX_RECENT_ACTIONS = 3
BROWSER_CLOSED_MESSAGE = "真实浏览器窗口已关闭，请重新打开执行浏览器。"
BLOCKED_SELECTOR_CONTROL_KEYWORDS = (
    "publish",
    "submitpublish",
    "save",
    "claim",
    "remark",
    "note",
    "release",
    "submit",
    "add.json",
    "发布",
    "保存",
    "待发布",
    "认领",
    "领取",
    "备注",
    "刊登",
    "上架",
)
USER_ACTION_HUD_COPY = {
    "WAITING_CAPTCHA": {
        "phase": "等待人工处理",
        "severity": "warning",
        "human_title": "需要你处理验证码",
        "human_action": "请在真实店小秘浏览器里完成验证码或二次确认",
        "human_next": "完成后回到控制台检测登录状态",
    },
    "MANUAL_APPROVAL_REQUIRED": {
        "phase": "等待人工确认",
        "severity": "warning",
        "human_title": "需要你人工确认只保存",
        "human_action": "请确认本次任务只保存、不发布",
        "human_next": "确认后才会启动真实浏览器保存",
    },
    "MANUAL_TAKEOVER": {
        "phase": "人工接管中",
        "severity": "warning",
        "human_title": "需要你接管真实浏览器",
        "human_action": "请在真实浏览器里检查或修正当前页面",
        "human_next": "处理完成后在控制台交还 Agent",
    },
    "BROWSER_CLOSED": {
        "phase": "真实浏览器已关闭",
        "severity": "error",
        "human_title": "真实浏览器窗口已关闭",
        "human_action": "请重新打开执行浏览器后继续任务",
        "human_next": "回到执行浏览器重新打开",
    },
}


class AgentConsoleService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = self._empty_state()
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-console")

    def status(self) -> dict[str, Any]:
        self._refresh_browser_liveness()
        with self._lock:
            return dict(self._state)

    def start(
        self,
        *,
        task_id: int | None = None,
        target_url: str | None = None,
        launch_browser: bool = True,
        launch_browser_async: bool = False,
        step: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reused = self._reuse_visible_browser_if_possible(
            task_id=task_id,
            target_url=target_url,
            launch_browser=launch_browser,
            step=step,
        )
        if reused is not None:
            return reused

        self._close_current_browser()
        with self._lock:
            session_id = f"agent-{uuid.uuid4().hex[:10]}"
            profile_dir = PROFILE_ROOT / session_id
            profile_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "active": True,
                "session_id": session_id,
                "task_id": task_id,
                "profile_dir": str(profile_dir),
                "launch_browser": launch_browser,
                "browser_launching": bool(launch_browser),
                "browser_visible": False,
                "target_url": target_url or DEFAULT_TARGET_URL,
                "current_url": target_url or DEFAULT_TARGET_URL,
                "page_title": "Agent Console",
                "hud": self._hud_state(step),
                "job_id": None,
                "product_id": None,
                "field_domain": None,
                "mode": None,
                "last_step_code": None,
                "last_step_name": None,
                "step_history": [],
                "network_events": [],
                "action_events": [],
                "manual_takeover": False,
                "manual_takeover_started_at": None,
                "screenshot": None,
                "last_frame_at": None,
                "created_at": _now(),
                "updated_at": _now(),
                "last_error": None,
            }
            self._state = state

        if launch_browser:
            if launch_browser_async:
                self._browser_executor.submit(lambda: self._launch_visible_browser(profile_dir, state))
            else:
                self._run_browser_op(lambda: self._launch_visible_browser(profile_dir, state))

        return self.status()

    def _reuse_visible_browser_if_possible(
        self,
        *,
        task_id: int | None,
        target_url: str | None,
        launch_browser: bool,
        step: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not launch_browser:
            return None
        with self._lock:
            current_task_id = self._state.get("task_id")
            same_task = task_id is None or current_task_id is None or current_task_id == task_id
            if (
                not same_task
                or not self._state.get("active")
                or not self._state.get("browser_visible")
                or self._page is None
            ):
                return None

            if current_task_id is None and task_id is not None:
                self._state["task_id"] = task_id
            if target_url:
                self._state["target_url"] = target_url
                if not self._state.get("current_url"):
                    self._state["current_url"] = target_url
            self._state["launch_browser"] = True
            self._state["browser_launching"] = False
            self._state["hud"] = self._hud_state(step)
            self._state["last_error"] = None
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])

        if page is not None:
            self._apply_hud_safely(page, hud)
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._close_current_browser()
        with self._lock:
            self._state = self._empty_state()
            return dict(self._state)

    def update_hud(self, step: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state["hud"] = self._hud_state(step)
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])
        if page is not None:
            self._run_browser_op(lambda: self._apply_hud(page, hud))
        return self.status()

    def update_task_step(
        self,
        *,
        task_id: int,
        job_id: int | None = None,
        product_id: int | None = None,
        step_code: str,
        step_name: str,
        field_domain: str | None = None,
        mode: str | None = None,
        store_name: str | None = None,
        title: str | None = None,
        line1: str | None = None,
        line2: str | None = None,
        next_step: str | None = None,
        screenshot_path: str | None = None,
        phase: str | None = None,
        progress_index: int | None = None,
        progress_total: int | None = None,
        severity: str | None = None,
        human_title: str | None = None,
        human_action: str | None = None,
        human_next: str | None = None,
        recent_actions: list[str] | None = None,
        requires_user_action: bool | None = None,
        guard: str | None = None,
        maintenance_detail: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {
                    "ok": True,
                    "updated": False,
                    "reason": "agent_console_inactive",
                    "active": False,
                }
            current_task_id = self._state.get("task_id")
            if current_task_id is not None and current_task_id != task_id:
                return {
                    "ok": False,
                    "updated": False,
                    "reason": "task_mismatch",
                    "active": True,
                    "session_id": self._state.get("session_id"),
                    "task_id": current_task_id,
                }
            if current_task_id is None:
                self._state["task_id"] = task_id

            current_hud = dict(self._state.get("hud") or {})
            hud = self._hud_state({
                "title": title or step_name,
                "state": step_code,
                "action": _step_action(field_domain, mode),
                "line1": line1,
                "line2": line2,
                "next_step": next_step or "等待状态机推进",
                "store_name": store_name or "Dang Kang",
                "guard": guard or "只保存不发布",
                "phase": phase,
                "progress_index": progress_index,
                "progress_total": progress_total,
                "severity": severity,
                "human_title": human_title,
                "human_action": human_action,
                "human_next": human_next,
                "recent_actions": recent_actions if recent_actions is not None else current_hud.get("recent_actions"),
                "requires_user_action": requires_user_action,
                "maintenance_detail": maintenance_detail,
            })
            event = {
                "task_id": task_id,
                "job_id": job_id,
                "product_id": product_id,
                "step_code": step_code,
                "step_name": step_name,
                "field_domain": field_domain,
                "mode": mode,
                "screenshot_path": screenshot_path,
                "updated_at": _now(),
            }
            history = list(self._state.get("step_history") or [])
            history.append(event)
            self._state.update({
                "hud": hud,
                "job_id": job_id,
                "product_id": product_id,
                "field_domain": field_domain,
                "mode": mode,
                "last_step_code": step_code,
                "last_step_name": step_name,
                "step_history": history[-80:],
                "updated_at": _now(),
            })
            page = self._page

        if page is not None:
            try:
                self._run_browser_op(lambda: self._apply_hud(page, hud))
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)
                    self._state["updated_at"] = _now()
                status = self._compact_status()
                return {
                    **status,
                    "ok": False,
                    "updated": False,
                    "reason": "hud_apply_failed",
                    "error": str(exc),
                }
        return {**self._compact_status(), "ok": True, "updated": True, "reason": "updated"}

    def record_action_event(
        self,
        *,
        task_id: int,
        job_id: int | None = None,
        product_id: int | None = None,
        type: str = "workflow_action",
        action: str | None = None,
        label: str | None = None,
        state: str | None = None,
        step_code: str | None = None,
        field_domain: str | None = None,
        status: str | None = None,
        target: str | None = None,
        value: str | None = None,
        page_url: str | None = None,
        screenshot_url: str | None = None,
        save_result: dict[str, Any] | None = None,
        store_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {
                    "ok": True,
                    "updated": False,
                    "reason": "agent_console_inactive",
                    "active": False,
                }
            current_task_id = self._state.get("task_id")
            if current_task_id is not None and current_task_id != task_id:
                return {
                    "ok": False,
                    "updated": False,
                    "reason": "task_mismatch",
                    "active": True,
                    "session_id": self._state.get("session_id"),
                    "task_id": current_task_id,
                }
            if current_task_id is None:
                self._state["task_id"] = task_id

            event = {
                "type": type or "workflow_action",
                "action": action,
                "label": label or action or "自动化动作",
                "state": state or step_code,
                "step_code": step_code or state,
                "task_id": task_id,
                "job_id": job_id,
                "product_id": product_id,
                "field_domain": field_domain,
                "status": status or "ok",
                "target": target,
                "value": value,
                "page_url": page_url,
                "screenshot_url": screenshot_url,
                "save_result": save_result,
                "store_name": store_name,
                "timestamp": _now(),
            }
            events = list(self._state.get("action_events") or [])
            events.append({key: value for key, value in event.items() if value is not None})
            self._state["action_events"] = events[-MAX_ACTION_EVENTS:]
            self._state["hud"] = self._hud_state({
                **dict(self._state.get("hud") or {}),
                "recent_actions": _recent_action_labels(events),
            })
            if page_url:
                self._state["current_url"] = page_url
            if screenshot_url:
                self._state["screenshot"] = screenshot_url
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])

        if page is not None:
            self._apply_hud_safely(page, hud)
        return {**self._compact_status(), "ok": True, "updated": True, "reason": "action_recorded"}

    def snapshot(self) -> dict[str, Any]:
        return self.refresh_frame()

    def request_manual_takeover(self) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {**dict(self._state), "ok": False, "reason": "agent_console_inactive"}
            self._state["manual_takeover"] = True
            self._state["manual_takeover_started_at"] = _now()
            current_hud = dict(self._state.get("hud") or {})
            self._state["hud"] = self._hud_state({
                "state": "MANUAL_TAKEOVER",
                "recent_actions": current_hud.get("recent_actions"),
            })
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])

        if page is not None:
            try:
                self._run_browser_op(lambda: page.bring_to_front())
                self._run_browser_op(lambda: self._apply_hud(page, hud))
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)
                    self._state["updated_at"] = _now()

        return self._record_manual_takeover_event(action="request_takeover", label="人工接管真实浏览器")

    def release_manual_takeover(self) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {**dict(self._state), "ok": False, "reason": "agent_console_inactive"}
            self._state["manual_takeover"] = False
            self._state["manual_takeover_started_at"] = None
            self._state["hud"] = self._hud_state({
                **dict(self._state.get("hud") or {}),
                "state": "AGENT_RESUMED",
                "phase": "Agent 继续执行",
                "severity": "info",
                "human_title": "Agent 继续执行",
                "human_action": "真实浏览器已交还给 Agent",
                "human_next": "继续按任务流程只保存、不发布",
                "requires_user_action": False,
            })
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])
        if page is not None:
            try:
                self._run_browser_op(lambda: self._apply_hud(page, hud))
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)
                    self._state["updated_at"] = _now()
        return self._record_manual_takeover_event(action="release_agent", label="交还 Agent")

    def refresh_frame(self) -> dict[str, Any]:
        self._refresh_browser_liveness()
        with self._lock:
            page = self._page
            session_id = self._state.get("session_id")
        if page is None or not session_id:
            return self.status()

        SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_ROOT / f"{session_id}.png"
        try:
            def capture_frame() -> dict[str, str]:
                page.screenshot(path=str(path), full_page=False)
                return {
                    "current_url": page.url,
                    "page_title": page.title(),
                }

            frame = self._run_browser_op(capture_frame)
            with self._lock:
                self._state["screenshot"] = str(path)
                self._state["last_frame_at"] = _now()
                self._state["current_url"] = frame["current_url"]
                self._state["page_title"] = frame["page_title"]
                self._state["last_error"] = None
                self._state["updated_at"] = _now()
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()
        return self.status()

    def control_browser(self, command: dict[str, Any]) -> dict[str, Any]:
        self._refresh_browser_liveness()
        action = str(command.get("action") or "").strip().lower()
        with self._lock:
            if not self._state.get("active"):
                return {**dict(self._state), "ok": False, "reason": "agent_console_inactive"}
            page = self._page
            if page is None:
                return {**dict(self._state), "ok": False, "reason": "browser_page_unavailable"}
            if not self._state.get("browser_visible"):
                return {**dict(self._state), "ok": False, "reason": "browser_window_not_visible"}
            if self._state.get("manual_takeover"):
                return {**dict(self._state), "ok": False, "reason": "manual_takeover_active"}

        try:
            result = self._run_browser_op(lambda: self._perform_browser_control(page, action, command))
            self._record_browser_control_event(action=action, command=command, status="ok", result=result)
            self.refresh_frame()
            return {**self.status(), "ok": True, "reason": "browser_control_executed", "control_result": result}
        except Exception as exc:
            self._record_browser_control_event(action=action or "unknown", command=command, status="error", error=str(exc))
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()
            return {**self.status(), "ok": False, "reason": "browser_control_failed", "error": str(exc)}

    def _perform_browser_control(self, page, action: str, command: dict[str, Any]) -> dict[str, Any]:
        if action == "click":
            raise ValueError("browser click controls are disabled; use the approved task flow or manual takeover")
        if action == "selector_click":
            selector = _required_text(command, "selector", "selector is required for selector_click")
            raise ValueError(
                "selector browser controls are disabled until publish guard approval is integrated; "
                f"use the approved task flow or manual takeover: {selector}"
            )
        if action == "selector_fill":
            selector = _required_text(command, "selector", "selector is required for selector_fill")
            text = _required_untrimmed_text(command, "text", "text is required for selector_fill")
            raise ValueError(
                "selector browser controls are disabled until publish guard approval is integrated; "
                f"use the approved task flow or manual takeover: {selector}; text_length={len(text)}"
            )
        if action == "type":
            raise ValueError("browser type controls are disabled; use the approved task flow or manual takeover")
        if action == "press":
            raise ValueError("browser key controls are disabled; use the approved task flow or manual takeover")
        if action == "scroll":
            delta_x = int(command.get("delta_x") or 0)
            delta_y = int(command.get("delta_y") or 0)
            if delta_x == 0 and delta_y == 0:
                raise ValueError("delta_x or delta_y is required for scroll")
            page.mouse.wheel(delta_x, delta_y)
            return {"action": action, "delta_x": delta_x, "delta_y": delta_y}
        if action == "goto":
            url = str(command.get("url") or "").strip()
            if not url.startswith(("https://www.dianxiaomi.com/", "https://dianxiaomi.com/")):
                raise ValueError("goto only allows dianxiaomi.com URLs")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return {"action": action, "url": url}
        raise ValueError(f"Unsupported browser control action: {action or 'empty'}")

    def _record_network_event(self, event: dict[str, Any]) -> None:
        cleaned = {
            "type": event.get("type") or "network",
            "method": event.get("method"),
            "url": event.get("url"),
            "status": event.get("status"),
            "timestamp": event.get("timestamp") or _now(),
        }
        with self._lock:
            events = list(self._state.get("network_events") or [])
            events.append(cleaned)
            self._state["network_events"] = events[-MAX_NETWORK_EVENTS:]
            self._state["updated_at"] = _now()

    def _record_browser_control_event(
        self,
        *,
        action: str,
        command: dict[str, Any],
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            event = {
                "type": "browser_control",
                "action": action,
                "label": _browser_control_label(action, command),
                "status": status,
                "target": _browser_control_target(action, command),
                "value": _browser_control_value(action, command),
                "page_url": self._state.get("current_url"),
                "result": result,
                "error": error,
                "timestamp": _now(),
            }
            events = list(self._state.get("action_events") or [])
            events.append({key: value for key, value in event.items() if value is not None})
            self._state["action_events"] = events[-MAX_ACTION_EVENTS:]
            self._state["hud"] = self._hud_state({
                **dict(self._state.get("hud") or {}),
                "recent_actions": _recent_action_labels(events),
            })
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])

        if page is not None:
            self._apply_hud_safely(page, hud)

    def _record_manual_takeover_event(self, *, action: str, label: str) -> dict[str, Any]:
        with self._lock:
            event = {
                "type": "manual_takeover",
                "action": action,
                "label": label,
                "status": "ok",
                "page_url": self._state.get("current_url"),
                "timestamp": _now(),
            }
            events = list(self._state.get("action_events") or [])
            events.append({key: value for key, value in event.items() if value is not None})
            self._state["action_events"] = events[-MAX_ACTION_EVENTS:]
            self._state["updated_at"] = _now()
            return dict(self._state)

    def _launch_visible_browser(self, profile_dir: Path, state: dict[str, Any]) -> None:
        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            options = chrome_launch_options(headless=False)
            options.setdefault("viewport", {"width": 1440, "height": 960})
            options.setdefault("ignore_https_errors", True)
            args = list(options.pop("args", []))
            args.extend([
                "--disable-notifications",
                "--no-first-run",
                "--no-default-browser-check",
            ])
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                **options,
                args=args,
            )
            page = context.pages[0] if context.pages else context.new_page()
            self._attach_network_listeners(page)
            self._attach_browser_lifecycle_listeners(context, page)
            self._attach_page_runtime_listeners(context, page)
            page.add_init_script(HUD_INIT_SCRIPT)
            page.goto(state["target_url"], wait_until="domcontentloaded", timeout=45000)
            self._apply_hud(page, state["hud"])
            current_url = page.url
            page_title = page.title()
            with self._lock:
                if self._state.get("session_id") != state["session_id"] or not self._state.get("active"):
                    self._close_browser_objects(context, playwright)
                    return
                self._playwright = playwright
                self._context = context
                self._page = page
                self._state["browser_launching"] = False
                self._state["browser_visible"] = True
                self._state["current_url"] = current_url
                self._state["page_title"] = page_title
                self._state["last_error"] = None
                self._state["updated_at"] = _now()
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["browser_launching"] = False
                self._state["browser_visible"] = False
                self._state["updated_at"] = _now()

    def _attach_network_listeners(self, page) -> None:
        def on_request(request) -> None:
            try:
                self._record_network_event({
                    "type": "request",
                    "method": getattr(request, "method", None),
                    "url": getattr(request, "url", None),
                })
            except Exception:
                pass

        def on_response(response) -> None:
            try:
                request = getattr(response, "request", None)
                self._record_network_event({
                    "type": "response",
                    "method": getattr(request, "method", None),
                    "url": getattr(response, "url", None),
                    "status": getattr(response, "status", None),
                })
            except Exception:
                pass

        try:
            page.on("request", on_request)
            page.on("response", on_response)
        except Exception:
            pass

    def _attach_browser_lifecycle_listeners(self, context, page) -> None:
        def on_closed() -> None:
            self._mark_browser_closed(BROWSER_CLOSED_MESSAGE)

        for target in (context, page):
            try:
                target.on("close", lambda *args: on_closed())
            except Exception:
                pass

    def _attach_page_runtime_listeners(self, context, page) -> None:
        def attach_page(target_page) -> None:
            try:
                self._attach_network_listeners(target_page)
            except Exception:
                pass
            for event_name in ("framenavigated", "domcontentloaded"):
                try:
                    target_page.on(event_name, lambda *args, p=target_page: self._reapply_hud_to_page(p))
                except Exception:
                    pass
            try:
                target_page.on("close", lambda *args: self._mark_browser_closed(BROWSER_CLOSED_MESSAGE))
            except Exception:
                pass
            self._reapply_hud_to_page(target_page)

        attach_page(page)
        try:
            context.on("page", lambda new_page: attach_page(new_page))
        except Exception:
            pass

    def _reapply_hud_to_page(self, page) -> None:
        with self._lock:
            if not self._state.get("active"):
                return
            hud = dict(self._state.get("hud") or {})
        if not hud:
            return
        try:
            self._apply_hud(page, hud)
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()

    def _apply_hud(self, page, hud: dict[str, Any]) -> None:
        try:
            page.evaluate(HUD_INIT_SCRIPT)
        except Exception:
            pass
        page.evaluate(
            """
            (hud) => {
              window.__dxmAgentHudState = hud;
              try {
                window.sessionStorage.setItem('__dxmAgentHudPersistedState', JSON.stringify(hud));
              } catch (error) {}
              if (window.__dxmRenderAgentHud) window.__dxmRenderAgentHud();
            }
            """,
            hud,
        )

    def _apply_hud_safely(self, page, hud: dict[str, Any]) -> None:
        try:
            self._run_browser_op(lambda: self._apply_hud(page, hud))
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()

    def _close_current_browser(self) -> None:
        with self._lock:
            context = self._context
            playwright = self._playwright
            self._playwright = None
            self._context = None
            self._page = None
        if context is not None or playwright is not None:
            self._run_browser_op(lambda: self._close_browser_objects(context, playwright))

    def _close_browser_objects(self, context, playwright) -> None:
        for obj in (context, playwright):
            if obj is None:
                continue
            try:
                if obj is playwright:
                    obj.stop()
                else:
                    obj.close()
            except Exception:
                pass

    def _refresh_browser_liveness(self) -> None:
        with self._lock:
            if not self._state.get("active"):
                return
            page = self._page
            context = self._context
            visible = bool(self._state.get("browser_visible"))
            launching = bool(self._state.get("browser_launching"))
        if not visible and not launching:
            return
        if page is None:
            closed = visible
        else:
            closed = self._object_is_closed(page) or self._object_is_closed(context)
        if not closed:
            return
        self._mark_browser_closed(BROWSER_CLOSED_MESSAGE)

    def _mark_browser_closed(self, message: str) -> None:
        with self._lock:
            if not self._state.get("active"):
                return
            self._state["browser_visible"] = False
            self._state["browser_launching"] = False
            self._state["last_error"] = message
            self._state["hud"] = self._hud_state({
                **dict(self._state.get("hud") or {}),
                "state": "BROWSER_CLOSED",
                "title": "真实浏览器窗口已关闭",
                "action": "请重新打开执行浏览器后继续任务",
                "next_step": "回到执行浏览器重新打开",
                "human_title": "真实浏览器窗口已关闭",
                "human_action": "请重新打开执行浏览器后继续任务",
                "human_next": "回到执行浏览器重新打开",
                "requires_user_action": True,
            })
            self._state["updated_at"] = _now()

    def _object_is_closed(self, value) -> bool:
        if value is None:
            return False
        is_closed = getattr(value, "is_closed", None)
        if callable(is_closed):
            try:
                return bool(is_closed())
            except Exception:
                return True
        return False

    def _run_browser_op(self, operation):
        return self._browser_executor.submit(operation).result(timeout=90)

    def _hud_state(self, step: dict[str, Any] | None) -> dict[str, Any]:
        step = step or {}
        state = step.get("state") or step.get("code") or "WAITING"
        mapped = None
        if str(state).upper() != "WAITING":
            mapped = build_browser_hud({
                "step": state,
                "status": step.get("status") or step.get("severity") or "running",
                "task_name": step.get("task_name"),
                "store_name": step.get("store_name"),
                "guard": step.get("guard"),
                "phase": step.get("phase"),
                "progress_index": step.get("progress_index"),
                "progress_total": step.get("progress_total"),
                "human_title": step.get("human_title"),
                "human_action": step.get("human_action"),
                "human_next": step.get("human_next") or step.get("next_step"),
                "line1": step.get("line1"),
                "line2": step.get("line2"),
                "maintenance_detail": step.get("maintenance_detail"),
            })
        title = step.get("title") or step.get("label") or (mapped or {}).get("title") or "Agent Console 待命"
        user_action_copy = USER_ACTION_HUD_COPY.get(str(state).upper())
        if user_action_copy and not step.get("title") and not step.get("label"):
            title = user_action_copy["human_title"]
        action = step.get("action") or step.get("detail") or (mapped or {}).get("line1") or (user_action_copy or {}).get("human_action") or "等待后端状态机推送"
        next_step = step.get("next_step") or (mapped or {}).get("human_next") or (user_action_copy or {}).get("human_next") or "等待下一步"
        line1 = step.get("line1") or (mapped or {}).get("line1") or action
        line2 = step.get("line2") or (mapped or {}).get("line2")
        recent_actions = step.get("recent_actions")
        requires_user_action = step.get("requires_user_action")
        if requires_user_action is None and user_action_copy:
            requires_user_action = True
        return {
            "title": title,
            "state": state,
            "action": action,
            "line1": line1,
            "line2": line2,
            "next_step": next_step,
            "store_name": step.get("store_name") or "Dang Kang",
            "guard": step.get("guard") or "只保存不发布",
            "phase": step.get("phase") or (mapped or {}).get("phase") or (user_action_copy or {}).get("phase") or "业务进度",
            "progress_index": step.get("progress_index") or (mapped or {}).get("progress_index"),
            "progress_total": step.get("progress_total") or (mapped or {}).get("progress_total"),
            "severity": step.get("severity") or (mapped or {}).get("severity") or (user_action_copy or {}).get("severity") or "info",
            "human_title": step.get("human_title") or (user_action_copy or {}).get("human_title") or title,
            "human_action": step.get("human_action") or step.get("action") or (mapped or {}).get("human_action") or (user_action_copy or {}).get("human_action") or action,
            "human_next": step.get("human_next") or step.get("next_step") or (mapped or {}).get("human_next") or (user_action_copy or {}).get("human_next") or next_step,
            "recent_actions": list(recent_actions or [])[-MAX_RECENT_ACTIONS:],
            "requires_user_action": bool(requires_user_action) if requires_user_action is not None else False,
            "maintenance_detail": step.get("maintenance_detail") or (mapped or {}).get("maintenance_detail"),
            "updated_at": _now(),
        }

    def _empty_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "session_id": None,
            "task_id": None,
            "profile_dir": None,
            "launch_browser": False,
            "browser_launching": False,
            "browser_visible": False,
            "target_url": DEFAULT_TARGET_URL,
            "current_url": None,
            "page_title": None,
            "hud": self._hud_state({}),
            "job_id": None,
            "product_id": None,
            "field_domain": None,
            "mode": None,
            "last_step_code": None,
            "last_step_name": None,
            "step_history": [],
            "network_events": [],
            "action_events": [],
            "manual_takeover": False,
            "manual_takeover_started_at": None,
            "screenshot": None,
            "last_frame_at": None,
            "created_at": None,
            "updated_at": None,
            "last_error": None,
        }

    def _compact_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._state.get("active"),
                "session_id": self._state.get("session_id"),
                "task_id": self._state.get("task_id"),
                "job_id": self._state.get("job_id"),
                "product_id": self._state.get("product_id"),
                "browser_visible": self._state.get("browser_visible"),
                "browser_launching": self._state.get("browser_launching"),
                "current_url": self._state.get("current_url"),
                "page_title": self._state.get("page_title"),
                "hud": dict(self._state.get("hud") or {}),
                "last_step_code": self._state.get("last_step_code"),
                "last_step_name": self._state.get("last_step_name"),
                "network_events": list(self._state.get("network_events") or []),
                "action_events": list(self._state.get("action_events") or []),
                "manual_takeover": self._state.get("manual_takeover"),
                "manual_takeover_started_at": self._state.get("manual_takeover_started_at"),
                "screenshot": self._state.get("screenshot"),
                "last_frame_at": self._state.get("last_frame_at"),
                "updated_at": self._state.get("updated_at"),
                "last_error": self._state.get("last_error"),
            }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step_action(field_domain: str | None, mode: str | None) -> str:
    parts = [part for part in (field_domain, mode) if part]
    return " / ".join(parts) if parts else "状态机步骤推进"


def _recent_action_labels(events: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for event in reversed(events):
        label = str(event.get("label") or event.get("action") or "").strip()
        if label:
            labels.append(label)
        if len(labels) >= MAX_RECENT_ACTIONS:
            break
    return list(reversed(labels))


def _required_int(command: dict[str, Any], key: str) -> int:
    value = command.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    return int(value)


def _required_text(command: dict[str, Any], key: str, message: str) -> str:
    value = str(command.get(key) or "").strip()
    if not value:
        raise ValueError(message)
    return value


def _required_untrimmed_text(command: dict[str, Any], key: str, message: str) -> str:
    value = command.get(key)
    if value is None or not str(value).strip():
        raise ValueError(message)
    return str(value)


def _assert_safe_selector_control(selector: str) -> None:
    normalized = selector.casefold()
    for keyword in BLOCKED_SELECTOR_CONTROL_KEYWORDS:
        if keyword.casefold() in normalized:
            raise ValueError(f"blocked selector target: {keyword}")


def _browser_control_label(action: str, command: dict[str, Any]) -> str:
    labels = {
        "click": "页面内点击",
        "selector_click": "选择器点击",
        "selector_fill": "选择器填写",
        "type": "页面内输入",
        "press": "键盘按键",
        "scroll": "页面滚动",
        "goto": "页面导航",
    }
    return labels.get(action) or f"浏览器控制：{action or 'unknown'}"


def _browser_control_target(action: str, command: dict[str, Any]) -> str | None:
    if action == "click":
        return f"x={command.get('x')}, y={command.get('y')}"
    if action in {"selector_click", "selector_fill"}:
        return str(command.get("selector") or "")
    if action == "scroll":
        return f"delta_x={command.get('delta_x') or 0}, delta_y={command.get('delta_y') or 0}"
    if action == "goto":
        return str(command.get("url") or "")
    return None


def _browser_control_value(action: str, command: dict[str, Any]) -> str | None:
    if action in {"type", "selector_fill"}:
        text = str(command.get("text") or "")
        return f"{len(text)} chars"
    if action == "press":
        return str(command.get("key") or "")
    return None


HUD_INIT_SCRIPT = """
(() => {
  const ID = 'dxm-agent-console-hud';
  let persisted = null;
  try {
    persisted = JSON.parse(window.sessionStorage.getItem('__dxmAgentHudPersistedState') || 'null');
  } catch (error) {
    persisted = null;
  }
  window.__dxmAgentHudState = persisted || window.__dxmAgentHudState || {};
  window.__dxmRenderAgentHud = () => {
    const hud = window.__dxmAgentHudState || {};
    let root = document.getElementById(ID);
    if (!root) {
      root = document.createElement('div');
      root.id = ID;
      root.dataset.dxmAgentHud = 'active';
      root.style.cssText = [
        'position:fixed',
        'top:max(86px, env(safe-area-inset-top, 0px))',
        'left:12px',
        'z-index:2147483647',
        'width:min(280px, calc(100vw - 24px))',
        'max-height:min(230px, calc(100vh - 110px))',
        'box-sizing:border-box',
        'overflow:hidden',
        'font:12px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif',
        'color:#f8fafc',
        'background:rgba(13,17,23,.94)',
        'border:1px solid rgba(148,163,184,.32)',
        'border-radius:8px',
        'box-shadow:0 18px 46px rgba(0,0,0,.36)',
        'padding:12px',
        'backdrop-filter:blur(8px)',
        'pointer-events:none'
      ].join(';');
      document.documentElement.appendChild(root);
    }
    root.dataset.dxmAgentHud = 'active';
    const safe = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const progressIndex = Number(hud.progress_index || 0);
    const progressTotal = Number(hud.progress_total || 0);
    const progressReady = progressIndex > 0 && progressTotal > 0;
    const percent = progressReady ? Math.max(3, Math.min(100, Math.round(progressIndex / progressTotal * 100))) : 0;
    const progressText = progressReady ? `${progressIndex}/${progressTotal}` : safe(hud.phase || '等待');
    const recentActions = Array.isArray(hud.recent_actions) ? hud.recent_actions.slice(-3) : [];
    const severityColor = hud.severity === 'error' ? '#fb7185' : hud.severity === 'warning' ? '#fbbf24' : hud.severity === 'success' ? '#34d399' : '#60a5fa';
    const userBadge = hud.requires_user_action ? '<span style="color:#fbbf24;font-weight:800">等待人工处理</span>' : '<span style="color:#93c5fd;font-weight:800">自动执行中</span>';
    const recentHtml = recentActions.length
      ? `<div style="margin-top:9px;display:grid;gap:4px">${recentActions.map((item) => `<div style="color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">• ${safe(item)}</div>`).join('')}</div>`
      : '';
    root.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:7px;min-width:0">
          <span style="width:10px;height:10px;border-radius:50%;background:${severityColor};box-shadow:0 0 0 5px rgba(96,165,250,.16)"></span>
          <strong style="white-space:nowrap">DXM Agent</strong>
        </div>
        ${userBadge}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;color:#94a3b8;margin-bottom:6px">
        <span>${safe(hud.phase || '业务进度')}</span>
        <strong style="color:#e2e8f0">${progressText}</strong>
      </div>
      <div style="height:5px;border-radius:999px;background:rgba(148,163,184,.22);overflow:hidden;margin-bottom:10px">
        <i style="display:block;height:100%;width:${percent}%;background:${severityColor};border-radius:999px"></i>
      </div>
      <div style="display:grid;gap:6px">
        <div style="font-size:16px;font-weight:850;line-height:1.28">${safe(hud.human_title || hud.title || '等待任务')}</div>
        <div style="color:#e2e8f0;font-weight:700">${safe(hud.human_action || hud.action || '等待任务开始')}</div>
        ${recentHtml}
        <div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(148,163,184,.28);display:grid;grid-template-columns:54px minmax(0,1fr);gap:8px">
          <span style="color:#94a3b8">下一步</span>
          <strong style="color:#f8fafc">${safe(hud.human_next || hud.next_step || '等待下一步')}</strong>
          <span style="color:#94a3b8">范围</span>
          <strong style="color:#bbf7d0">${safe(hud.guard || '只保存不发布')}</strong>
        </div>
      </div>
    `;
  };
  if (!window.__dxmAgentHudObserver) {
    window.__dxmAgentHudObserver = new MutationObserver(() => {
      if (!document.getElementById(ID) && window.__dxmRenderAgentHud) {
        window.__dxmRenderAgentHud();
      }
    });
    window.__dxmAgentHudObserver.observe(document.documentElement, { childList: true, subtree: true });
  }
  if (!window.__dxmAgentHudWatchdog) {
    window.__dxmAgentHudWatchdog = window.setInterval(() => {
      const root = document.getElementById(ID);
      if (!root || root.dataset.dxmAgentHud !== 'active') {
        window.__dxmRenderAgentHud();
      }
    }, 1000);
  }
  window.__dxmRenderAgentHud();
})();
"""
