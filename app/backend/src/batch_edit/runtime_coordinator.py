from __future__ import annotations

import asyncio
import secrets
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.batch_edit.execution_contract import (
    ITEM_EXECUTION_REQUEST_SCHEMA,
    PRE_SAVE_VALIDATION_REASON_ALLOWLIST,
    BatchExecutionContractError,
    classify_pre_save_no_write_outcome,
    classify_item_outcome,
    derive_running_item_claim_context,
)
from src.batch_edit.execution_state import (
    BATCH_ITEM_GRANT_TTL_SECONDS,
    EditBatchExecutionPersistenceError,
    derive_execution_item_grant,
    validate_execution_item_grant_consumption,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config import SCREENSHOT_DIR
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_action_result_envelope,
    validate_independent_save_verification_pair,
)
from src.execution.browser_agent_protocol import BrowserAgentCommand, mutation_target_hash
from src.services.evidence_ref import validate_evidence_ref


@dataclass(frozen=True)
class BatchBrowserStep:
    state: str
    action: str
    expected_page: str
    label: str
    include_defaults: bool = False


BATCH_BROWSER_STEPS: tuple[BatchBrowserStep, ...] = (
    BatchBrowserStep("PRECHECK_SESSION", "check_login_state", "authenticated_dxm", "确认店小秘登录"),
    BatchBrowserStep("OPEN_DRAFT_LIST", "open_draft_box", "draft_box", "打开商品箱"),
    BatchBrowserStep("OPEN_EDIT_PAGE", "open_editor", "editor", "打开目标商品"),
    BatchBrowserStep("VERIFY_EDIT_OWNERSHIP", "verify_edit_ownership", "editor", "核对目标商品"),
    BatchBrowserStep("FILL_BASE_INFO", "fill_editor_required_defaults", "editor", "填写基础信息", True),
    BatchBrowserStep("FILL_VARIANTS", "fill_editor_variants", "editor", "填写价格库存", True),
    BatchBrowserStep("FILL_MEDIA", "fill_media_assets", "editor", "处理商品素材", True),
    BatchBrowserStep("FILL_COMPLIANCE", "fill_compliance_defaults", "editor", "填写合规信息", True),
    BatchBrowserStep("ENABLE_SEMI_MANAGED", "enable_semi_managed", "editor", "启用半托管"),
    BatchBrowserStep("OPEN_SEMI_MANAGED_PAGE", "open_semi_managed_page", "semi_managed", "打开半托管编辑", True),
    BatchBrowserStep("FILL_SEMI_GOODS", "fill_semi_managed_defaults", "semi_managed", "填写包装物流", True),
    BatchBrowserStep("FILL_SEMI_VARIANTS", "fill_semi_managed_defaults", "semi_managed", "填写半托管库存", True),
    BatchBrowserStep("SAVE_ONLY", "save_only", "semi_managed", "只保存不发布", True),
    BatchBrowserStep("VERIFY_NOT_PUBLISHED", "verify_not_published", "semi_managed", "独立确认未发布"),
)

_EXECUTION_CONTRACT_BATCH_KEYS = {
    "id",
    "schema_version",
    "status",
    "scope_snapshot_id",
    "scope_snapshot_digest",
    "scope_snapshot",
    "template_id",
    "template_snapshot_digest",
    "template_snapshot",
    "policy_digest",
    "policy",
    "created_at",
    "updated_at",
    "items",
}


class BatchRuntimeError(RuntimeError):
    def __init__(self, reason_code: str, detail: str, *, manual_review: bool = False) -> None:
        self.reason_code = reason_code
        self.manual_review = manual_review
        super().__init__(detail)


class BatchExecutionRuntime:
    """Run one approved edit batch through the singleton Browser Agent.

    The runtime deliberately has no retry loop.  It claims each item without
    mutation authority, performs all pre-save work without a grant, then issues
    and consumes one 60-second grant at the SAVE click.  Any unproven external
    result stops the whole batch.  Repository methods provide the CAS boundaries.
    """

    def __init__(
        self,
        repository: Any,
        browser_agent_runtime: Any,
        mutation_ledger: Any,
        *,
        runtime_facts_provider: Callable[[], Mapping[str, Any]],
        browser_session_provider: Callable[[], str | None],
        command_timeout_seconds: float = 180.0,
    ) -> None:
        self._repository = repository
        self._browser_agent_runtime = browser_agent_runtime
        self._mutation_ledger = mutation_ledger
        self._runtime_facts_provider = runtime_facts_provider
        self._browser_session_provider = browser_session_provider
        self._command_timeout_seconds = max(30.0, float(command_timeout_seconds))
        self._item_grant_ttl_seconds = BATCH_ITEM_GRANT_TTL_SECONDS
        self._run_lock: asyncio.Lock | None = None
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._active_lock = threading.RLock()
        self._active_grants: dict[str, dict[str, Any]] = {}
        self._active_commands: dict[int, BrowserAgentCommand] = {}

    def recover_interrupted_batches(self) -> int:
        recover = getattr(self._repository, "recover_interrupted_edit_batches", None)
        if not callable(recover):
            return 0
        result = recover()
        if isinstance(result, Mapping):
            return int(result.get("recovered_count") or 0)
        if isinstance(result, bool):
            return int(result)
        return int(result or 0)

    def shutdown(self) -> dict[str, Any]:
        """Revoke active work and persist a manual-review stop before exit."""

        with self._active_lock:
            commands = list(self._active_commands.values())
            tasks = list(self._tasks.values())
            self._active_grants.clear()
            self._active_commands.clear()
        cancel_command = getattr(self._browser_agent_runtime, "cancel_command", None)
        if callable(cancel_command):
            for command in commands:
                try:
                    cancel_command(command.command_id, command.runtime_id)
                except Exception:
                    pass
        for task in tasks:
            if not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass
        recovered = self.recover_interrupted_batches()
        return {
            "ok": True,
            "cancelled_commands": len(commands),
            "cancelled_tasks": sum(1 for task in tasks if not task.done()),
            "stopped_batches": recovered,
        }

    def schedule(self, batch_id: int) -> asyncio.Task[None]:
        canonical_id = _positive_int(batch_id, "batch_id")
        current = self._tasks.get(canonical_id)
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(self.run_batch(canonical_id), name=f"dxm-edit-batch-{canonical_id}")
        self._tasks[canonical_id] = task
        task.add_done_callback(lambda completed, item=canonical_id: self._forget_task(item, completed))
        return task

    async def run_batch(self, batch_id: int) -> None:
        if self._run_lock is None:
            self._run_lock = asyncio.Lock()
        async with self._run_lock:
            while True:
                batch = self._private_batch(batch_id)
                status = str(batch.get("status") or "")
                if status == "stop_requested":
                    self._stop_batch(
                        batch_id,
                        "OPERATOR_STOPPED",
                        "操作员已停止批次；未开始的商品不会继续处理。",
                        manual_review=False,
                    )
                    return
                if status != "running":
                    return
                running = next(
                    (item for item in batch.get("items") or [] if item.get("status") == "running"),
                    None,
                )
                if running is not None:
                    self._stop_batch(
                        batch_id,
                        "UNEXPECTED_RUNNING_ITEM",
                        "批次存在未受当前执行器持有的运行商品，系统已停止且不会重试。",
                        manual_review=True,
                    )
                    return
                pending = next(
                    (item for item in batch.get("items") or [] if item.get("status") == "pending"),
                    None,
                )
                if pending is None:
                    complete = getattr(self._repository, "complete_edit_batch", None)
                    if not callable(complete) or not _cas_applied(complete(batch_id)):
                        raise BatchRuntimeError("BATCH_COMPLETE_CONFLICT", "批次完成状态写入失败。")
                    return

                start_context = _private_value(batch, "start_context")
                if not isinstance(start_context, Mapping):
                    self._stop_batch(
                        batch_id,
                        "START_CONTEXT_MISSING",
                        "批次启动上下文缺失，系统已停止且不会尝试保存。",
                        manual_review=True,
                    )
                    return
                claim_next = getattr(self._repository, "claim_next_edit_batch_item", None)
                claim_result = claim_next(batch_id) if callable(claim_next) else None
                if not _cas_applied(claim_result):
                    self._stop_batch(
                        batch_id,
                        _result_reason(claim_result, "ITEM_CLAIM_CONFLICT"),
                        "逐件认领状态已变化，系统已停止且不会重试。",
                        manual_review=True,
                    )
                    return
                claimed_item = getattr(claim_result, "item", None)
                if not isinstance(claimed_item, Mapping):
                    self._stop_batch(
                        batch_id,
                        "ITEM_CLAIM_RESULT_MISSING",
                        "逐件认领结果缺失，系统已停止且不会重试。",
                        manual_review=True,
                    )
                    return
                item_id = int(claimed_item["id"])
                batch = self._private_batch(batch_id)
                try:
                    claim_context = derive_running_item_claim_context(
                        _execution_contract_batch(batch),
                        start_context=dict(start_context),
                    )
                except BatchExecutionContractError as exc:
                    self._stop_batch(batch_id, exc.reason_code, str(exc), manual_review=True)
                    return
                try:
                    execution = await asyncio.to_thread(
                        self._execute_item,
                        batch_id,
                        item_id,
                        claim_context,
                    )
                except Exception as exc:
                    reason_code, detail, manual_review = self._failure_details(exc)
                    self._stop_batch(batch_id, reason_code, detail, manual_review=manual_review)
                    return
                finally:
                    with self._active_lock:
                        self._active_commands.pop(batch_id, None)

                complete_item = getattr(self._repository, "complete_edit_batch_item", None)
                if not callable(complete_item) or not _cas_applied(
                    complete_item(
                        batch_id,
                        item_id,
                        execution["decision"],
                        execution["outcome"],
                        execution["action_results"],
                    )
                ):
                    self._stop_batch(
                        batch_id,
                        "ITEM_RESULT_CONFLICT",
                        "商品结果无法可靠落库，系统已停止；请人工核对该商品。",
                        manual_review=True,
                    )
                    return

    def request_stop(self, batch_id: int, *, requested_by: str, reason: str | None = None) -> dict[str, Any]:
        request = getattr(self._repository, "request_stop_edit_batch", None)
        if not callable(request):
            raise BatchRuntimeError("BATCH_STOP_UNAVAILABLE", "批次停止接口不可用。")
        result = request(
            _positive_int(batch_id, "batch_id"),
            requested_by=" ".join(str(requested_by or "").split()),
            reason=" ".join(str(reason or "").split()) or None,
        )
        if not _cas_applied(result):
            raise BatchRuntimeError(_result_reason(result, "BATCH_STOP_CONFLICT"), "批次当前状态不能停止。")
        with self._active_lock:
            command = self._active_commands.get(batch_id)
            revoked_leases = [
                lease_id
                for lease_id, active in self._active_grants.items()
                if isinstance(active.get("grant"), Mapping)
                and int(active["grant"].get("batch_id") or 0) == batch_id
            ]
            for lease_id in revoked_leases:
                self._active_grants.pop(lease_id, None)
        if command is not None:
            cancel = getattr(self._browser_agent_runtime, "cancel_command", None)
            if callable(cancel):
                try:
                    cancel(command.command_id, command.runtime_id)
                except Exception:
                    pass
        return self._repository.get_edit_batch(batch_id)

    def is_batch_command(self, command: BrowserAgentCommand) -> bool:
        return isinstance(command.params, dict) and command.params.get("batch_execution") is True

    def authorize_mutation(self, command: BrowserAgentCommand, mutation_context: Any) -> dict[str, Any]:
        """Consume the in-memory nonce and persistent grant immediately before SAVE."""

        if not self.is_batch_command(command):
            return {"ok": False, "reason_code": "NOT_BATCH_COMMAND"}
        lease_id = str(command.authorization_lease_id or "")
        with self._active_lock:
            active = self._active_grants.get(lease_id)
        if not isinstance(active, dict):
            return {"ok": False, "reason_code": "BATCH_GRANT_NOT_ACTIVE"}
        grant = active.get("grant")
        nonce = active.get("nonce")
        if not isinstance(grant, dict) or not isinstance(nonce, str):
            return {"ok": False, "reason_code": "BATCH_GRANT_NOT_ACTIVE"}
        if (
            command.state != "SAVE_ONLY"
            or command.action != "save_only"
            or command.mutation_scope_id != grant.get("mutation_scope_id")
            or command.authorization_fingerprint != grant.get("fingerprint")
            or command.authorization_lease_id != grant.get("grant_lease_id")
        ):
            return {"ok": False, "reason_code": "BATCH_GRANT_COMMAND_DRIFT"}
        mutation_action = (
            str(mutation_context.get("mutation_action") or "")
            if isinstance(mutation_context, Mapping)
            else ""
        )
        if mutation_action != "save_only_click":
            return {"ok": False, "reason_code": "BATCH_MUTATION_ACTION_FORBIDDEN"}
        try:
            expected_target_hash = mutation_target_hash("save_only", command.params)
        except Exception:
            return {"ok": False, "reason_code": "BATCH_TARGET_BINDING_INVALID"}
        if command.target_hash != expected_target_hash:
            return {"ok": False, "reason_code": "BATCH_TARGET_BINDING_DRIFT"}

        try:
            batch = self._private_batch(int(grant["batch_id"]))
        except BatchRuntimeError as exc:
            return {"ok": False, "reason_code": exc.reason_code}
        item = next(
            (candidate for candidate in batch.get("items") or [] if candidate.get("id") == grant.get("item_id")),
            None,
        )
        if batch.get("status") != "running" or not isinstance(item, dict) or item.get("status") != "running":
            return {"ok": False, "reason_code": "BATCH_OR_ITEM_NOT_RUNNING"}
        if item.get("target_identity_sha256") != grant.get("target_identity_sha256"):
            return {"ok": False, "reason_code": "BATCH_ITEM_TARGET_DRIFT"}
        live_rejection = self._live_binding_rejection(grant)
        if live_rejection is not None:
            return {"ok": False, "reason_code": live_rejection}

        binding_keys = (
            "batch_id",
            "item_id",
            "ordinal",
            "approval_lease_id",
            "approval_context_fingerprint",
            "scope_digest",
            "template_digest",
            "policy_digest",
            "target_identity_sha256",
            "store_identity",
            "runtime_identity",
            "browser_session_id",
            "git_head",
            "page_identity",
            "mutation_scope_id",
            "grant_lease_id",
        )
        request = {
            "schema_version": ITEM_EXECUTION_REQUEST_SCHEMA,
            "action": "SAVE_ONLY",
            "mode": "batch_single_save",
            "grant_fingerprint": grant["fingerprint"],
            **{key: grant[key] for key in binding_keys},
        }
        consumed_reader = getattr(self._repository, "consumed_edit_batch_nonce_hashes", None)
        consumed = consumed_reader(int(grant["batch_id"])) if callable(consumed_reader) else []
        try:
            consumption = validate_execution_item_grant_consumption(
                grant,
                raw_nonce=nonce,
                now=datetime.now(timezone.utc),
                request=request,
                consumed_nonce_hashes=consumed,
            )
        except (BatchExecutionContractError, EditBatchExecutionPersistenceError) as exc:
            return {"ok": False, "reason_code": exc.reason_code}
        consume = getattr(self._repository, "consume_edit_batch_item_grant", None)
        if not callable(consume) or not _cas_applied(
            consume(int(grant["batch_id"]), int(grant["item_id"]), consumption)
        ):
            return {"ok": False, "reason_code": "BATCH_GRANT_CONSUME_CONFLICT"}
        with self._active_lock:
            current = self._active_grants.get(lease_id)
            if current is active:
                self._active_grants.pop(lease_id, None)
        return {
            "ok": True,
            "reason_code": "BATCH_ITEM_SAVE_AUTHORIZED",
            "batch_id": int(grant["batch_id"]),
            "item_id": int(grant["item_id"]),
            "grant_fingerprint": grant["fingerprint"],
        }

    def _execute_item(
        self,
        batch_id: int,
        item_id: int,
        claim_context: dict[str, Any],
    ) -> dict[str, Any]:
        batch = self._private_batch(batch_id)
        item = next(
            (candidate for candidate in batch.get("items") or [] if int(candidate.get("id") or 0) == item_id),
            None,
        )
        if not isinstance(item, dict):
            raise BatchRuntimeError("BATCH_ITEM_NOT_FOUND", "批次商品不存在。")
        snapshot = item.get("item_snapshot")
        if not isinstance(snapshot, dict):
            raise BatchRuntimeError("BATCH_ITEM_SNAPSHOT_MISSING", "批次商品冻结信息缺失。")
        target_identity = snapshot.get("target_identity")
        if (
            claim_context.get("batch_id") != batch_id
            or claim_context.get("item_id") != item_id
            or not isinstance(target_identity, dict)
            or canonical_sha256(target_identity) != claim_context.get(
                "target_identity_sha256"
            )
        ):
            raise BatchRuntimeError("BATCH_ITEM_TARGET_DRIFT", "冻结商品身份无法复现。")
        defaults = self._bundle_defaults(batch)
        store_name = str(batch["scope_snapshot"]["store_identity"]["store_name"])
        product_query = str(
            snapshot.get("dxm_product_id")
            or target_identity.get("stable_identity", {}).get("value")
            or snapshot.get("title")
            or ""
        ).strip()
        base_params = {
            "batch_execution": True,
            "product_query": product_query or None,
            "store_name": store_name,
            "target_source_urls": list(snapshot.get("source_urls") or []),
            "target_identity": target_identity,
            "target_identity_sha256": claim_context["target_identity_sha256"],
        }
        action_results: list[dict[str, Any]] = []
        pre_save_steps = tuple(
            step for step in BATCH_BROWSER_STEPS if step.state not in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}
        )
        for step in pre_save_steps:
            self._assert_batch_can_continue(batch_id, claim_context)
            params = dict(base_params)
            if step.action in {"check_login_state", "open_draft_box"}:
                params = {"batch_execution": True}
            elif step.include_defaults:
                params["defaults"] = defaults
            command = self._build_command(batch, item, None, step, params)
            canonical = self._run_browser_step(
                batch_id,
                command,
                step,
                expected_browser_session_id=str(claim_context["browser_session_id"]),
                post_grant=False,
            )
            action_results.append(canonical)
            if canonical.get("ok") is not True:
                isolated = self._isolated_pre_save_execution(
                    step,
                    claim_context,
                    canonical,
                    action_results,
                )
                if isolated is not None:
                    return isolated
                raise BatchRuntimeError(
                    str(canonical.get("failure_code") or "BROWSER_ACTION_REJECTED"),
                    f"{step.label}未完成，系统已停止且不会自动重试。",
                    manual_review=step.state in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"},
                )

        self._assert_batch_can_continue(batch_id, claim_context)
        current_batch = self._private_batch(batch_id)
        start_context = _private_value(current_batch, "start_context")
        if not isinstance(start_context, Mapping):
            raise BatchRuntimeError("START_CONTEXT_MISSING", "批次启动上下文缺失。", manual_review=True)
        try:
            issued = derive_execution_item_grant(
                _execution_contract_batch(current_batch),
                start_context=dict(start_context),
                now=datetime.now(timezone.utc),
                grant_lease_id=uuid.uuid4().hex,
                one_time_nonce=secrets.token_urlsafe(32),
                ttl_seconds=self._item_grant_ttl_seconds,
            )
        except (BatchExecutionContractError, EditBatchExecutionPersistenceError) as exc:
            raise BatchRuntimeError(exc.reason_code, str(exc), manual_review=True) from exc
        grant = dict(issued["grant"])
        nonce = str(issued["nonce"])
        if int(grant.get("item_id") or 0) != item_id:
            raise BatchRuntimeError("ITEM_GRANT_TARGET_DRIFT", "逐件授权绑定到了另一商品。", manual_review=True)
        issue_grant = getattr(self._repository, "issue_edit_batch_item_grant", None)
        grant_result = issue_grant(batch_id, item_id, grant) if callable(issue_grant) else None
        if not _cas_applied(grant_result):
            raise BatchRuntimeError(
                _result_reason(grant_result, "ITEM_GRANT_CONFLICT"),
                "保存授权状态已变化，系统已停止且不会重试。",
                manual_review=True,
            )

        save_step = next(step for step in BATCH_BROWSER_STEPS if step.state == "SAVE_ONLY")
        save_params = {**base_params, "defaults": defaults}
        save_command = self._build_command(current_batch, item, grant, save_step, save_params)
        self._reserve_item_mutation(save_command)
        lease_id = str(grant["grant_lease_id"])
        with self._active_lock:
            self._active_grants[lease_id] = {"grant": grant, "nonce": nonce}
        try:
            save = self._run_browser_step(
                batch_id,
                save_command,
                save_step,
                expected_browser_session_id=str(grant["browser_session_id"]),
                post_grant=True,
            )
        finally:
            with self._active_lock:
                self._active_grants.pop(lease_id, None)
        action_results.append(save)
        if save.get("ok") is not True:
            raise BatchRuntimeError(
                str(save.get("failure_code") or "SAVE_RESULT_UNCERTAIN"),
                "保存动作没有形成确定结果，系统已停止且不会自动重试。",
                manual_review=True,
            )
        if not self._grant_consumption_proven(batch_id, item_id, grant):
            raise BatchRuntimeError(
                "ITEM_GRANT_CONSUMPTION_UNPROVEN",
                "保存授权的一次性消费没有可靠落库。",
                manual_review=True,
            )

        verification_step = next(
            step for step in BATCH_BROWSER_STEPS if step.state == "VERIFY_NOT_PUBLISHED"
        )
        self._assert_batch_can_continue(batch_id, grant)
        verification_params = dict(base_params)
        verification_command = self._build_command(
            current_batch,
            item,
            None,
            verification_step,
            verification_params,
        )
        verification = self._run_browser_step(
            batch_id,
            verification_command,
            verification_step,
            expected_browser_session_id=str(grant["browser_session_id"]),
            post_grant=True,
        )
        action_results.append(verification)
        if verification.get("ok") is not True:
            raise BatchRuntimeError(
                str(verification.get("failure_code") or "UNPUBLISHED_VERIFICATION_UNCERTAIN"),
                "未发布核验没有形成确定结果，系统已停止且不会自动重试。",
                manual_review=True,
            )
        try:
            validate_independent_save_verification_pair(save, verification)
        except ActionResultContractError as exc:
            raise BatchRuntimeError(
                exc.reason_code,
                f"保存与未发布证据不是独立闭环：{exc}",
                manual_review=True,
            ) from exc
        ledger_entry = self._mutation_ledger.get_entry(
            str(grant["mutation_scope_id"]),
            "save_only_click",
        )
        ledger_status = str((ledger_entry or {}).get("status") or "") or None
        outcome = {
            "schema_version": "dxm_edit_batch_item_outcome_evidence.v1",
            "ok": True,
            "error_code": None,
            "validation_reason": None,
            "ledger_status": ledger_status,
            "network_audit": {
                "complete": True,
                "mutation_request_count": 1,
                "publish_request_count": 0,
            },
            "publish_signal": {"detected": False, "kind": "independent_unpublished_probe"},
            "save_proven": True,
            "runtime_identity": grant["runtime_identity"],
            "browser_session_id": grant["browser_session_id"],
            "git_head": grant["git_head"],
            "store_identity": grant["store_identity"],
            "page_identity": grant["page_identity"],
            "target_identity_sha256": grant["target_identity_sha256"],
            "mutation_scope_id": grant["mutation_scope_id"],
        }
        decision = classify_item_outcome(grant, outcome)
        if decision.get("continue_batch") is not True or decision.get("classification") != "SUCCEEDED":
            raise BatchRuntimeError(
                str(decision.get("reason_code") or "ITEM_OUTCOME_UNCERTAIN"),
                "商品保存结果不确定，系统已停止且不会自动重试。",
                manual_review=True,
            )
        return {"decision": decision, "outcome": outcome, "action_results": action_results}

    def _isolated_pre_save_execution(
        self,
        step: BatchBrowserStep,
        claim_context: Mapping[str, Any],
        action_result: Mapping[str, Any],
        action_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if step.state in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}:
            return None
        validation_reason = str(action_result.get("failure_code") or "")
        if validation_reason not in PRE_SAVE_VALIDATION_REASON_ALLOWLIST:
            return None
        observations = action_result.get("evidence", {}).get("observations")
        if not isinstance(observations, Mapping):
            return None
        network = observations.get("network_audit")
        publish = observations.get("publish_signal")
        if (
            not isinstance(network, Mapping)
            or set(network) != {"complete", "mutation_request_count", "publish_request_count"}
            or network.get("complete") is not True
            or type(network.get("mutation_request_count")) is not int
            or type(network.get("publish_request_count")) is not int
            or network.get("mutation_request_count") != 0
            or network.get("publish_request_count") != 0
            or not isinstance(publish, Mapping)
            or set(publish) != {"detected", "kind"}
            or publish.get("detected") is not False
            or not isinstance(publish.get("kind"), str)
            or not str(publish.get("kind") or "").strip()
        ):
            return None
        before_values = action_result.get("before_values")
        page_identity = action_result.get("page_identity")
        runtime_identity = claim_context.get("runtime_identity")
        if not isinstance(before_values, Mapping):
            return None
        target_identity = before_values.get("target_identity")
        store_identity = claim_context.get("store_identity")
        if (
            not isinstance(target_identity, Mapping)
            or canonical_sha256(dict(target_identity)) != claim_context.get("target_identity_sha256")
            or not isinstance(store_identity, Mapping)
            or before_values.get("store_name") != store_identity.get("store_name")
            or not isinstance(page_identity, Mapping)
            or page_identity.get("kind") != step.expected_page
            or not isinstance(page_identity.get("url"), str)
            or not str(page_identity.get("url") or "").strip()
            or not isinstance(runtime_identity, Mapping)
            or page_identity.get("runtime_id") != runtime_identity.get("browser_runtime_id")
            or page_identity.get("browser_session_id") != claim_context.get("browser_session_id")
            or self._live_binding_rejection(claim_context) is not None
        ):
            return None
        if not self._item_has_no_authority(
            int(claim_context["batch_id"]), int(claim_context["item_id"])
        ):
            return None
        outcome = {
            "schema_version": "dxm_edit_batch_item_outcome_evidence.v1",
            "ok": False,
            "error_code": "PRE_SAVE_VALIDATION_NO_WRITE",
            "validation_reason": validation_reason,
            "ledger_status": None,
            "network_audit": {
                "complete": True,
                "mutation_request_count": 0,
                "publish_request_count": 0,
            },
            "publish_signal": {
                "detected": False,
                "kind": publish.get("kind"),
            },
            "save_proven": False,
            "runtime_identity": claim_context["runtime_identity"],
            "browser_session_id": claim_context["browser_session_id"],
            "git_head": claim_context["git_head"],
            "store_identity": claim_context["store_identity"],
            "page_identity": claim_context["page_identity"],
            "target_identity_sha256": claim_context["target_identity_sha256"],
            "mutation_scope_id": None,
        }
        decision = classify_pre_save_no_write_outcome(dict(claim_context), outcome)
        if (
            decision.get("continue_batch") is not True
            or decision.get("classification") != "ISOLATED_PRE_SAVE_NO_WRITE"
        ):
            return None
        return {
            "decision": decision,
            "outcome": outcome,
            "action_results": list(action_results),
        }

    def _run_browser_step(
        self,
        batch_id: int,
        command: BrowserAgentCommand,
        step: BatchBrowserStep,
        *,
        expected_browser_session_id: str,
        post_grant: bool,
    ) -> dict[str, Any]:
        if not post_grant and any(
            value
            for value in (
                command.mutation_scope_id,
                command.authorization_fingerprint,
                command.authorization_lease_id,
                command.stage_task_facts_fingerprint,
            )
        ):
            raise BatchRuntimeError(
                "PRE_SAVE_AUTHORITY_FORBIDDEN",
                "保存前步骤携带了不应存在的变更授权。",
                manual_review=True,
            )
        with self._active_lock:
            self._active_commands[batch_id] = command
        try:
            raw_result = self._browser_agent_runtime.run(
                command,
                timeout_seconds=self._command_timeout_seconds,
            )
        except TimeoutError as exc:
            cancel = getattr(self._browser_agent_runtime, "cancel_command", None)
            if callable(cancel):
                try:
                    cancel(command.command_id, command.runtime_id)
                except Exception:
                    pass
            raise BatchRuntimeError(
                "BROWSER_COMMAND_TIMEOUT",
                f"{step.label}超时，系统已停止且不会自动重试。",
                manual_review=post_grant,
            ) from exc
        except Exception as exc:
            raise BatchRuntimeError(
                "BROWSER_COMMAND_FAILED",
                f"{step.label}失败：{exc}",
                manual_review=post_grant,
            ) from exc
        finally:
            with self._active_lock:
                self._active_commands.pop(batch_id, None)
        try:
            canonical = validate_action_result_envelope(
                raw_result,
                expected_state=step.state,
                expected_action=step.action,
                expected_runtime_id=str(self._browser_agent_runtime.runtime_id),
                expected_browser_session_id=expected_browser_session_id,
            )
        except ActionResultContractError as exc:
            raise BatchRuntimeError(
                exc.reason_code,
                f"{step.label}没有形成可信结果：{exc}",
                manual_review=post_grant,
            ) from exc
        self._validate_evidence_refs(canonical)
        return canonical

    def _grant_consumption_proven(
        self,
        batch_id: int,
        item_id: int,
        grant: Mapping[str, Any],
    ) -> bool:
        batch = self._private_batch(batch_id)
        private = batch.get("_private")
        rows = private.get("item_authorizations") if isinstance(private, Mapping) else None
        row = next(
            (
                value
                for value in rows or []
                if isinstance(value, Mapping) and int(value.get("item_id") or 0) == item_id
            ),
            None,
        )
        return bool(
            isinstance(row, Mapping)
            and row.get("grant_lease_id") == grant.get("grant_lease_id")
            and row.get("grant_fingerprint") == grant.get("fingerprint")
            and row.get("grant_nonce_hash") == grant.get("nonce_hash")
            and row.get("mutation_scope_id") == grant.get("mutation_scope_id")
            and row.get("grant_consumed_at")
        )

    def _item_has_no_authority(self, batch_id: int, item_id: int) -> bool:
        batch = self._private_batch(batch_id)
        private = batch.get("_private")
        rows = private.get("item_authorizations") if isinstance(private, Mapping) else None
        row = next(
            (
                value
                for value in rows or []
                if isinstance(value, Mapping) and int(value.get("item_id") or 0) == item_id
            ),
            None,
        )
        if not isinstance(row, Mapping):
            return False
        return all(
            row.get(key) is None
            for key in (
                "grant_lease_id",
                "grant_fingerprint",
                "grant_nonce_hash",
                "mutation_scope_id",
                "grant",
                "granted_at",
                "grant_expires_at",
                "grant_consumed_at",
            )
        )

    def _reserve_item_mutation(self, command: BrowserAgentCommand) -> None:
        """Create the durable RESERVED boundary immediately before SAVE_ONLY."""

        reserve = getattr(self._mutation_ledger, "reserve_command", None)
        if not callable(reserve):
            raise BatchRuntimeError(
                "MUTATION_LEDGER_REQUIRED",
                "逐件保存账本不可用，系统不会开始处理该商品。",
            )
        try:
            result = reserve(command)
        except Exception as exc:
            raise BatchRuntimeError(
                "MUTATION_LEDGER_UNAVAILABLE",
                f"逐件保存账本不可用：{exc}",
            ) from exc
        accepted = (
            result.get("ok") is True
            if isinstance(result, Mapping)
            else getattr(result, "ok", False) is True
        )
        if not accepted:
            raise BatchRuntimeError(
                _result_reason(result, "MUTATION_LEDGER_RESERVATION_REJECTED"),
                "逐件保存账本未能建立唯一保留项，系统不会继续。",
            )
        entry = self._mutation_ledger.get_entry(
            str(command.mutation_scope_id or ""),
            "save_only_click",
        )
        if (
            not isinstance(entry, Mapping)
            or entry.get("status") != "RESERVED"
            or entry.get("mutation_scope_id") != command.mutation_scope_id
            or entry.get("mutation_action") != "save_only_click"
        ):
            raise BatchRuntimeError(
                "MUTATION_LEDGER_RESERVATION_UNPROVEN",
                "逐件保存账本没有形成可信的 RESERVED 状态，系统不会继续。",
            )

    def _build_command(
        self,
        batch: dict[str, Any],
        item: dict[str, Any],
        grant: Mapping[str, Any] | None,
        step: BatchBrowserStep,
        params: dict[str, Any],
    ) -> BrowserAgentCommand:
        runtime_id = str(self._browser_agent_runtime.runtime_id)
        batch_id = int(batch["id"])
        item_id = int(item["id"])
        mutation_fields: dict[str, Any] = {}
        if step.state == "SAVE_ONLY":
            if not isinstance(grant, Mapping):
                raise BatchRuntimeError(
                    "SAVE_GRANT_REQUIRED",
                    "保存动作缺少逐件授权。",
                    manual_review=True,
                )
            mutation_fields = {
                "mutation_scope_id": grant["mutation_scope_id"],
                "target_hash": mutation_target_hash("save_only", params),
                "authorization_fingerprint": grant["fingerprint"],
                "authorization_lease_id": grant["grant_lease_id"],
                "stage_task_facts_fingerprint": canonical_sha256(
                    {
                        "batch_id": batch_id,
                        "item_id": item_id,
                        "scope_digest": grant["scope_digest"],
                        "template_digest": grant["template_digest"],
                        "policy_digest": grant["policy_digest"],
                        "target_identity_sha256": grant["target_identity_sha256"],
                        "grant_fingerprint": grant["fingerprint"],
                    }
                ),
            }
        now = datetime.now(timezone.utc)
        return BrowserAgentCommand(
            command_id=uuid.uuid4().hex,
            idempotency_key=(
                f"edit-batch:{runtime_id}:{batch_id}:{item_id}:{step.state}:{step.action}"
            ),
            deadline=(now + timedelta(seconds=self._command_timeout_seconds)).isoformat(),
            expected_page=step.expected_page,
            runtime_id=runtime_id,
            task_id=batch_id,
            job_id=item_id,
            state=step.state,
            action=step.action,
            params=params,
            step_label=step.label,
            **mutation_fields,
        )

    def _bundle_defaults(self, batch: Mapping[str, Any]) -> dict[str, Any]:
        template = batch.get("template_snapshot")
        payload = template.get("payload") if isinstance(template, Mapping) else None
        sections = payload.get("sections") if isinstance(payload, Mapping) else None
        if not isinstance(sections, Mapping) or not sections:
            raise BatchRuntimeError("BATCH_TEMPLATE_DEFAULTS_MISSING", "整批模板内容缺失。")
        return {str(key): value for key, value in sections.items()}

    def _assert_batch_can_continue(self, batch_id: int, grant: Mapping[str, Any]) -> None:
        batch = self._private_batch(batch_id)
        if batch.get("status") == "stop_requested":
            raise BatchRuntimeError("OPERATOR_STOPPED", "操作员已停止批次。")
        if batch.get("status") != "running":
            raise BatchRuntimeError("BATCH_NOT_RUNNING", "批次已不在执行状态。", manual_review=True)
        rejection = self._live_binding_rejection(grant)
        if rejection is not None:
            raise BatchRuntimeError(rejection, "运行现场已变化，系统已停止且不会自动重试。", manual_review=True)

    def _live_binding_rejection(self, grant: Mapping[str, Any]) -> str | None:
        facts = dict(self._runtime_facts_provider())
        expected_runtime = grant.get("runtime_identity")
        if facts.get("runtime_identity") != expected_runtime:
            return "BATCH_RUNTIME_IDENTITY_DRIFT"
        if facts.get("git_head") != grant.get("git_head"):
            return "BATCH_GIT_HEAD_DRIFT"
        browser_session_id = str(self._browser_session_provider() or "")
        if not browser_session_id or browser_session_id != grant.get("browser_session_id"):
            return "BATCH_BROWSER_SESSION_DRIFT"
        return None

    def _validate_evidence_refs(self, envelope: Mapping[str, Any]) -> None:
        refs = envelope.get("evidence", {}).get("refs", [])
        for evidence_ref in refs:
            validation = validate_evidence_ref(
                {
                    "path": evidence_ref.get("path"),
                    "sha256": evidence_ref.get("sha256"),
                    "size": evidence_ref.get("size"),
                },
                screenshot_root=Path(SCREENSHOT_DIR),
            )
            if validation.get("ok") is not True:
                raise BatchRuntimeError(
                    str(validation.get("reason_code") or "EVIDENCE_REF_INVALID"),
                    "执行证据文件无法验证，系统已停止。",
                    manual_review=True,
                )

    def _failure_details(
        self,
        exc: Exception,
    ) -> tuple[str, str, bool]:
        if isinstance(exc, BatchRuntimeError):
            return (
                exc.reason_code,
                str(exc),
                True,
            )
        return (
            "BATCH_ITEM_UNEXPECTED_FAILURE",
            f"批次商品执行异常：{exc}",
            True,
        )

    def _stop_batch(
        self,
        batch_id: int,
        reason_code: str,
        reason: str,
        *,
        manual_review: bool,
    ) -> None:
        stop = getattr(self._repository, "stop_edit_batch", None)
        if not callable(stop):
            raise BatchRuntimeError(
                "BATCH_STOP_UNAVAILABLE",
                "批次停止状态无法持久化。",
                manual_review=True,
            )
        result = stop(
            batch_id,
            reason_code=reason_code,
            reason=reason,
            requires_manual_review=manual_review,
        )
        if _cas_applied(result):
            return
        current = self._repository.get_edit_batch(batch_id)
        if isinstance(current, Mapping) and current.get("status") in {"stopped", "completed"}:
            return
        recover = getattr(self._repository, "recover_interrupted_edit_batches", None)
        if callable(recover):
            recover()
            current = self._repository.get_edit_batch(batch_id)
            if isinstance(current, Mapping) and current.get("status") in {"stopped", "completed"}:
                return
        raise BatchRuntimeError(
            _result_reason(result, "BATCH_STOP_PERSISTENCE_FAILED"),
            "批次停止状态无法持久化，运行时已撤销后续动作。",
            manual_review=True,
        )

    def _private_batch(self, batch_id: int) -> dict[str, Any]:
        getter = getattr(self._repository, "get_edit_batch_private", None)
        batch = getter(batch_id) if callable(getter) else None
        if not isinstance(batch, dict):
            raise BatchRuntimeError("BATCH_NOT_FOUND", "批次不存在。")
        return batch

    def _forget_task(self, batch_id: int, completed: asyncio.Task[None]) -> None:
        if self._tasks.get(batch_id) is completed:
            self._tasks.pop(batch_id, None)
        try:
            failure = completed.exception()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            failure = exc
        if failure is not None:
            try:
                self._stop_batch(
                    batch_id,
                    "BATCH_RUNTIME_UNHANDLED_FAILURE",
                    f"批次执行器异常退出：{failure}",
                    manual_review=True,
                )
            except Exception:
                try:
                    self.recover_interrupted_batches()
                except Exception:
                    pass


def _private_value(batch: Mapping[str, Any], key: str) -> Any:
    if key in batch:
        return batch.get(key)
    private = batch.get("_private")
    return private.get(key) if isinstance(private, Mapping) else None


def _execution_contract_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
    missing = _EXECUTION_CONTRACT_BATCH_KEYS - batch.keys()
    if missing:
        raise BatchRuntimeError(
            "BATCH_CONTRACT_FACTS_MISSING",
            f"批次执行事实缺失：{', '.join(sorted(missing))}",
        )
    result = {key: batch[key] for key in _EXECUTION_CONTRACT_BATCH_KEYS}
    approval = batch.get("approval")
    if isinstance(approval, Mapping):
        result["approval"] = dict(approval)
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise BatchRuntimeError("BATCH_ID_INVALID", f"{label} 必须是正整数。")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise BatchRuntimeError("BATCH_ID_INVALID", f"{label} 必须是正整数。") from exc
    if result <= 0:
        raise BatchRuntimeError("BATCH_ID_INVALID", f"{label} 必须是正整数。")
    return result


def _cas_applied(result: Any) -> bool:
    if result is True:
        return True
    if isinstance(result, Mapping):
        return result.get("ok") is True or result.get("applied") is True
    return bool(getattr(result, "ok", False) or getattr(result, "applied", False))


def _result_reason(result: Any, fallback: str) -> str:
    if isinstance(result, Mapping):
        return str(result.get("reason_code") or fallback)
    return str(getattr(result, "reason_code", None) or fallback)
