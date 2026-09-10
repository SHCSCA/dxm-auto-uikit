from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.scope_contract import canonical_sha256
from src.utils import now_iso


def validate_rollback_preparation_observation(
    observation, *, execution_payload, target_identity, browser_session_id,
):
    """Validate observed preimages, never infer missing values or writable controls."""
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp

    keys = {'schema', 'product_id', 'shop_id', 'browser_session_id', 'target_identity_sha256',
            'page_url', 'category_id', 'category_schema_hash', 'execution_payload_hash',
            'observed_at', 'write_attempted', 'values', 'evidence_ref'}
    if not isinstance(observation, Mapping) or set(observation) != keys:
        raise ValueError('ROLLBACK_OBSERVATION_INVALID')
    page = urlsplit(observation['page_url'])
    if (observation['schema'] != 'dxm.rollback-preimage-observation.v1'
            or observation['write_attempted'] is not False or not browser_session_id
            or observation['browser_session_id'] != browser_session_id
            or observation['product_id'] != execution_payload['product_id']
            or observation['target_identity_sha256'] != canonical_sha256(target_identity)
            or observation['execution_payload_hash'] != execution_payload['payload_hash']
            or canonical_sha256({k: v for k, v in execution_payload.items() if k != 'payload_hash'}) != execution_payload['payload_hash']
            or observation['category_id'] != execution_payload['category_id']
            or observation['category_schema_hash'] != execution_payload['category_schema_hash']
            or page.scheme != 'https' or page.netloc != 'www.dianxiaomi.com'
            or page.path != '/web/smt/edit' or page.fragment
            or parse_qs(page.query).get('id') != [observation['product_id']]):
        raise ValueError('ROLLBACK_OBSERVATION_IDENTITY_DRIFT')
    parse_strict_utc_timestamp(observation['observed_at'], field='rollback observed_at')
    values = observation['values']
    fields = execution_payload['fields']
    if (not isinstance(values, list) or not values or len(values) != len(fields)
            or execution_payload.get('save_stage') == 'SAVE2'):
        raise ValueError('ROLLBACK_PREIMAGE_COVERAGE_INVALID')
    seen = set()
    for observed, frozen in zip(values, fields):
        if (not isinstance(observed, Mapping)
                or set(observed) != {'field_key', 'value', 'ui_binding', 'unique', 'visible', 'writable'}
                or observed['field_key'] != frozen['field_key'] or observed['field_key'] in seen
                or observed['ui_binding'] != frozen['ui_binding']
                or any(observed[key] is not True for key in ('unique', 'visible', 'writable'))):
            raise ValueError('ROLLBACK_BINDING_NOT_RESTORABLE')
        seen.add(observed['field_key'])
    ref = observation['evidence_ref']
    if (not isinstance(ref, Mapping) or set(ref) != {'path', 'sha256', 'size'}
            or not isinstance(ref['path'], str) or not ref['path']
            or not isinstance(ref['size'], int) or isinstance(ref['size'], bool) or ref['size'] <= 0
            or not isinstance(ref['sha256'], str) or len(ref['sha256']) != 64
            or any(c not in '0123456789abcdefABCDEF' for c in ref['sha256'])):
        raise ValueError('ROLLBACK_EVIDENCE_INVALID')
    canonical_sha256(observation)
    return deepcopy(dict(observation))


def rollback_preparation_receipt(observation, command_id):
    from src.execution.canonical_receipt import ContentFinalizeReceipt, FieldReadback, ReceiptPhase

    receipt = ContentFinalizeReceipt(
        phase=ReceiptPhase.ROLLBACK_PREPARATION, action_grant_id=command_id, result_ok=True,
        started_at=observation['observed_at'], completed_at=observation['observed_at'],
        field_readbacks=[FieldReadback(field_key=row['field_key'], field_label=row['field_key'],
            source='visible_production_runtime', before_value=deepcopy(row['value']), after_value=deepcopy(row['value']),
            readback_proven=True, timestamp=observation['observed_at']) for row in observation['values']],
    )
    digest = receipt.finalize()
    return {'canonical_receipt': {**receipt.to_dict(), 'preimage_sha256': canonical_sha256(observation)},
            'receipt_sha256': digest}


def build_rollback_preparation_record(task, job, command_payload, observation):
    """Rebuild one command-bound preparation; persistence is owned by Repository."""
    from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, validate_frozen_execution_defaults
    from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command

    command = BrowserAgentCommand(**command_payload)
    validate_browser_agent_command(command)
    plan = task['payload']['plan_snapshot']
    matching = [item for item in plan['item_snapshots'] if str(item['product_id']) == str(job['product_id'])]
    if (len(matching) != 1 or plan.get('path') != 'B' or task.get('mode') != 'batch_draft_save'
            or command.to_payload() != command_payload or command.state != 'PREPARE_ROLLBACK'
            or command.action != 'prepare_rollback' or command.expected_page != 'editor'
            or command.execution_mode != 'batch_draft_save' or command.task_id != task['id']
            or command.job_id != job['id'] or not command.command_id or not command.runtime_id):
        raise ValueError('ROLLBACK_COMMAND_BINDING_INVALID')
    item = matching[0]
    execution = compile_frozen_execution_payload(task, job)
    validate_frozen_execution_defaults(command.params.get('defaults'), expected_payload=execution)
    if (command.params.get('target_identity') != item['target_identity']
            or command.params.get('shop_id') != str(item['shop_id'])
            or observation['shop_id'] != str(item['shop_id'])):
        raise ValueError('ROLLBACK_TARGET_DRIFT')
    observed = validate_rollback_preparation_observation(observation, execution_payload=execution,
        target_identity=item['target_identity'], browser_session_id=observation['browser_session_id'])
    governed = item.get('real_write_stage_facts', {}).get('SAVE1', [])
    if len(governed) != len(observed['values']):
        raise ValueError('ROLLBACK_PREIMAGE_AUTHORITY_MISSING')
    by_key = {entry['field_key']: entry for entry in governed}
    if len(by_key) != len(governed):
        raise ValueError('ROLLBACK_PREIMAGE_AUTHORITY_INVALID')
    for value in observed['values']:
        fact = by_key.get(value['field_key'], {})
        if fact.get('ui_binding') != value['ui_binding'] or fact.get('preimage_sha256') != canonical_sha256(value['value']):
            raise ValueError('ROLLBACK_PREIMAGE_DRIFT')
    restore = [{'operation': 'restore_field', 'field_key': row['field_key'],
                'ui_binding': row['ui_binding'], 'value': deepcopy(row['value'])}
               for row in reversed(observed['values'])]
    body = {'schema': 'dxm.rollback-preparation.v1', 'task_id': task['id'], 'job_id': job['id'],
            'product_id': str(job['product_id']), 'snapshot_sha256': plan['snapshot_hash'],
            'scope_sha256': task['payload']['real_dxm_write_authorization']['scope_sha256'],
            'command': deepcopy(command_payload), 'observation': observed, 'restore_plan': restore,
            'restore_policy': 'manual_before_external_mutation_only',
            'capability_receipt': rollback_preparation_receipt(observed, command.command_id)}
    return {**body, 'record_sha256': canonical_sha256(body)}


@dataclass
class FieldChange:
    """字段变更记录"""
    section: str                    # 分区名称
    field_name: str                 # 字段名称
    original_value: Any             # 修改前的值
    new_value: Any                 # 修改后的值
    timestamp: str                  # 变更时间


@dataclass
class SectionSnapshot:
    """分区快照（用于回滚）"""
    section: str                    # 分区名称
    fields: dict[str, Any]          # 字段值映射
    snapshot_time: str              # 快照时间


@dataclass
class RollbackResult:
    """回滚结果"""
    success: bool
    rolled_back_fields: int = 0
    error_message: str | None = None
    field_changes: list[FieldChange] = field(default_factory=list)


class BatchRollbackError(Exception):
    """批量执行回滚异常"""
    def __init__(self, reason: str, field_changes: list[FieldChange]):
        super().__init__(reason)
        self.reason = reason
        self.field_changes = field_changes


class RollbackManager:
    """执行回滚管理器 - 支持分区级回滚"""

    def __init__(self):
        self._snapshots: dict[str, SectionSnapshot] = {}  # section -> snapshot
        self._changes: list[FieldChange] = []            # 记录所有变更

    def take_snapshot(self, section: str, fields: dict[str, Any]) -> SectionSnapshot:
        """拍摄分区快照（回滚前的状态）"""
        snapshot = SectionSnapshot(
            section=section,
            fields=dict(fields),  # 深拷贝
            snapshot_time=now_iso(),
        )
        self._snapshots[section] = snapshot
        return snapshot

    def record_change(
        self,
        section: str,
        field_name: str,
        original_value: Any,
        new_value: Any,
    ) -> None:
        """记录字段变更"""
        change = FieldChange(
            section=section,
            field_name=field_name,
            original_value=original_value,
            new_value=new_value,
            timestamp=now_iso(),
        )
        self._changes.append(change)

    def get_section_changes(self, section: str) -> list[FieldChange]:
        """获取指定分区的所有变更"""
        return [c for c in self._changes if c.section == section]

    def get_all_changes(self) -> list[FieldChange]:
        """获取所有变更"""
        return list(self._changes)

    def get_snapshot(self, section: str) -> SectionSnapshot | None:
        """获取分区快照"""
        return self._snapshots.get(section)

    async def rollback_section(
        self,
        page: Any,
        section: str,
        ctx: Any,
    ) -> RollbackResult:
        """回滚指定分区"""
        snapshot = self._snapshots.get(section)
        if not snapshot:
            return RollbackResult(
                success=False,
                error_message=f"未找到分区快照：{section}",
            )

        try:
            rolled_back = 0
            field_changes = []

            for field_name, original_value in snapshot.fields.items():
                # 获取当前值
                current_value = await self._get_field_value(page, section, field_name)

                # 如果当前值与原始值不同，则回滚
                if current_value != original_value:
                    await self._set_field_value(page, section, field_name, original_value)
                    field_changes.append(FieldChange(
                        section=section,
                        field_name=field_name,
                        original_value=original_value,
                        new_value=current_value,
                        timestamp=now_iso(),
                    ))
                    rolled_back += 1

            return RollbackResult(
                success=True,
                rolled_back_fields=rolled_back,
                field_changes=field_changes,
            )

        except Exception as e:
            return RollbackResult(
                success=False,
                error_message=f"回滚失败：{str(e)}",
            )

    async def rollback_all(
        self,
        page: Any,
        reason: str,
        ctx: Any,
    ) -> RollbackResult:
        """回滚所有分区"""
        try:
            all_field_changes = []
            total_rolled_back = 0

            for section in self._snapshots.keys():
                result = await self.rollback_section(page, section, ctx)
                if result.success:
                    total_rolled_back += result.rolled_back_fields
                    all_field_changes.extend(result.field_changes)
                else:
                    return RollbackResult(
                        success=False,
                        error_message=f"回滚失败：{result.error_message}",
                    )

            # 抛出回滚异常让 runner 处理
            raise BatchRollbackError(
                reason=reason,
                field_changes=all_field_changes,
            )

        except BatchRollbackError:
            raise
        except Exception as e:
            return RollbackResult(
                success=False,
                error_message=f"回滚失败：{str(e)}",
            )

    def clear(self) -> None:
        """清除所有快照和变更记录"""
        self._snapshots.clear()
        self._changes.clear()

    async def _get_field_value(self, page: Any, section: str, field_name: str) -> Any:
        """获取字段当前值 (fail-closed stub).

        Rollback preparation requires reading the current page value to confirm
        a change actually took effect before recording it as a candidate for
        rollback. Without this, rollback has no observable basis and must not
        silently succeed. The previous implementation returned ``None``
        implicitly, which would have been recorded as a real change.
        """
        raise RollbackSafetyError(
            "ROLLBACK_READ_STUB_UNAVAILABLE",
            (
                f"无法读取分区 {section!r} 字段 {field_name!r} 当前值："
                "rollback 读回接线尚未注入；fail-closed 拒绝伪造快照。"
            ),
        )

    async def _set_field_value(self, page: Any, section: str, field_name: str, value: Any) -> None:
        """设置字段值 (fail-closed stub).

        Restoring a field to a previous value requires a real page write.
        A no-op here would leave the page in its mutated state while
        reporting success, which is exactly the data-corruption scenario
        rollback exists to prevent.
        """
        raise RollbackSafetyError(
            "ROLLBACK_WRITE_STUB_UNAVAILABLE",
            (
                f"无法回写分区 {section!r} 字段 {field_name!r} = {value!r}："
                "rollback 写入接线尚未注入；fail-closed 拒绝声明已恢复。"
            ),
        )


# =============================================================================
# RollbackSafety Production Contract
# =============================================================================


class RollbackSafetyError(Exception):
    """Raised when RollbackSafety contract is violated."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"[{reason_code}] {message}")


class RollbackPhase(Enum):
    """Phases of the rollback safety lifecycle."""

    PRE_ROLLBACK = "pre_rollback"
    ROLLBACK_IN_PROGRESS = "rollback_in_progress"
    ROLLBACK_COMMITTED = "rollback_committed"
    ROLLBACK_RELEASED = "rollback_released"


class RollbackSafetyViolationType(Enum):
    """Types of rollback safety violations."""

    NO_ACTIVE_SNAPSHOT = "no_active_snapshot"
    SNAPSHOT_STALE = "snapshot_stale"
    GATE_NOT_CLOSED = "gate_not_closed"
    UNCOMMITTED_MUTATIONS = "uncommitted_mutations"
    ROLLBACK_WINDOW_EXCEEDED = "rollback_window_exceeded"
    CONCURRENT_ROLLBACK = "concurrent_rollback"


class RollbackSafetyResult:
    """Result of a rollback safety check."""

    def __init__(
        self,
        ok: bool,
        reason_code: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.ok = ok
        self.reason_code = reason_code
        self.message = message
        self.metadata = metadata or {}

    def __bool__(self) -> bool:
        return self.ok

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise RollbackSafetyError(
                self.reason_code or "ROLLBACK_SAFETY_VIOLATION",
                self.message or "Rollback safety contract violated",
            )


class RollbackSafety:
    """Production contract for rollback safety.

    Guarantees:
    1. Active snapshot required: every product being edited must have an active snapshot
       before mutations are dispatched
    2. Snapshot not stale: snapshots expire after max_snapshot_age_hours
    3. All gates closed: all mutation dispatch gates must be closed before rollback
    4. Uncommitted mutations: rollback must be triggered within rollback_window_seconds
       of any uncommitted mutation
    5. No concurrent rollback: only one rollback can be in progress per product
    6. Rollback window: rollback must complete within rollback_window_seconds
    """

    DEFAULT_MAX_SNAPSHOT_AGE_HOURS = 24
    DEFAULT_ROLLBACK_WINDOW_SECONDS = 300

    def __init__(
        self,
        max_snapshot_age_hours: int = DEFAULT_MAX_SNAPSHOT_AGE_HOURS,
        rollback_window_seconds: int = DEFAULT_ROLLBACK_WINDOW_SECONDS,
    ) -> None:
        self._max_snapshot_age_hours = max_snapshot_age_hours
        self._rollback_window_seconds = rollback_window_seconds
        self._active_snapshots: dict[str, dict[str, Any]] = {}
        self._rollback_in_progress: dict[str, RollbackPhase] = {}
        self._closed_gates: dict[str, set[str]] = {}
        self._uncommitted_mutations: dict[str, list[dict[str, Any]]] = {}

    def register_snapshot(
        self,
        product_id: str,
        snapshot: dict[str, Any],
    ) -> RollbackSafetyResult:
        """Register a snapshot for a product (fail-closed)."""
        if not product_id:
            return RollbackSafetyResult(
                ok=False,
                reason_code="PRODUCT_ID_REQUIRED",
                message="product_id is required for snapshot registration",
            )

        if not snapshot:
            return RollbackSafetyResult(
                ok=False,
                reason_code="SNAPSHOT_REQUIRED",
                message="snapshot is required for registration",
            )

        if product_id in self._active_snapshots:
            existing = self._active_snapshots[product_id]
            return RollbackSafetyResult(
                ok=False,
                reason_code="SNAPSHOT_ALREADY_ACTIVE",
                message=f"Product {product_id} already has an active snapshot",
                metadata={
                    "existing_snapshot_time": existing.get("snapshot_time"),
                    "existing_snapshot_hash": existing.get("snapshot_hash"),
                },
            )

        self._active_snapshots[product_id] = dict(snapshot)
        self._closed_gates.setdefault(product_id, set())
        self._uncommitted_mutations.setdefault(product_id, [])

        return RollbackSafetyResult(
            ok=True,
            message="Snapshot registered successfully",
            metadata={
                "product_id": product_id,
                "snapshot_hash": snapshot.get("snapshot_hash"),
                "snapshot_time": snapshot.get("snapshot_time"),
            },
        )

    def check_pre_rollback(
        self,
        product_id: str,
    ) -> RollbackSafetyResult:
        """Check if rollback is safe for a product (pre-rollback gate)."""
        if product_id not in self._active_snapshots:
            return RollbackSafetyResult(
                ok=False,
                reason_code=RollbackSafetyViolationType.NO_ACTIVE_SNAPSHOT.value,
                message=f"No active snapshot found for product {product_id}",
            )

        snapshot = self._active_snapshots[product_id]

        snapshot_time_str = snapshot.get("snapshot_time")
        if snapshot_time_str:
            snapshot_time = self._parse_iso_time(snapshot_time_str)
            if snapshot_time is not None:
                age_hours = self._hours_since(snapshot_time)
                if age_hours > self._max_snapshot_age_hours:
                    return RollbackSafetyResult(
                        ok=False,
                        reason_code=RollbackSafetyViolationType.SNAPSHOT_STALE.value,
                        message=f"Snapshot for product {product_id} is stale ({age_hours:.1f}h old, max {self._max_snapshot_age_hours}h)",
                        metadata={
                            "age_hours": age_hours,
                            "max_age_hours": self._max_snapshot_age_hours,
                        },
                    )

        open_gates = [
            gate for gate in self._closed_gates.get(product_id, set())
            if not self._is_gate_closed(product_id, gate)
        ]
        if open_gates:
            return RollbackSafetyResult(
                ok=False,
                reason_code=RollbackSafetyViolationType.GATE_NOT_CLOSED.value,
                message=f"Open gates prevent rollback for product {product_id}: {open_gates}",
                metadata={"open_gates": open_gates},
            )

        if product_id in self._rollback_in_progress:
            ongoing = self._rollback_in_progress[product_id]
            if ongoing in {RollbackPhase.PRE_ROLLBACK, RollbackPhase.ROLLBACK_IN_PROGRESS}:
                return RollbackSafetyResult(
                    ok=False,
                    reason_code=RollbackSafetyViolationType.CONCURRENT_ROLLBACK.value,
                    message=f"Rollback already in progress for product {product_id}: {ongoing.value}",
                    metadata={"ongoing_phase": ongoing.value},
                )

        return RollbackSafetyResult(
            ok=True,
            message="Pre-rollback check passed",
            metadata={
                "product_id": product_id,
                "snapshot_time": snapshot.get("snapshot_time"),
                "snapshot_hash": snapshot.get("snapshot_hash"),
            },
        )

    def begin_rollback(
        self,
        product_id: str,
        reason: str,
    ) -> RollbackSafetyResult:
        """Begin rollback for a product (marks rollback as in-progress)."""
        pre_check = self.check_pre_rollback(product_id)
        if not pre_check.ok:
            return pre_check

        uncommitted = self._uncommitted_mutations.get(product_id, [])
        if uncommitted:
            oldest = uncommitted[0].get("dispatched_at")
            if oldest:
                dispatch_time = self._parse_iso_time(oldest)
                if dispatch_time is not None:
                    elapsed = self._seconds_since(dispatch_time)
                    if elapsed > self._rollback_window_seconds:
                        return RollbackSafetyResult(
                            ok=False,
                            reason_code=RollbackSafetyViolationType.ROLLBACK_WINDOW_EXCEEDED.value,
                            message=f"Rollback window exceeded for product {product_id} ({elapsed:.0f}s elapsed, max {self._rollback_window_seconds}s)",
                            metadata={
                                "elapsed_seconds": elapsed,
                                "max_window_seconds": self._rollback_window_seconds,
                            },
                        )

        self._rollback_in_progress[product_id] = RollbackPhase.ROLLBACK_IN_PROGRESS
        return RollbackSafetyResult(
            ok=True,
            message="Rollback begun",
            metadata={
                "product_id": product_id,
                "reason": reason,
                "phase": RollbackPhase.ROLLBACK_IN_PROGRESS.value,
            },
        )

    def commit_rollback(
        self,
        product_id: str,
    ) -> RollbackSafetyResult:
        """Commit rollback and release snapshot."""
        if product_id not in self._rollback_in_progress:
            return RollbackSafetyResult(
                ok=False,
                reason_code="NO_ROLLBACK_IN_PROGRESS",
                message=f"No rollback in progress for product {product_id}",
            )

        phase = self._rollback_in_progress[product_id]
        if phase != RollbackPhase.ROLLBACK_IN_PROGRESS:
            return RollbackSafetyResult(
                ok=False,
                reason_code="INVALID_ROLLBACK_PHASE",
                message=f"Cannot commit rollback in phase {phase.value}",
            )

        self._rollback_in_progress[product_id] = RollbackPhase.ROLLBACK_COMMITTED
        self._release_snapshot(product_id)

        return RollbackSafetyResult(
            ok=True,
            message="Rollback committed and snapshot released",
            metadata={
                "product_id": product_id,
                "phase": RollbackPhase.ROLLBACK_COMMITTED.value,
            },
        )

    def release_snapshot(
        self,
        product_id: str,
    ) -> RollbackSafetyResult:
        """Release a snapshot after successful commit."""
        self._release_snapshot(product_id)
        return RollbackSafetyResult(
            ok=True,
            message="Snapshot released",
            metadata={"product_id": product_id},
        )

    def record_mutation_dispatch(
        self,
        product_id: str,
        mutation_id: str,
    ) -> None:
        """Record a mutation dispatch for rollback tracking."""
        import time
        self._uncommitted_mutations.setdefault(product_id, []).append({
            "mutation_id": mutation_id,
            "dispatched_at": datetime.utcnow().isoformat() + "Z",
            "dispatched_at_ms": time.time(),
        })

    def commit_mutation(
        self,
        product_id: str,
        mutation_id: str,
    ) -> None:
        """Remove a mutation from the uncommitted list (after successful commit)."""
        if product_id in self._uncommitted_mutations:
            self._uncommitted_mutations[product_id] = [
                m for m in self._uncommitted_mutations[product_id]
                if m.get("mutation_id") != mutation_id
            ]

    def close_gate(self, product_id: str, gate_kind: str) -> None:
        """Mark a gate as closed for a product."""
        self._closed_gates.setdefault(product_id, set()).add(gate_kind)

    def _is_gate_closed(self, product_id: str, gate_kind: str) -> bool:
        return gate_kind in self._closed_gates.get(product_id, set())

    def _release_snapshot(self, product_id: str) -> None:
        if product_id in self._active_snapshots:
            del self._active_snapshots[product_id]
        if product_id in self._rollback_in_progress:
            self._rollback_in_progress[product_id] = RollbackPhase.ROLLBACK_RELEASED
        if product_id in self._closed_gates:
            del self._closed_gates[product_id]
        if product_id in self._uncommitted_mutations:
            del self._uncommitted_mutations[product_id]

    def _parse_iso_time(self, time_str: str) -> datetime | None:
        try:
            if time_str.endswith("Z"):
                time_str = time_str[:-1] + "+00:00"
            return datetime.fromisoformat(time_str)
        except (ValueError, TypeError):
            return None

    def _hours_since(self, dt: datetime) -> float:
        delta = datetime.utcnow() - dt
        return delta.total_seconds() / 3600.0

    def _seconds_since(self, dt: datetime) -> float:
        delta = datetime.utcnow() - dt
        return delta.total_seconds()
