"""Tests for V1TaskRunner `batch_draft_save` mode step sequences.

These tests verify the V1TaskRunner task-based execution model satisfies the
batch invariants:

1. Path A is single-save: one SAVE_ONLY, followed by WRITE_REPORT/RELEASE_LOCK
2. Path B is **dual-save**: SAVE1 (主编辑) → SAVE_INTENT_MODAL (原生门)
   → 半托管 → SAVE2 → WRITE_REPORT/RELEASE_LOCK
3. Path A must NOT include semi-managed steps
4. Path B must include all semi-managed steps
5. SAVE_INTENT_MODAL appears between SAVE1's verification and the semi-managed steps
6. WRITE_REPORT and RELEASE_LOCK appear at the end exactly once

The 15 skipped tests in `test_batch_edit_api.py` remain skipped because they
test the old BatchExecutionRuntime API (410 Gone).
"""
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
        """Path B must include all semi-managed steps in order."""
        semi_states = {
            StateName.ENABLE_SEMI_MANAGED,
            StateName.OPEN_SEMI_MANAGED_PAGE,
            StateName.FILL_SEMI_GOODS,
            StateName.FILL_SEMI_VARIANTS,
        }
        path_b_states = set(_names(BATCH_PATH_B_STEPS))
        assert semi_states.issubset(path_b_states), (
            f"Path B must include all semi-managed steps, but missing: "
            f"{semi_states - path_b_states}"
        )

    def test_path_b_semi_step_order(self):
        """Path B semi-managed steps must follow order: enable → open → goods → variants."""
        state_names = _names(BATCH_PATH_B_STEPS)
        enable_idx = state_names.index(StateName.ENABLE_SEMI_MANAGED)
        open_idx = state_names.index(StateName.OPEN_SEMI_MANAGED_PAGE)
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
        semi_idx = state_names.index(StateName.ENABLE_SEMI_MANAGED)
        save2_idx = state_names.index(StateName.SAVE2_ONLY)

        # 顺序合同：SAVE1 < 原生门 < 半托管 < SAVE2
        assert save1_idx < modal_idx < semi_idx < save2_idx, (
            f"Path B 必须按 SAVE1[{save1_idx}] → 原生门[{modal_idx}] "
            f"→ 半托管[{semi_idx}] → SAVE2[{save2_idx}] 顺序执行"
        )

    def test_path_b_save2_tail_closes_with_write_report_and_release(self):
        """SAVE2 must be followed by VERIFY_SAVE_RESULT, VERIFY_NOT_PUBLISHED, then WRITE_REPORT, RELEASE_LOCK."""
        state_names = _names(BATCH_PATH_B_STEPS)

        save2_idx = state_names.index(StateName.SAVE2_ONLY)
        # After SAVE2 we expect VERIFY_SAVE_RESULT, VERIFY_NOT_PUBLISHED, WRITE_REPORT, RELEASE_LOCK
        tail = state_names[save2_idx:]
        assert StateName.VERIFY_SAVE_RESULT in tail[:3]
        assert StateName.VERIFY_NOT_PUBLISHED in tail[:4]
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
