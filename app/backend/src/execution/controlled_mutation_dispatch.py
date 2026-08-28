"""
ControlledMutationDispatch — dispatch controller for mutation dispatch ledger.

Implements the mutation dispatch ledger contract:
- Mutation commands require: authorization_lease_id, mutation_id, stage_task_facts_fingerprint
- Ledger entries: mutation_id, mutation_scope_id, mutation_action, ordinal,
  command_state, command_action, authorization_lease_id, target_hash, etc.
- Three write path scenarios:
  1. snapshot_row_authority_sha256 present → use mutation_dispatch_ledger
  2. mutation_id present but no ledger → insert
  3. Neither → reject (fail-closed)
- Ledger entries immutable after creation (ordinal strictly increasing)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from src.db import connection


class MutationCommandState(Enum):
    """State of a mutation command."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class MutationDispatchError(Exception):
    """Error raised by ControlledMutationDispatch."""

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
    """Request to dispatch a mutation."""

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
    """Result of a mutation dispatch operation."""

    ok: bool
    mutation_id: str
    ledger_entry_id: int | None = None
    reason_code: str | None = None
    error_detail: str | None = None
    status: str = "dispatched"
    metadata: dict[str, Any] = field(default_factory=dict)


class ControlledMutationDispatch:
    """Dispatch controller for mutation dispatch ledger.

    Fail-closed:
      - If neither snapshot_row_authority_sha256 nor mutation_id is present → reject
      - If authorization_lease_id missing → reject
      - If stage_task_facts_fingerprint missing → reject
      - Ledger entries are immutable after creation (ordinal strictly increasing)
    """

    LEDGER_LEASE_TTL_SECONDS = 5 * 60

    def dispatch(
        self,
        request: MutationDispatchRequest,
    ) -> MutationDispatchResult:
        """Dispatch a mutation command to the ledger.

        Three write path scenarios:
        1. snapshot_row_authority_sha256 present → use mutation_dispatch_ledger
        2. mutation_id present but no ledger → insert
        3. Neither → reject (fail-closed)
        """
        self._validate_request(request)

        if request.snapshot_row_authority_sha256:
            return self._dispatch_with_snapshot_authority(request)

        if request.mutation_id:
            return self._dispatch_with_mutation_id(request)

        raise MutationDispatchError(
            "DISPATCH_REQUIRES_SCOPE",
            "Either snapshot_row_authority_sha256 or mutation_id must be present",
            status_code=400,
        )

    def _validate_request(self, request: MutationDispatchRequest) -> None:
        """Validate the dispatch request (fail-closed)."""
        if not request.authorization_lease_id:
            raise MutationDispatchError(
                "AUTHORIZATION_LEASE_REQUIRED",
                "authorization_lease_id is required for mutation dispatch",
                status_code=400,
            )

        if not request.stage_task_facts_fingerprint:
            raise MutationDispatchError(
                "STAGE_TASK_FACTS_FINGERPRINT_REQUIRED",
                "stage_task_facts_fingerprint is required for mutation dispatch",
                status_code=400,
            )

        if not request.target_hash:
            raise MutationDispatchError(
                "TARGET_HASH_REQUIRED",
                "target_hash is required for mutation dispatch",
                status_code=400,
            )

        if not request.authorization_fingerprint:
            raise MutationDispatchError(
                "AUTHORIZATION_FINGERPRINT_REQUIRED",
                "authorization_fingerprint is required for mutation dispatch",
                status_code=400,
            )

    def _dispatch_with_snapshot_authority(
        self,
        request: MutationDispatchRequest,
    ) -> MutationDispatchResult:
        """Dispatch with snapshot_row_authority_sha256 present."""
        with connection() as conn:
            existing = conn.execute(
                "SELECT id FROM mutation_dispatch_ledger WHERE mutation_id=? LIMIT 1",
                (request.mutation_id,),
            ).fetchone()

            if existing:
                return MutationDispatchResult(
                    ok=True,
                    mutation_id=request.mutation_id,
                    ledger_entry_id=existing["id"],
                    reason_code="DUPLICATE_DISPATCH",
                    error_detail=None,
                    status="already_exists",
                    metadata={"existing_entry_id": existing["id"]},
                )

            ordinal = self._get_next_ordinal(conn, request.mutation_id)

            now = self._now_iso()
            expires_at = self._expires_at_iso(self.LEDGER_LEASE_TTL_SECONDS)

            row = conn.execute(
                """
                INSERT INTO mutation_dispatch_ledger (
                    mutation_id, mutation_scope_id, mutation_action,
                    ordinal, command_state, command_action,
                    task_id, job_id,
                    authorization_lease_id, authorization_lease_fingerprint,
                    snapshot_row_authority_sha256,
                    stage_task_facts_fingerprint,
                    target_hash, authorization_fingerprint,
                    browser_session_id, page_url, page_kind,
                    status, command_id, command_sha256, command_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.mutation_id,
                    request.mutation_scope_id,
                    request.mutation_action,
                    ordinal,
                    request.command_state,
                    request.command_action,
                    request.task_id,
                    request.job_id,
                    request.authorization_lease_id,
                    request.authorization_lease_fingerprint,
                    request.snapshot_row_authority_sha256,
                    request.stage_task_facts_fingerprint,
                    request.target_hash,
                    request.authorization_fingerprint,
                    request.browser_session_id,
                    request.page_url,
                    request.page_kind,
                    request.command_id,
                    request.command_sha256,
                    json.dumps(request.command_json, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            ledger_entry_id = row.lastrowid

            return MutationDispatchResult(
                ok=True,
                mutation_id=request.mutation_id,
                ledger_entry_id=ledger_entry_id,
                status="dispatched",
                metadata={
                    "ordinal": ordinal,
                    "write_path": "snapshot_row_authority",
                    "expires_at": expires_at,
                },
            )

    def _dispatch_with_mutation_id(
        self,
        request: MutationDispatchRequest,
    ) -> MutationDispatchResult:
        """Dispatch with mutation_id present but no snapshot_row_authority_sha256."""
        with connection() as conn:
            existing = conn.execute(
                "SELECT id FROM mutation_dispatch_ledger WHERE mutation_id=? LIMIT 1",
                (request.mutation_id,),
            ).fetchone()

            if existing:
                return MutationDispatchResult(
                    ok=True,
                    mutation_id=request.mutation_id,
                    ledger_entry_id=existing["id"],
                    reason_code="DUPLICATE_DISPATCH",
                    error_detail=None,
                    status="already_exists",
                    metadata={"existing_entry_id": existing["id"]},
                )

            ordinal = self._get_next_ordinal(conn, request.mutation_id)

            now = self._now_iso()

            row = conn.execute(
                """
                INSERT INTO mutation_dispatch_ledger (
                    mutation_id, mutation_scope_id, mutation_action,
                    ordinal, command_state, command_action,
                    task_id, job_id,
                    authorization_lease_id, authorization_lease_fingerprint,
                    stage_task_facts_fingerprint,
                    target_hash, authorization_fingerprint,
                    browser_session_id, page_url, page_kind,
                    status, command_id, command_sha256, command_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.mutation_id,
                    request.mutation_scope_id,
                    request.mutation_action,
                    ordinal,
                    request.command_state,
                    request.command_action,
                    request.task_id,
                    request.job_id,
                    request.authorization_lease_id,
                    request.authorization_lease_fingerprint,
                    request.stage_task_facts_fingerprint,
                    request.target_hash,
                    request.authorization_fingerprint,
                    request.browser_session_id,
                    request.page_url,
                    request.page_kind,
                    request.command_id,
                    request.command_sha256,
                    json.dumps(request.command_json, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            ledger_entry_id = row.lastrowid

            return MutationDispatchResult(
                ok=True,
                mutation_id=request.mutation_id,
                ledger_entry_id=ledger_entry_id,
                status="dispatched",
                metadata={
                    "ordinal": ordinal,
                    "write_path": "mutation_id_only",
                },
            )

    def _get_next_ordinal(self, conn: Any, mutation_id: str) -> int:
        """Get the next ordinal for a mutation_id (strictly increasing)."""
        last = conn.execute(
            "SELECT ordinal FROM mutation_dispatch_ledger WHERE mutation_id=? ORDER BY ordinal DESC LIMIT 1",
            (mutation_id,),
        ).fetchone()
        if last:
            return int(last["ordinal"]) + 1
        return 1

    def get_ledger_entries(
        self,
        mutation_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read ledger entries (read-only)."""
        conditions = []
        params: list[Any] = []

        if mutation_id is not None:
            conditions.append("mutation_id=?")
            params.append(mutation_id)
        if task_id is not None:
            conditions.append("task_id=?")
            params.append(task_id)

        query = "SELECT * FROM mutation_dispatch_ledger"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ordinal ASC LIMIT ?"
        params.append(limit)

        with connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def update_command_state(
        self,
        mutation_id: str,
        ordinal: int,
        new_state: str,
        outcome_json: dict[str, Any] | None = None,
    ) -> MutationDispatchResult:
        """Update the command state of a ledger entry (immutable after terminal state)."""
        terminal_states = {
            MutationCommandState.COMMITTED.value,
            MutationCommandState.ROLLED_BACK.value,
            MutationCommandState.FAILED.value,
        }

        with connection() as conn:
            entry = conn.execute(
                "SELECT * FROM mutation_dispatch_ledger WHERE mutation_id=? AND ordinal=?",
                (mutation_id, ordinal),
            ).fetchone()

            if not entry:
                return MutationDispatchResult(
                    ok=False,
                    mutation_id=mutation_id,
                    reason_code="ENTRY_NOT_FOUND",
                    error_detail=f"No ledger entry for mutation_id={mutation_id} ordinal={ordinal}",
                )

            if entry["command_state"] in terminal_states:
                return MutationDispatchResult(
                    ok=False,
                    mutation_id=mutation_id,
                    ledger_entry_id=entry["id"],
                    reason_code="ENTRY_IMMUTABLE",
                    error_detail=f"Entry is in terminal state {entry['command_state']}",
                    status="immutable",
                )

            now = self._now_iso()
            update_fields = ["command_state=?", "updated_at=?"]
            update_params: list[Any] = [new_state, now]

            if outcome_json is not None:
                update_fields.append("outcome_json=?")
                update_params.append(json.dumps(outcome_json, ensure_ascii=False))

            if new_state == MutationCommandState.COMMITTED.value:
                update_fields.append("save_success_recorded_at=?")
                update_params.append(now)

            update_params.extend([mutation_id, ordinal])

            conn.execute(
                f"UPDATE mutation_dispatch_ledger SET {', '.join(update_fields)} WHERE mutation_id=? AND ordinal=?",
                update_params,
            )

            return MutationDispatchResult(
                ok=True,
                mutation_id=mutation_id,
                ledger_entry_id=entry["id"],
                status="updated",
                metadata={"new_state": new_state},
            )

    def _now_iso(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _expires_at_iso(self, ttl_seconds: int) -> str:
        return (
            datetime.utcnow()
            .replace(microsecond=0)
            + timedelta(seconds=ttl_seconds)
        ).isoformat() + "Z"

    @staticmethod
    def compute_target_hash(command_json: dict[str, Any]) -> str:
        """Compute deterministic target hash from command JSON."""
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
        """Compute SHA-256 from command JSON."""
        serialized = json.dumps(
            command_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
