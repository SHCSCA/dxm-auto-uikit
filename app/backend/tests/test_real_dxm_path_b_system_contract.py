"""Focused deterministic contract tests for the real DXM Path B flow.

These tests deliberately stop at pure contracts, temporary SQLite state, and
source invariants.  They never construct or mock the production DXM adapter,
never open a browser, and never treat fixture values as real acceptance proof.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from src import db
from src.batch_edit.full_product_edit_orchestrator import (
    EditPhase,
    FullProductEditOrchestrator,
    PhaseStatus,
)
from src.batch_edit.plan_snapshot_compiler import RELEASED_PLAN_EXECUTION_PATHS
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    build_mutation_scope_id,
)
from src.execution.canonical_receipt import (
    CanonicalReceipt,
    ContentFinalizeReceipt,
    FieldReadback,
    ReceiptPhase,
    ReceiptValidationError,
    SaveProof,
    SaveProofKind,
    SaveReceipt,
)
from src.execution.controlled_mutation_dispatch import ControlledMutationDispatch
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import SAVE1_TAIL, SAVE2_TAIL
from src.real_dxm_write_scope import (
    REAL_DXM_WRITE_APPROVAL_SCHEMA,
    REAL_DXM_WRITE_SCOPE_SCHEMA,
    RealDxmWriteScopeError,
    canonical_sha256,
    prepare_real_dxm_write_approval,
    prepare_real_dxm_write_scope,
    validate_real_dxm_write_approval,
    validate_real_dxm_write_scope,
)
from src.repository import Repository
from src.services.ownership_lock import ConcurrentEditorGuard
from src.state_machine.contracts import StateName


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-08-31T00:01:00Z"
ISSUED_AT = "2026-08-31T00:00:00Z"
APPROVED_AT = "2026-08-31T00:00:30Z"
EXPIRES_AT = "2026-08-31T00:10:00Z"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest().upper()
HASH_A = "A" * 64
HASH_B = "B" * 64
HASH_C = "C" * 64
HASH_D = "D" * 64
GIT_HEAD = "1" * 40


def _scope_facts(*, task_id: int = 701) -> dict:
    products = []
    for ordinal, product_id in enumerate((8101, 8102, 8103), start=1):
        products.append(
            {
                "ordinal": ordinal,
                "productId": product_id,
                "allowedFields": [
                    {
                        "field": "title",
                        "saveStage": "SAVE1",
                        "preimageSha256": HASH_A,
                        "expectedSha256": HASH_B,
                    },
                    {
                        "field": "semi_goods",
                        "saveStage": "SAVE2",
                        "preimageSha256": HASH_C,
                        "expectedSha256": HASH_D,
                    },
                ],
                "saves": [
                    {"stage": "SAVE1", "maxPhysicalRequests": 1},
                    {"stage": "SAVE2", "maxPhysicalRequests": 1},
                ],
            }
        )
    return {
        "schema": REAL_DXM_WRITE_SCOPE_SCHEMA,
        "stage": "execute",
        "path": "B",
        "issuedAt": ISSUED_AT,
        "expiresAt": EXPIRES_AT,
        "nonce": "scope-nonce-00000001",
        "account": {"accountContextHash": HASH_A},
        "shop": {"shopId": 91, "shopName": "Contract Shop"},
        "snapshot": {
            "snapshotId": 601,
            "snapshotSha256": HASH_B,
            "taskId": task_id,
        },
        "git": {"head": GIT_HEAD},
        "worktree": {
            "schema": "dxm.git-worktree.identity.v1",
            "git_head": GIT_HEAD,
            "git_dirty": False,
            "status_count": 0,
            "status_sha256": EMPTY_SHA256,
            "execution_file_count": 12,
            "execution_tree_sha256": HASH_C,
        },
        "runtime": {
            "runtimeInstanceId": "backend-runtime-contract",
            "browserRuntimeId": "browser-runtime-contract",
            "browserSessionId": "persistent-session-contract",
        },
        "l2": {"status": "passed", "evidenceFingerprint": HASH_D},
        "orderedProducts": products,
        "publishAllowed": False,
        "maxPhysicalRequestsPerSave": 1,
    }


def _prepared_scope(*, task_id: int = 701) -> dict:
    return prepare_real_dxm_write_scope(_scope_facts(task_id=task_id), now=NOW)


def _approval_facts(scope: dict) -> dict:
    return {
        "schema": REAL_DXM_WRITE_APPROVAL_SCHEMA,
        "stage": "execute",
        "scopeSha256": scope["scopeSha256"],
        "nonce": scope["nonce"],
        "approvedAt": APPROVED_AT,
        "expiresAt": scope["expiresAt"],
        "approvedBy": "contract-operator",
        "decision": "APPROVE",
    }


def _prepared_approval(scope: dict) -> dict:
    return prepare_real_dxm_write_approval(
        _approval_facts(scope),
        scope=scope,
        now=NOW,
    )


@pytest.fixture()
def contract_db(tmp_path, monkeypatch):
    db_path = tmp_path / "real-path-b-contract.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def _insert_draft_batch_task(task_id: int) -> None:
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, name, store_id, status, mode, publish_scene,
                total_jobs, completed_jobs, failed_jobs, payload_json,
                created_at, updated_at
            ) VALUES (?, 'Path B contract task', 91, 'draft',
                      'batch_draft_save', 'draft_only', 3, 0, 0,
                      '{}', ?, ?)
            """,
            (task_id, ISSUED_AT, ISSUED_AT),
        )


def _verified_section_receipt(seed: str = "a") -> dict:
    return {
        "success": True,
        "readback_proven": True,
        "receipt_sha256": seed * 64,
    }


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _field_readback(phase: str, timestamp: str) -> FieldReadback:
    return FieldReadback(
        field_key=f"{phase}_field",
        field_label=f"{phase} field",
        source="visible_production_runtime",
        before_value=f"{phase}-before",
        after_value=f"{phase}-expected",
        readback_proven=True,
        timestamp=timestamp,
    )


def _save_proofs(
    *,
    label: str,
    page_kind: str,
    request_at: str,
    response_at: str,
    screenshot_at: str,
    unpublished_at: str,
    target_hash: str,
) -> dict[SaveProofKind, SaveProof]:
    url = f"https://contract.invalid/{label}/save"
    common = {
        "file_path": None,
        "network_url": None,
        "network_method": None,
        "network_status": None,
        "body_sha256": None,
        "timestamp": None,
        "proven": True,
        "source": "visible_production_runtime",
        "target_hash": target_hash,
    }
    return {
        SaveProofKind.NETWORK_REQUEST: SaveProof(
            proof_kind=SaveProofKind.NETWORK_REQUEST,
            **(
                common
                | {
                    "network_url": url,
                    "network_method": "POST",
                    "body_sha256": _sha(f"{label}-request"),
                    "timestamp": request_at,
                    "evidence_id": f"{label}-network-request",
                }
            ),
        ),
        SaveProofKind.NETWORK_RESPONSE: SaveProof(
            proof_kind=SaveProofKind.NETWORK_RESPONSE,
            **(
                common
                | {
                    "network_url": url,
                    "network_method": "POST",
                    "network_status": 200,
                    "body_sha256": _sha(f"{label}-response"),
                    "timestamp": response_at,
                    "evidence_id": f"{label}-network-response",
                    "business_success": True,
                    "business_code": 0,
                    "business_message": "success",
                }
            ),
        ),
        SaveProofKind.PAGE_SUCCESS_SCREENSHOT: SaveProof(
            proof_kind=SaveProofKind.PAGE_SUCCESS_SCREENSHOT,
            **(
                common
                | {
                    "file_path": f"/contract-evidence/{label}.png",
                    "body_sha256": _sha(f"{label}-screenshot"),
                    "timestamp": screenshot_at,
                    "evidence_id": f"{label}-page-success",
                    "page_kind": page_kind,
                    "page_success": True,
                }
            ),
        ),
        SaveProofKind.UNPUBLISHED_STATUS: SaveProof(
            proof_kind=SaveProofKind.UNPUBLISHED_STATUS,
            **(
                common
                | {
                    "body_sha256": _sha(f"{label}-unpublished"),
                    "timestamp": unpublished_at,
                    "evidence_id": f"{label}-unpublished",
                    "unpublished": True,
                    "independent": True,
                }
            ),
        ),
    }


def _save_receipt(
    phase: ReceiptPhase,
    *,
    label: str,
    page_kind: str,
    ledger_entry_id: int,
    dispatched_at: str,
    completed_at: str,
    readback_at: str,
) -> SaveReceipt:
    target_hash = _sha("one-frozen-product-target")
    second = label == "save2"
    proofs = _save_proofs(
        label=label,
        page_kind=page_kind,
        request_at="2026-08-31T00:00:31Z" if second else "2026-08-31T00:00:11Z",
        response_at="2026-08-31T00:00:32Z" if second else "2026-08-31T00:00:12Z",
        screenshot_at="2026-08-31T00:00:33Z" if second else "2026-08-31T00:00:13Z",
        unpublished_at="2026-08-31T00:00:34Z" if second else "2026-08-31T00:00:14Z",
        target_hash=target_hash,
    )
    return SaveReceipt(
        save_phase=phase,
        save_lease_id=f"{label}-lease",
        action_grant_id=f"{label}-action-grant",
        mutation_id=f"{label}-mutation",
        ledger_entry_id=ledger_entry_id,
        target_hash=target_hash,
        dispatched_at=dispatched_at,
        completed_at=completed_at,
        physical_mutation_count=1,
        publish_request_count=0,
        published=False,
        proofs=proofs,
        field_readbacks=[_field_readback(label, readback_at)],
        save_result_ok=True,
        unresolved=False,
    )


def _canonical_receipt() -> CanonicalReceipt:
    receipt = CanonicalReceipt(
        task_id=701,
        job_id=801,
        product_id=8101,
        mode="batch_draft_save",
        claim_mark="path-b-contract-product-8101",
        started_at="2026-08-31T00:00:00Z",
        completed_at="2026-08-31T00:01:00Z",
    )
    for phase in (
        ReceiptPhase.CONTENT_FINALIZE_WHOLESALE,
        ReceiptPhase.CONTENT_FINALIZE_VIDEO,
        ReceiptPhase.CONTENT_FINALIZE_TRANSLATION,
        ReceiptPhase.SEMI_MANAGED_ENTRY,
        ReceiptPhase.ROLLBACK_PREPARATION,
    ):
        receipt.add_content_finalize_receipt(
            ContentFinalizeReceipt(
                phase=phase,
                action_grant_id=f"grant-{phase.value}",
                result_ok=True,
                unresolved=False,
                media_identity=(
                    "video-media-contract"
                    if phase == ReceiptPhase.CONTENT_FINALIZE_VIDEO
                    else None
                ),
            )
        )
    receipt.mark_rollback_prepared(_sha("rollback-preimage"))
    receipt.add_save_receipt(
        _save_receipt(
            ReceiptPhase.PHASE_1_FIRST_SAVE,
            label="save1",
            page_kind="editor",
            ledger_entry_id=1,
            dispatched_at="2026-08-31T00:00:10Z",
            completed_at="2026-08-31T00:00:20Z",
            readback_at="2026-08-31T00:00:15Z",
        )
    )
    receipt.add_save_receipt(
        _save_receipt(
            ReceiptPhase.PHASE_2_SECOND_SAVE,
            label="save2",
            page_kind="semi_managed",
            ledger_entry_id=2,
            dispatched_at="2026-08-31T00:00:30Z",
            completed_at="2026-08-31T00:00:40Z",
            readback_at="2026-08-31T00:00:35Z",
        )
    )
    receipt.mark_succeeded()
    return receipt


def _mutation_command() -> BrowserAgentCommand:
    values = {
        "command_id": "contract-command-1",
        "idempotency_key": "contract-idempotency-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "semi_managed",
        "runtime_id": "contract-runtime-1",
        "task_id": 11,
        "job_id": 22,
        "state": "SAVE_ONLY",
        "action": "save_only",
        "execution_mode": "single_save",
        "params": {},
        "authorization_lease_id": "contract-save-lease-1",
        "stage_task_facts_fingerprint": HASH_A,
        "target_hash": HASH_B,
        "authorization_fingerprint": HASH_C,
    }
    return BrowserAgentCommand(
        **values,
        mutation_scope_id=build_mutation_scope_id(
            authorization_lease_id=values["authorization_lease_id"],
            task_id=values["task_id"],
            job_id=values["job_id"],
            state=values["state"],
            action=values["action"],
        ),
    )


def test_scope_exact_keys_schema_digest_and_order_are_frozen() -> None:
    scope = _prepared_scope()
    unsigned = {key: value for key, value in scope.items() if key != "scopeSha256"}
    schema = json.loads(
        (REPO_ROOT / "config" / "real_dxm_write_scope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    scope_schema = schema["$defs"]["writeScope"]

    assert set(scope) == set(scope_schema["required"])
    assert scope_schema["additionalProperties"] is False
    assert scope["scopeSha256"] == canonical_sha256(unsigned)
    assert validate_real_dxm_write_scope(scope, now=NOW) == scope
    assert [item["productId"] for item in scope["orderedProducts"]] == [8101, 8102, 8103]
    assert all(
        [save["stage"] for save in item["saves"]] == ["SAVE1", "SAVE2"]
        for item in scope["orderedProducts"]
    )


@pytest.mark.parametrize(
    ("mutate", "detail_code"),
    [
        (
            lambda value: value.__setitem__("unexpected", True),
            "EXACT_KEYS_MISMATCH",
        ),
        (
            lambda value: value["orderedProducts"][0].__setitem__("productId", 9999),
            "SCOPE_HASH_MISMATCH",
        ),
        (
            lambda value: value["orderedProducts"][0].__setitem__("ordinal", 2),
            "PRODUCT_ORDER_INVALID",
        ),
        (
            lambda value: value["worktree"].__setitem__("git_head", "2" * 40),
            "WORKTREE_HEAD_MISMATCH",
        ),
    ],
)
def test_scope_rejects_tamper_order_or_identity_drift(mutate, detail_code: str) -> None:
    scope = _prepared_scope()
    mutate(scope)

    with pytest.raises(RealDxmWriteScopeError) as raised:
        validate_real_dxm_write_scope(scope, now=NOW)

    assert raised.value.reason_code == "SCOPE_REJECTED"
    assert raised.value.detail_code == detail_code


def test_scope_rejects_expiry_wildcard_and_publish_intent() -> None:
    with pytest.raises(RealDxmWriteScopeError) as expired:
        validate_real_dxm_write_scope(
            _prepared_scope(),
            now="2026-08-31T00:10:00Z",
        )
    assert expired.value.detail_code == "SCOPE_EXPIRED"

    wildcard = _scope_facts()
    wildcard["orderedProducts"][0]["allowedFields"][0]["field"] = "*"
    with pytest.raises(RealDxmWriteScopeError) as wildcard_rejected:
        prepare_real_dxm_write_scope(wildcard, now=NOW)
    assert wildcard_rejected.value.detail_code == "WILDCARD_FORBIDDEN"

    publishing = _scope_facts()
    publishing["publishAllowed"] = True
    with pytest.raises(RealDxmWriteScopeError) as publish_rejected:
        prepare_real_dxm_write_scope(publishing, now=NOW)
    assert publish_rejected.value.detail_code == "PUBLISH_INTENT_FORBIDDEN"

    publish_field = _scope_facts()
    publish_field["orderedProducts"][0]["allowedFields"][0]["field"] = "publishNow"
    with pytest.raises(RealDxmWriteScopeError) as field_rejected:
        prepare_real_dxm_write_scope(publish_field, now=NOW)
    assert field_rejected.value.detail_code == "PUBLISH_FIELD_FORBIDDEN"


def test_scope_rejection_has_zero_mutation_side_effect(contract_db) -> None:
    tampered = _prepared_scope()
    tampered["orderedProducts"][0]["productId"] = 9999
    wildcard = _scope_facts()
    wildcard["orderedProducts"][0]["allowedFields"][0]["field"] = "*"
    rejected_calls = (
        lambda: validate_real_dxm_write_scope(tampered, now=NOW),
        lambda: validate_real_dxm_write_scope(
            _prepared_scope(), now="2026-08-31T00:10:00Z"
        ),
        lambda: prepare_real_dxm_write_scope(wildcard, now=NOW),
    )
    for rejected_call in rejected_calls:
        with pytest.raises(RealDxmWriteScopeError) as rejected:
            rejected_call()
        assert rejected.value.reason_code == "SCOPE_REJECTED"

    with db.connection() as conn:
        mutation_count = conn.execute(
            "SELECT COUNT(*) AS count FROM mutation_dispatch_ledger"
        ).fetchone()["count"]
    assert mutation_count == 0


def test_approval_is_bound_to_exact_scope_nonce_and_hash() -> None:
    scope = _prepared_scope()
    approval = _prepared_approval(scope)
    schema = json.loads(
        (REPO_ROOT / "config" / "real_dxm_write_scope.schema.json").read_text(
            encoding="utf-8"
        )
    )["$defs"]["writeApproval"]

    assert set(approval) == set(schema["required"])
    assert schema["additionalProperties"] is False
    assert validate_real_dxm_write_approval(approval, scope=scope, now=NOW) == approval

    other_scope = deepcopy(approval)
    other_scope["scopeSha256"] = HASH_D
    with pytest.raises(RealDxmWriteScopeError) as wrong_scope:
        validate_real_dxm_write_approval(other_scope, scope=scope, now=NOW)
    assert wrong_scope.value.detail_code == "APPROVAL_SCOPE_HASH_MISMATCH"

    other_nonce = deepcopy(approval)
    other_nonce["nonce"] = "scope-nonce-00000002"
    with pytest.raises(RealDxmWriteScopeError) as wrong_nonce:
        validate_real_dxm_write_approval(other_nonce, scope=scope, now=NOW)
    assert wrong_nonce.value.detail_code == "APPROVAL_NONCE_MISMATCH"

    tampered_approver = deepcopy(approval)
    tampered_approver["approvedBy"] = "different-operator"
    with pytest.raises(RealDxmWriteScopeError) as wrong_approval_hash:
        validate_real_dxm_write_approval(tampered_approver, scope=scope, now=NOW)
    assert wrong_approval_hash.value.detail_code == "APPROVAL_HASH_MISMATCH"


def test_approval_consume_is_atomic_single_use_and_derives_six_leases(contract_db) -> None:
    task_id = 701
    _insert_draft_batch_task(task_id)
    scope = _prepared_scope(task_id=task_id)
    approval = _prepared_approval(scope)
    repository = Repository()
    assert repository.prepare_real_dxm_write_scope(scope)["ok"] is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: repository.consume_real_dxm_write_approval(
                    scope=scope,
                    approval=approval,
                ),
                range(2),
            )
        )

    accepted = [result for result in results if result["ok"] is True]
    rejected = [result for result in results if result["ok"] is False]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "SCOPE_REJECTED"
    assert rejected[0]["detail_code"] in {
        "APPROVAL_REPLAY",
        "SCOPE_NOT_PREPARED_OR_CONSUMED",
    }
    leases = accepted[0]["save_leases"]
    assert len(leases) == 6
    assert len({item["lease_id"] for item in leases}) == 6
    assert [item["save_stage"] for item in leases] == ["SAVE1", "SAVE2"] * 3
    assert all(item["single_use"] is True for item in leases)

    persisted = repository.get_real_dxm_write_scope(scope["scopeSha256"])
    assert persisted is not None
    assert persisted["status"] == "consumed"
    with db.connection() as conn:
        task_payload = db.loads(
            conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()[
                "payload_json"
            ],
            {},
        )
    bound = task_payload["real_dxm_write_authorization"]
    assert bound["publish_allowed"] is False
    assert bound["ordered_product_ids"] == [8101, 8102, 8103]
    assert bound["save_leases"] == leases


def test_writer_fence_is_shop_scoped_and_release_invalidates_owner(contract_db) -> None:
    guard = ConcurrentEditorGuard()
    first = guard.acquire_writer_fence("91", "task-701", generation=0)
    conflict = guard.acquire_writer_fence("91", "task-702", generation=0)

    assert first["acquired"] is True
    assert conflict == {
        "acquired": False,
        "conflict": True,
        "writer_fence_id": first["writer_fence_id"],
        "shop_id": "91",
        "task_id": "task-702",
        "generation": 0,
        "status": "conflict",
        "reason": "shop_writer_fence_held_by_other_task",
    }
    released = guard.release_writer_fence(first["writer_fence_id"], generation=0)
    assert released["status"] == "released"
    assert guard.validate_writer_fence("91", "task-701")["acquired"] is False
    assert guard.acquire_writer_fence("91", "task-702", generation=0)["acquired"] is True


def test_orchestrator_blocks_missing_failed_readback_or_receipt() -> None:
    orchestrator = FullProductEditOrchestrator()
    required = (
        *orchestrator.MAIN_SECTIONS,
        *orchestrator.CONTENT_FINALIZE_CAPABILITIES,
    )

    missing_ctx = orchestrator.create_context("8101", "91")
    missing = orchestrator.execute_phase(missing_ctx, EditPhase.PHASE_MAIN_EDIT, {})
    assert missing.status == PhaseStatus.BLOCKED
    assert missing.execute_receipt["missing_sections"] == list(required)

    for field_name, bad_value in (
        ("success", False),
        ("readback_proven", False),
        ("receipt_sha256", "not-a-receipt-hash"),
    ):
        results = {name: _verified_section_receipt() for name in required}
        results[required[0]][field_name] = bad_value
        ctx = orchestrator.create_context("8101", "91")
        blocked = orchestrator.execute_phase(ctx, EditPhase.PHASE_MAIN_EDIT, results)
        assert blocked.status == PhaseStatus.BLOCKED
        assert blocked.execute_receipt["failed_sections"] == [required[0]]


def test_orchestrator_requires_verified_native_gate_and_all_semi_sections() -> None:
    orchestrator = FullProductEditOrchestrator()
    modal_ctx = orchestrator.create_context("8101", "91")
    blocked = orchestrator.execute_phase(
        modal_ctx,
        EditPhase.PHASE_SAVE_MODAL,
        {
            "save_modal": {
                "save1_verified": True,
                "gate_outcome": "admitted",
                "semi_entry_triggered": True,
                "handshake_id": "handshake-1",
                "same_handshake": False,
            }
        },
    )
    assert blocked.status == PhaseStatus.BLOCKED

    semi_ctx = orchestrator.create_context("8101", "91")
    semi_results = {
        name: _verified_section_receipt("b") for name in orchestrator.SEMI_SECTIONS
    }
    semi_results.pop(orchestrator.SEMI_SECTIONS[-1])
    semi = orchestrator.execute_phase(semi_ctx, EditPhase.PHASE_SEMI_EDIT, semi_results)
    assert semi.status == PhaseStatus.BLOCKED
    assert semi.execute_receipt["missing_sections"] == [orchestrator.SEMI_SECTIONS[-1]]


def test_controlled_dispatch_delegates_to_one_ledger_and_cas_rejects_second_dispatch(
    contract_db,
) -> None:
    authority = MutationDispatchLedger(recover_inflight=False)
    dispatcher = ControlledMutationDispatch(ledger=authority, recover_inflight=False)
    command = _mutation_command()

    assert dispatcher.ledger is authority
    assert dispatcher.reserve_command(command).ok is True
    first = dispatcher.begin_dispatch(command, "save_only_click")
    duplicate = dispatcher.begin_dispatch(command, "save_only_click")

    assert first.ok is True
    assert duplicate.ok is False
    assert duplicate.reason_code == "MUTATION_ALREADY_DISPATCHING"
    source = inspect.getsource(ControlledMutationDispatch).casefold()
    assert "insert into" not in source
    assert "update mutation_dispatch_ledger" not in source
    assert "delete from" not in source
    main_source = (BACKEND_ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "ControlledMutationDispatch(" in main_source


def test_canonical_receipt_requires_two_independent_single_mutation_save_phases() -> None:
    receipt = _canonical_receipt()
    digest = receipt.finalize()

    assert len(digest) == 64
    assert len(receipt.content_finalize_receipts) == 5
    assert [item.save_phase for item in receipt.save_receipts] == [
        ReceiptPhase.PHASE_1_FIRST_SAVE,
        ReceiptPhase.PHASE_2_SECOND_SAVE,
    ]
    assert [item.physical_mutation_count for item in receipt.save_receipts] == [1, 1]
    assert [item.publish_request_count for item in receipt.save_receipts] == [0, 0]
    assert [item.published for item in receipt.save_receipts] == [False, False]
    assert [
        item.proofs[SaveProofKind.PAGE_SUCCESS_SCREENSHOT].page_kind
        for item in receipt.save_receipts
    ] == ["editor", "semi_managed"]
    assert receipt.save_receipts[0].evidence_identities().isdisjoint(
        receipt.save_receipts[1].evidence_identities()
    )
    persisted_saves = receipt.save_receipt_dicts()
    assert len(persisted_saves) == 2
    assert len({item["canonical_save_receipt_sha256"] for item in persisted_saves}) == 2


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (
            lambda receipt: setattr(
                receipt.save_receipts[0].proofs[SaveProofKind.NETWORK_RESPONSE],
                "business_success",
                False,
            ),
            "SAVE_BUSINESS_SUCCESS_NOT_PROVEN",
        ),
        (
            lambda receipt: setattr(
                receipt.save_receipts[0], "physical_mutation_count", 2
            ),
            "SAVE_PHYSICAL_MUTATION_COUNT_INVALID",
        ),
        (
            lambda receipt: setattr(receipt.save_receipts[0], "publish_request_count", 1),
            "SAVE_PUBLISH_NOT_PROVEN_ABSENT",
        ),
        (
            lambda receipt: setattr(
                receipt.save_receipts[1].proofs[SaveProofKind.PAGE_SUCCESS_SCREENSHOT],
                "page_kind",
                "editor",
            ),
            "SAVE_PAGE_KIND_MISMATCH",
        ),
    ],
)
def test_canonical_receipt_rejects_missing_business_proof_duplicate_write_or_publish(
    mutate,
    reason_code: str,
) -> None:
    receipt = _canonical_receipt()
    mutate(receipt)

    with pytest.raises(ReceiptValidationError) as raised:
        receipt.finalize()

    assert raised.value.reason_code == reason_code


def test_canonical_receipt_rejects_missing_or_reused_save_evidence() -> None:
    missing = _canonical_receipt()
    missing.save_receipts[0].proofs.pop(SaveProofKind.NETWORK_RESPONSE)
    with pytest.raises(ReceiptValidationError) as missing_proof:
        missing.finalize()
    assert missing_proof.value.reason_code == "SAVE_PROOF_REQUIRED"

    reused = _canonical_receipt()
    first_proofs = reused.save_receipts[0].proofs
    second_proofs = reused.save_receipts[1].proofs
    for kind in second_proofs:
        second_proofs[kind].evidence_id = first_proofs[kind].evidence_id
    with pytest.raises(ReceiptValidationError) as reused_proof:
        reused.finalize()
    assert reused_proof.value.reason_code == "SAVE_PHASE_EVIDENCE_REUSED"


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_runner_has_one_authority_context_lifetime_and_distinct_save_phases() -> None:
    source_files = list((BACKEND_ROOT / "src").rglob("*.py"))
    runner_calls = 0
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        runner_calls += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) == "V1TaskRunner"
        )
    assert runner_calls == 1

    runner_path = BACKEND_ROOT / "src" / "execution" / "v1_runner.py"
    runner_tree = ast.parse(runner_path.read_text(encoding="utf-8"), filename=str(runner_path))
    run_job = next(
        node
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_job"
    )
    create_context_calls = [
        node
        for node in ast.walk(run_job)
        if isinstance(node, ast.Call) and _call_name(node) == "create_context"
    ]
    state_loop = next(
        node
        for node in ast.walk(run_job)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Tuple)
        and [item.id for item in node.target.elts if isinstance(item, ast.Name)]
        == ["state_name", "step_name", "field_domain"]
    )
    assert len(create_context_calls) == 1
    assert create_context_calls[0].lineno < state_loop.lineno

    save1_states = [state for state, _label, _domain in SAVE1_TAIL]
    save2_states = [state for state, _label, _domain in SAVE2_TAIL]
    assert StateName.SAVE_ONLY in save1_states
    assert StateName.SAVE2_ONLY not in save1_states
    assert StateName.VERIFY_SAVE1_NOT_PUBLISHED in save1_states
    assert StateName.VERIFY_SAVE2_NOT_PUBLISHED not in save1_states
    assert StateName.SAVE2_ONLY in save2_states
    assert StateName.SAVE_ONLY not in save2_states
    assert StateName.VERIFY_SAVE2_NOT_PUBLISHED in save2_states
    assert StateName.VERIFY_SAVE1_NOT_PUBLISHED not in save2_states


def test_path_b_stays_release_locked_without_genuine_visible_runtime_provider() -> None:
    assert RELEASED_PLAN_EXECUTION_PATHS == frozenset({"A"})
    adapter_source = (
        BACKEND_ROOT / "src" / "execution" / "dxm_adapter.py"
    ).read_text(encoding="utf-8")
    assert 'proof.get("source") != "visible_production_runtime"' in adapter_source
    assert "PRODUCTION_CAPABILITY_NOT_CLOSED_" in adapter_source
    assert "evidence_sha256" in adapter_source


def test_flow_and_acceptance_scripts_use_public_api_without_db_or_private_adapter() -> None:
    flow_path = REPO_ROOT / "scripts" / "run-real-dxm-path-b-system-test.ps1"
    report_path = REPO_ROOT / "scripts" / "report" / "generate_v1_acceptance_record.py"
    assert flow_path.is_file()
    assert report_path.is_file()

    flow_source = flow_path.read_text(encoding="utf-8")
    report_source = report_path.read_text(encoding="utf-8")
    report_tree = ast.parse(report_source, filename=str(report_path))
    imported_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(report_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module or "").split(".")[0]
        for node in ast.walk(report_tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "sqlite3" not in imported_modules
    assert "src" not in imported_modules
    assert "/api/" in report_source
    assert "Invoke-RestMethod" in flow_source
    assert "/api/" in flow_source
    assert "db_path" not in report_source.casefold()
    flow_executable = "\n".join(
        line for line in flow_source.splitlines() if not line.lstrip().startswith("#")
    ).casefold()
    for forbidden in (
        "db_path",
        "sqlite3",
        "playwright",
        ".locator(",
        "dxm_adapter",
        "workflow_adapter.",
        "save_only(",
    ):
        assert forbidden not in flow_executable
