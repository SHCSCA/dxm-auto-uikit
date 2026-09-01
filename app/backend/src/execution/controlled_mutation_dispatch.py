"""Single controlled entry point for externally visible mutations.

``MutationDispatchLedger`` is the production authority for reservation,
just-in-time dispatch CAS, restart recovery, and terminal evidence.  This
module intentionally contains no SQL and owns no second ledger.  It is a
strict facade that keeps the older public names available while ensuring that
all state changes are delegated to that authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    browser_agent_command_sha256,
    build_mutation_id,
    mutation_ordinal_for_command,
)
from src.execution.mutation_dispatch_ledger import (
    MutationDispatchLedger,
    MutationLedgerDecision,
)


class MutationCommandState(Enum):
    """Compatibility enum; ledger status remains the durable authority."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class MutationDispatchError(Exception):
    """Stable fail-closed error raised by the compatibility surface."""

    def __init__(
        self,
        reason_code: str,
        detail: str,
        status_code: int = 400,
    ) -> None:
        self.reason_code = reason_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"[{reason_code}] {detail}")


@dataclass
class MutationDispatchRequest:
    """Legacy request shape accepted only when it embeds an exact command."""

    mutation_id: str
    mutation_scope_id: str
    mutation_action: str
    command_id: str
    command_sha256: str
    command_json: dict[str, Any]
    authorization_lease_id: str
    authorization_lease_fingerprint: str | None
    snapshot_row_authority_sha256: str | None
    stage_task_facts_fingerprint: str
    target_hash: str
    authorization_fingerprint: str
    task_id: str
    job_id: str
    browser_session_id: str | None
    page_url: str | None
    page_kind: str | None
    command_action: str
    command_state: str = MutationCommandState.PENDING.value


@dataclass
class MutationDispatchResult:
    """Compatibility result derived exclusively from a ledger decision."""

    ok: bool
    mutation_id: str
    ledger_entry_id: int | None = None
    reason_code: str | None = None
    error_detail: str | None = None
    status: str = "dispatched"
    metadata: dict[str, Any] = field(default_factory=dict)


class ControlledMutationDispatch:
    """Strict facade over the one production ``MutationDispatchLedger``.

    Reservation may be idempotent because it cannot emit an external write.
    ``begin_dispatch`` is deliberately not idempotent: the underlying ledger
    rejects every second attempt once the row is DISPATCHING, DISPATCHED, or
    UNKNOWN.  No method in this class inserts or updates ledger rows directly.
    """

    # Retained for import compatibility. Lease expiry is enforced by the
    # frozen authorization lease in MutationDispatchLedger, not by this value.
    LEDGER_LEASE_TTL_SECONDS = 5 * 60

    def __init__(
        self,
        ledger: MutationDispatchLedger | None = None,
        *,
        recover_inflight: bool = True,
        live_facts_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._ledger = ledger or MutationDispatchLedger(
            recover_inflight=recover_inflight,
            live_facts_provider=live_facts_provider,
        )

    @property
    def ledger(self) -> MutationDispatchLedger:
        """Return the delegated authority for dependency wiring/inspection."""

        return self._ledger

    # ------------------------------------------------------------------
    # Production facade: preserve the exact authority method signatures.
    # ------------------------------------------------------------------

    def reserve_command(self, command: BrowserAgentCommand) -> MutationLedgerDecision:
        return self._ledger.reserve_command(command)

    def reserve(self, command: BrowserAgentCommand) -> MutationLedgerDecision:
        return self.reserve_command(command)

    def begin_dispatch(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        identity: dict[str, Any] | None = None,
    ) -> MutationLedgerDecision:
        # This CAS is the only operation allowed to cross RESERVED ->
        # DISPATCHING. It rejects duplicate dispatches instead of replaying.
        return self._ledger.begin_dispatch(command, mutation_action, identity)

    def begin(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        identity: dict[str, Any] | None = None,
    ) -> MutationLedgerDecision:
        return self.begin_dispatch(command, mutation_action, identity)

    def mark_dispatched(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        outcome: Any | None = None,
    ) -> MutationLedgerDecision:
        return self._ledger.mark_dispatched(command, mutation_action, outcome)

    def mark(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        outcome: Any | None = None,
    ) -> MutationLedgerDecision:
        return self.mark_dispatched(command, mutation_action, outcome)

    def mark_unknown(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        detail: Any | None = None,
    ) -> MutationLedgerDecision:
        return self._ledger.mark_unknown(command, mutation_action, detail)

    def unknown(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        detail: Any | None = None,
    ) -> MutationLedgerDecision:
        return self.mark_unknown(command, mutation_action, detail)

    def record_success(
        self,
        command: BrowserAgentCommand,
        action_result: Any,
    ) -> MutationLedgerDecision:
        return self._ledger.record_success(command, action_result)

    def success(
        self,
        command: BrowserAgentCommand,
        action_result: Any,
    ) -> MutationLedgerDecision:
        return self.record_success(command, action_result)

    def cancel_reserved(
        self,
        command: BrowserAgentCommand,
        mutation_action: str,
        *,
        reason_code: str = "BATCH_STOPPED_BEFORE_DISPATCH",
    ) -> MutationLedgerDecision:
        return self._ledger.cancel_reserved(
            command,
            mutation_action,
            reason_code=reason_code,
        )

    def get_entry(
        self,
        mutation_scope_id: str,
        mutation_action: str,
    ) -> dict[str, Any] | None:
        return self._ledger.get_entry(mutation_scope_id, mutation_action)

    def read(
        self,
        mutation_scope_id: str,
        mutation_action: str,
    ) -> dict[str, Any] | None:
        return self.get_entry(mutation_scope_id, mutation_action)

    def job_recovery_classification(
        self,
        task_id: int | str,
        job_id: int | str,
    ) -> str | None:
        return self._ledger.job_recovery_classification(task_id, job_id)

    def mark_incomplete_job_unknown(
        self,
        task_id: int | str,
        job_id: int | str,
    ) -> int:
        return self._ledger.mark_incomplete_job_unknown(task_id, job_id)

    def recover_inflight(self) -> int:
        return self._ledger.recover_inflight()

    # ------------------------------------------------------------------
    # Compatibility surface. It validates the duplicated legacy fields
    # against one exact BrowserAgentCommand, then delegates reserve + begin.
    # It never writes a row itself.
    # ------------------------------------------------------------------

    def dispatch(self, request: MutationDispatchRequest) -> MutationDispatchResult:
        try:
            command = self._command_from_request(request)
        except MutationDispatchError as exc:
            return MutationDispatchResult(
                ok=False,
                mutation_id=str(getattr(request, "mutation_id", "") or ""),
                reason_code=exc.reason_code,
                error_detail=exc.detail,
                status="rejected",
            )

        reserved = self.reserve_command(command)
        if not reserved.ok:
            return self._compat_result(request.mutation_id, reserved, "rejected")

        # The ledger independently derives current snapshot authority during
        # reservation. A caller-supplied digest may only narrow that authority.
        entry = self.get_entry(str(command.mutation_scope_id), request.mutation_action)
        if entry is None:
            return MutationDispatchResult(
                ok=False,
                mutation_id=request.mutation_id,
                reason_code="MUTATION_NOT_RESERVED",
                error_detail="delegated ledger reservation did not produce an entry",
                status="rejected",
            )
        supplied_snapshot = str(request.snapshot_row_authority_sha256 or "").strip()
        if supplied_snapshot and not hmac.compare_digest(
            supplied_snapshot.casefold(),
            str(entry.get("snapshot_row_authority_sha256") or "").casefold(),
        ):
            self.cancel_reserved(
                command,
                request.mutation_action,
                reason_code="AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
            )
            return MutationDispatchResult(
                ok=False,
                mutation_id=request.mutation_id,
                ledger_entry_id=self._entry_id(entry),
                reason_code="AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH",
                error_detail="supplied snapshot authority differs from the ledger authority",
                status="rejected",
            )

        begun = self.begin_dispatch(
            command,
            request.mutation_action,
            {
                "browser_session_id": request.browser_session_id,
                "page_url": request.page_url,
                "page_kind": request.page_kind,
            },
        )
        return self._compat_result(
            request.mutation_id,
            begun,
            "dispatching" if begun.ok else "rejected",
        )

    def _command_from_request(
        self,
        request: MutationDispatchRequest,
    ) -> BrowserAgentCommand:
        if not isinstance(request, MutationDispatchRequest):
            raise MutationDispatchError(
                "MUTATION_DISPATCH_REQUEST_INVALID",
                "MutationDispatchRequest is required",
            )
        if not isinstance(request.command_json, dict):
            raise MutationDispatchError(
                "MUTATION_COMMAND_INVALID",
                "command_json must contain one exact BrowserAgentCommand payload",
            )
        try:
            command = BrowserAgentCommand(**request.command_json)
            ordinal = mutation_ordinal_for_command(command, request.mutation_action)
            expected_mutation_id = build_mutation_id(
                mutation_scope_id=str(command.mutation_scope_id),
                state=command.state,
                ordinal=ordinal,
                mutation_action=request.mutation_action,
            )
            actual_command_sha256 = browser_agent_command_sha256(command)
        except (MutationCommandContractError, TypeError, ValueError) as exc:
            reason_code = getattr(exc, "reason_code", "MUTATION_COMMAND_INVALID")
            raise MutationDispatchError(reason_code, str(exc)) from exc

        exact_bindings = {
            "mutation_id": (request.mutation_id, expected_mutation_id),
            "mutation_scope_id": (request.mutation_scope_id, command.mutation_scope_id),
            "command_id": (request.command_id, command.command_id),
            "command_sha256": (request.command_sha256, actual_command_sha256),
            "authorization_lease_id": (
                request.authorization_lease_id,
                command.authorization_lease_id,
            ),
            "authorization_lease_fingerprint": (
                request.authorization_lease_fingerprint,
                command.authorization_lease_fingerprint,
            ),
            "stage_task_facts_fingerprint": (
                request.stage_task_facts_fingerprint,
                command.stage_task_facts_fingerprint,
            ),
            "target_hash": (request.target_hash, command.target_hash),
            "authorization_fingerprint": (
                request.authorization_fingerprint,
                command.authorization_fingerprint,
            ),
            "task_id": (request.task_id, command.task_id),
            "job_id": (request.job_id, command.job_id),
            "command_action": (request.command_action, command.action),
            "command_state": (request.command_state, command.state),
        }
        for field_name, (supplied, authoritative) in exact_bindings.items():
            if str(supplied) != str(authoritative):
                raise MutationDispatchError(
                    "MUTATION_SCOPE_BINDING_MISMATCH",
                    f"{field_name} differs from the embedded command authority",
                )
        if request.command_json != command.to_payload():
            raise MutationDispatchError(
                "MUTATION_COMMAND_SERIALIZATION_MISMATCH",
                "command_json is not the canonical command payload",
            )
        return command

    @staticmethod
    def _entry_id(entry: dict[str, Any] | None) -> int | None:
        if not entry:
            return None
        try:
            return int(entry["id"])
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def _compat_result(
        cls,
        mutation_id: str,
        decision: MutationLedgerDecision,
        status: str,
    ) -> MutationDispatchResult:
        return MutationDispatchResult(
            ok=decision.ok,
            mutation_id=mutation_id,
            ledger_entry_id=cls._entry_id(decision.entry),
            reason_code=None if decision.ok else decision.reason_code,
            error_detail=None if decision.ok else decision.reason_code,
            status=status,
            metadata={
                "ledger_reason_code": decision.reason_code,
                "idempotent": decision.idempotent,
                "entry": decision.entry,
            },
        )

    def get_ledger_entries(
        self,
        mutation_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Reject the old unscoped DB scan instead of bypassing authority."""

        del mutation_id, task_id, limit
        raise MutationDispatchError(
            "LEDGER_SCOPED_READ_REQUIRED",
            "use get_entry(mutation_scope_id, mutation_action)",
        )

    def update_command_state(
        self,
        mutation_id: str,
        ordinal: int,
        new_state: str,
        outcome_json: dict[str, Any] | None = None,
    ) -> MutationDispatchResult:
        """Reject arbitrary state updates that would bypass ledger CAS."""

        del ordinal, new_state, outcome_json
        return MutationDispatchResult(
            ok=False,
            mutation_id=mutation_id,
            reason_code="LEDGER_TRANSITION_API_REQUIRED",
            error_detail="arbitrary command-state updates are forbidden",
            status="rejected",
        )

    @staticmethod
    def compute_target_hash(command_json: dict[str, Any]) -> str:
        serialized = json.dumps(
            command_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest().upper()

    @staticmethod
    def compute_command_sha256(command_json: dict[str, Any]) -> str:
        serialized = json.dumps(
            command_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
