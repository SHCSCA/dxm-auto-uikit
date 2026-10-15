from __future__ import annotations

from typing import Any

from src.services.structured_logging import get_logger, log_exception


_LOGGER = get_logger("browser_page_focus")


def bring_controlled_page_to_front(page: Any) -> bool:
    """只前置传入的受控页面，不搜索桌面窗口或重试。"""
    try:
        bring_to_front = getattr(page, "bring_to_front", None)
        if not callable(bring_to_front):
            raise RuntimeError("BROWSER_PAGE_FOCUS_METHOD_UNAVAILABLE")
        bring_to_front()
        return True
    except Exception as exc:
        log_exception(_LOGGER, "controlled_page_focus_failed", exc)
        return False
