from __future__ import annotations

"""Post-SAVE trust matrix for E3 boundaries 7-10.

Stages: normal and single-field tamper are covered here. SAVE reserve->JIT and
JIT->begin flow through real BrowserAgentRuntime/SQLite ledger. Restart is
covered for both proven and unproven SAVE. VERIFY is read-only, so JIT->begin
is intentionally N/A; its persisted predecessor is checked at reservation.
"""

from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from playwright.sync_api import sync_playwright

from src import db
from src.execution.batch_dispatch_authority import (
    LiveDispatchFacts,
    save_verification_facts_from_frozen_authority,
)
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_independent_save_verification_pair,
)
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution import browser_agent_worker as browser_agent_worker_module
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import V1TaskRunner
from src.execution.dxm_login_flow import DxmLoginFlow
from src.state_machine.contracts import StateName
from tests.test_action_result_contract import (
    _as_path_a_editor,
    _valid_save_result,
    _valid_unpublished_result,
)
from tests.test_e3_batch_draft_save_gates import (
    DummyManager,
    E3WorkflowAdapter,
    _runner_context,
    _worktree_identity,
)
from src import repository as repository_module
from tests.test_login_flow import DummyLiveClient, _save_only_kwargs


@dataclass
class _PostSaveHarness:
    command: BrowserAgentCommand
    action_result: dict
    ledger: MutationDispatchLedger
    runtime: BrowserAgentRuntime
    adapter: "_VerifyProbeAdapter"
    live_facts_provider: Callable[[], LiveDispatchFacts]


class _VerifyProbeAdapter:
    requires_persistent_browser_agent = True

    def __init__(self) -> None:
        self.target_hash: str | None = None
        self.verify_calls = 0

    def browser_session_id(self) -> str:
        return "e3-test-browser-session"

    def current_mutation_identity(self) -> dict:
        return {
            "browser_session_id": self.browser_session_id(),
            "page_url": "https://www.dianxiaomi.com/web/smt/edit",
            "page_kind": "editor",
            "target_hash": self.target_hash,
        }

    def verify_not_published(self, **_kwargs):
        self.verify_calls += 1
        raise AssertionError("rejected VERIFY must not reach the external adapter")


class _CorruptingPostSaveAdapter(_VerifyProbeAdapter):
    def __init__(
        self,
        *,
        canonical_mutator=None,
        corrupt_authority: bool = True,
        explicit_failure_code: str | None = None,
    ) -> None:
        super().__init__()
        self.authorizer = None
        self.command_context: dict = {}
        self.mutation_scope_id: str | None = None
        self.save_operations = 0
        self.canonical_mutator = canonical_mutator
        self.corrupt_authority = corrupt_authority
        self.explicit_failure_code = explicit_failure_code

    def set_mutation_authorizer(self, authorizer, command_context=None):
        self.authorizer = authorizer
        self.command_context = dict(command_context or {})

    def clear_mutation_authorizer(self):
        self.authorizer = None

    def save_only(self, *, store_name, target_identity, defaults, **_kwargs):
        decision = self.authorizer(
            {
                **self.command_context,
                "mutation_action": "save_only_click",
            },
            lambda: self._save_operation(),
        )
        assert decision["ok"] is True
        assert decision["executed"] is True

        if self.explicit_failure_code:
            return {
                "ok": False,
                "action": "save_only",
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
                "store_name": store_name,
                "target_identity": deepcopy(target_identity),
                "contract_facts": {
                    "before_values": {
                        "store_name": store_name,
                        "target_identity": deepcopy(target_identity),
                    },
                    "after_values": {},
                    "postconditions": {"saved": False},
                    "evidence_observations": {
                        "save_result": {
                            "pre_dispatch_readback": {
                                "frozen_execution_readback": {
                                    "execution_payload_hash": defaults[
                                        "_frozen_execution_payload"
                                    ]["payload_hash"]
                                }
                            }
                        }
                    },
                    "failure_code": self.explicit_failure_code,
                    "recoverability": {
                        "kind": "manual_takeover",
                        "retryable": False,
                        "requires_page_reverify": True,
                        "reason": "SAVE was dispatched but complete success evidence was unavailable",
                    },
                },
            }

        canonical = _valid_save_result()
        E3WorkflowAdapter._bind_path_a_result(
            canonical,
            target_identity,
            store_name,
            "save_screenshot",
            execution_defaults=defaults,
        )
        canonical["page_identity"]["runtime_id"] = self.command_context["runtime_id"]
        canonical["page_identity"]["browser_session_id"] = self.browser_session_id()
        if callable(self.canonical_mutator):
            self.canonical_mutator(canonical)

        # Corrupt persisted post-dispatch authority at the external boundary.
        # The real ledger's record_success must reject this after exactly one
        # dispatched operation, and the worker must classify the result UNKNOWN.
        if self.corrupt_authority:
            with db.connection() as conn:
                conn.execute(
                    """
                    UPDATE mutation_dispatch_ledger
                       SET save_authority_json='{bad-json'
                     WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                    """,
                    (self.mutation_scope_id,),
                )
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT save_authority_json FROM mutation_dispatch_ledger WHERE mutation_scope_id=?",
                    (self.mutation_scope_id,),
                ).fetchone()
                assert row["save_authority_json"] == "{bad-json"

        evidence_ref = canonical["evidence"]["refs"][0]
        raw_ref = {key: evidence_ref[key] for key in ("path", "sha256", "size")}
        return {
            "ok": True,
            "action": "save_only",
            "page_url": "https://www.dianxiaomi.com/web/smt/edit",
            "store_name": store_name,
            "target_identity": deepcopy(target_identity),
            "save_evidence_ref": raw_ref,
            "evidence_ref": raw_ref,
            "contract_facts": {
                "before_values": canonical["before_values"],
                "after_values": canonical["after_values"],
                "postconditions": canonical["postconditions"],
                "evidence_observations": canonical["evidence"]["observations"],
                "failure_code": None,
                "recoverability": canonical["recoverability"],
            },
        }

    def _save_operation(self):
        self.save_operations += 1
        return {"dispatched": True, "external_write": False}


def _prepare_dispatched_save(tmp_path, monkeypatch) -> _PostSaveHarness:
    repo, task, _ids, _setup_runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    ) is True

    adapter = _VerifyProbeAdapter()
    runtime_box: dict[str, BrowserAgentRuntime] = {}
    git_head = "6" * 40
    worktree_identity = _worktree_identity(git_head, "runner-context")
    def live_facts_provider() -> LiveDispatchFacts:
        return LiveDispatchFacts(
            runtime_instance_id="e3-test-backend-runtime",
            browser_runtime_id=runtime_box["runtime"].runtime_id,
            browser_session_id=adapter.browser_session_id(),
            git_head=git_head,
            worktree_identity=worktree_identity,
            l2_status="passed",
            l2_evidence_fingerprint="9" * 64,
        )

    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=live_facts_provider,
    )
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=ledger)
    runtime_box["runtime"] = runtime
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    defaults = runner._execution_defaults(private, None, job=first_job)
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        defaults,
    )
    assert spec is not None
    action, _error_code, _error_title, params = spec
    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )
    adapter.target_hash = command.target_hash
    if isinstance(adapter, _CorruptingPostSaveAdapter):
        adapter.mutation_scope_id = command.mutation_scope_id

    assert runtime.reserve_command(command)["ok"] is True
    identity = adapter.current_mutation_identity()
    assert ledger.begin_dispatch(command, "save_only_click", identity).ok is True
    assert ledger.mark_dispatched(
        command,
        "save_only_click",
        {"dispatched": True, "external_write": False},
    ).ok is True

    action_result = _valid_save_result()
    E3WorkflowAdapter._bind_path_a_result(
        action_result,
        command.params["target_identity"],
        command.params["store_name"],
        "save_screenshot",
        execution_defaults=command.params["defaults"],
    )
    action_result["page_identity"]["runtime_id"] = command.runtime_id
    action_result["page_identity"]["browser_session_id"] = adapter.browser_session_id()
    return _PostSaveHarness(
        command,
        action_result,
        ledger,
        runtime,
        adapter,
        live_facts_provider,
    )


def _prepare_runtime_save(tmp_path, monkeypatch, adapter):
    repo, task, _ids, _setup_runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    monkeypatch.setattr(
        browser_agent_worker_module,
        "SCREENSHOT_DIR",
        repository_module.SCREENSHOT_DIR,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    ) is True
    runtime_box: dict[str, BrowserAgentRuntime] = {}
    git_head = "6" * 40
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: LiveDispatchFacts(
            runtime_instance_id="e3-test-backend-runtime",
            browser_runtime_id=runtime_box["runtime"].runtime_id,
            browser_session_id=adapter.browser_session_id(),
            git_head=git_head,
            worktree_identity=_worktree_identity(git_head, "runner-context"),
            l2_status="passed",
            l2_evidence_fingerprint="9" * 64,
        ),
    )
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=ledger)
    runtime_box["runtime"] = runtime
    runtime.set_mutation_authorizer(
        lambda _command, _context: {"ok": True, "reason_code": "OK"}
    )
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    defaults = runner._execution_defaults(private, None, job=first_job)
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        defaults,
    )
    assert spec is not None
    action, _error_code, _error_title, params = spec
    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )
    adapter.target_hash = command.target_hash
    if isinstance(adapter, _CorruptingPostSaveAdapter):
        adapter.mutation_scope_id = command.mutation_scope_id
    assert runtime.reserve_command(command)["ok"] is True
    return command, ledger, runtime


def _verify_command(
    harness: _PostSaveHarness,
    *,
    ledger_entry: dict,
    command_id: str,
) -> BrowserAgentCommand:
    authority = json.loads(ledger_entry["save_authority_json"])
    action_result_sha256 = ledger_entry.get("save_action_result_sha256") or "A" * 64
    context_entry = {
        **ledger_entry,
        "save_action_result_sha256": action_result_sha256,
    }
    context = save_verification_facts_from_frozen_authority(
        authority,
        save_command=harness.command,
        ledger_entry=context_entry,
        save_action_result_sha256=action_result_sha256,
    )
    return BrowserAgentCommand(
        command_id=command_id,
        idempotency_key=command_id,
        deadline="2099-01-01T00:00:00+00:00",
        expected_page="editor",
        runtime_id=harness.command.runtime_id,
        task_id=harness.command.task_id,
        job_id=harness.command.job_id,
        state="VERIFY_NOT_PUBLISHED",
        action="verify_not_published",
        execution_mode="batch_draft_save",
        params={"save_verification_context": context},
    )


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def test_verify_after_restart_uses_persisted_save_authority(tmp_path, monkeypatch):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        recorded = harness.ledger.record_success(
            harness.command,
            harness.action_result,
        )
        assert recorded.ok is True
        assert recorded.reason_code == "OK"
        entry = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        verify = _verify_command(
            harness,
            ledger_entry=entry,
            command_id="verify-after-restart",
        )

        restarted = MutationDispatchLedger(
            recover_inflight=False,
            live_facts_provider=harness.live_facts_provider,
        )
        decision = restarted.reserve_command(verify)

        assert decision.ok is True
        assert decision.reason_code == "OK"
        assert harness.adapter.verify_calls == 0
    finally:
        harness.runtime.shutdown()


def test_post_save_evidence_rejection_is_unknown_and_not_retryable(
    tmp_path,
    monkeypatch,
):
    adapter = _CorruptingPostSaveAdapter()
    command, ledger, runtime = _prepare_runtime_save(tmp_path, monkeypatch, adapter)
    try:
        with pytest.raises(RuntimeError, match="SAVE_SUCCESS_AUTHORITY_INVALID"):
            runtime.run(command, timeout_seconds=2)

        entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert adapter.save_operations == 1
        assert entry["status"] == "UNKNOWN"
        assert entry["outcome"]["reason_code"] == "SAVE_SUCCESS_AUTHORITY_INVALID"
        assert entry["save_action_result_sha256"] is None
        retry = ledger.begin_dispatch(command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        runtime.shutdown()


def test_explicit_post_dispatch_failure_is_immediately_unknown_and_not_retryable(
    tmp_path,
    monkeypatch,
):
    adapter = _CorruptingPostSaveAdapter(
        corrupt_authority=False,
        explicit_failure_code="SAVE_POST_DISPATCH_EVIDENCE_FAILED",
    )
    command, ledger, runtime = _prepare_runtime_save(tmp_path, monkeypatch, adapter)
    try:
        result = runtime.run(command, timeout_seconds=2)

        entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert result["ok"] is False
        assert result["failure_code"] == "SAVE_POST_DISPATCH_EVIDENCE_FAILED"
        assert adapter.save_operations == 1
        assert entry["status"] == "UNKNOWN"
        assert entry["outcome"]["reason_code"] == (
            "SAVE_POST_DISPATCH_EVIDENCE_FAILED"
        )
        assert entry["save_action_result_sha256"] is None
        retry = ledger.begin_dispatch(command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        runtime.shutdown()


def test_restart_recovers_unproven_dispatched_batch_save_to_unknown(
    tmp_path,
    monkeypatch,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        before = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        assert before["status"] == "DISPATCHED"
        assert before["save_action_result_sha256"] is None

        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == (
            "SAVE_ACTION_RESULT_MISSING_AFTER_RESTART"
        )
        retry = restarted.begin_dispatch(harness.command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        harness.runtime.shutdown()


@pytest.mark.parametrize(
    ("corruption", "expected_reason_code"),
    [
        ("action-result-hash-only", "SAVE_ACTION_RESULT_MISSING_AFTER_RESTART"),
        ("action-result-json-only", "SAVE_ACTION_RESULT_MISSING_AFTER_RESTART"),
        ("authority-missing", "SAVE_AUTHORITY_MISSING_AFTER_RESTART"),
        ("authority-invalid", "SAVE_AUTHORITY_INVALID_AFTER_RESTART"),
        ("action-result-digest-mismatch", "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"),
    ],
)
def test_restart_rejects_partial_or_corrupt_dispatched_save_proof(
    tmp_path,
    monkeypatch,
    corruption,
    expected_reason_code,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        result_json = _canonical_json(harness.action_result)
        result_sha256 = _canonical_sha256(harness.action_result)
        updates = {
            "action-result-hash-only": (result_sha256, None, "keep", "keep"),
            "action-result-json-only": (None, result_json, "keep", "keep"),
            "authority-missing": (None, None, None, None),
            "authority-invalid": (None, None, "keep", "{bad-json"),
            "action-result-digest-mismatch": (
                "B" * 64,
                result_json,
                "keep",
                "keep",
            ),
        }[corruption]
        result_digest, result_body, authority_digest, authority_body = updates
        with db.connection() as conn:
            current = conn.execute(
                """
                SELECT save_authority_sha256, save_authority_json
                  FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (harness.command.mutation_scope_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET save_action_result_sha256=?, save_action_result_json=?,
                       save_authority_sha256=?, save_authority_json=?
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (
                    result_digest,
                    result_body,
                    (
                        current["save_authority_sha256"]
                        if authority_digest == "keep"
                        else authority_digest
                    ),
                    (
                        current["save_authority_json"]
                        if authority_body == "keep"
                        else authority_body
                    ),
                    harness.command.mutation_scope_id,
                ),
            )

        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == expected_reason_code
        retry = restarted.begin_dispatch(harness.command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        harness.runtime.shutdown()


def test_restart_rejects_save_proof_without_success_timestamp(
    tmp_path,
    monkeypatch,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        assert harness.ledger.record_success(
            harness.command,
            harness.action_result,
        ).ok is True
        entry = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        verify = _verify_command(
            harness,
            ledger_entry=entry,
            command_id="verify-missing-save-time",
        )
        with db.connection() as conn:
            conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET save_success_recorded_at=NULL
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (harness.command.mutation_scope_id,),
            )

        verify_decision = MutationDispatchLedger(
            recover_inflight=False,
        ).reserve_command(verify)
        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )

        assert verify_decision.ok is False
        assert verify_decision.reason_code == (
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_MISSING"
        )
        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == (
            "SAVE_SUCCESS_RECORD_MISSING_AFTER_RESTART"
        )
    finally:
        harness.runtime.shutdown()


@pytest.mark.parametrize(
    "save_success_recorded_at",
    [
        "not-a-timestamp",
        "2026-08-12T12:00:00+08:00",
        "2000-01-01T00:00:00.000001Z",
    ],
)
def test_bad_save_success_timestamp_rejects_verify_and_recovers_unknown(
    tmp_path,
    monkeypatch,
    save_success_recorded_at,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        assert harness.ledger.record_success(
            harness.command,
            harness.action_result,
        ).ok is True
        entry = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        verify = _verify_command(
            harness,
            ledger_entry=entry,
            command_id="verify-bad-save-time",
        )
        with db.connection() as conn:
            conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET save_success_recorded_at=?
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (save_success_recorded_at, harness.command.mutation_scope_id),
            )

        verify_decision = MutationDispatchLedger(
            recover_inflight=False,
        ).reserve_command(verify)
        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )

        assert verify_decision.ok is False
        assert verify_decision.reason_code == (
            "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID"
        )
        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == (
            "SAVE_SUCCESS_RECORD_INVALID_AFTER_RESTART"
        )
    finally:
        harness.runtime.shutdown()


def test_restart_rejects_rehashed_single_save_command_rewrite(
    tmp_path,
    monkeypatch,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        assert harness.ledger.record_success(
            harness.command,
            harness.action_result,
        ).ok is True
        entry = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        payload = json.loads(entry["command_json"])
        payload["execution_mode"] = "single_save"
        with db.connection() as conn:
            conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET command_json=?, command_sha256=?
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (
                    _canonical_json(payload),
                    _canonical_sha256(payload),
                    harness.command.mutation_scope_id,
                ),
            )

        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )

        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == (
            "SAVE_COMMAND_INVALID_AFTER_RESTART"
        )
    finally:
        harness.runtime.shutdown()


def _frozen_readback(result: dict) -> dict:
    return result["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ]["frozen_execution_readback"]


def _mutate_binding(result: dict) -> None:
    _frozen_readback(result)["fields"][0]["ui_binding"] = "reviewed:weight"


def _mutate_observed_value(result: dict) -> None:
    _frozen_readback(result)["fields"][0]["observed_value_hash"] = "B" * 64


def _mutate_exact_save_count(result: dict, value: int) -> None:
    result["evidence"]["observations"]["save_result"]["exact_save_count"] = value


def _mutate_save_request_count(result: dict, value: int) -> None:
    result["evidence"]["observations"]["save_result"]["network_audit"][
        "save_request_count"
    ] = value


def _mutate_publish_request_count(result: dict) -> None:
    result["evidence"]["observations"]["save_result"]["network_audit"][
        "publish_request_count"
    ] = 1


@pytest.mark.parametrize(
    ("case_id", "mutator", "expected_reason", "expected_reason_code"),
    [
        (
            "stable-binding",
            _mutate_binding,
            "FROZEN_EXECUTION_READBACK_FIELD_MISMATCH",
            "FROZEN_EXECUTION_READBACK_FIELD_MISMATCH",
        ),
        (
            "frozen-value",
            _mutate_observed_value,
            "FROZEN_EXECUTION_READBACK_FIELD_MISMATCH",
            "FROZEN_EXECUTION_READBACK_FIELD_MISMATCH",
        ),
        (
            "exact-save-zero",
            lambda result: _mutate_exact_save_count(result, 0),
            "exactly one visible button",
            "ACTION_RESULT_CONTRACT_VIOLATION",
        ),
        (
            "exact-save-two",
            lambda result: _mutate_exact_save_count(result, 2),
            "exactly one visible button",
            "ACTION_RESULT_CONTRACT_VIOLATION",
        ),
        (
            "save-request-zero",
            lambda result: _mutate_save_request_count(result, 0),
            "one exact SAVE request",
            "ACTION_RESULT_CONTRACT_VIOLATION",
        ),
        (
            "save-request-two",
            lambda result: _mutate_save_request_count(result, 2),
            "one exact SAVE request",
            "ACTION_RESULT_CONTRACT_VIOLATION",
        ),
        (
            "publish-request",
            _mutate_publish_request_count,
            "one exact SAVE request",
            "ACTION_RESULT_CONTRACT_VIOLATION",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_post_save_single_field_tamper_is_unknown_and_not_retryable(
    tmp_path,
    monkeypatch,
    case_id,
    mutator,
    expected_reason,
    expected_reason_code,
):
    adapter = _CorruptingPostSaveAdapter(
        canonical_mutator=mutator,
        corrupt_authority=False,
    )
    command, ledger, runtime = _prepare_runtime_save(tmp_path, monkeypatch, adapter)
    try:
        with pytest.raises(RuntimeError, match=expected_reason) as exc_info:
            runtime.run(command, timeout_seconds=2)

        entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert adapter.save_operations == 1, case_id
        assert entry["status"] == "UNKNOWN"
        assert expected_reason_code in str(exc_info.value)
        assert entry["outcome"]["reason_code"] == expected_reason_code
        assert entry["save_action_result_sha256"] is None
        retry = ledger.begin_dispatch(command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        runtime.shutdown()


@pytest.mark.parametrize("exact_save_count", [0, 2])
def test_exact_save_count_is_rejected_before_any_click(
    tmp_path,
    monkeypatch,
    exact_save_count,
):
    flow = DxmLoginFlow(
        DummyLiveClient(logged_in=True),
        state_file=tmp_path / "runtime.json",
    )
    # The only seam replaces the production DevTools transport with a local
    # Playwright DOM evaluator. The production exact-button locator and SAVE
    # fail-closed path execute unchanged; no click implementation is mocked.
    monkeypatch.setattr(flow, "_is_headless", lambda: False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        buttons = "".join(
            '<button onclick="window.__saveClicks += 1">保存</button>'
            for _ in range(exact_save_count)
        )
        page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                body=(
                    "<style>button{width:96px;height:36px}</style>"
                    "<script>window.__saveClicks=0</script>"
                    f"{buttons}"
                ),
            ),
        )
        page.goto("https://www.dianxiaomi.com/web/smt/edit?id=70001")
        monkeypatch.setattr(
            flow,
            "_evaluate_visible_page_function_via_devtools",
            lambda local_page, script, _arg=None, **_kwargs: local_page.evaluate(
                script
            ),
        )

        result = flow._save_only_on_page(page, **_save_only_kwargs())

        assert result["stage"] == "save_only_failed"
        assert result["save_result"]["failure_code"] == (
            "MUTATION_CANCELLED_BEFORE_DISPATCH"
        )
        assert result["save_result"]["exact_save_count"] == exact_save_count
        assert result["save_result"]["clicked"] is False
        assert result["save_result"]["zero_click_proven"] is True
        assert page.evaluate("window.__saveClicks") == 0
        browser.close()


def test_proven_save_is_idempotent_and_stays_dispatched_after_restart(
    tmp_path,
    monkeypatch,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        first = harness.ledger.record_success(harness.command, harness.action_result)
        second = harness.ledger.record_success(harness.command, harness.action_result)
        assert first.ok is True and first.idempotent is False
        assert second.ok is True and second.idempotent is True

        restarted = MutationDispatchLedger()
        entry = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        assert entry["status"] == "DISPATCHED"
        assert entry["save_action_result_sha256"]
        retry = restarted.begin_dispatch(harness.command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_ALREADY_DISPATCHED"
    finally:
        harness.runtime.shutdown()


def test_forged_verify_after_restart_does_not_execute_or_change_save_ledger(
    tmp_path,
    monkeypatch,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    try:
        assert harness.ledger.record_success(
            harness.command,
            harness.action_result,
        ).ok is True
        restarted = MutationDispatchLedger(
            recover_inflight=False,
            live_facts_provider=harness.live_facts_provider,
        )
        before = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        honest = _verify_command(
            harness,
            ledger_entry=before,
            command_id="verify-honest-before-forgery",
        )
        forged_context = deepcopy(honest.params["save_verification_context"])
        forged_context["plan_snapshot_hash"] = "D" * 64
        forged_context["context_sha256"] = _canonical_sha256(
            {
                key: value
                for key, value in forged_context.items()
                if key != "context_sha256"
            }
        )
        forged = replace(
            honest,
            command_id="verify-forged-after-restart",
            idempotency_key="verify-forged-after-restart",
            params={"save_verification_context": forged_context},
        )

        decision = restarted.reserve_command(forged)
        after = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )

        assert decision.ok is False
        assert decision.reason_code == "SAVE_VERIFICATION_AUTHORITY_MISMATCH"
        assert harness.adapter.verify_calls == 0
        assert after == before
    finally:
        harness.runtime.shutdown()


@pytest.mark.parametrize(
    "captured_at",
    [
        "2026-07-15T08:00:00+08:00",
        "2026-07-15T07:59:59+08:00",
    ],
)
def test_verify_evidence_must_be_strictly_after_save(captured_at):
    save = _valid_save_result()
    verification = _valid_unpublished_result()
    verification["evidence"]["refs"][0]["captured_at"] = captured_at
    verify_operations = 0

    with pytest.raises(ActionResultContractError) as exc_info:
        validate_independent_save_verification_pair(save, verification)

    assert exc_info.value.reason_code == "ACTION_RESULT_CONTRACT_VIOLATION"
    assert "captured after SAVE" in str(exc_info.value)
    assert verify_operations == 0


def test_verify_evidence_after_save_is_accepted():
    save = _valid_save_result()
    verification = _valid_unpublished_result()

    pair = validate_independent_save_verification_pair(save, verification)

    assert pair["save"]["attempted_state"] == "SAVE_ONLY"
    assert pair["verification"]["attempted_state"] == "VERIFY_NOT_PUBLISHED"
