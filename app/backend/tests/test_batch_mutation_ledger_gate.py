from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from src.execution.browser_agent_protocol import (
    build_frozen_product_target_identity,
    mutation_target_hash,
)
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.v1_runner import V1TaskRunner
from tests.test_e3_batch_draft_save_gates import E3WorkflowAdapter, _runner_context
from tests.test_mutation_dispatch_ledger import _batch_save_command
from tests.test_v1_runner import DummyManager


_MISSING = object()


class _NoopAdapter:
    pass


class _RecordingSaveAdapter:
    def __init__(self) -> None:
        self.save_calls = 0

    def save_only(self, **_kwargs):
        self.save_calls += 1
        return {"ok": False, "error": "save_only must not be reached"}


class _PersistentE3Adapter(E3WorkflowAdapter):
    requires_persistent_browser_agent = True


class _LedgerDisabledRuntime:
    runtime_id = "ledger-disabled-runtime"

    def __init__(self, ledger_status=False) -> None:
        self.run_calls = 0
        self.ledger_status = ledger_status

    def status(self):
        status = {
            "runtimeId": self.runtime_id,
            "status": "idle",
            "healthy": True,
            "active": False,
        }
        if self.ledger_status is not _MISSING:
            status["mutationLedgerEnabled"] = self.ledger_status
        return status

    def run(self, *_args, **_kwargs):
        self.run_calls += 1
        raise RuntimeError("ledger-disabled runtime must not dispatch")


class _ReadOnlyAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def browser_session_id(self):
        return "readonly-session"

    def open_draft_box(self):
        self.calls += 1
        return {
            "ok": True,
            "action": "open_draft_box",
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "contract_facts": {
                "before_values": {"requested_page": "draft_box"},
                "after_values": {"observed_page": "draft_box"},
                "postconditions": {
                    "expected_page": True,
                    "business_marker_present": True,
                    "loading_absent": True,
                    "blocking_modal_absent": True,
                },
                "evidence_observations": {"page": "draft_box"},
                "failure_code": None,
                "recoverability": {
                    "kind": "none",
                    "retryable": False,
                    "requires_page_reverify": False,
                    "reason": None,
                },
            },
        }


def _batch_command_for_runtime(runtime: BrowserAgentRuntime):
    base = _batch_save_command()
    target = build_frozen_product_target_identity(
        product_id="70001",
        store_name="E3 Draft Shop",
        source_urls=["https://detail.1688.com/offer/70001.html"],
    )
    params = {
        **base.params,
        "product_query": "70001",
        "store_name": "E3 Draft Shop",
        "target_source_urls": list(target["source_urls"]),
        "target_identity": target,
    }
    return replace(
        base,
        runtime_id=runtime.runtime_id,
        params=params,
        target_hash=mutation_target_hash("save_only", params),
    )


def test_batch_draft_save_reserve_requires_mutation_ledger():
    runtime = BrowserAgentRuntime(_NoopAdapter(), mutation_ledger=None)
    command = _batch_command_for_runtime(runtime)

    try:
        decision = runtime.reserve_command(command)
    finally:
        runtime.shutdown()

    assert decision["ok"] is False
    assert decision["reasonCode"] == "MUTATION_LEDGER_REQUIRED"


def test_batch_draft_save_run_requires_mutation_ledger_before_adapter_execution():
    adapter = _RecordingSaveAdapter()
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=None)
    command = _batch_command_for_runtime(runtime)

    try:
        with pytest.raises(RuntimeError, match="MUTATION_LEDGER_REQUIRED"):
            runtime.run(command, timeout_seconds=1)
    finally:
        runtime.shutdown()

    assert adapter.save_calls == 0


@pytest.mark.parametrize(
    "ledger_status",
    [False, None, 1, "true", _MISSING],
    ids=["false", "none", "integer-one", "string-true", "missing"],
)
def test_batch_draft_save_v1_readiness_requires_exact_true_mutation_ledger(
    tmp_path,
    monkeypatch,
    ledger_status,
):
    repo, task, _ids, unused_runner, _unused_workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    adapter = _PersistentE3Adapter()
    runtime = _LedgerDisabledRuntime(ledger_status)
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
    )

    try:
        asyncio.run(runner.run_task(task["id"]))
    finally:
        unused_runner._workflow_executor.shutdown(wait=True)
        runner._workflow_executor.shutdown(wait=True)

    report = repo.list_reports(task["id"])[0]
    assert runtime.run_calls == 0
    assert "MUTATION_LEDGER_REQUIRED" in report["summary"]["blocked_reason"]


def test_batch_draft_save_cannot_bypass_ledger_readiness_with_unmarked_adapter(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, unused_runner, _unused_workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    adapter = E3WorkflowAdapter()
    runtime = _LedgerDisabledRuntime()
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
    )

    try:
        asyncio.run(runner.run_task(task["id"]))
    finally:
        unused_runner._workflow_executor.shutdown(wait=True)
        runner._workflow_executor.shutdown(wait=True)

    report = repo.list_reports(task["id"])[0]
    assert runtime.run_calls == 0
    assert "MUTATION_LEDGER_REQUIRED" in report["summary"]["blocked_reason"]


def test_read_only_browser_command_does_not_require_mutation_ledger():
    adapter = _ReadOnlyAdapter()
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=None)
    command = replace(
        _batch_save_command(),
        command_id="readonly-open-draft-box",
        idempotency_key="readonly-open-draft-box",
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=1,
        job_id=2,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        execution_mode="",
        params={},
        authorization_lease_id=None,
        stage_task_facts_fingerprint=None,
        target_hash=None,
        authorization_fingerprint=None,
        mutation_scope_id=None,
        execution_payload_hash=None,
    )

    try:
        assert runtime.reserve_command(command)["ok"] is True
        result = runtime.run(command, timeout_seconds=1)
    finally:
        runtime.shutdown()

    assert result["ok"] is True
    assert result["action"] == "open_draft_box"
    assert adapter.calls == 1
