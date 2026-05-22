from __future__ import annotations

import threading
import uuid
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
        with self._lock:
            self._close_locked()
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
                "screenshot": None,
                "created_at": _now(),
                "updated_at": _now(),
                "last_error": None,
            }
            self._state = state

        if launch_browser:
            self._launch_visible_browser(profile_dir, state)

        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._close_locked()
            self._state = self._empty_state()
            return dict(self._state)

    def update_hud(self, step: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state["hud"] = self._hud_state(step)
            self._state["updated_at"] = _now()
            page = self._page
            hud = dict(self._state["hud"])
        if page is not None:
            self._apply_hud(page, hud)
        return self.status()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            page = self._page
            session_id = self._state.get("session_id")
        if page is None or not session_id:
            return self.status()

        SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_ROOT / f"{session_id}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
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

    def _close_locked(self) -> None:
        for obj in (self._context, self._playwright):
            if obj is None:
                continue
            try:
                if obj is self._playwright:
                    obj.stop()
                else:
                    obj.close()
            except Exception:
                pass
        self._playwright = None
        self._context = None
        self._page = None

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
            "screenshot": None,
            "created_at": None,
            "updated_at": None,
            "last_error": None,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
