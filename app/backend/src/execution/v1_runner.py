from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.core.config import DATA_DIR, SCREENSHOT_DIR
from src.execution.action_result_contract import (
    ACTION_RESULT_SCHEMA_VERSION,
    ActionResultContractError,
    validate_action_result_envelope,
    validate_independent_save_verification_pair,
)
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    MUTATION_COMMAND_PLANS,
    MutationCommandContractError,
    browser_agent_command_from_worker_request,
    build_mutation_scope_id,
    canonical_frozen_target_identity,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.dxm_live import DxmLiveClient
from src.repository import Repository, TerminalReportConflictError
from src.services.browser_agent_status import build_browser_hud
from src.services.config_defaults import DEFAULT_TEMPLATE_TYPES, ConfigDefaultsResolver
from src.services.config_validation import ConfigValidationService
from src.services.evidence_ref import validate_evidence_ref
from src.services.ownership_lock import OwnershipLockService
from src.services.publish_guard import PublishGuardService
from src.state_machine.save_authorization import (
    SaveOnlyContractError,
    authorization_context_fingerprint,
    verify_authorization_context,
    verify_exact_save_task_facts,
    verify_product_box_snapshot,
)
from src.state_machine.contracts import StateName, normalize_execution_mode
from src.utils import now_iso


V1_STEPS = [
    (StateName.PRECHECK_CONFIG, "启动前配置校验", "config"),
    (StateName.PRECHECK_SESSION, "检查店小秘登录态", "session"),
    (StateName.PRECHECK_PUBLISH_GUARD, "发布隔离预检", "publish_guard"),
    (StateName.OPEN_DRAFT_LIST, "进入商品箱", "navigation"),
    (StateName.FIND_PRODUCT, "定位目标商品", "ownership"),
    (StateName.ITEM_LOCKING, "创建商品归属锁", "ownership"),
    (StateName.OPEN_EDIT_PAGE, "打开普通编辑页", "editor"),
    (StateName.VERIFY_EDIT_OWNERSHIP, "校验编辑页归属", "ownership"),
    (StateName.FILL_BASE_INFO, "输入标题/选择分类", "base_info"),
    (StateName.FILL_VARIANTS, "设置 SKU / 价格 / 库存", "variants"),
    (StateName.FILL_MEDIA, "处理商品图片和详情图", "media"),
    (StateName.FILL_COMPLIANCE, "填写合规与海关信息", "compliance"),
    (StateName.ENABLE_SEMI_MANAGED, "选择半托管服务", "semi_managed"),
    (StateName.OPEN_SEMI_MANAGED_PAGE, "进入半托管编辑页", "semi_managed"),
    (StateName.FILL_SEMI_GOODS, "设置包装/物流/货品信息", "semi_goods"),
    (StateName.FILL_SEMI_VARIANTS, "设置半托管 SKU / 库存", "semi_variants"),
    (StateName.PRE_SAVE_GUARD_CHECK, "保存前发布隔离复核", "publish_guard"),
    (StateName.SAVE_ONLY, "只点击保存", "save"),
    (StateName.VERIFY_SAVE_RESULT, "读取保存成功提示", "result"),
    (StateName.VERIFY_NOT_PUBLISHED, "确认没有发布", "result"),
    (StateName.WRITE_REPORT, "生成商品执行报告", "report"),
    (StateName.RELEASE_LOCK, "释放商品归属锁", "ownership"),
]


FROZEN_TARGET_STATES = frozenset(
    {
        StateName.OPEN_EDIT_PAGE,
        StateName.VERIFY_EDIT_OWNERSHIP,
        StateName.FILL_BASE_INFO,
        StateName.FILL_VARIANTS,
        StateName.FILL_MEDIA,
        StateName.FILL_COMPLIANCE,
        StateName.ENABLE_SEMI_MANAGED,
        StateName.OPEN_SEMI_MANAGED_PAGE,
        StateName.FILL_SEMI_GOODS,
        StateName.FILL_SEMI_VARIANTS,
        StateName.SAVE_ONLY,
        StateName.VERIFY_NOT_PUBLISHED,
    }
)


def _normalized_observed_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _observed_text_contains_hint(observed_text: str, hint: str) -> bool:
    normalized_hint = _normalized_observed_text(hint)
    if not observed_text or not normalized_hint:
        return False
    if any(character.isascii() and character.isalnum() for character in normalized_hint):
        pattern = rf"(?<![0-9a-z_]){re.escape(normalized_hint)}(?![0-9a-z_])"
        return re.search(pattern, observed_text) is not None
    return normalized_hint in observed_text


def _observed_text_contains_exact_boundary(observed_text: str, expected_text: str) -> bool:
    normalized_observed = _normalized_observed_text(observed_text)
    normalized_expected = _normalized_observed_text(expected_text)
    if not normalized_observed or not normalized_expected:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_expected)}(?!\w)",
        normalized_observed,
    ) is not None

SINGLE_SAVE_STEPS = list(V1_STEPS)

MODE_LAST_STATE = {
    "probe": StateName.PRECHECK_PUBLISH_GUARD,
    "dry_run": StateName.PRECHECK_CONFIG,
    "single_save": StateName.RELEASE_LOCK,
    "batch_save": StateName.RELEASE_LOCK,
}

SINGLE_SAVE_PROGRESS_STEPS = [
    ("start_task", "开始任务", "准备打开店小秘草稿箱"),
    ("open_draft_box", "打开草稿箱", "进入店小秘商品草稿箱"),
    ("find_product", "查找商品", "按商品来源和标题定位草稿"),
    ("open_editor", "打开编辑页", "进入当前商品编辑页"),
    ("fill_title", "输入标题", "填写商品标题和卖点"),
    ("choose_category", "选择分类", "确认商品类目和属性"),
    ("fill_price_stock", "填写价格库存", "填写价格、库存和 SKU 信息"),
    ("handle_images", "处理图片", "检查主图、营销图和外包装图"),
    ("set_logistics", "设置包装物流", "填写重量尺寸和物流模板"),
    ("click_save", "点击保存", "只点击保存，不点击发布"),
    ("verify_unpublished", "确认未发布", "检查商品仍未发布"),
    ("done", "任务完成", "保存成功并确认未发布"),
]

HUD_PROGRESS_TOTAL = len(SINGLE_SAVE_PROGRESS_STEPS)
DEFAULT_WORKFLOW_ACTION_TIMEOUT_SECONDS = 180.0

HUD_PROGRESS_INDEX = {
    StateName.PRECHECK_CONFIG: 1,
    StateName.PRECHECK_SESSION: 1,
    StateName.PRECHECK_PUBLISH_GUARD: 1,
    StateName.OPEN_DRAFT_LIST: 2,
    StateName.FIND_PRODUCT: 3,
    StateName.ITEM_LOCKING: 3,
    StateName.OPEN_EDIT_PAGE: 4,
    StateName.VERIFY_EDIT_OWNERSHIP: 4,
    StateName.FILL_BASE_INFO: 5,
    StateName.FILL_VARIANTS: 7,
    StateName.FILL_MEDIA: 8,
    StateName.FILL_COMPLIANCE: 9,
    StateName.ENABLE_SEMI_MANAGED: 9,
    StateName.OPEN_SEMI_MANAGED_PAGE: 9,
    StateName.FILL_SEMI_GOODS: 9,
    StateName.FILL_SEMI_VARIANTS: 9,
    StateName.PRE_SAVE_GUARD_CHECK: 9,
    StateName.SAVE_ONLY: 10,
    StateName.VERIFY_SAVE_RESULT: 10,
    StateName.VERIFY_NOT_PUBLISHED: 11,
    StateName.WRITE_REPORT: 12,
    StateName.RELEASE_LOCK: 12,
}

HUD_STEP_COPY = {
    StateName.PRECHECK_CONFIG: ("开始任务", "开始任务", "正在检查任务、店铺登录和只保存边界"),
    StateName.PRECHECK_SESSION: ("开始任务", "开始任务", "正在确认店小秘已经登录"),
    StateName.PRECHECK_PUBLISH_GUARD: ("开始任务", "开始任务", "正在确认本次只保存，不发布"),
    StateName.OPEN_DRAFT_LIST: ("打开草稿箱", "打开草稿箱", "正在打开店小秘草稿箱"),
    StateName.FIND_PRODUCT: ("查找商品", "查找商品", "正在查找本次要保存的商品"),
    StateName.ITEM_LOCKING: ("查找商品", "查找商品", "正在锁定本次商品，避免误操作其他商品"),
    StateName.OPEN_EDIT_PAGE: ("打开编辑页", "打开编辑页", "正在进入当前商品编辑页"),
    StateName.VERIFY_EDIT_OWNERSHIP: ("打开编辑页", "打开编辑页", "正在确认编辑页商品匹配"),
    StateName.FILL_BASE_INFO: ("输入标题", "输入标题", "正在输入商品标题和卖点"),
    StateName.FILL_VARIANTS: ("填写价格库存", "填写价格库存", "正在填写 SKU、价格和库存"),
    StateName.FILL_MEDIA: ("处理图片", "处理图片", "正在整理商品主图、营销图和详情图"),
    StateName.FILL_COMPLIANCE: ("设置包装物流", "设置包装物流", "正在填写合规、海关和商品补充信息"),
    StateName.ENABLE_SEMI_MANAGED: ("设置包装物流", "设置包装物流", "正在选择半托管服务，不触碰发布入口"),
    StateName.OPEN_SEMI_MANAGED_PAGE: ("设置包装物流", "设置包装物流", "正在进入半托管编辑页"),
    StateName.FILL_SEMI_GOODS: ("设置包装物流", "设置包装物流", "正在填写重量、尺寸和物流信息"),
    StateName.FILL_SEMI_VARIANTS: ("设置包装物流", "设置包装物流", "正在填写半托管 SKU、价格和库存"),
    StateName.PRE_SAVE_GUARD_CHECK: ("设置包装物流", "设置包装物流", "正在做保存前检查，确认不会发布"),
    StateName.SAVE_ONLY: ("点击保存", "点击保存", "正在点击保存按钮，不点击发布"),
    StateName.VERIFY_SAVE_RESULT: ("点击保存", "点击保存", "正在确认店小秘返回保存成功"),
    StateName.VERIFY_NOT_PUBLISHED: ("确认未发布", "确认未发布", "正在确认商品没有发布"),
    StateName.WRITE_REPORT: ("任务完成", "任务完成", "正在记录保存结果和未发布证明"),
    StateName.RELEASE_LOCK: ("任务完成", "任务完成", "保存成功并确认未发布"),
}

HUD_NEXT_OVERRIDE = {
    StateName.FILL_BASE_INFO: "选择分类",
}

HUD_VIRTUAL_STAGE_AFTER = {
    StateName.FILL_BASE_INFO: {
        "step_code": "SELECT_CATEGORY",
        "step_name": "选择分类",
        "progress_index": 6,
    },
}

WORKFLOW_BROWSER_ACTION_STATES = {
    StateName.PRECHECK_SESSION,
    StateName.OPEN_DRAFT_LIST,
    StateName.OPEN_EDIT_PAGE,
    StateName.VERIFY_EDIT_OWNERSHIP,
    StateName.FILL_BASE_INFO,
    StateName.FILL_VARIANTS,
    StateName.FILL_MEDIA,
    StateName.FILL_COMPLIANCE,
    StateName.ENABLE_SEMI_MANAGED,
    StateName.OPEN_SEMI_MANAGED_PAGE,
    StateName.FILL_SEMI_GOODS,
    StateName.FILL_SEMI_VARIANTS,
    StateName.SAVE_ONLY,
    StateName.VERIFY_NOT_PUBLISHED,
}

WORKFLOW_EXPECTED_PAGE_BY_STATE = {
    StateName.PRECHECK_SESSION: "authenticated_dxm",
    StateName.OPEN_DRAFT_LIST: "draft_box",
    StateName.OPEN_EDIT_PAGE: "editor",
    StateName.VERIFY_EDIT_OWNERSHIP: "editor",
    StateName.FILL_BASE_INFO: "editor",
    StateName.FILL_VARIANTS: "editor",
    StateName.FILL_MEDIA: "editor",
    StateName.FILL_COMPLIANCE: "editor",
    StateName.ENABLE_SEMI_MANAGED: "editor",
    StateName.OPEN_SEMI_MANAGED_PAGE: "semi_managed",
    StateName.FILL_SEMI_GOODS: "semi_managed",
    StateName.FILL_SEMI_VARIANTS: "semi_managed",
    StateName.SAVE_ONLY: "semi_managed",
    StateName.VERIFY_NOT_PUBLISHED: "semi_managed",
}

class V1TaskRunner:
    def __init__(
        self,
        repo: Repository,
        manager,
        workflow_adapter: Any | None = None,
        agent_console: Any | None = None,
        browser_agent_runtime: Any | None = None,
        authorization_verifier: Callable[[int, str, str], Any] | None = None,
        workflow_executor: ThreadPoolExecutor | None = None,
        workflow_action_timeout_seconds: float | None = None,
    ) -> None:
        self.repo = repo
        self.manager = manager
        self.workflow_adapter = workflow_adapter
        self.agent_console = agent_console
        self.browser_agent_runtime = browser_agent_runtime
        self.authorization_verifier = authorization_verifier
        self._workflow_executor = workflow_executor or (ThreadPoolExecutor(max_workers=1) if workflow_adapter is not None else None)
        self.workflow_action_timeout_seconds = (
            float(workflow_action_timeout_seconds)
            if workflow_action_timeout_seconds is not None
            else self._workflow_action_timeout_from_env()
        )
        self.workflow_runtime_unhealthy_reason: str | None = None
        self._active_browser_agent_commands: dict[tuple[int, int, str], BrowserAgentCommand] = {}
        self.live = DxmLiveClient()
        self.publish_guard = PublishGuardService()
        self.config_validation = ConfigValidationService()
        self.defaults_resolver = ConfigDefaultsResolver()
        self.ownership_lock = OwnershipLockService()

    def _workflow_action_timeout_from_env(self) -> float:
        raw = os.getenv("DXM_WORKFLOW_ACTION_TIMEOUT_SECONDS")
        if raw:
            try:
                value = float(raw)
                if value > 0:
                    return value
            except ValueError:
                pass
        return DEFAULT_WORKFLOW_ACTION_TIMEOUT_SECONDS

    def _workflow_action_runtime_from_env(self) -> str:
        raw = (os.getenv("DXM_WORKFLOW_ACTION_RUNTIME") or "auto").strip().lower()
        if raw in {"auto", "thread", "process", "browser_agent"}:
            return raw
        return "auto"

    def _use_browser_agent_runtime(self) -> bool:
        if self._requires_persistent_browser_agent():
            return self.browser_agent_runtime is not None
        if self.browser_agent_runtime is None:
            return False
        runtime = self._workflow_action_runtime_from_env()
        if runtime == "browser_agent":
            return True
        if runtime in {"thread", "process"}:
            return False
        adapter = self.workflow_adapter
        if adapter is None:
            return False
        adapter_class = adapter.__class__
        return adapter_class.__name__ == "DxmWorkflowAdapter" and adapter_class.__module__.endswith("dxm_adapter")

    def _use_process_workflow_runtime(self) -> bool:
        if self._requires_persistent_browser_agent():
            return False
        runtime = self._workflow_action_runtime_from_env()
        if runtime == "browser_agent":
            return False
        if runtime == "thread":
            return False
        if runtime == "process":
            return True
        adapter = self.workflow_adapter
        if adapter is None:
            return False
        adapter_class = adapter.__class__
        return adapter_class.__name__ == "DxmWorkflowAdapter" and adapter_class.__module__.endswith("dxm_adapter")

    def _requires_persistent_browser_agent(self) -> bool:
        return getattr(self.workflow_adapter, "requires_persistent_browser_agent", False) is True

    async def run_task(self, task_id: int) -> None:
        task = self.repo.get_task_private(task_id)
        if not task:
            return
        try:
            mode = normalize_execution_mode(task.get("mode") or task.get("payload", {}).get("execution_mode") or "single_save").value
        except ValueError as exc:
            self.repo.update_task_status(task_id, "failed", completed_jobs=0, failed_jobs=len(task.get("jobs", [])))
            for job in task.get("jobs", []):
                self.repo.update_job(
                    job["id"],
                    status="failed",
                    current_step_code="FAILED",
                    current_step_name="禁止的执行模式",
                    error_code="E999",
                    error_message=str(exc),
                )
                self.repo.add_exception(
                    task_id,
                    job["id"],
                    "E999",
                    "publish_guard",
                    "禁止的执行模式",
                    str(exc),
                    "改为 probe、dry_run、single_save 或 batch_save。",
                )
            await self.manager.broadcast(task_id, {"type": "task_status", "status": "failed", "taskId": task_id})
            return
        if not self.repo.try_update_task_status(
            task_id,
            "running",
            expected_statuses=("draft", "running"),
        ):
            return
        await self.manager.broadcast(task_id, {"type": "task_status", "status": "running", "taskId": task_id, "mode": mode})

        completed = 0
        failed = 0
        for job in task["jobs"]:
            success = await self._run_job(task, job, mode)
            if success is None:
                return
            if success:
                completed += 1
            else:
                failed += 1
                failed_task = self.repo.get_task(task_id)
                if failed_task and failed_task.get("status") == "failed":
                    await self.manager.broadcast(task_id, {
                        "type": "task_status",
                        "taskId": task_id,
                        "status": "failed",
                        "completedJobs": failed_task.get("completed_jobs", completed),
                        "failedJobs": failed_task.get("failed_jobs", failed),
                    })
                    return
            if not self.repo.try_update_task_status(
                task_id,
                "running",
                expected_statuses=("running",),
                completed_jobs=completed,
                failed_jobs=failed,
            ):
                return
            await self.manager.broadcast(task_id, {
                "type": "job_completed",
                "taskId": task_id,
                "jobId": job["id"],
                "completedJobs": completed,
                "failedJobs": failed,
            })

        final_status = "completed" if failed == 0 else ("partial_success" if completed else "failed")
        if not self.repo.try_update_task_status(
            task_id,
            final_status,
            expected_statuses=("running",),
            completed_jobs=completed,
            failed_jobs=failed,
        ):
            return
        await self.manager.broadcast(task_id, {
            "type": "task_status",
            "taskId": task_id,
            "status": final_status,
            "completedJobs": completed,
            "failedJobs": failed,
        })

    async def _run_job(self, task: dict[str, Any], job: dict[str, Any], mode: str) -> bool | None:
        task_id = task["id"]
        job_id = job["id"]
        product_id = job.get("product_id")
        product = self._product(product_id)
        execution_defaults = self._execution_defaults(task, product)
        lock_token: str | None = None
        filled_fields: list[str] = []
        empty_fields: list[str] = []
        evidence_paths: list[str] = []
        workflow_results: list[dict[str, Any]] = []
        agent_console_events: list[dict[str, Any]] = []
        agent_action_events: list[dict[str, Any]] = []
        live_browser_hud_events: list[dict[str, Any]] = []
        last_state = MODE_LAST_STATE[mode]
        current_state_name = StateName.PRECHECK_CONFIG
        current_step_name = "启动前配置校验"
        current_field_domain = "precheck"

        self.repo.update_job(job_id, status="running", current_step_code="PRECHECK_CONFIG", current_step_name="启动前配置校验")
        self.repo.add_log(task_id, job_id, "info", "V1 执行开始", {"mode": mode, "product_id": product_id})

        try:
            if self.workflow_adapter is None and mode in {"single_save", "batch_save"}:
                raise V1ExecutionError("E901", "缺少真实工作流适配器", f"{mode} requires workflow_adapter")

            for state_name, step_name, field_domain in self._steps_for_mode(mode):
                current_state_name = state_name
                current_step_name = step_name
                current_field_domain = field_domain
                self._guard_step(task, job, state_name, product)
                self.repo.update_job(job_id, status="running", current_step_code=state_name.value, current_step_name=step_name)
                evidence_path = self._write_evidence(task_id, job_id, state_name)
                evidence_paths.append(str(evidence_path))
                agent_console_event = self._sync_agent_console(
                    task,
                    job,
                    mode,
                    state_name,
                    step_name,
                    field_domain,
                    str(evidence_path),
                )
                if agent_console_event:
                    agent_console_events.append(agent_console_event)
                live_browser_hud_event = self._sync_live_browser_hud(
                    task,
                    job,
                    mode,
                    state_name,
                    step_name,
                    field_domain,
                    str(evidence_path),
                )
                if live_browser_hud_event:
                    live_browser_hud_events.append(live_browser_hud_event)
                evidence_meta = {
                    "state": state_name.value,
                    "field_domain": field_domain,
                    "mode": mode,
                }
                if agent_console_event:
                    evidence_meta["agent_console"] = agent_console_event
                if live_browser_hud_event:
                    evidence_meta["live_browser_hud"] = live_browser_hud_event
                self.repo.add_evidence(task_id, job_id, "state_snapshot", str(evidence_path), evidence_meta)
                self.repo.add_log(task_id, job_id, "info", f"执行步骤：{step_name}", {
                    "state": state_name.value,
                    "field_domain": field_domain,
                    "mode": mode,
                })

                if state_name == StateName.ITEM_LOCKING:
                    lock = self.ownership_lock.acquire_lock(
                        task_id=task_id,
                        job_id=job_id,
                        product_id=product_id or job_id,
                        store_name=self._store_name(task),
                        source_title=self._source_title(product_id),
                        ownership_tag_base="DXM-LOCK",
                    )
                    if lock["conflict"]:
                        raise V1ExecutionError("E202", "商品归属锁冲突", lock["reason"])
                    lock_token = lock["lock_token"]

                if mode == "single_save" and state_name == StateName.SAVE_ONLY:
                    self._assert_real_mutation_authorized(task_id, mode, state_name)
                workflow_result = await self._run_workflow_action_async(task, job, state_name, execution_defaults)
                if workflow_result:
                    if state_name == StateName.VERIFY_NOT_PUBLISHED:
                        self._assert_save_and_unpublished_proofs_independent(
                            workflow_results,
                            workflow_result,
                        )
                    agent_action_event = self._sync_agent_action(
                        task,
                        job,
                        mode,
                        state_name,
                        step_name,
                        field_domain,
                        workflow_result,
                    )
                    if agent_action_event:
                        agent_action_events.append(agent_action_event)
                    workflow_results.append(workflow_result)
                    workflow_meta = {
                        "state": state_name.value,
                        "action": workflow_result.get("action"),
                        "stage": workflow_result.get("stage"),
                        "page_title": workflow_result.get("page_title"),
                        "page_url": workflow_result.get("page_url"),
                        "ok": workflow_result.get("ok"),
                        "product_query": workflow_result.get("product_query"),
                        "store_name": workflow_result.get("store_name"),
                        "save_result": workflow_result.get("save_result"),
                        "dxm_reference_template_results": workflow_result.get("dxm_reference_template_results"),
                    }
                    required_action_evidence = state_name in {
                        StateName.SAVE_ONLY,
                        StateName.VERIFY_NOT_PUBLISHED,
                    }
                    evidence_ref = workflow_result.get("evidence_ref")
                    if not required_action_evidence and not isinstance(evidence_ref, Mapping):
                        nested_evidence = workflow_result.get("evidence")
                        evidence_ref = (
                            nested_evidence.get("evidence_ref")
                            if isinstance(nested_evidence, Mapping)
                            else None
                        )
                    valid_evidence_ref = (
                        isinstance(evidence_ref, Mapping)
                        and set(evidence_ref) == {"path", "sha256", "size"}
                        and isinstance(evidence_ref.get("path"), str)
                        and bool(evidence_ref.get("path"))
                        and isinstance(evidence_ref.get("sha256"), str)
                        and bool(evidence_ref.get("sha256"))
                        and isinstance(evidence_ref.get("size"), int)
                        and not isinstance(evidence_ref.get("size"), bool)
                        and evidence_ref.get("size") > 0
                    )
                    workflow_evidence_path = workflow_result.get("screenshot_url")
                    if valid_evidence_ref:
                        workflow_meta["evidence_ref"] = dict(evidence_ref)
                        workflow_evidence_path = evidence_ref["path"]
                    if agent_action_event:
                        workflow_meta["agent_action"] = agent_action_event
                    self.repo.add_evidence(task_id, job_id, "workflow_action", workflow_evidence_path, workflow_meta)

                virtual_hud = HUD_VIRTUAL_STAGE_AFTER.get(state_name)
                if virtual_hud:
                    agent_console_event = self._sync_agent_console(
                        task,
                        job,
                        mode,
                        state_name,
                        step_name,
                        field_domain,
                        str(evidence_path),
                        hud_override=virtual_hud,
                    )
                    if agent_console_event:
                        agent_console_events.append(agent_console_event)
                    live_browser_hud_event = self._sync_live_browser_hud(
                        task,
                        job,
                        mode,
                        state_name,
                        step_name,
                        field_domain,
                        str(evidence_path),
                        hud_override=virtual_hud,
                    )
                    if live_browser_hud_event:
                        live_browser_hud_events.append(live_browser_hud_event)
                    virtual_meta = {
                        "state": virtual_hud["step_code"],
                        "field_domain": field_domain,
                        "mode": mode,
                        "source_state": state_name.value,
                    }
                    if agent_console_event:
                        virtual_meta["agent_console"] = agent_console_event
                    if live_browser_hud_event:
                        virtual_meta["live_browser_hud"] = live_browser_hud_event
                    self.repo.add_evidence(task_id, job_id, "state_snapshot", str(evidence_path), virtual_meta)

                if state_name in {
                    StateName.FILL_BASE_INFO,
                    StateName.FILL_VARIANTS,
                    StateName.FILL_MEDIA,
                    StateName.FILL_COMPLIANCE,
                    StateName.FILL_SEMI_GOODS,
                    StateName.FILL_SEMI_VARIANTS,
                }:
                    filled_fields.append(field_domain)

                if state_name == StateName.PRE_SAVE_GUARD_CHECK:
                    result = self.publish_guard.check(
                        intended_action="save",
                        target_text="保存",
                        current_url="https://www.dianxiaomi.com/web/smt/editFromSmt",
                        visible_texts=["保存"],
                        modal_texts=[],
                        network_urls=["https://www.dianxiaomi.com/api/smt/product/save"],
                    )
                    if not result["allowed"]:
                        raise V1ExecutionError("E999", "发布风险被拦截", "; ".join(result["reasons"]))

                if state_name == StateName.RELEASE_LOCK and lock_token:
                    self.ownership_lock.release_lock(lock_token)
                    lock_token = None

                await self.manager.broadcast(task_id, {
                    "type": "step_update",
                    "taskId": task_id,
                    "jobId": job_id,
                    "productId": product_id,
                    "stepCode": state_name.value,
                    "stepName": step_name,
                    "fieldDomain": field_domain,
                    "screenshotPath": str(evidence_path),
                    "timestamp": now_iso(),
                })
                await asyncio.sleep(0.03)

                if state_name == last_state:
                    break

            if mode in {"probe", "dry_run"}:
                empty_fields.append("未进入商品保存字段，当前模式不需要填写")
            if mode in {"single_save", "batch_save"}:
                empty_fields.append("货品条码：配置允许留空")

            summary = self._build_summary(
                task,
                job,
                mode,
                filled_fields,
                empty_fields,
                evidence_paths,
                workflow_results,
                execution_defaults,
                agent_console_events=agent_console_events,
                agent_action_events=agent_action_events,
                live_browser_hud_events=live_browser_hud_events,
            )
            if mode in {"single_save", "batch_save"}:
                self._revalidate_terminal_action_evidence(workflow_results)
            save_result = self._save_result_for_mode(mode, workflow_results)
            summary["published"] = save_result["published"]
            finalized = self.repo.finalize_job_success(
                task_id,
                job_id,
                product_id,
                published=save_result["published"],
                save_result=save_result,
                summary=summary,
            )
            if not finalized.applied:
                if finalized.conflict_code == TerminalReportConflictError.conflict_code:
                    raise TerminalReportConflictError(task_id, job_id)
                raise _JobTerminalTransitionRejected(finalized.conflict_code, finalized.reason)
            self.repo.add_log(
                task_id,
                job_id,
                "success",
                "V1 商品流程完成",
                {"mode": mode, "published": save_result["published"]},
            )
            return True
        except _JobTerminalTransitionRejected:
            return None
        except Exception as exc:
            if lock_token:
                self.ownership_lock.release_lock(lock_token)
            if isinstance(exc, V1ExecutionError):
                error = exc
            elif isinstance(exc, TerminalReportConflictError):
                error = V1ExecutionError(exc.conflict_code, "报告终态冲突", str(exc))
            else:
                error = V1ExecutionError("E999", "V1 执行失败", str(exc))
            failure_override = self._failure_hud_override(error)
            failure_evidence_path = evidence_paths[-1] if evidence_paths else ""
            agent_console_event = self._sync_agent_console(
                task,
                job,
                mode,
                current_state_name,
                current_step_name,
                current_field_domain,
                failure_evidence_path,
                hud_override=failure_override,
            )
            if agent_console_event:
                agent_console_events.append(agent_console_event)
            live_browser_hud_event = self._sync_live_browser_hud(
                task,
                job,
                mode,
                current_state_name,
                current_step_name,
                current_field_domain,
                failure_evidence_path,
                hud_override=failure_override,
            )
            if live_browser_hud_event:
                live_browser_hud_events.append(live_browser_hud_event)
            failure_summary = self._build_summary(
                task,
                job,
                mode,
                filled_fields,
                empty_fields,
                evidence_paths,
                workflow_results,
                execution_defaults,
                blocked_reason=error.detail,
                agent_console_events=agent_console_events,
                agent_action_events=agent_action_events,
                live_browser_hud_events=live_browser_hud_events,
            )
            finalized = self.repo.finalize_job_failure(
                task_id,
                job_id,
                product_id,
                error_code=error.error_code,
                field_domain="v1_executor",
                title=error.title,
                detail=error.detail,
                suggestion="检查配置、页面状态和证据后重试；禁止忽略发布或归属风险继续执行。",
                save_result={"ok": False, "error_code": error.error_code, "message": error.detail},
                summary=failure_summary,
            )
            if not finalized.applied:
                return None
            self.repo.add_log(task_id, job_id, "error", error.title, {"error_code": error.error_code, "detail": error.detail})
            return False

    def _steps_for_mode(self, mode: str):
        if mode == "dry_run":
            return [V1_STEPS[0]]
        if mode == "single_save":
            return SINGLE_SAVE_STEPS
        return V1_STEPS

    def _sync_agent_console(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        state_name: StateName,
        step_name: str,
        field_domain: str,
        screenshot_path: str,
        hud_override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.agent_console is None:
            return None
        try:
            result = self.agent_console.update_task_step(**self._hud_step_payload(
                task,
                job,
                mode,
                state_name,
                step_name,
                field_domain,
                screenshot_path,
                hud_override=hud_override,
            ))
        except Exception as exc:
            result = {
                "ok": False,
                "updated": False,
                "reason": "agent_console_exception",
                "error": str(exc),
            }
        if result.get("reason") == "agent_console_inactive":
            return None
        return self._agent_console_summary(result)

    def _sync_live_browser_hud(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        state_name: StateName,
        step_name: str,
        field_domain: str,
        screenshot_path: str,
        hud_override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        updater = getattr(self.workflow_adapter, "update_live_hud", None)
        if not callable(updater):
            return None
        payload = self._hud_step_payload(
            task,
            job,
            mode,
            state_name,
            step_name,
            field_domain,
            screenshot_path,
            hud_override=hud_override,
        )
        try:
            if self._use_browser_agent_runtime() and self.browser_agent_runtime is not None:
                runtime_status: Mapping[str, Any] = {}
                status_reader = getattr(self.browser_agent_runtime, "status", None)
                if callable(status_reader):
                    try:
                        status_payload = status_reader()
                        if isinstance(status_payload, Mapping):
                            runtime_status = status_payload
                    except Exception:
                        runtime_status = {}
                if runtime_status.get("healthy") is False:
                    result = {
                        "ok": False,
                        "updated": False,
                        "reason": "live_browser_hud_runtime_unhealthy",
                        "error": runtime_status.get("lastError") or runtime_status.get("unhealthyReason"),
                    }
                else:
                    result = {
                        "ok": True,
                        "updated": False,
                        "reason": "live_browser_hud_deferred_to_browser_agent",
                        "current_url": runtime_status.get("currentUrl") or runtime_status.get("current_url"),
                        "page_title": runtime_status.get("pageTitle") or runtime_status.get("page_title"),
                        "hud": payload,
                    }
            elif self._workflow_executor is not None:
                result = self._workflow_executor.submit(updater, payload).result(timeout=8)
            else:
                result = updater(payload)
        except (FutureTimeoutError, TimeoutError):
            result = {
                "ok": False,
                "updated": False,
                "reason": "live_browser_hud_timeout",
                "error": "live browser HUD update timed out",
            }
        except Exception as exc:
            result = {
                "ok": False,
                "updated": False,
                "reason": "live_browser_hud_exception",
                "error": str(exc),
            }
        hud = result.get("hud") if isinstance(result.get("hud"), Mapping) else payload
        return {
            "ok": bool(result.get("ok", True)),
            "updated": bool(result.get("updated")),
            "reason": result.get("reason"),
            "task_id": task["id"],
            "job_id": job["id"],
            "product_id": job.get("product_id"),
            "current_url": result.get("current_url"),
            "page_title": result.get("page_title"),
            "last_step_code": payload.get("step_code") or state_name.value,
            "last_step_name": payload.get("step_name") or step_name,
            "hud": {
                "title": hud.get("title") or payload.get("step_name") or step_name,
                "state": hud.get("state") or payload.get("step_code") or state_name.value,
                "action": hud.get("action"),
                "line1": hud.get("line1") or payload.get("line1"),
                "line2": hud.get("line2") or payload.get("line2"),
                "next_step": hud.get("next_step"),
                "store_name": hud.get("store_name"),
                "guard": hud.get("guard"),
                "phase": hud.get("phase"),
                "progress_index": hud.get("progress_index"),
                "progress_total": hud.get("progress_total"),
                "severity": hud.get("severity"),
                "human_title": hud.get("human_title"),
                "human_action": hud.get("human_action"),
                "human_next": hud.get("human_next"),
                "requires_user_action": hud.get("requires_user_action"),
                "maintenance_detail": hud.get("maintenance_detail") or payload.get("maintenance_detail"),
            },
            "screenshot": result.get("screenshot"),
            "updated_at": result.get("updated_at"),
            "last_error": result.get("last_error") or result.get("error"),
        }

    def _hud_step_payload(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        state_name: StateName,
        step_name: str,
        field_domain: str,
        screenshot_path: str,
        hud_override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        override = hud_override or {}
        resolved_step_code = str(override.get("step_code") or state_name.value)
        resolved_step_name = str(override.get("step_name") or step_name)
        store_name = self._store_name(task)
        hud = build_browser_hud({
            "task_name": "商品箱编辑保存",
            "step": resolved_step_code,
            "status": override.get("status") or "running",
            "severity": override.get("severity"),
            "requires_user_action": override.get("requires_user_action"),
            "maintenance_detail": override.get("maintenance_detail"),
            "store_name": store_name,
            "guard": "只保存不发布",
            "phase": override.get("phase"),
            "progress_index": override.get("progress_index") or self._progress_index(mode, state_name),
            "progress_total": self._progress_total(mode),
            "human_title": override.get("human_title"),
            "human_action": override.get("human_action"),
            "human_next": override.get("human_next") or override.get("next_step"),
        })
        return {
            "task_id": task["id"],
            "job_id": job["id"],
            "product_id": job.get("product_id"),
            "step_code": resolved_step_code,
            "step_name": resolved_step_name,
            "field_domain": field_domain,
            "mode": mode,
            "store_name": store_name,
            "title": hud["title"],
            "line1": hud["line1"],
            "line2": hud["line2"],
            "next_step": hud["next_step"] or self._next_step_name(mode, state_name),
            "screenshot_path": screenshot_path,
            "guard": hud["guard"],
            "phase": hud["phase"],
            "progress_index": hud["progress_index"],
            "progress_total": hud["progress_total"],
            "severity": hud["severity"],
            "human_title": hud["human_title"],
            "human_action": hud["human_action"],
            "human_next": hud["human_next"],
            "requires_user_action": hud["requires_user_action"],
            "maintenance_detail": hud.get("maintenance_detail"),
        }

    def _failure_hud_override(self, error: V1ExecutionError) -> dict[str, Any]:
        return {
            "step_code": "TASK_FAILED",
            "step_name": "当前步骤失败",
            "status": "failed",
            "severity": "error",
            "phase": "需要人工处理",
            "human_title": "当前步骤失败",
            "human_action": "请按页面提示处理后重试，真实保存不会继续",
            "human_next": "查看结果与问题，确认原因后重试",
            "requires_user_action": True,
            "maintenance_detail": f"{error.error_code}: {error.detail}",
        }

    def _agent_console_summary(self, result: Mapping[str, Any]) -> dict[str, Any]:
        hud = result.get("hud") if isinstance(result.get("hud"), Mapping) else {}
        return {
            "ok": bool(result.get("ok", True)),
            "updated": bool(result.get("updated")),
            "reason": result.get("reason"),
            "session_id": result.get("session_id"),
            "task_id": result.get("task_id"),
            "job_id": result.get("job_id"),
            "product_id": result.get("product_id"),
            "browser_visible": result.get("browser_visible"),
            "current_url": result.get("current_url"),
            "last_step_code": result.get("last_step_code") or hud.get("state"),
            "last_step_name": result.get("last_step_name") or hud.get("title"),
            "hud": {
                "title": hud.get("title"),
                "state": hud.get("state"),
                "action": hud.get("action"),
                "line1": hud.get("line1"),
                "line2": hud.get("line2"),
                "next_step": hud.get("next_step"),
                "store_name": hud.get("store_name"),
                "guard": hud.get("guard"),
                "phase": hud.get("phase"),
                "progress_index": hud.get("progress_index"),
                "progress_total": hud.get("progress_total"),
                "severity": hud.get("severity"),
                "human_title": hud.get("human_title"),
                "human_action": hud.get("human_action"),
                "human_next": hud.get("human_next"),
                "recent_actions": hud.get("recent_actions"),
                "requires_user_action": hud.get("requires_user_action"),
                "maintenance_detail": hud.get("maintenance_detail"),
            },
            "screenshot": result.get("screenshot"),
            "updated_at": result.get("updated_at"),
            "last_error": result.get("last_error") or result.get("error"),
        }

    def _sync_agent_action(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        state_name: StateName,
        step_name: str,
        field_domain: str,
        workflow_result: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if self.agent_console is None:
            return None
        action_name = str(workflow_result.get("action") or state_name.value)
        save_result = self._extract_save_result(dict(workflow_result)) if action_name == "save_only" else None
        try:
            result = self.agent_console.record_action_event(
                task_id=task["id"],
                job_id=job["id"],
                product_id=job.get("product_id"),
                type=self._agent_action_type(action_name),
                action=action_name,
                label=step_name,
                state=state_name.value,
                step_code=state_name.value,
                field_domain=field_domain,
                status="ok" if workflow_result.get("ok") else "failed",
                target=self._agent_action_target(action_name, workflow_result),
                page_url=workflow_result.get("page_url"),
                screenshot_url=workflow_result.get("screenshot_url"),
                save_result=save_result,
                store_name=self._store_name(task),
            )
        except Exception as exc:
            result = {
                "ok": False,
                "updated": False,
                "reason": "agent_console_exception",
                "error": str(exc),
            }
        if result.get("reason") == "agent_console_inactive":
            return None
        summary = self._agent_console_summary(result)
        action_events = result.get("action_events") if isinstance(result.get("action_events"), list) else []
        if action_events:
            summary["action_event"] = action_events[-1]
            return action_events[-1]
        summary["action_event"] = {
            "type": self._agent_action_type(action_name),
            "action": action_name,
            "label": step_name,
            "state": state_name.value,
            "step_code": state_name.value,
            "task_id": task["id"],
            "job_id": job["id"],
            "product_id": job.get("product_id"),
            "field_domain": field_domain,
            "status": "ok" if workflow_result.get("ok") else "failed",
            "target": self._agent_action_target(action_name, workflow_result),
            "page_url": workflow_result.get("page_url"),
            "screenshot_url": workflow_result.get("screenshot_url"),
            "save_result": save_result,
            "store_name": self._store_name(task),
        }
        return {key: value for key, value in summary["action_event"].items() if value is not None}

    def _agent_action_type(self, action_name: str) -> str:
        if action_name == "save_only":
            return "save"
        if action_name == "fill_media_assets":
            return "upload"
        if action_name.startswith("fill_"):
            return "fill"
        if action_name in {"enable_semi_managed"}:
            return "select"
        if action_name.startswith("verify_") or action_name == "check_login_state":
            return "wait"
        if action_name.startswith("open_"):
            return "click"
        return "workflow_action"

    def _agent_action_target(self, action_name: str, workflow_result: Mapping[str, Any]) -> str | None:
        if action_name == "save_only":
            return "保存"
        if action_name.startswith("fill_"):
            return str(workflow_result.get("product_query") or "编辑页字段")
        if action_name.startswith("open_"):
            return str(workflow_result.get("page_url") or "店小秘页面")
        return str(workflow_result.get("stage") or "") or None

    def _next_step_name(self, mode: str, current_state: StateName) -> str | None:
        steps = self._steps_for_mode(mode)
        for index, (state_name, _step_name, _field_domain) in enumerate(steps):
            if state_name == current_state:
                if state_name == MODE_LAST_STATE[mode]:
                    return "任务收尾与报告"
                if index + 1 < len(steps):
                    return steps[index + 1][1]
                return None
        return None

    def _progress_index(self, mode: str, current_state: StateName) -> int | None:
        return HUD_PROGRESS_INDEX.get(current_state)

    def _progress_total(self, mode: str) -> int:
        return HUD_PROGRESS_TOTAL

    def _hud_phase(self, state_name: StateName) -> str:
        return HUD_STEP_COPY.get(state_name, ("业务进度", state_name.value, "正在推进任务"))[0]

    def _human_title(self, state_name: StateName, fallback: str) -> str:
        return HUD_STEP_COPY.get(state_name, ("业务进度", fallback, "正在推进任务"))[1]

    def _human_action(self, state_name: StateName, field_domain: str | None, mode: str) -> str:
        configured = HUD_STEP_COPY.get(state_name)
        if configured:
            return configured[2]
        parts = [part for part in (field_domain, mode) if part]
        return "正在推进：" + " / ".join(parts) if parts else "正在推进任务"

    def _human_next(self, mode: str, current_state: StateName) -> str:
        if current_state in HUD_NEXT_OVERRIDE:
            return HUD_NEXT_OVERRIDE[current_state]
        steps = self._steps_for_mode(mode)
        for index, (state_name, step_name, _field_domain) in enumerate(steps):
            if state_name != current_state:
                continue
            if state_name == MODE_LAST_STATE[mode]:
                return "任务收尾与报告"
            if index + 1 < len(steps):
                next_state = steps[index + 1][0]
                return self._human_title(next_state, steps[index + 1][1])
            return "等待下一步"
        return "等待下一步"

    def _guard_step(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        product: Mapping[str, Any] | None = None,
    ) -> None:
        if state_name == StateName.PRECHECK_CONFIG:
            mode = task.get("mode", "")
            validation = self.config_validation.validate_task(task, self.repo.list_templates(), product=product)
            if not validation["ok"]:
                detail = "缺少配置：" + ", ".join(validation["missing"]) if validation["missing"] else "; ".join(validation["warnings"])
                raise V1ExecutionError(validation["error_code"] or "E302", "启动前配置校验失败", detail)
            if mode in {"single_save", "batch_save"} and task.get("publish_scene") != "SMT_SEMI_MANAGED_SAVE_ONLY":
                raise V1ExecutionError("E999", "任务发布场景不安全", "V1 只允许 SMT_SEMI_MANAGED_SAVE_ONLY")
            if mode == "single_save":
                self._guard_single_save_product_box_item(task, job, product)
        if state_name == StateName.SAVE_ONLY:
            result = self.publish_guard.check(intended_action="save", target_text="保存")
            if not result["allowed"]:
                raise V1ExecutionError("E999", "保存动作被发布隔离器阻断", "; ".join(result["reasons"]))

    def _assert_real_mutation_authorized(
        self,
        task_id: int,
        mode: str,
        state_name: StateName,
    ) -> None:
        verifier = self.authorization_verifier
        if verifier is None:
            raise V1ExecutionError(
                "AUTH_VERIFIER_MISSING",
                "真实写入授权校验器缺失",
                f"{mode} cannot enter {state_name.value} without exact lease revalidation",
            )
        try:
            result = verifier(int(task_id), mode, state_name.value)
        except V1ExecutionError:
            raise
        except Exception as exc:
            reason_code = str(
                getattr(exc, "reason_code", None)
                or getattr(exc, "error_code", None)
                or "AUTH_REVALIDATION_FAILED"
            )
            raise V1ExecutionError(
                reason_code,
                "真实写入授权已失效",
                str(exc) or reason_code,
            ) from exc
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            reason_code = (
                str(result.get("reason_code") or "AUTH_REVALIDATION_FAILED")
                if isinstance(result, Mapping)
                else "AUTH_REVALIDATION_FAILED"
            )
            raise V1ExecutionError(
                reason_code,
                "真实写入授权已失效",
                reason_code,
            )

    def _guard_single_save_product_box_item(
        self,
        task: Mapping[str, Any],
        job: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> None:
        if not product:
            raise V1ExecutionError(
                "E202",
                "保存任务缺少商品箱商品",
                "单商品只保存必须绑定当前已验证的商品箱商品；系统不会打开编辑页或保存。",
            )
        status = str(product.get("status") or "")
        payload = product.get("payload") if isinstance(product.get("payload"), Mapping) else {}
        source = str(product.get("source") or "").strip()
        if status != "ready_for_edit":
            raise V1ExecutionError(
                "E202",
                "保存任务商品未进入商品箱",
                "当前商品不是可编辑的商品箱商品；请从当前商品箱重新选择并创建只保存任务。",
            )
        if source != "dxm_draft_box":
            raise V1ExecutionError(
                "E202",
                "保存任务商品来源不正确",
                "单商品只保存只能处理系统从店小秘商品箱捕获的真实商品；手工导入或测试商品不会启动真实保存。",
            )
        if payload.get("draft_box_verified") is not True:
            raise V1ExecutionError(
                "E202",
                "商品箱验证未完成",
                "当前商品尚未通过商品箱验证；请先确认商品已进入商品箱后再启动只保存。",
            )
        if not self._payload_source_urls(payload):
            raise V1ExecutionError(
                "E202",
                "商品箱身份校验证据不足",
                "单商品只保存必须确认商品箱中能唯一匹配本次商品；系统不会打开编辑页或保存。",
            )
        snapshot_error = self.repo.single_save_product_box_snapshot_error(
            dict(task),
            dict(product),
        )
        if snapshot_error:
            raise V1ExecutionError(
                "E202",
                "商品箱身份快照已变化",
                f"{snapshot_error}；请从当前商品箱重新创建单商品只保存任务。",
            )
        self._frozen_single_save_target_identity(task, job)

    def _frozen_single_save_target_identity(
        self,
        task: Mapping[str, Any],
        job: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Derive the mutation target only from the immutable product-box snapshot."""

        mode = str(task.get("mode") or "").strip()
        if mode != "single_save":
            raise V1ExecutionError(
                "E999",
                "真实编辑入口未开放",
                "只有具有完整商品箱证据的单商品只保存任务可以进入真实编辑链。",
            )
        product_id = job.get("product_id")
        if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
            raise V1ExecutionError("E202", "商品身份无效", "single_save job is not bound to one exact product")
        payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        snapshot = payload.get("product_box_snapshot")
        if not isinstance(snapshot, Mapping):
            raise V1ExecutionError(
                "E202",
                "商品箱证据缺失",
                "single_save requires an immutable product-box snapshot",
            )
        snapshot_check = verify_product_box_snapshot(snapshot)
        if snapshot_check.get("ok") is not True:
            raise V1ExecutionError(
                "E202",
                "商品箱证据无效",
                str(snapshot_check.get("reason_code") or "PRODUCT_BOX_SNAPSHOT_INVALID"),
            )
        if snapshot.get("product_id") != product_id:
            raise V1ExecutionError("E202", "商品箱身份不一致", "snapshot product does not match this job")
        _store_id, authoritative_store_name = self._authoritative_store(task)
        store_name = " ".join(authoritative_store_name.split())
        if " ".join(str(snapshot.get("store_name") or "").split()) != store_name:
            raise V1ExecutionError("E202", "商品箱店铺身份不一致", "snapshot store does not match this task")
        try:
            target = canonical_frozen_target_identity(snapshot.get("target_identity"), store_name=store_name)
        except MutationCommandContractError as exc:
            raise V1ExecutionError("E202", "商品箱精确身份无效", str(exc)) from exc
        if target is None:
            raise V1ExecutionError("E202", "商品箱精确身份缺失", "frozen target validator returned no target")
        return target

    def _workflow_action_worker_request(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        defaults: dict[str, Any],
    ) -> tuple[str, str, str, dict[str, Any]] | None:
        product_query = self._source_title(job.get("product_id"))
        target_source_urls = self._target_source_urls(task, job)
        store_name = self._store_name(task)
        specs: dict[StateName, tuple[str, str, str, dict[str, Any]]] = {
            StateName.PRECHECK_SESSION: (
                "check_login_state",
                "E101",
                "店小秘登录态检查失败",
                {},
            ),
            StateName.OPEN_DRAFT_LIST: (
                "open_draft_box",
                "E201",
                "进入商品箱失败",
                {},
            ),
            StateName.OPEN_EDIT_PAGE: (
                "open_editor",
                "E901",
                "打开编辑页失败",
                {
                    "product_query": product_query,
                    "store_name": store_name,
                    "target_source_urls": target_source_urls,
                },
            ),
            StateName.VERIFY_EDIT_OWNERSHIP: (
                "verify_edit_ownership",
                "E202",
                "编辑页归属校验失败",
                {
                    "product_query": product_query,
                    "store_name": store_name,
                    "target_source_urls": target_source_urls,
                },
            ),
            StateName.FILL_BASE_INFO: (
                "fill_editor_required_defaults",
                "E901",
                "填写普通编辑页必填项失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.FILL_VARIANTS: (
                "fill_editor_variants",
                "E901",
                "填写普通变种表格失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.FILL_MEDIA: (
                "fill_media_assets",
                "E901",
                "处理图片素材失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.FILL_COMPLIANCE: (
                "fill_compliance_defaults",
                "E901",
                "填写合规信息失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.ENABLE_SEMI_MANAGED: (
                "enable_semi_managed",
                "E901",
                "勾选半托管服务失败",
                {
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.OPEN_SEMI_MANAGED_PAGE: (
                "open_semi_managed_page",
                "E901",
                "打开半托管编辑页失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.FILL_SEMI_GOODS: (
                "fill_semi_managed_defaults",
                "E901",
                "填写半托管货品信息失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.FILL_SEMI_VARIANTS: (
                "fill_semi_managed_defaults",
                "E901",
                "填写半托管变种信息失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
            StateName.SAVE_ONLY: (
                "save_only",
                "E999",
                "只保存失败",
                {
                    "defaults": defaults,
                    "product_query": product_query,
                    "store_name": store_name,
                    "target_source_urls": target_source_urls,
                },
            ),
            StateName.VERIFY_NOT_PUBLISHED: (
                "verify_not_published",
                "E999",
                "未发布状态校验失败",
                {
                    "product_query": product_query,
                    "store_name": store_name,
                },
            ),
        }
        spec = specs.get(state_name)
        if spec is None or state_name not in FROZEN_TARGET_STATES:
            return spec
        action_name, error_code, error_title, params = spec
        return (
            action_name,
            error_code,
            error_title,
            {
                **params,
                "target_identity": self._frozen_single_save_target_identity(task, job),
            },
        )

    def _run_workflow_action_process(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        defaults: dict[str, Any],
    ) -> dict[str, Any] | None:
        spec = self._workflow_action_worker_request(task, job, state_name, defaults)
        if spec is None:
            return None
        action_name, error_code, error_title, params = spec
        if state_name == StateName.SAVE_ONLY:
            self._assert_manual_approval_before_save(task)

        runtime_id = self._browser_agent_runtime_id()
        request = {
            "command_id": uuid.uuid4().hex,
            "idempotency_key": (
                f"v1:{runtime_id}:{task.get('id')}:"
                f"{job.get('id')}:{state_name.value}:{action_name}"
            ),
            "deadline": (
                datetime.now(timezone.utc) + timedelta(seconds=self.workflow_action_timeout_seconds)
            ).isoformat(),
            "expected_page": self._expected_page_for_state(state_name),
            "runtime_id": runtime_id,
            "task_id": task.get("id"),
            "job_id": job.get("id"),
            "state": state_name.value,
            "action": action_name,
            "params": params,
        }
        result = self._invoke_workflow_worker(
            request=request,
            state_name=state_name,
            action_name=action_name,
            error_code=error_code,
            error_title=error_title,
        )
        validated_result = self._validate_workflow_action_result(
            state_name=state_name,
            action_name=action_name,
            error_code=error_code,
            error_title=error_title,
            result=result,
        )
        validated_result["workflow_runtime"] = "process"
        return validated_result

    def _run_workflow_action_browser_agent(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        defaults: dict[str, Any],
        command: BrowserAgentCommand | None = None,
    ) -> dict[str, Any] | None:
        if self.browser_agent_runtime is None:
            return None
        spec = self._workflow_action_worker_request(task, job, state_name, defaults)
        if spec is None:
            return None
        action_name, error_code, error_title, params = spec
        if state_name == StateName.SAVE_ONLY:
            self._assert_manual_approval_before_save(task)

        command = command or self._build_browser_agent_command(
            task,
            job,
            state_name,
            action_name,
            params,
        )
        command_key = (int(task["id"]), int(job["id"]), state_name.value)
        self._active_browser_agent_commands[command_key] = command
        try:
            result = self.browser_agent_runtime.run(
                command,
                timeout_seconds=self.workflow_action_timeout_seconds,
            )
        except TimeoutError as exc:
            self._cancel_browser_agent_command(command)
            self._active_browser_agent_commands.pop(command_key, None)
            detail = self._browser_agent_timeout_detail(state_name)
            self.workflow_runtime_unhealthy_reason = detail
            raise V1ExecutionError(
                "E901",
                "真实浏览器操作超时",
                detail,
            ) from exc
        except Exception as exc:
            self._active_browser_agent_commands.pop(command_key, None)
            detail = self._workflow_exception_detail(action_name, exc)
            self.workflow_runtime_unhealthy_reason = detail
            raise V1ExecutionError(error_code, error_title, detail) from exc
        try:
            validated_result = self._validate_workflow_action_result(
                state_name=state_name,
                action_name=action_name,
                error_code=error_code,
                error_title=error_title,
                result=result,
            )
        finally:
            self._active_browser_agent_commands.pop(command_key, None)
        validated_result["workflow_runtime"] = "browser_agent"
        validated_result.setdefault("browser_agent_command", command.to_payload())
        return validated_result

    def _build_browser_agent_command(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        action_name: str,
        params: dict[str, Any],
    ) -> BrowserAgentCommand:
        runtime_id = self._browser_agent_runtime_id()
        mutation_scope = self._build_browser_agent_mutation_scope(
            task,
            job,
            state_name,
            action_name,
            params,
        )
        request = {
            "command_id": uuid.uuid4().hex,
            "idempotency_key": (
                f"v1:{runtime_id}:{task.get('id')}:{job.get('id')}:"
                f"{state_name.value}:{action_name}"
            ),
            "deadline": (
                datetime.now(timezone.utc) + timedelta(seconds=self.workflow_action_timeout_seconds)
            ).isoformat(),
            "expected_page": self._expected_page_for_state(state_name),
            "runtime_id": runtime_id,
            "task_id": task.get("id"),
            "job_id": job.get("id"),
            "state": state_name.value,
            "action": action_name,
            "params": dict(params),
            **mutation_scope,
        }
        command = browser_agent_command_from_worker_request(
            request,
            step_label=self._workflow_step_label(state_name),
        )
        if mutation_scope or (state_name.value, action_name) not in MUTATION_COMMAND_PLANS:
            try:
                validate_browser_agent_command(command)
            except MutationCommandContractError as exc:
                raise V1ExecutionError(
                    "E999",
                    "真实浏览器变更范围无效",
                    f"{exc.reason_code}: browser mutation command scope is invalid; no mutation was dispatched.",
                ) from exc
        return command

    def _build_browser_agent_mutation_scope(
        self,
        task: Mapping[str, Any],
        job: Mapping[str, Any],
        state_name: StateName,
        action_name: str,
        params: dict[str, Any],
    ) -> dict[str, str]:
        if (state_name, action_name) != (StateName.SAVE_ONLY, "save_only"):
            return {}
        if not self._requires_persistent_browser_agent():
            # Synthetic adapters used for contract and timeout tests do not
            # perform external DXM mutations, so they do not consume a real
            # authorization lease or durable mutation ledger scope.
            return {}

        try:
            task_id = int(task.get("id"))
            job_id = int(job.get("id"))
        except (TypeError, ValueError) as exc:
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization scope requires canonical task and job IDs; no mutation was dispatched.",
            ) from exc
        if task_id <= 0 or job_id <= 0:
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization scope requires positive task and job IDs; no mutation was dispatched.",
            )

        current_task = self.repo.get_task_private(task_id)
        payload = (
            current_task.get("payload")
            if isinstance(current_task, Mapping) and isinstance(current_task.get("payload"), Mapping)
            else {}
        )
        approval = payload.get("manual_approval") if isinstance(payload, Mapping) else None
        if not isinstance(approval, Mapping):
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization lease is missing; no mutation was dispatched.",
            )
        lease_id = str(approval.get("lease_id") or "").strip()
        if (
            approval.get("approved") is not True
            or approval.get("source") != "server"
            or approval.get("consumed") is not True
            or not str(approval.get("consumed_at") or "").strip()
            or not lease_id
        ):
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization lease is absent or unconsumed; no mutation was dispatched.",
            )

        authorization_context = approval.get("authorization_context")
        stage_task_facts = approval.get("stage_task_facts")
        if not isinstance(authorization_context, Mapping) or not isinstance(stage_task_facts, Mapping):
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization context or exact stage facts are missing; no mutation was dispatched.",
            )
        context_facts = authorization_context.get("stage_task_facts")
        if not isinstance(context_facts, Mapping) or dict(context_facts) != dict(stage_task_facts):
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization stage facts have drifted; no mutation was dispatched.",
            )
        context_check = verify_authorization_context(authorization_context)
        facts_check = verify_exact_save_task_facts(stage_task_facts)
        if context_check.get("ok") is not True or facts_check.get("ok") is not True:
            reason_code = (
                context_check.get("reason_code")
                if context_check.get("ok") is not True
                else facts_check.get("reason_code")
            )
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                f"{reason_code}: mutation authorization contract is invalid; no mutation was dispatched.",
            )
        if (
            isinstance(stage_task_facts.get("task_id"), bool)
            or isinstance(stage_task_facts.get("job_id"), bool)
            or stage_task_facts.get("task_id") != task_id
            or stage_task_facts.get("job_id") != job_id
        ):
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                "mutation authorization stage facts do not bind this task and job; no mutation was dispatched.",
            )

        try:
            target_digest = mutation_target_hash(action_name, params)
            authorization_digest = authorization_context_fingerprint(authorization_context)
            stage_digest = str(stage_task_facts.get("fingerprint") or "")
            scope_id = build_mutation_scope_id(
                authorization_lease_id=lease_id,
                task_id=task_id,
                job_id=job_id,
                state=state_name.value,
                action=action_name,
            )
        except (MutationCommandContractError, SaveOnlyContractError) as exc:
            reason_code = getattr(exc, "reason_code", "MUTATION_SCOPE_INVALID")
            raise V1ExecutionError(
                "E999",
                "真实浏览器变更范围无效",
                f"{reason_code}: mutation target or authorization fingerprint is invalid; no mutation was dispatched.",
            ) from exc
        return {
            "mutation_scope_id": scope_id,
            "target_hash": target_digest,
            "authorization_fingerprint": authorization_digest,
            "authorization_lease_id": lease_id,
            "stage_task_facts_fingerprint": stage_digest,
        }

    def _cancel_browser_agent_command(self, command: BrowserAgentCommand | None) -> dict[str, Any] | None:
        if command is None or self.browser_agent_runtime is None:
            return None
        cancel = getattr(self.browser_agent_runtime, "cancel_command", None)
        if not callable(cancel):
            return None
        try:
            result = cancel(command.command_id, command.runtime_id)
        except Exception:
            return None
        return dict(result) if isinstance(result, Mapping) else None

    def _expected_page_for_state(self, state_name: StateName) -> str:
        expected_page = WORKFLOW_EXPECTED_PAGE_BY_STATE.get(state_name)
        if not expected_page:
            raise V1ExecutionError(
                "E901",
                "真实浏览器页面契约缺失",
                f"步骤 {state_name.value} 没有受控 expected_page 映射；系统已停止任务，不会保存或发布。",
            )
        return expected_page

    def _browser_agent_runtime_id(self) -> str:
        runtime = self.browser_agent_runtime
        runtime_id = str(getattr(runtime, "runtime_id", "") or "").strip()
        if runtime_id:
            return runtime_id
        status_getter = getattr(runtime, "status", None)
        if callable(status_getter):
            try:
                status = status_getter()
            except Exception:
                status = None
            if isinstance(status, Mapping):
                runtime_id = str(status.get("runtimeId") or "").strip()
                if runtime_id:
                    return runtime_id
        return f"test-runtime-{id(runtime)}"

    def _invoke_workflow_worker(
        self,
        *,
        request: dict[str, Any],
        state_name: StateName,
        action_name: str,
        error_code: str,
        error_title: str,
    ) -> dict[str, Any]:
        task_id = request.get("task_id") or "task"
        job_id = request.get("job_id") or "job"
        worker_dir = DATA_DIR / "workflow_worker"
        worker_dir.mkdir(parents=True, exist_ok=True)
        file_stem = f"task_{task_id}_job_{job_id}_{state_name.value}_{uuid.uuid4().hex}"
        request_file = worker_dir / f"{file_stem}.request.json"
        result_file = worker_dir / f"{file_stem}.result.json"
        trace_file = worker_dir / f"{file_stem}.trace.jsonl"
        request_file.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        backend_dir = Path(__file__).resolve().parents[2]
        command = [
            sys.executable,
            "-m",
            "src.execution.workflow_worker",
            "--request-file",
            str(request_file),
            "--result-file",
            str(result_file),
        ]
        env = os.environ.copy()
        env["DXM_WORKFLOW_TRACE_FILE"] = str(trace_file)
        env.setdefault("DXM_WORKFLOW_PERSISTENT_PROFILE", "1")
        try:
            completed = subprocess.run(
                command,
                cwd=str(backend_dir),
                env=env,
                text=True,
                capture_output=True,
                timeout=self.workflow_action_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            trace_tail = self._workflow_trace_tail(trace_file)
            detail = self._workflow_action_timeout_detail(state_name)
            if trace_tail:
                detail = f"{detail} 最近执行轨迹：{trace_tail}"
            raise V1ExecutionError(
                "E901",
                "真实浏览器操作超时",
                detail,
            ) from exc

        if not result_file.exists():
            detail = self._workflow_worker_process_detail(
                action_name=action_name,
                completed=completed,
                fallback="执行器没有写回结果文件。",
            )
            raise V1ExecutionError(error_code, error_title, detail)

        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception as exc:
            detail = self._workflow_worker_process_detail(
                action_name=action_name,
                completed=completed,
                fallback=f"执行器结果文件无法读取：{exc}",
            )
            raise V1ExecutionError(error_code, error_title, detail) from exc

        if payload.get("ok") is not True:
            error_text = " ".join(
                str(value or "")
                for value in (
                    payload.get("error"),
                    payload.get("traceback"),
                    completed.stderr,
                    completed.stdout,
                )
                if value
            )
            browser_detail = self._operator_browser_failure_detail(error_text)
            detail = browser_detail or f"{action_name}: {error_text or '真实浏览器执行器返回失败'}"
            raise V1ExecutionError(error_code, error_title, detail[:1200])

        result = payload.get("result")
        if not isinstance(result, dict):
            detail = self._workflow_worker_process_detail(
                action_name=action_name,
                completed=completed,
                fallback="执行器结果格式不正确。",
            )
            raise V1ExecutionError(error_code, error_title, detail)
        return result

    def _workflow_trace_tail(self, trace_file: Path, limit: int = 5) -> str:
        if not trace_file.exists():
            return ""
        try:
            lines = trace_file.read_text(encoding="utf-8").splitlines()[-limit:]
        except Exception:
            return str(trace_file)
        events: list[str] = []
        for line in lines:
            try:
                item = json.loads(line)
            except Exception:
                events.append(line[:200])
                continue
            event = str(item.get("event") or "")
            url = str(item.get("current_url") or item.get("url") or "")
            events.append(f"{event} {url}".strip())
        return " / ".join(events)[:1200]

    def _workflow_worker_process_detail(
        self,
        *,
        action_name: str,
        completed: subprocess.CompletedProcess[str],
        fallback: str,
    ) -> str:
        parts = [f"{action_name}: {fallback}", f"exit_code={completed.returncode}"]
        if completed.stderr:
            parts.append(f"stderr={completed.stderr.strip()[:800]}")
        if completed.stdout:
            parts.append(f"stdout={completed.stdout.strip()[:800]}")
        return "; ".join(parts)[:1200]

    def _validate_workflow_action_result(
        self,
        *,
        state_name: StateName,
        action_name: str,
        error_code: str,
        error_title: str,
        result: Any,
    ) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise V1ExecutionError(
                error_code,
                error_title,
                f"{action_name} result must be a mapping with ok=true",
            )
        result_dict = dict(result)
        if result_dict.get("schema_version") != ACTION_RESULT_SCHEMA_VERSION:
            legacy_detail = (
                self._workflow_failure_detail(action_name, result_dict)
                if result_dict.get("ok") is not True
                else f"{action_name} result is missing {ACTION_RESULT_SCHEMA_VERSION}"
            )
            raise V1ExecutionError(
                error_code,
                error_title,
                f"ACTION_RESULT_CONTRACT_MISSING: {legacy_detail}",
            )
        try:
            envelope = validate_action_result_envelope(
                result_dict,
                expected_state=state_name.value,
                expected_action=action_name,
            )
        except ActionResultContractError as exc:
            raise V1ExecutionError(
                error_code,
                error_title,
                f"{exc.reason_code}: {exc}",
            ) from exc

        if envelope["ok"] is not True:
            recovery = envelope.get("recoverability") or {}
            operator_detail = self._workflow_failure_detail(action_name, result_dict)
            observations = envelope.get("evidence", {}).get("observations", {})
            save_failure = (
                observations.get("save_result")
                if isinstance(observations, Mapping)
                and isinstance(observations.get("save_result"), Mapping)
                else {}
            )
            save_failure_bits = [
                save_failure.get("reason"),
                save_failure.get("message"),
            ]
            network_failure = save_failure.get("network_save_result")
            if isinstance(network_failure, Mapping):
                save_failure_bits.extend(
                    (network_failure.get("reason"), network_failure.get("message"))
                )
            network_events = save_failure.get("network_events")
            if isinstance(network_events, list):
                save_failure_bits.append(f"保存接口捕获 {len(network_events)} 条")
            save_failure_detail = "; ".join(
                str(item) for item in save_failure_bits if item
            )
            contract_detail = (
                f"{action_name} save_result missing or false: {envelope.get('failure_code')}; "
                f"{save_failure_detail or recovery.get('reason') or 'no recovery detail'}"
                if action_name == "save_only"
                else (
                    f"{action_name} failed: {envelope.get('failure_code')}; "
                    f"{recovery.get('reason') or 'no recovery detail'}"
                )
            )
            raise V1ExecutionError(
                error_code,
                error_title,
                (
                    f"{operator_detail}; {contract_detail}"
                    if operator_detail and contract_detail not in operator_detail
                    else operator_detail or contract_detail
                ),
            )

        normalized_refs: list[dict[str, Any]] = []
        for evidence_ref in envelope["evidence"]["refs"]:
            validated_ref = self._validate_action_evidence_ref(
                {
                    "path": evidence_ref.get("path"),
                    "sha256": evidence_ref.get("sha256"),
                    "size": evidence_ref.get("size"),
                },
                action_name=action_name,
                error_code=error_code,
                error_title=error_title,
            )
            normalized_refs.append(
                {
                    **validated_ref,
                    "kind": evidence_ref["kind"],
                    "captured_at": evidence_ref["captured_at"],
                }
            )
        envelope["evidence"]["refs"] = normalized_refs
        return self._workflow_action_compatibility_view(envelope)

    @staticmethod
    def _workflow_action_compatibility_view(envelope: Mapping[str, Any]) -> dict[str, Any]:
        """Expose trusted legacy read paths only after the canonical envelope passes."""

        canonical = dict(envelope)
        observations = canonical["evidence"]["observations"]
        before_values = canonical["before_values"]
        after_values = canonical["after_values"]

        def observation_value(key: str) -> Any:
            if key in observations:
                return observations.get(key)
            for source_name in (
                "verification_result",
                "draft_action_result",
                "editor_action_result",
                "fill_result",
                "save_result",
                "unpublished_proof",
                "navigation_result",
                "wait_result",
                "login_check",
                "live_probe",
            ):
                source = observations.get(source_name)
                if isinstance(source, Mapping) and key in source:
                    return source.get(key)
            return None

        target_identity = before_values.get("target_identity")
        target_identity = target_identity if isinstance(target_identity, Mapping) else {}
        refs = canonical["evidence"]["refs"]
        basic_ref = (
            {
                "path": refs[0]["path"],
                "sha256": refs[0]["sha256"],
                "size": refs[0]["size"],
            }
            if refs
            else None
        )
        result = {
            "ok": True,
            "action": canonical["action"],
            "stage": canonical["attempted_state"],
            "page_title": observation_value("page_title"),
            "page_url": canonical["page_identity"]["url"],
            "screenshot_url": basic_ref["path"] if basic_ref else observation_value("screenshot_url"),
            "product_query": before_values.get("product_query") or target_identity.get("product_query"),
            "store_name": before_values.get("store_name") or target_identity.get("store_name"),
            "save_result": observation_value("save_result"),
            "fill_result": observation_value("fill_result"),
            "unpublished_proof": observation_value("unpublished_proof"),
            "published": after_values.get("published"),
            "evidence": dict(observations),
            "evidence_ref": basic_ref,
            "dxm_reference_template_results": observation_value(
                "dxm_reference_template_results"
            ),
            "action_result": canonical,
        }
        return result

    def _validate_action_evidence_ref(
        self,
        value: Any,
        *,
        action_name: str,
        error_code: str,
        error_title: str,
    ) -> dict[str, Any]:
        validation = validate_evidence_ref(
            value,
            screenshot_root=Path(SCREENSHOT_DIR),
        )
        if validation.get("ok") is not True:
            reason_code = str(validation.get("reason_code") or "EVIDENCE_REF_INVALID")
            raise V1ExecutionError(
                error_code,
                error_title,
                f"{action_name} evidence_ref invalid: {reason_code}",
            )
        return {
            "path": validation["path"],
            "sha256": validation["sha256"],
            "size": validation["size"],
        }

    def _assert_save_and_unpublished_proofs_independent(
        self,
        prior_results: list[dict[str, Any]],
        verification_result: Mapping[str, Any],
    ) -> None:
        save_envelope = next(
            (
                result.get("action_result")
                for result in reversed(prior_results)
                if isinstance(result.get("action_result"), Mapping)
                and result["action_result"].get("attempted_state") == StateName.SAVE_ONLY.value
            ),
            None,
        )
        verification_envelope = verification_result.get("action_result")
        if not isinstance(save_envelope, Mapping) or not isinstance(
            verification_envelope, Mapping
        ):
            raise V1ExecutionError(
                "E999",
                "保存与未发布证据链不完整",
                "SAVE_ONLY and VERIFY_NOT_PUBLISHED require canonical action results",
            )
        try:
            validate_independent_save_verification_pair(
                save_envelope,
                verification_envelope,
            )
        except ActionResultContractError as exc:
            raise V1ExecutionError(
                "E999",
                "未发布证据不是独立复核",
                f"{exc.reason_code}: {exc}",
            ) from exc

    def _revalidate_terminal_action_evidence(
        self,
        workflow_results: list[dict[str, Any]],
    ) -> None:
        required_actions = {
            "save_only": "只保存证据终态复核失败",
            "verify_not_published": "未发布证据终态复核失败",
        }
        for action_name, error_title in required_actions.items():
            matches = [
                result
                for result in workflow_results
                if result.get("action") == action_name
            ]
            if len(matches) != 1:
                raise V1ExecutionError(
                    "E999",
                    error_title,
                    f"{action_name} requires exactly one validated evidence_ref",
                )
            matches[0]["evidence_ref"] = self._validate_action_evidence_ref(
                matches[0].get("evidence_ref"),
                action_name=action_name,
                error_code="E999",
                error_title=error_title,
            )

    def _run_workflow_action(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        defaults: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.workflow_adapter is None:
            return None

        product_query = self._source_title(job.get("product_id"))
        target_source_urls = self._target_source_urls(task, job)
        store_name = self._store_name(task)
        target_identity = (
            self._frozen_single_save_target_identity(task, job)
            if state_name in FROZEN_TARGET_STATES
            else None
        )
        actions = {
            StateName.PRECHECK_SESSION: ("check_login_state", "E101", "店小秘登录态检查失败", lambda: self.workflow_adapter.check_login_state()),
            StateName.OPEN_DRAFT_LIST: ("open_draft_box", "E201", "进入商品箱失败", lambda: self.workflow_adapter.open_draft_box()),
            StateName.OPEN_EDIT_PAGE: (
                "open_editor",
                "E901",
                "打开编辑页失败",
                lambda: self.workflow_adapter.open_editor(
                    product_query=product_query,
                    store_name=store_name,
                    target_source_urls=target_source_urls,
                    target_identity=target_identity,
                ),
            ),
            StateName.VERIFY_EDIT_OWNERSHIP: (
                "verify_edit_ownership",
                "E202",
                "编辑页归属校验失败",
                lambda: self.workflow_adapter.verify_edit_ownership(
                    product_query=product_query,
                    store_name=store_name,
                    target_source_urls=target_source_urls,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_BASE_INFO: (
                "fill_editor_required_defaults",
                "E901",
                "填写普通编辑页必填项失败",
                lambda: self.workflow_adapter.fill_editor_required_defaults(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_VARIANTS: (
                "fill_editor_variants",
                "E901",
                "填写普通变种表格失败",
                lambda: self.workflow_adapter.fill_editor_variants(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_MEDIA: (
                "fill_media_assets",
                "E901",
                "处理图片素材失败",
                lambda: self.workflow_adapter.fill_media_assets(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_COMPLIANCE: (
                "fill_compliance_defaults",
                "E901",
                "填写合规信息失败",
                lambda: self.workflow_adapter.fill_compliance_defaults(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.ENABLE_SEMI_MANAGED: (
                "enable_semi_managed",
                "E901",
                "勾选半托管服务失败",
                lambda: self.workflow_adapter.enable_semi_managed(
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.OPEN_SEMI_MANAGED_PAGE: (
                "open_semi_managed_page",
                "E901",
                "打开半托管编辑页失败",
                lambda: self.workflow_adapter.open_semi_managed_page(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_SEMI_GOODS: (
                "fill_semi_managed_defaults",
                "E901",
                "填写半托管货品信息失败",
                lambda: self.workflow_adapter.fill_semi_managed_defaults(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.FILL_SEMI_VARIANTS: (
                "fill_semi_managed_defaults",
                "E901",
                "填写半托管变种信息失败",
                lambda: self.workflow_adapter.fill_semi_managed_defaults(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.SAVE_ONLY: (
                "save_only",
                "E999",
                "只保存失败",
                lambda: self.workflow_adapter.save_only(
                    defaults=defaults,
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
            StateName.VERIFY_NOT_PUBLISHED: (
                "verify_not_published",
                "E999",
                "未发布状态校验失败",
                lambda: self.workflow_adapter.verify_not_published(
                    product_query=product_query,
                    store_name=store_name,
                    target_identity=target_identity,
                ),
            ),
        }
        action = actions.get(state_name)
        if action is None:
            return None

        action_name, error_code, error_title, call = action
        adapter_method = getattr(self.workflow_adapter, action_name, None)
        if action_name in {"fill_media_assets", "fill_compliance_defaults"} and not callable(adapter_method):
            raise V1ExecutionError(
                error_code,
                error_title,
                f"{action_name} adapter method unavailable",
            )
        if state_name == StateName.SAVE_ONLY:
            self._assert_manual_approval_before_save(task)
        command_context = {
            "task_id": task.get("id"),
            "job_id": job.get("id"),
            "state": state_name.value,
            "mode": str(task.get("mode") or ""),
            "command_id": uuid.uuid4().hex,
        }
        mutation_setter = getattr(self.workflow_adapter, "set_mutation_authorizer", None)
        mutation_clearer = getattr(self.workflow_adapter, "clear_mutation_authorizer", None)
        evidence_setter = getattr(self.workflow_adapter, "set_execution_evidence_context", None)
        evidence_clearer = getattr(self.workflow_adapter, "clear_execution_evidence_context", None)
        if callable(mutation_setter):
            mutation_setter(
                lambda _context, operation: self._mutation_click_authorization_result(
                    task,
                    state_name,
                    operation,
                ),
                command_context,
            )
        if callable(evidence_setter):
            evidence_setter(command_context)
        try:
            result = call()
        except Exception as exc:
            raise V1ExecutionError(error_code, error_title, self._workflow_exception_detail(action_name, exc)) from exc
        finally:
            if callable(mutation_clearer):
                mutation_clearer()
            if callable(evidence_clearer):
                evidence_clearer()

        return self._validate_workflow_action_result(
            state_name=state_name,
            action_name=action_name,
            error_code=error_code,
            error_title=error_title,
            result=result,
        )

    def _mutation_click_authorization_result(
        self,
        task: Mapping[str, Any],
        state_name: StateName,
        operation: Callable[[], Any],
    ) -> dict[str, Any]:
        if not callable(operation):
            return {
                "ok": False,
                "executed": False,
                "reason_code": "MUTATION_OPERATION_INVALID",
            }
        mode = str(task.get("mode") or "")
        if state_name != StateName.SAVE_ONLY:
            operation_result = operation()
            return {
                "ok": True,
                "executed": True,
                "operation_result": operation_result,
                "reason_code": "NON_MUTATING_STATE",
            }
        self._assert_real_mutation_authorized(int(task["id"]), mode, state_name)
        operation_result = operation()
        return {
            "ok": True,
            "executed": True,
            "operation_result": operation_result,
            "reason_code": "OK",
        }

    def _assert_manual_approval_before_save(self, task: Mapping[str, Any]) -> None:
        current_task = self.repo.get_task_private(int(task["id"])) if task.get("id") is not None else None
        payload = (current_task or task).get("payload") if isinstance((current_task or task).get("payload"), Mapping) else {}
        approval = payload.get("manual_approval") if isinstance(payload, Mapping) else {}
        if not isinstance(approval, Mapping):
            approval = {}
        if (
            approval.get("approved") is True
            and approval.get("source") == "server"
            and bool(str(approval.get("approved_by") or "").strip())
        ):
            return
        raise V1ExecutionError(
            "E999",
            "缺少人工确认",
            "保存前人工确认未完成：请在控制台填写批准人，确认只保存、不发布后再启动单商品只保存。",
        )

    def _workflow_exception_detail(self, action_name: str, exc: Exception) -> str:
        browser_detail = self._operator_browser_failure_detail(str(exc))
        if browser_detail:
            return browser_detail
        return f"{action_name}: {exc}"

    def _workflow_failure_detail(self, action_name: str, result: Mapping[str, Any]) -> str:
        evidence = result.get("evidence") if isinstance(result.get("evidence"), Mapping) else {}
        browser_detail = self._operator_browser_failure_detail(
            result.get("message"),
            result.get("reason"),
            result.get("error"),
            evidence.get("message"),
            evidence.get("reason"),
            evidence.get("error"),
        )
        if browser_detail:
            return browser_detail

        page_identity = result.get("page_identity") if isinstance(result.get("page_identity"), Mapping) else {}
        stage = result.get("stage") or result.get("attempted_state") or "unknown_stage"
        page_url = result.get("page_url") or page_identity.get("url") or "unknown_url"
        parts = [f"{action_name} failed at {stage}: {page_url}"]

        for value in (result.get("message"), result.get("reason"), result.get("error")):
            if value:
                parts.append(str(value))

        for value in (evidence.get("message"), evidence.get("reason"), evidence.get("error")):
            if value:
                parts.append(str(value))

        save_result = self._extract_save_result(dict(result)) if action_name == "save_only" else None
        if isinstance(save_result, Mapping):
            for value in (save_result.get("message"), save_result.get("reason"), save_result.get("success_text")):
                if value:
                    parts.append(f"保存结果：{value}")
            network_result = save_result.get("network_save_result")
            if isinstance(network_result, Mapping):
                network_bits = [
                    network_result.get("message"),
                    network_result.get("msg"),
                    network_result.get("reason"),
                    f"status={network_result.get('status')}" if network_result.get("status") is not None else None,
                    f"code={network_result.get('code')}" if network_result.get("code") is not None else None,
                ]
                network_text = " ".join(str(item) for item in network_bits if item)
                if network_text:
                    parts.append(f"保存接口：{network_text}")
            events = save_result.get("network_events")
            if isinstance(events, list):
                parts.append(f"保存接口捕获 {len(events)} 条")

        seen: set[str] = set()
        compact_parts: list[str] = []
        for part in parts:
            text = str(part).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            compact_parts.append(text)
        return "; ".join(compact_parts)[:1200]

    def _operator_browser_failure_detail(self, *values: Any) -> str | None:
        text = " ".join(str(value or "") for value in values)
        lowered = text.casefold()
        browser_failure_terms = (
            "target page, context or browser has been closed",
            "browser has been closed",
            "page.evaluate",
            "cannot switch to a different thread",
            "playwright sync api inside the asyncio loop",
            "greenlet",
        )
        if not any(term in lowered for term in browser_failure_terms):
            return None
        return (
            "真实浏览器窗口已关闭或失去连接，本次任务已停止，不会保存或发布。"
            "请关闭残留的店小秘浏览器和旧后台进程，重新打开执行浏览器后再重试。"
        )

    async def _run_workflow_action_async(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        defaults: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.workflow_adapter is None:
            return None
        task_id = int(task["id"])
        job_id = int(job["id"])
        label = self._workflow_step_label(state_name)
        should_log_browser_action = state_name in WORKFLOW_BROWSER_ACTION_STATES
        runtime_setting = self._workflow_action_runtime_from_env()
        if self._requires_persistent_browser_agent():
            self._require_persistent_browser_agent_ready()
        if runtime_setting == "browser_agent" and self.browser_agent_runtime is None:
            raise V1ExecutionError(
                "E901",
                "自动浏览器未配置",
                "当前已指定使用持久在线真实浏览器，但后端没有装配自动浏览器运行时；系统已停止任务，不会保存或发布。",
            )
        use_browser_agent_runtime = self._use_browser_agent_runtime()
        use_process_runtime = (not use_browser_agent_runtime) and self._use_process_workflow_runtime()
        runtime_name = "browser_agent" if use_browser_agent_runtime else "process" if use_process_runtime else "thread"
        if should_log_browser_action:
            self.repo.add_log(task_id, job_id, "info", f"真实浏览器动作开始：{label}", {
                "state": state_name.value,
                "timeout_seconds": self.workflow_action_timeout_seconds,
                "runtime": runtime_name,
            })
        loop = asyncio.get_running_loop()
        if use_browser_agent_runtime:
            command_spec = self._workflow_action_worker_request(
                task,
                job,
                state_name,
                defaults,
            )
            if command_spec is None:
                return None
            action_name, _error_code, _error_title, params = command_spec
            if state_name == StateName.SAVE_ONLY:
                self._assert_manual_approval_before_save(task)
            browser_agent_command = self._build_browser_agent_command(
                task,
                job,
                state_name,
                action_name,
                params,
            )
            reserve = getattr(self.browser_agent_runtime, "reserve_command", None)
            if callable(reserve):
                try:
                    reservation = reserve(browser_agent_command)
                except Exception as exc:
                    raise V1ExecutionError(
                        "E901",
                        "真实浏览器命令预留失败",
                        f"真实浏览器 runtime binding 或命令预留失败：{exc}；系统已停止任务，不会保存或发布。",
                    ) from exc
                if not isinstance(reservation, Mapping) or reservation.get("ok") is not True:
                    reason = reservation.get("reasonCode") if isinstance(reservation, Mapping) else "invalid_reservation"
                    raise V1ExecutionError(
                        "E901",
                        "真实浏览器命令预留失败",
                        f"真实浏览器命令预留被拒绝：{reason}；系统已停止任务，不会保存或发布。",
                    )
            command_key = (task_id, job_id, state_name.value)
            self._active_browser_agent_commands[command_key] = browser_agent_command
            future = loop.run_in_executor(
                None,
                self._run_workflow_action_browser_agent,
                task,
                job,
                state_name,
                defaults,
                browser_agent_command,
            )
            wait_timeout = self.workflow_action_timeout_seconds + 10
        elif use_process_runtime:
            future = loop.run_in_executor(
                None,
                self._run_workflow_action_process,
                task,
                job,
                state_name,
                defaults,
            )
            wait_timeout = self.workflow_action_timeout_seconds + 10
        else:
            future = loop.run_in_executor(
                self._workflow_executor,
                self._run_workflow_action,
                task,
                job,
                state_name,
                defaults,
            )
            wait_timeout = self.workflow_action_timeout_seconds
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=wait_timeout)
            if should_log_browser_action and result:
                self.repo.add_log(task_id, job_id, "success", f"真实浏览器动作完成：{label}", {
                    "state": state_name.value,
                    "action": result.get("action"),
                    "stage": result.get("stage"),
                    "page_url": result.get("page_url"),
                    "ok": result.get("ok"),
                    "runtime": runtime_name,
                })
            return result
        except asyncio.CancelledError:
            self._cancel_active_browser_agent_command(task_id, job_id, state_name)
            raise
        except asyncio.TimeoutError as exc:
            self._cancel_active_browser_agent_command(task_id, job_id, state_name)
            detail = self._workflow_action_timeout_detail(state_name)
            self.workflow_runtime_unhealthy_reason = detail
            if should_log_browser_action:
                self.repo.add_log(task_id, job_id, "error", f"真实浏览器动作超时：{label}", {
                    "state": state_name.value,
                    "timeout_seconds": self.workflow_action_timeout_seconds,
                    "detail": detail,
                    "runtime": runtime_name,
                })
            raise V1ExecutionError(
                "E901",
                "真实浏览器操作超时",
                detail,
            ) from exc
        except V1ExecutionError as exc:
            if should_log_browser_action:
                self.repo.add_log(task_id, job_id, "error", f"真实浏览器动作失败：{label}", {
                    "state": state_name.value,
                    "error_code": exc.error_code,
                    "detail": exc.detail,
                    "runtime": runtime_name,
                })
            raise

    def _cancel_active_browser_agent_command(
        self,
        task_id: int,
        job_id: int,
        state_name: StateName,
    ) -> dict[str, Any] | None:
        command = self._active_browser_agent_commands.get((task_id, job_id, state_name.value))
        return self._cancel_browser_agent_command(command)

    def _require_persistent_browser_agent_ready(self) -> dict[str, Any]:
        runtime = self.browser_agent_runtime
        if runtime is None:
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器未配置",
                "真实店小秘流程必须使用持久在线真实浏览器，但当前运行时缺失；系统已停止任务，不会保存或发布。",
            )
        status_getter = getattr(runtime, "status", None)
        if not callable(status_getter):
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器状态不可用",
                "无法读取持久在线真实浏览器的健康状态；系统已停止任务，不会保存或发布。",
            )
        try:
            status = status_getter()
        except Exception as exc:
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器状态不可用",
                f"读取持久在线真实浏览器状态失败：{exc}；系统已停止任务，不会保存或发布。",
            ) from exc
        if not isinstance(status, Mapping):
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器状态无效",
                "持久在线真实浏览器返回了无效状态；系统已停止任务，不会保存或发布。",
            )
        status_runtime_id = str(status.get("runtimeId") or "").strip()
        bound_runtime_id = str(getattr(runtime, "runtime_id", "") or "").strip()
        if not status_runtime_id or not bound_runtime_id or status_runtime_id != bound_runtime_id:
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器绑定失效",
                "持久在线真实浏览器的 runtime binding 不匹配；系统已停止任务，不会保存或发布。",
            )
        if (
            status.get("healthy") is not True
            or status.get("active") is True
            or str(status.get("status") or "") != "idle"
        ):
            raise V1ExecutionError(
                "E901",
                "持久在线真实浏览器不健康",
                "持久在线真实浏览器当前不健康或仍有命令未收口；系统已停止任务，不会保存或发布。",
            )
        return dict(status)

    def _workflow_action_timeout_detail(self, state_name: StateName) -> str:
        step_label = self._workflow_step_label(state_name)
        seconds = int(self.workflow_action_timeout_seconds)
        return (
            f"真实浏览器操作超时：当前步骤「{step_label}」超过 {seconds} 秒没有完成，"
            "系统已停止本次任务，不会保存或发布。请关闭旧的执行浏览器或后台进程，"
            "重新打开执行浏览器后再重试。"
        )

    def _browser_agent_timeout_detail(self, state_name: StateName) -> str:
        detail = self._workflow_action_timeout_detail(state_name)
        internal_step = self._browser_agent_internal_step()
        if internal_step and internal_step not in detail:
            detail = f"{detail} 最后停在：{internal_step}。"
        return detail

    def _browser_agent_internal_step(self) -> str | None:
        if self.browser_agent_runtime is None:
            return None
        try:
            status = self.browser_agent_runtime.status()
        except Exception:
            return None
        if not isinstance(status, dict):
            return None
        event = status.get("lastWorkflowEvent")
        if isinstance(event, dict):
            for key in ("human_step", "step", "label", "event"):
                value = str(event.get(key) or "").strip()
                if value:
                    return value
        value = str(status.get("currentStep") or "").strip()
        return value or None

    def _workflow_step_label(self, state_name: StateName) -> str:
        copy = HUD_STEP_COPY.get(state_name)
        return copy[0] if copy else state_name.value

    def _write_evidence(self, task_id: int, job_id: int, state_name: StateName) -> Path:
        path = SCREENSHOT_DIR / f"v1_task_{task_id}_job_{job_id}_{state_name.value}.txt"
        path.write_text(
            (
                f"state={state_name.value}\n"
                f"task_id={task_id}\n"
                f"job_id={job_id}\n"
                f"created_at={now_iso()}\n"
                "publish_state=unverified\n"
            ),
            encoding="utf-8",
        )
        return path

    def _build_summary(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        filled_fields: list[str],
        empty_fields: list[str],
        evidence_paths: list[str],
        workflow_results: list[dict[str, Any]],
        execution_defaults: Mapping[str, Any] | None = None,
        blocked_reason: str | None = None,
        agent_console_events: list[dict[str, Any]] | None = None,
        agent_action_events: list[dict[str, Any]] | None = None,
        live_browser_hud_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        console_events = agent_console_events or []
        action_events = agent_action_events or []
        live_hud_events = live_browser_hud_events or []
        return {
            "task_id": task["id"],
            "job_id": job["id"],
            "product_id": job.get("product_id"),
            "store_name": self._store_name(task),
            "source_title": self._source_title(job.get("product_id")),
            "category": self._summary_category(task, job, execution_defaults),
            "mode": mode,
            "product_box_snapshot_fingerprint": (
                (task.get("payload") or {}).get("product_box_snapshot_fingerprint")
                if isinstance(task.get("payload"), Mapping)
                else None
            ),
            "status": "failed" if blocked_reason else "success",
            "blocked_reason": blocked_reason,
            "empty_fields": empty_fields,
            "filled_fields": filled_fields,
            "evidence_paths": evidence_paths,
            "template_trace": list((execution_defaults or {}).get("_template_trace") or []),
            "dxm_reference_templates_resolved": dict((execution_defaults or {}).get("dxm_reference_templates_resolved") or {}),
            "dxm_reference_template_results": self._workflow_reference_template_results(workflow_results),
            "resolved_defaults": self._redacted_defaults(execution_defaults or {}),
            "workflow_actions": [result.get("action") for result in workflow_results],
            "workflow_results": workflow_results,
            "agent_console_events": console_events,
            "agent_console": console_events[-1] if console_events else None,
            "agent_action_events": action_events,
            "live_browser_hud_events": live_hud_events,
            "live_browser_hud": live_hud_events[-1] if live_hud_events else None,
            # A failure can occur after a real mutation was dispatched.  Do not
            # turn missing terminal evidence into a fabricated non-publish fact.
            "published": None,
        }

    def _workflow_reference_template_results(self, workflow_results: list[dict[str, Any]]) -> dict[str, Any]:
        for result in workflow_results:
            reference_results = result.get("dxm_reference_template_results")
            if isinstance(reference_results, Mapping):
                return dict(reference_results)
            fill_result = result.get("fill_result")
            if isinstance(fill_result, Mapping) and isinstance(fill_result.get("dxm_reference_template_results"), Mapping):
                return dict(fill_result["dxm_reference_template_results"])
        return {}

    def _summary_category(
        self,
        task: Mapping[str, Any],
        job: Mapping[str, Any],
        execution_defaults: Mapping[str, Any] | None = None,
    ) -> str:
        product = self._product(job.get("product_id"))
        product_payload = (product or {}).get("payload") or {}
        task_payload = task.get("payload") or {}
        category_defaults = (execution_defaults or {}).get("category")
        if isinstance(category_defaults, Mapping):
            configured = category_defaults.get("category_match") or category_defaults.get("category_name")
            if configured:
                return str(configured)
        return str(
            (product or {}).get("category_name")
            or product_payload.get("category_name")
            or task_payload.get("category_name")
            or "未配置类目"
        )

    def _redacted_defaults(self, defaults: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in defaults.items()
            if not str(key).startswith("_")
        }

    def _save_result_for_mode(
        self,
        mode: str,
        workflow_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if mode in {"probe", "dry_run"}:
            return {
                "ok": True,
                "mode": mode,
                "message": "当前模式未执行保存动作",
                "published": None,
                "save_attempted": False,
                "publish_attempted": False,
            }
        raw_save_result = next((self._extract_save_result(result) for result in reversed(workflow_results) if result.get("action") == "save_only"), None)
        if not isinstance(raw_save_result, Mapping):
            raise V1ExecutionError("E999", "缺少保存证据", "save_only save_result missing")
        save_result = dict(raw_save_result)
        if save_result.get("ok") is not True:
            raise V1ExecutionError(
                "E999",
                "保存结果未确认成功",
                "save_only save_result must explicitly report ok=true",
            )
        if save_result.get("published") is not False:
            raise V1ExecutionError(
                "E999",
                "未发布结果不可信",
                "save_only save_result must explicitly report published=false",
            )
        return save_result

    def _extract_save_result(self, workflow_result: dict[str, Any]) -> dict[str, Any] | None:
        save_result = workflow_result.get("save_result")
        if isinstance(save_result, Mapping):
            return save_result
        evidence = workflow_result.get("evidence")
        if not isinstance(evidence, Mapping):
            return None
        nested = evidence.get("save_result")
        if isinstance(nested, Mapping):
            return dict(nested)
        observations = evidence.get("observations")
        nested = observations.get("save_result") if isinstance(observations, Mapping) else None
        return dict(nested) if isinstance(nested, Mapping) else None

    def _store_name(self, task: dict[str, Any]) -> str:
        try:
            _store_id, authoritative_name = self._authoritative_store(task)
        except V1ExecutionError:
            authoritative_name = ""
        if authoritative_name:
            return authoritative_name
        payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        configured = str(
            payload.get("store_name")
            or task.get("store_name")
            or payload.get("store")
            or task.get("store")
            or ""
        ).strip()
        return configured

    def _authoritative_store(self, task: Mapping[str, Any]) -> tuple[int, str]:
        try:
            store_id = int(task.get("store_id"))
        except (TypeError, ValueError) as exc:
            raise V1ExecutionError("E202", "任务店铺绑定无效", "task store_id is invalid") from exc
        if store_id <= 0:
            raise V1ExecutionError("E202", "任务店铺绑定无效", "task store_id is invalid")
        store = next(
            (
                item
                for item in self.repo.list_stores()
                if not isinstance(item.get("id"), bool) and int(item.get("id") or 0) == store_id
            ),
            None,
        )
        store_name = str((store or {}).get("name") or "").strip()
        if not store_name:
            raise V1ExecutionError("E202", "任务店铺不存在", "task store_id has no authoritative store row")
        return store_id, store_name

    def _execution_defaults(
        self,
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return self.defaults_resolver.resolve(self.repo.list_templates(), task, product).defaults

    def _template_applies_to(
        self,
        template: Mapping[str, Any],
        task: Mapping[str, Any],
        product: Mapping[str, Any] | None,
    ) -> bool:
        payload = template.get("payload") or {}
        if not isinstance(payload, Mapping):
            return True
        binding = (
            payload.get("binding")
            or payload.get("applies_to")
            or payload.get("match")
        )
        if not isinstance(binding, Mapping):
            return True

        task_payload = task.get("payload") or {}
        product_payload = (product or {}).get("payload") or {}
        actual_store = self._store_name(dict(task))
        actual_category = (
            (product or {}).get("category_name")
            or product_payload.get("category_name")
            or task_payload.get("category_name")
            or task_payload.get("category")
        )
        actual_platform = (
            task_payload.get("platform")
            or task.get("platform")
            or "AliExpress"
        )
        return (
            self._matches_binding(binding, ("store_name", "store", "stores", "store_names"), actual_store)
            and self._matches_binding(binding, ("category_name", "category", "categories", "category_names"), actual_category)
            and self._matches_binding(binding, ("platform", "platforms"), actual_platform)
        )

    def _matches_binding(self, binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> bool:
        expected = next((binding.get(key) for key in keys if key in binding), None)
        if expected is None or expected == "":
            return True
        actual_text = str(actual or "").strip().lower()
        if isinstance(expected, (list, tuple, set)):
            values = expected
        else:
            values = [expected]
        normalized = [str(value or "").strip().lower() for value in values]
        return "*" in normalized or "all" in normalized or actual_text in normalized

    def _merge_template_payload(self, target: dict[str, Any], template_type: str, payload: Mapping[str, Any]) -> None:
        self._merge_payload(target, payload)
        grouped_payload = payload.get(template_type)
        if isinstance(grouped_payload, Mapping):
            self._deep_merge(target.setdefault(template_type, {}), grouped_payload)
            return
        flat_group_payload = {
            key: value
            for key, value in payload.items()
            if key not in DEFAULT_TEMPLATE_TYPES and key != "template_overrides"
        }
        if flat_group_payload:
            self._deep_merge(target.setdefault(template_type, {}), flat_group_payload)

    def _merge_payload(
        self,
        target: dict[str, Any],
        payload: Mapping[str, Any],
        skip_keys: set[str] | None = None,
    ) -> None:
        skip_keys = skip_keys or set()
        for key, value in payload.items():
            if key in skip_keys:
                continue
            normalized = self._normalize_template_type(key)
            target_key = normalized if normalized in DEFAULT_TEMPLATE_TYPES else key
            if isinstance(value, Mapping) and isinstance(target.get(target_key), dict):
                self._deep_merge(target[target_key], value)
            elif isinstance(value, Mapping):
                target[target_key] = dict(value)
            else:
                target[target_key] = value

    def _deep_merge(self, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
            elif isinstance(value, Mapping):
                target[key] = dict(value)
            else:
                target[key] = value

    def _normalize_template_type(self, value: Any) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _source_title(self, product_id: int | None) -> str:
        if product_id is None:
            return "未指定商品"
        product = self._product(product_id)
        if product:
            payload = product.get("payload") or {}
            return payload.get("source_title") or product.get("title") or f"任务商品 #{product_id}"
        return f"任务商品 #{product_id}"

    def _source_urls(self, product_id: int | None) -> list[str]:
        product = self._product(product_id)
        payload = (product or {}).get("payload") or {}
        return self._payload_source_urls(payload)

    def _target_source_urls(self, task: Mapping[str, Any], job: Mapping[str, Any]) -> list[str]:
        product_urls = self._source_urls(job.get("product_id"))
        if product_urls:
            return product_urls
        payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
        return self._payload_source_urls(payload)

    def _unique_source_urls(self, *values: Any) -> list[str]:
        urls: list[str] = []
        for value in values:
            if isinstance(value, str):
                candidates = [value]
            elif isinstance(value, (list, tuple, set)):
                candidates = list(value)
            else:
                candidates = []
            for candidate in candidates:
                text = str(candidate or '').strip()
                if text and text not in urls:
                    urls.append(text)
        return urls

    def _payload_source_urls(self, payload: Mapping[str, Any] | dict[str, Any]) -> list[str]:
        values: list[Any] = []
        if isinstance(payload, Mapping):
            values.extend([payload.get("source_url"), payload.get("url")])
            source_urls = payload.get("source_urls")
            if isinstance(source_urls, (list, tuple)):
                values.extend(source_urls)
        urls: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in urls:
                urls.append(text)
        return urls

    def _product(self, product_id: int | None) -> dict[str, Any] | None:
        if product_id is None:
            return None
        for product in self.repo.list_products():
            if product.get("id") == product_id:
                return product
        return None

class _JobTerminalTransitionRejected(Exception):
    def __init__(self, conflict_code: str | None, reason: str | None) -> None:
        super().__init__(reason or conflict_code or "job terminal transition rejected")
        self.conflict_code = conflict_code
        self.reason = reason


class V1ExecutionError(Exception):
    def __init__(self, error_code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.title = title
        self.detail = detail
