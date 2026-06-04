from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import DATA_DIR
from src.execution.browser_runtime import chrome_launch_options


PROFILE_ROOT = DATA_DIR / "browser_profiles" / "agent_console"
SCREENSHOT_ROOT = DATA_DIR / "screenshots" / "agent_console"
DEFAULT_TARGET_URL = "https://www.dianxiaomi.com/"
MAX_NETWORK_EVENTS = 120
MAX_ACTION_EVENTS = 160


class AgentConsoleService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = self._empty_state()
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-console")

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            page = self._page
        if page is not None:
            try:
                state["current_url"] = page.url
                state["page_title"] = page.title()
            except Exception as exc:
                state["last_error"] = str(exc)
        return state

    def start(
        self,
        *,
        task_id: int | None = None,
        target_url: str | None = None,
        launch_browser: bool = True,
        step: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            self._run_browser_op(lambda: self._launch_visible_browser(profile_dir, state))

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
        next_step: str | None = None,
        screenshot_path: str | None = None,
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

            hud = self._hud_state({
                "title": step_name,
                "state": step_code,
                "action": _step_action(field_domain, mode),
                "next_step": next_step or "等待状态机推进",
                "store_name": store_name or "Dang Kang",
                "guard": "只保存不发布",
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
            if page_url:
                self._state["current_url"] = page_url
            if screenshot_url:
                self._state["screenshot"] = screenshot_url
            self._state["updated_at"] = _now()

        return {**self._compact_status(), "ok": True, "updated": True, "reason": "action_recorded"}

    def snapshot(self) -> dict[str, Any]:
        return self.refresh_frame()

    def request_manual_takeover(self) -> dict[str, Any]:
        with self._lock:
            if not self._state.get("active"):
                return {**dict(self._state), "ok": False, "reason": "agent_console_inactive"}
            self._state["manual_takeover"] = True
            self._state["manual_takeover_started_at"] = _now()
            self._state["updated_at"] = _now()
            page = self._page

        if page is not None:
            try:
                self._run_browser_op(lambda: page.bring_to_front())
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
            self._state["updated_at"] = _now()
        return self._record_manual_takeover_event(action="release_agent", label="交还 Agent")

    def refresh_frame(self) -> dict[str, Any]:
        with self._lock:
            page = self._page
            session_id = self._state.get("session_id")
        if page is None or not session_id:
            return self.status()

        SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_ROOT / f"{session_id}.png"
        try:
            self._run_browser_op(lambda: page.screenshot(path=str(path), full_page=False))
            with self._lock:
                self._state["screenshot"] = str(path)
                self._state["last_frame_at"] = _now()
                try:
                    self._state["current_url"] = page.url
                    self._state["page_title"] = page.title()
                except Exception as exc:
                    self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()
        return self.status()

    def control_browser(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action") or "").strip().lower()
        with self._lock:
            if not self._state.get("active"):
                return {**dict(self._state), "ok": False, "reason": "agent_console_inactive"}
            page = self._page
            if page is None:
                return {**dict(self._state), "ok": False, "reason": "browser_page_unavailable"}

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
            x = _required_int(command, "x")
            y = _required_int(command, "y")
            page.mouse.click(x, y)
            return {"action": action, "x": x, "y": y}
        if action == "selector_click":
            selector = _required_text(command, "selector", "selector is required for selector_click")
            page.locator(selector).click(timeout=8000)
            return {"action": action, "selector": selector}
        if action == "selector_fill":
            selector = _required_text(command, "selector", "selector is required for selector_fill")
            text = _required_text(command, "text", "text is required for selector_fill")
            page.locator(selector).fill(text, timeout=8000)
            return {"action": action, "selector": selector, "text_length": len(text)}
        if action == "type":
            text = str(command.get("text") or "")
            if not text:
                raise ValueError("text is required for type")
            page.keyboard.type(text)
            return {"action": action, "text_length": len(text)}
        if action == "press":
            key = str(command.get("key") or "").strip()
            if not key:
                raise ValueError("key is required for press")
            page.keyboard.press(key)
            return {"action": action, "key": key}
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
            self._state["updated_at"] = _now()

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
            page.add_init_script(HUD_INIT_SCRIPT)
            page.goto(state["target_url"], wait_until="domcontentloaded", timeout=45000)
            self._apply_hud(page, state["hud"])
            with self._lock:
                if self._state.get("session_id") != state["session_id"] or not self._state.get("active"):
                    self._close_browser_objects(context, playwright)
                    return
                self._playwright = playwright
                self._context = context
                self._page = page
                self._state["browser_visible"] = True
                self._state["current_url"] = page.url
                self._state["page_title"] = page.title()
                self._state["updated_at"] = _now()
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
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

    def _apply_hud(self, page, hud: dict[str, Any]) -> None:
        page.evaluate(
            """
            (hud) => {
              window.__dxmAgentHudState = hud;
              if (window.__dxmRenderAgentHud) window.__dxmRenderAgentHud();
            }
            """,
            hud,
        )

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

    def _run_browser_op(self, operation):
        return self._browser_executor.submit(operation).result(timeout=90)

    def _hud_state(self, step: dict[str, Any] | None) -> dict[str, Any]:
        step = step or {}
        return {
            "title": step.get("title") or step.get("label") or "Agent Console 待命",
            "state": step.get("state") or step.get("code") or "WAITING",
            "action": step.get("action") or step.get("detail") or "等待后端状态机推送",
            "next_step": step.get("next_step") or "等待下一步",
            "store_name": step.get("store_name") or "Dang Kang",
            "guard": step.get("guard") or "只保存不发布",
            "updated_at": _now(),
        }

    def _empty_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "session_id": None,
            "task_id": None,
            "profile_dir": None,
            "launch_browser": False,
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
  window.__dxmAgentHudState = window.__dxmAgentHudState || {};
  window.__dxmRenderAgentHud = () => {
    const hud = window.__dxmAgentHudState || {};
    let root = document.getElementById(ID);
    if (!root) {
      root = document.createElement('div');
      root.id = ID;
      root.style.cssText = [
        'position:fixed',
        'top:18px',
        'right:18px',
        'z-index:2147483647',
        'width:360px',
        'max-width:calc(100vw - 36px)',
        'font:13px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif',
        'color:#1d252d',
        'background:rgba(255,255,255,.96)',
        'border:1px solid rgba(25,37,51,.18)',
        'border-left:5px solid #2563eb',
        'border-radius:8px',
        'box-shadow:0 18px 42px rgba(21,26,33,.22)',
        'padding:13px',
        'pointer-events:none'
      ].join(';');
      document.documentElement.appendChild(root);
    }
    const safe = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    root.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <span style="width:12px;height:12px;border-radius:50%;background:#2563eb;box-shadow:0 0 0 5px #e7efff"></span>
        <strong>${safe(hud.title || 'Agent Console')}</strong>
      </div>
      <div style="display:grid;gap:7px">
        <div><span style="color:#66717f">店铺</span><div style="font-weight:750">${safe(hud.store_name || 'Dang Kang')}</div></div>
        <div><span style="color:#66717f">当前状态</span><div style="font-weight:750">${safe(hud.state || 'WAITING')}</div></div>
        <div><span style="color:#66717f">正在执行</span><div style="font-weight:750">${safe(hud.action || '等待状态机')}</div></div>
        <div><span style="color:#66717f">下一步</span><div style="font-weight:750">${safe(hud.next_step || '等待下一步')}</div></div>
      </div>
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid #d8dde5;display:flex;justify-content:space-between;gap:10px">
        <span style="color:#66717f">发布隔离</span><strong>${safe(hud.guard || '只保存不发布')}</strong>
      </div>
    `;
  };
  window.__dxmRenderAgentHud();
})();
"""
