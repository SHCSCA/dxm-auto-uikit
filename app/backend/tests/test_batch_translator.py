"""翻译执行器测试"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.batch_edit.translator import (
    BatchTranslator,
    TranslateResult,
    TranslateError,
)
from src.batch_edit.path_a_section_templates import AutoTranslateConfig


class TestAutoTranslateConfig:
    """翻译配置测试"""

    def test_default_config(self):
        """默认配置测试"""
        config = AutoTranslateConfig()
        assert config.enabled is False
        assert config.translate_type == "normal"
        assert config.direction == "zh_en"
        assert "title" in config.apply_to
        assert "attributes" in config.apply_to
        assert "descriptions" in config.apply_to
        assert "custom_names" in config.apply_to

    def test_ai_translate_type(self):
        """AI翻译类型测试"""
        config = AutoTranslateConfig(
            enabled=True,
            translate_type="ai",
        )
        assert config.translate_type == "ai"


class TestTranslateResult:
    """翻译结果测试"""

    def test_success_result(self):
        """成功结果测试"""
        result = TranslateResult(
            success=True,
            translated_fields=5,
            field_changes={
                "title": {"before": "测试标题", "after": "Test Title"},
            },
        )
        assert result.success is True
        assert result.translated_fields == 5

    def test_failure_result(self):
        """失败结果测试"""
        result = TranslateResult(
            success=False,
            error_message="翻译执行失败：超时",
        )
        assert result.success is False
        assert result.error_message is not None


class TestBatchTranslator:
    """翻译执行器测试"""

    @pytest.fixture
    def translator(self):
        return BatchTranslator()

    @pytest.fixture
    def mock_page(self):
        return AsyncMock()

    def test_disabled_returns_skipped(self, translator, mock_page):
        """禁用时返回 success=False 且 dispatch_state=skipped。

        安全门禁：disabled 不应被误判为完成。
        """
        config = AutoTranslateConfig(enabled=False)
        ctx = MagicMock()

        result = asyncio.run(translator.execute(mock_page, config, ctx))

        assert result.success is False
        assert result.dispatch_state == "skipped"
        assert result.error_type == TranslateError.FIELD_MISSING
