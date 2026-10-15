from __future__ import annotations

from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError, validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.batch_dispatch_authority import (
    DispatchAuthorityDecision, DispatchAuthorityError, LiveDispatchFacts, _deep_freeze, _reject,
    _validate_authorization, content_action_execution_payload, snapshot_row_authority_in_transaction,
)
from src.execution.browser_agent_protocol import validate_browser_agent_command
from src.execution.current_authority_facts import load_current_authority_facts
from src.services.structured_logging import get_logger, log_exception


_TRANSLATION_STEPS = frozenset({"BATCH_TRANSLATE_EXECUTE"})
_LOGGER = get_logger("content_action_authority")


def validate_current_translation_authority(conn, authority, *, command, observation):
    """只读消费实际翻译派发来源，不创建 lease、账本或保存授权。"""
    from src.execution.mutation_dispatch_ledger import MutationDispatchLedger

    try:
        if (command.state != "BATCH_TRANSLATE_EXECUTE" or command.action != "translate_editor_content"
                or command.execution_mode != "batch_draft_save" or command.expected_page != "editor"):
            _reject("AUTH_CONTENT_SOURCE_COMMAND_INVALID")
        validate_browser_agent_command(command)
        canonical, task = load_current_authority_facts(conn, authority, allowed_steps=_TRANSLATION_STEPS)
        if (canonical["command"]["payload"] != command.to_payload()
                or task["payload"].get("path") != "B"
                or canonical["queue"]["guard"]["current_job_id"] != command.job_id):
            _reject("AUTH_CONTENT_SOURCE_COMMAND_INVALID")
        job = next((item for item in task["jobs"] if item["id"] == command.job_id), None)
        if job is None or command.task_id != task["id"]:
            _reject("AUTH_CONTENT_SOURCE_COMMAND_INVALID")
        execution = content_action_execution_payload(task, job, command.state)
        validate_frozen_execution_defaults(command.params.get("defaults"), expected_payload=execution)
        if (canonical["execution"]["payload"] != execution
                or canonical["execution"]["payload_hash"] != execution["payload_hash"]
                or command.execution_payload_hash != execution["payload_hash"]):
            _reject("AUTH_CONTENT_SOURCE_POLICY_DRIFT")
        rows = conn.execute("SELECT * FROM mutation_dispatch_ledger WHERE command_id=?", (command.command_id,)).fetchall()
        if len(rows) != 1:
            _reject("AUTH_CONTENT_SOURCE_LEDGER_NOT_UNIQUE")
        snapshot = snapshot_row_authority_in_transaction(conn, task["id"])
        persisted = MutationDispatchLedger.validate_translation_source(dict(rows[0]), command, observation,
            snapshot_row_authority_sha256=canonical_sha256(snapshot))
        if persisted != canonical:
            _reject("AUTH_CONTENT_SOURCE_LEDGER_DRIFT")
        # 重读已消费作用域与父批准，严格复用 SAVE1 派生 grant 的验证；不采样或声称新运行事实。
        runtime, code, l2 = canonical["runtime"], canonical["code_identity"], canonical["l2"]
        frozen_live = LiveDispatchFacts(**runtime, **code, l2_status=l2["status"],
                                        l2_evidence_fingerprint=l2["evidence_fingerprint"])
        stage, context, lease, parent, save_stage = _validate_authorization(
            conn, task, canonical["snapshot"]["plan_snapshot"], job, command, frozen_live)
        expected = canonical["authorization"]
        if (save_stage != "SAVE1" or stage != expected["stage_task_facts"]
                or context != expected["authorization_context"] or lease != expected["lease_authority"]
                or parent != expected["parent_lease_authority"]):
            _reject("AUTH_CONTENT_SOURCE_GRANT_DRIFT")
    except DispatchAuthorityError as exc:
        log_exception(_LOGGER, "translation_source_authority_rejected", exc, reason_code=exc.reason_code)
        return DispatchAuthorityDecision(False, exc.reason_code)
    except (FrozenExecutionContractError, KeyError, TypeError, ValueError) as exc:
        log_exception(_LOGGER, "translation_source_authority_rejected", exc)
        return DispatchAuthorityDecision(False, "AUTH_CONTENT_SOURCE_INVALID")
    except Exception as exc:
        log_exception(_LOGGER, "translation_source_authority_failed", exc)
        raise
    frozen = _deep_freeze(canonical)
    return DispatchAuthorityDecision(True, "OK", authority=frozen, authority_sha256=canonical_sha256(frozen))
