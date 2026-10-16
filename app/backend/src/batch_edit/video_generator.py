"""保留旧视频模块的导入兼容；旧执行入口始终拒绝，不拥有浏览器写入权。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.batch_edit.path_a_section_templates import VideoGenerationConfig
from src.batch_edit.native_video_inputs import (
    NATIVE_VIDEO_TRANSITIONS, resolve_native_video_inputs, validate_native_video_generation_rule,
)
from src.services.structured_logging import get_logger, log_event


LEGACY_VIDEO_EXECUTOR_NOT_BOUND = "LEGACY_VIDEO_EXECUTOR_NOT_BOUND"
_LOGGER = get_logger("legacy_video_generator")


class VideoGenerationError(StrEnum):
    """保留历史错误值，并明确区分未接生产的旧入口。"""

    QUOTA_EXHAUSTED = "quota_exhausted"
    PROGRAM_ERROR = "program_error"
    TIMEOUT = "timeout"
    PAGE_ERROR = "page_error"
    DISPATCH_UNCERTAIN = "dispatch_uncertain"
    EXECUTOR_NOT_BOUND = LEGACY_VIDEO_EXECUTOR_NOT_BOUND


@dataclass
class VideoGenerationResult:
    """兼容历史结果容器；该容器本身不证明生产动作或授予派发权。"""

    success: bool
    video_id: str | None = None
    error_type: VideoGenerationError | None = None
    error_message: str | None = None
    quota_remaining: int | None = None
    request_recorded: bool = False
    completion_state: str | None = None
    media_identity: dict[str, Any] | None = None
    execution_state: str = "unknown"
    evidence: dict[str, Any] = field(default_factory=dict)


class BatchVideoGenerator:
    """旧调用方的拒绝适配层；生成与投放必须经唯一 BrowserAgent 的独立命令。"""

    def __init__(self, dxm_client: Any | None = None):
        """仅接受旧构造参数，不绑定客户端或创建执行器。"""

    async def execute(
        self,
        page: Any,
        config: VideoGenerationConfig,
        ctx: dict[str, Any],
    ) -> VideoGenerationResult:
        """不读取页面、配置或上下文，所有旧配置均在零派发边界拒绝。"""
        log_event(_LOGGER, "legacy_video_execution_rejected", level="WARNING",
                  reason_code=LEGACY_VIDEO_EXECUTOR_NOT_BOUND, write_attempted=False)
        return VideoGenerationResult(
            success=False,
            error_type=VideoGenerationError.EXECUTOR_NOT_BOUND,
            error_message=LEGACY_VIDEO_EXECUTOR_NOT_BOUND,
            completion_state="not_bound",
            execution_state="blocked",
            evidence={"reason_code": LEGACY_VIDEO_EXECUTOR_NOT_BOUND,
                      "write_attempted": False, "execution_allowed": False},
        )
