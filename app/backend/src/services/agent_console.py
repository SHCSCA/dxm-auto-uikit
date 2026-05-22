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
                "screenshot": None,
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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            page = self._page
            session_id = self._state.get("session_id")
        if page is None or not session_id:
            return self.status()

        SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_ROOT / f"{session_id}.png"
        try:
            self._run_browser_op(lambda: page.screenshot(path=str(path), full_page=True))
            with self._lock:
                self._state["screenshot"] = str(path)
                self._state["updated_at"] = _now()
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = str(exc)
                self._state["updated_at"] = _now()
        return self.status()

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
            "screenshot": None,
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
                "screenshot": self._state.get("screenshot"),
                "updated_at": self._state.get("updated_at"),
                "last_error": self._state.get("last_error"),
            }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step_action(field_domain: str | None, mode: str | None) -> str:
    parts = [part for part in (field_domain, mode) if part]
    return " / ".join(parts) if parts else "状态机步骤推进"


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
