"""批发配置器测试"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.batch_edit.wholesale_filler import (
    WholesaleFiller,
    WholesaleResult,
    WholesaleError,
)
from src.batch_edit.path_a_section_templates import WholesaleConfig


class TestWholesaleConfig:
    """批发配置测试"""

    def test_default_config(self):
        """默认配置测试"""
        config = WholesaleConfig()
        assert config.enabled is False
        assert config.min_quantity == 3
        assert config.discount_percent == 10
        assert config.deduction_method == "payment"

    def test_valid_config(self):
        """有效配置测试"""
        config = WholesaleConfig(
            enabled=True,
            min_quantity=10,
            discount_percent=20,
            deduction_method="order",
        )
        assert config.enabled is True
        assert config.min_quantity == 10
        assert config.discount_percent == 20
        assert config.deduction_method == "order"


class TestWholesaleResult:
    """批发结果测试"""

    def test_configured_result(self):
        """已配置结果测试"""
        result = WholesaleResult(
            success=True,
            configured=True,
            evidence={"min_quantity": 10},
        )
        assert result.success is True
        assert result.configured is True


class TestWholesaleFiller:
    """批发配置器测试"""

    @pytest.fixture
    def filler(self):
        return WholesaleFiller()

    @pytest.fixture
    def mock_page(self):
        return AsyncMock()

    def test_disabled_returns_skipped(self, filler, mock_page):
        """禁用时返回 success=False 且 configured/validated/readback_verified 均为 False。

        安全门禁：disabled 不应被误判为已验证。
        """
        config = WholesaleConfig(enabled=False)
        ctx = MagicMock()

        result = asyncio.run(filler.execute(mock_page, config, ctx))

        assert result.success is False
        assert result.configured is False
        assert result.validated is False
        assert result.readback_verified is False
        assert result.error_type == WholesaleError.VALIDATION_FAILED
