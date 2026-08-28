"""回滚管理器测试"""
import pytest
from unittest.mock import AsyncMock

from src.batch_edit.rollback_manager import (
    RollbackManager,
    BatchRollbackError,
    FieldChange,
    SectionSnapshot,
    RollbackResult,
)


class TestFieldChange:
    """字段变更测试"""

    def test_create_field_change(self):
        """创建字段变更"""
        change = FieldChange(
            section="basic_info",
            field_name="title",
            original_value="原标题",
            new_value="新标题",
            timestamp="2026-08-25T00:00:00Z",
        )
        assert change.section == "basic_info"
        assert change.field_name == "title"


class TestSectionSnapshot:
    """分区快照测试"""

    def test_create_snapshot(self):
        """创建分区快照"""
        snapshot = SectionSnapshot(
            section="basic_info",
            fields={"title": "测试标题", "category": "电子产品"},
            snapshot_time="2026-08-25T00:00:00Z",
        )
        assert snapshot.section == "basic_info"
        assert len(snapshot.fields) == 2


class TestRollbackManager:
    """回滚管理器测试"""

    @pytest.fixture
    def manager(self):
        return RollbackManager()

    def test_take_snapshot(self, manager):
        """拍摄快照测试"""
        fields = {"title": "测试标题", "category": "电子产品"}
        snapshot = manager.take_snapshot("basic_info", fields)

        assert snapshot.section == "basic_info"
        assert snapshot.fields == fields

    def test_record_change(self, manager):
        """记录变更测试"""
        manager.record_change(
            section="basic_info",
            field_name="title",
            original_value="原标题",
            new_value="新标题",
        )

        changes = manager.get_all_changes()
        assert len(changes) == 1
        assert changes[0].field_name == "title"

    def test_get_section_changes(self, manager):
        """获取分区变更测试"""
        manager.record_change("basic_info", "title", "原", "新")
        manager.record_change("basic_info", "category", "旧", "新")
        manager.record_change("attributes", "size", "S", "M")

        basic_info_changes = manager.get_section_changes("basic_info")
        assert len(basic_info_changes) == 2

    def test_clear(self, manager):
        """清除测试"""
        manager.take_snapshot("basic_info", {"title": "测试"})
        manager.record_change("basic_info", "title", "原", "新")

        manager.clear()

        assert manager.get_snapshot("basic_info") is None
        assert len(manager.get_all_changes()) == 0


class TestBatchRollbackError:
    """批量回滚异常测试"""

    def test_exception_properties(self):
        """异常属性测试"""
        changes = [
            FieldChange("basic_info", "title", "原", "新", "2026-08-25T00:00:00Z"),
        ]
        error = BatchRollbackError(
            reason="检测失败",
            field_changes=changes,
        )

        assert str(error) == "检测失败"
        assert error.reason == "检测失败"
        assert len(error.field_changes) == 1
