"""视频生成器测试"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.batch_edit.video_generator import (
    BatchVideoGenerator,
    VideoGenerationError,
    VideoGenerationResult,
)
from src.batch_edit.path_a_section_templates import VideoGenerationConfig


class TestVideoGenerationConfig:
    """视频生成配置测试"""

    def test_default_config(self):
        """默认配置测试"""
        config = VideoGenerationConfig()
        assert config.enabled is False
        assert config.failure_strategy == "pause"
        assert config.max_wait_seconds == 300
        assert config.poll_interval_seconds == 5

    def test_ignore_strategy(self):
        """忽略策略测试"""
        config = VideoGenerationConfig(
            enabled=True,
            failure_strategy="ignore",
        )
        assert config.failure_strategy == "ignore"

    def test_pause_strategy(self):
        """暂停策略测试"""
        config = VideoGenerationConfig(
            enabled=True,
            failure_strategy="pause",
        )
        assert config.failure_strategy == "pause"


class TestVideoGenerationResult:
    """视频生成结果测试"""

    def test_success_result(self):
        """成功结果测试"""
        result = VideoGenerationResult(
            success=True,
            video_id="vid_123",
            quota_remaining=24,
        )
        assert result.success is True
        assert result.video_id == "vid_123"
        assert result.error_type is None

    def test_quota_exhausted_result(self):
        """配额用完结果测试"""
        result = VideoGenerationResult(
            success=True,
            quota_remaining=0,
            error_type=VideoGenerationError.QUOTA_EXHAUSTED,
            error_message="店小秘返回：免费额度已用完，继续执行",
        )
        assert result.success is True
        assert result.error_type == VideoGenerationError.QUOTA_EXHAUSTED

    def test_failure_result(self):
        """失败结果测试"""
        result = VideoGenerationResult(
            success=False,
            error_type=VideoGenerationError.PROGRAM_ERROR,
            error_message="店小秘返回：视频生成失败",
        )
        assert result.success is False
        assert result.error_type == VideoGenerationError.PROGRAM_ERROR


class TestBatchVideoGenerator:
    """视频生成器测试"""

    @pytest.fixture
    def generator(self):
        return BatchVideoGenerator()

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        return page

    def test_disabled_returns_skipped(self, generator, mock_page):
        """禁用时返回 success=False 且 execution_state=skipped。

        安全门禁：disabled 不应被误判为完成 — 上游 bundle_composer 据此
        阻断 finalize，避免未真实执行的步骤被放行。
        """
        config = VideoGenerationConfig(enabled=False)
        ctx = MagicMock()

        result = asyncio.run(generator.execute(mock_page, config, ctx))

        assert result.success is False
        assert result.completion_state == "disabled"
        assert result.execution_state == "skipped"
        assert result.error_type == VideoGenerationError.PROGRAM_ERROR

    def test_quota_exhausted_with_ignore_strategy(self, generator, mock_page):
        """配额用完 + ignore策略 = 继续执行"""
        config = VideoGenerationConfig(
            enabled=True,
            failure_strategy="ignore",
        )
        ctx = MagicMock()

        # Mock 配额检查返回 exhausted=True
        async def mock_check_quota(page):
            return {"exhausted": True, "remaining": 0}
        generator._check_quota = mock_check_quota

        result = asyncio.run(generator.execute(mock_page, config, ctx))

        # 应该成功（继续执行）
        assert result.success is True
        assert result.error_type is None
        assert result.completion_state == "quota_exhausted"
