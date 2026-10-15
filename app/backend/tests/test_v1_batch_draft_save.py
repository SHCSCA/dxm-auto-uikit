"""验证唯一 Runner 的阶段顺序；双保存证据与原生入口必须分别闭合。"""
from __future__ import annotations

import pytest

from src.execution.v1_runner import (
    BATCH_DRAFT_SAVE_STEPS,
    BATCH_PATH_B_STEPS,
    V1_STEPS,
)
from src.state_machine.contracts import StateName
from collections import Counter


def _names(steps):
    return [step[0] for step in steps]


class TestBatchDraftSaveStepSequences:
    """Verify step sequences for batch_draft_save mode."""

    def test_path_a_excludes_semi_managed_steps(self):
        """Path A must not include semi-managed steps.

        This is the core invariant: Path A is plain editing only, no semi-managed.
        """
        semi_states = {
            StateName.ENABLE_SEMI_MANAGED,
            StateName.OPEN_SEMI_MANAGED_PAGE,
            StateName.FILL_SEMI_GOODS,
            StateName.FILL_SEMI_VARIANTS,
        }
        path_a_states = set(_names(BATCH_DRAFT_SAVE_STEPS))
        assert semi_states.isdisjoint(path_a_states), (
            f"Path A must not include semi-managed steps, but found: "
            f"{semi_states & path_a_states}"
        )

    def test_path_b_includes_semi_managed_steps(self):
        """原生门取代旧单保存的直接入口，保留半托管字段阶段。"""
        semi_states = {
            StateName.ENABLE_SEMI_MANAGED,
            StateName.SAVE_INTENT_MODAL,
            StateName.FILL_SEMI_GOODS,
            StateName.FILL_SEMI_VARIANTS,
        }
        path_b_states = set(_names(BATCH_PATH_B_STEPS))
        assert semi_states.issubset(path_b_states), (
            f"Path B must include all semi-managed steps, but missing: "
            f"{semi_states - path_b_states}"
        )

    def test_path_b_semi_step_order(self):
        """主页面启用半托管后，经原生门才进入第二页填写。"""
        state_names = _names(BATCH_PATH_B_STEPS)
        enable_idx = state_names.index(StateName.ENABLE_SEMI_MANAGED)
        open_idx = state_names.index(StateName.SAVE_INTENT_MODAL)
        goods_idx = state_names.index(StateName.FILL_SEMI_GOODS)
        variants_idx = state_names.index(StateName.FILL_SEMI_VARIANTS)

        assert enable_idx < open_idx < goods_idx < variants_idx, (
            "Semi-managed steps must be in order: "
            "ENABLE → OPEN → FILL_GOODS → FILL_VARIANTS"
        )

    def test_path_a_is_single_save(self):
        """Path A is single-save: SAVE_ONLY appears exactly once."""
        path_a_states = _names(BATCH_DRAFT_SAVE_STEPS)
        assert path_a_states.count(StateName.SAVE_ONLY) == 1, (
            "Path A must have exactly one SAVE_ONLY"
        )
        # Path A does NOT use SAVE2_ONLY
        assert StateName.SAVE2_ONLY not in path_a_states
        # Path A does NOT use SAVE_INTENT_MODAL
        assert StateName.SAVE_INTENT_MODAL not in path_a_states

    def test_path_b_dual_save_contract(self):
        """Path B is dual-save: SAVE1 → SAVE_INTENT_MODAL → 半托管 → SAVE2.

        Contract: SAVE_ONLY (SAVE1) must appear, then SAVE_INTENT_MODAL
        (原生门：点击"编辑半托管信息"), then semi-managed steps, then SAVE2_ONLY.
        """
        state_names = _names(BATCH_PATH_B_STEPS)

        save1_idx = state_names.index(StateName.SAVE_ONLY)
        modal_idx = state_names.index(StateName.SAVE_INTENT_MODAL)
        enable_idx = state_names.index(StateName.ENABLE_SEMI_MANAGED)
        semi_idx = state_names.index(StateName.FILL_SEMI_GOODS)
        save2_idx = state_names.index(StateName.SAVE2_ONLY)

        # 原生入口已包含打开第二页，不得再调用旧复合保存入口。
        assert enable_idx < save1_idx
        assert StateName.OPEN_SEMI_MANAGED_PAGE not in state_names
        assert save1_idx < modal_idx < semi_idx < save2_idx, (
            f"Path B 必须按 SAVE1[{save1_idx}] → 原生门[{modal_idx}] "
            f"→ 半托管[{semi_idx}] → SAVE2[{save2_idx}] 顺序执行"
        )

    def test_path_b_save2_tail_closes_with_write_report_and_release(self):
        """第二次保存必须使用独立阶段的未发布证明。"""
        state_names = _names(BATCH_PATH_B_STEPS)

        save2_idx = state_names.index(StateName.SAVE2_ONLY)
        # SAVE1 证据不能代替 SAVE2，两个阶段分别验证。
        tail = state_names[save2_idx:]
        assert StateName.VERIFY_SAVE_RESULT in tail[:3]
        assert StateName.VERIFY_SAVE2_NOT_PUBLISHED in tail[:4]
        assert StateName.VERIFY_SAVE1_NOT_PUBLISHED not in tail
        assert StateName.WRITE_REPORT in tail[-3:]
        assert state_names[-1] == StateName.RELEASE_LOCK

    def test_write_report_and_release_appear_once(self):
        """WRITE_REPORT and RELEASE_LOCK must appear exactly once each."""
        for label, steps in (
            ("Path A", BATCH_DRAFT_SAVE_STEPS),
            ("Path B", BATCH_PATH_B_STEPS),
        ):
            states = _names(steps)
            assert states.count(StateName.WRITE_REPORT) == 1, (
                f"{label}: WRITE_REPORT must appear exactly once"
            )
            assert states.count(StateName.RELEASE_LOCK) == 1, (
                f"{label}: RELEASE_LOCK must appear exactly once"
            )
            assert states[-1] == StateName.RELEASE_LOCK, (
                f"{label}: RELEASE_LOCK must be the last step"
            )

    def test_path_a_starts_with_precheck_open_draft(self):
        """Both sequences start with PRECHECK_CONFIG + OPEN_DRAFT_LIST navigation."""
        pa = _names(BATCH_DRAFT_SAVE_STEPS)
        pb = _names(BATCH_PATH_B_STEPS)
        assert pa[0] == StateName.PRECHECK_CONFIG
        assert pb[0] == StateName.PRECHECK_CONFIG
        assert StateName.OPEN_DRAFT_LIST in pa[:5]
        assert StateName.OPEN_DRAFT_LIST in pb[:5]
