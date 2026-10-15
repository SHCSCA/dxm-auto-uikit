"""隔离回放的能力边界，缺少生产事实时不得生成成功回执。"""

from __future__ import annotations

from typing import Any, NoReturn

from src.services.structured_logging import get_logger, log_event


logger = get_logger("replay_capability_boundary")


class ReplayCapabilityBoundary:
    def _reject_unmodeled_action(self, action: str) -> NoReturn:
        log_event(logger, "replay_capability_unavailable", level="ERROR", action=action)
        raise RuntimeError(f"CLOSED_LOOP_CAPABILITY_NOT_MODELED:{action}")

    def prepare_rollback(self, **_kwargs: Any) -> dict[str, Any]:
        return self._reject_unmodeled_action("prepare_rollback")

    def validate_editor_wholesale(self, **_kwargs: Any) -> dict[str, Any]:
        return self._reject_unmodeled_action("validate_editor_wholesale")

    def translate_editor_content(self, **_kwargs: Any) -> dict[str, Any]:
        return self._reject_unmodeled_action("translate_editor_content")

    def generate_editor_video(self, **_kwargs: Any) -> dict[str, Any]:
        return self._reject_unmodeled_action("generate_editor_video")
