from copy import deepcopy
from pathlib import Path

import pytest

from src.state_machine.batch_draft_authorization import (
    BatchDraftAuthorizationError,
    authorization_context_fingerprint,
    build_authorization_context,
    build_batch_draft_save_task_facts,
    compare_authorization_context,
    verify_authorization_context,
    verify_exact_batch_draft_save_task_facts,
)


def _worktree_identity(git_head: str, seed: str = "batch") -> dict:
    return {
        "schema": "dxm.git-worktree.identity.v1",
        "git_head": git_head,
        "git_dirty": True,
        "status_count": 7,
        "status_sha256": (seed[0].upper() if seed else "A") * 64,
        "execution_file_count": 91,
        "execution_tree_sha256": "F" * 64,
    }


def _task_facts() -> dict:
    return build_batch_draft_save_task_facts(
        task_id=11,
        store_id=22,
        product_ids=[101, 102, 103],
        plan_snapshot_id=33,
        plan_snapshot_hash="A" * 64,
        path="A",
    )


def _authorization_context(*, approved_by: str = "ops-owner") -> dict:
    git_head = "b" * 40
    return build_authorization_context(
        stage_task_facts=_task_facts(),
        runtime_instance_id="batch-backend-runtime",
        browser_session_id="batch-browser-session",
        git_head=git_head,
        worktree_identity=_worktree_identity(git_head),
        l2_evidence_fingerprint="C" * 64,
        approved_by=approved_by,
    )


def test_batch_task_facts_are_exact_and_path_a_only() -> None:
    facts = _task_facts()

    assert verify_exact_batch_draft_save_task_facts(facts) == {
        "ok": True,
        "reason_code": "OK",
    }
    assert facts["product_ids"] == [101, 102, 103]

    with pytest.raises(BatchDraftAuthorizationError) as raised:
        build_batch_draft_save_task_facts(
            task_id=11,
            store_id=22,
            product_ids=[101],
            plan_snapshot_id=33,
            plan_snapshot_hash="A" * 64,
            path="B",
        )
    assert raised.value.reason_code == "BATCH_PATH_FORBIDDEN"


def test_batch_task_facts_reject_identity_and_digest_drift() -> None:
    duplicate = deepcopy(_task_facts())
    duplicate["product_ids"] = [101, 101, 103]
    assert verify_exact_batch_draft_save_task_facts(duplicate) == {
        "ok": False,
        "reason_code": "BATCH_PRODUCT_DUPLICATE",
    }

    tampered = deepcopy(_task_facts())
    tampered["plan_snapshot_id"] = 99
    assert verify_exact_batch_draft_save_task_facts(tampered) == {
        "ok": False,
        "reason_code": "STAGE_TASK_FACTS_FINGERPRINT_MISMATCH",
    }


def test_batch_v2_authorization_binds_worktree_and_compares_exactly() -> None:
    expected = _authorization_context()
    different_approver = _authorization_context(approved_by="other-operator")

    assert expected["schema"] == "dxm.authorization.context.v2"
    assert authorization_context_fingerprint(expected) == expected["fingerprint"]
    assert verify_authorization_context(expected) == {
        "ok": True,
        "reason_code": "OK",
    }
    assert compare_authorization_context(expected, expected) == {
        "ok": True,
        "reason_code": "OK",
    }
    assert compare_authorization_context(expected, different_approver) == {
        "ok": False,
        "reason_code": "AUTH_CONTEXT_MISMATCH",
    }


def test_batch_v2_authorization_rejects_worktree_head_or_fact_tampering() -> None:
    git_head = "b" * 40
    with pytest.raises(BatchDraftAuthorizationError) as raised:
        build_authorization_context(
            stage_task_facts=_task_facts(),
            runtime_instance_id="batch-backend-runtime",
            browser_session_id="batch-browser-session",
            git_head=git_head,
            worktree_identity=_worktree_identity("d" * 40),
            l2_evidence_fingerprint="C" * 64,
            approved_by="ops-owner",
        )
    assert raised.value.reason_code == "WORKTREE_IDENTITY_HEAD_MISMATCH"

    tampered = deepcopy(_authorization_context())
    tampered["stage_task_facts"]["product_ids"][0] = 999
    assert verify_authorization_context(tampered)["ok"] is False


def test_batch_authorization_source_has_no_removed_claim_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "state_machine"
        / "batch_draft_authorization.py"
    ).read_text(encoding="utf-8")

    for removed_token in (
        "claim_only",
        "claim_to_draft",
        "stage_a",
        "stage_b",
    ):
        assert removed_token not in source
