"""半托管执行器测试"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.batch_edit.semi_managed_executor import (
    SemiManagedExecutor,
    SemiManagedError,
    SemiManagedCheckResult,
    SemiManagedEditResult,
)
from src.batch_edit.path_a_section_templates import SemiManagedConfig


class TestSemiManagedConfig:
    """半托管配置测试"""

    def test_default_config(self):
        """默认配置测试"""
        config = SemiManagedConfig()
        assert config.enabled is False
        assert config.countries_strategy == "all"
        assert config.use_batch_fill is True

    def test_custom_countries(self):
        """自定义国家测试"""
        config = SemiManagedConfig(
            enabled=True,
            countries_strategy="custom",
            custom_countries=("DE", "FR", "IT"),
        )
        assert config.countries_strategy == "custom"
        assert "DE" in config.custom_countries


class TestSemiManagedCheckResult:
    """半托管检测结果测试"""

    def test_pass_result(self):
        """通过结果测试"""
        result = SemiManagedCheckResult(
            check_passed=True,
            modal_sequence=["semi_tip", "detect_success"],
        )
        assert result.check_passed is True

    def test_fail_result(self):
        """失败结果测试"""
        result = SemiManagedCheckResult(
            check_passed=False,
            error_type=SemiManagedError.DETECT_FAILED,
            error_message="店小秘返回：仿品检测未通过",
        )
        assert result.check_passed is False
        assert result.error_type == SemiManagedError.DETECT_FAILED


class TestSemiManagedExecutor:
    """半托管执行器测试"""

    @pytest.fixture
    def executor(self):
        return SemiManagedExecutor()

    @pytest.fixture
    def mock_page(self):
        return AsyncMock()

    def test_disabled_returns_pass(self, executor, mock_page):
        """禁用时返回通过"""
        config = SemiManagedConfig(enabled=False)
        ctx = MagicMock()

        result = asyncio.run(executor.execute_check(mock_page, config, ctx))

        assert result.check_passed is True
