from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.db import connection
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    build_mutation_id,
    mutation_ordinal_for_command,
    validate_browser_agent_command,
)
from src.utils import now_iso


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

    def __init__(self, *, recover_inflight: bool = True) -> None:
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
            "stage_task_facts_fingerprint": str(command.stage_task_facts_fingerprint),
            "target_hash": str(command.target_hash),
            "authorization_fingerprint": str(command.authorization_fingerprint),
            "command_id": str(command.command_id),
            "runtime_id": str(command.runtime_id),
        }

    @staticmethod
    def _binding_matches(row: dict[str, Any], expected: dict[str, Any]) -> bool:
        return all(row.get(key) == value for key, value in expected.items())

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
            return MutationLedgerDecision(True, "NON_MUTATION_COMMAND", idempotent=True)

        now = now_iso()
        scope_id = str(command.mutation_scope_id)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
                        stage_task_facts_fingerprint,
                        target_hash,
                        authorization_fingerprint,
                        status,
                        command_id,
                        runtime_id,
                        reserved_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?, ?)
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
        live_identity = dict(identity or {})
        browser_session_id = str(live_identity.get("browser_session_id") or "").strip() or None
        page_url = str(live_identity.get("page_url") or "").strip() or None
        page_kind = str(live_identity.get("page_kind") or "").strip() or None
        now = now_iso()
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
            if status != "RESERVED":
                return MutationLedgerDecision(False, self._terminal_reason(status), dict(row))
            if not self._reserved_row_is_pristine(row):
                return MutationLedgerDecision(
                    False,
                    "MUTATION_RESERVED_STATE_UNCERTAIN",
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

            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='DISPATCHING',
                       command_id=?,
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
                    command.runtime_id,
                    browser_session_id,
                    page_url,
                    page_kind,
                    now,
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
            status = str(row.get("status") or "")
            if status == "UNKNOWN":
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
                   SET status='UNKNOWN', outcome_json=?, unknown_at=?, updated_at=?
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

    def recover_inflight(self) -> int:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='UNKNOWN', unknown_at=?, updated_at=?
                 WHERE status='DISPATCHING'
                """,
                (now, now),
            )
            return int(updated.rowcount)

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
