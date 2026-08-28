from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from src.db import connection, loads
from src.execution.batch_command_contract import (
    BatchCommandContractError,
    validate_current_batch_queue_guard,
    validate_save_verification_context,
)
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_action_result_envelope,
)
from src.execution.batch_dispatch_authority import (
    DispatchAuthorityError,
    LiveDispatchFacts,
    save_verification_facts_from_frozen_authority,
    snapshot_row_authority_fingerprint_in_transaction,
    validate_current_live_facts_against_frozen_authority,
    validate_current_task_against_frozen_authority,
    validate_in_transaction as validate_dispatch_authority_in_transaction,
)
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    browser_agent_command_sha256,
    build_mutation_id,
    mutation_ordinal_for_command,
    validate_browser_agent_command,
)
from src.execution.e3_authority_contract import (
    StrictUtcTimestampError,
    authorization_lease_authority_fingerprint,
    authorization_lease_is_active,
    parse_strict_utc_timestamp,
    utc_now_iso,
)
from src.state_machine.batch_draft_authorization import verify_authorization_context
from src.utils import now_iso


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(value: Any) -> str:
    import hashlib

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _validate_frozen_batch_save_action_result(
    action_result: Any,
    *,
    command: BrowserAgentCommand,
    authority: dict[str, Any],
) -> dict[str, Any]:
    """Validate SAVE evidence against its exact persisted command authority."""

    runtime_authority = authority.get("runtime")
    browser_session_id = (
        runtime_authority.get("browser_session_id")
        if isinstance(runtime_authority, dict)
        else None
    )
    expected_payload = (
        command.params.get("defaults", {}).get("_frozen_execution_payload")
        if isinstance(command.params.get("defaults"), dict)
        else None
    )
    return validate_action_result_envelope(
        action_result,
        expected_state="SAVE_ONLY",
        expected_action="save_only",
        expected_page="editor",
        execution_mode="batch_draft_save",
        expected_runtime_id=command.runtime_id,
        expected_browser_session_id=(
            browser_session_id if isinstance(browser_session_id, str) else None
        ),
        expected_execution_payload=(
            expected_payload if isinstance(expected_payload, dict) else None
        ),
        expected_target_identity=command.params.get("target_identity"),
        expected_store_name=command.params.get("store_name"),
        expected_target_hash=command.target_hash,
    )


def _dispatched_batch_save_proof_failure(row: dict[str, Any]) -> str | None:
    """Return a stable recovery reason when a dispatched SAVE lacks full proof."""

    raw_command = row.get("command_json")
    try:
        command_payload = json.loads(raw_command) if isinstance(raw_command, str) else None
        if not isinstance(command_payload, dict):
            raise ValueError("command payload missing")
        command = BrowserAgentCommand(**command_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "SAVE_COMMAND_INVALID_AFTER_RESTART"
    if not (
        command.execution_mode == "batch_draft_save"
        and command.state == "SAVE_ONLY"
        and command.action == "save_only"
    ):
        return "SAVE_COMMAND_INVALID_AFTER_RESTART"
    try:
        plan = validate_browser_agent_command(command)
        ordinal = mutation_ordinal_for_command(command, "save_only_click")
        expected_binding = {
            "mutation_id": build_mutation_id(
                mutation_scope_id=str(command.mutation_scope_id),
                state=command.state,
                ordinal=ordinal,
                mutation_action="save_only_click",
            ),
            "mutation_scope_id": str(command.mutation_scope_id),
            "mutation_action": "save_only_click",
            "ordinal": ordinal,
            "command_state": command.state,
            "command_action": command.action,
            "task_id": str(command.task_id),
            "job_id": str(command.job_id),
            "authorization_lease_id": str(command.authorization_lease_id),
            "authorization_lease_fingerprint": str(
                command.authorization_lease_fingerprint
            ),
            "stage_task_facts_fingerprint": str(
                command.stage_task_facts_fingerprint
            ),
            "target_hash": str(command.target_hash),
            "authorization_fingerprint": str(command.authorization_fingerprint),
            "command_id": str(command.command_id),
            "runtime_id": str(command.runtime_id),
        }
        command_is_valid = (
            bool(plan)
            and plan.get("save_only_click") == ordinal
            and all(row.get(key) == value for key, value in expected_binding.items())
            and raw_command == _canonical_json(command.to_payload())
            and str(row.get("command_sha256") or "").casefold()
            == browser_agent_command_sha256(command).casefold()
        )
    except (MutationCommandContractError, TypeError, ValueError):
        command_is_valid = False
    if not command_is_valid:
        return "SAVE_COMMAND_INVALID_AFTER_RESTART"

    raw_authority = row.get("save_authority_json")
    authority_sha256 = row.get("save_authority_sha256")
    if not isinstance(raw_authority, str) or not isinstance(authority_sha256, str):
        return "SAVE_AUTHORITY_MISSING_AFTER_RESTART"
    try:
        authority = json.loads(raw_authority)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "SAVE_AUTHORITY_INVALID_AFTER_RESTART"
    try:
        authority_is_valid = (
            isinstance(authority, dict)
            and raw_authority == _canonical_json(authority)
            and _canonical_sha256(authority).casefold() == authority_sha256.casefold()
        )
    except (TypeError, ValueError):
        authority_is_valid = False
    if not authority_is_valid:
        return "SAVE_AUTHORITY_INVALID_AFTER_RESTART"

    raw_action_result = row.get("save_action_result_json")
    action_result_sha256 = row.get("save_action_result_sha256")
    if not isinstance(raw_action_result, str) or not isinstance(
        action_result_sha256, str
    ):
        return "SAVE_ACTION_RESULT_MISSING_AFTER_RESTART"
    try:
        action_result = json.loads(raw_action_result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"
    try:
        action_result_is_valid = (
            isinstance(action_result, dict)
            and raw_action_result == _canonical_json(action_result)
            and _canonical_sha256(action_result).casefold()
            == action_result_sha256.casefold()
        )
    except (TypeError, ValueError):
        action_result_is_valid = False
    if not action_result_is_valid:
        return "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"

    dispatched_at = row.get("dispatched_at")
    recorded_at = row.get("save_success_recorded_at")
    if not (
        isinstance(dispatched_at, str)
        and dispatched_at.strip()
        and isinstance(recorded_at, str)
        and recorded_at.strip()
    ):
        return "SAVE_SUCCESS_RECORD_MISSING_AFTER_RESTART"
    try:
        dispatched_time = parse_strict_utc_timestamp(
            dispatched_at,
            field="dispatched_at",
        )
        recorded_time = parse_strict_utc_timestamp(
            recorded_at,
            field="save_success_recorded_at",
        )
    except StrictUtcTimestampError:
        return "SAVE_SUCCESS_RECORD_INVALID_AFTER_RESTART"
    if dispatched_time > recorded_time:
        return "SAVE_SUCCESS_RECORD_INVALID_AFTER_RESTART"

    try:
        validated = _validate_frozen_batch_save_action_result(
            action_result,
            command=command,
            authority=authority,
        )
        if validated.get("ok") is not True:
            return "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"
        save_verification_facts_from_frozen_authority(
            authority,
            save_command=command,
            ledger_entry=row,
            save_action_result_sha256=action_result_sha256,
        )
    except (ActionResultContractError, DispatchAuthorityError, TypeError, ValueError):
        return "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"
    return None


@dataclass(frozen=True)
class MutationLedgerDecision:
    ok: bool
    reason_code: str
    entry: dict[str, Any] | None = None
    idempotent: bool = False


class MutationDispatchLedger:
    """Durable local at-most-once boundary for non-idempotent DXM clicks.

    `DISPATCHING` is written before the external click. A new process converts
    every abandoned `DISPATCHING` row to `UNKNOWN`; neither `UNKNOWN` nor
    `DISPATCHED` can return to a dispatchable state. This deliberately prefers
    a manual reconciliation over a possible duplicate external mutation.
    """

    def __init__(
        self,
        *,
        recover_inflight: bool = True,
        live_facts_provider: Callable[[], LiveDispatchFacts] | None = None,
    ) -> None:
        self._live_facts_provider = live_facts_provider
        if recover_inflight:
            self.recover_inflight()

    @staticmethod
    def _contract_failure(exc: MutationCommandContractError) -> MutationLedgerDecision:
        return MutationLedgerDecision(False, exc.reason_code)

    @staticmethod
    def _binding(command: BrowserAgentCommand, mutation_action: str, ordinal: int) -> dict[str, Any]:
        return {
            "mutation_id": build_mutation_id(
                mutation_scope_id=str(command.mutation_scope_id),
                state=command.state,
                ordinal=ordinal,
                mutation_action=mutation_action,
            ),
            "mutation_scope_id": str(command.mutation_scope_id),
            "mutation_action": mutation_action,
            "ordinal": ordinal,
            "command_state": command.state,
            "command_action": command.action,
            "task_id": str(command.task_id),
            "job_id": str(command.job_id),
            "authorization_lease_id": str(command.authorization_lease_id),
            "authorization_lease_fingerprint": str(
                command.authorization_lease_fingerprint
            ),
            "stage_task_facts_fingerprint": str(command.stage_task_facts_fingerprint),
            "target_hash": str(command.target_hash),
            "authorization_fingerprint": str(command.authorization_fingerprint),
            "command_id": str(command.command_id),
            "runtime_id": str(command.runtime_id),
        }

    @staticmethod
    def _binding_matches(row: dict[str, Any], expected: dict[str, Any]) -> bool:
        # command_id/runtime_id belong to one process attempt, not to the
        # durable mutation identity. A restarted BrowserAgent must still see
        # the terminal state for the same task/job/lease/target scope instead
        # of misclassifying it as business-binding drift.
        durable_expected = {
            key: value
            for key, value in expected.items()
            if key not in {"command_id", "runtime_id"}
        }
        return all(row.get(key) == value for key, value in durable_expected.items())

    @staticmethod
    def _reserved_row_is_pristine(row: dict[str, Any]) -> bool:
        return all(
            row.get(key) is None
            for key in (
                "browser_session_id",
                "page_url",
                "page_kind",
                "outcome_json",
                "command_sha256",
                "command_json",
                "save_action_result_sha256",
                "save_action_result_json",
                "save_authority_sha256",
                "save_authority_json",
                "save_success_recorded_at",
                "dispatch_started_at",
                "dispatched_at",
                "unknown_at",
            )
        )

    @staticmethod
    def _reserved_row_is_pristine(row: dict[str, Any]) -> bool:
        return all(
            row.get(key) is None
            for key in (
                "browser_session_id",
                "page_url",
                "page_kind",
                "outcome_json",
                "dispatch_started_at",
                "dispatched_at",
                "unknown_at",
            )
        )

    @staticmethod
    def _terminal_reason(status: str) -> str:
        return {
            "DISPATCHING": "MUTATION_ALREADY_DISPATCHING",
            "DISPATCHED": "MUTATION_ALREADY_DISPATCHED",
            "UNKNOWN": "MUTATION_OUTCOME_UNKNOWN",
            "CANCELLED_BEFORE_DISPATCH": "MUTATION_CANCELLED_BEFORE_DISPATCH",
        }.get(status, "MUTATION_LEDGER_STATE_INVALID")

    def reserve_command(self, command: BrowserAgentCommand) -> MutationLedgerDecision:
        try:
            plan = validate_browser_agent_command(command)
        except MutationCommandContractError as exc:
            return self._contract_failure(exc)
        if not plan:
            if (
                command.state == "VERIFY_NOT_PUBLISHED"
                and command.action == "verify_not_published"
                and command.execution_mode == "batch_draft_save"
            ):
                return self._verify_dispatched_save_predecessor(command)
            return MutationLedgerDecision(True, "NON_MUTATION_COMMAND", idempotent=True)

        now = now_iso()
        scope_id = str(command.mutation_scope_id)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot_row_authority_sha256 = None
            if (
                command.execution_mode == "batch_draft_save"
                and command.state == "SAVE_ONLY"
                and command.action == "save_only"
            ):
                try:
                    snapshot_row_authority_sha256 = (
                        snapshot_row_authority_fingerprint_in_transaction(
                            conn,
                            int(command.task_id),
                        )
                    )
                except (DispatchAuthorityError, TypeError, ValueError):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                    )
            existing_rows = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=?
                 ORDER BY ordinal ASC
                """,
                (scope_id,),
            ).fetchall()
            expected_by_action = {
                action: self._binding(command, action, ordinal)
                for action, ordinal in plan.items()
            }
            for row in existing_rows:
                expected = expected_by_action.get(str(row.get("mutation_action") or ""))
                if expected is None or not self._binding_matches(row, expected):
                    return MutationLedgerDecision(
                        False,
                        "MUTATION_SCOPE_BINDING_MISMATCH",
                        dict(row),
                    )
                if (
                    snapshot_row_authority_sha256 is not None
                    and str(row.get("snapshot_row_authority_sha256") or "").casefold()
                    != snapshot_row_authority_sha256.casefold()
                ):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                        dict(row),
                    )
                status = str(row.get("status") or "")
                if status != "RESERVED":
                    return MutationLedgerDecision(
                        False,
                        self._terminal_reason(status),
                        dict(row),
                    )
                if not self._reserved_row_is_pristine(row):
                    return MutationLedgerDecision(
                        False,
                        "MUTATION_RESERVED_STATE_UNCERTAIN",
                        dict(row),
                    )
            existing_actions = {str(row["mutation_action"]) for row in existing_rows}
            for action, ordinal in sorted(plan.items(), key=lambda item: item[1]):
                if action in existing_actions:
                    continue
                binding = expected_by_action[action]
                conn.execute(
                    """
                    INSERT INTO mutation_dispatch_ledger (
                        mutation_id,
                        mutation_scope_id,
                        mutation_action,
                        ordinal,
                        command_state,
                        command_action,
                        task_id,
                        job_id,
                        authorization_lease_id,
                        authorization_lease_fingerprint,
                        snapshot_row_authority_sha256,
                        stage_task_facts_fingerprint,
                        target_hash,
                        authorization_fingerprint,
                        status,
                        command_id,
                        runtime_id,
                        reserved_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?, ?)
                    """,
                    (
                        binding["mutation_id"],
                        binding["mutation_scope_id"],
                        binding["mutation_action"],
                        binding["ordinal"],
                        binding["command_state"],
                        binding["command_action"],
                        binding["task_id"],
                        binding["job_id"],
                        binding["authorization_lease_id"],
                        binding["authorization_lease_fingerprint"],
                        snapshot_row_authority_sha256,
                        binding["stage_task_facts_fingerprint"],
                        binding["target_hash"],
                        binding["authorization_fingerprint"],
                        command.command_id,
                        command.runtime_id,
                        now,
                        now,
                    ),
                )
            first = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=?
                 ORDER BY ordinal ASC
                 LIMIT 1
                """,
                (scope_id,),
            ).fetchone()
            return MutationLedgerDecision(
                True,
                "OK",
                dict(first) if first else None,
                idempotent=bool(existing_rows),
            )

    def _verify_dispatched_save_predecessor(
        self,
        command: BrowserAgentCommand,
    ) -> MutationLedgerDecision:
        try:
            context = validate_save_verification_context(
                command.params.get("save_verification_context"),
                task_id=command.task_id,
                job_id=command.job_id,
                runtime_id=command.runtime_id,
                execution_mode=command.execution_mode,
                structural_only=True,
            )
        except BatchCommandContractError as exc:
            return MutationLedgerDecision(False, exc.reason_code)

        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (str(context["mutation_scope_id"]).lower(),),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_LEDGER_MISMATCH",
                )
            entry = dict(row)
            if not all(
                isinstance(entry.get(key), str) and str(entry.get(key)).strip()
                for key in (
                    "save_action_result_sha256",
                    "save_action_result_json",
                    "save_authority_sha256",
                    "save_authority_json",
                    "dispatched_at",
                    "save_success_recorded_at",
                )
            ):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_MISSING",
                    entry,
                )
            try:
                dispatched_time = parse_strict_utc_timestamp(
                    entry["dispatched_at"],
                    field="dispatched_at",
                )
                recorded_time = parse_strict_utc_timestamp(
                    entry["save_success_recorded_at"],
                    field="save_success_recorded_at",
                )
            except StrictUtcTimestampError:
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            if dispatched_time > recorded_time:
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            if str(entry.get("command_sha256") or "").casefold() != str(
                context.get("save_command_sha256") or ""
            ).casefold():
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_LEDGER_MISMATCH",
                    entry,
                )
            raw_save_command = entry.get("command_json")
            if not isinstance(raw_save_command, str) or not raw_save_command.strip():
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_MISSING",
                    entry,
                )
            try:
                persisted_save_command = json.loads(raw_save_command)
            except (TypeError, ValueError):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            raw_action_result = entry.get("save_action_result_json")
            try:
                persisted_action_result = json.loads(raw_action_result)
            except (TypeError, ValueError):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            action_result_sha256 = _canonical_sha256(persisted_action_result)
            if action_result_sha256.casefold() != str(
                entry.get("save_action_result_sha256") or ""
            ).casefold():
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            if str(context.get("save_action_result_sha256") or "").casefold() != (
                action_result_sha256.casefold()
            ):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_RESULT_MISMATCH",
                    entry,
                )
            raw_authority = entry.get("save_authority_json")
            try:
                frozen_authority = json.loads(raw_authority)
            except (TypeError, ValueError):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            if _canonical_sha256(frozen_authority).casefold() != str(
                entry.get("save_authority_sha256") or ""
            ).casefold():
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )

            try:
                persisted_save_command_object = BrowserAgentCommand(
                    **persisted_save_command
                )
                validated_persisted_result = _validate_frozen_batch_save_action_result(
                    persisted_action_result,
                    command=persisted_save_command_object,
                    authority=frozen_authority,
                )
            except (ActionResultContractError, TypeError, ValueError):
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )
            if validated_persisted_result != persisted_action_result:
                return MutationLedgerDecision(
                    False,
                    "SAVE_VERIFICATION_PREDECESSOR_FACTS_INVALID",
                    entry,
                )

            current_authority = validate_current_task_against_frozen_authority(
                conn,
                frozen_authority,
            )
            if current_authority.ok is not True:
                reason_code = (
                    "SAVE_AUTHORITY_TASK_DRIFT"
                    if current_authority.reason_code == "AUTH_CURRENT_TASK_DRIFT"
                    else current_authority.reason_code
                )
                return MutationLedgerDecision(False, reason_code, entry)
            provider = self._live_facts_provider
            if not callable(provider):
                return MutationLedgerDecision(
                    False,
                    "AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
                    entry,
                )
            try:
                current_live_facts = provider()
            except Exception:
                return MutationLedgerDecision(
                    False,
                    "AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
                    entry,
                )
            current_live_authority = (
                validate_current_live_facts_against_frozen_authority(
                    frozen_authority,
                    current_live_facts,
                )
            )
            if current_live_authority.ok is not True:
                return MutationLedgerDecision(
                    False,
                    current_live_authority.reason_code,
                    entry,
                )
            try:
                authoritative_facts = save_verification_facts_from_frozen_authority(
                    frozen_authority,
                    save_command=persisted_save_command,
                    ledger_entry=entry,
                    save_action_result_sha256=action_result_sha256,
                )
                validate_save_verification_context(
                    command.params.get("save_verification_context"),
                    task_id=command.task_id,
                    job_id=command.job_id,
                    runtime_id=command.runtime_id,
                    execution_mode=command.execution_mode,
                    save_command=persisted_save_command,
                    save_action_result=persisted_action_result,
                    authoritative_facts=authoritative_facts,
                )
            except DispatchAuthorityError as exc:
                return MutationLedgerDecision(False, exc.reason_code, entry)
            except BatchCommandContractError as exc:
                return MutationLedgerDecision(False, exc.reason_code, entry)
            return MutationLedgerDecision(
                True,
                "OK",
                entry,
                idempotent=True,
            )

    def record_success(
        self,
        command: BrowserAgentCommand,
        action_result: Any,
    ) -> MutationLedgerDecision:
        """Freeze one canonical validated batch SAVE ActionResult exactly once."""

        if not (
            command.execution_mode == "batch_draft_save"
            and command.state == "SAVE_ONLY"
            and command.action == "save_only"
        ):
            return MutationLedgerDecision(False, "SAVE_SUCCESS_COMMAND_INVALID")
        command_sha256 = browser_agent_command_sha256(command)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (command.mutation_scope_id,),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(False, "MUTATION_NOT_RESERVED")
            entry = dict(row)
            if (
                entry.get("status") != "DISPATCHED"
                or str(entry.get("command_sha256") or "").casefold()
                != command_sha256.casefold()
                or entry.get("command_json") != _canonical_json(command.to_payload())
            ):
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_COMMAND_MISMATCH",
                    entry,
                )
            raw_authority = entry.get("save_authority_json")
            stored_authority_sha256 = entry.get("save_authority_sha256")
            if (
                not isinstance(raw_authority, str)
                or not raw_authority.strip()
                or not isinstance(stored_authority_sha256, str)
                or not stored_authority_sha256.strip()
            ):
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_AUTHORITY_MISSING",
                    entry,
                )
            try:
                frozen_authority = json.loads(raw_authority)
            except (TypeError, ValueError):
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_AUTHORITY_INVALID",
                    entry,
                )
            if _canonical_sha256(frozen_authority).casefold() != str(
                stored_authority_sha256
            ).casefold():
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_AUTHORITY_INVALID",
                    entry,
                )
            try:
                validated = _validate_frozen_batch_save_action_result(
                    action_result,
                    command=command,
                    authority=frozen_authority,
                )
            except ActionResultContractError as exc:
                return MutationLedgerDecision(False, exc.reason_code, entry)
            if validated.get("ok") is not True:
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_EVIDENCE_INVALID",
                    entry,
                )
            action_result_json = _canonical_json(validated)
            action_result_sha256 = _canonical_sha256(validated)
            try:
                save_verification_facts_from_frozen_authority(
                    frozen_authority,
                    save_command=command,
                    ledger_entry={
                        **entry,
                        "save_action_result_sha256": action_result_sha256,
                    },
                    save_action_result_sha256=action_result_sha256,
                )
            except DispatchAuthorityError as exc:
                return MutationLedgerDecision(False, exc.reason_code, entry)
            now = utc_now_iso()
            existing_json = entry.get("save_action_result_json")
            existing_sha256 = entry.get("save_action_result_sha256")
            if existing_json is not None or existing_sha256 is not None:
                if (
                    existing_json == action_result_json
                    and str(existing_sha256 or "").casefold()
                    == action_result_sha256.casefold()
                ):
                    return MutationLedgerDecision(True, "OK", entry, idempotent=True)
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_EVIDENCE_CONFLICT",
                    entry,
                )
            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET save_action_result_sha256=?,
                       save_action_result_json=?,
                       save_success_recorded_at=?,
                       updated_at=?
                 WHERE mutation_scope_id=?
                   AND mutation_action='save_only_click'
                   AND status='DISPATCHED'
                   AND save_action_result_sha256 IS NULL
                   AND save_action_result_json IS NULL
                """,
                (
                    action_result_sha256,
                    action_result_json,
                    now,
                    now,
                    command.mutation_scope_id,
                ),
            )
            if updated.rowcount != 1:
                return MutationLedgerDecision(
                    False,
                    "SAVE_SUCCESS_EVIDENCE_CONFLICT",
                    entry,
                )
            persisted = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (command.mutation_scope_id,),
            ).fetchone()
            return MutationLedgerDecision(True, "OK", dict(persisted))

    @staticmethod
    def _validate_batch_queue_cas(
        conn: Any,
        command: BrowserAgentCommand,
    ) -> MutationLedgerDecision | None:
        if not (
            command.execution_mode == "batch_draft_save"
            and command.state == "SAVE_ONLY"
            and command.action == "save_only"
        ):
            return None
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=?",
            (command.task_id,),
        ).fetchone()
        if task is None:
            return MutationLedgerDecision(False, "AUTH_COMMAND_QUEUE_STATE_MISMATCH")
        persisted = dict(task)
        persisted["payload"] = loads(persisted.pop("payload_json", None), {})
        persisted["jobs"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC",
                (command.task_id,),
            ).fetchall()
        ]
        try:
            validate_current_batch_queue_guard(
                persisted,
                command.job_id,
                command.params.get("batch_queue_guard"),
            )
        except BatchCommandContractError:
            return MutationLedgerDecision(False, "AUTH_COMMAND_QUEUE_STATE_MISMATCH")
        return None

    @staticmethod
    def _validate_batch_authorization_lease_cas(
        conn: Any,
        command: BrowserAgentCommand,
        *,
        checked_at: str,
    ) -> MutationLedgerDecision | None:
        """Re-read the persisted approval lease in the dispatch transaction."""

        if not (
            command.execution_mode == "batch_draft_save"
            and command.state == "SAVE_ONLY"
            and command.action == "save_only"
        ):
            return None
        task = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (command.task_id,),
        ).fetchone()
        if task is None:
            return MutationLedgerDecision(False, "AUTH_TASK_NOT_FOUND")
        payload = loads(task.get("payload_json"), {})
        approval = (
            payload.get("manual_approval")
            if isinstance(payload.get("manual_approval"), dict)
            else {}
        )
        if approval.get("approved") is not True or approval.get("source") != "server":
            return MutationLedgerDecision(False, "AUTH_LEASE_NOT_APPROVED")
        if str(approval.get("lease_id") or "") != str(command.authorization_lease_id or ""):
            return MutationLedgerDecision(False, "AUTH_COMMAND_AUTHORIZATION_MISMATCH")
        if approval.get("consumed") is not True or not approval.get("consumed_at"):
            return MutationLedgerDecision(False, "AUTH_LEASE_NOT_CONSUMED")
        stored_context = approval.get("authorization_context")
        stored_stage = approval.get("stage_task_facts")
        context_stage = (
            stored_context.get("stage_task_facts")
            if isinstance(stored_context, dict)
            else None
        )
        if not isinstance(stored_stage, dict) or stored_stage != context_stage:
            return MutationLedgerDecision(False, "AUTH_STAGE_FACTS_MISMATCH")
        if (
            not isinstance(stored_context, dict)
            or verify_authorization_context(stored_context).get("ok") is not True
        ):
            return MutationLedgerDecision(
                False, "AUTH_COMMAND_AUTHORIZATION_MISMATCH"
            )
        if not authorization_lease_is_active(
            checked_at=checked_at,
            expires_at=approval.get("expires_at"),
        ):
            return MutationLedgerDecision(False, "AUTH_LEASE_EXPIRED")
        try:
            current_lease_fingerprint = authorization_lease_authority_fingerprint(
                approval
            )
        except ValueError:
            return MutationLedgerDecision(False, "AUTH_LEASE_AUTHORITY_MISMATCH")
        if str(command.authorization_lease_fingerprint or "").casefold() != (
            current_lease_fingerprint.casefold()
        ):
            return MutationLedgerDecision(False, "AUTH_LEASE_AUTHORITY_MISMATCH")
        return None

    def begin_dispatch(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        identity: dict[str, Any] | None = None,
    ) -> MutationLedgerDecision:
        try:
            ordinal = mutation_ordinal_for_command(command, mutation_action)
        except MutationCommandContractError as exc:
            return self._contract_failure(exc)
        expected = self._binding(command, mutation_action, ordinal)
        command_sha256 = browser_agent_command_sha256(command)
        command_json = json.dumps(
            command.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        live_identity = dict(identity or {})
        browser_session_id = str(live_identity.get("browser_session_id") or "").strip() or None
        page_url = str(live_identity.get("page_url") or "").strip() or None
        page_kind = str(live_identity.get("page_kind") or "").strip() or None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Take the clock reading only after acquiring the write lock. A
            # lease that expires while waiting for the transaction must never
            # be allowed to reach DISPATCHING/the external click.
            now = utc_now_iso()
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(False, "MUTATION_NOT_RESERVED")
            if not self._binding_matches(row, expected):
                return MutationLedgerDecision(
                    False,
                    "MUTATION_SCOPE_BINDING_MISMATCH",
                    dict(row),
                )
            status = str(row.get("status") or "")
            if status != "RESERVED":
                return MutationLedgerDecision(False, self._terminal_reason(status), dict(row))
            if not self._reserved_row_is_pristine(row):
                return MutationLedgerDecision(
                    False,
                    "MUTATION_RESERVED_STATE_UNCERTAIN",
                    dict(row),
                )

            if (
                command.execution_mode == "batch_draft_save"
                and command.state == "SAVE_ONLY"
                and command.action == "save_only"
            ):
                try:
                    current_snapshot_row_authority_sha256 = (
                        snapshot_row_authority_fingerprint_in_transaction(
                            conn,
                            int(command.task_id),
                        )
                    )
                except (DispatchAuthorityError, TypeError, ValueError):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                        dict(row),
                    )
                if str(row.get("snapshot_row_authority_sha256") or "").casefold() != (
                    current_snapshot_row_authority_sha256.casefold()
                ):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                        dict(row),
                    )

            lease_rejection = self._validate_batch_authorization_lease_cas(
                conn,
                command,
                checked_at=now,
            )
            if lease_rejection is not None:
                return lease_rejection

            queue_rejection = self._validate_batch_queue_cas(conn, command)
            if queue_rejection is not None:
                return queue_rejection

            save_authority_json = None
            save_authority_sha256 = None
            if (
                command.execution_mode == "batch_draft_save"
                and command.state == "SAVE_ONLY"
                and command.action == "save_only"
            ):
                provider = self._live_facts_provider
                if not callable(provider):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
                        dict(row),
                    )
                try:
                    live_facts = provider()
                except Exception:
                    return MutationLedgerDecision(
                        False,
                        "AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
                        dict(row),
                    )
                authority_decision = validate_dispatch_authority_in_transaction(
                    conn,
                    command,
                    live_identity,
                    live_facts,
                )
                if authority_decision.ok is not True:
                    return MutationLedgerDecision(
                        False,
                        authority_decision.reason_code,
                        dict(row),
                    )
                if (
                    authority_decision.authority is None
                    or not isinstance(authority_decision.authority_sha256, str)
                ):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_DISPATCH_AUTHORITY_UNAVAILABLE",
                        dict(row),
                    )
                save_authority_json = _canonical_json(
                    authority_decision.authority
                )
                save_authority_sha256 = _canonical_sha256(
                    authority_decision.authority
                )
                if save_authority_sha256.casefold() != (
                    authority_decision.authority_sha256.casefold()
                ):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_DISPATCH_AUTHORITY_INVALID",
                        dict(row),
                    )

            predecessors = conn.execute(
                """
                SELECT ordinal, status FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND ordinal<?
                 ORDER BY ordinal ASC
                """,
                (command.mutation_scope_id, ordinal),
            ).fetchall()
            expected_predecessor_ordinals = list(range(1, ordinal))
            if (
                [int(item["ordinal"]) for item in predecessors] != expected_predecessor_ordinals
                or any(item.get("status") != "DISPATCHED" for item in predecessors)
            ):
                return MutationLedgerDecision(False, "MUTATION_ORDINAL_BLOCKED", dict(row))

            # The provider, page authority, and full snapshot validation above
            # may consume the remainder of a short lease. Sample the clock
            # again at the final CAS boundary and rebuild the full lease
            # authority inside the same write transaction.
            final_now = utc_now_iso()
            final_lease_rejection = self._validate_batch_authorization_lease_cas(
                conn,
                command,
                checked_at=final_now,
            )
            if final_lease_rejection is not None:
                return final_lease_rejection

            if (
                command.execution_mode == "batch_draft_save"
                and command.state == "SAVE_ONLY"
                and command.action == "save_only"
            ):
                try:
                    final_snapshot_row_authority_sha256 = (
                        snapshot_row_authority_fingerprint_in_transaction(
                            conn,
                            int(command.task_id),
                        )
                    )
                except (DispatchAuthorityError, TypeError, ValueError):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                        dict(row),
                    )
                if str(row.get("snapshot_row_authority_sha256") or "").casefold() != (
                    final_snapshot_row_authority_sha256.casefold()
                ):
                    return MutationLedgerDecision(
                        False,
                        "AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                        dict(row),
                    )

            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='DISPATCHING',
                       command_id=?,
                       command_sha256=?,
                       command_json=?,
                       save_authority_sha256=?,
                       save_authority_json=?,
                       runtime_id=?,
                       browser_session_id=?,
                       page_url=?,
                       page_kind=?,
                       dispatch_started_at=?,
                       updated_at=?
                 WHERE mutation_scope_id=?
                   AND mutation_action=?
                   AND status='RESERVED'
                """,
                (
                    command.command_id,
                    command_sha256,
                    command_json,
                    save_authority_sha256,
                    save_authority_json,
                    command.runtime_id,
                    browser_session_id,
                    page_url,
                    page_kind,
                    final_now,
                    final_now,
                    command.mutation_scope_id,
                    mutation_action,
                ),
            )
            if updated.rowcount != 1:
                current = conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                     WHERE mutation_scope_id=? AND mutation_action=?
                    """,
                    (command.mutation_scope_id, mutation_action),
                ).fetchone()
                current_status = str((current or {}).get("status") or "")
                return MutationLedgerDecision(
                    False,
                    self._terminal_reason(current_status),
                    dict(current) if current else None,
                )
            dispatched = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            return MutationLedgerDecision(True, "OK", dict(dispatched))

    def cancel_reserved(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        *,
        reason_code: str = "BATCH_STOPPED_BEFORE_DISPATCH",
    ) -> MutationLedgerDecision:
        """CAS-cancel one exact RESERVED binding before any external dispatch."""

        try:
            ordinal = mutation_ordinal_for_command(command, mutation_action)
        except MutationCommandContractError as exc:
            return self._contract_failure(exc)
        expected = self._binding(command, mutation_action, ordinal)
        canonical_reason = str(reason_code or "").strip().upper()
        if (
            not canonical_reason
            or len(canonical_reason) > 120
            or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in canonical_reason)
        ):
            return MutationLedgerDecision(False, "MUTATION_CANCEL_REASON_INVALID")
        now = now_iso()
        outcome_json = json.dumps(
            {
                "classification": "CANCELLED_BEFORE_DISPATCH",
                "reason_code": canonical_reason,
                "cancelled_at": now,
                "external_dispatch_started": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(False, "MUTATION_NOT_RESERVED")
            if not self._binding_matches(row, expected):
                return MutationLedgerDecision(
                    False,
                    "MUTATION_SCOPE_BINDING_MISMATCH",
                    dict(row),
                )
            status = str(row.get("status") or "")
            if status == "CANCELLED_BEFORE_DISPATCH":
                try:
                    prior_outcome = json.loads(str(row.get("outcome_json") or ""))
                except (TypeError, ValueError):
                    prior_outcome = None
                if (
                    not isinstance(prior_outcome, dict)
                    or prior_outcome.get("classification")
                    != "CANCELLED_BEFORE_DISPATCH"
                    or prior_outcome.get("reason_code") != canonical_reason
                    or prior_outcome.get("external_dispatch_started") is not False
                    or any(
                        row.get(key) is not None
                        for key in (
                            "dispatch_started_at",
                            "dispatched_at",
                            "unknown_at",
                            "browser_session_id",
                            "page_url",
                            "page_kind",
                        )
                    )
                ):
                    return MutationLedgerDecision(
                        False,
                        "MUTATION_CANCEL_PROOF_INVALID",
                        dict(row),
                    )
                return MutationLedgerDecision(True, "OK", dict(row), idempotent=True)
            if status != "RESERVED":
                return MutationLedgerDecision(False, self._terminal_reason(status), dict(row))
            if any(
                row.get(key) is not None
                for key in (
                    "dispatch_started_at",
                    "dispatched_at",
                    "unknown_at",
                    "outcome_json",
                    "browser_session_id",
                    "page_url",
                    "page_kind",
                )
            ):
                return MutationLedgerDecision(
                    False,
                    "MUTATION_RESERVED_STATE_UNCERTAIN",
                    dict(row),
                )
            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='CANCELLED_BEFORE_DISPATCH',
                       outcome_json=?, updated_at=?
                 WHERE mutation_scope_id=?
                   AND mutation_action=?
                   AND status='RESERVED'
                   AND dispatch_started_at IS NULL
                   AND dispatched_at IS NULL
                   AND unknown_at IS NULL
                   AND outcome_json IS NULL
                   AND browser_session_id IS NULL
                   AND page_url IS NULL
                   AND page_kind IS NULL
                """,
                (
                    outcome_json,
                    now,
                    command.mutation_scope_id,
                    mutation_action,
                ),
            )
            if updated.rowcount != 1:
                current = conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                     WHERE mutation_scope_id=? AND mutation_action=?
                    """,
                    (command.mutation_scope_id, mutation_action),
                ).fetchone()
                current_status = str((current or {}).get("status") or "")
                return MutationLedgerDecision(
                    False,
                    self._terminal_reason(current_status),
                    dict(current) if current else None,
                )
            cancelled = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            return MutationLedgerDecision(True, "OK", dict(cancelled))

    def mark_dispatched(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        outcome: Any | None = None,
    ) -> MutationLedgerDecision:
        try:
            ordinal = mutation_ordinal_for_command(command, mutation_action)
        except MutationCommandContractError as exc:
            return self._contract_failure(exc)
        expected = self._binding(command, mutation_action, ordinal)
        command_sha256 = browser_agent_command_sha256(command)
        now = now_iso()
        outcome_json = json.dumps(outcome, ensure_ascii=False, sort_keys=True, default=str)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(False, "MUTATION_NOT_RESERVED")
            if not self._binding_matches(row, expected):
                return MutationLedgerDecision(False, "MUTATION_SCOPE_BINDING_MISMATCH", dict(row))
            if str(row.get("command_sha256") or "").casefold() != command_sha256.casefold():
                return MutationLedgerDecision(False, "MUTATION_COMMAND_DIGEST_MISMATCH", dict(row))
            status = str(row.get("status") or "")
            if status == "DISPATCHED":
                if row.get("outcome_json") != outcome_json:
                    return MutationLedgerDecision(
                        False,
                        "MUTATION_OUTCOME_CONFLICT",
                        dict(row),
                    )
                return MutationLedgerDecision(True, "OK", dict(row), idempotent=True)
            if status != "DISPATCHING":
                return MutationLedgerDecision(False, self._terminal_reason(status), dict(row))
            changed = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='DISPATCHED', outcome_json=?, dispatched_at=?, updated_at=?
                 WHERE mutation_scope_id=? AND mutation_action=? AND status='DISPATCHING'
                """,
                (outcome_json, now, now, command.mutation_scope_id, mutation_action),
            )
            if changed.rowcount != 1:
                return MutationLedgerDecision(
                    False,
                    "MUTATION_LEDGER_STATE_INVALID",
                    dict(row),
                )
            updated = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            return MutationLedgerDecision(True, "OK", dict(updated))

    def mark_unknown(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        detail: Any | None = None,
    ) -> MutationLedgerDecision:
        try:
            ordinal = mutation_ordinal_for_command(command, mutation_action)
        except MutationCommandContractError as exc:
            return self._contract_failure(exc)
        expected = self._binding(command, mutation_action, ordinal)
        command_sha256 = browser_agent_command_sha256(command)
        now = now_iso()
        outcome_json = json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            if row is None:
                return MutationLedgerDecision(False, "MUTATION_NOT_RESERVED")
            if not self._binding_matches(row, expected):
                return MutationLedgerDecision(False, "MUTATION_SCOPE_BINDING_MISMATCH", dict(row))
            if str(row.get("command_sha256") or "").casefold() != command_sha256.casefold():
                return MutationLedgerDecision(False, "MUTATION_COMMAND_DIGEST_MISMATCH", dict(row))
            status = str(row.get("status") or "")
            if status == "UNKNOWN":
                if row.get("outcome_json") != outcome_json:
                    return MutationLedgerDecision(
                        False,
                        "MUTATION_OUTCOME_CONFLICT",
                        dict(row),
                    )
                return MutationLedgerDecision(True, "OK", dict(row), idempotent=True)
            unproven_batch_save = (
                status == "DISPATCHED"
                and command.execution_mode == "batch_draft_save"
                and command.state == "SAVE_ONLY"
                and command.action == "save_only"
                and _dispatched_batch_save_proof_failure(dict(row)) is not None
            )
            if status != "DISPATCHING" and not unproven_batch_save:
                return MutationLedgerDecision(False, self._terminal_reason(status), dict(row))
            changed = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='UNKNOWN', outcome_json=?, unknown_at=?, updated_at=?
                 WHERE mutation_scope_id=? AND mutation_action=?
                   AND (
                       status='DISPATCHING'
                       OR (
                           status='DISPATCHED'
                           AND command_state='SAVE_ONLY'
                           AND command_action='save_only'
                       )
                   )
                """,
                (outcome_json, now, now, command.mutation_scope_id, mutation_action),
            )
            if changed.rowcount != 1:
                return MutationLedgerDecision(
                    False,
                    "MUTATION_LEDGER_STATE_INVALID",
                    dict(row),
                )
            updated = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (command.mutation_scope_id, mutation_action),
            ).fetchone()
            return MutationLedgerDecision(True, "OK", dict(updated))

    def recover_inflight(self) -> int:
        now = now_iso()
        interrupted_outcome = _canonical_json(
            {
                "phase": "startup_recovery",
                "reason_code": "MUTATION_INTERRUPTED_INFLIGHT",
            }
        )
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated_count = int(
                conn.execute(
                    """
                    UPDATE mutation_dispatch_ledger
                       SET status='UNKNOWN', outcome_json=COALESCE(outcome_json, ?),
                           unknown_at=?, updated_at=?
                     WHERE status='DISPATCHING'
                    """,
                    (interrupted_outcome, now, now),
                ).rowcount
            )
            dispatched_rows = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE status='DISPATCHED'
                   AND command_state='SAVE_ONLY'
                   AND command_action='save_only'
                """,
            ).fetchall()
            for raw_row in dispatched_rows:
                row = dict(raw_row)
                reason_code = _dispatched_batch_save_proof_failure(row)
                if reason_code is None:
                    continue
                outcome = _canonical_json(
                    {
                        "phase": "startup_recovery",
                        "reason_code": reason_code,
                    }
                )
                updated_count += int(
                    conn.execute(
                        """
                        UPDATE mutation_dispatch_ledger
                           SET status='UNKNOWN', outcome_json=?, unknown_at=?, updated_at=?
                         WHERE mutation_scope_id=? AND mutation_action=?
                           AND status='DISPATCHED'
                        """,
                        (
                            outcome,
                            now,
                            now,
                            row["mutation_scope_id"],
                            row["mutation_action"],
                        ),
                    ).rowcount
                )
            return updated_count

    def get_entry(
        self,
        mutation_scope_id: str,
        mutation_action: str,
    ) -> dict[str, Any] | None:
        with connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE mutation_scope_id=? AND mutation_action=?
                """,
                (mutation_scope_id, mutation_action),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            raw_outcome = result.pop("outcome_json", None)
            result["outcome"] = json.loads(raw_outcome) if raw_outcome else None
            return result

    def job_recovery_classification(
        self,
        task_id: int | str,
        job_id: int | str,
    ) -> str | None:
        """Return the strongest non-retryable recovery fact for one job.

        Startup recovery must not replace a dispatched-but-unproven mutation
        outcome with a generic process-interruption error. ``DISPATCHED`` only
        proves that the click left this process; until the job has its complete
        response/page/unpublished proof chain, a restart must classify it as
        UNKNOWN and forbid retry. Keep the precedence here so callers cannot
        reinterpret internal row shapes.
        """

        with connection() as conn:
            rows = conn.execute(
                """
                SELECT status
                  FROM mutation_dispatch_ledger
                 WHERE task_id=? AND job_id=?
                 ORDER BY ordinal ASC
                """,
                (str(task_id), str(job_id)),
            ).fetchall()
        statuses = {str(row.get("status") or "") for row in rows}
        if "DISPATCHING" in statuses:
            # A caller may invoke recovery before the process-wide inflight
            # conversion. The externally dispatched outcome is still unknown.
            return "UNKNOWN"
        if "UNKNOWN" in statuses or "DISPATCHED" in statuses:
            return "UNKNOWN"
        return None

    def mark_incomplete_job_unknown(
        self,
        task_id: int | str,
        job_id: int | str,
    ) -> int:
        """Persist UNKNOWN for an unfinished job whose click may have escaped."""

        now = now_iso()
        with connection() as conn:
            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='UNKNOWN',
                       unknown_at=COALESCE(unknown_at, ?),
                       updated_at=?
                 WHERE task_id=? AND job_id=?
                   AND status IN ('DISPATCHING', 'DISPATCHED')
                """,
                (now, now, str(task_id), str(job_id)),
            )
        return int(updated.rowcount)
