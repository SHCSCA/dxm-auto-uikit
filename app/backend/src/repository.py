from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.core.config import SCREENSHOT_DIR
from src.db import (
    connection,
    disable_edit_batch_bundles_with_quarantined_sources,
    disable_legacy_generated_starter_templates,
    disable_unexecutable_edit_batch_bundles,
    dumps,
    loads,
    migrate_canonical_receipts,
    migrate_real_dxm_path_b_discovery_receipts,
    migrate_real_dxm_write_scopes,
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
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MutationCommandContractError,
    browser_agent_command_sha256,
    canonical_frozen_target_identity,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_action_result_envelope,
)
from src.execution.batch_command_contract import (
    PATH_B_SAVE1_DISCOVERY_ACTION,
    PATH_B_FORMAL_LINEAGE_KEY,
    PATH_B_FORMAL_LINEAGE_SCHEMA,
    PATH_B_SAVE1_DISCOVERY_PROFILE_KEY,
    PATH_B_SAVE1_DISCOVERY_STATE,
    BatchCommandContractError,
    build_path_b_save1_discovery_profile,
    rebuild_save_verification_authority,
    validate_path_b_save1_discovery_dispatch,
    validate_path_b_save1_discovery_profile,
    validate_path_b_formal_lineage,
    validate_save_verification_context,
)
from src.execution.batch_dispatch_authority import (
    DispatchAuthorityError,
    save_verification_facts_from_frozen_authority,
)
from src.execution.canonical_receipt import (
    ReceiptPhase,
    ReceiptValidationError,
    SaveReceipt,
    build_save_receipt_from_verified_pair,
    validated_field_readbacks_from_payload,
)
from src.execution.task_worker_control import (
    ACTIVE_TASK_STATUSES,
    PAYLOAD_KEY as WORKER_CONTROL_PAYLOAD_KEY,
    TaskControlResult,
    build_ack_control,
    build_request_control,
    empty_worker_control,
    normalize_worker_control,
    public_worker_control,
)
from src.services.evidence_ref import validate_evidence_ref
from src.state_machine.save_authorization import (
    SaveOnlyContractError,
    build_product_box_snapshot,
    canonical_source_identity,
    canonical_sha256 as canonical_contract_sha256,
    compare_authorization_context as compare_save_authorization_context,
    verify_product_box_snapshot,
)
from src.state_machine.batch_draft_authorization import (
    BATCH_DRAFT_SAVE_CONFIRMATION,
    BATCH_DRAFT_SAVE_PUBLISH_SCENE,
    BatchDraftAuthorizationError,
    build_authorization_context as build_batch_authorization_context,
    build_batch_draft_save_task_facts,
    compare_authorization_context as compare_batch_authorization_context,
    verify_authorization_context as verify_batch_authorization_context,
)
from src.real_dxm_write_scope import (
    RealDxmWriteScopeError,
    validate_real_dxm_write_authorization,
)
from src.core.config import EVIDENCE_DIR
from src.utils import now_iso


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


class _AtomicPathBStartRejected(RuntimeError):
    """Private rollback signal for the all-or-nothing Path B start transaction."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _RealDxmAuthorizationBindingError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


_PATH_B_DISCOVERY_RECEIPT_SCHEMA = (
    "dxm.real-dxm-path-b.save1-discovery-receipt.v1"
)
_PATH_B_DISCOVERY_LEAF_PROOF_SCHEMA = (
    "dxm.real-dxm-path-b.discovery-leaf-proof-manifest.v1"
)


def _discovery_attempt_public_status(
    attempt_status: Any,
    *,
    task_status: Any = None,
) -> str:
    normalized = str(attempt_status or "").strip().lower()
    if normalized == "sealed":
        return "DISCOVERY_SEALED"
    if normalized == "unknown":
        return "UNKNOWN"
    if normalized == "blocked":
        return "BLOCKED"
    if normalized == "armed" and str(task_status or "").strip() == "running":
        return "RUNNING"
    return "ARMED"


def _normalized_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if len(normalized) != 64 or any(
        character not in "0123456789ABCDEF" for character in normalized
    ):
        return None
    return normalized


def _derive_real_dxm_write_authorization_binding(
    scope: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    consumed_at: str,
) -> dict[str, Any]:
    """Derive the immutable task binding and all phase-specific SAVE leases."""

    scope_sha256 = str(scope.get("scopeSha256") or "")
    approval_sha256 = str(approval.get("approvalSha256") or "")
    snapshot = scope.get("snapshot") if isinstance(scope.get("snapshot"), Mapping) else {}
    task_id = snapshot.get("taskId")
    products = scope.get("orderedProducts") if isinstance(scope.get("orderedProducts"), list) else []
    if (
        isinstance(task_id, bool)
        or not isinstance(task_id, int)
        or task_id <= 0
        or len(products) < 3
    ):
        raise _RealDxmAuthorizationBindingError("SAVE_LEASE_COUNT_INVALID")

    save_leases: list[dict[str, Any]] = []
    ordered_product_ids: list[int] = []
    for expected_ordinal, item in enumerate(products, start=1):
        if not isinstance(item, Mapping):
            raise _RealDxmAuthorizationBindingError("SAVE_LEASE_COUNT_INVALID")
        product_id = item.get("productId")
        ordinal = item.get("ordinal")
        saves = item.get("saves")
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal != expected_ordinal
            or not isinstance(saves, list)
            or [save.get("stage") if isinstance(save, Mapping) else None for save in saves]
            != ["SAVE1", "SAVE2"]
        ):
            raise _RealDxmAuthorizationBindingError("SAVE_LEASE_COUNT_INVALID")
        ordered_product_ids.append(product_id)
        for save_stage in ("SAVE1", "SAVE2"):
            lease_material = (
                f"real-path-b-save-lease:{scope_sha256}:{approval_sha256}:"
                f"{task_id}:{ordinal}:{product_id}:{save_stage}"
            )
            save_leases.append(
                {
                    "product_id": product_id,
                    "product_ordinal": ordinal,
                    "save_stage": save_stage,
                    "lease_id": hashlib.sha256(lease_material.encode("utf-8")).hexdigest(),
                    "scope_sha256": scope_sha256,
                    "expires_at": approval.get("expiresAt"),
                    "single_use": True,
                }
            )
    if len(save_leases) != 2 * len(products) or len({item["lease_id"] for item in save_leases}) != len(save_leases):
        raise _RealDxmAuthorizationBindingError("SAVE_LEASE_COUNT_INVALID")
    return {
        "schema": "real_dxm_write_authorization.v1",
        "scope_sha256": scope_sha256,
        "approval_sha256": approval_sha256,
        "approval_nonce_sha256": hashlib.sha256(
            str(approval.get("nonce") or "").encode("utf-8")
        ).hexdigest().upper(),
        "approval_consumed_at": consumed_at,
        "approval_expires_at": approval.get("expiresAt"),
        "approved_by": approval.get("approvedBy"),
        "ordered_product_ids": ordered_product_ids,
        "save_leases": save_leases,
        "publish_allowed": False,
    }


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


def _product_box_evidence_integrity_error(evidence_ref: Any) -> str | None:
    """Validate the immutable on-disk source evidence used by a product-box task."""

    if not isinstance(evidence_ref, dict) or set(evidence_ref) != {'path', 'sha256', 'size'}:
        return 'product-box evidence reference is invalid'
    path_text = evidence_ref.get('path')
    digest = evidence_ref.get('sha256')
    expected_size = evidence_ref.get('size')
    if (
        not isinstance(path_text, str)
        or not path_text.strip()
        or not isinstance(digest, str)
        or len(digest) != 64
        or digest != digest.upper()
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size <= 0
    ):
        return 'product-box evidence reference is invalid'
    try:
        int(digest, 16)
    except ValueError:
        return 'product-box evidence reference is invalid'

    configured_root = EVIDENCE_DIR.resolve(strict=False)
    supplied_path = Path(path_text)
    if not supplied_path.is_absolute():
        return 'product-box evidence path is not absolute'
    try:
        resolved_path = supplied_path.resolve(strict=True)
        resolved_path.relative_to(configured_root)
    except (FileNotFoundError, OSError, RuntimeError):
        return 'product-box evidence file is missing'
    except ValueError:
        return 'product-box evidence path is outside the evidence directory'
    if supplied_path.is_symlink() or not resolved_path.is_file():
        return 'product-box evidence path is not a regular file'
    try:
        stat = resolved_path.stat()
        if stat.st_size != expected_size:
            return 'product-box evidence size does not match its immutable reference'
        hasher = hashlib.sha256()
        with resolved_path.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                hasher.update(block)
    except OSError:
        return 'product-box evidence file cannot be read'
    if not hmac.compare_digest(hasher.hexdigest().upper(), digest):
        return 'product-box evidence SHA-256 does not match its immutable reference'
    return None


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
            disable_unexecutable_edit_batch_bundles(conn)
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
            disable_unexecutable_edit_batch_bundles(conn)
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
        evidence_ref = self._persist_product_box_scope_evidence(snapshot)
        with connection() as conn:
            existing = conn.execute(
                "SELECT * FROM draft_box_scope_snapshots WHERE digest=?",
                (snapshot['digest'],),
            ).fetchone()
            if existing:
                stored_snapshot = loads(existing['snapshot_json'], {})
                if stored_snapshot != snapshot:
                    raise SaveOnlyContractError(
                        'PRODUCT_BOX_SCOPE_DIGEST_CONFLICT',
                        'an existing product-box scope digest contains different facts',
                    )
                stored = {
                    'id': int(existing['id']),
                    **stored_snapshot,
                    'created_at': existing['created_at'],
                }
            else:
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
            store_id, local_product_ids = self._sync_products_from_scope_snapshot(
                conn,
                stored,
                evidence_ref=evidence_ref,
            )
            return self._public_draft_box_scope_snapshot(
                stored,
                store_id=store_id,
                local_product_ids=local_product_ids,
            )

    @staticmethod
    def _persist_product_box_scope_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
        content = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
        digest = hashlib.sha256(content).hexdigest().upper()
        declared_digest = str(snapshot.get('digest') or '').strip().upper()
        if len(declared_digest) != 64:
            raise SaveOnlyContractError(
                'PRODUCT_BOX_SCOPE_DIGEST_INVALID',
                'product-box scope digest is missing or invalid',
            )
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = (EVIDENCE_DIR / f'product-box-scope-{declared_digest}.json').resolve()
        if path.exists():
            existing = path.read_bytes()
            if existing != content:
                raise SaveOnlyContractError(
                    'PRODUCT_BOX_SCOPE_EVIDENCE_CONFLICT',
                    'product-box scope evidence path already contains different facts',
                )
        else:
            path.write_bytes(content)
        return {'path': str(path), 'sha256': digest, 'size': len(content)}

    @staticmethod
    def _sync_products_from_scope_snapshot(
        conn: Any,
        snapshot: dict[str, Any],
        *,
        evidence_ref: dict[str, Any],
    ) -> tuple[int | None, dict[int, int]]:
        store_identity = snapshot.get('store_identity')
        store_name = (
            str(store_identity.get('store_name') or '').strip()
            if isinstance(store_identity, dict)
            else ''
        )
        normalized_store_name = ' '.join(store_name.split())
        stores = conn.execute('SELECT id, name FROM stores ORDER BY id ASC').fetchall()
        matches = [
            row
            for row in stores
            if ' '.join(str(row.get('name') or '').strip().split()) == normalized_store_name
        ]
        if len(matches) != 1:
            return None, {}
        store_id = int(matches[0]['id'])
        existing_rows = conn.execute(
            "SELECT * FROM products WHERE source='dxm_draft_box' ORDER BY id ASC"
        ).fetchall()
        existing_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in existing_rows:
            payload = loads(row.get('payload_json'), {})
            key = payload.get('product_box_record_key') if isinstance(payload, dict) else None
            if isinstance(key, str) and key:
                existing_by_key.setdefault(key, []).append(row)

        local_product_ids: dict[int, int] = {}
        observed_at = str(snapshot.get('observed_at') or '')
        scope_digest = str(snapshot.get('digest') or '').strip().upper()
        for item in snapshot.get('items') or []:
            if not isinstance(item, dict):
                continue
            ordinal = int(item['ordinal'])
            record_key = f"{store_id}:{item['stable_record_key']}"
            candidates = existing_by_key.get(record_key, [])
            if len(candidates) > 1:
                raise SaveOnlyContractError(
                    'PRODUCT_BOX_IDENTITY_AMBIGUOUS',
                    'multiple local products match one live product-box identity',
                )
            payload = {
                'store_id': store_id,
                'store_name': store_name,
                'draft_box_verified': True,
                'source_url': item['source_url'],
                'source_urls': list(item['source_urls']),
                'product_box_record_key': record_key,
                'product_box_observed_at': observed_at,
                'product_box_evidence_ref': dict(evidence_ref),
                'product_box_target_identity': dict(item['target_identity']),
                'product_box_target_identity_sha256': item['target_identity_sha256'],
                'product_box_scope_snapshot_id': int(snapshot['id']),
                'product_box_scope_digest': scope_digest,
            }
            if candidates:
                product_id = int(candidates[0]['id'])
                conn.execute(
                    """
                    UPDATE products
                       SET title=?, source='dxm_draft_box', status='ready_for_edit',
                           payload_json=?, updated_at=?
                     WHERE id=?
                    """,
                    (item['title'], dumps(payload), observed_at, product_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO products (
                        title, source, status, category_name, price, currency,
                        sku_count, image_count, payload_json, created_at, updated_at
                    ) VALUES (?, 'dxm_draft_box', 'ready_for_edit', '未分类', 0, 'USD', 1, 0, ?, ?, ?)
                    """,
                    (item['title'], dumps(payload), observed_at, observed_at),
                )
                product_id = int(cur.lastrowid)
                existing_by_key[record_key] = [{'id': product_id}]
            local_product_ids[ordinal] = product_id
        return store_id, local_product_ids

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
    def _public_draft_box_scope_snapshot(
        snapshot: dict[str, Any],
        *,
        store_id: int | None = None,
        local_product_ids: dict[int, int] | None = None,
    ) -> dict[str, Any]:
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
                'store_id': store_id,
            },
            'filter_state': snapshot.get('filter_state'),
            'sort_state': snapshot.get('sort_state'),
            'page_state': snapshot.get('page_state'),
            'items': [
                {
                    'ordinal': item.get('ordinal'),
                    'title': item.get('title'),
                    'dxm_product_id': item.get('dxm_product_id'),
                    'local_product_id': (local_product_ids or {}).get(int(item.get('ordinal') or 0)),
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
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        return conn.execute(
            f"SELECT 1 AS active FROM tasks WHERE status IN ({placeholders}) LIMIT 1",
            tuple(ACTIVE_TASK_STATUSES),
        ).fetchone() is not None

    @staticmethod
    def _other_running_task_exists(conn: Any, task_id: int) -> bool:
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        return conn.execute(
            f"SELECT 1 AS active FROM tasks WHERE status IN ({placeholders}) AND id<>? LIMIT 1",
            (*ACTIVE_TASK_STATUSES, task_id),
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
            cancelled = cls._edit_batch_ledger_time(
                cancellation.get("cancelled_at")
            )
            if cancelled is None or not reserved <= cancelled <= stopped:
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

    @staticmethod
    def _edit_batch_normalized_page_url(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = urlparse(value)
        except ValueError:
            return None
        scheme = str(parsed.scheme or "").casefold()
        hostname = str(parsed.hostname or "").casefold()
        if scheme not in {"http", "https"} or not hostname:
            return None
        path = str(parsed.path or "").rstrip("/")
        return f"{scheme}://{hostname}{path}?{parsed.query}".rstrip("?")

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
        try:
            ledger_outcome = loads(row.get("outcome_json"), None)
        except (TypeError, ValueError):
            return "MUTATION_LEDGER_DISPATCH_UNPROVEN"
        if not (
            ledger_outcome is True
            or (
                isinstance(ledger_outcome, dict)
                and ledger_outcome.get("dispatched") is True
            )
        ):
            return "MUTATION_LEDGER_DISPATCH_UNPROVEN"
        save_page = outcome.get("save_page_identity")
        ledger_page_url = cls._edit_batch_normalized_page_url(row.get("page_url"))
        save_page_url = cls._edit_batch_normalized_page_url(
            save_page.get("url") if isinstance(save_page, dict) else None
        )
        expected_runtime_id = (
            stored_grant.get("runtime_identity", {}).get("browser_runtime_id")
            if isinstance(stored_grant.get("runtime_identity"), dict)
            else None
        )
        if (
            not isinstance(save_page, dict)
            or row.get("page_kind") != "semi_managed"
            or save_page.get("kind") != row.get("page_kind")
            or save_page.get("browser_session_id") != row.get("browser_session_id")
            or row.get("runtime_id") != expected_runtime_id
            or save_page.get("runtime_id") != expected_runtime_id
            or ledger_page_url is None
            or row.get("page_url") != ledger_page_url
            or save_page_url != ledger_page_url
        ):
            return "MUTATION_LEDGER_PAGE_IDENTITY_UNPROVEN"
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
            rows = conn.execute(
                """
                SELECT * FROM products
                 WHERE source NOT IN ('removed_workflow_legacy', 'dxm_data_acquisition')
                   AND status!='claimed_to_draft'
                 ORDER BY id DESC
                """
            ).fetchall()
            for row in rows:
                row['payload'] = loads(row.pop('payload_json'), {})
                self._attach_product_lifecycle(row)
            return rows

    def get_product(self, product_id: int):
        with connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM products
                 WHERE id=?
                   AND source NOT IN ('removed_workflow_legacy', 'dxm_data_acquisition')
                   AND status!='claimed_to_draft'
                """,
                (product_id,),
            ).fetchone()
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
            rows = conn.execute(
                "SELECT * FROM tasks WHERE mode!='removed_workflow_legacy' ORDER BY id DESC"
            ).fetchall()
            for row in rows:
                row['payload'] = self._public_task_payload(loads(row.pop('payload_json'), {}))
            return rows

    def list_task_summaries(self, *, mode: str | None = None):
        """List task metadata without reading or decoding frozen task payloads."""

        normalized_mode = str(mode or '').strip()
        sql = """
            SELECT id, name, store_id, status, mode, publish_scene,
                   total_jobs AS item_count, completed_jobs, failed_jobs,
                   created_at, updated_at
              FROM tasks
        """
        params: tuple[Any, ...] = ()
        if normalized_mode:
            sql += " WHERE mode=?"
            params = (normalized_mode,)
        sql += " ORDER BY id DESC"
        with connection() as conn:
            return conn.execute(sql, params).fetchall()

    def get_task(self, task_id: int, *, include_private: bool = False):
        with connection() as conn:
            task = conn.execute(
                "SELECT * FROM tasks WHERE id=? AND mode!='removed_workflow_legacy'",
                (task_id,),
            ).fetchone()
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
            'execution_mode': data['mode'],
            'publish_allowed': False,
            'max_count': len(data.get('product_ids', [])),
        })
        with connection() as conn:
            if data.get('mode') == 'single_save':
                self._attach_single_save_product_box_snapshot(
                    conn,
                    payload,
                    data.get('product_ids', []),
                    expected_store_id=data.get('store_id'),
                )
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

    def _attach_single_save_product_box_snapshot(
        self,
        conn: Any,
        payload: dict[str, Any],
        product_ids: list[int],
        *,
        expected_store_id: Any,
    ) -> None:
        if len(product_ids) != 1:
            return
        product = conn.execute("SELECT * FROM products WHERE id=?", (int(product_ids[0]),)).fetchone()
        if not product:
            return
        product_payload = loads(product.get('payload_json'), {})
        product['payload'] = product_payload
        if product.get('source') != 'dxm_draft_box':
            raise SaveOnlyContractError(
                'PRODUCT_BOX_SOURCE_INVALID',
                'single-save requires a product created from the current product-box scope',
            )
        source_url = self._first_source_url(product_payload)
        source_urls = list(product_payload.get('source_urls') or ([source_url] if source_url else []))
        if not source_url:
            raise SaveOnlyContractError(
                'PRODUCT_BOX_IDENTITY_MISSING',
                'single-save requires an exact product-box source identity',
            )
        product_store_id = product_payload.get('store_id')
        if (
            isinstance(expected_store_id, bool)
            or not isinstance(expected_store_id, int)
            or expected_store_id <= 0
            or isinstance(product_store_id, bool)
            or not isinstance(product_store_id, int)
            or product_store_id != expected_store_id
        ):
            raise SaveOnlyContractError(
                'PRODUCT_BOX_STORE_MISMATCH',
                'single-save task store must match the product-box item store',
            )
        if product.get('status') != 'ready_for_edit':
            raise SaveOnlyContractError(
                'PRODUCT_BOX_STATUS_INVALID',
                'single-save requires a product currently available in the product box',
            )
        if product_payload.get('draft_box_verified') is not True:
            raise SaveOnlyContractError(
                'PRODUCT_BOX_NOT_VERIFIED',
                'single-save requires current product-box verification',
            )
        store_name = str(product_payload.get('store_name') or self._store_name_for_id(product_store_id) or '').strip()
        source_identity = canonical_source_identity(source_url, source_urls)
        evidence_ref = product_payload.get('product_box_evidence_ref')
        evidence_error = _product_box_evidence_integrity_error(evidence_ref)
        if evidence_error:
            raise SaveOnlyContractError(
                'PRODUCT_BOX_EVIDENCE_INVALID',
                evidence_error,
            )
        target_identity = product_payload.get('product_box_target_identity')
        if not isinstance(target_identity, dict):
            store_fingerprint = canonical_contract_sha256(
                {'store_name': store_name, 'source': 'structured_store_cell'}
            )
            target_identity = {
                'schema_version': 'dxm_draft_box_target.v1',
                'store_fingerprint': store_fingerprint,
                'stable_identity': {
                    'kind': 'source_url',
                    'value': source_identity['primary_url'],
                    'fingerprint': source_identity['fingerprint'],
                },
                'source_urls': list(source_identity['urls']),
            }
        target_identity = canonical_frozen_target_identity(target_identity, store_name=store_name)
        if target_identity is None:
            raise SaveOnlyContractError('PRODUCT_BOX_TARGET_INVALID', 'product-box target identity is missing')
        captured_at = str(
            product_payload.get('product_box_observed_at')
            or product_payload.get('draft_box_observed_at')
            or product.get('updated_at')
            or ''
        )
        snapshot = build_product_box_snapshot(
            product_id=int(product['id']),
            store_id=product_store_id,
            store_name=store_name,
            product_title=str(product.get('title') or ''),
            product_status=str(product.get('status') or ''),
            source_identity=source_identity,
            target_identity=target_identity,
            captured_at=captured_at,
            evidence_ref=evidence_ref,
        )
        payload.update({
            'stage': 'product_box_edit_save',
            'product_box_product_id': product.get('id'),
            'product_box_product_title': product.get('title'),
            'product_box_product_status': product.get('status'),
            'product_box_source_url': source_url,
            'product_box_category_name': product.get('category_name'),
            'store_id': product_payload.get('store_id'),
            'product_box_source_identity': source_identity,
            'product_box_source_urls': list(source_identity['urls']),
            'product_box_snapshot': snapshot,
            'product_box_snapshot_fingerprint': snapshot['fingerprint'],
            'draft_box_verified': product_payload.get('draft_box_verified') is True,
        })
        if source_url:
            payload['source_url'] = source_url

    def _first_source_url(self, payload: dict[str, Any]) -> str | None:
        return _first_source_url_from_payload(payload)

    def _attach_product_lifecycle(self, product: dict[str, Any]) -> None:
        payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
        source = str(product.get('source') or '').strip()
        source_url = self._first_source_url(payload)
        status = str(product.get('status') or '').strip().lower()
        draft_box_verified = payload.get('draft_box_verified') is True
        if status in {'saved', 'save_completed', 'completed'}:
            lifecycle_state = 'saved'
            lifecycle_label = '已保存结果'
        elif status == 'ready_for_edit' and draft_box_verified and bool(source_url):
            lifecycle_state = 'editable'
            lifecycle_label = '可编辑商品'
        else:
            lifecycle_state = 'unverified'
            lifecycle_label = '等待商品箱确认'

        if source == 'dxm_draft_box':
            source_status_label = '店小秘商品箱商品'
        elif source in {'manual', 'manual_import'}:
            source_status_label = '手工/导入商品'
        else:
            source_status_label = '等待来源确认'

        if draft_box_verified:
            draft_box_verification_label = '已确认在商品箱'
        else:
            draft_box_verification_label = '等待商品箱确认'

        product.update({
            'lifecycle_state': lifecycle_state,
            'lifecycle_label': lifecycle_label,
            'source_status_label': source_status_label,
            'draft_box_verification_label': draft_box_verification_label,
            'source_url': source_url,
            'store_id': payload.get('store_id'),
            'store_name': payload.get('store_name'),
            'draft_box_verified': draft_box_verified,
        })

    def single_save_product_box_snapshot_error(
        self,
        task: dict[str, Any],
        product: dict[str, Any],
    ) -> str | None:
        if task.get('mode') != 'single_save':
            return 'task is not single_save'
        task_payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        product_payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
        jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
        try:
            _exact_positive_int(task.get('id'))
            task_store_id = _exact_positive_int(task.get('store_id'))
            product_id = _exact_positive_int(product.get('id'))
            product_store_id = _exact_positive_int(product_payload.get('store_id'))
            snapshot_product_id = _exact_positive_int(task_payload.get('product_box_product_id'))
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
        snapshot = task_payload.get('product_box_snapshot')
        if not isinstance(snapshot, dict):
            return 'product-box snapshot is missing'
        verification = verify_product_box_snapshot(snapshot)
        if verification.get('ok') is not True:
            return f"product-box snapshot is invalid: {verification.get('reason_code')}"
        evidence_error = _product_box_evidence_integrity_error(snapshot.get('evidence_ref'))
        if evidence_error:
            return evidence_error
        if task_payload.get('product_box_snapshot_fingerprint') != snapshot.get('fingerprint'):
            return 'product-box snapshot fingerprint has drifted'
        if (
            snapshot.get('product_id') != product_id
            or snapshot.get('store_id') != product_store_id
            or snapshot.get('product_title') != product.get('title')
            or snapshot.get('product_status') != product.get('status')
        ):
            return 'product-box snapshot no longer matches the selected product'
        try:
            canonical_target = canonical_frozen_target_identity(
                snapshot.get('target_identity'),
                store_name=str(snapshot.get('store_name') or ''),
            )
        except Exception:
            return 'product-box frozen target identity is invalid'
        if canonical_target != snapshot.get('target_identity'):
            return 'product-box frozen target identity has drifted'
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
                allowed = {'store_name', 'category_name', 'execution_mode'}
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

    def try_claim_task_runner_dispatch(self, task_id: int) -> bool:
        """Claim one durable runner dispatch for a draft or API-started task."""

        claimed_at = now_iso()
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = conn.execute(
                'SELECT status, payload_json FROM tasks WHERE id=?',
                (task_id,),
            ).fetchone()
            if not task or task.get('status') not in {'draft', 'running'}:
                return False
            if self._active_edit_batch_exists(conn):
                return False
            if self._other_running_task_exists(conn, task_id):
                return False
            payload = loads(task['payload_json'], {})
            dispatch = payload.get('runner_dispatch')
            if isinstance(dispatch, dict) and dispatch.get('claimed') is True:
                return False
            next_payload = dict(payload)
            next_payload['runner_dispatch'] = {
                'schema': 'dxm.task-runner-dispatch.v1',
                'claimed': True,
                'claimed_at': claimed_at,
            }
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='running', payload_json=?, updated_at=?
                 WHERE id=? AND status=? AND payload_json=?
                """,
                (
                    dumps(next_payload),
                    claimed_at,
                    task_id,
                    task['status'],
                    task['payload_json'],
                ),
            )
            return updated.rowcount == 1

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
            compare_context = (
                compare_batch_authorization_context
                if str(task.get('mode') or '') == 'batch_draft_save'
                else compare_save_authorization_context
            )
            context_check = compare_context(stored_context, authorization_context)
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

    def approve_and_start_task_with_authorization(
        self,
        task_id: int,
        *,
        token: str,
        confirmation: str,
        approved_by: str,
        authorization_context: dict[str, Any],
        lease_id: str,
        issued_at: str,
        expires_at: str,
        consumed_at: str,
    ) -> AuthorizationLeaseResult:
        """Atomically issue, consume, and start one real-write task authorization."""

        try:
            issued = datetime.fromisoformat(str(issued_at).replace('Z', '+00:00'))
            expiry = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
            consumed = datetime.fromisoformat(str(consumed_at).replace('Z', '+00:00'))
            issued = issued if issued.tzinfo else issued.replace(tzinfo=timezone.utc)
            expiry = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
            consumed = consumed if consumed.tzinfo else consumed.replace(tzinfo=timezone.utc)
        except (AttributeError, TypeError, ValueError):
            return AuthorizationLeaseResult(False, 'AUTH_TIME_INVALID', self.get_task(task_id), None)
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(confirmation, str)
            or not confirmation
            or not isinstance(approved_by, str)
            or not approved_by.strip()
            or not isinstance(lease_id, str)
            or not lease_id.strip()
            or not isinstance(authorization_context, dict)
            or not authorization_context
        ):
            return AuthorizationLeaseResult(False, 'TASK_APPROVAL_INPUT_INVALID', self.get_task(task_id), None)
        if not (issued <= consumed < expiry) or (expiry - issued).total_seconds() > 5 * 60:
            return AuthorizationLeaseResult(False, 'TASK_APPROVAL_TIME_INVALID', self.get_task(task_id), None)

        next_approval = {
            'approved': True,
            'token_hash': hashlib.sha256(token.encode('utf-8')).hexdigest(),
            'approved_by': approved_by.strip(),
            'approved_at': issued_at,
            'source': 'server',
            'lease_id': lease_id,
            'confirmation': confirmation,
            'stage_task_facts': dict(authorization_context.get('stage_task_facts') or {}),
            'authorization_context': dict(authorization_context),
            'issued_at': issued_at,
            'expires_at': expires_at,
            'consumed': True,
            'consumed_at': consumed_at,
        }
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not task:
                return AuthorizationLeaseResult(False, 'AUTH_TASK_NOT_FOUND', None, None)
            if task.get('status') != 'draft':
                return AuthorizationLeaseResult(
                    False,
                    'AUTH_TASK_NOT_DRAFT',
                    self.get_task(task_id),
                    None,
                )
            if self._active_edit_batch_exists(conn):
                return AuthorizationLeaseResult(False, 'AUTH_EDIT_BATCH_ACTIVE', self.get_task(task_id), None)
            if self._other_running_task_exists(conn, task_id):
                return AuthorizationLeaseResult(False, 'AUTH_ANOTHER_TASK_ACTIVE', self.get_task(task_id), None)
            payload = loads(task['payload_json'], {})
            if isinstance(payload.get('manual_approval'), dict):
                return AuthorizationLeaseResult(
                    False,
                    'TASK_APPROVAL_ALREADY_ISSUED',
                    self.get_task(task_id),
                    None,
                )
            next_payload = dict(payload)
            next_payload['manual_approval'] = next_approval
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='running', payload_json=?, updated_at=?
                 WHERE id=? AND status='draft' AND payload_json=?
                """,
                (dumps(next_payload), consumed_at, task_id, task['payload_json']),
            )
            if updated.rowcount != 1:
                return AuthorizationLeaseResult(
                    False,
                    'AUTH_START_CAS_CONFLICT',
                    self.get_task(task_id),
                    None,
                )
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
        compare_context = (
            compare_batch_authorization_context
            if str(task.get('mode') or '') == 'batch_draft_save'
            else compare_save_authorization_context
        )
        context_check = compare_context(stored_context, authorization_context)
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
        """Backward-compatible alias: request pause (not yet worker-acked)."""
        return self.request_pause_task(task_id).ok

    def try_resume_task(self, task_id: int) -> bool:
        return self.request_resume_task(task_id).ok

    def get_task_worker_control(self, task_id: int) -> dict[str, Any] | None:
        task = self.get_task_private(task_id)
        if not task:
            return None
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        return normalize_worker_control(payload.get(WORKER_CONTROL_PAYLOAD_KEY))

    def request_pause_task(self, task_id: int, *, detail: str | None = None) -> TaskControlResult:
        now = now_iso()
        control = build_request_control(
            request="pause",
            requested_at=now,
            reason_code="OPERATOR_PAUSE_REQUESTED",
            detail=detail,
        )
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return TaskControlResult(False, "TASK_NOT_FOUND")
            status = str(row["status"] or "")
            if status == "pause_requested":
                existing = normalize_worker_control(
                    loads(row["payload_json"], {}).get(WORKER_CONTROL_PAYLOAD_KEY)
                )
                return TaskControlResult(
                    True,
                    "PAUSE_ALREADY_REQUESTED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status == "paused":
                existing = normalize_worker_control(
                    loads(row["payload_json"], {}).get(WORKER_CONTROL_PAYLOAD_KEY)
                )
                return TaskControlResult(
                    True,
                    "PAUSE_ALREADY_ACKED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status == "stop_requested":
                return TaskControlResult(False, "TASK_STOP_PENDING", status=status)
            if status != "running":
                return TaskControlResult(False, "TASK_NOT_RUNNING", status=status)
            payload = loads(row["payload_json"], {})
            next_payload = dict(payload)
            next_payload[WORKER_CONTROL_PAYLOAD_KEY] = control
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='pause_requested', payload_json=?, updated_at=?
                 WHERE id=? AND status='running' AND payload_json=?
                """,
                (dumps(next_payload), now, task_id, row["payload_json"]),
            )
            if updated.rowcount != 1:
                return TaskControlResult(False, "PAUSE_REQUEST_CAS_CONFLICT")
        return TaskControlResult(
            True,
            "OK",
            status="pause_requested",
            applied=True,
            worker_control=control,
        )

    def acknowledge_pause_task(
        self,
        task_id: int,
        *,
        completed_jobs: int | None = None,
        failed_jobs: int | None = None,
        detail: str | None = None,
    ) -> TaskControlResult:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, status, payload_json, completed_jobs, failed_jobs FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return TaskControlResult(False, "TASK_NOT_FOUND")
            status = str(row["status"] or "")
            payload = loads(row["payload_json"], {})
            if status == "paused":
                existing = normalize_worker_control(payload.get(WORKER_CONTROL_PAYLOAD_KEY))
                return TaskControlResult(
                    True,
                    "PAUSE_ALREADY_ACKED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status != "pause_requested":
                return TaskControlResult(False, "TASK_NOT_PAUSE_REQUESTED", status=status)
            control = build_ack_control(
                payload.get(WORKER_CONTROL_PAYLOAD_KEY),
                ack="paused",
                acked_at=now,
                reason_code="WORKER_PAUSE_ACKED",
                detail=detail or "worker acked pause at product safe point",
            )
            next_payload = dict(payload)
            next_payload[WORKER_CONTROL_PAYLOAD_KEY] = control
            next_payload["runner_dispatch"] = self._released_runner_dispatch(
                payload.get("runner_dispatch"),
                released_at=now,
                reason="pause_acked",
            )
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='paused',
                       payload_json=?,
                       completed_jobs=COALESCE(?, completed_jobs),
                       failed_jobs=COALESCE(?, failed_jobs),
                       updated_at=?
                 WHERE id=? AND status='pause_requested' AND payload_json=?
                """,
                (
                    dumps(next_payload),
                    completed_jobs,
                    failed_jobs,
                    now,
                    task_id,
                    row["payload_json"],
                ),
            )
            if updated.rowcount != 1:
                return TaskControlResult(False, "PAUSE_ACK_CAS_CONFLICT")
        return TaskControlResult(
            True,
            "OK",
            status="paused",
            applied=True,
            worker_control=control,
        )

    def request_resume_task(self, task_id: int, *, detail: str | None = None) -> TaskControlResult:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._active_edit_batch_exists(conn):
                return TaskControlResult(False, "AUTH_EDIT_BATCH_ACTIVE")
            if self._other_running_task_exists(conn, task_id):
                return TaskControlResult(False, "AUTH_ANOTHER_TASK_ACTIVE")
            row = conn.execute(
                "SELECT id, status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return TaskControlResult(False, "TASK_NOT_FOUND")
            status = str(row["status"] or "")
            if status != "paused":
                if status == "running":
                    return TaskControlResult(
                        False,
                        "TASK_ALREADY_RUNNING",
                        status=status,
                    )
                if status == "pause_requested":
                    return TaskControlResult(
                        False,
                        "PAUSE_ACK_REQUIRED",
                        status=status,
                    )
                return TaskControlResult(False, "TASK_NOT_PAUSED", status=status)
            payload = loads(row["payload_json"], {})
            control = empty_worker_control()
            control["reason_code"] = "OPERATOR_RESUME_REQUESTED"
            control["detail"] = " ".join(str(detail or "operator resume from paused").split())
            control["requested_at"] = now
            next_payload = dict(payload)
            next_payload[WORKER_CONTROL_PAYLOAD_KEY] = control
            next_payload["runner_dispatch"] = {
                "schema": "dxm.task-runner-dispatch.v1",
                "claimed": False,
                "released_at": now,
                "resume_requested_at": now,
            }
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='running', payload_json=?, updated_at=?
                 WHERE id=? AND status='paused' AND payload_json=?
                """,
                (dumps(next_payload), now, task_id, row["payload_json"]),
            )
            if updated.rowcount != 1:
                return TaskControlResult(False, "RESUME_CAS_CONFLICT")
        return TaskControlResult(
            True,
            "OK",
            status="running",
            applied=True,
            worker_control=control,
        )

    def request_stop_task(self, task_id: int, *, detail: str | None = None) -> TaskControlResult:
        now = now_iso()
        control = build_request_control(
            request="stop",
            requested_at=now,
            reason_code="OPERATOR_STOP_REQUESTED",
            detail=detail,
        )
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return TaskControlResult(False, "TASK_NOT_FOUND")
            status = str(row["status"] or "")
            if status == "stop_requested":
                existing = normalize_worker_control(
                    loads(row["payload_json"], {}).get(WORKER_CONTROL_PAYLOAD_KEY)
                )
                return TaskControlResult(
                    True,
                    "STOP_ALREADY_REQUESTED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status == "stopped":
                existing = normalize_worker_control(
                    loads(row["payload_json"], {}).get(WORKER_CONTROL_PAYLOAD_KEY)
                )
                return TaskControlResult(
                    True,
                    "STOP_ALREADY_ACKED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status not in {"running", "pause_requested", "paused"}:
                return TaskControlResult(False, "TASK_NOT_STOPPABLE", status=status)
            payload = loads(row["payload_json"], {})
            next_payload = dict(payload)
            next_payload[WORKER_CONTROL_PAYLOAD_KEY] = control
            updated = conn.execute(
                f"""
                UPDATE tasks
                   SET status='stop_requested', payload_json=?, updated_at=?
                 WHERE id=? AND status=? AND payload_json=?
                """,
                (dumps(next_payload), now, task_id, status, row["payload_json"]),
            )
            if updated.rowcount != 1:
                return TaskControlResult(False, "STOP_REQUEST_CAS_CONFLICT")
        return TaskControlResult(
            True,
            "OK",
            status="stop_requested",
            applied=True,
            worker_control=control,
        )

    def acknowledge_stop_task(
        self,
        task_id: int,
        *,
        completed_jobs: int | None = None,
        failed_jobs: int | None = None,
        detail: str | None = None,
    ) -> TaskControlResult:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return TaskControlResult(False, "TASK_NOT_FOUND")
            status = str(row["status"] or "")
            payload = loads(row["payload_json"], {})
            if status == "stopped":
                existing = normalize_worker_control(payload.get(WORKER_CONTROL_PAYLOAD_KEY))
                return TaskControlResult(
                    True,
                    "STOP_ALREADY_ACKED",
                    status=status,
                    applied=True,
                    idempotent=True,
                    worker_control=existing,
                )
            if status != "stop_requested":
                return TaskControlResult(False, "TASK_NOT_STOP_REQUESTED", status=status)
            control = build_ack_control(
                payload.get(WORKER_CONTROL_PAYLOAD_KEY),
                ack="stopped",
                acked_at=now,
                reason_code="WORKER_STOP_ACKED",
                detail=detail or "worker acked stop; no further products dispatched",
            )
            next_payload = dict(payload)
            next_payload[WORKER_CONTROL_PAYLOAD_KEY] = control
            next_payload["runner_dispatch"] = self._released_runner_dispatch(
                payload.get("runner_dispatch"),
                released_at=now,
                reason="stop_acked",
            )
            updated = conn.execute(
                """
                UPDATE tasks
                   SET status='stopped',
                       payload_json=?,
                       completed_jobs=COALESCE(?, completed_jobs),
                       failed_jobs=COALESCE(?, failed_jobs),
                       updated_at=?
                 WHERE id=? AND status='stop_requested' AND payload_json=?
                """,
                (
                    dumps(next_payload),
                    completed_jobs,
                    failed_jobs,
                    now,
                    task_id,
                    row["payload_json"],
                ),
            )
            if updated.rowcount != 1:
                return TaskControlResult(False, "STOP_ACK_CAS_CONFLICT")
            # Leave remaining pending jobs untouched so operators can audit the queue.
            conn.execute(
                """
                UPDATE jobs
                   SET current_step_code=COALESCE(current_step_code, 'STOPPED'),
                       current_step_name=COALESCE(current_step_name, '已停止，未派发'),
                       updated_at=?
                 WHERE task_id=? AND status='pending'
                """,
                (now, task_id),
            )
        return TaskControlResult(
            True,
            "OK",
            status="stopped",
            applied=True,
            worker_control=control,
        )

    def release_task_runner_dispatch(self, task_id: int, *, reason: str) -> bool:
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return False
            payload = loads(row["payload_json"], {})
            next_payload = dict(payload)
            next_payload["runner_dispatch"] = self._released_runner_dispatch(
                payload.get("runner_dispatch"),
                released_at=now,
                reason=reason,
            )
            updated = conn.execute(
                """
                UPDATE tasks
                   SET payload_json=?, updated_at=?
                 WHERE id=? AND payload_json=?
                """,
                (dumps(next_payload), now, task_id, row["payload_json"]),
            )
            return updated.rowcount == 1

    @staticmethod
    def _released_runner_dispatch(previous: Any, *, released_at: str, reason: str) -> dict[str, Any]:
        base = dict(previous) if isinstance(previous, dict) else {}
        return {
            "schema": "dxm.task-runner-dispatch.v1",
            "claimed": False,
            "released_at": released_at,
            "release_reason": reason,
            "previous_claimed_at": base.get("claimed_at"),
        }

    def public_task_worker_control(self, task: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(task, Mapping):
            return None
        payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        raw = payload.get(WORKER_CONTROL_PAYLOAD_KEY)
        if raw is None and str(task.get("status") or "") not in ACTIVE_TASK_STATUSES | {"stopped"}:
            return None
        return public_worker_control(raw)

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
                    "unknown",
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
                rows = conn.execute(
                    """
                    SELECT job_logs.*
                      FROM job_logs
                      JOIN tasks ON tasks.id=job_logs.task_id
                     WHERE tasks.mode!='removed_workflow_legacy'
                     ORDER BY job_logs.id DESC LIMIT 200
                    """
                ).fetchall()
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
                rows = conn.execute(
                    """
                    SELECT job_evidences.*
                      FROM job_evidences
                      JOIN tasks ON tasks.id=job_evidences.task_id
                     WHERE tasks.mode!='removed_workflow_legacy'
                     ORDER BY job_evidences.id DESC LIMIT 200
                    """
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_evidences WHERE task_id=? ORDER BY id DESC LIMIT 200", (task_id,)).fetchall()
            for row in rows:
                row['meta'] = loads(row.pop('meta_json'), {})
            return rows

    def prepare_real_dxm_write_scope(
        self,
        scope: Mapping[str, Any],
        *,
        purpose: str = "general",
        lineage_sha256: str | None = None,
        lineage_discovery_receipt_sha256: str | None = None,
        lineage_predecessor_scope_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Persist one already-validated external scope without consuming it."""

        normalized_lineage = _normalized_sha256(lineage_sha256)
        normalized_discovery = _normalized_sha256(
            lineage_discovery_receipt_sha256
        )
        normalized_predecessor = _normalized_sha256(
            lineage_predecessor_scope_sha256
        )
        if (
            purpose not in {"general", "discovery", "formal"}
            or (
                purpose == "formal"
                and None
                in {
                    normalized_lineage,
                    normalized_discovery,
                    normalized_predecessor,
                }
            )
            or (
                purpose != "formal"
                and any(
                    value is not None
                    for value in (
                        normalized_lineage,
                        normalized_discovery,
                        normalized_predecessor,
                    )
                )
            )
        ):
            return {
                "ok": False,
                "reason_code": "SCOPE_REJECTED",
                "detail_code": "FORMAL_LINEAGE_INVALID",
            }

        scope_sha256 = str(scope.get("scopeSha256") or "")
        snapshot = scope.get("snapshot") if isinstance(scope.get("snapshot"), Mapping) else {}
        account = scope.get("account") if isinstance(scope.get("account"), Mapping) else {}
        shop = scope.get("shop") if isinstance(scope.get("shop"), Mapping) else {}
        products = scope.get("orderedProducts") if isinstance(scope.get("orderedProducts"), list) else []
        task_id = int(snapshot.get("taskId") or 0)
        snapshot_id = int(snapshot.get("snapshotId") or 0)
        snapshot_sha256 = str(snapshot.get("snapshotSha256") or "")
        nonce = str(scope.get("nonce") or "")
        nonce_sha256 = hashlib.sha256(nonce.encode("utf-8")).hexdigest().upper()
        order_sha256 = canonical_sha256(
            [item.get("productId") for item in products if isinstance(item, Mapping)]
        )
        now = now_iso()
        scope_json = dumps(dict(scope))
        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT id, status FROM tasks WHERE id=? AND mode='batch_draft_save'",
                (task_id,),
            ).fetchone()
            if not task:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "TASK_NOT_FOUND"}
            if task["status"] != "draft":
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "TASK_NOT_DRAFT"}
            existing = conn.execute(
                "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                (scope_sha256,),
            ).fetchone()
            if existing:
                same = bool(
                    existing["scope_json"] == scope_json
                    and int(existing["task_id"]) == task_id
                    and existing["status"] == "prepared"
                    and str(existing.get("purpose") or "general") == purpose
                    and _normalized_sha256(existing.get("lineage_sha256"))
                    == normalized_lineage
                    and _normalized_sha256(
                        existing.get("lineage_discovery_receipt_sha256")
                    )
                    == normalized_discovery
                    and _normalized_sha256(
                        existing.get("lineage_predecessor_scope_sha256")
                    )
                    == normalized_predecessor
                )
                conn.execute("ROLLBACK")
                return {
                    "ok": same,
                    "reason_code": "OK" if same else "SCOPE_REJECTED",
                    "detail_code": "SCOPE_ALREADY_PREPARED" if same else "SCOPE_REPLAY_OR_DRIFT",
                    "scope_sha256": scope_sha256,
                    "status": existing["status"],
                }
            active = conn.execute(
                """
                SELECT * FROM real_dxm_write_scopes
                 WHERE task_id=? AND status='prepared'
                 ORDER BY id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if active:
                try:
                    active_expiry = datetime.fromisoformat(
                        str(active["expires_at"]).replace("Z", "+00:00")
                    )
                    if active_expiry.tzinfo is None:
                        active_expiry = active_expiry.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    active_expiry = None
                if active_expiry is None or datetime.now(timezone.utc) < active_expiry:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "reason_code": "SCOPE_REJECTED",
                        "detail_code": "TASK_ACTIVE_SCOPE_CONFLICT",
                        "scope_sha256": active["scope_sha256"],
                        "status": active["status"],
                    }
                conn.execute(
                    """
                    UPDATE real_dxm_write_scopes
                       SET status='expired', updated_at=?
                     WHERE id=? AND status='prepared'
                    """,
                    (now, active["id"]),
                )
            try:
                conn.execute(
                    """
                    INSERT INTO real_dxm_write_scopes (
                        scope_sha256, task_id, snapshot_id, snapshot_sha256,
                        account_ref_hash, shop_id, product_order_sha256,
                        scope_nonce_sha256, scope_json, expires_at, status,
                        purpose, lineage_sha256,
                        lineage_discovery_receipt_sha256,
                        lineage_predecessor_scope_sha256,
                        prepared_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scope_sha256,
                        task_id,
                        snapshot_id,
                        snapshot_sha256,
                        str(account.get("accountContextHash") or ""),
                        str(shop.get("shopId") or ""),
                        order_sha256,
                        nonce_sha256,
                        scope_json,
                        str(scope.get("expiresAt") or ""),
                        purpose,
                        normalized_lineage,
                        normalized_discovery,
                        normalized_predecessor,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "SCOPE_NONCE_REPLAY"}
            conn.execute("COMMIT")
        return {
            "ok": True,
            "reason_code": "OK",
            "scope_sha256": scope_sha256,
            "status": "prepared",
            "purpose": purpose,
            "lineage_sha256": normalized_lineage,
            "lineage_discovery_receipt_sha256": normalized_discovery,
            "lineage_predecessor_scope_sha256": normalized_predecessor,
        }

    def get_prepared_real_dxm_write_scope_for_task(
        self,
        task_id: int,
    ) -> dict[str, Any] | None:
        """Return the sole active prepared scope candidate for idempotent Prepare."""

        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            row = conn.execute(
                """
                SELECT * FROM real_dxm_write_scopes
                 WHERE task_id=? AND status='prepared'
                 ORDER BY id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["scope"] = loads(result.pop("scope_json"), {})
            return result

    def consume_real_dxm_write_approval(
        self,
        *,
        scope: Mapping[str, Any],
        approval: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Low-level persistence contract retained for isolated contract tests.

        The consume and task-payload binding share one SQLite transaction.  A
        later start failure leaves the approval consumed, which is fail-closed
        and requires a newly approved scope instead of replay.  No public API
        uses this partial operation; production Path B start must call
        :meth:`approve_and_start_real_dxm_path_b`.
        """

        scope_sha256 = str(scope.get("scopeSha256") or "")
        approval_sha256 = str(approval.get("approvalSha256") or "")
        snapshot = scope.get("snapshot") if isinstance(scope.get("snapshot"), Mapping) else {}
        task_id = int(snapshot.get("taskId") or 0)
        now = now_iso()
        try:
            real_authorization = _derive_real_dxm_write_authorization_binding(
                scope,
                approval,
                consumed_at=now,
            )
        except _RealDxmAuthorizationBindingError:
            return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "SAVE_LEASE_COUNT_INVALID"}
        approval_nonce_hash = real_authorization["approval_nonce_sha256"]
        save_leases = real_authorization["save_leases"]
        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                (scope_sha256,),
            ).fetchone()
            if not row or row["status"] != "prepared" or int(row["task_id"]) != task_id:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "SCOPE_NOT_PREPARED_OR_CONSUMED"}
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["status"] != "draft":
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "TASK_NOT_DRAFT"}
            payload = loads(task["payload_json"], {})
            if not isinstance(payload, dict) or payload.get("real_dxm_write_authorization") is not None:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "TASK_SCOPE_ALREADY_BOUND"}
            payload["real_dxm_write_authorization"] = real_authorization
            updated = conn.execute(
                """
                UPDATE real_dxm_write_scopes
                   SET status='consumed', approval_sha256=?,
                       approval_nonce_sha256=?, approval_stage=?,
                       approval_consumed_at=?, updated_at=?
                 WHERE scope_sha256=? AND status='prepared'
                """,
                (
                    approval_sha256,
                    approval_nonce_hash,
                    str(approval.get("stage") or ""),
                    now,
                    now,
                    scope_sha256,
                ),
            )
            if updated.rowcount != 1:
                conn.execute("ROLLBACK")
                return {"ok": False, "reason_code": "SCOPE_REJECTED", "detail_code": "APPROVAL_REPLAY"}
            conn.execute(
                "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=? AND status='draft'",
                (dumps(payload), now, task_id),
            )
            conn.execute("COMMIT")
        return {
            "ok": True,
            "reason_code": "OK",
            "scope_sha256": scope_sha256,
            "approval_sha256": approval_sha256,
            "save_leases": save_leases,
        }

    def approve_and_start_real_dxm_path_b(
        self,
        task_id: int,
        *,
        scope: Mapping[str, Any],
        approval: Mapping[str, Any],
        token: str,
        confirmation: str,
        approved_by: str,
        lease_id: str,
        predecessor_scope_sha256: str | None = None,
        discovery_receipt_sha256: str | None = None,
        _discovery_context: Mapping[str, Any] | None = None,
    ) -> AuthorizationLeaseResult:
        """Consume the external approval and start Path B in one transaction.

        No scope, task payload, or manual-approval state is committed unless
        every invariant and both compare-and-swap updates succeed.  In
        particular, an approval can no longer be stranded as ``consumed`` on a
        draft task when the subsequent task start fails.
        """

        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id <= 0
            or not isinstance(token, str)
            or not token
            or confirmation != BATCH_DRAFT_SAVE_CONFIRMATION
            or not isinstance(approved_by, str)
            or not approved_by.strip()
            or not isinstance(lease_id, str)
            or not lease_id.strip()
        ):
            return AuthorizationLeaseResult(
                False,
                "TASK_APPROVAL_INPUT_INVALID",
                self.get_task(task_id) if isinstance(task_id, int) and task_id > 0 else None,
                None,
            )

        discovery_context: dict[str, Any] | None = None
        raw_predecessor = (
            predecessor_scope_sha256.strip()
            if isinstance(predecessor_scope_sha256, str)
            else ""
        )
        raw_discovery_receipt = (
            discovery_receipt_sha256.strip()
            if isinstance(discovery_receipt_sha256, str)
            else ""
        )
        formal_lineage_requested = bool(
            raw_predecessor and raw_discovery_receipt
        )
        normalized_predecessor = _normalized_sha256(raw_predecessor)
        normalized_discovery_receipt = _normalized_sha256(
            raw_discovery_receipt
        )
        if (
            bool(raw_predecessor) != bool(raw_discovery_receipt)
            or (
                formal_lineage_requested
                and (
                    normalized_predecessor is None
                    or normalized_discovery_receipt is None
                    or normalized_predecessor
                    == normalized_discovery_receipt
                )
            )
        ):
            return AuthorizationLeaseResult(
                False,
                "FORMAL_LINEAGE_INPUT_INVALID",
                self.get_task(task_id),
                None,
            )
        if _discovery_context is not None:
            if formal_lineage_requested:
                return AuthorizationLeaseResult(
                    False,
                    "DISCOVERY_FORMAL_LINEAGE_FORBIDDEN",
                    self.get_task(task_id),
                    None,
                )
            if not isinstance(_discovery_context, Mapping) or set(
                _discovery_context
            ) != {
                "target_product_id",
                "discovery_key_sha256",
                "request_sha256",
            }:
                return AuthorizationLeaseResult(
                    False,
                    "DISCOVERY_START_INPUT_INVALID",
                    self.get_task(task_id),
                    None,
                )
            target_product_id = _discovery_context.get("target_product_id")
            discovery_key_sha256 = _normalized_sha256(
                _discovery_context.get("discovery_key_sha256")
            )
            request_sha256 = _normalized_sha256(
                _discovery_context.get("request_sha256")
            )
            if (
                isinstance(target_product_id, bool)
                or not isinstance(target_product_id, int)
                or target_product_id <= 0
                or discovery_key_sha256 is None
                or request_sha256 is None
            ):
                return AuthorizationLeaseResult(
                    False,
                    "DISCOVERY_START_INPUT_INVALID",
                    self.get_task(task_id),
                    None,
                )
            discovery_context = {
                "target_product_id": target_product_id,
                "discovery_key_sha256": discovery_key_sha256,
                "request_sha256": request_sha256,
            }
        if discovery_context is None and not formal_lineage_requested:
            return AuthorizationLeaseResult(
                False,
                "FORMAL_LINEAGE_REQUIRED",
                self.get_task(task_id),
                None,
            )

        next_approval: dict[str, Any] | None = None
        try:
            with connection() as conn:
                migrate_real_dxm_write_scopes(conn)
                if discovery_context is not None or formal_lineage_requested:
                    migrate_real_dxm_path_b_discovery_receipts(conn)
                conn.execute("BEGIN IMMEDIATE")
                transaction_time = datetime.now(timezone.utc)
                transaction_time_text = transaction_time.isoformat()
                try:
                    authorization = validate_real_dxm_write_authorization(
                        scope=scope,
                        approval=approval,
                        now=transaction_time,
                    )
                except RealDxmWriteScopeError as exc:
                    raise _AtomicPathBStartRejected(exc.detail_code) from exc
                canonical_scope = authorization["scope"]
                canonical_approval = authorization["approval"]
                snapshot = canonical_scope["snapshot"]
                if snapshot["taskId"] != task_id:
                    raise _AtomicPathBStartRejected("SCOPE_TASK_MISMATCH")
                if not hmac.compare_digest(
                    canonical_approval["approvedBy"].encode("utf-8"),
                    approved_by.strip().encode("utf-8"),
                ):
                    raise _AtomicPathBStartRejected("APPROVER_MISMATCH")

                try:
                    real_authorization = _derive_real_dxm_write_authorization_binding(
                        canonical_scope,
                        canonical_approval,
                        consumed_at=transaction_time_text,
                    )
                except _RealDxmAuthorizationBindingError as exc:
                    raise _AtomicPathBStartRejected(exc.reason_code) from exc

                scope_sha256 = canonical_scope["scopeSha256"]
                stored_scope_json = dumps(canonical_scope)
                scope_row = conn.execute(
                    "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                    (scope_sha256,),
                ).fetchone()
                expected_order_sha256 = canonical_sha256(
                    [item["productId"] for item in canonical_scope["orderedProducts"]]
                )
                expected_scope_nonce_sha256 = hashlib.sha256(
                    canonical_scope["nonce"].encode("utf-8")
                ).hexdigest().upper()
                if (
                    not scope_row
                    or scope_row["status"] != "prepared"
                    or int(scope_row["task_id"]) != task_id
                    or scope_row["scope_json"] != stored_scope_json
                    or int(scope_row["snapshot_id"]) != snapshot["snapshotId"]
                    or scope_row["snapshot_sha256"] != snapshot["snapshotSha256"]
                    or scope_row["account_ref_hash"]
                    != canonical_scope["account"]["accountContextHash"]
                    or int(scope_row["shop_id"]) != canonical_scope["shop"]["shopId"]
                    or scope_row["product_order_sha256"] != expected_order_sha256
                    or scope_row["scope_nonce_sha256"] != expected_scope_nonce_sha256
                    or scope_row["expires_at"] != canonical_scope["expiresAt"]
                ):
                    raise _AtomicPathBStartRejected("SCOPE_NOT_PREPARED_OR_CONSUMED")
                if discovery_context is not None and (
                    str(scope_row.get("purpose") or "general")
                    not in {"general", "discovery"}
                    or scope_row.get("lineage_discovery_receipt_sha256") is not None
                    or scope_row.get("lineage_predecessor_scope_sha256") is not None
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SCOPE_PURPOSE_INVALID"
                    )
                formal_lineage: dict[str, Any] | None = None
                if formal_lineage_requested:
                    if (
                        str(scope_row.get("purpose") or "") != "formal"
                        or _normalized_sha256(
                            scope_row.get(
                                "lineage_discovery_receipt_sha256"
                            )
                        )
                        != normalized_discovery_receipt
                        or _normalized_sha256(
                            scope_row.get(
                                "lineage_predecessor_scope_sha256"
                            )
                        )
                        != normalized_predecessor
                        or _normalized_sha256(
                            scope_row.get("lineage_sha256")
                        )
                        is None
                        or scope_sha256 == normalized_predecessor
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_LINEAGE_SCOPE_MISMATCH"
                        )
                    discovery_attempt = conn.execute(
                        """
                        SELECT * FROM real_dxm_path_b_discovery_attempts
                         WHERE discovery_receipt_sha256=? AND status='sealed'
                        """,
                        (normalized_discovery_receipt,),
                    ).fetchone()
                    discovery_receipt_row = conn.execute(
                        """
                        SELECT * FROM real_dxm_path_b_discovery_receipts
                         WHERE discovery_receipt_sha256=? AND status='sealed'
                        """,
                        (normalized_discovery_receipt,),
                    ).fetchone()
                    predecessor_scope = conn.execute(
                        """
                        SELECT * FROM real_dxm_write_scopes
                         WHERE scope_sha256=?
                           AND status='discovery_sealed'
                           AND purpose='discovery'
                        """,
                        (normalized_predecessor,),
                    ).fetchone()
                    discovery_task_row = (
                        conn.execute(
                            """
                            SELECT * FROM tasks WHERE id=?
                            """,
                            (discovery_attempt["task_id"],),
                        ).fetchone()
                        if discovery_attempt
                        else None
                    )
                    if (
                        not discovery_attempt
                        or not discovery_receipt_row
                        or not predecessor_scope
                        or not discovery_task_row
                        or str(discovery_task_row.get("status") or "")
                        != "stopped"
                        or int(
                            discovery_receipt_row.get("attempt_id") or 0
                        )
                        != int(discovery_attempt.get("id") or 0)
                        or _normalized_sha256(
                            discovery_attempt.get("scope_sha256")
                        )
                        != normalized_predecessor
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_RECEIPT_NOT_SEALED"
                        )
                    discovery_task_payload = loads(
                        discovery_task_row.get("payload_json"), None
                    )
                    try:
                        discovery_profile = (
                            validate_path_b_save1_discovery_profile(
                                discovery_task_payload.get(
                                    PATH_B_SAVE1_DISCOVERY_PROFILE_KEY
                                )
                                if isinstance(
                                    discovery_task_payload, Mapping
                                )
                                else None
                            )
                        )
                    except BatchCommandContractError as exc:
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_PROFILE_INVALID"
                        ) from exc
                    if (
                        canonical_contract_sha256(discovery_profile)
                        != _normalized_sha256(
                            discovery_attempt.get("profile_sha256")
                        )
                        or discovery_profile["target_task_id"]
                        != int(discovery_attempt["task_id"])
                        or discovery_profile["target_product_id"]
                        != int(discovery_attempt.get("product_id") or 0)
                        or discovery_profile["scope_sha256"]
                        != normalized_predecessor
                        or discovery_profile["discovery_key_sha256"]
                        != _normalized_sha256(
                            discovery_attempt.get(
                                "discovery_key_sha256"
                            )
                        )
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_PROFILE_INVALID"
                        )
                    discovery_receipt = loads(
                        discovery_receipt_row.get("receipt_json"), None
                    )
                    if not isinstance(discovery_receipt, Mapping):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_RECEIPT_INVALID"
                        )
                    receipt_body = {
                        key: value
                        for key, value in discovery_receipt.items()
                        if key != "discovery_receipt_sha256"
                    }
                    recomputed_receipt_sha256 = canonical_contract_sha256(
                        receipt_body
                    )
                    if (
                        discovery_receipt.get("schema_version")
                        != _PATH_B_DISCOVERY_RECEIPT_SCHEMA
                        or _normalized_sha256(
                            discovery_receipt.get(
                                "discovery_receipt_sha256"
                            )
                        )
                        != normalized_discovery_receipt
                        or recomputed_receipt_sha256
                        != normalized_discovery_receipt
                        or _normalized_sha256(
                            discovery_receipt_row.get(
                                "discovery_receipt_sha256"
                            )
                        )
                        != normalized_discovery_receipt
                        or _normalized_sha256(
                            discovery_attempt.get(
                                "discovery_receipt_sha256"
                            )
                        )
                        != normalized_discovery_receipt
                        or _normalized_sha256(
                            discovery_receipt.get("scope_sha256")
                        )
                        != normalized_predecessor
                        or int(discovery_receipt.get("task_id") or 0)
                        != int(discovery_attempt.get("task_id") or 0)
                        or int(discovery_receipt.get("job_id") or 0)
                        != int(discovery_attempt.get("job_id") or 0)
                        or int(discovery_receipt.get("product_id") or 0)
                        != int(discovery_attempt.get("product_id") or 0)
                        or _normalized_sha256(
                            discovery_receipt.get("profile_sha256")
                        )
                        != _normalized_sha256(
                            discovery_attempt.get("profile_sha256")
                        )
                        or _normalized_sha256(
                            discovery_receipt.get(
                                "discovery_key_sha256"
                            )
                        )
                        != _normalized_sha256(
                            discovery_attempt.get(
                                "discovery_key_sha256"
                            )
                        )
                        or discovery_receipt.get(
                            "physical_mutation_count"
                        )
                        != 1
                        or discovery_receipt.get("save1_count") != 1
                        or discovery_receipt.get("save2_count") != 0
                        or discovery_receipt.get(
                            "other_product_mutation_count"
                        )
                        != 0
                        or discovery_receipt.get("publish_request_count")
                        != 0
                        or discovery_receipt.get("published") is not False
                        or discovery_receipt.get("unknown_count") != 0
                        or int(
                            discovery_receipt_row.get("task_id") or 0
                        )
                        != int(discovery_receipt.get("task_id") or 0)
                        or int(
                            discovery_receipt_row.get("job_id") or 0
                        )
                        != int(discovery_receipt.get("job_id") or 0)
                        or int(
                            discovery_receipt_row.get("product_id") or 0
                        )
                        != int(discovery_receipt.get("product_id") or 0)
                        or _normalized_sha256(
                            discovery_receipt_row.get("scope_sha256")
                        )
                        != _normalized_sha256(
                            discovery_receipt.get("scope_sha256")
                        )
                        or _normalized_sha256(
                            discovery_receipt_row.get("profile_sha256")
                        )
                        != _normalized_sha256(
                            discovery_receipt.get("profile_sha256")
                        )
                        or _normalized_sha256(
                            discovery_receipt_row.get(
                                "field_readbacks_sha256"
                            )
                        )
                        != _normalized_sha256(
                            discovery_receipt.get(
                                "field_readbacks_sha256"
                            )
                        )
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_RECEIPT_INVALID"
                        )
                    try:
                        self._validate_sealed_discovery_authority(
                            conn,
                            attempt=discovery_attempt,
                            receipt_row=discovery_receipt_row,
                            receipt=discovery_receipt,
                        )
                    except (TypeError, ValueError) as exc:
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_AUTHORITY_DRIFT"
                        ) from exc
                    predecessor_scope_payload = loads(
                        predecessor_scope.get("scope_json"), None
                    )
                    if not isinstance(predecessor_scope_payload, Mapping):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_PREDECESSOR_SCOPE_INVALID"
                        )
                    try:
                        rebuilt_discovery_attempt_identity = (
                            canonical_contract_sha256(
                                {
                                    "schema": "dxm.real-dxm-path-b.discovery-attempt-identity.v1",
                                    "discovery_key_sha256": discovery_profile[
                                        "discovery_key_sha256"
                                    ],
                                    "task_id": int(
                                        discovery_attempt["task_id"]
                                    ),
                                    "snapshot_sha256": predecessor_scope_payload[
                                        "snapshot"
                                    ]["snapshotSha256"],
                                    "scope_sha256": normalized_predecessor,
                                    "approval_sha256": discovery_profile[
                                        "approval_sha256"
                                    ],
                                    "target_product_ordinal": 1,
                                    "target_product_id": discovery_profile[
                                        "target_product_id"
                                    ],
                                    "profile_sha256": canonical_contract_sha256(
                                        discovery_profile
                                    ),
                                    "account_ref_hash": predecessor_scope_payload[
                                        "account"
                                    ]["accountContextHash"],
                                    "shop_id": predecessor_scope_payload[
                                        "shop"
                                    ]["shopId"],
                                    "runtime_instance_id": predecessor_scope_payload[
                                        "runtime"
                                    ]["runtimeInstanceId"],
                                    "browser_session_id": predecessor_scope_payload[
                                        "runtime"
                                    ]["browserSessionId"],
                                    "git_head": predecessor_scope_payload[
                                        "git"
                                    ]["head"],
                                    "worktree": predecessor_scope_payload[
                                        "worktree"
                                    ],
                                }
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_ATTEMPT_IDENTITY_INVALID"
                        ) from exc
                    if rebuilt_discovery_attempt_identity != _normalized_sha256(
                        discovery_attempt.get("attempt_identity_sha256")
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_ATTEMPT_IDENTITY_INVALID"
                        )
                    try:
                        discovery_readbacks = [
                            item.to_dict()
                            for item in validated_field_readbacks_from_payload(
                                discovery_receipt.get("field_readbacks"),
                                require_nonempty=True,
                                reason_prefix="DISCOVERY_SAVE1",
                            )
                        ]
                    except ReceiptValidationError as exc:
                        raise _AtomicPathBStartRejected(exc.reason_code) from exc
                    discovery_plan = (
                        discovery_task_payload.get("plan_snapshot")
                        if isinstance(discovery_task_payload, Mapping)
                        else None
                    )
                    discovery_items = (
                        discovery_plan.get("item_snapshots")
                        if isinstance(discovery_plan, Mapping)
                        else None
                    )
                    matching_discovery_items = [
                        item
                        for item in discovery_items or []
                        if isinstance(item, Mapping)
                        and str(item.get("product_id") or "")
                        == str(discovery_profile["target_product_id"])
                    ]
                    discovery_stage_facts = (
                        matching_discovery_items[0].get(
                            "real_write_stage_facts"
                        )
                        if len(matching_discovery_items) == 1
                        and isinstance(
                            matching_discovery_items[0].get(
                                "real_write_stage_facts"
                            ),
                            Mapping,
                        )
                        else None
                    )
                    discovery_save1_facts = (
                        discovery_stage_facts.get("SAVE1")
                        if isinstance(discovery_stage_facts, Mapping)
                        else None
                    )
                    discovery_expected_after = (
                        {
                            str(item.get("field_key") or ""):
                            _normalized_sha256(
                                item.get("expected_sha256")
                            )
                            for item in discovery_save1_facts
                            if isinstance(item, Mapping)
                        }
                        if isinstance(discovery_save1_facts, list)
                        and discovery_save1_facts
                        else None
                    )
                    discovery_actual_after = {
                        str(item["field_key"]): canonical_contract_sha256(
                            item.get("after_value")
                        )
                        for item in discovery_readbacks
                    }
                    if (
                        not isinstance(discovery_expected_after, dict)
                        or "" in discovery_expected_after
                        or None in discovery_expected_after.values()
                        or discovery_expected_after
                        != discovery_actual_after
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_READBACK_AUTHORITY_DRIFT"
                        )
                    discovery_order = discovery_receipt.get(
                        "ordered_product_ids"
                    )
                    formal_order = [
                        item["productId"]
                        for item in canonical_scope["orderedProducts"]
                    ]
                    identity_pairs = (
                        (
                            canonical_scope["account"][
                                "accountContextHash"
                            ],
                            discovery_receipt.get("account_ref_hash"),
                        ),
                        (
                            canonical_scope["shop"]["shopId"],
                            discovery_receipt.get("shop_id"),
                        ),
                        (
                            canonical_scope["shop"]["shopName"],
                            discovery_receipt.get("shop_name"),
                        ),
                        (
                            canonical_scope["git"]["head"],
                            discovery_receipt.get("git_head"),
                        ),
                        (
                            canonical_scope["worktree"],
                            discovery_receipt.get("worktree"),
                        ),
                        (
                            canonical_scope["runtime"],
                            discovery_receipt.get("runtime"),
                        ),
                        (formal_order, discovery_order),
                        (
                            predecessor_scope_payload["account"][
                                "accountContextHash"
                            ],
                            discovery_receipt.get("account_ref_hash"),
                        ),
                        (
                            predecessor_scope_payload["shop"]["shopId"],
                            discovery_receipt.get("shop_id"),
                        ),
                        (
                            predecessor_scope_payload["shop"]["shopName"],
                            discovery_receipt.get("shop_name"),
                        ),
                        (
                            predecessor_scope_payload["git"]["head"],
                            discovery_receipt.get("git_head"),
                        ),
                        (
                            predecessor_scope_payload["worktree"],
                            discovery_receipt.get("worktree"),
                        ),
                        (
                            predecessor_scope_payload["runtime"],
                            discovery_receipt.get("runtime"),
                        ),
                    )
                    if (
                        len(formal_order) != 3
                        or len(set(formal_order)) != 3
                        or any(
                            observed != expected
                            for observed, expected in identity_pairs
                        )
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_IDENTITY_DRIFT"
                        )
                    if (
                        int(discovery_receipt.get("task_id") or 0)
                        == task_id
                        or int(
                            discovery_receipt.get("snapshot_id") or 0
                        )
                        == int(snapshot["snapshotId"])
                        or _normalized_sha256(
                            discovery_receipt.get("snapshot_sha256")
                        )
                        == _normalized_sha256(snapshot["snapshotSha256"])
                        or _normalized_sha256(
                            discovery_receipt.get("approval_sha256")
                        )
                        == _normalized_sha256(
                            canonical_approval["approvalSha256"]
                        )
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_TASK_SNAPSHOT_APPROVAL_NOT_FRESH"
                        )
                    first_product = canonical_scope["orderedProducts"][0]
                    formal_save1_preimages = {
                        str(item.get("field") or ""): _normalized_sha256(
                            item.get("preimageSha256")
                        )
                        for item in first_product.get("allowedFields", [])
                        if isinstance(item, Mapping)
                        and item.get("saveStage") == "SAVE1"
                    }
                    discovery_after_values = {
                        str(item["field_key"]): canonical_contract_sha256(
                            item.get("after_value")
                        )
                        for item in discovery_readbacks
                    }
                    if (
                        not formal_save1_preimages
                        or "" in formal_save1_preimages
                        or None in formal_save1_preimages.values()
                        or formal_save1_preimages
                        != discovery_after_values
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_DISCOVERY_PREIMAGE_MISMATCH"
                        )
                    formal_lineage_hash_body = {
                        "schemaVersion": PATH_B_FORMAL_LINEAGE_SCHEMA,
                        "predecessorScopeSha256": normalized_predecessor,
                        "discoveryReceiptSha256": (
                            normalized_discovery_receipt
                        ),
                        "formalScopeSha256": scope_sha256,
                        "formalTaskId": task_id,
                        "formalSnapshotId": snapshot["snapshotId"],
                        "formalSnapshotSha256": snapshot[
                            "snapshotSha256"
                        ],
                    }
                    formal_lineage_sha256 = canonical_contract_sha256(
                        formal_lineage_hash_body
                    )
                    if formal_lineage_sha256 != _normalized_sha256(
                        scope_row.get("lineage_sha256")
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_LINEAGE_HASH_MISMATCH"
                        )
                    try:
                        formal_lineage = validate_path_b_formal_lineage(
                            {
                                "schema": PATH_B_FORMAL_LINEAGE_SCHEMA,
                                "predecessor_scope_sha256": (
                                    normalized_predecessor
                                ),
                                "discovery_receipt_sha256": (
                                    normalized_discovery_receipt
                                ),
                                "formal_scope_sha256": scope_sha256,
                                "lineage_sha256": formal_lineage_sha256,
                                "discovery_task_id": int(
                                    discovery_receipt["task_id"]
                                ),
                                "discovery_snapshot_id": int(
                                    discovery_receipt["snapshot_id"]
                                ),
                                "discovery_snapshot_sha256": (
                                    discovery_receipt[
                                        "snapshot_sha256"
                                    ]
                                ),
                                "formal_task_id": task_id,
                                "formal_snapshot_id": snapshot[
                                    "snapshotId"
                                ],
                                "formal_snapshot_sha256": snapshot[
                                    "snapshotSha256"
                                ],
                            }
                        )
                    except BatchCommandContractError as exc:
                        raise _AtomicPathBStartRejected(
                            exc.reason_code
                        ) from exc
                elif discovery_context is None and (
                    str(scope_row.get("purpose") or "general") == "formal"
                    or scope_row.get("lineage_sha256") is not None
                    or scope_row.get(
                        "lineage_discovery_receipt_sha256"
                    )
                    is not None
                    or scope_row.get("lineage_predecessor_scope_sha256")
                    is not None
                ):
                    raise _AtomicPathBStartRejected(
                        "FORMAL_LINEAGE_REQUIRED"
                    )

                task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not task:
                    raise _AtomicPathBStartRejected("AUTH_TASK_NOT_FOUND")
                if task["status"] != "draft":
                    raise _AtomicPathBStartRejected("AUTH_TASK_NOT_DRAFT")
                if task["mode"] != "batch_draft_save":
                    raise _AtomicPathBStartRejected("AUTH_TASK_MODE_MISMATCH")
                if task["publish_scene"] != BATCH_DRAFT_SAVE_PUBLISH_SCENE:
                    raise _AtomicPathBStartRejected("PUBLISH_SCENE_MISMATCH")
                if self._active_edit_batch_exists(conn):
                    raise _AtomicPathBStartRejected("AUTH_EDIT_BATCH_ACTIVE")
                if self._other_running_task_exists(conn, task_id):
                    raise _AtomicPathBStartRejected("AUTH_ANOTHER_TASK_ACTIVE")

                payload = loads(task["payload_json"], {})
                plan = payload.get("plan_snapshot") if isinstance(payload, dict) else None
                if not isinstance(payload, dict) or not isinstance(plan, Mapping):
                    raise _AtomicPathBStartRejected("BATCH_PLAN_SNAPSHOT_REQUIRED")
                frozen_row = conn.execute(
                    "SELECT * FROM plan_snapshots WHERE id=?",
                    (snapshot["snapshotId"],),
                ).fetchone()
                stored_plan = (
                    loads(frozen_row["snapshot_json"], {})
                    if frozen_row and isinstance(frozen_row.get("snapshot_json"), str)
                    else None
                )
                if (
                    not frozen_row
                    or int(frozen_row.get("task_id") or 0) != task_id
                    or frozen_row.get("snapshot_hash") != snapshot["snapshotSha256"]
                    or not isinstance(stored_plan, dict)
                    or dict(plan) != stored_plan
                ):
                    raise _AtomicPathBStartRejected("BATCH_PLAN_SNAPSHOT_EMBEDDED_DRIFT")
                if formal_lineage_requested:
                    def _formal_artifact_time(value: Any) -> datetime:
                        if not isinstance(value, str) or not value.strip():
                            raise ValueError("formal artifact timestamp is missing")
                        parsed = datetime.fromisoformat(
                            value.strip().replace("Z", "+00:00")
                        )
                        if parsed.tzinfo is None or parsed.utcoffset() is None:
                            raise ValueError(
                                "formal artifact timestamp must include a timezone"
                            )
                        return parsed.astimezone(timezone.utc)

                    try:
                        discovery_sealed_at = _formal_artifact_time(
                            discovery_receipt.get("sealed_at")
                        )
                        formal_snapshot_created_at = _formal_artifact_time(
                            frozen_row.get("created_at")
                        )
                        formal_task_created_at = _formal_artifact_time(
                            task.get("created_at")
                        )
                        formal_scope_issued_at = _formal_artifact_time(
                            canonical_scope.get("issuedAt")
                        )
                        formal_scope_prepared_at = _formal_artifact_time(
                            scope_row.get("prepared_at")
                        )
                        formal_approval_approved_at = _formal_artifact_time(
                            canonical_approval.get("approvedAt")
                        )
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise _AtomicPathBStartRejected(
                            "FORMAL_ARTIFACTS_NOT_AFTER_DISCOVERY"
                        ) from exc
                    formal_artifact_times = (
                        formal_snapshot_created_at,
                        formal_task_created_at,
                        formal_scope_issued_at,
                        formal_scope_prepared_at,
                        formal_approval_approved_at,
                    )
                    scope_clock_precision_drift = (
                        formal_scope_issued_at - formal_scope_prepared_at
                    )
                    if (
                        any(
                            timestamp <= discovery_sealed_at
                            for timestamp in formal_artifact_times
                        )
                        or formal_snapshot_created_at > formal_task_created_at
                        or formal_task_created_at
                        > min(
                            formal_scope_issued_at,
                            formal_scope_prepared_at,
                        )
                        or (
                            formal_scope_prepared_at < formal_scope_issued_at
                            and scope_clock_precision_drift
                            >= timedelta(seconds=1)
                        )
                        or max(
                            formal_scope_issued_at,
                            formal_scope_prepared_at,
                        )
                        > formal_approval_approved_at
                        or formal_approval_approved_at > transaction_time
                    ):
                        raise _AtomicPathBStartRejected(
                            "FORMAL_ARTIFACTS_NOT_AFTER_DISCOVERY"
                        )
                if payload.get("real_dxm_write_authorization") is not None:
                    raise _AtomicPathBStartRejected("TASK_SCOPE_ALREADY_BOUND")
                if isinstance(payload.get("manual_approval"), Mapping):
                    raise _AtomicPathBStartRejected("TASK_APPROVAL_ALREADY_ISSUED")
                ordered_product_ids = real_authorization["ordered_product_ids"]
                job_rows = conn.execute(
                    "SELECT * FROM jobs WHERE task_id=? ORDER BY id",
                    (task_id,),
                ).fetchall()
                job_product_ids = [int(row["product_id"]) for row in job_rows]
                plan_session = (
                    plan.get("session_context")
                    if isinstance(plan.get("session_context"), Mapping)
                    else {}
                )
                if (
                    str(payload.get("path") or "").strip().upper() != "B"
                    or str(plan.get("path") or "").strip().upper() != "B"
                    or payload.get("publish_allowed") is not False
                    or plan.get("publish_allowed") is not False
                    or int(task.get("store_id") or 0) != canonical_scope["shop"]["shopId"]
                    or int(payload.get("plan_snapshot_id") or 0) != snapshot["snapshotId"]
                    or str(payload.get("plan_snapshot_hash") or "").upper()
                    != snapshot["snapshotSha256"]
                    or str(plan.get("snapshot_hash") or "").upper()
                    != snapshot["snapshotSha256"]
                    or str(plan_session.get("account_ref_hash") or "")
                    != canonical_scope["account"]["accountContextHash"]
                    or int(plan_session.get("shop_id") or 0)
                    != canonical_scope["shop"]["shopId"]
                    or str(plan_session.get("shop_name") or "")
                    != canonical_scope["shop"]["shopName"]
                    or payload.get("product_ids") != ordered_product_ids
                    or job_product_ids != ordered_product_ids
                    or int(task.get("total_jobs") or 0) != len(ordered_product_ids)
                ):
                    raise _AtomicPathBStartRejected("TASK_SCOPE_BINDING_MISMATCH")
                if discovery_context is not None and (
                    len(ordered_product_ids) != 3
                    or len(job_rows) != 3
                    or len(set(job_product_ids)) != 3
                    or any(str(row.get("status") or "") != "pending" for row in job_rows)
                    or int(task.get("completed_jobs") or 0) != 0
                    or int(task.get("failed_jobs") or 0) != 0
                ):
                    raise _AtomicPathBStartRejected("DISCOVERY_QUEUE_INVALID")
                if formal_lineage_requested and (
                    len(ordered_product_ids) != 3
                    or len(job_rows) != 3
                    or len(set(job_product_ids)) != 3
                    or any(
                        str(row.get("status") or "") != "pending"
                        for row in job_rows
                    )
                    or int(task.get("completed_jobs") or 0) != 0
                    or int(task.get("failed_jobs") or 0) != 0
                ):
                    raise _AtomicPathBStartRejected(
                        "FORMAL_QUEUE_INVALID"
                    )

                discovery_profile: dict[str, Any] | None = None
                discovery_profile_sha256: str | None = None
                discovery_attempt_identity_sha256: str | None = None
                discovery_save1_lease_id: str | None = None
                if discovery_context is not None:
                    profile_payload = dict(payload)
                    profile_payload["real_dxm_write_authorization"] = real_authorization
                    profile_task = dict(task)
                    profile_task["payload"] = profile_payload
                    profile_task["jobs"] = [dict(row) for row in job_rows]
                    try:
                        discovery_profile = build_path_b_save1_discovery_profile(
                            profile_task,
                            target_product_id=discovery_context[
                                "target_product_id"
                            ],
                            scope_sha256=scope_sha256,
                            approval_sha256=canonical_approval["approvalSha256"],
                            discovery_key_sha256=discovery_context[
                                "discovery_key_sha256"
                            ],
                        )
                    except BatchCommandContractError as exc:
                        raise _AtomicPathBStartRejected(exc.reason_code) from exc
                    discovery_profile_sha256 = canonical_contract_sha256(
                        discovery_profile
                    )
                    save1_leases = [
                        item
                        for item in real_authorization["save_leases"]
                        if isinstance(item, Mapping)
                        and item.get("product_id")
                        == discovery_profile["target_product_id"]
                        and item.get("product_ordinal") == 1
                        and item.get("save_stage") == "SAVE1"
                    ]
                    if len(save1_leases) != 1:
                        raise _AtomicPathBStartRejected(
                            "DISCOVERY_SAVE1_LEASE_INVALID"
                        )
                    discovery_save1_lease_id = str(
                        save1_leases[0].get("lease_id") or ""
                    )
                    if not discovery_save1_lease_id:
                        raise _AtomicPathBStartRejected(
                            "DISCOVERY_SAVE1_LEASE_INVALID"
                        )
                    discovery_attempt_identity_sha256 = canonical_contract_sha256(
                        {
                            "schema": "dxm.real-dxm-path-b.discovery-attempt-identity.v1",
                            "discovery_key_sha256": discovery_context[
                                "discovery_key_sha256"
                            ],
                            "task_id": task_id,
                            "snapshot_sha256": snapshot["snapshotSha256"],
                            "scope_sha256": scope_sha256,
                            "approval_sha256": canonical_approval[
                                "approvalSha256"
                            ],
                            "target_product_ordinal": 1,
                            "target_product_id": discovery_profile[
                                "target_product_id"
                            ],
                            "profile_sha256": discovery_profile_sha256,
                            "account_ref_hash": canonical_scope["account"][
                                "accountContextHash"
                            ],
                            "shop_id": canonical_scope["shop"]["shopId"],
                            "runtime_instance_id": canonical_scope["runtime"][
                                "runtimeInstanceId"
                            ],
                            "browser_session_id": canonical_scope["runtime"][
                                "browserSessionId"
                            ],
                            "git_head": canonical_scope["git"]["head"],
                            "worktree": canonical_scope["worktree"],
                        }
                    )

                try:
                    stage_task_facts = build_batch_draft_save_task_facts(
                        task_id=task_id,
                        store_id=int(task["store_id"]),
                        product_ids=ordered_product_ids,
                        plan_snapshot_id=snapshot["snapshotId"],
                        plan_snapshot_hash=snapshot["snapshotSha256"],
                        path="B",
                        real_authorization=real_authorization,
                    )
                    authorization_context = build_batch_authorization_context(
                        stage_task_facts=stage_task_facts,
                        runtime_instance_id=canonical_scope["runtime"]["runtimeInstanceId"],
                        browser_session_id=canonical_scope["runtime"]["browserSessionId"],
                        git_head=canonical_scope["git"]["head"],
                        worktree_identity=canonical_scope["worktree"],
                        l2_evidence_fingerprint=canonical_scope["l2"]["evidenceFingerprint"],
                        approved_by=canonical_approval["approvedBy"],
                    )
                except BatchDraftAuthorizationError as exc:
                    raise _AtomicPathBStartRejected(exc.reason_code) from exc
                context_check = verify_batch_authorization_context(authorization_context)
                if context_check.get("ok") is not True:
                    raise _AtomicPathBStartRejected(
                        str(context_check.get("reason_code") or "AUTH_CONTEXT_MISMATCH")
                    )

                approval_expiry = datetime.fromisoformat(
                    canonical_approval["expiresAt"].replace("Z", "+00:00")
                )
                manual_expiry = min(
                    transaction_time + timedelta(minutes=5),
                    approval_expiry,
                )
                if manual_expiry <= transaction_time:
                    raise _AtomicPathBStartRejected("APPROVAL_EXPIRED")
                next_approval = {
                    "approved": True,
                    "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    "approved_by": canonical_approval["approvedBy"],
                    "approved_at": canonical_approval["approvedAt"],
                    "source": "server",
                    "lease_id": lease_id.strip(),
                    "confirmation": confirmation,
                    "stage_task_facts": stage_task_facts,
                    "authorization_context": authorization_context,
                    "issued_at": transaction_time_text,
                    "expires_at": manual_expiry.isoformat(),
                    "consumed": True,
                    "consumed_at": transaction_time_text,
                }
                next_payload = dict(payload)
                next_payload["real_dxm_write_authorization"] = real_authorization
                next_payload["manual_approval"] = next_approval
                if formal_lineage is not None:
                    next_payload[PATH_B_FORMAL_LINEAGE_KEY] = (
                        formal_lineage
                    )
                if discovery_profile is not None:
                    next_payload[PATH_B_SAVE1_DISCOVERY_PROFILE_KEY] = (
                        discovery_profile
                    )

                if discovery_context is None:
                    scope_updated = conn.execute(
                        """
                        UPDATE real_dxm_write_scopes
                           SET status='consumed', approval_sha256=?,
                               approval_nonce_sha256=?, approval_stage=?,
                               approval_consumed_at=?, updated_at=?
                         WHERE scope_sha256=? AND task_id=? AND status='prepared'
                           AND scope_json=?
                        """,
                        (
                            canonical_approval["approvalSha256"],
                            real_authorization["approval_nonce_sha256"],
                            canonical_approval["stage"],
                            transaction_time_text,
                            transaction_time_text,
                            scope_sha256,
                            task_id,
                            stored_scope_json,
                        ),
                    )
                else:
                    scope_updated = conn.execute(
                        """
                        UPDATE real_dxm_write_scopes
                           SET status='consumed', approval_sha256=?,
                               approval_nonce_sha256=?, approval_stage='discovery',
                               approval_consumed_at=?, purpose='discovery', updated_at=?
                         WHERE scope_sha256=? AND task_id=? AND status='prepared'
                           AND scope_json=?
                           AND COALESCE(purpose, 'general') IN ('general', 'discovery')
                           AND lineage_discovery_receipt_sha256 IS NULL
                           AND lineage_predecessor_scope_sha256 IS NULL
                        """,
                        (
                            canonical_approval["approvalSha256"],
                            real_authorization["approval_nonce_sha256"],
                            transaction_time_text,
                            transaction_time_text,
                            scope_sha256,
                            task_id,
                            stored_scope_json,
                        ),
                    )
                if scope_updated.rowcount != 1:
                    raise _AtomicPathBStartRejected("APPROVAL_REPLAY")
                if discovery_context is not None:
                    if not all(
                        (
                            discovery_profile,
                            discovery_profile_sha256,
                            discovery_attempt_identity_sha256,
                            discovery_save1_lease_id,
                        )
                    ):
                        raise _AtomicPathBStartRejected(
                            "DISCOVERY_ATTEMPT_BINDING_INVALID"
                        )
                    attempt = conn.execute(
                        """
                        INSERT INTO real_dxm_path_b_discovery_attempts (
                            task_id, scope_sha256, discovery_key_sha256,
                            attempt_identity_sha256, profile_sha256,
                            request_sha256, approval_sha256, snapshot_id,
                            snapshot_sha256, job_id, product_id,
                            authorization_lease_id, status, reason_code,
                            discovery_receipt_sha256, armed_at, terminal_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  'armed', NULL, NULL, ?, NULL, ?, ?)
                        """,
                        (
                            task_id,
                            scope_sha256,
                            discovery_context["discovery_key_sha256"],
                            discovery_attempt_identity_sha256,
                            discovery_profile_sha256,
                            discovery_context["request_sha256"],
                            canonical_approval["approvalSha256"],
                            snapshot["snapshotId"],
                            snapshot["snapshotSha256"],
                            discovery_profile["target_job_id"],
                            discovery_profile["target_product_id"],
                            discovery_save1_lease_id,
                            transaction_time_text,
                            transaction_time_text,
                            transaction_time_text,
                        ),
                    )
                    if attempt.rowcount != 1:
                        raise _AtomicPathBStartRejected(
                            "DISCOVERY_ATTEMPT_CLAIM_CONFLICT"
                        )
                task_updated = conn.execute(
                    """
                    UPDATE tasks
                       SET status='running', payload_json=?, updated_at=?
                     WHERE id=? AND mode='batch_draft_save' AND status='draft'
                       AND payload_json=?
                    """,
                    (
                        dumps(next_payload),
                        transaction_time_text,
                        task_id,
                        task["payload_json"],
                    ),
                )
                if task_updated.rowcount != 1:
                    raise _AtomicPathBStartRejected("AUTH_START_CAS_CONFLICT")
        except _AtomicPathBStartRejected as exc:
            return AuthorizationLeaseResult(
                False,
                exc.reason_code,
                self.get_task(task_id),
                None,
            )
        except (
            sqlite3.IntegrityError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return AuthorizationLeaseResult(
                False,
                "AUTH_PERSISTENCE_CONFLICT",
                self.get_task(task_id),
                None,
            )

        return AuthorizationLeaseResult(
            True,
            "OK",
            self.get_task(task_id),
            self._public_authorization_lease(next_approval),
        )

    def approve_and_start_real_dxm_path_b_discovery(
        self,
        task_id: int,
        *,
        scope: Mapping[str, Any],
        approval: Mapping[str, Any],
        target_product_id: int,
        discovery_key_sha256: str,
        request_sha256: str,
        token: str,
        confirmation: str,
        approved_by: str,
        lease_id: str,
    ) -> AuthorizationLeaseResult:
        """Atomically arm the sole first-product SAVE1 discovery attempt.

        This entry point does not release general Path B.  It delegates to the
        same scope/approval transaction as formal starts while injecting the
        narrower persisted profile and one durable, non-replayable claim.
        """

        return self.approve_and_start_real_dxm_path_b(
            task_id,
            scope=scope,
            approval=approval,
            token=token,
            confirmation=confirmation,
            approved_by=approved_by,
            lease_id=lease_id,
            _discovery_context={
                "target_product_id": target_product_id,
                "discovery_key_sha256": discovery_key_sha256,
                "request_sha256": request_sha256,
            },
        )

    def get_real_dxm_write_scope(self, scope_sha256: str) -> dict[str, Any] | None:
        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            row = conn.execute(
                "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                (scope_sha256,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["scope"] = loads(result.pop("scope_json"), {})
            return result

    @staticmethod
    def _private_task_from_connection(
        conn: Any,
        task_id: int,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND mode!='removed_workflow_legacy'",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        task = dict(row)
        task["payload"] = loads(task.pop("payload_json"), {})
        task["jobs"] = [
            dict(candidate)
            for candidate in conn.execute(
                "SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        ]
        return task

    @staticmethod
    def _discovery_evidence_paths(value: Mapping[str, Any]) -> set[str]:
        evidence = value.get("evidence")
        refs = evidence.get("refs") if isinstance(evidence, Mapping) else None
        if not isinstance(refs, list):
            return set()
        return {
            str(item.get("path") or "").replace("\\", "/").casefold()
            for item in refs
            if isinstance(item, Mapping) and str(item.get("path") or "").strip()
        }

    @staticmethod
    def _discovery_evidence_times(
        value: Mapping[str, Any],
    ) -> list[datetime]:
        evidence = value.get("evidence")
        refs = evidence.get("refs") if isinstance(evidence, Mapping) else None
        if not isinstance(refs, list):
            return []
        result: list[datetime] = []
        for item in refs:
            raw = item.get("captured_at") if isinstance(item, Mapping) else None
            if not isinstance(raw, str) or not raw.strip():
                return []
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return []
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return []
            result.append(parsed.astimezone(timezone.utc))
        return result

    @staticmethod
    def _build_discovery_leaf_proof_manifest(
        *,
        first_save_action_result: Mapping[str, Any],
        unpublished_action_result: Mapping[str, Any],
        field_readbacks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Project the same five leaf proof hashes used by Formal receipts."""

        save_evidence = first_save_action_result.get("evidence")
        verify_evidence = unpublished_action_result.get("evidence")
        save_observations = (
            save_evidence.get("observations")
            if isinstance(save_evidence, Mapping)
            else None
        )
        handshake = (
            save_observations.get("first_save_intent_handshake")
            if isinstance(save_observations, Mapping)
            else None
        )
        network = (
            handshake.get("network_save_result")
            if isinstance(handshake, Mapping)
            else None
        )
        save_refs = (
            save_evidence.get("refs")
            if isinstance(save_evidence, Mapping)
            else None
        )
        verify_refs = (
            verify_evidence.get("refs")
            if isinstance(verify_evidence, Mapping)
            else None
        )
        if (
            not isinstance(network, Mapping)
            or not isinstance(save_refs, list)
            or len(save_refs) != 1
            or not isinstance(save_refs[0], Mapping)
            or not isinstance(verify_refs, list)
            or len(verify_refs) != 1
            or not isinstance(verify_refs[0], Mapping)
            or not field_readbacks
        ):
            raise ValueError("Discovery leaf proof sources are incomplete")
        proof_hashes = {
            "network_request_sha256": _normalized_sha256(
                network.get("request_body_sha256")
            ),
            "network_response_sha256": _normalized_sha256(
                network.get("response_body_sha256")
            ),
            "screenshot_sha256": _normalized_sha256(
                save_refs[0].get("sha256")
            ),
            "readback_sha256": canonical_contract_sha256(field_readbacks),
            "unpublished_readback_sha256": _normalized_sha256(
                verify_refs[0].get("sha256")
            ),
        }
        if (
            any(value is None for value in proof_hashes.values())
            or len(set(proof_hashes.values())) != len(proof_hashes)
        ):
            raise ValueError("Discovery leaf proof hashes are invalid or reused")
        return {
            "schema_version": _PATH_B_DISCOVERY_LEAF_PROOF_SCHEMA,
            **proof_hashes,
        }

    def _validate_sealed_discovery_authority(
        self,
        conn: Any,
        *,
        attempt: Mapping[str, Any],
        receipt_row: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Recompute the durable ledger and independent proof chain."""

        ledger_rows = conn.execute(
            """
            SELECT * FROM mutation_dispatch_ledger
             WHERE task_id=? ORDER BY id ASC
            """,
            (str(attempt.get("task_id")),),
        ).fetchall()
        if len(ledger_rows) != 1:
            raise ValueError("Discovery ledger cardinality drift")
        ledger = dict(ledger_rows[0])
        command = loads(ledger.get("command_json"), None)
        save_result = loads(ledger.get("save_action_result_json"), None)
        save_authority = loads(ledger.get("save_authority_json"), None)
        verify_command = loads(
            receipt_row.get("verification_command_json"), None
        )
        unpublished_result = loads(
            receipt_row.get("unpublished_action_result_json"), None
        )
        stored_manifest = loads(
            receipt_row.get("leaf_proof_manifest_json"), None
        )
        ledger_outcome = loads(ledger.get("outcome_json"), None)
        if not all(
            isinstance(value, Mapping)
            for value in (
                command,
                save_result,
                save_authority,
                verify_command,
                unpublished_result,
                stored_manifest,
            )
        ) or not (
            ledger_outcome is True
            or (
                isinstance(ledger_outcome, Mapping)
                and ledger_outcome.get("dispatched") is True
            )
        ):
            raise ValueError("Discovery persisted authority JSON is incomplete")
        command_sha256 = canonical_contract_sha256(command)
        save_result_sha256 = canonical_contract_sha256(save_result)
        save_authority_sha256 = canonical_contract_sha256(save_authority)
        verification_command_sha256 = canonical_contract_sha256(verify_command)
        unpublished_result_sha256 = canonical_contract_sha256(
            unpublished_result
        )
        try:
            save_command_contract = BrowserAgentCommand(**dict(command))
            verify_command_contract = BrowserAgentCommand(
                **dict(verify_command)
            )
            validate_browser_agent_command(save_command_contract)
            validate_browser_agent_command(verify_command_contract)
            defaults = save_command_contract.params.get("defaults")
            expected_execution_payload = (
                defaults.get("_frozen_execution_payload")
                if isinstance(defaults, Mapping)
                else None
            )
            task = self._private_task_from_connection(
                conn, int(receipt.get("task_id") or 0)
            )
            if not isinstance(task, Mapping):
                raise ValueError("Discovery task is missing")
            validated_save_result = validate_action_result_envelope(
                save_result,
                expected_state=PATH_B_SAVE1_DISCOVERY_STATE,
                expected_action=PATH_B_SAVE1_DISCOVERY_ACTION,
                expected_page="semi_managed",
                execution_mode="batch_draft_save",
                expected_runtime_id=save_command_contract.runtime_id,
                expected_browser_session_id=str(
                    receipt.get("runtime", {}).get("browserSessionId")
                    if isinstance(receipt.get("runtime"), Mapping)
                    else ""
                ),
                expected_execution_payload=expected_execution_payload,
                expected_target_identity=save_command_contract.params.get(
                    "target_identity"
                ),
                expected_store_name=save_command_contract.params.get(
                    "store_name"
                ),
                expected_target_hash=save_command_contract.target_hash,
            )
            rebuilt_authority = rebuild_save_verification_authority(
                task,
                save_command=dict(command),
                ledger_entry=ledger,
            )
            frozen_verification_context = (
                save_verification_facts_from_frozen_authority(
                    save_authority,
                    save_command=dict(command),
                    ledger_entry=ledger,
                    save_action_result_sha256=save_result_sha256,
                )
            )
            verification_context = validate_save_verification_context(
                verify_command_contract.params.get(
                    "save_verification_context"
                ),
                task_id=int(receipt.get("task_id") or 0),
                job_id=int(receipt.get("job_id") or 0),
                runtime_id=save_command_contract.runtime_id,
                execution_mode="batch_draft_save",
                save_command=dict(command),
                save_action_result=validated_save_result,
                authoritative_facts=rebuilt_authority,
            )
            validated_unpublished_result = validate_action_result_envelope(
                unpublished_result,
                expected_state="VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED",
                expected_action="verify_not_published",
                expected_page="semi_managed",
                execution_mode="batch_draft_save",
                expected_runtime_id=save_command_contract.runtime_id,
                expected_browser_session_id=str(
                    receipt.get("runtime", {}).get("browserSessionId")
                    if isinstance(receipt.get("runtime"), Mapping)
                    else ""
                ),
            )
        except (
            ActionResultContractError,
            BatchCommandContractError,
            DispatchAuthorityError,
            MutationCommandContractError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError("Discovery persisted contracts are invalid") from exc
        save_observations = validated_save_result["evidence"]["observations"]
        handshake = save_observations.get("first_save_intent_handshake")
        audit = (
            handshake.get("network_audit")
            if isinstance(handshake, Mapping)
            else None
        )
        authorization = (
            handshake.get("mutation_authorization")
            if isinstance(handshake, Mapping)
            else None
        )
        verify_observations = validated_unpublished_result["evidence"][
            "observations"
        ]
        fresh_probe = verify_observations.get("fresh_probe")
        save_target = validated_save_result["before_values"].get(
            "target_identity"
        )
        verify_target = validated_unpublished_result["before_values"].get(
            "target_identity"
        )
        save_times = self._discovery_evidence_times(validated_save_result)
        verify_times = self._discovery_evidence_times(
            validated_unpublished_result
        )
        opened_observation = (
            handshake.get("open_semi_managed_editor")
            if isinstance(handshake, Mapping)
            else None
        )
        authoritative_raw_readbacks = save_observations.get(
            "save_field_readbacks"
        )
        if authoritative_raw_readbacks is None and isinstance(
            opened_observation, Mapping
        ):
            authoritative_raw_readbacks = opened_observation.get(
                "field_readbacks"
            )
        if authoritative_raw_readbacks is None:
            authoritative_raw_readbacks = validated_save_result[
                "after_values"
            ].get("field_readbacks")
        try:
            authoritative_field_readbacks = [
                item.to_dict()
                for item in validated_field_readbacks_from_payload(
                    authoritative_raw_readbacks,
                    require_nonempty=True,
                    reason_prefix="DISCOVERY_SAVE1",
                )
            ]
        except ReceiptValidationError as exc:
            raise ValueError(
                "Discovery authoritative field readbacks are invalid"
            ) from exc
        authoritative_unpublished_readback = {
            "before_values": validated_unpublished_result["before_values"],
            "after_values": validated_unpublished_result["after_values"],
            "fresh_probe": fresh_probe,
        }
        def _ledger_time(value: Any) -> datetime:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("ledger timestamp lacks timezone")
            return parsed.astimezone(timezone.utc)

        try:
            reserved_at = _ledger_time(ledger.get("reserved_at"))
            dispatch_started_at = _ledger_time(
                ledger.get("dispatch_started_at")
            )
            dispatched_at = _ledger_time(ledger.get("dispatched_at"))
            recorded_at = _ledger_time(
                ledger.get("save_success_recorded_at")
            )
            ledger_updated_at = _ledger_time(ledger.get("updated_at"))
            sealed_at = _ledger_time(receipt.get("sealed_at"))
            receipt_row_sealed_at = _ledger_time(
                receipt_row.get("sealed_at")
            )
            attempt_terminal_at = _ledger_time(attempt.get("terminal_at"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Discovery ledger timestamps are invalid") from exc
        if (
            frozen_verification_context != verification_context
            or not isinstance(audit, Mapping)
            or not isinstance(authorization, Mapping)
            or audit.get("mutation_request_count") != 1
            or audit.get("save_request_count") != 1
            or audit.get("other_mutation_request_count") != 0
            or audit.get("publish_request_count") != 0
            or authorization.get("mutation_id") != ledger.get("mutation_id")
            or authorization.get("mutation_action") != "first_save_intent"
            or authorization.get("mutation_status") != "DISPATCHED"
            or save_target != verify_target
            or not isinstance(fresh_probe, Mapping)
            or fresh_probe.get("save_verification_context")
            != verification_context
            or validated_unpublished_result["before_values"].get(
                "save_verification_context"
            )
            != verification_context
            or _normalized_sha256(
                fresh_probe.get("target_identity_sha256")
            )
            != canonical_contract_sha256(save_target)
            or validated_unpublished_result["after_values"].get(
                "published"
            )
            is not False
            or receipt.get("physical_mutation_count") != 1
            or receipt.get("save1_count") != 1
            or receipt.get("save2_count") != 0
            or receipt.get("other_product_mutation_count") != 0
            or receipt.get("publish_request_count") != 0
            or receipt.get("published") is not False
            or receipt.get("unknown_count") != 0
            or receipt.get("field_readbacks")
            != authoritative_field_readbacks
            or receipt.get("unpublished_readback")
            != authoritative_unpublished_readback
            or ledger.get("unknown_at") is not None
            or not save_times
            or not verify_times
            or min(verify_times) <= max(save_times)
            or not (
                reserved_at
                <= dispatch_started_at
                <= dispatched_at
                <= recorded_at
                <= min(verify_times)
            )
            or max(save_times) > recorded_at
            or ledger_updated_at < recorded_at
            or sealed_at < max(verify_times)
            or receipt_row_sealed_at != sealed_at
            or attempt_terminal_at != sealed_at
        ):
            raise ValueError("Discovery counters, identity, or chronology drift")
        manifest = self._build_discovery_leaf_proof_manifest(
            first_save_action_result=validated_save_result,
            unpublished_action_result=validated_unpublished_result,
            field_readbacks=authoritative_field_readbacks,
        )
        manifest_sha256 = canonical_contract_sha256(manifest)
        expected_pairs = (
            (int(ledger.get("id") or 0), int(receipt.get("ledger_entry_id") or 0)),
            (ledger.get("status"), "DISPATCHED"),
            (ledger.get("mutation_action"), "first_save_intent"),
            (ledger.get("command_state"), PATH_B_SAVE1_DISCOVERY_STATE),
            (ledger.get("command_action"), PATH_B_SAVE1_DISCOVERY_ACTION),
            (ledger.get("task_id"), str(receipt.get("task_id"))),
            (ledger.get("job_id"), str(receipt.get("job_id"))),
            (ledger.get("command_id"), receipt.get("command_id")),
            (
                ledger.get("authorization_lease_id"),
                receipt.get("authorization_lease_id"),
            ),
            (ledger.get("mutation_id"), receipt.get("mutation_id")),
            (ledger.get("target_hash"), command.get("target_hash")),
            (_normalized_sha256(ledger.get("command_sha256")), command_sha256),
            (
                _normalized_sha256(ledger.get("save_action_result_sha256")),
                save_result_sha256,
            ),
            (
                _normalized_sha256(ledger.get("save_authority_sha256")),
                save_authority_sha256,
            ),
            (command.get("task_id"), receipt.get("task_id")),
            (command.get("job_id"), receipt.get("job_id")),
            (command.get("state"), PATH_B_SAVE1_DISCOVERY_STATE),
            (command.get("action"), PATH_B_SAVE1_DISCOVERY_ACTION),
            (command.get("command_id"), receipt.get("command_id")),
            (
                command.get("authorization_lease_id"),
                receipt.get("authorization_lease_id"),
            ),
            (verify_command.get("task_id"), receipt.get("task_id")),
            (verify_command.get("job_id"), receipt.get("job_id")),
            (
                verify_command.get("state"),
                "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED",
            ),
            (verify_command.get("action"), "verify_not_published"),
            (verify_command.get("execution_mode"), "batch_draft_save"),
            (verify_command.get("runtime_id"), command.get("runtime_id")),
            (
                verify_command.get("params", {}).get("target_identity"),
                command.get("params", {}).get("target_identity"),
            ),
            (
                verify_command.get("params", {}).get("store_name"),
                command.get("params", {}).get("store_name"),
            ),
            (
                verify_command.get("params", {}).get("save_predecessor"),
                {
                    "state": PATH_B_SAVE1_DISCOVERY_STATE,
                    "action": PATH_B_SAVE1_DISCOVERY_ACTION,
                },
            ),
            (
                _normalized_sha256(receipt.get("first_save_command_sha256")),
                command_sha256,
            ),
            (
                _normalized_sha256(
                    receipt.get("first_save_action_result_sha256")
                ),
                save_result_sha256,
            ),
            (
                _normalized_sha256(receipt.get("save_authority_sha256")),
                save_authority_sha256,
            ),
            (
                _normalized_sha256(
                    receipt.get("save_verification_context_sha256")
                ),
                canonical_contract_sha256(verification_context),
            ),
            (
                _normalized_sha256(receipt.get("field_readbacks_sha256")),
                canonical_contract_sha256(authoritative_field_readbacks),
            ),
            (
                _normalized_sha256(
                    receipt.get("unpublished_readback_sha256")
                ),
                canonical_contract_sha256(
                    authoritative_unpublished_readback
                ),
            ),
            (
                _normalized_sha256(
                    receipt.get("first_save_intent_handshake_sha256")
                ),
                _normalized_sha256(
                    handshake.get("handshake_sha256")
                    if isinstance(handshake, Mapping)
                    else None
                ),
            ),
            (
                _normalized_sha256(
                    receipt.get("verification_command_sha256")
                ),
                verification_command_sha256,
            ),
            (
                _normalized_sha256(
                    receipt.get("unpublished_action_result_sha256")
                ),
                unpublished_result_sha256,
            ),
            (receipt.get("leaf_proof_manifest"), manifest),
            (
                _normalized_sha256(
                    receipt.get("leaf_proof_manifest_sha256")
                ),
                manifest_sha256,
            ),
            (dict(stored_manifest), manifest),
            (
                _normalized_sha256(
                    receipt_row.get("leaf_proof_manifest_sha256")
                ),
                manifest_sha256,
            ),
            (attempt.get("authorization_lease_id"), receipt.get("authorization_lease_id")),
            (attempt.get("command_id"), receipt.get("command_id")),
            (attempt.get("mutation_id"), receipt.get("mutation_id")),
            (attempt.get("status"), "sealed"),
            (receipt_row.get("status"), "sealed"),
            (receipt_row.get("created_at"), receipt.get("sealed_at")),
            (receipt_row.get("updated_at"), receipt.get("sealed_at")),
            (
                _normalized_sha256(
                    receipt_row.get("first_save_command_sha256")
                ),
                command_sha256,
            ),
            (
                _normalized_sha256(
                    receipt_row.get("first_save_action_result_sha256")
                ),
                save_result_sha256,
            ),
            (
                _normalized_sha256(
                    receipt_row.get("save_authority_sha256")
                ),
                save_authority_sha256,
            ),
            (
                _normalized_sha256(
                    receipt_row.get("verification_command_sha256")
                ),
                verification_command_sha256,
            ),
            (
                _normalized_sha256(
                    receipt_row.get("unpublished_action_result_sha256")
                ),
                unpublished_result_sha256,
            ),
            (
                _normalized_sha256(
                    receipt_row.get("save_verification_context_sha256")
                ),
                canonical_contract_sha256(verification_context),
            ),
            (
                _normalized_sha256(
                    receipt_row.get("field_readbacks_sha256")
                ),
                canonical_contract_sha256(authoritative_field_readbacks),
            ),
            (
                _normalized_sha256(
                    receipt_row.get("unpublished_readback_sha256")
                ),
                canonical_contract_sha256(
                    authoritative_unpublished_readback
                ),
            ),
            (
                _normalized_sha256(
                    receipt_row.get(
                        "first_save_intent_handshake_sha256"
                    )
                ),
                _normalized_sha256(
                    handshake.get("handshake_sha256")
                    if isinstance(handshake, Mapping)
                    else None
                ),
            ),
        )
        if any(observed != expected for observed, expected in expected_pairs):
            raise ValueError("Discovery persisted authority binding drift")
        return manifest

    def seal_path_b_save1_discovery_and_stop(
        self,
        *,
        task_id: int,
        job_id: int,
        expected_profile: Mapping[str, Any],
        expected_profile_sha256: str,
        first_save_command: Mapping[str, Any],
        first_save_action_result: Mapping[str, Any],
        unpublished_command: Mapping[str, Any],
        unpublished_action_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Seal the one allowed Discovery mutation and stop before SAVE2.

        All mutable facts are re-read under ``BEGIN IMMEDIATE``.  The receipt
        is inserted in the same transaction that seals the attempt, consumes
        the scope terminally, and stops the task/job queue.
        """

        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id <= 0
            or isinstance(job_id, bool)
            or not isinstance(job_id, int)
            or job_id <= 0
            or not isinstance(expected_profile, Mapping)
            or _normalized_sha256(expected_profile_sha256) is None
            or not all(
                isinstance(value, Mapping)
                for value in (
                    first_save_command,
                    first_save_action_result,
                    unpublished_command,
                    unpublished_action_result,
                )
            )
        ):
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason_code": "DISCOVERY_SEAL_INPUT_INVALID",
            }

        try:
            with connection() as conn:
                migrate_real_dxm_write_scopes(conn)
                migrate_real_dxm_path_b_discovery_receipts(conn)
                conn.execute("BEGIN IMMEDIATE")
                task = self._private_task_from_connection(conn, task_id)
                if task is None:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_CURRENT_TASK_MISSING"
                    )
                payload = (
                    task.get("payload")
                    if isinstance(task.get("payload"), Mapping)
                    else {}
                )
                stored_profile_raw = payload.get(
                    PATH_B_SAVE1_DISCOVERY_PROFILE_KEY
                )
                try:
                    stored_profile = validate_path_b_save1_discovery_profile(
                        stored_profile_raw
                    )
                    requested_profile = validate_path_b_save1_discovery_profile(
                        expected_profile
                    )
                except BatchCommandContractError as exc:
                    raise _AtomicPathBStartRejected(exc.reason_code) from exc
                profile_sha256 = canonical_contract_sha256(stored_profile)
                if (
                    stored_profile != requested_profile
                    or profile_sha256
                    != _normalized_sha256(expected_profile_sha256)
                    or stored_profile["target_task_id"] != task_id
                    or stored_profile["target_job_id"] != job_id
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_PROFILE_PERSISTENCE_DRIFT"
                    )
                try:
                    validated_dispatch_profile = (
                        validate_path_b_save1_discovery_dispatch(
                            task,
                            job_id=job_id,
                            command_state=first_save_command.get("state"),
                            command_action=first_save_command.get("action"),
                        )
                    )
                except BatchCommandContractError as exc:
                    raise _AtomicPathBStartRejected(exc.reason_code) from exc
                if validated_dispatch_profile != stored_profile:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_DISPATCH_PROFILE_MISMATCH"
                    )

                attempt = conn.execute(
                    """
                    SELECT * FROM real_dxm_path_b_discovery_attempts
                     WHERE task_id=?
                    """,
                    (task_id,),
                ).fetchone()
                if not attempt or str(attempt.get("status") or "") != "armed":
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_ATTEMPT_NOT_ARMED"
                    )
                scope_row = conn.execute(
                    "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                    (stored_profile["scope_sha256"],),
                ).fetchone()
                if (
                    not scope_row
                    or str(scope_row.get("status") or "") != "consumed"
                    or str(scope_row.get("purpose") or "") != "discovery"
                    or str(scope_row.get("approval_stage") or "") != "discovery"
                    or int(scope_row.get("task_id") or 0) != task_id
                    or _normalized_sha256(scope_row.get("approval_sha256"))
                    != stored_profile["approval_sha256"]
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SCOPE_PERSISTENCE_DRIFT"
                    )
                scope = loads(scope_row.get("scope_json"), {})
                if not isinstance(scope, Mapping):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SCOPE_PERSISTENCE_DRIFT"
                    )
                attempt_pairs = (
                    (int(attempt.get("task_id") or 0), task_id),
                    (
                        _normalized_sha256(attempt.get("scope_sha256")),
                        stored_profile["scope_sha256"],
                    ),
                    (
                        _normalized_sha256(
                            attempt.get("discovery_key_sha256")
                        ),
                        stored_profile["discovery_key_sha256"],
                    ),
                    (
                        _normalized_sha256(attempt.get("profile_sha256")),
                        profile_sha256,
                    ),
                    (
                        _normalized_sha256(attempt.get("approval_sha256")),
                        stored_profile["approval_sha256"],
                    ),
                    (
                        int(attempt.get("snapshot_id") or 0),
                        int(scope["snapshot"]["snapshotId"]),
                    ),
                    (
                        _normalized_sha256(attempt.get("snapshot_sha256")),
                        _normalized_sha256(
                            scope["snapshot"]["snapshotSha256"]
                        ),
                    ),
                    (int(attempt.get("job_id") or 0), job_id),
                    (
                        int(attempt.get("product_id") or 0),
                        stored_profile["target_product_id"],
                    ),
                )
                attempt_identity_sha256 = canonical_contract_sha256(
                    {
                        "schema": "dxm.real-dxm-path-b.discovery-attempt-identity.v1",
                        "discovery_key_sha256": stored_profile[
                            "discovery_key_sha256"
                        ],
                        "task_id": task_id,
                        "snapshot_sha256": scope["snapshot"][
                            "snapshotSha256"
                        ],
                        "scope_sha256": stored_profile["scope_sha256"],
                        "approval_sha256": stored_profile[
                            "approval_sha256"
                        ],
                        "target_product_ordinal": 1,
                        "target_product_id": stored_profile[
                            "target_product_id"
                        ],
                        "profile_sha256": profile_sha256,
                        "account_ref_hash": scope["account"][
                            "accountContextHash"
                        ],
                        "shop_id": scope["shop"]["shopId"],
                        "runtime_instance_id": scope["runtime"][
                            "runtimeInstanceId"
                        ],
                        "browser_session_id": scope["runtime"][
                            "browserSessionId"
                        ],
                        "git_head": scope["git"]["head"],
                        "worktree": scope["worktree"],
                    }
                )
                if (
                    any(
                        observed != expected
                        for observed, expected in attempt_pairs
                    )
                    or _normalized_sha256(
                        attempt.get("attempt_identity_sha256")
                    )
                    != attempt_identity_sha256
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_ATTEMPT_PERSISTENCE_DRIFT"
                    )

                try:
                    save_command = BrowserAgentCommand(**dict(first_save_command))
                    verify_command = BrowserAgentCommand(**dict(unpublished_command))
                    validate_browser_agent_command(save_command)
                    validate_browser_agent_command(verify_command)
                except (MutationCommandContractError, TypeError, ValueError) as exc:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_COMMAND_INVALID"
                    ) from exc
                if (
                    save_command.task_id != task_id
                    or save_command.job_id != job_id
                    or save_command.state != PATH_B_SAVE1_DISCOVERY_STATE
                    or save_command.action != PATH_B_SAVE1_DISCOVERY_ACTION
                    or save_command.execution_mode != "batch_draft_save"
                    or save_command.expected_page != "editor"
                    or save_command.pre_dispatch_page != "editor"
                    or save_command.post_dispatch_page != "semi_managed"
                    or verify_command.task_id != task_id
                    or verify_command.job_id != job_id
                    or verify_command.state
                    != "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED"
                    or verify_command.action != "verify_not_published"
                    or verify_command.execution_mode != "batch_draft_save"
                    or verify_command.expected_page != "semi_managed"
                    or save_command.command_id == verify_command.command_id
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_COMMAND_BINDING_MISMATCH"
                    )

                real_authorization = payload.get(
                    "real_dxm_write_authorization"
                )
                leases = (
                    real_authorization.get("save_leases")
                    if isinstance(real_authorization, Mapping)
                    else None
                )
                if not isinstance(leases, list) or len(leases) != 6:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SAVE_LEASE_COUNT_INVALID"
                    )
                save1_leases = [
                    item
                    for item in leases
                    if isinstance(item, Mapping)
                    and item.get("product_id")
                    == stored_profile["target_product_id"]
                    and item.get("product_ordinal") == 1
                    and item.get("save_stage") == "SAVE1"
                    and item.get("scope_sha256")
                    == stored_profile["scope_sha256"]
                ]
                if (
                    len(save1_leases) != 1
                    or save_command.authorization_lease_id
                    != save1_leases[0].get("lease_id")
                    or attempt.get("authorization_lease_id")
                    != save_command.authorization_lease_id
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SAVE1_LEASE_MISMATCH"
                    )

                ledger_rows = conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                     WHERE task_id=?
                     ORDER BY id ASC
                    """,
                    (str(task_id),),
                ).fetchall()
                if len(ledger_rows) != 1:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_MUTATION_COUNT_INVALID"
                    )
                ledger = dict(ledger_rows[0])
                command_sha256 = browser_agent_command_sha256(save_command)
                persisted_command = loads(ledger.get("command_json"), None)
                persisted_save_result = loads(
                    ledger.get("save_action_result_json"), None
                )
                save_result_sha256 = canonical_contract_sha256(
                    dict(first_save_action_result)
                )
                save_authority = loads(
                    ledger.get("save_authority_json"), None
                )
                save_authority_sha256 = (
                    canonical_contract_sha256(save_authority)
                    if isinstance(save_authority, Mapping)
                    else None
                )
                ledger_pairs = (
                    (ledger.get("mutation_action"), "first_save_intent"),
                    (int(ledger.get("ordinal") or 0), 1),
                    (ledger.get("command_state"), PATH_B_SAVE1_DISCOVERY_STATE),
                    (ledger.get("command_action"), PATH_B_SAVE1_DISCOVERY_ACTION),
                    (ledger.get("task_id"), str(task_id)),
                    (ledger.get("job_id"), str(job_id)),
                    (
                        ledger.get("authorization_lease_id"),
                        save_command.authorization_lease_id,
                    ),
                    (ledger.get("status"), "DISPATCHED"),
                    (ledger.get("command_id"), save_command.command_id),
                    (
                        _normalized_sha256(ledger.get("command_sha256")),
                        command_sha256,
                    ),
                    (
                        _normalized_sha256(
                            ledger.get("save_action_result_sha256")
                        ),
                        save_result_sha256,
                    ),
                    (
                        _normalized_sha256(
                            ledger.get("save_authority_sha256")
                        ),
                        save_authority_sha256,
                    ),
                )
                if (
                    any(
                        observed != expected
                        for observed, expected in ledger_pairs
                    )
                    or persisted_command != dict(first_save_command)
                    or persisted_save_result != dict(first_save_action_result)
                    or not isinstance(save_authority, Mapping)
                    or not ledger.get("mutation_id")
                    or not ledger.get("save_success_recorded_at")
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_LEDGER_PERSISTENCE_DRIFT"
                    )

                defaults = save_command.params.get("defaults")
                expected_execution_payload = (
                    defaults.get("_frozen_execution_payload")
                    if isinstance(defaults, Mapping)
                    else None
                )
                target_identity = save_command.params.get("target_identity")
                store_name = save_command.params.get("store_name")
                scope_runtime = (
                    scope.get("runtime")
                    if isinstance(scope.get("runtime"), Mapping)
                    else {}
                )
                if (
                    not isinstance(expected_execution_payload, Mapping)
                    or not isinstance(target_identity, Mapping)
                    or not isinstance(store_name, str)
                    or not store_name.strip()
                    or save_command.runtime_id
                    != scope_runtime.get("runtimeInstanceId")
                    or verify_command.runtime_id != save_command.runtime_id
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_RUNTIME_OR_TARGET_DRIFT"
                    )
                browser_session_id = str(
                    scope_runtime.get("browserSessionId") or ""
                )
                try:
                    validated_save_result = validate_action_result_envelope(
                        first_save_action_result,
                        expected_state=PATH_B_SAVE1_DISCOVERY_STATE,
                        expected_action=PATH_B_SAVE1_DISCOVERY_ACTION,
                        expected_page="semi_managed",
                        execution_mode="batch_draft_save",
                        expected_runtime_id=save_command.runtime_id,
                        expected_browser_session_id=browser_session_id,
                        expected_execution_payload=expected_execution_payload,
                        expected_target_identity=target_identity,
                        expected_store_name=store_name,
                        expected_target_hash=save_command.target_hash,
                    )
                    authoritative_facts = rebuild_save_verification_authority(
                        task,
                        save_command=dict(first_save_command),
                        ledger_entry=ledger,
                    )
                    verification_context = validate_save_verification_context(
                        verify_command.params.get(
                            "save_verification_context"
                        ),
                        task_id=task_id,
                        job_id=job_id,
                        runtime_id=save_command.runtime_id,
                        execution_mode="batch_draft_save",
                        save_command=dict(first_save_command),
                        save_action_result=validated_save_result,
                        authoritative_facts=authoritative_facts,
                    )
                    validated_unpublished_result = (
                        validate_action_result_envelope(
                            unpublished_action_result,
                            expected_state=(
                                "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED"
                            ),
                            expected_action="verify_not_published",
                            expected_page="semi_managed",
                            execution_mode="batch_draft_save",
                            expected_runtime_id=save_command.runtime_id,
                            expected_browser_session_id=browser_session_id,
                        )
                    )
                except (
                    ActionResultContractError,
                    BatchCommandContractError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_CAUSAL_EVIDENCE_INVALID"
                    ) from exc
                if (
                    validated_save_result != dict(first_save_action_result)
                    or validated_unpublished_result
                    != dict(unpublished_action_result)
                    or verify_command.params.get("save_predecessor")
                    != {
                        "state": PATH_B_SAVE1_DISCOVERY_STATE,
                        "action": PATH_B_SAVE1_DISCOVERY_ACTION,
                    }
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_CAUSAL_EVIDENCE_DRIFT"
                    )

                verify_observations = validated_unpublished_result[
                    "evidence"
                ]["observations"]
                fresh_probe = verify_observations.get("fresh_probe")
                save_target = validated_save_result["before_values"].get(
                    "target_identity"
                )
                verify_target = validated_unpublished_result[
                    "before_values"
                ].get("target_identity")
                if (
                    save_target != verify_target
                    or not isinstance(fresh_probe, Mapping)
                    or fresh_probe.get("save_verification_context")
                    != verification_context
                    or validated_unpublished_result["before_values"].get(
                        "save_verification_context"
                    )
                    != verification_context
                    or _normalized_sha256(
                        fresh_probe.get("target_identity_sha256")
                    )
                    != canonical_contract_sha256(save_target)
                    or validated_unpublished_result["after_values"].get(
                        "published"
                    )
                    is not False
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_IDENTITY_CONTINUITY_INVALID"
                    )
                save_paths = self._discovery_evidence_paths(
                    validated_save_result
                )
                verify_paths = self._discovery_evidence_paths(
                    validated_unpublished_result
                )
                save_times = self._discovery_evidence_times(
                    validated_save_result
                )
                verify_times = self._discovery_evidence_times(
                    validated_unpublished_result
                )
                if (
                    not save_paths
                    or not verify_paths
                    or bool(save_paths & verify_paths)
                    or not save_times
                    or not verify_times
                    or min(verify_times) <= max(save_times)
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_INDEPENDENT_PROOF_INVALID"
                    )

                save_observations = validated_save_result["evidence"][
                    "observations"
                ]
                handshake = save_observations.get(
                    "first_save_intent_handshake"
                )
                if not isinstance(handshake, Mapping):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_HANDSHAKE_MISSING"
                    )
                audit = handshake.get("network_audit")
                authorization = handshake.get("mutation_authorization")
                if (
                    not isinstance(audit, Mapping)
                    or not isinstance(authorization, Mapping)
                    or audit.get("mutation_request_count") != 1
                    or audit.get("save_request_count") != 1
                    or audit.get("other_mutation_request_count") != 0
                    or audit.get("publish_request_count") != 0
                    or authorization.get("mutation_id")
                    != ledger.get("mutation_id")
                    or authorization.get("mutation_action")
                    != "first_save_intent"
                    or authorization.get("mutation_status") != "DISPATCHED"
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_WRITE_COUNTER_INVALID"
                    )

                unpublished_result_sha256 = canonical_contract_sha256(
                    validated_unpublished_result
                )
                handshake_sha256 = _normalized_sha256(
                    handshake.get("handshake_sha256")
                )
                verification_command_sha256 = canonical_contract_sha256(
                    dict(unpublished_command)
                )
                opened_observation = handshake.get(
                    "open_semi_managed_editor"
                )
                raw_field_readbacks = save_observations.get(
                    "save_field_readbacks"
                )
                if raw_field_readbacks is None and isinstance(
                    opened_observation, Mapping
                ):
                    raw_field_readbacks = opened_observation.get(
                        "field_readbacks"
                    )
                if raw_field_readbacks is None:
                    raw_field_readbacks = validated_save_result[
                        "after_values"
                    ].get("field_readbacks")
                try:
                    field_readbacks = [
                        item.to_dict()
                        for item in validated_field_readbacks_from_payload(
                            raw_field_readbacks,
                            require_nonempty=True,
                            reason_prefix="DISCOVERY_SAVE1",
                        )
                    ]
                except ReceiptValidationError as exc:
                    raise _AtomicPathBStartRejected(exc.reason_code) from exc
                plan = payload.get("plan_snapshot")
                item_snapshots = (
                    plan.get("item_snapshots")
                    if isinstance(plan, Mapping)
                    else None
                )
                matching_items = [
                    item
                    for item in item_snapshots or []
                    if isinstance(item, Mapping)
                    and str(item.get("product_id") or "")
                    == str(stored_profile["target_product_id"])
                ]
                stage_facts = (
                    matching_items[0].get("real_write_stage_facts")
                    if len(matching_items) == 1
                    and isinstance(
                        matching_items[0].get("real_write_stage_facts"),
                        Mapping,
                    )
                    else None
                )
                expected_save1_facts = (
                    stage_facts.get("SAVE1")
                    if isinstance(stage_facts, Mapping)
                    else None
                )
                if (
                    not isinstance(expected_save1_facts, list)
                    or not expected_save1_facts
                    or any(
                        not isinstance(item, Mapping)
                        for item in expected_save1_facts
                    )
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SAVE1_STAGE_FACTS_INVALID"
                    )
                expected_after_by_field = {
                    str(item.get("field_key") or ""): _normalized_sha256(
                        item.get("expected_sha256")
                    )
                    for item in expected_save1_facts
                }
                actual_after_by_field = {
                    str(item["field_key"]): canonical_contract_sha256(
                        item.get("after_value")
                    )
                    for item in field_readbacks
                }
                if (
                    "" in expected_after_by_field
                    or None in expected_after_by_field.values()
                    or expected_after_by_field != actual_after_by_field
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SAVE1_FIELD_READBACK_MISMATCH"
                    )
                field_readbacks_sha256 = canonical_contract_sha256(
                    field_readbacks
                )
                unpublished_readback = {
                    "before_values": validated_unpublished_result[
                        "before_values"
                    ],
                    "after_values": validated_unpublished_result[
                        "after_values"
                    ],
                    "fresh_probe": fresh_probe,
                }
                unpublished_readback_sha256 = canonical_contract_sha256(
                    unpublished_readback
                )
                leaf_proof_manifest = (
                    self._build_discovery_leaf_proof_manifest(
                        first_save_action_result=validated_save_result,
                        unpublished_action_result=(
                            validated_unpublished_result
                        ),
                        field_readbacks=field_readbacks,
                    )
                )
                leaf_proof_manifest_sha256 = canonical_contract_sha256(
                    leaf_proof_manifest
                )
                if (
                    handshake_sha256 is None
                    or handshake_sha256 == unpublished_result_sha256
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_PROOF_REUSE_INVALID"
                    )

                sealed_at = now_iso()
                receipt: dict[str, Any] = {
                    "schema_version": _PATH_B_DISCOVERY_RECEIPT_SCHEMA,
                    "attempt_identity_sha256": _normalized_sha256(
                        attempt.get("attempt_identity_sha256")
                    ),
                    "task_id": task_id,
                    "job_id": job_id,
                    "product_id": stored_profile["target_product_id"],
                    "snapshot_id": int(scope["snapshot"]["snapshotId"]),
                    "snapshot_sha256": _normalized_sha256(
                        scope["snapshot"]["snapshotSha256"]
                    ),
                    "ordered_product_ids": [
                        int(item["productId"])
                        for item in scope["orderedProducts"]
                    ],
                    "account_ref_hash": scope["account"][
                        "accountContextHash"
                    ],
                    "shop_id": scope["shop"]["shopId"],
                    "shop_name": scope["shop"]["shopName"],
                    "git_head": scope["git"]["head"],
                    "worktree": dict(scope["worktree"]),
                    "runtime": dict(scope["runtime"]),
                    "scope_sha256": stored_profile["scope_sha256"],
                    "approval_sha256": stored_profile["approval_sha256"],
                    "discovery_key_sha256": stored_profile[
                        "discovery_key_sha256"
                    ],
                    "profile_sha256": profile_sha256,
                    "command_id": save_command.command_id,
                    "authorization_lease_id": (
                        save_command.authorization_lease_id
                    ),
                    "mutation_id": ledger["mutation_id"],
                    "ledger_entry_id": int(ledger["id"]),
                    "first_save_command_sha256": command_sha256,
                    "first_save_action_result_sha256": save_result_sha256,
                    "save_authority_sha256": save_authority_sha256,
                    "verification_command_sha256": (
                        verification_command_sha256
                    ),
                    "save_verification_context_sha256": (
                        verification_context["context_sha256"]
                    ),
                    "field_readbacks": field_readbacks,
                    "field_readbacks_sha256": field_readbacks_sha256,
                    "unpublished_readback": unpublished_readback,
                    "unpublished_readback_sha256": (
                        unpublished_readback_sha256
                    ),
                    "physical_mutation_count": 1,
                    "save1_count": 1,
                    "save2_count": 0,
                    "other_product_mutation_count": 0,
                    "publish_request_count": 0,
                    "published": False,
                    "unknown_count": 0,
                    "first_save_intent_handshake_sha256": handshake_sha256,
                    "unpublished_action_result_sha256": (
                        unpublished_result_sha256
                    ),
                    "leaf_proof_manifest": leaf_proof_manifest,
                    "leaf_proof_manifest_sha256": (
                        leaf_proof_manifest_sha256
                    ),
                    "sealed_at": sealed_at,
                }
                receipt["discovery_receipt_sha256"] = canonical_contract_sha256(
                    receipt
                )
                receipt_sha256 = receipt["discovery_receipt_sha256"]
                inserted = conn.execute(
                    """
                    INSERT INTO real_dxm_path_b_discovery_receipts (
                        attempt_id, attempt_identity_sha256, task_id, job_id,
                        product_id, scope_sha256, approval_sha256,
                        discovery_key_sha256, profile_sha256, command_id,
                        authorization_lease_id, mutation_id, ledger_entry_id,
                        first_save_command_sha256,
                        first_save_action_result_sha256, save_authority_sha256,
                        verification_command_sha256,
                        save_verification_context_sha256,
                        field_readbacks_sha256, unpublished_readback_sha256,
                        first_save_intent_handshake_sha256,
                        unpublished_action_result_sha256,
                        verification_command_json,
                        unpublished_action_result_json,
                        leaf_proof_manifest_sha256,
                        leaf_proof_manifest_json,
                        discovery_receipt_sha256, receipt_json, status,
                        sealed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'sealed', ?, ?, ?)
                    """,
                    (
                        int(attempt["id"]),
                        receipt["attempt_identity_sha256"],
                        task_id,
                        job_id,
                        receipt["product_id"],
                        receipt["scope_sha256"],
                        receipt["approval_sha256"],
                        receipt["discovery_key_sha256"],
                        receipt["profile_sha256"],
                        receipt["command_id"],
                        receipt["authorization_lease_id"],
                        receipt["mutation_id"],
                        receipt["ledger_entry_id"],
                        receipt["first_save_command_sha256"],
                        receipt["first_save_action_result_sha256"],
                        receipt["save_authority_sha256"],
                        receipt["verification_command_sha256"],
                        receipt["save_verification_context_sha256"],
                        receipt["field_readbacks_sha256"],
                        receipt["unpublished_readback_sha256"],
                        receipt["first_save_intent_handshake_sha256"],
                        receipt["unpublished_action_result_sha256"],
                        dumps(dict(unpublished_command)),
                        dumps(validated_unpublished_result),
                        receipt["leaf_proof_manifest_sha256"],
                        dumps(receipt["leaf_proof_manifest"]),
                        receipt_sha256,
                        dumps(receipt),
                        sealed_at,
                        sealed_at,
                        sealed_at,
                    ),
                )
                if inserted.rowcount != 1:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_RECEIPT_INSERT_CONFLICT"
                    )
                attempt_updated = conn.execute(
                    """
                    UPDATE real_dxm_path_b_discovery_attempts
                       SET status='sealed', reason_code=NULL,
                           discovery_receipt_sha256=?, command_id=?,
                           mutation_id=?, terminal_at=?, updated_at=?
                     WHERE id=? AND status='armed'
                       AND discovery_receipt_sha256 IS NULL
                    """,
                    (
                        receipt_sha256,
                        receipt["command_id"],
                        receipt["mutation_id"],
                        sealed_at,
                        sealed_at,
                        attempt["id"],
                    ),
                )
                scope_updated = conn.execute(
                    """
                    UPDATE real_dxm_write_scopes
                       SET status='discovery_sealed', updated_at=?
                     WHERE id=? AND status='consumed'
                       AND purpose='discovery' AND approval_stage='discovery'
                    """,
                    (sealed_at, scope_row["id"]),
                )
                job_updated = conn.execute(
                    """
                    UPDATE jobs
                       SET status='stopped',
                           current_step_code='DISCOVERY_SEAL_STOP',
                           current_step_name='Discovery SAVE1 已封存，停止后续写入',
                           updated_at=?
                     WHERE id=? AND task_id=? AND status='running'
                    """,
                    (sealed_at, job_id, task_id),
                )
                next_payload = dict(payload)
                next_payload["runner_dispatch"] = self._released_runner_dispatch(
                    payload.get("runner_dispatch"),
                    released_at=sealed_at,
                    reason="path_b_save1_discovery_sealed",
                )
                task_updated = conn.execute(
                    """
                    UPDATE tasks
                       SET status='stopped', payload_json=?, completed_jobs=0,
                           failed_jobs=0, updated_at=?
                     WHERE id=? AND status='running' AND completed_jobs=0
                       AND failed_jobs=0
                    """,
                    (dumps(next_payload), sealed_at, task_id),
                )
                if any(
                    cursor.rowcount != 1
                    for cursor in (
                        attempt_updated,
                        scope_updated,
                        job_updated,
                        task_updated,
                    )
                ):
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_SEAL_CAS_CONFLICT"
                    )
                pending_count = conn.execute(
                    """
                    SELECT COUNT(*) AS value FROM jobs
                     WHERE task_id=? AND status='pending'
                    """,
                    (task_id,),
                ).fetchone()
                if int(pending_count["value"] or 0) != 2:
                    raise _AtomicPathBStartRejected(
                        "DISCOVERY_REMAINING_QUEUE_DRIFT"
                    )
        except _AtomicPathBStartRejected as exc:
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason_code": exc.reason_code,
            }
        except (
            sqlite3.IntegrityError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason_code": "DISCOVERY_SEAL_PERSISTENCE_CONFLICT",
            }
        return {
            "ok": True,
            "status": "stopped",
            "reason_code": "PATH_B_SAVE1_DISCOVERY_SEALED",
            "receipt_sha256": receipt_sha256,
        }

    def _get_real_dxm_path_b_discovery(
        self,
        *,
        lookup_column: str,
        lookup_sha256: str,
    ) -> dict[str, Any] | None:
        normalized = _normalized_sha256(lookup_sha256)
        if normalized is None or lookup_column not in {
            "discovery_key_sha256",
            "discovery_receipt_sha256",
        }:
            return None
        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            migrate_real_dxm_path_b_discovery_receipts(conn)
            attempt = conn.execute(
                f"""
                SELECT * FROM real_dxm_path_b_discovery_attempts
                 WHERE {lookup_column}=?
                """,
                (normalized,),
            ).fetchone()
            if not attempt:
                return None
            task = conn.execute(
                "SELECT id, status, payload_json FROM tasks WHERE id=?",
                (attempt["task_id"],),
            ).fetchone()
            scope = conn.execute(
                "SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?",
                (attempt["scope_sha256"],),
            ).fetchone()
            scope_payload = (
                loads(scope.get("scope_json"), {}) if scope else {}
            )
            receipt_row = None
            if attempt.get("discovery_receipt_sha256"):
                receipt_row = conn.execute(
                    """
                    SELECT * FROM real_dxm_path_b_discovery_receipts
                     WHERE discovery_receipt_sha256=?
                    """,
                    (attempt["discovery_receipt_sha256"],),
                ).fetchone()

            drift = False
            payload = (
                loads(task.get("payload_json"), {}) if task else {}
            )
            raw_profile = (
                payload.get(PATH_B_SAVE1_DISCOVERY_PROFILE_KEY)
                if isinstance(payload, Mapping)
                else None
            )
            try:
                profile = validate_path_b_save1_discovery_profile(raw_profile)
            except (BatchCommandContractError, TypeError, ValueError):
                profile = None
                drift = True
            if (
                not task
                or not scope
                or profile is None
                or canonical_contract_sha256(profile)
                != _normalized_sha256(attempt.get("profile_sha256"))
                or profile["target_task_id"] != int(attempt["task_id"])
                or profile["target_job_id"] != int(attempt.get("job_id") or 0)
                or profile["target_product_id"]
                != int(attempt.get("product_id") or 0)
                or profile["scope_sha256"]
                != _normalized_sha256(attempt.get("scope_sha256"))
                or profile["discovery_key_sha256"]
                != _normalized_sha256(
                    attempt.get("discovery_key_sha256")
                )
                or profile["approval_sha256"]
                != _normalized_sha256(attempt.get("approval_sha256"))
                or int(scope.get("task_id") or 0) != int(attempt["task_id"])
                or not isinstance(scope_payload, Mapping)
            ):
                drift = True
            if profile is not None and isinstance(scope_payload, Mapping):
                try:
                    rebuilt_attempt_identity = canonical_contract_sha256(
                        {
                            "schema": "dxm.real-dxm-path-b.discovery-attempt-identity.v1",
                            "discovery_key_sha256": profile[
                                "discovery_key_sha256"
                            ],
                            "task_id": int(attempt["task_id"]),
                            "snapshot_sha256": scope_payload["snapshot"][
                                "snapshotSha256"
                            ],
                            "scope_sha256": profile["scope_sha256"],
                            "approval_sha256": profile[
                                "approval_sha256"
                            ],
                            "target_product_ordinal": 1,
                            "target_product_id": profile[
                                "target_product_id"
                            ],
                            "profile_sha256": canonical_contract_sha256(
                                profile
                            ),
                            "account_ref_hash": scope_payload["account"][
                                "accountContextHash"
                            ],
                            "shop_id": scope_payload["shop"]["shopId"],
                            "runtime_instance_id": scope_payload["runtime"][
                                "runtimeInstanceId"
                            ],
                            "browser_session_id": scope_payload["runtime"][
                                "browserSessionId"
                            ],
                            "git_head": scope_payload["git"]["head"],
                            "worktree": scope_payload["worktree"],
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    rebuilt_attempt_identity = None
                if rebuilt_attempt_identity != _normalized_sha256(
                    attempt.get("attempt_identity_sha256")
                ):
                    drift = True

            receipt: dict[str, Any] | None = None
            attempt_status = str(attempt.get("status") or "")
            if attempt_status == "sealed":
                if not receipt_row:
                    drift = True
                else:
                    loaded = loads(receipt_row.get("receipt_json"), None)
                    if isinstance(loaded, dict):
                        receipt = loaded
                    else:
                        drift = True
                    if receipt is not None:
                        receipt_hash = receipt.get(
                            "discovery_receipt_sha256"
                        )
                        body = {
                            key: value
                            for key, value in receipt.items()
                            if key != "discovery_receipt_sha256"
                        }
                        expected_hash = canonical_contract_sha256(body)
                        try:
                            expected_ordered_product_ids = [
                                int(item["productId"])
                                for item in scope_payload["orderedProducts"]
                            ]
                            expected_snapshot_id = int(
                                scope_payload["snapshot"]["snapshotId"]
                            )
                            expected_snapshot_sha256 = _normalized_sha256(
                                scope_payload["snapshot"]["snapshotSha256"]
                            )
                            expected_account_ref_hash = scope_payload[
                                "account"
                            ]["accountContextHash"]
                            expected_shop_id = scope_payload["shop"]["shopId"]
                            expected_shop_name = scope_payload["shop"][
                                "shopName"
                            ]
                            expected_git_head = scope_payload["git"]["head"]
                            expected_worktree = scope_payload["worktree"]
                            expected_runtime = scope_payload["runtime"]
                        except (KeyError, TypeError, ValueError):
                            expected_ordered_product_ids = None
                            expected_snapshot_id = 0
                            expected_snapshot_sha256 = None
                            expected_account_ref_hash = None
                            expected_shop_id = None
                            expected_shop_name = None
                            expected_git_head = None
                            expected_worktree = None
                            expected_runtime = None
                            drift = True
                        row_pairs = (
                            (
                                receipt.get("schema_version"),
                                _PATH_B_DISCOVERY_RECEIPT_SCHEMA,
                            ),
                            (
                                _normalized_sha256(receipt_hash),
                                expected_hash,
                            ),
                            (
                                _normalized_sha256(
                                    receipt_row.get(
                                        "discovery_receipt_sha256"
                                    )
                                ),
                                expected_hash,
                            ),
                            (
                                _normalized_sha256(
                                    attempt.get(
                                        "discovery_receipt_sha256"
                                    )
                                ),
                                expected_hash,
                            ),
                            (
                                int(receipt.get("task_id") or 0),
                                int(attempt["task_id"]),
                            ),
                            (
                                int(receipt.get("job_id") or 0),
                                int(attempt.get("job_id") or 0),
                            ),
                            (
                                int(receipt.get("product_id") or 0),
                                int(attempt.get("product_id") or 0),
                            ),
                            (
                                int(receipt.get("snapshot_id") or 0),
                                expected_snapshot_id,
                            ),
                            (
                                _normalized_sha256(
                                    receipt.get("snapshot_sha256")
                                ),
                                expected_snapshot_sha256,
                            ),
                            (
                                receipt.get("ordered_product_ids"),
                                expected_ordered_product_ids,
                            ),
                            (
                                receipt.get("account_ref_hash"),
                                expected_account_ref_hash,
                            ),
                            (receipt.get("shop_id"), expected_shop_id),
                            (
                                receipt.get("shop_name"),
                                expected_shop_name,
                            ),
                            (receipt.get("git_head"), expected_git_head),
                            (receipt.get("worktree"), expected_worktree),
                            (receipt.get("runtime"), expected_runtime),
                            (
                                _normalized_sha256(
                                    receipt.get("scope_sha256")
                                ),
                                _normalized_sha256(
                                    attempt.get("scope_sha256")
                                ),
                            ),
                            (
                                _normalized_sha256(
                                    receipt.get("discovery_key_sha256")
                                ),
                                _normalized_sha256(
                                    attempt.get("discovery_key_sha256")
                                ),
                            ),
                            (
                                receipt.get("physical_mutation_count"),
                                1,
                            ),
                            (receipt.get("save1_count"), 1),
                            (receipt.get("save2_count"), 0),
                            (
                                receipt.get(
                                    "other_product_mutation_count"
                                ),
                                0,
                            ),
                            (receipt.get("publish_request_count"), 0),
                            (receipt.get("published"), False),
                            (receipt.get("unknown_count"), 0),
                            (
                                canonical_contract_sha256(
                                    receipt.get("field_readbacks")
                                ),
                                _normalized_sha256(
                                    receipt.get("field_readbacks_sha256")
                                ),
                            ),
                            (
                                canonical_contract_sha256(
                                    receipt.get("unpublished_readback")
                                ),
                                _normalized_sha256(
                                    receipt.get(
                                        "unpublished_readback_sha256"
                                    )
                                ),
                            ),
                        )
                        if any(
                            observed != expected
                            for observed, expected in row_pairs
                        ):
                            drift = True
                        try:
                            canonical_readbacks = [
                                item.to_dict()
                                for item in validated_field_readbacks_from_payload(
                                    receipt.get("field_readbacks"),
                                    require_nonempty=True,
                                    reason_prefix="DISCOVERY_SAVE1",
                                )
                            ]
                        except ReceiptValidationError:
                            canonical_readbacks = None
                            drift = True
                        if canonical_readbacks != receipt.get(
                            "field_readbacks"
                        ):
                            drift = True
                        plan = (
                            payload.get("plan_snapshot")
                            if isinstance(payload, Mapping)
                            else None
                        )
                        item_snapshots = (
                            plan.get("item_snapshots")
                            if isinstance(plan, Mapping)
                            else None
                        )
                        matching_items = [
                            item
                            for item in item_snapshots or []
                            if isinstance(item, Mapping)
                            and str(item.get("product_id") or "")
                            == str(attempt.get("product_id") or "")
                        ]
                        stage_facts = (
                            matching_items[0].get(
                                "real_write_stage_facts"
                            )
                            if len(matching_items) == 1
                            and isinstance(
                                matching_items[0].get(
                                    "real_write_stage_facts"
                                ),
                                Mapping,
                            )
                            else None
                        )
                        expected_save1_facts = (
                            stage_facts.get("SAVE1")
                            if isinstance(stage_facts, Mapping)
                            else None
                        )
                        expected_after_by_field = (
                            {
                                str(item.get("field_key") or ""):
                                _normalized_sha256(
                                    item.get("expected_sha256")
                                )
                                for item in expected_save1_facts
                                if isinstance(item, Mapping)
                            }
                            if isinstance(expected_save1_facts, list)
                            and expected_save1_facts
                            else None
                        )
                        actual_after_by_field = (
                            {
                                str(item["field_key"]):
                                canonical_contract_sha256(
                                    item.get("after_value")
                                )
                                for item in canonical_readbacks
                            }
                            if isinstance(canonical_readbacks, list)
                            else None
                        )
                        if (
                            not isinstance(expected_after_by_field, dict)
                            or "" in expected_after_by_field
                            or None in expected_after_by_field.values()
                            or expected_after_by_field
                            != actual_after_by_field
                        ):
                            drift = True
                        if (
                            int(receipt_row.get("attempt_id") or 0)
                            != int(attempt["id"])
                            or int(receipt_row.get("task_id") or 0)
                            != int(attempt["task_id"])
                            or int(receipt_row.get("job_id") or 0)
                            != int(attempt.get("job_id") or 0)
                            or int(receipt_row.get("product_id") or 0)
                            != int(attempt.get("product_id") or 0)
                            or str(receipt_row.get("status") or "")
                            != "sealed"
                        ):
                            drift = True
                        row_receipt_fields = (
                            "attempt_identity_sha256",
                            "scope_sha256",
                            "approval_sha256",
                            "discovery_key_sha256",
                            "profile_sha256",
                            "command_id",
                            "authorization_lease_id",
                            "mutation_id",
                            "ledger_entry_id",
                            "first_save_command_sha256",
                            "first_save_action_result_sha256",
                            "save_authority_sha256",
                            "verification_command_sha256",
                            "save_verification_context_sha256",
                            "field_readbacks_sha256",
                            "unpublished_readback_sha256",
                            "first_save_intent_handshake_sha256",
                            "unpublished_action_result_sha256",
                            "leaf_proof_manifest_sha256",
                        )
                        if any(
                            receipt.get(key) != receipt_row.get(key)
                            for key in row_receipt_fields
                        ):
                            drift = True
                        try:
                            self._validate_sealed_discovery_authority(
                                conn,
                                attempt=attempt,
                                receipt_row=receipt_row,
                                receipt=receipt,
                            )
                        except (TypeError, ValueError):
                            drift = True
                if (
                    str(task.get("status") or "") != "stopped"
                    or str(scope.get("status") or "")
                    != "discovery_sealed"
                ):
                    drift = True
            elif attempt_status == "armed":
                if (
                    str(scope.get("status") or "") != "consumed"
                    or str(scope.get("purpose") or "") != "discovery"
                    or str(scope.get("approval_stage") or "") != "discovery"
                    or str(task.get("status") or "") != "running"
                    or receipt_row is not None
                ):
                    drift = True
            elif attempt_status not in {"unknown", "blocked"}:
                drift = True

            status = (
                "UNKNOWN"
                if drift
                else _discovery_attempt_public_status(
                    attempt_status,
                    task_status=task.get("status") if task else None,
                )
            )
            result: dict[str, Any] = {
                "ok": True,
                "status": status,
                "reasonCode": (
                    "DISCOVERY_PERSISTENCE_DRIFT"
                    if drift
                    else attempt.get("reason_code") or "OK"
                ),
                "taskId": int(attempt["task_id"]),
                "discoveryKeySha256": str(
                    attempt["discovery_key_sha256"]
                ),
                "scopeSha256": str(attempt["scope_sha256"]),
                "discoveryReceiptSha256": (
                    str(attempt["discovery_receipt_sha256"])
                    if attempt.get("discovery_receipt_sha256")
                    else None
                ),
            }
            if not drift and status == "DISCOVERY_SEALED" and receipt is not None:
                result["receipt"] = receipt
            return result

    def get_real_dxm_path_b_discovery_by_key_sha256(
        self,
        discovery_key_sha256: str,
    ) -> dict[str, Any] | None:
        """Return a revalidated public recovery projection for one opaque key."""

        return self._get_real_dxm_path_b_discovery(
            lookup_column="discovery_key_sha256",
            lookup_sha256=discovery_key_sha256,
        )

    def get_real_dxm_path_b_discovery_by_receipt_sha256(
        self,
        discovery_receipt_sha256: str,
    ) -> dict[str, Any] | None:
        """Return the same projection for Formal lineage verification."""

        return self._get_real_dxm_path_b_discovery(
            lookup_column="discovery_receipt_sha256",
            lookup_sha256=discovery_receipt_sha256,
        )

    def mark_real_dxm_path_b_discovery_unknown(
        self,
        task_id: int,
        *,
        reason_code: str,
    ) -> dict[str, Any]:
        """Terminally quarantine an armed attempt after ambiguous runner exit."""

        normalized_reason = str(reason_code or "UNKNOWN").strip().upper()
        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id <= 0
            or len(normalized_reason) < 3
            or len(normalized_reason) > 96
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                for character in normalized_reason
            )
        ):
            return {
                "ok": False,
                "status": "UNKNOWN",
                "reason_code": "DISCOVERY_UNKNOWN_INPUT_INVALID",
            }
        now = now_iso()
        with connection() as conn:
            migrate_real_dxm_write_scopes(conn)
            migrate_real_dxm_path_b_discovery_receipts(conn)
            conn.execute("BEGIN IMMEDIATE")
            attempt = conn.execute(
                """
                SELECT * FROM real_dxm_path_b_discovery_attempts
                 WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if not attempt:
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "reason_code": "DISCOVERY_ATTEMPT_NOT_FOUND",
                }
            status = str(attempt.get("status") or "")
            if status == "sealed":
                return {
                    "ok": True,
                    "status": "DISCOVERY_SEALED",
                    "reason_code": "PATH_B_SAVE1_DISCOVERY_SEALED",
                    "receipt_sha256": attempt.get(
                        "discovery_receipt_sha256"
                    ),
                }
            if status in {"unknown", "blocked"}:
                return {
                    "ok": True,
                    "status": status.upper(),
                    "reason_code": attempt.get("reason_code")
                    or normalized_reason,
                    "idempotent": True,
                }
            if status != "armed":
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "reason_code": "DISCOVERY_ATTEMPT_STATE_INVALID",
                }
            attempt_updated = conn.execute(
                """
                UPDATE real_dxm_path_b_discovery_attempts
                   SET status='unknown', reason_code=?, terminal_at=?, updated_at=?
                 WHERE id=? AND status='armed'
                   AND discovery_receipt_sha256 IS NULL
                """,
                (normalized_reason, now, now, attempt["id"]),
            )
            scope_updated = conn.execute(
                """
                UPDATE real_dxm_write_scopes
                   SET status='unknown', approval_stage='discovery_unknown',
                       updated_at=?
                 WHERE scope_sha256=? AND status='consumed'
                   AND purpose='discovery'
                """,
                (now, attempt["scope_sha256"]),
            )
            task = conn.execute(
                "SELECT status, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if not task:
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "reason_code": "DISCOVERY_CURRENT_TASK_MISSING",
                }
            payload = loads(task["payload_json"], {})
            next_payload = dict(payload)
            next_payload["runner_dispatch"] = self._released_runner_dispatch(
                payload.get("runner_dispatch"),
                released_at=now,
                reason="path_b_save1_discovery_unknown",
            )
            task_updated = conn.execute(
                """
                UPDATE tasks
                   SET status='needs_manual_review', payload_json=?, updated_at=?
                 WHERE id=? AND status IN (
                     'running', 'pause_requested', 'stop_requested',
                     'failed', 'needs_manual_review'
                 )
                """,
                (dumps(next_payload), now, task_id),
            )
            conn.execute(
                """
                UPDATE jobs
                   SET status='needs_manual_review',
                       error_code='UNKNOWN',
                       error_detail=?, updated_at=?
                 WHERE task_id=? AND status='running'
                """,
                (normalized_reason, now, task_id),
            )
            if (
                attempt_updated.rowcount != 1
                or scope_updated.rowcount != 1
                or task_updated.rowcount != 1
            ):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "status": "UNKNOWN",
                    "reason_code": "DISCOVERY_UNKNOWN_CAS_CONFLICT",
                }
        return {
            "ok": True,
            "status": "UNKNOWN",
            "reason_code": normalized_reason,
        }

    def add_receipt(self, receipt: dict[str, Any]) -> int:
        """
        Persist a CanonicalReceipt dict to the canonical_receipts table.
        Returns the inserted row id.
        """
        now = now_iso()
        with connection() as conn:
            migrate_canonical_receipts(conn)
            cursor = self._insert_canonical_receipt(conn, receipt, now=now)
            return cursor.lastrowid or 0

    @staticmethod
    def _insert_canonical_receipt(
        conn: Any,
        receipt: Mapping[str, Any],
        *,
        now: str,
        verification_command: Mapping[str, Any] | None = None,
        verification_action_result: Mapping[str, Any] | None = None,
    ) -> Any:
        """Insert one canonical receipt using the caller's transaction."""

        return conn.execute(
            """
            INSERT INTO canonical_receipts (
                task_id, job_id, product_id, receipt_kind, save_stage,
                parent_canonical_receipt_sha256, scope_sha256,
                mode, claim_mark,
                canonical_receipt_sha256, started_at, completed_at,
                job_status, error_code, error_detail, needs_manual_review,
                verification_command_sha256,
                verification_action_result_sha256,
                verification_command_json, verification_action_result_json,
                receipt_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?)
            """,
            (
                receipt.get("task_id"),
                receipt.get("job_id"),
                receipt.get("product_id"),
                receipt.get("receipt_kind") or "product_aggregate",
                receipt.get("save_stage"),
                receipt.get("parent_canonical_receipt_sha256"),
                receipt.get("scope_sha256"),
                receipt.get("mode"),
                receipt.get("claim_mark"),
                receipt.get("canonical_receipt_sha256"),
                receipt.get("started_at"),
                receipt.get("completed_at"),
                receipt.get("job_status"),
                receipt.get("error_code"),
                receipt.get("error_detail"),
                1 if receipt.get("needs_manual_review") else 0,
                (
                    canonical_contract_sha256(verification_command)
                    if isinstance(verification_command, Mapping)
                    else None
                ),
                (
                    canonical_contract_sha256(verification_action_result)
                    if isinstance(verification_action_result, Mapping)
                    else None
                ),
                (
                    dumps(dict(verification_command))
                    if isinstance(verification_command, Mapping)
                    else None
                ),
                (
                    dumps(dict(verification_action_result))
                    if isinstance(verification_action_result, Mapping)
                    else None
                ),
                dumps(dict(receipt)),
                now,
                now,
            ),
        )

    @staticmethod
    def _build_canonical_save_stage_receipt(
        conn: Any,
        raw_save: Mapping[str, Any],
        *,
        task_id: int,
        job_id: int,
        product_id: int | None,
        scope_sha256: str,
        save_stage: str,
        verification_command: Mapping[str, Any] | None = None,
        verification_action_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build one canonical stage wrapper from a verified SAVE pair."""

        expected = {
            "SAVE1": (
                ReceiptPhase.PHASE_1_FIRST_SAVE,
                "SAVE_ONLY",
                "VERIFY_SAVE1_NOT_PUBLISHED",
            ),
            "SAVE2": (
                ReceiptPhase.PHASE_2_SECOND_SAVE,
                "SAVE2_ONLY",
                "VERIFY_SAVE2_NOT_PUBLISHED",
            ),
        }.get(save_stage)
        normalized_scope = _normalized_sha256(scope_sha256)
        if expected is None or normalized_scope is None:
            raise ValueError("canonical SAVE stage/scope is invalid")
        expected_phase, expected_state, expected_verification_state = expected
        validated_save = SaveReceipt.from_dict(raw_save)
        nested_digest = _normalized_sha256(
            raw_save.get("canonical_save_receipt_sha256")
        )
        if (
            validated_save.save_phase != expected_phase
            or nested_digest is None
            or _normalized_sha256(validated_save.finalize()) != nested_digest
            or validated_save.physical_mutation_count != 1
            or validated_save.publish_request_count != 0
            or validated_save.published is not False
        ):
            raise ValueError(f"{save_stage} canonical receipt is not acceptable")

        ledger_row = conn.execute(
            "SELECT * FROM mutation_dispatch_ledger WHERE id=?",
            (validated_save.ledger_entry_id,),
        ).fetchone()
        persisted_command = (
            loads(ledger_row.get("command_json"), None)
            if ledger_row
            else None
        )
        persisted_save_result = (
            loads(ledger_row.get("save_action_result_json"), None)
            if ledger_row
            else None
        )
        persisted_save_authority = (
            loads(ledger_row.get("save_authority_json"), None)
            if ledger_row
            else None
        )
        ledger_outcome = (
            loads(ledger_row.get("outcome_json"), None)
            if ledger_row
            else None
        )
        command_sha256 = (
            canonical_contract_sha256(persisted_command)
            if isinstance(persisted_command, Mapping)
            else None
        )
        save_result_sha256 = (
            canonical_contract_sha256(persisted_save_result)
            if isinstance(persisted_save_result, Mapping)
            else None
        )
        save_authority_sha256 = (
            canonical_contract_sha256(persisted_save_authority)
            if isinstance(persisted_save_authority, Mapping)
            else None
        )
        if not isinstance(verification_command, Mapping) or not isinstance(
            verification_action_result, Mapping
        ):
            persisted_stage_source = conn.execute(
                """
                SELECT verification_command_json,
                       verification_action_result_json
                  FROM canonical_receipts
                 WHERE task_id=? AND job_id=?
                   AND receipt_kind='save_stage' AND save_stage=?
                """,
                (task_id, job_id, save_stage),
            ).fetchone()
            verification_command = (
                loads(
                    persisted_stage_source.get("verification_command_json"),
                    None,
                )
                if persisted_stage_source
                else None
            )
            verification_action_result = (
                loads(
                    persisted_stage_source.get(
                        "verification_action_result_json"
                    ),
                    None,
                )
                if persisted_stage_source
                else None
            )
        verification_command_sha256 = (
            canonical_contract_sha256(verification_command)
            if isinstance(verification_command, Mapping)
            else None
        )
        verification_action_result_sha256 = (
            canonical_contract_sha256(verification_action_result)
            if isinstance(verification_action_result, Mapping)
            else None
        )
        rebuilt_save_receipt: Mapping[str, Any] | None = None
        if (
            isinstance(persisted_command, Mapping)
            and isinstance(persisted_save_result, Mapping)
            and isinstance(verification_command, Mapping)
            and isinstance(verification_action_result, Mapping)
            and ledger_row
        ):
            save_params = persisted_command.get("params")
            defaults = (
                save_params.get("defaults")
                if isinstance(save_params, Mapping)
                and isinstance(save_params.get("defaults"), Mapping)
                else None
            )
            verification_params = verification_command.get("params")
            try:
                save_command_contract = BrowserAgentCommand(
                    **dict(persisted_command)
                )
                verification_command_contract = BrowserAgentCommand(
                    **dict(verification_command)
                )
                validate_browser_agent_command(save_command_contract)
                validate_browser_agent_command(
                    verification_command_contract
                )
                validated_persisted_save_result = (
                    validate_action_result_envelope(
                        persisted_save_result,
                        expected_state=expected_state,
                        expected_action="save_only",
                        expected_page=(
                            "editor"
                            if save_stage == "SAVE1"
                            else "semi_managed"
                        ),
                        execution_mode="batch_draft_save",
                        expected_runtime_id=(
                            save_command_contract.runtime_id
                        ),
                        expected_execution_payload=(
                            defaults.get("_frozen_execution_payload")
                            if isinstance(defaults, Mapping)
                            else None
                        ),
                        expected_target_identity=(
                            save_command_contract.params.get(
                                "target_identity"
                            )
                        ),
                        expected_store_name=(
                            save_command_contract.params.get("store_name")
                        ),
                        expected_target_hash=(
                            save_command_contract.target_hash
                        ),
                    )
                )
                save_page_identity = validated_persisted_save_result.get(
                    "page_identity"
                )
                validated_verification_action_result = (
                    validate_action_result_envelope(
                        verification_action_result,
                        expected_state=expected_verification_state,
                        expected_action="verify_not_published",
                        expected_page=(
                            "editor"
                            if save_stage == "SAVE1"
                            else "semi_managed"
                        ),
                        execution_mode="batch_draft_save",
                        expected_runtime_id=(
                            verification_command_contract.runtime_id
                        ),
                        expected_browser_session_id=(
                            save_page_identity.get("browser_session_id")
                            if isinstance(save_page_identity, Mapping)
                            else None
                        ),
                    )
                )
                frozen_verification_context = (
                    save_verification_facts_from_frozen_authority(
                        persisted_save_authority,
                        save_command=persisted_command,
                        ledger_entry=dict(ledger_row),
                        save_action_result_sha256=save_result_sha256,
                    )
                )
                persisted_verification_context = (
                    verification_params.get(
                        "save_verification_context"
                    )
                    if isinstance(verification_params, Mapping)
                    else None
                )
                if (
                    persisted_verification_context
                    != frozen_verification_context
                ):
                    raise ReceiptValidationError(
                        "SAVE_STAGE_VERIFICATION_AUTHORITY_DRIFT",
                        save_stage,
                    )
                rebuilt_save_receipt = (
                    build_save_receipt_from_verified_pair(
                        save_command=persisted_command,
                        ledger_entry=dict(ledger_row),
                        save_action_result=(
                            validated_persisted_save_result
                        ),
                        verification_action_result=(
                            validated_verification_action_result
                        ),
                        expected_execution_payload=(
                            defaults.get("_frozen_execution_payload")
                            if isinstance(defaults, Mapping)
                            else None
                        ),
                        expected_verification_context=(
                            verification_params.get(
                                "save_verification_context"
                            )
                            if isinstance(verification_params, Mapping)
                            else None
                        ),
                    ).to_persisted_dict()
                )
            except (
                ActionResultContractError,
                BatchCommandContractError,
                DispatchAuthorityError,
                MutationCommandContractError,
                ReceiptValidationError,
            ) as exc:
                raise ValueError(
                    f"{save_stage} persisted SAVE/VERIFY pair is invalid"
                ) from exc
        if (
            not ledger_row
            or ledger_row.get("status") != "DISPATCHED"
            or ledger_row.get("unknown_at") is not None
            or not (
                ledger_outcome is True
                or (
                    isinstance(ledger_outcome, Mapping)
                    and ledger_outcome.get("dispatched") is True
                )
            )
            or ledger_row.get("mutation_action") != "save_only_click"
            or ledger_row.get("command_state") != expected_state
            or str(ledger_row.get("task_id") or "") != str(task_id)
            or str(ledger_row.get("job_id") or "") != str(job_id)
            or ledger_row.get("mutation_id") != validated_save.mutation_id
            or ledger_row.get("command_id") != validated_save.action_grant_id
            or ledger_row.get("authorization_lease_id")
            != validated_save.save_lease_id
            or _normalized_sha256(ledger_row.get("target_hash"))
            != _normalized_sha256(validated_save.target_hash)
            or not isinstance(persisted_command, Mapping)
            or not isinstance(persisted_save_result, Mapping)
            or not isinstance(persisted_save_authority, Mapping)
            or not isinstance(verification_command, Mapping)
            or not isinstance(verification_action_result, Mapping)
            or verification_command_sha256 is None
            or verification_action_result_sha256 is None
            or rebuilt_save_receipt != dict(raw_save)
            or str(verification_command.get("task_id")) != str(task_id)
            or str(verification_command.get("job_id")) != str(job_id)
            or verification_command.get("state")
            != expected_verification_state
            or verification_command.get("action") != "verify_not_published"
            or verification_command.get("execution_mode")
            != "batch_draft_save"
            or verification_command.get("runtime_id")
            != persisted_command.get("runtime_id")
            or not isinstance(verification_command.get("params"), Mapping)
            or verification_command.get("params", {}).get("target_identity")
            != persisted_command.get("params", {}).get("target_identity")
            or verification_command.get("params", {}).get("store_name")
            != persisted_command.get("params", {}).get("store_name")
            or verification_action_result.get("attempted_state")
            != expected_verification_state
            or _normalized_sha256(ledger_row.get("command_sha256"))
            != command_sha256
            or _normalized_sha256(
                ledger_row.get("save_action_result_sha256")
            )
            != save_result_sha256
            or _normalized_sha256(ledger_row.get("save_authority_sha256"))
            != save_authority_sha256
            or str(persisted_command.get("task_id")) != str(task_id)
            or str(persisted_command.get("job_id")) != str(job_id)
            or persisted_command.get("state") != expected_state
            or persisted_command.get("action") != "save_only"
            or persisted_command.get("command_id")
            != validated_save.action_grant_id
            or persisted_command.get("authorization_lease_id")
            != validated_save.save_lease_id
            or _normalized_sha256(persisted_command.get("target_hash"))
            != _normalized_sha256(validated_save.target_hash)
            or not isinstance(ledger_row.get("save_success_recorded_at"), str)
            or not str(ledger_row.get("save_success_recorded_at") or "").strip()
        ):
            raise ValueError(f"{save_stage} mutation ledger binding is incomplete")

        task_row = conn.execute(
            "SELECT payload_json FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        task_payload = loads(task_row.get("payload_json"), {}) if task_row else {}
        real_authorization = (
            task_payload.get("real_dxm_write_authorization")
            if isinstance(task_payload, Mapping)
            and isinstance(task_payload.get("real_dxm_write_authorization"), Mapping)
            else None
        )
        job_rows = conn.execute(
            "SELECT id, product_id FROM jobs WHERE task_id=? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
        ordered_product_ids = [row.get("product_id") for row in job_rows]
        ordinal_matches = [
            ordinal
            for ordinal, row in enumerate(job_rows, start=1)
            if row.get("id") == job_id and row.get("product_id") == product_id
        ]
        raw_leases = (
            real_authorization.get("save_leases")
            if isinstance(real_authorization, Mapping)
            else None
        )
        lease_matches = [
            lease
            for lease in raw_leases or []
            if isinstance(lease, Mapping)
            and lease.get("product_id") == product_id
            and lease.get("product_ordinal")
            == (ordinal_matches[0] if len(ordinal_matches) == 1 else None)
            and lease.get("save_stage") == save_stage
            and _normalized_sha256(lease.get("scope_sha256"))
            == normalized_scope
            and _normalized_sha256(lease.get("lease_id"))
            == _normalized_sha256(validated_save.save_lease_id)
            and lease.get("single_use") is True
        ]
        if (
            not isinstance(real_authorization, Mapping)
            or real_authorization.get("schema")
            != "real_dxm_write_authorization.v1"
            or real_authorization.get("publish_allowed") is not False
            or _normalized_sha256(real_authorization.get("scope_sha256"))
            != normalized_scope
            or real_authorization.get("ordered_product_ids")
            != ordered_product_ids
            or not isinstance(raw_leases, list)
            or len(raw_leases) != 6
            or len(ordinal_matches) != 1
            or len(lease_matches) != 1
        ):
            raise ValueError(f"{save_stage} scope lease binding is incomplete")

        unsigned_stage_receipt = {
            "receipt_kind": "save_stage",
            "task_id": task_id,
            "job_id": job_id,
            "product_id": product_id,
            "scope_sha256": normalized_scope,
            "save_stage": save_stage,
            "mode": "batch_draft_save",
            "claim_mark": normalized_scope,
            "canonical_save_receipt_sha256": nested_digest,
            "verification_command_sha256": verification_command_sha256,
            "verification_action_result_sha256": (
                verification_action_result_sha256
            ),
            "started_at": validated_save.dispatched_at,
            "completed_at": validated_save.completed_at,
            "job_status": "succeeded",
            "error_code": None,
            "error_detail": None,
            "needs_manual_review": False,
            "save_receipt": dict(raw_save),
        }
        return {
            "schema_version": "dxm.path-b.canonical-save-stage-receipt.v1",
            **unsigned_stage_receipt,
            "canonical_receipt_sha256": canonical_sha256(
                unsigned_stage_receipt
            ),
        }

    def persist_canonical_save_stage_receipt(
        self,
        task_id: int,
        job_id: int,
        product_id: int | None,
        *,
        save_stage: str,
        save_receipt: Mapping[str, Any],
        verification_command: Mapping[str, Any],
        verification_action_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist SAVE1/SAVE2 immediately after its independent VERIFY closes."""

        now = now_iso()
        with connection() as conn:
            migrate_canonical_receipts(conn)
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT status, mode, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            job = conn.execute(
                "SELECT status, product_id FROM jobs WHERE id=? AND task_id=?",
                (job_id, task_id),
            ).fetchone()
            payload = loads(task.get("payload_json"), {}) if task else {}
            real_authorization = (
                payload.get("real_dxm_write_authorization")
                if isinstance(payload, Mapping)
                and isinstance(payload.get("real_dxm_write_authorization"), Mapping)
                else None
            )
            scope_sha256 = (
                str(real_authorization.get("scope_sha256") or "")
                if isinstance(real_authorization, Mapping)
                else ""
            )
            scope_row = conn.execute(
                "SELECT task_id, status FROM real_dxm_write_scopes WHERE scope_sha256=?",
                (scope_sha256,),
            ).fetchone()
            if (
                not task
                or task.get("status") != "running"
                or task.get("mode") != "batch_draft_save"
                or not isinstance(payload, Mapping)
                or str(payload.get("path") or "").strip().upper() != "B"
                or not job
                or job.get("status") != "running"
                or job.get("product_id") != product_id
                or _normalized_sha256(scope_sha256) is None
                or not scope_row
                or int(scope_row.get("task_id") or 0) != task_id
                or scope_row.get("status") != "consumed"
            ):
                raise ValueError("SAVE stage persistence authority is not live")
            canonical_stage = self._build_canonical_save_stage_receipt(
                conn,
                save_receipt,
                task_id=task_id,
                job_id=job_id,
                product_id=product_id,
                scope_sha256=scope_sha256,
                save_stage=save_stage,
                verification_command=verification_command,
                verification_action_result=verification_action_result,
            )
            existing = conn.execute(
                """
                SELECT * FROM canonical_receipts
                 WHERE task_id=? AND job_id=? AND receipt_kind='save_stage'
                   AND save_stage=?
                """,
                (task_id, job_id, save_stage),
            ).fetchone()
            if existing:
                if (
                    _normalized_sha256(existing.get("canonical_receipt_sha256"))
                    != _normalized_sha256(
                        canonical_stage.get("canonical_receipt_sha256")
                    )
                    or loads(existing.get("receipt_json"), {}) != canonical_stage
                    or loads(
                        existing.get("verification_command_json"), None
                    )
                    != dict(verification_command)
                    or loads(
                        existing.get(
                            "verification_action_result_json"
                        ),
                        None,
                    )
                    != dict(verification_action_result)
                    or _normalized_sha256(
                        existing.get("verification_command_sha256")
                    )
                    != _normalized_sha256(
                        canonical_stage.get(
                            "verification_command_sha256"
                        )
                    )
                    or _normalized_sha256(
                        existing.get(
                            "verification_action_result_sha256"
                        )
                    )
                    != _normalized_sha256(
                        canonical_stage.get(
                            "verification_action_result_sha256"
                        )
                    )
                ):
                    raise ValueError("SAVE stage receipt persistence conflict")
                return canonical_stage
            self._insert_canonical_receipt(
                conn,
                canonical_stage,
                now=now,
                verification_command=verification_command,
                verification_action_result=verification_action_result,
            )
            return canonical_stage

    def _validate_persisted_save_stage_receipts(
        self,
        conn: Any,
        canonical_receipt: Mapping[str, Any],
        *,
        task_id: int,
        job_id: int,
        product_id: int | None,
        scope_sha256: str,
    ) -> None:
        """Require the aggregate receipt to match two already durable stages."""

        normalized_scope = _normalized_sha256(scope_sha256)
        parent_digest = _normalized_sha256(
            canonical_receipt.get("canonical_receipt_sha256")
        )
        parent_unsigned = {
            key: value
            for key, value in canonical_receipt.items()
            if key not in {"schema_version", "canonical_receipt_sha256"}
        }
        if (
            canonical_receipt.get("schema_version")
            != "dxm.path-b.canonical-receipt.v1"
            or normalized_scope is None
            or parent_digest is None
            or canonical_sha256(parent_unsigned) != parent_digest
            or canonical_receipt.get("task_id") != task_id
            or canonical_receipt.get("job_id") != job_id
            or canonical_receipt.get("product_id") != product_id
            or canonical_receipt.get("mode") != "batch_draft_save"
            or _normalized_sha256(canonical_receipt.get("claim_mark"))
            != normalized_scope
            or canonical_receipt.get("job_status") != "succeeded"
            or canonical_receipt.get("error_code") is not None
            or canonical_receipt.get("error_detail") is not None
            or canonical_receipt.get("needs_manual_review") is not False
        ):
            raise ValueError("canonical product receipt is not scope/identity bound")
        raw_saves = canonical_receipt.get("save_receipts")
        if not isinstance(raw_saves, list) or len(raw_saves) != 2:
            raise ValueError("canonical product receipt must contain exactly two SAVE receipts")
        stage_hashes: list[str] = []
        for raw_save, save_stage in zip(
            raw_saves,
            ("SAVE1", "SAVE2"),
            strict=True,
        ):
            if not isinstance(raw_save, Mapping):
                raise ValueError(f"{save_stage} canonical receipt is not an object")
            expected_stage = self._build_canonical_save_stage_receipt(
                conn,
                raw_save,
                task_id=task_id,
                job_id=job_id,
                product_id=product_id,
                scope_sha256=scope_sha256,
                save_stage=save_stage,
            )
            persisted = conn.execute(
                """
                SELECT * FROM canonical_receipts
                 WHERE task_id=? AND job_id=? AND receipt_kind='save_stage'
                   AND save_stage=?
                """,
                (task_id, job_id, save_stage),
            ).fetchone()
            if (
                not persisted
                or _normalized_sha256(persisted.get("canonical_receipt_sha256"))
                != _normalized_sha256(
                    expected_stage.get("canonical_receipt_sha256")
                )
                or loads(persisted.get("receipt_json"), {}) != expected_stage
            ):
                raise ValueError(f"{save_stage} persisted canonical receipt mismatch")
            persisted_parent = _normalized_sha256(
                persisted.get("parent_canonical_receipt_sha256")
            )
            if persisted_parent is not None and persisted_parent != parent_digest:
                raise ValueError(f"{save_stage} product receipt parent conflict")
            if persisted_parent is None:
                parent_bound = conn.execute(
                    """
                    UPDATE canonical_receipts
                       SET parent_canonical_receipt_sha256=?, updated_at=?
                     WHERE id=? AND receipt_kind='save_stage'
                       AND parent_canonical_receipt_sha256 IS NULL
                    """,
                    (parent_digest, now_iso(), persisted.get("id")),
                )
                if parent_bound.rowcount != 1:
                    raise ValueError(
                        f"{save_stage} product receipt parent compare-and-set failed"
                    )
            stage_hashes.append(expected_stage["canonical_receipt_sha256"])
        if len(set(stage_hashes)) != 2:
            raise ValueError("SAVE1/SAVE2 canonical stage receipt digest reused")

    def get_receipt(self, task_id: int, job_id: int) -> dict[str, Any] | None:
        """Retrieve the canonical receipt for a specific job, if it exists."""
        with connection() as conn:
            row = conn.execute(
                """
                SELECT receipt_json FROM canonical_receipts
                WHERE task_id=? AND job_id=?
                  AND receipt_kind='product_aggregate'
                ORDER BY id DESC LIMIT 1
                """,
                (task_id, job_id),
            ).fetchone()
            if row:
                return loads(row["receipt_json"], {})
            return None

    def list_receipts(self, task_id: int) -> list[dict[str, Any]]:
        """List all canonical receipts for a task."""
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM canonical_receipts
                WHERE task_id=?
                ORDER BY id DESC
                """,
                (task_id,),
            ).fetchall()
            results = []
            for row in rows:
                r = dict(row)
                r["receipt"] = loads(r.pop("receipt_json"), {})
                r["needs_manual_review"] = bool(r["needs_manual_review"])
                results.append(r)
            return results

    def revalidate_task_save_stage_authority(
        self,
        task_id: int,
    ) -> dict[str, Any]:
        """Rebuild every durable Formal SAVE/VERIFY stage from private sources."""

        failures: list[dict[str, Any]] = []
        validated_pairs: list[tuple[int, str]] = []
        with connection() as conn:
            migrate_canonical_receipts(conn)
            job_rows = conn.execute(
                "SELECT id FROM jobs WHERE task_id=? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
            expected_pairs = {
                (int(job.get("id") or 0), save_stage)
                for job in job_rows
                for save_stage in ("SAVE1", "SAVE2")
            }
            rows = conn.execute(
                """
                SELECT * FROM canonical_receipts
                 WHERE task_id=? AND receipt_kind='save_stage'
                 ORDER BY job_id ASC, save_stage ASC
                """,
                (task_id,),
            ).fetchall()
            for row in rows:
                receipt = loads(row.get("receipt_json"), None)
                stage = str(row.get("save_stage") or "")
                job_id = int(row.get("job_id") or 0)
                try:
                    if not isinstance(receipt, Mapping):
                        raise ValueError("stage receipt JSON is missing")
                    rebuilt = self._build_canonical_save_stage_receipt(
                        conn,
                        receipt.get("save_receipt")
                        if isinstance(receipt.get("save_receipt"), Mapping)
                        else {},
                        task_id=task_id,
                        job_id=job_id,
                        product_id=row.get("product_id"),
                        scope_sha256=str(row.get("scope_sha256") or ""),
                        save_stage=stage,
                    )
                    if (
                        rebuilt != dict(receipt)
                        or _normalized_sha256(
                            row.get("canonical_receipt_sha256")
                        )
                        != _normalized_sha256(
                            rebuilt.get("canonical_receipt_sha256")
                        )
                        or _normalized_sha256(
                            row.get("verification_command_sha256")
                        )
                        != _normalized_sha256(
                            rebuilt.get("verification_command_sha256")
                        )
                        or _normalized_sha256(
                            row.get(
                                "verification_action_result_sha256"
                            )
                        )
                        != _normalized_sha256(
                            rebuilt.get(
                                "verification_action_result_sha256"
                            )
                        )
                    ):
                        raise ValueError("stage receipt rebuild drift")
                    validated_pairs.append((job_id, stage))
                except (
                    KeyError,
                    ReceiptValidationError,
                    TypeError,
                    ValueError,
                ) as exc:
                    failures.append(
                        {
                            "job_id": job_id,
                            "save_stage": stage or None,
                            "reason_code": "SAVE_STAGE_AUTHORITY_DRIFT",
                            "detail": str(exc),
                        }
                    )
        return {
            "ok": (
                len(job_rows) == 3
                and len(rows) == 6
                and len(validated_pairs) == 6
                and set(validated_pairs) == expected_pairs
                and not failures
            ),
            "count": len(validated_pairs),
            "pairs": validated_pairs,
            "failures": failures,
        }

    def list_task_mutation_ledger(self, task_id: int) -> list[dict[str, Any]]:
        """Read persisted mutation authority rows for one task.

        Callers must explicitly project safe fields before exposing this data;
        command/outcome/authority JSON can contain runtime-only evidence.
        """

        with connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM mutation_dispatch_ledger
                     WHERE task_id=?
                     ORDER BY id ASC
                    """,
                    (str(task_id),),
                ).fetchall()
            ]

    def list_task_writer_fences(self, task_id: int) -> list[dict[str, Any]]:
        """Read the durable per-shop writer-fence lineage for one task."""

        with connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM writer_fences
                     WHERE task_id=?
                     ORDER BY id ASC
                    """,
                    (str(task_id),),
                ).fetchall()
            ]

    def add_exception(self, task_id: int, job_id: int | None, error_code: str, field_domain: str, title: str, detail: str, suggestion: str):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO exceptions (task_id, job_id, error_code, field_domain, title, detail, suggestion, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, job_id, error_code, field_domain, title, detail, suggestion, now, now),
            )

    def list_exceptions(self):
        with connection() as conn:
            return conn.execute(
                """
                SELECT exceptions.*
                  FROM exceptions
                  JOIN tasks ON tasks.id=exceptions.task_id
                 WHERE tasks.mode!='removed_workflow_legacy'
                 ORDER BY exceptions.id DESC LIMIT 200
                """
            ).fetchall()

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
        canonical_receipt: Mapping[str, Any] | None = None,
    ) -> JobFinalizationResult:
        now = now_iso()
        report_id: int | None = None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT status, mode, payload_json FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
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
                    task_payload = loads(task.get("payload_json"), {})
                    task_path = (
                        str(task_payload.get("path") or "").strip().upper()
                        if isinstance(task_payload, Mapping)
                        else ""
                    )
                    if (
                        task.get("mode") == "batch_draft_save"
                        and task_path == "B"
                        and canonical_receipt is None
                    ):
                        raise ValueError(
                            "Path B job success requires a canonical product receipt"
                        )
                    if canonical_receipt is not None and (
                        canonical_receipt.get("task_id") != task_id
                        or canonical_receipt.get("job_id") != job_id
                        or canonical_receipt.get("product_id") != product_id
                        or canonical_receipt.get("job_status") != "succeeded"
                    ):
                        raise ValueError(
                            "canonical receipt identity/status does not match job success"
                        )
                    if canonical_receipt is not None:
                        real_authorization = (
                            task_payload.get("real_dxm_write_authorization")
                            if isinstance(task_payload, Mapping)
                            and isinstance(
                                task_payload.get("real_dxm_write_authorization"),
                                Mapping,
                            )
                            else None
                        )
                        scope_sha256 = (
                            str(real_authorization.get("scope_sha256") or "")
                            if isinstance(real_authorization, Mapping)
                            else ""
                        )
                        scope_row = conn.execute(
                            """
                            SELECT task_id, status FROM real_dxm_write_scopes
                             WHERE scope_sha256=?
                            """,
                            (scope_sha256,),
                        ).fetchone()
                        if (
                            _normalized_sha256(scope_sha256) is None
                            or not scope_row
                            or int(scope_row.get("task_id") or 0) != task_id
                            or scope_row.get("status") != "consumed"
                        ):
                            raise ValueError(
                                "canonical receipt scope is not consumed by this task"
                            )
                        self._validate_persisted_save_stage_receipts(
                            conn,
                            canonical_receipt,
                            task_id=task_id,
                            job_id=job_id,
                            product_id=product_id,
                            scope_sha256=scope_sha256,
                        )
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
                        if canonical_receipt is not None:
                            self._insert_canonical_receipt(
                                conn,
                                canonical_receipt,
                                now=now,
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

    def finalize_job_unknown(
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
        """Persist a non-retryable unknown mutation outcome without counting it failed."""

        now = now_iso()
        report_id: int | None = None
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute(
                "SELECT status FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
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
                        and existing_report.get("status") == "unknown"
                        and job.get("status") == "unknown"
                    )
                    if already_terminal:
                        conflict_code = TerminalReportConflictError.conflict_code
                        reason = "unknown report and unknown job are already terminal"
                        report_id = int(existing_report["id"])
                    elif existing_report:
                        conflict_code = TerminalReportConflictError.conflict_code
                        reason = "an existing report prevents unknown finalization"
                        report_id = int(existing_report["id"])
                    else:
                        report_id = self._upsert_report(
                            conn,
                            task_id,
                            job_id,
                            product_id,
                            "unknown",
                            None,
                            save_result,
                            summary,
                            now,
                        )
                        updated = conn.execute(
                            """
                            UPDATE jobs
                               SET status='unknown', current_step_code='UNKNOWN',
                                   current_step_name='保存结果待人工核对', error_code=?,
                                   error_message=?, updated_at=?
                             WHERE id=? AND task_id=? AND status IN ('pending', 'running')
                            """,
                            (error_code, detail, now, job_id, task_id),
                        )
                        if updated.rowcount != 1:
                            raise RuntimeError("job unknown compare-and-set failed")
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
                               SET status='needs_manual_review',
                                   completed_jobs=(
                                       SELECT COUNT(*) FROM jobs
                                        WHERE task_id=? AND status IN ('succeeded', 'completed')
                                   ),
                                   failed_jobs=(
                                       SELECT COUNT(*) FROM jobs
                                        WHERE task_id=? AND status='failed'
                                   ),
                                   updated_at=?
                             WHERE id=? AND status IN ('running', 'paused', 'completed', 'partial_success')
                            """,
                            (task_id, task_id, now, task_id),
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
        if existing and existing.get('status') in {'failed', 'unknown'}:
            if status != existing.get('status'):
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
                rows = conn.execute(
                    """
                    SELECT reports.*
                      FROM reports
                      JOIN tasks ON tasks.id=reports.task_id
                     WHERE tasks.mode!='removed_workflow_legacy'
                     ORDER BY reports.id DESC LIMIT 200
                    """
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM reports WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
            for row in rows:
                row['published'] = _published_from_db(row['published'])
                row['save_result'] = loads(row.pop('save_result_json'), {})
                row['summary'] = loads(row.pop('summary_json'), {})
            return rows
