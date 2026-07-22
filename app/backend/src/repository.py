from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.core.config import SCREENSHOT_DIR
from src.db import (
    connection,
    disable_edit_batch_bundles_with_quarantined_sources,
    disable_legacy_generated_starter_templates,
    dumps,
    loads,
    recover_interrupted_edit_batches as recover_edit_batches_in_db,
)
from src.batch_edit.execution_state import (
    ITEM_CONTINUE_TERMINAL_STATUSES,
    ITEM_TERMINAL_STATUSES,
    EditBatchExecutionPersistenceError,
    EditBatchExecutionTransitionResult,
    build_public_execution,
    build_public_item_outcome,
    build_public_progress,
    normalize_action_results_for_storage,
    normalize_approval_for_storage,
    normalize_execution_evidence_for_storage,
    normalize_item_grant_consumption_for_storage,
    normalize_item_grant_for_storage,
    normalize_item_outcome_for_storage,
    normalize_start_context_for_storage,
)
from src.batch_edit.execution_contract import (
    BatchExecutionContractError,
    derive_running_item_claim_context,
)
from src.batch_edit.batch_contract import BatchContractError, freeze_template_bundle
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import mutation_target_hash
from src.services.evidence_ref import validate_evidence_ref
from src.state_machine.two_stage import (
    TwoStageContractError,
    build_draft_box_proof,
    build_stage_a_task_facts,
    canonical_claim_target_identity,
    compare_authorization_context,
    verify_draft_box_proof,
)
from src.utils import now_iso


@dataclass(frozen=True)
class ClaimCompletionResult:
    applied: bool
    idempotent: bool
    conflict_code: str | None
    reason: str | None
    task: dict[str, Any] | None
    product: dict[str, Any] | None


class TerminalReportConflictError(RuntimeError):
    conflict_code = "REPORT_TERMINAL_STATE_CONFLICT"

    def __init__(self, task_id: int, job_id: int | None) -> None:
        self.task_id = task_id
        self.job_id = job_id
        super().__init__("failed report is terminal and cannot be replaced by a late success")


@dataclass(frozen=True)
class JobFinalizationResult:
    applied: bool
    conflict_code: str | None
    reason: str | None
    report: dict[str, Any] | None


@dataclass(frozen=True)
class AuthorizationLeaseResult:
    ok: bool
    reason_code: str
    task: dict[str, Any] | None
    lease: dict[str, Any] | None


@dataclass(frozen=True)
class TaskManualApprovalResult:
    ok: bool
    reason_code: str
    task: dict[str, Any] | None


@dataclass(frozen=True)
class BatchApprovalResult:
    applied: bool
    reason_code: str
    batch: dict[str, Any] | None


def _first_source_url_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ('source_url', 'url'):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    values = payload.get('source_urls')
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _exact_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("expected a positive integer")
    return value


def _published_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("published must be true, false, or null")
    return int(value)


def _published_from_db(value: Any) -> bool | None:
    if value is None:
        return None
    if value == 0:
        return False
    if value == 1:
        return True
    raise ValueError("reports.published contains an invalid tri-state value")


class Repository:
    def list_stores(self):
        with connection() as conn:
            return conn.execute("SELECT * FROM stores ORDER BY id DESC").fetchall()

    def create_store(self, name: str, platform: str):
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO stores (name, platform, status, created_at, updated_at) VALUES (?, ?, 'connected', ?, ?)",
                (name, platform, now, now),
            )
            return conn.execute("SELECT * FROM stores WHERE id=?", (cur.lastrowid,)).fetchone()

    def list_templates(self):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM templates ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = loads(row.pop('payload_json'), {})
                row['is_enabled'] = bool(row['is_enabled'])
                row['requires_manual_configuration'] = bool(
                    row.get('requires_manual_configuration')
                )
            return rows

    def create_template(self, data: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                INSERT INTO templates (
                    template_type, template_name, binding_scope, payload_json,
                    is_enabled, requires_manual_configuration, quarantine_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (
                    data['template_type'], data['template_name'], data['binding_scope'], dumps(data['payload']), int(data['is_enabled']), now, now,
                ),
            )
            # Generic template APIs must not bypass the same exact legacy and
            # source-reference quarantine applied during database startup.
            disable_legacy_generated_starter_templates(conn)
            disable_edit_batch_bundles_with_quarantined_sources(conn)
            row = conn.execute("SELECT * FROM templates WHERE id=?", (cur.lastrowid,)).fetchone()
            row['payload'] = loads(row.pop('payload_json'), {})
            row['is_enabled'] = bool(row['is_enabled'])
            row['requires_manual_configuration'] = bool(
                row.get('requires_manual_configuration')
            )
            return row

    def update_template(self, template_id: int, data: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM templates WHERE id=?",
                (template_id,),
            ).fetchone()
            if not row:
                return None
            current = dict(row)
            current['payload'] = loads(current.pop('payload_json'), {})
            current['is_enabled'] = bool(current['is_enabled'])
            current['requires_manual_configuration'] = bool(
                current.get('requires_manual_configuration')
            )
            next_payload = {
                'template_type': data.get('template_type') or current['template_type'],
                'template_name': data.get('template_name') or current['template_name'],
                'binding_scope': data.get('binding_scope') or current['binding_scope'],
                'payload': data['payload'] if data.get('payload') is not None else current['payload'],
                'is_enabled': current['is_enabled'] if data.get('is_enabled') is None else bool(data['is_enabled']),
            }
            material_changed = (
                'payload' in data
                and data.get('payload') is not None
                and data.get('payload') != current.get('payload')
            )
            requires_manual_configuration = bool(
                current.get('requires_manual_configuration') and not material_changed
            )
            quarantine_reason = (
                current.get('quarantine_reason')
                if requires_manual_configuration
                else None
            )
            if requires_manual_configuration and quarantine_reason in {
                'LEGACY_GENERATED_STARTER_EXACT_MATCH',
                'BUNDLE_REFERENCES_QUARANTINED_SOURCE',
            }:
                next_payload['is_enabled'] = False
            conn.execute(
                """
                UPDATE templates
                   SET template_type=?, template_name=?, binding_scope=?, payload_json=?,
                       is_enabled=?, requires_manual_configuration=?, quarantine_reason=?,
                       updated_at=?
                 WHERE id=?
                """,
                (
                    next_payload['template_type'],
                    next_payload['template_name'],
                    next_payload['binding_scope'],
                    dumps(next_payload['payload']),
                    int(next_payload['is_enabled']),
                    int(requires_manual_configuration),
                    quarantine_reason,
                    now,
                    template_id,
                ),
            )
            # A substantive payload change may clear a legacy marker, but the
            # exact legacy signature or a still-quarantined source reference
            # immediately reinstates quarantine in this same transaction.
            disable_legacy_generated_starter_templates(conn)
            disable_edit_batch_bundles_with_quarantined_sources(conn)
            updated = conn.execute(
                "SELECT * FROM templates WHERE id=?",
                (template_id,),
            ).fetchone()
            updated['payload'] = loads(updated.pop('payload_json'), {})
            updated['is_enabled'] = bool(updated['is_enabled'])
            updated['requires_manual_configuration'] = bool(
                updated.get('requires_manual_configuration')
            )
            return updated

    def get_template(self, template_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
            if not row:
                return None
            row['payload'] = loads(row.pop('payload_json'), {})
            row['is_enabled'] = bool(row['is_enabled'])
            row['requires_manual_configuration'] = bool(
                row.get('requires_manual_configuration')
            )
            return row

    def create_draft_box_scope_snapshot(self, snapshot: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO draft_box_scope_snapshots
                    (schema_version, digest, snapshot_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot['schema_version'],
                    snapshot['digest'],
                    dumps(snapshot),
                    now,
                ),
            )
            stored = {
                'id': int(cur.lastrowid),
                **snapshot,
                'created_at': now,
            }
            return self._public_draft_box_scope_snapshot(stored)

    def get_draft_box_scope_snapshot(self, snapshot_id: int):
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM draft_box_scope_snapshots WHERE id=?",
                (snapshot_id,),
            ).fetchone()
            if not row:
                return None
            snapshot = loads(row['snapshot_json'], {})
            return {
                'id': int(row['id']),
                **snapshot,
                'created_at': row['created_at'],
            }

    @staticmethod
    def _public_draft_box_scope_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        page = snapshot.get('page_identity') if isinstance(snapshot.get('page_identity'), dict) else {}
        store = snapshot.get('store_identity') if isinstance(snapshot.get('store_identity'), dict) else {}
        return {
            'id': snapshot.get('id'),
            'observed_at': snapshot.get('observed_at'),
            'page_identity': {
                'url': page.get('url'),
                'title': page.get('title'),
            },
            'store_identity': {
                'store_name': store.get('store_name'),
            },
            'filter_state': snapshot.get('filter_state'),
            'sort_state': snapshot.get('sort_state'),
            'page_state': snapshot.get('page_state'),
            'items': [
                {
                    'ordinal': item.get('ordinal'),
                    'title': item.get('title'),
                    'dxm_product_id': item.get('dxm_product_id'),
                }
                for item in snapshot.get('items') or []
                if isinstance(item, dict)
            ],
            'zero_write_proof': snapshot.get('zero_write_proof'),
        }

    def create_edit_batch(self, data: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                INSERT INTO edit_batches (
                    schema_version, status,
                    scope_snapshot_id, scope_snapshot_digest, scope_snapshot_json,
                    template_id, template_snapshot_digest, template_snapshot_json,
                    policy_digest, policy_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['schema_version'],
                    data['status'],
                    data['scope_snapshot_id'],
                    data['scope_snapshot_digest'],
                    dumps(data['scope_snapshot']),
                    data['template_id'],
                    data['template_snapshot_digest'],
                    dumps(data['template_snapshot']),
                    data['policy_digest'],
                    dumps(data['policy']),
                    now,
                    now,
                ),
            )
            batch_id = int(cur.lastrowid)
            for item in data['items']:
                conn.execute(
                    """
                    INSERT INTO edit_batch_items (
                        batch_id, ordinal, status, target_identity_sha256,
                        item_snapshot_json, created_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        item['ordinal'],
                        item['target_identity_sha256'],
                        dumps(item),
                        now,
                        now,
                    ),
                )
        return self.get_edit_batch(batch_id)

    def get_edit_batch(self, batch_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                return None
            items = conn.execute(
                "SELECT * FROM edit_batch_items WHERE batch_id=? ORDER BY ordinal ASC",
                (batch_id,),
            ).fetchall()
            decoded = self._decode_edit_batch(row, items, include_execution=True)
            return self._public_edit_batch(decoded)

    def get_edit_batch_private(self, batch_id: int):
        """Return frozen batch facts and hashed authorization state for the executor only."""
        with connection() as conn:
            row = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                return None
            items = conn.execute(
                "SELECT * FROM edit_batch_items WHERE batch_id=? ORDER BY ordinal ASC",
                (batch_id,),
            ).fetchall()
            batch = self._decode_edit_batch(row, items, include_execution=False)
            batch["_private"] = {
                "approval_token_hash": row.get("approval_token_hash"),
                "approval_lease_id": row.get("approval_lease_id"),
                "approval_context": loads(row.get("approval_context_json"), None),
                "approval_token_consumed_at": row.get("approval_token_consumed_at"),
                "start_context": loads(row.get("start_context_json"), None),
                "execution_detail": row.get("execution_detail"),
                "stop_request_context": loads(row.get("stop_request_context_json"), None),
                "item_authorizations": [
                    {
                        "item_id": int(item["id"]),
                        "ordinal": int(item["ordinal"]),
                        "grant_lease_id": item.get("grant_lease_id"),
                        "grant_fingerprint": item.get("grant_fingerprint"),
                        "grant_nonce_hash": item.get("grant_nonce_hash"),
                        "mutation_scope_id": item.get("mutation_scope_id"),
                        "grant": loads(item.get("grant_context_json"), None),
                        "granted_at": item.get("granted_at"),
                        "grant_expires_at": item.get("grant_expires_at"),
                        "grant_consumed_at": item.get("grant_consumed_at"),
                        "outcome_evidence": loads(item.get("outcome_evidence_json"), None),
                        "outcome_decision": loads(item.get("outcome_decision_json"), None),
                        "action_results": loads(item.get("action_results_json"), None),
                    }
                    for item in items
                ],
            }
            return batch

    def approve_edit_batch(self, batch_id: int, approval: dict[str, Any]) -> BatchApprovalResult:
        now = now_iso()
        reason_code = "BATCH_NOT_DRAFT"
        try:
            stored_approval = normalize_approval_for_storage(approval)
        except EditBatchExecutionPersistenceError as exc:
            return BatchApprovalResult(False, exc.reason_code, None)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM edit_batches WHERE id=?",
                (batch_id,),
            ).fetchone()
            if not row:
                return BatchApprovalResult(False, "BATCH_NOT_FOUND", None)
            if row["status"] != "draft":
                return BatchApprovalResult(False, reason_code, None)
            template_rejection = self._edit_batch_live_template_rejection(conn, row)
            if template_rejection is not None:
                return BatchApprovalResult(False, template_rejection, None)
            cursor = conn.execute(
                """
                UPDATE edit_batches
                   SET status='approved',
                       approval_token_hash=?, approval_lease_id=?, approval_context_json=?,
                       updated_at=?
                 WHERE id=? AND status='draft'
                """,
                (
                    stored_approval["token_hash"],
                    stored_approval["lease_id"],
                    dumps(stored_approval["context"]),
                    now,
                    batch_id,
                ),
            )
            if cursor.rowcount != 1:
                return BatchApprovalResult(False, reason_code, None)
        return BatchApprovalResult(True, "OK", self.get_edit_batch(batch_id))

    def approve_and_start_edit_batch(
        self,
        batch_id: int,
        approval: dict[str, Any],
        start_context: dict[str, Any],
        *,
        consumed_at: str | None = None,
    ) -> EditBatchExecutionTransitionResult:
        """Atomically persist approval and consume it while moving draft -> running."""
        try:
            transition_at = self._edit_batch_timestamp(consumed_at)
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        try:
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
                if not row:
                    return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
                if row["status"] != "draft":
                    return self._edit_batch_execution_failure("BATCH_NOT_DRAFT")
                if self._other_active_edit_batch_exists(conn, batch_id):
                    return self._edit_batch_execution_failure("ANOTHER_EDIT_BATCH_ACTIVE")
                if self._running_task_exists(conn):
                    return self._edit_batch_execution_failure("LEGACY_TASK_ACTIVE")
                template_rejection = self._edit_batch_live_template_rejection(conn, row)
                if template_rejection is not None:
                    return self._edit_batch_execution_failure(template_rejection)
                items = self._edit_batch_item_rows(conn, batch_id)
                if not items or any(item["status"] != "pending" for item in items):
                    return self._edit_batch_execution_failure("BATCH_ITEMS_NOT_STARTABLE")

                stored_approval = normalize_approval_for_storage(approval)
                stored_start = normalize_start_context_for_storage(
                    start_context,
                    batch_row=row,
                    approval_context=stored_approval["context"],
                    consumed_at=transition_at,
                )
                cursor = conn.execute(
                    """
                    UPDATE edit_batches
                       SET status='running',
                           approval_token_hash=?,
                           approval_lease_id=?,
                           approval_context_json=?,
                           approval_token_consumed_at=?,
                           start_context_json=?,
                           started_at=?,
                           execution_reason_code='BATCH_STARTED',
                           manual_review_required=0,
                           updated_at=?
                     WHERE id=? AND status='draft'
                    """,
                    (
                        stored_approval["token_hash"],
                        stored_approval["lease_id"],
                        dumps(stored_approval["context"]),
                        transition_at,
                        dumps(stored_start),
                        transition_at,
                        transition_at,
                        batch_id,
                    ),
                )
                if cursor.rowcount != 1:
                    return self._edit_batch_execution_failure("BATCH_START_CAS_CONFLICT")
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        except sqlite3.IntegrityError:
            return self._edit_batch_execution_failure("ANOTHER_EDIT_BATCH_ACTIVE")
        return self._edit_batch_execution_success(batch_id)

    def start_approved_edit_batch(
        self,
        batch_id: int,
        start_context: dict[str, Any],
        *,
        consumed_at: str | None = None,
    ) -> EditBatchExecutionTransitionResult:
        """Consume an already-issued approval using an approved -> running CAS."""
        try:
            transition_at = self._edit_batch_timestamp(consumed_at)
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        try:
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
                if not row:
                    return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
                if row["status"] != "approved":
                    return self._edit_batch_execution_failure("BATCH_NOT_APPROVED")
                if row.get("approval_token_consumed_at"):
                    return self._edit_batch_execution_failure("APPROVAL_TOKEN_ALREADY_CONSUMED")
                if self._other_active_edit_batch_exists(conn, batch_id):
                    return self._edit_batch_execution_failure("ANOTHER_EDIT_BATCH_ACTIVE")
                if self._running_task_exists(conn):
                    return self._edit_batch_execution_failure("LEGACY_TASK_ACTIVE")
                template_rejection = self._edit_batch_live_template_rejection(conn, row)
                if template_rejection is not None:
                    return self._edit_batch_execution_failure(template_rejection)
                items = self._edit_batch_item_rows(conn, batch_id)
                if not items or any(item["status"] != "pending" for item in items):
                    return self._edit_batch_execution_failure("BATCH_ITEMS_NOT_STARTABLE")

                stored_approval = normalize_approval_for_storage(
                    {
                        "token_hash": row.get("approval_token_hash"),
                        "lease_id": row.get("approval_lease_id"),
                        "context": loads(row.get("approval_context_json"), None),
                    }
                )
                stored_start = normalize_start_context_for_storage(
                    start_context,
                    batch_row=row,
                    approval_context=stored_approval["context"],
                    consumed_at=transition_at,
                )
                cursor = conn.execute(
                    """
                    UPDATE edit_batches
                       SET status='running',
                           approval_token_consumed_at=?,
                           start_context_json=?,
                           started_at=?,
                           execution_reason_code='BATCH_STARTED',
                           manual_review_required=0,
                           updated_at=?
                     WHERE id=?
                       AND status='approved'
                       AND approval_token_consumed_at IS NULL
                       AND approval_lease_id=?
                       AND approval_token_hash=?
                    """,
                    (
                        transition_at,
                        dumps(stored_start),
                        transition_at,
                        transition_at,
                        batch_id,
                        stored_approval["lease_id"],
                        stored_approval["token_hash"],
                    ),
                )
                if cursor.rowcount != 1:
                    return self._edit_batch_execution_failure("BATCH_START_CAS_CONFLICT")
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        except sqlite3.IntegrityError:
            return self._edit_batch_execution_failure("ANOTHER_EDIT_BATCH_ACTIVE")
        return self._edit_batch_execution_success(batch_id)

    def claim_next_edit_batch_item(
        self,
        batch_id: int,
    ) -> EditBatchExecutionTransitionResult:
        """Atomically claim the next item without creating any save authority."""

        claimed_at = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute("SELECT status FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
            if batch["status"] != "running":
                return self._edit_batch_execution_failure("BATCH_NOT_RUNNING")
            items = self._edit_batch_item_rows(conn, batch_id)
            if not items:
                return self._edit_batch_execution_failure("BATCH_HAS_NO_ITEMS")
            if any(item["status"] == "running" for item in items):
                return self._edit_batch_execution_failure("ANOTHER_BATCH_ITEM_RUNNING")
            item = next((row for row in items if row["status"] == "pending"), None)
            if item is None:
                return self._edit_batch_execution_failure("BATCH_NO_PENDING_ITEM")
            prior = [row for row in items if int(row["ordinal"]) < int(item["ordinal"])]
            following = [row for row in items if int(row["ordinal"]) > int(item["ordinal"])]
            if any(row["status"] not in ITEM_CONTINUE_TERMINAL_STATUSES for row in prior):
                return self._edit_batch_execution_failure("BATCH_PRIOR_ITEM_NOT_SAFE")
            if any(row["status"] != "pending" for row in following):
                return self._edit_batch_execution_failure("BATCH_ITEM_ORDER_INVALID")
            if any(
                item.get(column) is not None
                for column in (
                    "grant_lease_id",
                    "grant_fingerprint",
                    "grant_nonce_hash",
                    "mutation_scope_id",
                    "grant_context_json",
                    "granted_at",
                    "grant_expires_at",
                    "grant_consumed_at",
                )
            ):
                return self._edit_batch_execution_failure("PENDING_ITEM_AUTHORITY_PRESENT")
            cursor = conn.execute(
                """
                UPDATE edit_batch_items
                   SET status='running', claimed_at=?, updated_at=?
                 WHERE id=? AND batch_id=? AND status='pending'
                   AND grant_lease_id IS NULL
                   AND grant_fingerprint IS NULL
                   AND grant_nonce_hash IS NULL
                   AND mutation_scope_id IS NULL
                   AND grant_context_json IS NULL
                   AND grant_consumed_at IS NULL
                """,
                (claimed_at, claimed_at, item["id"], batch_id),
            )
            if cursor.rowcount != 1:
                return self._edit_batch_execution_failure("ITEM_CLAIM_CAS_CONFLICT")
            item_id = int(item["id"])
        return self._edit_batch_execution_success(batch_id, item_id=item_id)

    def issue_edit_batch_item_grant(
        self,
        batch_id: int,
        item_id: int,
        grant: dict[str, Any],
    ) -> EditBatchExecutionTransitionResult:
        """Persist one 60-second grant for an already-claimed running item."""
        try:
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                batch = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
                if not batch:
                    return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
                if batch["status"] != "running":
                    return self._edit_batch_execution_failure("BATCH_NOT_RUNNING")
                template_rejection = self._edit_batch_live_template_rejection(
                    conn, batch
                )
                if template_rejection is not None:
                    return self._edit_batch_execution_failure(template_rejection)
                start_context = loads(batch.get("start_context_json"), None)
                if not isinstance(start_context, dict):
                    return self._edit_batch_execution_failure("BATCH_START_CONTEXT_MISSING")
                items = self._edit_batch_item_rows(conn, batch_id)
                item = next((row for row in items if int(row["id"]) == item_id), None)
                if not item:
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_FOUND")

                normalized_grant = normalize_item_grant_for_storage(
                    grant,
                    batch_row=batch,
                    item_row=item,
                    start_context=start_context,
                )
                issued_at = datetime.fromisoformat(
                    str(normalized_grant["issued_at"]).replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                expires_at = datetime.fromisoformat(
                    str(normalized_grant["expires_at"]).replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                grant_checked_at = datetime.now(timezone.utc)
                if grant_checked_at < issued_at or grant_checked_at >= expires_at:
                    return self._edit_batch_execution_failure("ITEM_GRANT_NOT_CURRENT")
                if conn.execute(
                    """
                    SELECT 1 AS present
                      FROM mutation_dispatch_ledger
                     WHERE mutation_scope_id=?
                     LIMIT 1
                    """,
                    (normalized_grant["mutation_scope_id"],),
                ).fetchone() is not None:
                    return self._edit_batch_execution_failure(
                        "ITEM_GRANT_LEDGER_SCOPE_ALREADY_PRESENT"
                    )
                existing_grant = loads(item.get("grant_context_json"), None)
                if item["status"] != "running":
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_RUNNING")
                running_items = [row for row in items if row["status"] == "running"]
                if len(running_items) != 1 or int(running_items[0]["id"]) != item_id:
                    return self._edit_batch_execution_failure("ANOTHER_BATCH_ITEM_RUNNING")
                prior_items = [row for row in items if int(row["ordinal"]) < int(item["ordinal"])]
                if any(row["status"] not in ITEM_CONTINUE_TERMINAL_STATUSES for row in prior_items):
                    return self._edit_batch_execution_failure("BATCH_PRIOR_ITEM_NOT_SAFE")
                if existing_grant is not None or any(
                    item.get(column) is not None
                    for column in (
                        "grant_lease_id",
                        "grant_fingerprint",
                        "grant_nonce_hash",
                        "mutation_scope_id",
                        "granted_at",
                        "grant_expires_at",
                        "grant_consumed_at",
                    )
                ):
                    exact_existing = {
                        "grant_lease_id": normalized_grant["grant_lease_id"],
                        "grant_fingerprint": normalized_grant["fingerprint"],
                        "grant_nonce_hash": normalized_grant["nonce_hash"],
                        "mutation_scope_id": normalized_grant["mutation_scope_id"],
                        "granted_at": normalized_grant["issued_at"],
                        "grant_expires_at": normalized_grant["expires_at"],
                    }
                    if (
                        existing_grant == normalized_grant
                        and not item.get("grant_consumed_at")
                        and all(item.get(key) == value for key, value in exact_existing.items())
                    ):
                        return self._edit_batch_execution_success(
                            batch_id,
                            item_id=item_id,
                            applied=True,
                            idempotent=True,
                            reason_code="ITEM_GRANT_ALREADY_ISSUED",
                        )
                    return self._edit_batch_execution_failure("ITEM_GRANT_ALREADY_PRESENT")

                cursor = conn.execute(
                    """
                    UPDATE edit_batch_items
                       SET grant_lease_id=?,
                           grant_fingerprint=?,
                           grant_nonce_hash=?,
                           mutation_scope_id=?,
                           grant_context_json=?,
                           granted_at=?,
                           grant_expires_at=?,
                           updated_at=?
                     WHERE id=? AND batch_id=? AND status='running'
                       AND grant_lease_id IS NULL
                       AND grant_fingerprint IS NULL
                       AND grant_nonce_hash IS NULL
                       AND mutation_scope_id IS NULL
                       AND grant_context_json IS NULL
                       AND grant_consumed_at IS NULL
                    """,
                    (
                        normalized_grant["grant_lease_id"],
                        normalized_grant["fingerprint"],
                        normalized_grant["nonce_hash"],
                        normalized_grant["mutation_scope_id"],
                        dumps(normalized_grant),
                        normalized_grant["issued_at"],
                        normalized_grant["expires_at"],
                        now_iso(),
                        item_id,
                        batch_id,
                    ),
                )
                if cursor.rowcount != 1:
                    return self._edit_batch_execution_failure("ITEM_GRANT_CAS_CONFLICT")
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        except sqlite3.IntegrityError:
            return self._edit_batch_execution_failure("ITEM_GRANT_UNIQUENESS_CONFLICT")
        return self._edit_batch_execution_success(batch_id, item_id=item_id)

    def consume_edit_batch_item_grant(
        self,
        batch_id: int,
        item_id: int,
        consumption: dict[str, Any],
    ) -> EditBatchExecutionTransitionResult:
        """CAS-consume the persisted nonce hash immediately before the save mutation."""
        try:
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                batch = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
                if not batch:
                    return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
                if batch["status"] != "running":
                    return self._edit_batch_execution_failure("BATCH_NOT_RUNNING")
                template_rejection = self._edit_batch_live_template_rejection(
                    conn, batch
                )
                if template_rejection is not None:
                    return self._edit_batch_execution_failure(template_rejection)
                item = conn.execute(
                    "SELECT * FROM edit_batch_items WHERE id=? AND batch_id=?",
                    (item_id, batch_id),
                ).fetchone()
                if not item:
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_FOUND")
                if item["status"] != "running":
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_RUNNING")
                if item.get("grant_consumed_at"):
                    return self._edit_batch_execution_failure("ITEM_GRANT_ALREADY_CONSUMED")
                stored_grant = loads(item.get("grant_context_json"), None)
                if not isinstance(stored_grant, dict):
                    return self._edit_batch_execution_failure("ITEM_GRANT_MISSING")
                consumed_at = now_iso()
                normalized = normalize_item_grant_consumption_for_storage(
                    consumption,
                    batch_row=batch,
                    item_row=item,
                    stored_grant=stored_grant,
                    consumed_at=consumed_at,
                )
                ledger_rejection = self._edit_batch_reserved_ledger_rejection(
                    conn,
                    batch_id=batch_id,
                    item_id=item_id,
                    item_row=item,
                    stored_grant=stored_grant,
                    consumed_at=consumed_at,
                )
                if ledger_rejection is not None:
                    return self._edit_batch_execution_failure(ledger_rejection)
                cursor = conn.execute(
                    """
                    UPDATE edit_batch_items
                       SET grant_consumed_at=?, updated_at=?
                     WHERE id=? AND batch_id=? AND status='running'
                       AND grant_consumed_at IS NULL
                       AND grant_fingerprint=?
                       AND grant_nonce_hash=?
                    """,
                    (
                        consumed_at,
                        consumed_at,
                        item_id,
                        batch_id,
                        normalized["grant_fingerprint"],
                        normalized["consumed_nonce_hash"],
                    ),
                )
                if cursor.rowcount != 1:
                    return self._edit_batch_execution_failure("ITEM_GRANT_CONSUME_CAS_CONFLICT")
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        return self._edit_batch_execution_success(batch_id, item_id=item_id)

    def consumed_edit_batch_nonce_hashes(self, batch_id: int) -> set[str]:
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT grant_nonce_hash
                  FROM edit_batch_items
                 WHERE batch_id=?
                   AND grant_consumed_at IS NOT NULL
                   AND grant_nonce_hash IS NOT NULL
                """,
                (batch_id,),
            ).fetchall()
            return {str(row["grant_nonce_hash"]) for row in rows}

    def complete_edit_batch_item(
        self,
        batch_id: int,
        item_id: int,
        decision: dict[str, Any],
        outcome: dict[str, Any],
        action_results: list[dict[str, Any]],
    ) -> EditBatchExecutionTransitionResult:
        """Persist a terminal item result; uncertain evidence stops the whole batch."""
        finished_at = now_iso()
        try:
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                batch = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
                if not batch:
                    return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
                items = self._edit_batch_item_rows(conn, batch_id)
                item = next((row for row in items if int(row["id"]) == item_id), None)
                if not item:
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_FOUND")

                if item["status"] in ITEM_TERMINAL_STATUSES:
                    try:
                        replay_decision = normalize_execution_evidence_for_storage(decision)
                        replay_outcome = normalize_execution_evidence_for_storage(outcome)
                        replay_actions = normalize_action_results_for_storage(action_results)
                    except EditBatchExecutionPersistenceError:
                        return self._edit_batch_execution_failure("ITEM_OUTCOME_CONFLICT")
                    if (
                        loads(item.get("outcome_decision_json"), None) == replay_decision
                        and loads(item.get("outcome_evidence_json"), None) == replay_outcome
                        and loads(item.get("action_results_json"), None) == replay_actions
                    ):
                        return self._edit_batch_execution_success(
                            batch_id,
                            item_id=item_id,
                            applied=True,
                            idempotent=True,
                            reason_code="ITEM_OUTCOME_ALREADY_RECORDED",
                        )
                    return self._edit_batch_execution_failure("ITEM_OUTCOME_CONFLICT")

                stored_grant = loads(item.get("grant_context_json"), None)
                start_context = loads(batch.get("start_context_json"), None)
                try:
                    claim_context = derive_running_item_claim_context(
                        self._decode_edit_batch(batch, items, include_execution=False),
                        start_context=start_context,
                        allow_stop_requested=True,
                    )
                except BatchExecutionContractError as exc:
                    return self._edit_batch_execution_failure(exc.reason_code)

                normalized_actions = normalize_action_results_for_storage(action_results)
                normalized_decision, normalized_outcome = normalize_item_outcome_for_storage(
                    decision,
                    outcome,
                    batch_id=batch_id,
                    item_id=item_id,
                    ordinal=int(item["ordinal"]),
                    stored_grant=stored_grant if isinstance(stored_grant, dict) else None,
                    claim_context=claim_context,
                    action_results=normalized_actions,
                )
                target_status = normalized_decision["item_transition"]["to_status"]
                if batch["status"] not in {"running", "stop_requested"}:
                    return self._edit_batch_execution_failure("BATCH_NOT_ACTIVE")
                if item["status"] != "running":
                    return self._edit_batch_execution_failure("BATCH_ITEM_NOT_RUNNING")

                classification = normalized_decision["classification"]
                if classification == "SUCCEEDED" and not item.get("grant_consumed_at"):
                    return self._edit_batch_execution_failure("ITEM_GRANT_NOT_CONSUMED")
                if classification == "SUCCEEDED":
                    ledger_rejection = self._edit_batch_dispatched_ledger_rejection(
                        conn,
                        batch_id=batch_id,
                        item_id=item_id,
                        item_row=item,
                        stored_grant=(
                            stored_grant if isinstance(stored_grant, dict) else None
                        ),
                        outcome=normalized_outcome,
                    )
                    if ledger_rejection is not None:
                        return self._edit_batch_execution_failure(ledger_rejection)
                if classification == "ISOLATED_PRE_SAVE_NO_WRITE" and any(
                    item.get(column) is not None
                    for column in (
                        "grant_lease_id",
                        "grant_fingerprint",
                        "grant_nonce_hash",
                        "mutation_scope_id",
                        "grant_context_json",
                        "granted_at",
                        "grant_expires_at",
                        "grant_consumed_at",
                    )
                ):
                    return self._edit_batch_execution_failure("ISOLATED_ITEM_AUTHORITY_PRESENT")
                manual_review = classification == "STOPPED_UNCERTAIN"
                cursor = conn.execute(
                    """
                    UPDATE edit_batch_items
                       SET status=?,
                           outcome_classification=?,
                           outcome_reason_code=?,
                           outcome_evidence_json=?,
                           outcome_decision_json=?,
                           action_results_json=?,
                           finished_at=?,
                           manual_review_required=?,
                           updated_at=?
                     WHERE id=? AND batch_id=? AND status='running'
                    """,
                    (
                        target_status,
                        classification,
                        normalized_decision["reason_code"],
                        dumps(normalized_outcome),
                        dumps(normalized_decision),
                        dumps(normalized_actions),
                        finished_at,
                        int(manual_review),
                        finished_at,
                        item_id,
                        batch_id,
                    ),
                )
                if cursor.rowcount != 1:
                    return self._edit_batch_execution_failure("ITEM_OUTCOME_CAS_CONFLICT")

                if manual_review:
                    batch_cursor = conn.execute(
                        """
                        UPDATE edit_batches
                           SET status='stopped', stopped_at=?, execution_reason_code=?,
                               manual_review_required=1, updated_at=?
                         WHERE id=? AND status IN ('running', 'stop_requested')
                        """,
                        (
                            finished_at,
                            normalized_decision["reason_code"],
                            finished_at,
                            batch_id,
                        ),
                    )
                    if batch_cursor.rowcount != 1:
                        conn.rollback()
                        return self._edit_batch_execution_failure("BATCH_STOP_CAS_CONFLICT")
                elif batch["status"] == "stop_requested":
                    batch_cursor = conn.execute(
                        """
                        UPDATE edit_batches
                           SET status='stopped', stopped_at=?,
                               execution_reason_code='STOP_REQUESTED_SAFE_ITEM_BOUNDARY',
                               updated_at=?
                         WHERE id=? AND status='stop_requested'
                        """,
                        (finished_at, finished_at, batch_id),
                    )
                    if batch_cursor.rowcount != 1:
                        conn.rollback()
                        return self._edit_batch_execution_failure("BATCH_STOP_CAS_CONFLICT")
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        return self._edit_batch_execution_success(batch_id, item_id=item_id)

    def request_stop_edit_batch(
        self,
        batch_id: int,
        *,
        requested_by: str,
        reason: str | None = None,
    ) -> EditBatchExecutionTransitionResult:
        requested_at = now_iso()
        operator = " ".join(str(requested_by or "").split())
        detail = " ".join(str(reason or "").split()) or None
        if not operator or len(operator) > 200 or (detail is not None and len(detail) > 500):
            return self._edit_batch_execution_failure("STOP_REQUEST_INVALID")
        request_context = {
            "schema_version": "dxm_edit_batch_stop_request.v1",
            "requested_by": operator,
            "reason": detail,
            "requested_at": requested_at,
        }
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
            if row["status"] == "stop_requested":
                return self._edit_batch_execution_success(
                    batch_id,
                    applied=True,
                    idempotent=True,
                    reason_code="STOP_ALREADY_REQUESTED",
                )
            if row["status"] != "running":
                return self._edit_batch_execution_failure("BATCH_NOT_RUNNING")
            cursor = conn.execute(
                """
                UPDATE edit_batches
                   SET status='stop_requested', stop_requested_at=?,
                       execution_reason_code='OPERATOR_STOP_REQUESTED',
                       execution_detail=?, stop_request_context_json=?, updated_at=?
                 WHERE id=? AND status='running'
                """,
                (requested_at, detail, dumps(request_context), requested_at, batch_id),
            )
            if cursor.rowcount != 1:
                return self._edit_batch_execution_failure("STOP_REQUEST_CAS_CONFLICT")
        return self._edit_batch_execution_success(batch_id)

    def stop_edit_batch(
        self,
        batch_id: int,
        reason_code: str = "STOP_REQUESTED",
        reason: str | None = None,
        requires_manual_review: bool = True,
        *,
        evidence: dict[str, Any] | None = None,
        action_results: list[dict[str, Any]] | None = None,
    ) -> EditBatchExecutionTransitionResult:
        """Finalize an active batch and classify a running item from durable dispatch facts."""
        stopped_at = now_iso()
        try:
            canonical_reason = self._edit_batch_reason_code(reason_code)
        except EditBatchExecutionPersistenceError as exc:
            return self._edit_batch_execution_failure(exc.reason_code)
        detail = " ".join(str(reason or "").split()) or None
        if detail is not None and len(detail) > 1000:
            return self._edit_batch_execution_failure("STOP_REASON_DETAIL_INVALID")
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute("SELECT * FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
            if batch["status"] == "stopped":
                return self._edit_batch_execution_success(
                    batch_id,
                    applied=True,
                    idempotent=True,
                    reason_code="BATCH_ALREADY_STOPPED",
                )
            if batch["status"] not in {"running", "stop_requested"}:
                return self._edit_batch_execution_failure("BATCH_NOT_ACTIVE")
            running_items = conn.execute(
                "SELECT * FROM edit_batch_items WHERE batch_id=? AND status='running'",
                (batch_id,),
            ).fetchall()
            if len(running_items) > 1:
                return self._edit_batch_execution_failure("MULTIPLE_BATCH_ITEMS_RUNNING")
            safe_stop_evidence: dict[str, Any] | None = None
            if running_items:
                safe_stop_evidence = self._edit_batch_safe_pre_dispatch_stop_evidence(
                    conn,
                    batch_row=batch,
                    item_row=running_items[0],
                    reason_code=canonical_reason,
                    detail=detail,
                    stopped_at=stopped_at,
                )
            running_item_safe = safe_stop_evidence is not None
            manual_review = bool(
                requires_manual_review or (running_items and not running_item_safe)
            )
            if running_items:
                item = running_items[0]
                stop_evidence = (
                    safe_stop_evidence
                    if running_item_safe
                    else evidence
                    or {
                        "schema_version": "dxm_edit_batch_stop_evidence.v1",
                        "reason_code": canonical_reason,
                        "detail": detail,
                        "stopped_at": stopped_at,
                        "retry_allowed": False,
                        "zero_dispatch_proven": False,
                    }
                )
                safe_actions = action_results or []
                try:
                    canonical_evidence = normalize_execution_evidence_for_storage(stop_evidence)
                    canonical_actions = normalize_action_results_for_storage(safe_actions)
                except EditBatchExecutionPersistenceError:
                    return self._edit_batch_execution_failure("STOP_EVIDENCE_INVALID")
                item_status = (
                    "stopped_before_save_no_write"
                    if running_item_safe
                    else "stopped_uncertain"
                )
                classification = (
                    "STOPPED_BEFORE_SAVE_NO_WRITE"
                    if running_item_safe
                    else "STOPPED_UNCERTAIN"
                )
                item_cursor = conn.execute(
                    """
                    UPDATE edit_batch_items
                       SET status=?,
                           outcome_classification=?,
                           outcome_reason_code=?,
                           outcome_evidence_json=?,
                           action_results_json=?,
                           finished_at=?,
                           manual_review_required=?,
                           updated_at=?
                     WHERE id=? AND batch_id=? AND status='running'
                    """,
                    (
                        item_status,
                        classification,
                        canonical_reason,
                        dumps(canonical_evidence),
                        dumps(canonical_actions),
                        stopped_at,
                        int(manual_review),
                        stopped_at,
                        item["id"],
                        batch_id,
                    ),
                )
                if item_cursor.rowcount != 1:
                    conn.rollback()
                    return self._edit_batch_execution_failure("ITEM_STOP_CAS_CONFLICT")
            cursor = conn.execute(
                """
                UPDATE edit_batches
                   SET status='stopped', stopped_at=?, execution_reason_code=?,
                       execution_detail=?, manual_review_required=?, updated_at=?
                 WHERE id=? AND status IN ('running', 'stop_requested')
                """,
                (
                    stopped_at,
                    canonical_reason,
                    detail,
                    int(manual_review),
                    stopped_at,
                    batch_id,
                ),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return self._edit_batch_execution_failure("STOP_CAS_CONFLICT")
        return self._edit_batch_execution_success(batch_id)

    def complete_edit_batch(self, batch_id: int) -> EditBatchExecutionTransitionResult:
        completed_at = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute("SELECT status FROM edit_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                return self._edit_batch_execution_failure("BATCH_NOT_FOUND")
            if batch["status"] == "completed":
                return self._edit_batch_execution_success(
                    batch_id,
                    applied=True,
                    idempotent=True,
                    reason_code="BATCH_ALREADY_COMPLETED",
                )
            if batch["status"] != "running":
                return self._edit_batch_execution_failure("BATCH_NOT_RUNNING")
            items = self._edit_batch_item_rows(conn, batch_id)
            if not items:
                return self._edit_batch_execution_failure("BATCH_HAS_NO_ITEMS")
            if any(item["status"] not in ITEM_CONTINUE_TERMINAL_STATUSES for item in items):
                return self._edit_batch_execution_failure("BATCH_ITEMS_NOT_COMPLETE")
            cursor = conn.execute(
                """
                UPDATE edit_batches
                   SET status='completed', completed_at=?,
                       execution_reason_code='ALL_ITEMS_COMPLETED',
                       manual_review_required=0, updated_at=?
                 WHERE id=? AND status='running'
                """,
                (completed_at, completed_at, batch_id),
            )
            if cursor.rowcount != 1:
                return self._edit_batch_execution_failure("BATCH_COMPLETE_CAS_CONFLICT")
        return self._edit_batch_execution_success(batch_id)

    def recover_interrupted_edit_batches(self) -> dict[str, Any]:
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch_ids = recover_edit_batches_in_db(conn)
        return {
            "applied": bool(batch_ids),
            "reason_code": "INTERRUPTED_BATCHES_STOPPED" if batch_ids else "NO_INTERRUPTED_BATCHES",
            "recovered_count": len(batch_ids),
            "batch_ids": batch_ids,
            "manual_review_required": bool(batch_ids),
            "auto_resumed": False,
        }

    def get_active_edit_batch_execution(self) -> dict[str, Any] | None:
        """Expose only the active batch identity and progress for cross-workflow gating."""
        with connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM edit_batches
                 WHERE status IN ('running', 'stop_requested')
                 ORDER BY started_at ASC, id ASC
                 LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            items = self._edit_batch_item_rows(conn, int(row["id"]))
            return {
                "id": int(row["id"]),
                "status": row["status"],
                "execution": build_public_execution(row),
                "progress": build_public_progress(items),
            }

    def get_active_task_execution(self) -> dict[str, Any] | None:
        """Expose a minimal legacy-task fact set before any batch recapture work."""

        with connection() as conn:
            row = conn.execute(
                """
                SELECT id, status, mode
                  FROM tasks
                 WHERE status='running'
                 ORDER BY updated_at ASC, id ASC
                 LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row["id"]),
                "status": str(row["status"]),
                "mode": str(row["mode"]),
            }

    @staticmethod
    def _edit_batch_execution_failure(reason_code: str) -> EditBatchExecutionTransitionResult:
        return EditBatchExecutionTransitionResult(
            applied=False,
            idempotent=False,
            reason_code=reason_code,
            batch=None,
            item=None,
        )

    def _edit_batch_execution_success(
        self,
        batch_id: int,
        *,
        item_id: int | None = None,
        applied: bool = True,
        idempotent: bool = False,
        reason_code: str = "OK",
    ) -> EditBatchExecutionTransitionResult:
        batch = self.get_edit_batch(batch_id)
        item = None
        if batch and item_id is not None:
            item = next(
                (value for value in batch.get("items", []) if int(value.get("id", 0)) == item_id),
                None,
            )
        return EditBatchExecutionTransitionResult(
            applied=applied,
            idempotent=idempotent,
            reason_code=reason_code,
            batch=batch,
            item=item,
        )

    @staticmethod
    def _other_active_edit_batch_exists(conn: Any, batch_id: int) -> bool:
        row = conn.execute(
            """
            SELECT id
              FROM edit_batches
             WHERE status IN ('running', 'stop_requested') AND id<>?
             LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _running_task_exists(conn: Any) -> bool:
        return conn.execute(
            "SELECT 1 AS active FROM tasks WHERE status='running' LIMIT 1"
        ).fetchone() is not None

    @staticmethod
    def _other_running_task_exists(conn: Any, task_id: int) -> bool:
        return conn.execute(
            "SELECT 1 AS active FROM tasks WHERE status='running' AND id<>? LIMIT 1",
            (task_id,),
        ).fetchone() is not None

    @staticmethod
    def _active_edit_batch_exists(conn: Any) -> bool:
        return conn.execute(
            """
            SELECT 1 AS active
              FROM edit_batches
             WHERE status IN ('running', 'stop_requested')
             LIMIT 1
            """
        ).fetchone() is not None

    @staticmethod
    def _edit_batch_live_template_rejection(
        conn: Any,
        batch_row: dict[str, Any],
    ) -> str | None:
        template_row = conn.execute(
            "SELECT * FROM templates WHERE id=?",
            (batch_row.get("template_id"),),
        ).fetchone()
        if not isinstance(template_row, dict):
            return "TEMPLATE_NOT_FOUND"
        template = dict(template_row)
        template["payload"] = loads(template.pop("payload_json", None), {})
        template["is_enabled"] = bool(template.get("is_enabled"))
        template["requires_manual_configuration"] = bool(
            template.get("requires_manual_configuration")
        )
        try:
            frozen = freeze_template_bundle(template)
        except BatchContractError as exc:
            return exc.reason_code
        if (
            int(frozen.get("id") or 0) != int(batch_row.get("template_id") or 0)
            or canonical_sha256(frozen)
            != str(batch_row.get("template_snapshot_digest") or "")
        ):
            return "BATCH_TEMPLATE_SNAPSHOT_DRIFT"
        return None

    @classmethod
    def _edit_batch_safe_pre_dispatch_stop_evidence(
        cls,
        conn: Any,
        *,
        batch_row: dict[str, Any],
        item_row: dict[str, Any],
        reason_code: str,
        detail: str | None,
        stopped_at: str,
    ) -> dict[str, Any] | None:
        """Prove zero dispatch and terminate an exact RESERVED row in one write txn."""

        authority_columns = (
            "grant_lease_id",
            "grant_fingerprint",
            "grant_nonce_hash",
            "mutation_scope_id",
            "grant_context_json",
            "granted_at",
            "grant_expires_at",
        )
        scope_id = item_row.get("mutation_scope_id")
        if scope_id is None:
            ledger_rows = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE task_id=? AND job_id=?
                 ORDER BY id ASC
                """,
                (str(batch_row["id"]), str(item_row["id"])),
            ).fetchall()
        else:
            ledger_rows = conn.execute(
                """
                SELECT * FROM mutation_dispatch_ledger
                 WHERE (task_id=? AND job_id=?) OR mutation_scope_id=?
                 ORDER BY id ASC
                """,
                (str(batch_row["id"]), str(item_row["id"]), str(scope_id)),
            ).fetchall()

        authority_present = [item_row.get(column) is not None for column in authority_columns]
        if item_row.get("grant_consumed_at") is not None:
            return None
        if not any(authority_present):
            if ledger_rows:
                return None
            return {
                "schema_version": "dxm_edit_batch_stop_evidence.v1",
                "classification": "STOPPED_BEFORE_SAVE_NO_WRITE",
                "reason_code": reason_code,
                "detail": detail,
                "stopped_at": stopped_at,
                "retry_allowed": False,
                "grant_issued": False,
                "grant_consumed": False,
                "ledger_status": None,
                "zero_dispatch_proven": True,
            }
        if not all(authority_present):
            return None

        stored_grant = loads(item_row.get("grant_context_json"), None)
        start_context = loads(batch_row.get("start_context_json"), None)
        if not isinstance(stored_grant, dict) or not isinstance(start_context, dict):
            return None
        try:
            normalized_grant = normalize_item_grant_for_storage(
                stored_grant,
                batch_row=batch_row,
                item_row=item_row,
                start_context=start_context,
            )
        except EditBatchExecutionPersistenceError:
            return None
        if normalized_grant != stored_grant:
            return None
        item_binding = {
            "grant_lease_id": normalized_grant.get("grant_lease_id"),
            "grant_fingerprint": normalized_grant.get("fingerprint"),
            "grant_nonce_hash": normalized_grant.get("nonce_hash"),
            "mutation_scope_id": normalized_grant.get("mutation_scope_id"),
            "granted_at": normalized_grant.get("issued_at"),
            "grant_expires_at": normalized_grant.get("expires_at"),
        }
        if any(item_row.get(key) != value for key, value in item_binding.items()):
            return None
        granted = cls._edit_batch_ledger_time(item_row.get("granted_at"))
        stopped = cls._edit_batch_ledger_time(stopped_at)
        if granted is None or stopped is None or granted > stopped:
            return None
        if not ledger_rows:
            return {
                "schema_version": "dxm_edit_batch_stop_evidence.v1",
                "classification": "STOPPED_BEFORE_SAVE_NO_WRITE",
                "reason_code": reason_code,
                "detail": detail,
                "stopped_at": stopped_at,
                "retry_allowed": False,
                "grant_issued": True,
                "grant_consumed": False,
                "ledger_status": None,
                "zero_dispatch_proven": True,
            }
        if len(ledger_rows) != 1:
            return None
        ledger_row = ledger_rows[0]
        rejection = cls._edit_batch_ledger_binding_rejection(
            ledger_row,
            batch_id=int(batch_row["id"]),
            item_id=int(item_row["id"]),
            item_row=item_row,
            stored_grant=normalized_grant,
        )
        if rejection is not None:
            return None
        reserved = cls._edit_batch_ledger_time(ledger_row.get("reserved_at"))
        if reserved is None or not granted <= reserved <= stopped:
            return None
        dispatch_fields = (
            "dispatch_started_at",
            "dispatched_at",
            "unknown_at",
            "browser_session_id",
            "page_url",
            "page_kind",
        )
        if any(ledger_row.get(key) is not None for key in dispatch_fields):
            return None
        ledger_status = str(ledger_row.get("status") or "")
        if ledger_status == "RESERVED":
            if ledger_row.get("outcome_json") is not None:
                return None
            cancellation = {
                "classification": "CANCELLED_BEFORE_DISPATCH",
                "reason_code": reason_code,
                "cancelled_at": stopped_at,
                "external_dispatch_started": False,
            }
            cursor = conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET status='CANCELLED_BEFORE_DISPATCH',
                       outcome_json=?, updated_at=?
                 WHERE id=?
                   AND mutation_scope_id=?
                   AND mutation_action='save_only_click'
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
                    dumps(cancellation),
                    stopped_at,
                    ledger_row["id"],
                    normalized_grant["mutation_scope_id"],
                ),
            )
            if cursor.rowcount != 1:
                return None
        elif ledger_status == "CANCELLED_BEFORE_DISPATCH":
            cancellation = loads(ledger_row.get("outcome_json"), None)
            if (
                not isinstance(cancellation, dict)
                or cancellation.get("classification") != "CANCELLED_BEFORE_DISPATCH"
                or cancellation.get("external_dispatch_started") is not False
            ):
                return None
        else:
            return None
        return {
            "schema_version": "dxm_edit_batch_stop_evidence.v1",
            "classification": "STOPPED_BEFORE_SAVE_NO_WRITE",
            "reason_code": reason_code,
            "detail": detail,
            "stopped_at": stopped_at,
            "retry_allowed": False,
            "grant_issued": True,
            "grant_consumed": False,
            "ledger_status": "CANCELLED_BEFORE_DISPATCH",
            "zero_dispatch_proven": True,
        }

    @staticmethod
    def _edit_batch_ledger_row(conn: Any, mutation_scope_id: str) -> dict[str, Any] | None:
        return conn.execute(
            """
            SELECT *
              FROM mutation_dispatch_ledger
             WHERE mutation_scope_id=? AND mutation_action='save_only_click'
             LIMIT 1
            """,
            (mutation_scope_id,),
        ).fetchone()

    @staticmethod
    def _edit_batch_ledger_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _edit_batch_ledger_binding_rejection(
        cls,
        row: dict[str, Any] | None,
        *,
        batch_id: int,
        item_id: int,
        item_row: dict[str, Any],
        stored_grant: dict[str, Any],
    ) -> str | None:
        if not isinstance(row, dict):
            return "MUTATION_LEDGER_ENTRY_MISSING"
        expected = {
            "mutation_scope_id": stored_grant.get("mutation_scope_id"),
            "mutation_action": "save_only_click",
            "command_state": "SAVE_ONLY",
            "command_action": "save_only",
            "task_id": str(batch_id),
            "job_id": str(item_id),
            "authorization_lease_id": stored_grant.get("grant_lease_id"),
            "stage_task_facts_fingerprint": canonical_sha256(
                {
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "scope_digest": stored_grant.get("scope_digest"),
                    "template_digest": stored_grant.get("template_digest"),
                    "policy_digest": stored_grant.get("policy_digest"),
                    "target_identity_sha256": stored_grant.get(
                        "target_identity_sha256"
                    ),
                    "grant_fingerprint": stored_grant.get("fingerprint"),
                }
            ),
            "authorization_fingerprint": stored_grant.get("fingerprint"),
            "runtime_id": (
                stored_grant.get("runtime_identity", {}).get("browser_runtime_id")
                if isinstance(stored_grant.get("runtime_identity"), dict)
                else None
            ),
        }
        if any(row.get(key) != value for key, value in expected.items()):
            return "MUTATION_LEDGER_BINDING_DRIFT"
        item_snapshot = loads(item_row.get("item_snapshot_json"), None)
        store_identity = stored_grant.get("store_identity")
        if not isinstance(item_snapshot, dict) or not isinstance(store_identity, dict):
            return "MUTATION_LEDGER_TARGET_BINDING_UNPROVEN"
        target_identity = item_snapshot.get("target_identity")
        if not isinstance(target_identity, dict):
            return "MUTATION_LEDGER_TARGET_BINDING_UNPROVEN"
        try:
            expected_target_hash = mutation_target_hash(
                "save_only",
                {
                    "store_name": store_identity.get("store_name"),
                    "target_source_urls": list(item_snapshot.get("source_urls") or []),
                    "target_identity": target_identity,
                    "target_identity_sha256": stored_grant.get(
                        "target_identity_sha256"
                    ),
                },
            )
        except Exception:
            return "MUTATION_LEDGER_TARGET_BINDING_UNPROVEN"
        if row.get("target_hash") != expected_target_hash:
            return "MUTATION_LEDGER_TARGET_BINDING_DRIFT"
        command_id = row.get("command_id")
        if (
            not isinstance(command_id, str)
            or len(command_id) != 32
            or any(char not in "0123456789abcdef" for char in command_id)
        ):
            return "MUTATION_LEDGER_COMMAND_BINDING_UNPROVEN"
        item_binding = {
            "grant_lease_id": stored_grant.get("grant_lease_id"),
            "grant_fingerprint": stored_grant.get("fingerprint"),
            "grant_nonce_hash": stored_grant.get("nonce_hash"),
            "mutation_scope_id": stored_grant.get("mutation_scope_id"),
            "granted_at": stored_grant.get("issued_at"),
            "grant_expires_at": stored_grant.get("expires_at"),
        }
        if any(item_row.get(key) != value for key, value in item_binding.items()):
            return "ITEM_GRANT_PERSISTED_BINDING_DRIFT"
        return None

    @classmethod
    def _edit_batch_reserved_ledger_rejection(
        cls,
        conn: Any,
        *,
        batch_id: int,
        item_id: int,
        item_row: dict[str, Any],
        stored_grant: dict[str, Any],
        consumed_at: str,
    ) -> str | None:
        row = cls._edit_batch_ledger_row(
            conn, str(stored_grant.get("mutation_scope_id") or "")
        )
        rejection = cls._edit_batch_ledger_binding_rejection(
            row,
            batch_id=batch_id,
            item_id=item_id,
            item_row=item_row,
            stored_grant=stored_grant,
        )
        if rejection is not None:
            return rejection
        if row.get("status") != "RESERVED":
            return "MUTATION_LEDGER_NOT_RESERVED"
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
            return "MUTATION_RESERVED_STATE_UNCERTAIN"
        granted = cls._edit_batch_ledger_time(item_row.get("granted_at"))
        reserved = cls._edit_batch_ledger_time(row.get("reserved_at"))
        consumed = cls._edit_batch_ledger_time(consumed_at)
        if granted is None or reserved is None or consumed is None:
            return "MUTATION_LEDGER_ORDER_UNPROVEN"
        if not granted <= reserved <= consumed:
            return "MUTATION_LEDGER_ORDER_INVALID"
        return None

    @classmethod
    def _edit_batch_dispatched_ledger_rejection(
        cls,
        conn: Any,
        *,
        batch_id: int,
        item_id: int,
        item_row: dict[str, Any],
        stored_grant: dict[str, Any] | None,
        outcome: dict[str, Any],
    ) -> str | None:
        if not isinstance(stored_grant, dict):
            return "ITEM_GRANT_MISSING"
        row = cls._edit_batch_ledger_row(
            conn, str(stored_grant.get("mutation_scope_id") or "")
        )
        rejection = cls._edit_batch_ledger_binding_rejection(
            row,
            batch_id=batch_id,
            item_id=item_id,
            item_row=item_row,
            stored_grant=stored_grant,
        )
        if rejection is not None:
            return rejection
        if (
            row.get("status") != "DISPATCHED"
            or row.get("unknown_at") is not None
            or not row.get("outcome_json")
            or row.get("browser_session_id") != stored_grant.get("browser_session_id")
            or outcome.get("ledger_status") != "DISPATCHED"
            or outcome.get("mutation_scope_id") != stored_grant.get("mutation_scope_id")
        ):
            return "MUTATION_LEDGER_DISPATCH_UNPROVEN"
        ordered_times = [
            cls._edit_batch_ledger_time(item_row.get("granted_at")),
            cls._edit_batch_ledger_time(row.get("reserved_at")),
            cls._edit_batch_ledger_time(item_row.get("grant_consumed_at")),
            cls._edit_batch_ledger_time(row.get("dispatch_started_at")),
            cls._edit_batch_ledger_time(row.get("dispatched_at")),
        ]
        if any(value is None for value in ordered_times):
            return "MUTATION_LEDGER_ORDER_UNPROVEN"
        if any(
            earlier > later
            for earlier, later in zip(ordered_times, ordered_times[1:])
        ):
            return "MUTATION_LEDGER_ORDER_INVALID"
        return None

    @staticmethod
    def _edit_batch_item_rows(conn: Any, batch_id: int) -> list[dict[str, Any]]:
        return conn.execute(
            "SELECT * FROM edit_batch_items WHERE batch_id=? ORDER BY ordinal ASC",
            (batch_id,),
        ).fetchall()

    @staticmethod
    def _edit_batch_reason_code(value: Any) -> str:
        if not isinstance(value, str):
            raise EditBatchExecutionPersistenceError(
                "STOP_REASON_INVALID", "stop reason code must be text"
            )
        reason = value.strip().upper()
        if (
            not reason
            or len(reason) > 120
            or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in reason)
        ):
            raise EditBatchExecutionPersistenceError(
                "STOP_REASON_INVALID", "stop reason code must be canonical upper snake case"
            )
        return reason

    @staticmethod
    def _edit_batch_timestamp(value: str | None) -> str:
        if value is None:
            return now_iso()
        if not isinstance(value, str) or value != value.strip():
            raise EditBatchExecutionPersistenceError(
                "EXECUTION_TIMESTAMP_INVALID", "execution timestamp must be canonical ISO text"
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EditBatchExecutionPersistenceError(
                "EXECUTION_TIMESTAMP_INVALID", "execution timestamp is invalid"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise EditBatchExecutionPersistenceError(
                "EXECUTION_TIMESTAMP_INVALID", "execution timestamp must be timezone-aware"
            )
        return parsed.astimezone(timezone.utc).isoformat()

    def list_edit_batches(self):
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT b.*,
                       (SELECT COUNT(*) FROM edit_batch_items i WHERE i.batch_id=b.id) AS item_count
                  FROM edit_batches b
                 ORDER BY b.created_at DESC, b.id DESC
                """
            ).fetchall()
            summaries = []
            for row in rows:
                item_rows = conn.execute(
                    "SELECT status, ordinal FROM edit_batch_items WHERE batch_id=? ORDER BY ordinal ASC",
                    (row["id"],),
                ).fetchall()
                scope_snapshot = loads(row['scope_snapshot_json'], {})
                template_snapshot = loads(row['template_snapshot_json'], {})
                template_payload = template_snapshot.get('payload') if isinstance(template_snapshot.get('payload'), dict) else {}
                summaries.append({
                    'id': int(row['id']),
                    'schema_version': row['schema_version'],
                    'status': row['status'],
                    'scope_snapshot_id': int(row['scope_snapshot_id']),
                    'template_id': int(row['template_id']),
                    'item_count': int(row['item_count']),
                    'store_identity': self._public_store_identity(
                        scope_snapshot.get('store_identity')
                    ),
                    'template': {
                        'name': template_snapshot.get('template_name'),
                        'version': template_payload.get('version'),
                    },
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                    'execution': build_public_execution(row),
                    'progress': build_public_progress(item_rows),
                })
                approval = self._decode_edit_batch_approval_summary(row)
                if approval is not None:
                    summaries[-1]['approval'] = approval
            return summaries

    def _decode_edit_batch(
        self,
        row: dict[str, Any],
        items: list[dict[str, Any]],
        *,
        include_execution: bool,
    ):
        batch = {
            'id': int(row['id']),
            'schema_version': row['schema_version'],
            'status': row['status'],
            'scope_snapshot_id': int(row['scope_snapshot_id']),
            'scope_snapshot_digest': row['scope_snapshot_digest'],
            'scope_snapshot': loads(row['scope_snapshot_json'], {}),
            'template_id': int(row['template_id']),
            'template_snapshot_digest': row['template_snapshot_digest'],
            'template_snapshot': loads(row['template_snapshot_json'], {}),
            'policy_digest': row['policy_digest'],
            'policy': loads(row['policy_json'], {}),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'items': [],
        }
        for item in items:
            public_item = {
                    'id': int(item['id']),
                    'batch_id': int(item['batch_id']),
                    'ordinal': int(item['ordinal']),
                    'status': item['status'],
                    'target_identity_sha256': item['target_identity_sha256'],
                    'item_snapshot': loads(item['item_snapshot_json'], {}),
                    'created_at': item['created_at'],
                    'updated_at': item['updated_at'],
            }
            outcome = build_public_item_outcome(item)
            if outcome is not None:
                public_item['outcome'] = outcome
            batch['items'].append(public_item)
        approval = self._decode_edit_batch_approval_summary(row)
        if approval is not None:
            batch['approval'] = approval
        if include_execution:
            batch['execution'] = build_public_execution(row)
            batch['progress'] = build_public_progress(items)
        return batch

    @classmethod
    def _public_edit_batch(cls, batch: dict[str, Any]) -> dict[str, Any]:
        """Project frozen execution facts into the small operator-facing contract."""

        scope_snapshot = (
            batch.get('scope_snapshot')
            if isinstance(batch.get('scope_snapshot'), dict)
            else {}
        )
        template_snapshot = (
            batch.get('template_snapshot')
            if isinstance(batch.get('template_snapshot'), dict)
            else {}
        )
        template_payload = (
            template_snapshot.get('payload')
            if isinstance(template_snapshot.get('payload'), dict)
            else {}
        )
        policy = batch.get('policy') if isinstance(batch.get('policy'), dict) else {}
        public_batch = {
            'id': batch.get('id'),
            'schema_version': batch.get('schema_version'),
            'status': batch.get('status'),
            'scope_snapshot_id': batch.get('scope_snapshot_id'),
            'scope_snapshot': cls._public_scope_snapshot(scope_snapshot),
            'template_id': batch.get('template_id'),
            'template_snapshot': {
                'template_name': template_snapshot.get('template_name'),
                'payload': {'version': template_payload.get('version')},
            },
            'policy': {
                key: policy.get(key)
                for key in (
                    'approval_mode',
                    'dispatch_mode',
                    'global_concurrency',
                    'publish_allowed',
                    'unknown_result_policy',
                    'identity_drift_policy',
                    'session_loss_policy',
                    'pre_save_no_effect_failure_policy',
                )
                if key in policy
            },
            'created_at': batch.get('created_at'),
            'updated_at': batch.get('updated_at'),
            'items': [
                cls._public_edit_batch_item(item)
                for item in batch.get('items') or []
                if isinstance(item, dict)
            ],
        }
        for key in ('approval', 'execution', 'progress'):
            if key in batch:
                public_batch[key] = batch[key]
        return public_batch

    @classmethod
    def _public_scope_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        page_state = snapshot.get('page_state') if isinstance(snapshot.get('page_state'), dict) else {}
        return {
            'observed_at': snapshot.get('observed_at'),
            'store_identity': cls._public_store_identity(snapshot.get('store_identity')),
            'page_state': {
                key: page_state.get(key)
                for key in (
                    'current_page',
                    'total_items',
                    'captured_count',
                    'max_items',
                    'truncated',
                )
                if key in page_state
            },
        }

    @staticmethod
    def _public_store_identity(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {'store_name': value.get('store_name')}

    @staticmethod
    def _public_edit_batch_item(item: dict[str, Any]) -> dict[str, Any]:
        snapshot = (
            item.get('item_snapshot')
            if isinstance(item.get('item_snapshot'), dict)
            else {}
        )
        public_item = {
            'id': item.get('id'),
            'batch_id': item.get('batch_id'),
            'ordinal': item.get('ordinal'),
            'status': item.get('status'),
            'item_snapshot': {
                'title': snapshot.get('title'),
                'dxm_product_id': snapshot.get('dxm_product_id'),
                'source_url': snapshot.get('source_url'),
                'source_urls': list(snapshot.get('source_urls') or []),
            },
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
        }
        if 'outcome' in item:
            public_item['outcome'] = item['outcome']
        return public_item

    @staticmethod
    def _decode_edit_batch_approval_summary(row: dict[str, Any]) -> dict[str, Any] | None:
        if not row.get('approval_context_json'):
            return None
        context = loads(row['approval_context_json'], {})
        if not isinstance(context, dict):
            return None
        return {
            'approved': True,
            'approved_by': context.get('approved_by'),
            'approved_at': context.get('issued_at'),
        }

    def list_products(self, *, include_fixtures: bool = False):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = loads(row.pop('payload_json'), {})
                self._attach_product_lifecycle(row)
            return rows

    def list_claimed_draft_products(self):
        products = self.list_products()
        claimed_statuses = {'claimed_to_draft', 'ready_for_edit'}
        eligible = []
        for product in products:
            payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
            source = str(payload.get('source') or product.get('source') or '').strip()
            source_url = self._first_source_url(payload)
            if product.get('status') not in claimed_statuses:
                continue
            if source != 'dxm_data_acquisition':
                continue
            if payload.get('draft_box_verified') is not True:
                continue
            if not source_url:
                continue
            if not self.product_has_completed_claim_provenance(product):
                continue
            eligible.append(product)
        return eligible

    def get_product(self, product_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            if not row:
                return None
            row['payload'] = loads(row.pop('payload_json'), {})
            self._attach_product_lifecycle(row)
            return row

    def create_product(self, data: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            return self._insert_product(conn, data, now)

    def _insert_product(self, conn: Any, data: dict[str, Any], now: str) -> dict[str, Any]:
        status = str(data.get('status') or 'draft')
        cur = conn.execute(
            "INSERT INTO products (title, source, status, category_name, price, currency, sku_count, image_count, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['title'], data.get('source', 'manual'), status, data['category_name'], data['price'], data['currency'], data['sku_count'], data['image_count'], dumps(data['payload']), now, now),
        )
        row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
        row['payload'] = loads(row.pop('payload_json'), {})
        self._attach_product_lifecycle(row)
        return row

    def create_acquisition_claim_request(self, data: dict[str, Any]):
        store_name = str(data.get('store_name') or self._store_name_for_id(data['store_id']) or '').strip()
        payload = {
            'stage': 'pending_acquisition_claim',
            'status': 'pending',
            'store_id': data['store_id'],
            'store_name': store_name or None,
            'source_url': data.get('source_url'),
            'keyword': data.get('keyword'),
            'category_name': data.get('category_name'),
            'claim_mark': data['claim_mark'],
            'template_id': data.get('template_id'),
        }
        task = self.create_task({
            'name': f"待认领商品 - {payload.get('keyword') or payload.get('category_name') or '待选择商品'}",
            'store_id': payload['store_id'],
            'mode': 'claim_only',
            'publish_scene': 'CONTROLLED_CLAIM_TO_DRAFT_ONLY',
            'claim_mark': payload['claim_mark'],
            'product_ids': [],
            'payload': payload,
        })
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "UPDATE tasks SET total_jobs=1, updated_at=? WHERE id=?",
                (now, task['id']),
            )
            conn.execute(
                "INSERT INTO jobs (task_id, product_id, status, created_at, updated_at) VALUES (?, NULL, 'pending', ?, ?)",
                (task['id'], now, now),
            )
        task = self.get_task_private(task['id'])
        task['payload'] = self._public_task_payload(task.get('payload') or {})
        return task

    def _store_name_for_id(self, store_id: Any) -> str | None:
        with connection() as conn:
            row = conn.execute("SELECT name FROM stores WHERE id=?", (store_id,)).fetchone()
            return str(row['name']) if row and row.get('name') else None

    def bulk_import_products(self, rows: list[dict[str, Any]]):
        created = []
        for row in rows:
            created.append(self.create_product({
                'title': row.get('title', '未命名商品'),
                'source': 'import',
                'category_name': row.get('category_name', '未分类'),
                'price': float(row.get('price', 0) or 0),
                'currency': row.get('currency', 'USD'),
                'sku_count': int(row.get('sku_count', 1) or 1),
                'image_count': int(row.get('image_count', 0) or 0),
                'payload': row,
            }))
        return created

    def list_tasks(self):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = self._public_task_payload(loads(row.pop('payload_json'), {}))
            return rows

    def get_task(self, task_id: int, *, include_private: bool = False):
        with connection() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            payload = loads(task.pop('payload_json'), {})
            task['payload'] = payload if include_private else self._public_task_payload(payload)
            task['jobs'] = conn.execute("SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
            return task

    def get_task_private(self, task_id: int):
        return self.get_task(task_id, include_private=True)

    def create_task(self, data: dict[str, Any]):
        now = now_iso()
        payload = dict(data.get('payload') or {})
        payload.pop('manual_approval', None)
        payload.update({
            'product_ids': data.get('product_ids', []),
            'claim_mark': data.get('claim_mark', 'AI认领'),
            'execution_mode': data['mode'],
            'publish_allowed': False,
            'max_count': len(data.get('product_ids', [])),
        })
        with connection() as conn:
            if data.get('mode') == 'single_save':
                self._attach_single_save_claim_proof(conn, payload, data.get('product_ids', []))
            cur = conn.execute(
                "INSERT INTO tasks (name, store_id, status, mode, publish_scene, total_jobs, payload_json, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (data['name'], data.get('store_id'), data['mode'], data['publish_scene'], len(data.get('product_ids', [])), dumps(payload), now, now),
            )
            task_id = cur.lastrowid
            for product_id in data.get('product_ids', []):
                conn.execute(
                    "INSERT INTO jobs (task_id, product_id, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
                    (task_id, product_id, now, now),
                )
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            task['payload'] = loads(task.pop('payload_json'), {})
            return task

    def _attach_single_save_claim_proof(self, conn: Any, payload: dict[str, Any], product_ids: list[int]) -> None:
        if len(product_ids) != 1:
            return
        product = conn.execute("SELECT * FROM products WHERE id=?", (int(product_ids[0]),)).fetchone()
        if not product:
            return
        product_payload = loads(product.get('payload_json'), {})
        product['payload'] = product_payload
        if not self.product_has_completed_claim_provenance(product):
            raise TwoStageContractError(
                'CLAIM_PROOF_INVALID',
                'single-save task requires a fully verified completed claim provenance',
            )
        source = str(product_payload.get('source') or product.get('source') or '').strip()
        source_url = self._first_source_url(product_payload)
        payload.update({
            'stage': 'draft_edit_save',
            'claimed_product_id': product.get('id'),
            'claimed_product_title': product.get('title'),
            'claimed_product_status': product.get('status'),
            'claimed_product_source': source or None,
            'claimed_product_source_url': source_url,
            'claimed_product_category_name': product.get('category_name'),
            'claim_task_id': product_payload.get('claim_task_id'),
            'claim_job_id': product_payload.get('claim_job_id'),
            'store_id': product_payload.get('store_id'),
            'claimed_product_source_identity': product_payload.get('source_identity'),
            'claimed_product_source_urls': list(product_payload.get('source_urls') or []),
            'stage_a_task_facts': product_payload.get('stage_a_task_facts'),
            'stage_a_task_facts_fingerprint': product_payload.get('stage_a_task_facts_fingerprint'),
            'claim_target_identity': product_payload.get('claim_target_identity'),
            'claim_target_fingerprint': product_payload.get('claim_target_fingerprint'),
            'draft_box_proof': product_payload.get('draft_box_proof'),
            'draft_box_proof_fingerprint': product_payload.get('draft_box_proof_fingerprint'),
            'draft_box_verified': product_payload.get('draft_box_verified') is True,
        })
        if source_url:
            payload['source_url'] = source_url

    def _first_source_url(self, payload: dict[str, Any]) -> str | None:
        return _first_source_url_from_payload(payload)

    def _attach_product_lifecycle(self, product: dict[str, Any]) -> None:
        payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
        source = str(payload.get('source') or product.get('source') or '').strip()
        source_url = self._first_source_url(payload)
        status = str(product.get('status') or '').strip().lower()
        draft_box_verified = payload.get('draft_box_verified') is True
        if status in {'saved', 'save_completed', 'completed'}:
            lifecycle_state = 'saved'
            lifecycle_label = '已保存结果'
        elif status == 'ready_for_edit' or (
            status == 'claimed_to_draft'
            and source == 'dxm_data_acquisition'
            and draft_box_verified
            and bool(source_url)
        ):
            lifecycle_state = 'editable'
            lifecycle_label = '可编辑商品'
        elif status in {'claimed_to_draft', 'claimed'} or payload.get('claim_task_id'):
            lifecycle_state = 'claimed'
            lifecycle_label = '已认领商品'
        else:
            lifecycle_state = 'awaiting_claim'
            lifecycle_label = '待认领商品'

        if source == 'dxm_data_acquisition':
            source_status_label = '店小秘已有待认领商品'
        elif source in {'manual', 'manual_import'}:
            source_status_label = '手工/导入商品'
        else:
            source_status_label = '等待来源确认'

        if draft_box_verified:
            draft_box_verification_label = '已确认进入商品箱'
        elif lifecycle_state in {'claimed', 'editable'}:
            draft_box_verification_label = '等待确认商品箱'
        else:
            draft_box_verification_label = '未进入商品箱'

        product.update({
            'lifecycle_state': lifecycle_state,
            'lifecycle_label': lifecycle_label,
            'source_status_label': source_status_label,
            'draft_box_verification_label': draft_box_verification_label,
            'source_url': source_url,
            'claim_task_id': payload.get('claim_task_id'),
            'store_id': payload.get('store_id'),
            'store_name': payload.get('store_name'),
            'claimed_at': payload.get('claimed_at') or payload.get('completed_at'),
            'draft_box_verified': draft_box_verified,
        })

    def product_has_completed_claim_provenance(self, product: dict[str, Any]) -> bool:
        payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
        claim_task_id = payload.get('claim_task_id') or product.get('claim_task_id')
        try:
            claim_task_id_int = _exact_positive_int(claim_task_id)
            product_id = _exact_positive_int(product.get('id'))
        except ValueError:
            return False
        task = self.get_task_private(claim_task_id_int)
        if not task:
            return False
        if task.get('mode') != 'claim_only':
            return False
        if task.get('status') != 'completed':
            return False
        task_payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        if task_payload.get('status') != 'completed':
            return False
        jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
        if len(jobs) != 1 or jobs[0].get('product_id') is not None:
            return False
        try:
            claimed_product_id = _exact_positive_int(task_payload.get('claimed_product_id'))
        except ValueError:
            return False
        if claimed_product_id != product_id or task_payload.get('draft_box_verified') is not True:
            return False
        if self._claim_product_proof_error(
            claim_task_id_int,
            product,
            task=task,
            job=jobs[0],
        ) is not None:
            return False
        expected_task_snapshot = {
            'claim_job_id': payload.get('claim_job_id'),
            'store_id': payload.get('store_id'),
            'stage_a_task_facts': payload.get('stage_a_task_facts'),
            'stage_a_task_facts_fingerprint': payload.get('stage_a_task_facts_fingerprint'),
            'claim_target_identity': payload.get('claim_target_identity'),
            'claim_target_fingerprint': payload.get('claim_target_fingerprint'),
            'claimed_product_source_identity': payload.get('source_identity'),
            'draft_box_proof': payload.get('draft_box_proof'),
            'draft_box_proof_fingerprint': payload.get('draft_box_proof_fingerprint'),
        }
        return all(task_payload.get(key) == value for key, value in expected_task_snapshot.items())

    def single_save_claim_snapshot_error(
        self,
        task: dict[str, Any],
        product: dict[str, Any],
    ) -> str | None:
        if task.get('mode') != 'single_save':
            return 'task is not single_save'
        if not self.product_has_completed_claim_provenance(product):
            return 'current product claim provenance is invalid'
        task_payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        product_payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
        jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
        try:
            _exact_positive_int(task.get('id'))
            task_store_id = _exact_positive_int(task.get('store_id'))
            product_id = _exact_positive_int(product.get('id'))
            product_store_id = _exact_positive_int(product_payload.get('store_id'))
            snapshot_product_id = _exact_positive_int(task_payload.get('claimed_product_id'))
        except ValueError:
            return 'single-save task or product bindings are invalid'
        if len(jobs) != 1:
            return 'single-save task must contain exactly one job'
        try:
            job_product_id = _exact_positive_int(jobs[0].get('product_id'))
        except ValueError:
            return 'single-save job product binding is invalid'
        if not (
            task_store_id == product_store_id
            and snapshot_product_id == product_id == job_product_id
            and task_payload.get('product_ids') == [product_id]
        ):
            return 'single-save task store or product binding has drifted'
        expected_snapshot = {
            'claimed_product_id': product_id,
            'claimed_product_title': product.get('title'),
            'claimed_product_status': product.get('status'),
            'claimed_product_source': product_payload.get('source') or product.get('source'),
            'claimed_product_source_url': _first_source_url_from_payload(product_payload),
            'claimed_product_category_name': product.get('category_name'),
            'claim_task_id': product_payload.get('claim_task_id'),
            'claim_job_id': product_payload.get('claim_job_id'),
            'store_id': product_payload.get('store_id'),
            'claimed_product_source_identity': product_payload.get('source_identity'),
            'claimed_product_source_urls': list(product_payload.get('source_urls') or []),
            'stage_a_task_facts': product_payload.get('stage_a_task_facts'),
            'stage_a_task_facts_fingerprint': product_payload.get('stage_a_task_facts_fingerprint'),
            'claim_target_identity': product_payload.get('claim_target_identity'),
            'claim_target_fingerprint': product_payload.get('claim_target_fingerprint'),
            'draft_box_proof': product_payload.get('draft_box_proof'),
            'draft_box_proof_fingerprint': product_payload.get('draft_box_proof_fingerprint'),
            'draft_box_verified': True,
        }
        for key, expected in expected_snapshot.items():
            if task_payload.get(key) != expected:
                return f'single-save task snapshot field {key} has drifted'
        return None

    def set_task_manual_approval(
        self,
        task_id: int,
        *,
        approved: bool,
        token: str,
        approved_by: str = "system",
        confirmation: str | None = None,
        authorization_context: dict[str, Any] | None = None,
        lease_id: str | None = None,
        issued_at: str | None = None,
        expires_at: str | None = None,
    ) -> TaskManualApprovalResult:
        now = issued_at or now_iso()
        try:
            current_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
        except (AttributeError, TypeError, ValueError):
            return TaskManualApprovalResult(False, "TASK_APPROVAL_TIME_INVALID", None)
        if not isinstance(token, str) or not token or not isinstance(approved_by, str) or not approved_by.strip():
            return TaskManualApprovalResult(False, "TASK_APPROVAL_INPUT_INVALID", None)
        if authorization_context is not None:
            if (
                not isinstance(lease_id, str)
                or not lease_id.strip()
                or not isinstance(confirmation, str)
                or not confirmation.strip()
                or not isinstance(expires_at, str)
            ):
                return TaskManualApprovalResult(False, "TASK_APPROVAL_INPUT_INVALID", None)
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except ValueError:
                return TaskManualApprovalResult(False, "TASK_APPROVAL_TIME_INVALID", None)
            lease_seconds = (expiry - current_time).total_seconds()
            if lease_seconds <= 0 or lease_seconds > 5 * 60:
                return TaskManualApprovalResult(False, "TASK_APPROVAL_TIME_INVALID", None)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not task:
                return TaskManualApprovalResult(False, "TASK_NOT_FOUND", None)
            if task["status"] != "draft":
                return TaskManualApprovalResult(False, "TASK_NOT_DRAFT", None)
            original_payload_json = task["payload_json"]
            payload = loads(original_payload_json, {})
            existing_approval = (
                payload.get("manual_approval")
                if isinstance(payload.get("manual_approval"), dict)
                else None
            )
            if (
                isinstance(existing_approval, dict)
                and existing_approval.get("approved") is True
                and existing_approval.get("source") == "server"
                and existing_approval.get("consumed") is not True
            ):
                existing_expiry_text = existing_approval.get("expires_at")
                try:
                    existing_expiry = datetime.fromisoformat(
                        str(existing_expiry_text).replace("Z", "+00:00")
                    )
                    if existing_expiry.tzinfo is None:
                        existing_expiry = existing_expiry.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    existing_expiry = None
                if existing_expiry is None or current_time < existing_expiry:
                    return TaskManualApprovalResult(
                        False,
                        "TASK_APPROVAL_ALREADY_ISSUED",
                        None,
                    )
            payload['manual_approval'] = {
                'approved': bool(approved),
                'token_hash': hashlib.sha256(token.encode("utf-8")).hexdigest(),
                'approved_by': approved_by,
                'approved_at': now,
                'source': 'server',
                **({
                    'lease_id': lease_id,
                    'confirmation': confirmation,
                    'stage_task_facts': dict((authorization_context or {}).get('stage_task_facts') or {}),
                    'authorization_context': dict(authorization_context or {}),
                    'issued_at': now,
                    'expires_at': expires_at,
                    'consumed': False,
                    'consumed_at': None,
                } if authorization_context is not None else {}),
            }
            cursor = conn.execute(
                """
                UPDATE tasks
                   SET payload_json=?, updated_at=?
                 WHERE id=? AND status='draft' AND payload_json=?
                """,
                (dumps(payload), now, task_id, original_payload_json),
            )
            if cursor.rowcount != 1:
                return TaskManualApprovalResult(False, "TASK_APPROVAL_CAS_CONFLICT", None)
        return TaskManualApprovalResult(True, "OK", self.get_task(task_id))

    def update_task_template_override(self, task_id: int, section: str, values: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            task = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            payload = loads(task['payload_json'], {})
            if section == 'task_basic':
                allowed = {'store_name', 'category_name', 'claim_mark', 'execution_mode'}
                for key, value in dict(values or {}).items():
                    if key not in allowed:
                        continue
                    if value is None or (isinstance(value, str) and value.strip() == ''):
                        payload.pop(key, None)
                    else:
                        payload[key] = value
                conn.execute(
                    "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=?",
                    (dumps(payload), now, task_id),
                )
                return self.get_task(task_id)
            overrides = payload.get('template_overrides')
            if not isinstance(overrides, dict):
                overrides = {}
            cleaned_values = self._prune_empty_config_values(dict(values or {}))
            if cleaned_values:
                overrides[section] = cleaned_values
            else:
                overrides.pop(section, None)
            if overrides:
                payload['template_overrides'] = overrides
            else:
                payload.pop('template_overrides', None)
            conn.execute(
                "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=?",
                (dumps(payload), now, task_id),
            )
        return self.get_task(task_id)

    def _prune_empty_config_values(self, value: Any):
        if value is None:
            return None
        if isinstance(value, str):
            return value if value.strip() != '' else None
        if isinstance(value, dict):
            cleaned = {}
            for key, child in value.items():
                cleaned_child = self._prune_empty_config_values(child)
                if cleaned_child is not None:
                    cleaned[key] = cleaned_child
            return cleaned or None
        if isinstance(value, list):
            cleaned_items = [
                cleaned_child
                for item in value
                if (cleaned_child := self._prune_empty_config_values(item)) is not None
            ]
            return cleaned_items or None
        return value

    def update_task_status(self, task_id: int, status: str, completed_jobs: int | None = None, failed_jobs: int | None = None):
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if status == 'running':
                if self._active_edit_batch_exists(conn):
                    raise RuntimeError('AUTH_EDIT_BATCH_ACTIVE')
                if self._other_running_task_exists(conn, task_id):
                    raise RuntimeError('AUTH_ANOTHER_TASK_ACTIVE')
            existing = conn.execute(
                "SELECT status, completed_jobs, failed_jobs FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not existing:
                return False
            if (
                str(existing.get("status") or "")
                in {"failed", "cancelled", "needs_manual_review"}
                and status in {"running", "completed", "partial_success"}
                and status != existing.get("status")
            ):
                return False
            conn.execute(
                "UPDATE tasks SET status=?, completed_jobs=?, failed_jobs=?, updated_at=? WHERE id=?",
                (status, completed_jobs if completed_jobs is not None else existing['completed_jobs'], failed_jobs if failed_jobs is not None else existing['failed_jobs'], now, task_id),
            )
            return True

    def try_update_task_status(
        self,
        task_id: int,
        status: str,
        *,
        expected_statuses: tuple[str, ...] | list[str] | set[str],
        completed_jobs: int | None = None,
        failed_jobs: int | None = None,
    ) -> bool:
        expected = tuple(dict.fromkeys(expected_statuses))
        if not expected:
            return False
        now = now_iso()
        placeholders = ", ".join("?" for _ in expected)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if status == 'running':
                if self._active_edit_batch_exists(conn):
                    return False
                if self._other_running_task_exists(conn, task_id):
                    return False
            if status in {"running", "completed", "partial_success"}:
                current = conn.execute(
                    "SELECT status FROM tasks WHERE id=?",
                    (task_id,),
                ).fetchone()
                if (
                    current
                    and str(current.get("status") or "")
                    in {"failed", "cancelled", "needs_manual_review"}
                    and status != current.get("status")
                ):
                    return False
            updated = conn.execute(
                f"""
                UPDATE tasks
                   SET status=?,
                       completed_jobs=COALESCE(?, completed_jobs),
                       failed_jobs=COALESCE(?, failed_jobs),
                       updated_at=?
                 WHERE id=? AND status IN ({placeholders})
                """,
                (status, completed_jobs, failed_jobs, now, task_id, *expected),
            )
            return updated.rowcount == 1

    def mark_acquisition_claim_completed(self, task_id: int, claimed_product: dict[str, Any]) -> ClaimCompletionResult:
        now = now_iso()
        product_id = claimed_product.get('id')
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            authoritative_product = None
            if product_id is not None:
                product_row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
                if product_row:
                    product_row['payload'] = loads(product_row.pop('payload_json'), {})
                    self._attach_product_lifecycle(product_row)
                    authoritative_product = product_row
            if authoritative_product is None:
                decision = {
                    'idempotent': False,
                    'conflict_code': 'CLAIM_PRODUCT_NOT_FOUND',
                    'reason': 'claimed product does not exist',
                }
            else:
                decision = self._claim_completion_decision(
                    conn,
                    task_id,
                    authoritative_product,
                    allow_draft=True,
                )
                if decision['conflict_code'] is None and not decision['idempotent']:
                    self._apply_claim_completion(
                        conn,
                        decision['task'],
                        decision['jobs'][0],
                        decision['payload'],
                        authoritative_product,
                        now,
                    )
        return ClaimCompletionResult(
            applied=decision['conflict_code'] is None and not decision['idempotent'],
            idempotent=bool(decision['idempotent']),
            conflict_code=decision['conflict_code'],
            reason=decision['reason'],
            task=self.get_task_private(task_id),
            product=self.get_product(int(product_id)) if product_id is not None else None,
        )

    def create_claimed_product_and_complete_acquisition(
        self,
        task_id: int,
        product_data: dict[str, Any],
        *,
        draft_box_observation: dict[str, Any] | None = None,
    ) -> ClaimCompletionResult:
        """Create the verified claimed product and complete its claim task atomically."""
        now = now_iso()
        product_id: int | None = None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            decision = self._claim_completion_decision(
                conn,
                task_id,
                product_data,
                validate_product_proof=False,
            )
            if decision['conflict_code'] is None and not decision['idempotent']:
                exact_product_data = dict(product_data)
                exact_product_payload = dict(product_data.get('payload') or {})
                exact_product_payload.pop('draft_box_proof', None)
                exact_product_data['payload'] = exact_product_payload
                product = self._insert_product(conn, exact_product_data, now)
                product_id = int(product['id'])
                job = decision['jobs'][0]
                stage_a_task_facts = self._build_stage_a_task_facts(decision['task'], job)
                proof = build_draft_box_proof(
                    stage_a_task_facts=stage_a_task_facts,
                    product_id=product_id,
                    proof_content=draft_box_observation or {},
                )
                proof_content = proof['proof_content']
                source_identity = proof_content.get('observed_source_identity')
                if source_identity is None:
                    exact_product_payload.pop('source_url', None)
                    exact_product_payload.pop('source_urls', None)
                else:
                    exact_product_payload['source_url'] = source_identity['primary_url']
                    exact_product_payload['source_urls'] = list(source_identity['urls'])
                exact_product_payload.update({
                    'claim_task_id': int(task_id),
                    'claim_job_id': int(job['id']),
                    'store_id': int(decision['task']['store_id']),
                    'source_identity': source_identity,
                    'stage_a_task_facts': stage_a_task_facts,
                    'stage_a_task_facts_fingerprint': stage_a_task_facts['fingerprint'],
                    'claim_target_identity': stage_a_task_facts['target_identity'],
                    'claim_target_fingerprint': stage_a_task_facts['target_identity']['fingerprint'],
                    'draft_box_verified': True,
                    'draft_box_proof': proof,
                    'draft_box_proof_fingerprint': proof['fingerprint'],
                })
                conn.execute(
                    "UPDATE products SET payload_json=?, updated_at=? WHERE id=?",
                    (dumps(exact_product_payload), now, product_id),
                )
                product['payload'] = exact_product_payload
                proof_error = self._claim_product_proof_error(
                    task_id,
                    product,
                    task=decision['task'],
                    job=job,
                )
                if proof_error:
                    raise TwoStageContractError('CLAIM_PROOF_INVALID', proof_error)
                self._apply_claim_completion(
                    conn,
                    decision['task'],
                    job,
                    decision['payload'],
                    product,
                    now,
                )
        return ClaimCompletionResult(
            applied=product_id is not None,
            idempotent=bool(decision['idempotent']),
            conflict_code=decision['conflict_code'],
            reason=decision['reason'],
            task=self.get_task_private(task_id),
            product=self.get_product(product_id) if product_id is not None else None,
        )

    def _build_stage_a_task_facts(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
    ) -> dict[str, Any]:
        payload = (
            task.get('payload')
            if isinstance(task.get('payload'), dict)
            else loads(task.get('payload_json'), {})
        )
        target_identity = canonical_claim_target_identity(
            payload.get('source_url'),
            payload.get('source_urls') or (),
            keyword=payload.get('keyword'),
            category_name=payload.get('category_name'),
        )
        return build_stage_a_task_facts(
            task_id=_exact_positive_int(task.get('id')),
            job_id=_exact_positive_int(job.get('id')),
            store_id=_exact_positive_int(task.get('store_id')),
            target_identity=target_identity,
        )

    def _claim_completion_decision(
        self,
        conn: Any,
        task_id: int,
        claimed_product: dict[str, Any],
        *,
        allow_draft: bool = False,
        validate_product_proof: bool = True,
    ) -> dict[str, Any]:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return {
                'task': None,
                'jobs': [],
                'payload': {},
                'idempotent': False,
                'conflict_code': 'CLAIM_TASK_NOT_FOUND',
                'reason': 'claim task does not exist',
            }
        jobs = conn.execute("SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
        payload = loads(task['payload_json'], {})
        claimed_payload = claimed_product.get('payload') if isinstance(claimed_product.get('payload'), dict) else {}
        has_failed_report = conn.execute(
            "SELECT 1 FROM reports WHERE task_id=? AND status='failed' LIMIT 1",
            (task_id,),
        ).fetchone() is not None
        has_open_exception = conn.execute(
            "SELECT 1 FROM exceptions WHERE task_id=? AND status='open' LIMIT 1",
            (task_id,),
        ).fetchone() is not None
        terminal_failure = (
            task.get('status') in {'failed', 'partial_success', 'cancelled', 'needs_manual_review'}
            or any(job.get('status') == 'failed' or job.get('error_code') for job in jobs)
            or has_failed_report
            or has_open_exception
        )
        completed_state = task.get('status') == 'completed' or payload.get('status') == 'completed'
        task_shape_valid = task.get('mode') == 'claim_only' and len(jobs) == 1 and jobs[0].get('product_id') is None
        proof_error = (
            self._claim_product_proof_error(
                task_id,
                claimed_product,
                task=task,
                job=jobs[0],
            )
            if validate_product_proof and task_shape_valid
            else None
        )
        claimed_proof = claimed_payload.get('draft_box_proof') if isinstance(claimed_payload.get('draft_box_proof'), dict) else {}
        same_completed_result = (
            claimed_product.get('id') is not None
            and task.get('status') == 'completed'
            and payload.get('status') == 'completed'
            and str(payload.get('claimed_product_id')) == str(claimed_product.get('id'))
            and payload.get('claimed_product_source_url') == _first_source_url_from_payload(claimed_payload)
            and payload.get('draft_box_verified') is True
            and len(jobs) == 1
            and jobs[0].get('status') in {'completed', 'succeeded'}
            and not jobs[0].get('error_code')
            and payload.get('claim_job_id') == claimed_payload.get('claim_job_id') == jobs[0].get('id')
            and payload.get('store_id') == claimed_payload.get('store_id') == task.get('store_id')
            and payload.get('stage_a_task_facts') == claimed_payload.get('stage_a_task_facts')
            and payload.get('stage_a_task_facts_fingerprint') == claimed_payload.get('stage_a_task_facts_fingerprint')
            and payload.get('claim_target_identity') == claimed_payload.get('claim_target_identity')
            and payload.get('claim_target_fingerprint') == claimed_payload.get('claim_target_fingerprint')
            and payload.get('claimed_product_source_identity') == claimed_payload.get('source_identity')
            and payload.get('draft_box_proof') == claimed_proof
            and payload.get('draft_box_proof_fingerprint') == claimed_proof.get('fingerprint')
        )
        conflict_code: str | None = None
        reason: str | None = None
        idempotent = False
        if terminal_failure:
            conflict_code = 'CLAIM_TERMINAL_STATE_CONFLICT'
            reason = 'failed claim facts are terminal and cannot be rewritten by a late success'
        elif completed_state:
            if proof_error:
                conflict_code = 'CLAIM_PROOF_INVALID'
                reason = proof_error
            elif same_completed_result:
                idempotent = True
            else:
                conflict_code = 'CLAIM_COMPLETION_RESULT_CONFLICT'
                reason = 'completed claim result does not match the requested product proof'
        elif not task_shape_valid:
            conflict_code = 'CLAIM_TASK_SHAPE_CONFLICT'
            reason = 'claim completion requires one product-less claim job'
        elif (
            task.get('status') not in ({'draft', 'running'} if allow_draft else {'running'})
            or jobs[0].get('status') not in ({'pending', 'running'} if allow_draft else {'running'})
        ):
            conflict_code = 'CLAIM_STATE_TRANSITION_CONFLICT'
            reason = 'claim task and job are not in a completable state'
        else:
            if proof_error:
                conflict_code = 'CLAIM_PROOF_INVALID'
                reason = proof_error
        return {
            'task': task,
            'jobs': jobs,
            'payload': payload,
            'idempotent': idempotent,
            'conflict_code': conflict_code,
            'reason': reason,
        }

    def _claim_product_proof_error(
        self,
        task_id: int,
        claimed_product: dict[str, Any],
        *,
        task: dict[str, Any],
        job: dict[str, Any],
    ) -> str | None:
        payload = claimed_product.get('payload') if isinstance(claimed_product.get('payload'), dict) else {}
        source = str(payload.get('source') or claimed_product.get('source') or '').strip()
        try:
            proof_task_id = _exact_positive_int(payload.get('claim_task_id'))
        except ValueError:
            proof_task_id = None
        if source != 'dxm_data_acquisition':
            return 'claimed product source is not dxm_data_acquisition'
        if proof_task_id != int(task_id):
            return 'claimed product proof belongs to a different claim task'
        if payload.get('draft_box_verified') is not True:
            return 'claimed product is missing verified draft-box proof'
        try:
            claim_job_id = _exact_positive_int(payload.get('claim_job_id'))
            proof_store_id = _exact_positive_int(payload.get('store_id'))
            product_id = _exact_positive_int(claimed_product.get('id'))
            expected_job_id = _exact_positive_int(job.get('id'))
            expected_store_id = _exact_positive_int(task.get('store_id'))
            stage_a_task_facts = self._build_stage_a_task_facts(task, job)
        except (TypeError, ValueError, TwoStageContractError):
            return 'claimed product proof bindings are invalid'
        if claim_job_id != expected_job_id:
            return 'claimed product proof belongs to a different claim job'
        if proof_store_id != expected_store_id:
            return 'claimed product proof belongs to a different store'
        proof = payload.get('draft_box_proof')
        verification = verify_draft_box_proof(
            proof,
            stage_a_task_facts=stage_a_task_facts,
            product_id=product_id,
        )
        if verification.get('ok') is not True:
            return f"draft-box proof is invalid: {verification.get('reason_code')}"
        proof_content = proof.get('proof_content') if isinstance(proof, dict) else {}
        evidence_ref = proof_content.get('evidence_ref') if isinstance(proof_content, dict) else None
        evidence_validation = validate_evidence_ref(
            evidence_ref,
            screenshot_root=SCREENSHOT_DIR,
        )
        if evidence_validation.get('ok') is not True:
            return (
                'draft-box proof evidence reference is invalid: '
                f"{evidence_validation.get('reason_code')}"
            )
        observed_store_identity = proof_content.get('observed_store_identity') if isinstance(proof_content, dict) else None
        authoritative_store_name = str(self._store_name_for_id(expected_store_id) or '').strip()
        if (
            not isinstance(observed_store_identity, dict)
            or not authoritative_store_name
            or str(observed_store_identity.get('store_name') or '').strip()
            != authoritative_store_name
        ):
            return 'draft-box proof observed store name does not match the authoritative store'
        observed_source_identity = proof_content.get('observed_source_identity')
        expected_source_url = (
            observed_source_identity.get('primary_url')
            if isinstance(observed_source_identity, dict)
            else None
        )
        if payload.get('source_identity') != observed_source_identity:
            return 'claimed product source identity has drifted'
        if _first_source_url_from_payload(payload) != expected_source_url:
            return 'claimed product source URL has drifted'
        if payload.get('stage_a_task_facts') != stage_a_task_facts:
            return 'claimed product Stage A task facts have drifted'
        if payload.get('stage_a_task_facts_fingerprint') != stage_a_task_facts.get('fingerprint'):
            return 'claimed product Stage A task facts fingerprint has drifted'
        if payload.get('claim_target_identity') != stage_a_task_facts.get('target_identity'):
            return 'claimed product claim target has drifted'
        if payload.get('claim_target_fingerprint') != stage_a_task_facts.get('target_identity', {}).get('fingerprint'):
            return 'claimed product claim target fingerprint has drifted'
        if payload.get('draft_box_proof_fingerprint') != proof.get('fingerprint'):
            return 'claimed product draft-box proof fingerprint has drifted'
        if str(claimed_product.get('status') or '').strip().lower() not in {'claimed_to_draft', 'ready_for_edit'}:
            return 'claimed product is not in an editable draft-box state'
        return None

    def _apply_claim_completion(
        self,
        conn: Any,
        task: dict[str, Any],
        job: dict[str, Any],
        payload: dict[str, Any],
        claimed_product: dict[str, Any],
        now: str,
    ) -> None:
        claimed_payload = claimed_product.get('payload') if isinstance(claimed_product.get('payload'), dict) else {}
        next_payload = dict(payload)
        next_payload.update({
            'stage': 'claimed_to_draft',
            'status': 'completed',
            'claimed_product_id': claimed_product.get('id'),
            'claimed_product_title': claimed_product.get('title'),
            'claimed_product_status': claimed_product.get('status'),
            'claimed_product_source': claimed_payload.get('source') or claimed_product.get('source'),
            'claimed_product_source_url': _first_source_url_from_payload(claimed_payload),
            'claimed_product_category_name': claimed_product.get('category_name'),
            'draft_box_verified': claimed_payload.get('draft_box_verified') is True,
            'claim_job_id': job.get('id'),
            'store_id': task.get('store_id'),
            'stage_a_task_facts': claimed_payload.get('stage_a_task_facts'),
            'stage_a_task_facts_fingerprint': claimed_payload.get('stage_a_task_facts_fingerprint'),
            'claim_target_identity': claimed_payload.get('claim_target_identity'),
            'claim_target_fingerprint': claimed_payload.get('claim_target_fingerprint'),
            'claimed_product_source_identity': claimed_payload.get('source_identity'),
            'draft_box_proof': claimed_payload.get('draft_box_proof'),
            'draft_box_proof_fingerprint': (claimed_payload.get('draft_box_proof') or {}).get('fingerprint'),
            'completed_at': now,
            'next_step': '进入“商品箱编辑保存”，选择该商品创建单商品只保存任务。',
        })
        task_update = conn.execute(
            """
            UPDATE tasks
               SET status='completed', completed_jobs=1, failed_jobs=0,
                   payload_json=?, updated_at=?
             WHERE id=? AND status IN ('draft', 'running')
            """,
            (dumps(next_payload), now, task['id']),
        )
        job_update = conn.execute(
            """
            UPDATE jobs
               SET status='completed',
                   current_step_code='VERIFY_DRAFT_BOX_CLAIM',
                   current_step_name='确认商品箱商品',
                   error_code=NULL,
                   error_message=NULL,
                   updated_at=?
             WHERE id=? AND task_id=? AND product_id IS NULL
               AND status IN ('pending', 'running')
            """,
            (now, job['id'], task['id']),
        )
        if task_update.rowcount != 1 or job_update.rowcount != 1:
            raise RuntimeError('claim completion compare-and-set failed')

    def try_start_task(self, task_id: int) -> bool:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._active_edit_batch_exists(conn):
                return False
            if self._other_running_task_exists(conn, task_id):
                return False
            cur = conn.execute(
                "UPDATE tasks SET status='running', updated_at=? WHERE id=? AND status='draft'",
                (now, task_id),
            )
            return cur.rowcount == 1

    def try_start_task_with_authorization(
        self,
        task_id: int,
        *,
        token: str,
        confirmation: str,
        approved_by: str,
        authorization_context: dict[str, Any],
        consumed_at: str | None = None,
    ) -> AuthorizationLeaseResult:
        now_text = consumed_at or now_iso()
        try:
            current_time = datetime.fromisoformat(now_text)
        except ValueError:
            return AuthorizationLeaseResult(False, 'AUTH_TIME_INVALID', self.get_task(task_id), None)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return AuthorizationLeaseResult(False, 'AUTH_TASK_NOT_FOUND', None, None)
            payload = loads(task['payload_json'], {})
            approval = payload.get('manual_approval') if isinstance(payload.get('manual_approval'), dict) else {}
            reason_code = 'OK'
            stored_token_hash = str(approval.get('token_hash') or '')
            actual_token_hash = hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()
            stored_approver = str(approval.get('approved_by') or '')
            stored_confirmation = str(approval.get('confirmation') or '')
            expires_at = str(approval.get('expires_at') or '')
            try:
                expiry = datetime.fromisoformat(expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except ValueError:
                expiry = None
            stored_context = approval.get('authorization_context')
            context_check = compare_authorization_context(stored_context, authorization_context)
            edit_batch_active = self._active_edit_batch_exists(conn)
            another_task_active = self._other_running_task_exists(conn, task_id)
            if task.get('status') != 'draft':
                reason_code = 'AUTH_TASK_NOT_DRAFT'
            elif edit_batch_active:
                reason_code = 'AUTH_EDIT_BATCH_ACTIVE'
            elif another_task_active:
                reason_code = 'AUTH_ANOTHER_TASK_ACTIVE'
            elif approval.get('approved') is not True or approval.get('source') != 'server':
                reason_code = 'AUTH_LEASE_NOT_APPROVED'
            elif approval.get('consumed') is True:
                reason_code = 'AUTH_LEASE_CONSUMED'
            elif not stored_token_hash or not hmac.compare_digest(actual_token_hash, stored_token_hash):
                reason_code = 'AUTH_TOKEN_MISMATCH'
            elif not stored_approver or not hmac.compare_digest(str(approved_by).encode('utf-8'), stored_approver.encode('utf-8')):
                reason_code = 'AUTH_APPROVER_MISMATCH'
            elif not stored_confirmation or not hmac.compare_digest(str(confirmation).encode('utf-8'), stored_confirmation.encode('utf-8')):
                reason_code = 'AUTH_CONFIRMATION_MISMATCH'
            elif expiry is None or current_time >= expiry:
                reason_code = 'AUTH_LEASE_EXPIRED'
            elif approval.get('stage_task_facts') != (stored_context or {}).get('stage_task_facts'):
                reason_code = 'AUTH_STAGE_FACTS_MISMATCH'
            elif context_check.get('ok') is not True:
                reason_code = str(context_check.get('reason_code') or 'AUTH_CONTEXT_MISMATCH')
            if reason_code != 'OK':
                task['payload'] = self._public_task_payload(payload)
                task.pop('payload_json', None)
                return AuthorizationLeaseResult(
                    False,
                    reason_code,
                    task,
                    self._public_authorization_lease(approval),
                )
            next_approval = dict(approval)
            next_approval.update({'consumed': True, 'consumed_at': now_text})
            next_payload = dict(payload)
            next_payload['manual_approval'] = next_approval
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='running', payload_json=?, updated_at=?
                 WHERE id=? AND status='draft'
                """,
                (dumps(next_payload), now_text, task_id),
            )
            if updated.rowcount != 1:
                return AuthorizationLeaseResult(False, 'AUTH_START_CAS_CONFLICT', self.get_task(task_id), None)
        return AuthorizationLeaseResult(
            True,
            'OK',
            self.get_task(task_id),
            self._public_authorization_lease(next_approval),
        )

    def verify_consumed_task_authorization(
        self,
        task_id: int,
        *,
        authorization_context: dict[str, Any],
        checked_at: str | None = None,
    ) -> AuthorizationLeaseResult:
        now_text = checked_at or now_iso()
        try:
            current_time = datetime.fromisoformat(now_text)
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
        except ValueError:
            return AuthorizationLeaseResult(False, 'AUTH_TIME_INVALID', self.get_task(task_id), None)
        task = self.get_task_private(task_id)
        if not task:
            return AuthorizationLeaseResult(False, 'AUTH_TASK_NOT_FOUND', None, None)
        payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        approval = payload.get('manual_approval') if isinstance(payload.get('manual_approval'), dict) else {}
        expires_at = str(approval.get('expires_at') or '')
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            expiry = None
        stored_context = approval.get('authorization_context')
        context_check = compare_authorization_context(stored_context, authorization_context)
        if task.get('status') != 'running':
            reason_code = 'AUTH_TASK_NOT_RUNNING'
        elif approval.get('approved') is not True or approval.get('source') != 'server':
            reason_code = 'AUTH_LEASE_NOT_APPROVED'
        elif approval.get('consumed') is not True or not approval.get('consumed_at'):
            reason_code = 'AUTH_LEASE_NOT_CONSUMED'
        elif expiry is None or current_time >= expiry:
            reason_code = 'AUTH_LEASE_EXPIRED'
        elif approval.get('stage_task_facts') != (stored_context or {}).get('stage_task_facts'):
            reason_code = 'AUTH_STAGE_FACTS_MISMATCH'
        elif context_check.get('ok') is not True:
            reason_code = str(context_check.get('reason_code') or 'AUTH_CONTEXT_MISMATCH')
        else:
            reason_code = 'OK'
        return AuthorizationLeaseResult(
            reason_code == 'OK',
            reason_code,
            self.get_task(task_id),
            self._public_authorization_lease(approval),
        )

    def try_pause_task(self, task_id: int) -> bool:
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status='paused', updated_at=? WHERE id=? AND status='running'",
                (now, task_id),
            )
            return cur.rowcount == 1

    def try_resume_task(self, task_id: int) -> bool:
        return False

    def _public_task_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        public_payload = {
            key: value
            for key, value in dict(payload or {}).items()
            if not self._is_private_task_payload_key(key)
        }
        approval = public_payload.get('manual_approval')
        if isinstance(approval, dict):
            public_approval = {
                key: value
                for key, value in approval.items()
                if key in {
                    'approved',
                    'approved_by',
                    'approved_at',
                    'source',
                    'confirmation',
                    'issued_at',
                    'expires_at',
                    'consumed',
                    'consumed_at',
                }
            }
            public_payload['manual_approval'] = public_approval
        return public_payload

    @staticmethod
    def _is_private_task_payload_key(key: Any) -> bool:
        normalized = str(key).strip().lower().replace('-', '_')
        compact = normalized.replace('_', '')
        if compact in {
            'authorizationcontext',
            'claimtargetidentity',
            'claimedproductsourceidentity',
            'draftboxproof',
            'sourceidentity',
            'stageataskfacts',
            'stagetaskfacts',
            'startcontext',
        }:
            return True
        if compact == 'grant' or compact.startswith('grant'):
            return True
        if compact in {
            'approvaltoken',
            'onetimenonce',
            'rawnonce',
            'token',
        }:
            return True
        return (
            'nonce' in compact
            or compact.endswith('digest')
            or compact.endswith('fingerprint')
            or compact.endswith('hash')
            or compact.endswith('sha256')
            or compact.endswith('token')
        )

    @staticmethod
    def _public_authorization_lease(approval: Any) -> dict[str, Any] | None:
        if not isinstance(approval, dict) or not approval:
            return None
        return {
            key: approval.get(key)
            for key in (
                'approved',
                'approved_by',
                'approved_at',
                'source',
                'confirmation',
                'issued_at',
                'expires_at',
                'consumed',
                'consumed_at',
            )
            if key in approval
        }

    def update_job(self, job_id: int, **fields):
        now = now_iso()
        requested_status = fields.get("status")
        cols = []
        values = []
        for key, value in fields.items():
            cols.append(f"{key}=?")
            values.append(value)
        if not cols:
            return False
        cols.append("updated_at=?")
        values.append(now)
        values.append(job_id)
        with connection() as conn:
            if requested_status is not None:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT status FROM jobs WHERE id=?",
                    (job_id,),
                ).fetchone()
                if not current:
                    return False
                current_status = str(current.get("status") or "")
                next_status = str(requested_status or "")
                failure_terminal = {
                    "failed",
                    "cancelled",
                    "needs_manual_review",
                    "stopped_uncertain",
                }
                success_terminal = {"succeeded", "completed"}
                if current_status in failure_terminal and next_status != current_status:
                    return False
                if current_status in success_terminal and next_status in {"pending", "running"}:
                    return False
            updated = conn.execute(
                f"UPDATE jobs SET {', '.join(cols)} WHERE id=?",
                values,
            )
            return updated.rowcount == 1

    def add_log(self, task_id: int, job_id: int | None, level: str, message: str, context: dict[str, Any] | None = None):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO job_logs (task_id, job_id, level, message, context_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, job_id, level, message, dumps(context or {}), now),
            )

    def list_logs(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM job_logs ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_logs WHERE task_id=? ORDER BY id DESC LIMIT 200", (task_id,)).fetchall()
            for row in rows:
                row['context'] = loads(row.pop('context_json'), {})
            return rows

    def add_evidence(self, task_id: int, job_id: int | None, evidence_type: str, file_path: str | None, meta: dict[str, Any] | None = None):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO job_evidences (task_id, job_id, evidence_type, file_path, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, job_id, evidence_type, file_path, dumps(meta or {}), now),
            )

    def list_evidences(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM job_evidences ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_evidences WHERE task_id=? ORDER BY id DESC LIMIT 200", (task_id,)).fetchall()
            for row in rows:
                row['meta'] = loads(row.pop('meta_json'), {})
            return rows

    def add_exception(self, task_id: int, job_id: int | None, error_code: str, field_domain: str, title: str, detail: str, suggestion: str):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO exceptions (task_id, job_id, error_code, field_domain, title, detail, suggestion, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, job_id, error_code, field_domain, title, detail, suggestion, now, now),
            )

    def list_exceptions(self):
        with connection() as conn:
            return conn.execute("SELECT * FROM exceptions ORDER BY id DESC LIMIT 200").fetchall()

    def list_task_exceptions(self, task_id: int):
        """Return the complete exception history for one exact task."""
        with connection() as conn:
            return conn.execute(
                "SELECT * FROM exceptions WHERE task_id=? ORDER BY id DESC",
                (task_id,),
            ).fetchall()

    def add_report(
        self,
        task_id: int,
        job_id: int | None,
        product_id: int | None,
        status: str,
        published: bool | None,
        save_result: dict[str, Any],
        summary: dict[str, Any],
    ):
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            report_id = self._upsert_report(
                conn,
                task_id,
                job_id,
                product_id,
                status,
                published,
                save_result,
                summary,
                now,
            )
        return self.get_report(report_id)

    def finalize_job_success(
        self,
        task_id: int,
        job_id: int,
        product_id: int | None,
        *,
        published: bool | None,
        save_result: dict[str, Any],
        summary: dict[str, Any],
    ) -> JobFinalizationResult:
        now = now_iso()
        report_id: int | None = None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                conflict_code = "TASK_NOT_FOUND"
                reason = "task does not exist"
            elif task.get("status") != "running":
                conflict_code = "TASK_TERMINAL_STATE_CONFLICT"
                reason = f"task status is {task.get('status')!r}, expected 'running'"
            else:
                job = conn.execute(
                    "SELECT status FROM jobs WHERE id=? AND task_id=?",
                    (job_id, task_id),
                ).fetchone()
                if not job:
                    conflict_code = "JOB_NOT_FOUND"
                    reason = "job does not exist for task"
                elif job.get("status") != "running":
                    conflict_code = "JOB_TERMINAL_STATE_CONFLICT"
                    reason = f"job status is {job.get('status')!r}, expected 'running'"
                else:
                    existing = conn.execute(
                        "SELECT status FROM reports WHERE task_id=? AND job_id IS ? ORDER BY id LIMIT 1",
                        (task_id, job_id),
                    ).fetchone()
                    if existing and existing.get("status") == "failed":
                        conflict_code = TerminalReportConflictError.conflict_code
                        reason = "failed report is terminal"
                    else:
                        report_id = self._upsert_report(
                            conn,
                            task_id,
                            job_id,
                            product_id,
                            "success",
                            published,
                            save_result,
                            summary,
                            now,
                        )
                        updated = conn.execute(
                            """
                            UPDATE jobs
                               SET status='succeeded', current_step_code='DONE',
                                   current_step_name='V1 执行完成', error_code=NULL,
                                   error_message=NULL, updated_at=?
                             WHERE id=? AND task_id=? AND status='running'
                            """,
                            (now, job_id, task_id),
                        )
                        if updated.rowcount != 1:
                            raise RuntimeError("job success compare-and-set failed")
                        conflict_code = None
                        reason = None
        return JobFinalizationResult(
            applied=conflict_code is None,
            conflict_code=conflict_code,
            reason=reason,
            report=self.get_report(report_id) if report_id is not None else None,
        )

    def finalize_job_failure(
        self,
        task_id: int,
        job_id: int,
        product_id: int | None,
        *,
        error_code: str,
        field_domain: str,
        title: str,
        detail: str,
        suggestion: str,
        save_result: dict[str, Any],
        summary: dict[str, Any],
    ) -> JobFinalizationResult:
        """Persist one job failure as a single failure-priority transaction."""
        now = now_iso()
        report_id: int | None = None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                conflict_code = "TASK_NOT_FOUND"
                reason = "task does not exist"
            else:
                job = conn.execute(
                    "SELECT status FROM jobs WHERE id=? AND task_id=?",
                    (job_id, task_id),
                ).fetchone()
                if not job:
                    conflict_code = "JOB_NOT_FOUND"
                    reason = "job does not exist for task"
                else:
                    existing_report = conn.execute(
                        "SELECT id, status FROM reports WHERE task_id=? AND job_id IS ? ORDER BY id LIMIT 1",
                        (task_id, job_id),
                    ).fetchone()
                    already_terminal = bool(
                        existing_report
                        and existing_report.get("status") == "failed"
                        and job.get("status") == "failed"
                    )
                    if already_terminal:
                        conflict_code = TerminalReportConflictError.conflict_code
                        reason = "failed report and failed job are already terminal"
                        report_id = int(existing_report["id"])
                    else:
                        report_id = (
                            int(existing_report["id"])
                            if existing_report and existing_report.get("status") == "failed"
                            else self._upsert_report(
                                conn,
                                task_id,
                                job_id,
                                product_id,
                                "failed",
                                None,
                                save_result,
                                summary,
                                now,
                            )
                        )
                        conn.execute(
                            """
                            UPDATE jobs
                               SET status='failed', current_step_code='FAILED',
                                   current_step_name='执行失败', error_code=?,
                                   error_message=?, updated_at=?
                             WHERE id=? AND task_id=?
                            """,
                            (error_code, detail, now, job_id, task_id),
                        )
                        conn.execute(
                            """
                            INSERT INTO exceptions (
                                task_id, job_id, error_code, field_domain, title,
                                detail, suggestion, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                task_id,
                                job_id,
                                error_code,
                                field_domain,
                                title,
                                detail,
                                suggestion,
                                now,
                                now,
                            ),
                        )
                        conn.execute(
                            """
                            UPDATE tasks
                               SET completed_jobs=(
                                       SELECT COUNT(*) FROM jobs
                                        WHERE task_id=? AND status IN ('succeeded', 'completed')
                                   ),
                                   failed_jobs=(
                                       SELECT COUNT(*) FROM jobs
                                        WHERE task_id=? AND status='failed'
                                   ),
                                   updated_at=?
                             WHERE id=?
                            """,
                            (task_id, task_id, now, task_id),
                        )
                        # Failure is terminal for the active task. A user-selected
                        # manual-review/cancelled state remains authoritative.
                        conn.execute(
                            """
                            UPDATE tasks
                               SET status='failed', updated_at=?
                             WHERE id=? AND status IN ('running', 'paused', 'completed', 'partial_success')
                            """,
                            (now, task_id),
                        )
                        conflict_code = None
                        reason = None
        return JobFinalizationResult(
            applied=conflict_code is None,
            conflict_code=conflict_code,
            reason=reason,
            report=self.get_report(report_id) if report_id is not None else None,
        )

    def _upsert_report(
        self,
        conn,
        task_id: int,
        job_id: int | None,
        product_id: int | None,
        status: str,
        published: bool | None,
        save_result: dict[str, Any],
        summary: dict[str, Any],
        now: str,
    ) -> int:
        published_db = _published_to_db(published)
        existing = conn.execute(
            "SELECT id, status FROM reports WHERE task_id=? AND job_id IS ? ORDER BY id LIMIT 1",
            (task_id, job_id),
        ).fetchone()
        if existing and existing.get('status') == 'failed':
            if status != 'failed':
                raise TerminalReportConflictError(task_id, job_id)
            return int(existing['id'])
        if existing:
            conn.execute(
                """
                UPDATE reports
                SET product_id=?, status=?, published=?, save_result_json=?, summary_json=?, updated_at=?
                WHERE id=?
                """,
                (product_id, status, published_db, dumps(save_result), dumps(summary), now, existing['id']),
            )
            return int(existing['id'])
        cur = conn.execute(
            """
            INSERT INTO reports (
                task_id, job_id, product_id, status, published,
                save_result_json, summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, job_id, product_id, status, published_db, dumps(save_result), dumps(summary), now, now),
        )
        return int(cur.lastrowid)

    def get_report(self, report_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                return None
            row['published'] = _published_from_db(row['published'])
            row['save_result'] = loads(row.pop('save_result_json'), {})
            row['summary'] = loads(row.pop('summary_json'), {})
            return row

    def list_reports(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM reports WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
            for row in rows:
                row['published'] = _published_from_db(row['published'])
                row['save_result'] = loads(row.pop('save_result_json'), {})
                row['summary'] = loads(row.pop('summary_json'), {})
            return rows
