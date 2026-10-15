from types import SimpleNamespace

import pytest

from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.services.structured_logging import StructuredLogFormatter


@pytest.mark.parametrize("failure, reason", [
    ("operation_exception", "MUTATION_OUTCOME_UNKNOWN"),
    ("operation_result", "MUTATION_OUTCOME_UNKNOWN"),
    ("mark_dispatched_exception", "MUTATION_LEDGER_COMMIT_FAILED"),
    ("mark_dispatched_rejected", "MUTATION_LEDGER_COMMIT_FAILED"),
])
def test_unknown_record_failure_is_logged_without_retry_or_success(monkeypatch, caplog, failure, reason):
    class Ledger:
        begins = 0
        unknowns = 0

        def begin_dispatch(self, *args, **kwargs):
            self.begins += 1
            return SimpleNamespace(ok=True, entry={"id": 1})

        def mark_dispatched(self, *args):
            if failure == "mark_dispatched_exception":
                raise OSError("dispatch commit failed")
            return SimpleNamespace(ok=False, reason_code="LEDGER_CAS_REJECTED")

        def mark_unknown(self, *args):
            self.unknowns += 1
            raise OSError("unknown commit failed token=secret-test-value")

    ledger = Ledger()
    runtime = BrowserAgentRuntime(object(), mutation_ledger=ledger)
    monkeypatch.setattr(runtime, "_mutation_dispatch_rejection_locked", lambda *args: None)
    monkeypatch.setattr(runtime, "_bound_mutation_identity", lambda *args, **kwargs: ({}, None))
    monkeypatch.setattr(runtime, "_refresh_batch_account_context", lambda *args: None)
    command = BrowserAgentCommand(command_id="unknown-log-command", task_id=7, job_id=9,
        state="SAVE_ONLY", action="save_only", idempotency_key="unknown-once",
        deadline="2099-01-01T00:00:00Z", expected_page="semi_managed", runtime_id="unit-runtime", params={})
    lease = SimpleNamespace(context=SimpleNamespace(command_id=command.command_id),
        authorizer=lambda *args: {"ok": True}, adapter=object())
    calls = []

    def operation():
        calls.append("dispatch")
        if failure == "operation_exception":
            raise RuntimeError("remote outcome unknown")
        return False if failure == "operation_result" else {"dispatched": True}

    with pytest.raises(RuntimeError, match=reason):
        runtime._authorize_mutation(lease, command, {"mutation_action": "save_only_click"}, operation)

    assert calls == ["dispatch"]
    assert ledger.begins == ledger.unknowns == 1
    assert lease.mutation_dispatch_inflight is False
    records = [record for record in caplog.records if record.getMessage() == "mutation_unknown_record_failed"]
    assert len(records) == 1
    assert records[0].event_fields == {"command_id": command.command_id, "task_id": 7, "job_id": 9,
        "mutation_action": "save_only_click", "phase": failure}
    rendered = StructuredLogFormatter().format(records[0])
    assert "secret-test-value" not in rendered
    assert "OSError" in rendered
