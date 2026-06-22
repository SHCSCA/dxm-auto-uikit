from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.core.config import SCREENSHOT_DIR
from src.execution.dxm_live import DxmLiveClient
from src.repository import Repository
from src.services.config_defaults import DEFAULT_TEMPLATE_TYPES, ConfigDefaultsResolver
from src.services.config_validation import ConfigValidationService
from src.services.ownership_lock import OwnershipLockService
from src.services.publish_guard import PublishGuardService
from src.state_machine.contracts import StateName, normalize_execution_mode
from src.utils import now_iso


V1_STEPS = [
    (StateName.PRECHECK_CONFIG, "启动前配置校验", "config"),
    (StateName.PRECHECK_SESSION, "检查店小秘登录态", "session"),
    (StateName.PRECHECK_PUBLISH_GUARD, "发布隔离预检", "publish_guard"),
    (StateName.OPEN_DRAFT_LIST, "进入速卖通采集箱", "navigation"),
    (StateName.FIND_PRODUCT, "定位目标商品", "ownership"),
    (StateName.ITEM_LOCKING, "创建商品归属锁", "ownership"),
    (StateName.CLAIM_PRODUCT, "写入领取备注", "ownership"),
    (StateName.VERIFY_LIST_OWNERSHIP, "校验采集箱归属", "ownership"),
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

MODE_LAST_STATE = {
    "probe": StateName.PRECHECK_PUBLISH_GUARD,
    "dry_run": StateName.PRECHECK_CONFIG,
    "claim_only": StateName.VERIFY_LIST_OWNERSHIP,
    "single_save": StateName.RELEASE_LOCK,
    "batch_save": StateName.RELEASE_LOCK,
}

HUD_PROGRESS_TOTAL = 10

HUD_PROGRESS_INDEX = {
    StateName.PRECHECK_CONFIG: 1,
    StateName.PRECHECK_SESSION: 1,
    StateName.PRECHECK_PUBLISH_GUARD: 1,
    StateName.OPEN_DRAFT_LIST: 2,
    StateName.FIND_PRODUCT: 3,
    StateName.ITEM_LOCKING: 3,
    StateName.CLAIM_PRODUCT: 3,
    StateName.VERIFY_LIST_OWNERSHIP: 3,
    StateName.OPEN_EDIT_PAGE: 4,
    StateName.VERIFY_EDIT_OWNERSHIP: 4,
    StateName.FILL_BASE_INFO: 4,
    StateName.FILL_VARIANTS: 6,
    StateName.FILL_MEDIA: 7,
    StateName.FILL_COMPLIANCE: 8,
    StateName.ENABLE_SEMI_MANAGED: 8,
    StateName.OPEN_SEMI_MANAGED_PAGE: 8,
    StateName.FILL_SEMI_GOODS: 8,
    StateName.FILL_SEMI_VARIANTS: 8,
    StateName.PRE_SAVE_GUARD_CHECK: 8,
    StateName.SAVE_ONLY: 9,
    StateName.VERIFY_SAVE_RESULT: 9,
    StateName.VERIFY_NOT_PUBLISHED: 10,
    StateName.WRITE_REPORT: 10,
    StateName.RELEASE_LOCK: 10,
}

HUD_STEP_COPY = {
    StateName.PRECHECK_CONFIG: ("开始任务", "开始任务", "正在检查任务、店铺登录和只保存边界"),
    StateName.PRECHECK_SESSION: ("开始任务", "开始任务", "正在确认店小秘已经登录"),
    StateName.PRECHECK_PUBLISH_GUARD: ("开始任务", "开始任务", "正在确认本次只保存，不发布"),
    StateName.OPEN_DRAFT_LIST: ("打开草稿箱", "打开草稿箱", "正在打开店小秘草稿箱"),
    StateName.FIND_PRODUCT: ("查找商品", "查找商品", "正在查找本次要保存的商品"),
    StateName.ITEM_LOCKING: ("查找商品", "查找商品", "正在锁定本次商品，避免误操作其他商品"),
    StateName.CLAIM_PRODUCT: ("查找商品", "查找商品", "正在标记本次任务商品"),
    StateName.VERIFY_LIST_OWNERSHIP: ("查找商品", "查找商品", "正在确认只处理本次商品"),
    StateName.OPEN_EDIT_PAGE: ("输入标题", "输入标题", "正在打开编辑页，准备填写标题"),
    StateName.VERIFY_EDIT_OWNERSHIP: ("输入标题", "输入标题", "正在确认编辑页商品匹配"),
    StateName.FILL_BASE_INFO: ("输入标题", "输入标题", "正在输入标题并选择分类"),
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
    StateName.WRITE_REPORT: ("确认未发布", "确认未发布", "正在记录保存结果和未发布证明"),
    StateName.RELEASE_LOCK: ("确认未发布", "确认未发布", "正在完成收尾，保持只保存状态"),
}

HUD_NEXT_OVERRIDE = {
    StateName.FILL_BASE_INFO: "选择分类",
}

HUD_VIRTUAL_STAGE_AFTER = {
    StateName.FILL_BASE_INFO: {
        "step_code": "SELECT_CATEGORY",
        "step_name": "选择分类",
        "phase": "选择分类",
        "progress_index": 5,
        "human_title": "选择分类",
        "human_action": "正在确认商品分类已选择",
        "human_next": "填写价格库存",
        "next_step": "填写价格库存",
    },
}

class V1TaskRunner:
    def __init__(
        self,
        repo: Repository,
        manager,
        workflow_adapter: Any | None = None,
        agent_console: Any | None = None,
        workflow_executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.repo = repo
        self.manager = manager
        self.workflow_adapter = workflow_adapter
        self.agent_console = agent_console
        self._workflow_executor = workflow_executor or (ThreadPoolExecutor(max_workers=1) if workflow_adapter is not None else None)
        self.live = DxmLiveClient()
        self.publish_guard = PublishGuardService()
        self.config_validation = ConfigValidationService()
        self.defaults_resolver = ConfigDefaultsResolver()
        self.ownership_lock = OwnershipLockService()

    async def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
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
                    "改为 probe、dry_run、claim_only、single_save 或 batch_save。",
                )
            await self.manager.broadcast(task_id, {"type": "task_status", "status": "failed", "taskId": task_id})
            return
        self.repo.update_task_status(task_id, "running")
        await self.manager.broadcast(task_id, {"type": "task_status", "status": "running", "taskId": task_id, "mode": mode})

        completed = 0
        failed = 0
        for job in task["jobs"]:
            success = await self._run_job(task, job, mode)
            if success:
                completed += 1
            else:
                failed += 1
            self.repo.update_task_status(task_id, "running", completed_jobs=completed, failed_jobs=failed)
            await self.manager.broadcast(task_id, {
                "type": "job_completed",
                "taskId": task_id,
                "jobId": job["id"],
                "completedJobs": completed,
                "failedJobs": failed,
            })

        final_status = "completed" if failed == 0 else ("partial_success" if completed else "failed")
        self.repo.update_task_status(task_id, final_status, completed_jobs=completed, failed_jobs=failed)
        await self.manager.broadcast(task_id, {
            "type": "task_status",
            "taskId": task_id,
            "status": final_status,
            "completedJobs": completed,
            "failedJobs": failed,
        })

    async def _run_job(self, task: dict[str, Any], job: dict[str, Any], mode: str) -> bool:
        task_id = task["id"]
        job_id = job["id"]
        product_id = job.get("product_id")
        product = self._product(product_id)
        execution_defaults = self._execution_defaults(task, product)
        lock_token: str | None = None
        claim_mark = self._claim_mark(task)
        filled_fields: list[str] = []
        empty_fields: list[str] = []
        evidence_paths: list[str] = []
        workflow_results: list[dict[str, Any]] = []
        agent_console_events: list[dict[str, Any]] = []
        agent_action_events: list[dict[str, Any]] = []
        live_browser_hud_events: list[dict[str, Any]] = []
        last_state = MODE_LAST_STATE[mode]

        self.repo.update_job(job_id, status="running", current_step_code="PRECHECK_CONFIG", current_step_name="启动前配置校验")
        self.repo.add_log(task_id, job_id, "info", "V1 执行开始", {"mode": mode, "product_id": product_id})

        try:
            if self.workflow_adapter is None and mode in {"claim_only", "single_save", "batch_save"}:
                raise V1ExecutionError("E901", "缺少真实工作流适配器", f"{mode} requires workflow_adapter")

            for state_name, step_name, field_domain in self._steps_for_mode(mode):
                self._guard_step(task, job, state_name, claim_mark, product)
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
                        claim_mark_base=task.get("payload", {}).get("claim_mark", "AI认领"),
                    )
                    if lock["conflict"]:
                        raise V1ExecutionError("E202", "商品归属锁冲突", lock["reason"])
                    lock_token = lock["lock_token"]
                    claim_mark = lock["claim_mark"]

                if state_name == StateName.VERIFY_LIST_OWNERSHIP and lock_token:
                    verified = self.ownership_lock.mark_page_claim_verified(lock_token, claim_mark)
                    if verified["conflict"]:
                        raise V1ExecutionError("E202", "页面领取标记不一致", verified["reason"])

                workflow_result = await self._run_workflow_action_async(task, job, state_name, claim_mark, execution_defaults)
                if workflow_result:
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
                    if agent_action_event:
                        workflow_meta["agent_action"] = agent_action_event
                    self.repo.add_evidence(task_id, job_id, "workflow_action", workflow_result.get("screenshot_url"), workflow_meta)

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

            if mode in {"probe", "dry_run", "claim_only"}:
                empty_fields.append("未进入商品保存字段，当前模式不需要填写")
            if mode in {"single_save", "batch_save"}:
                empty_fields.append("货品条码：配置允许留空")

            summary = self._build_summary(
                task,
                job,
                mode,
                claim_mark,
                filled_fields,
                empty_fields,
                evidence_paths,
                workflow_results,
                execution_defaults,
                agent_console_events=agent_console_events,
                agent_action_events=agent_action_events,
                live_browser_hud_events=live_browser_hud_events,
            )
            save_result = self._save_result_for_mode(mode, workflow_results)
            self.repo.add_report(task_id, job_id, product_id, "success", False, save_result, summary)
            self.repo.update_job(
                job_id,
                status="succeeded",
                current_step_code="DONE",
                current_step_name="V1 执行完成",
                error_code=None,
                error_message=None,
            )
            self.repo.add_log(task_id, job_id, "success", "V1 商品流程完成", {"mode": mode, "published": False})
            return True
        except Exception as exc:
            if lock_token:
                self.ownership_lock.release_lock(lock_token)
            error = exc if isinstance(exc, V1ExecutionError) else V1ExecutionError("E999", "V1 执行失败", str(exc))
            self.repo.update_job(
                job_id,
                status="failed",
                current_step_code="FAILED",
                current_step_name="执行失败",
                error_code=error.error_code,
                error_message=error.detail,
            )
            self.repo.add_exception(
                task_id,
                job_id,
                error.error_code,
                "v1_executor",
                error.title,
                error.detail,
                "检查配置、页面状态和证据后重试；禁止忽略发布或归属风险继续执行。",
            )
            self.repo.add_report(
                task_id,
                job_id,
                product_id,
                "failed",
                False,
                {"ok": False, "error_code": error.error_code, "message": error.detail},
                self._build_summary(
                    task,
                    job,
                    mode,
                    claim_mark,
                    filled_fields,
                    empty_fields,
                    evidence_paths,
                    workflow_results,
                    execution_defaults,
                    blocked_reason=error.detail,
                    agent_console_events=agent_console_events,
                    agent_action_events=agent_action_events,
                    live_browser_hud_events=live_browser_hud_events,
                ),
            )
            self.repo.add_log(task_id, job_id, "error", error.title, {"error_code": error.error_code, "detail": error.detail})
            return False

    def _steps_for_mode(self, mode: str):
        if mode == "dry_run":
            return [V1_STEPS[0]]
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
            if self._workflow_executor is not None:
                result = self._workflow_executor.submit(updater, payload).result(timeout=8)
            else:
                result = updater(payload)
        except FutureTimeoutError:
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
        return {
            "task_id": task["id"],
            "job_id": job["id"],
            "product_id": job.get("product_id"),
            "step_code": resolved_step_code,
            "step_name": resolved_step_name,
            "field_domain": field_domain,
            "mode": mode,
            "store_name": self._store_name(task),
            "next_step": override.get("next_step") or self._next_step_name(mode, state_name),
            "screenshot_path": screenshot_path,
            "guard": "只保存不发布",
            "phase": override.get("phase") or self._hud_phase(state_name),
            "progress_index": override.get("progress_index") or self._progress_index(mode, state_name),
            "progress_total": self._progress_total(mode),
            "severity": "info",
            "human_title": override.get("human_title") or self._human_title(state_name, step_name),
            "human_action": override.get("human_action") or self._human_action(state_name, field_domain, mode),
            "human_next": override.get("human_next") or self._human_next(mode, state_name),
            "requires_user_action": False,
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
        if action_name.startswith("fill_") or action_name == "claim_product":
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
        if action_name == "claim_product":
            return "领取备注"
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
        claim_mark: str,
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
        if state_name == StateName.CLAIM_PRODUCT and not claim_mark:
            raise V1ExecutionError("E202", "领取标记为空", "任务缺少 claim_mark")
        if state_name == StateName.SAVE_ONLY:
            result = self.publish_guard.check(intended_action="save", target_text="保存")
            if not result["allowed"]:
                raise V1ExecutionError("E999", "保存动作被发布隔离器阻断", "; ".join(result["reasons"]))

    def _run_workflow_action(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        claim_mark: str,
        defaults: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.workflow_adapter is None:
            return None

        product_query = self._source_title(job.get("product_id"))
        target_source_urls = self._source_urls(job.get("product_id"))
        store_name = self._store_name(task)
        actions = {
            StateName.PRECHECK_SESSION: ("check_login_state", "E101", "店小秘登录态检查失败", lambda: self.workflow_adapter.check_login_state()),
            StateName.OPEN_DRAFT_LIST: ("open_draft_box", "E201", "进入采集箱失败", lambda: self.workflow_adapter.open_draft_box()),
            StateName.CLAIM_PRODUCT: (
                "claim_product",
                "E202",
                "写入领取备注失败",
                lambda: self.workflow_adapter.claim_product(
                    claim_mark,
                    product_query=product_query,
                    store_name=store_name,
                    target_source_urls=target_source_urls,
                ),
            ),
            StateName.OPEN_EDIT_PAGE: (
                "open_editor",
                "E901",
                "打开编辑页失败",
                lambda: self.workflow_adapter.open_editor(
                    product_query=product_query,
                    store_name=store_name,
                    note_text=claim_mark,
                ),
            ),
            StateName.VERIFY_EDIT_OWNERSHIP: (
                "verify_edit_ownership",
                "E202",
                "编辑页归属校验失败",
                lambda: self.workflow_adapter.verify_edit_ownership(
                    product_query=product_query,
                    store_name=store_name,
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
                ),
            ),
            StateName.ENABLE_SEMI_MANAGED: (
                "enable_semi_managed",
                "E901",
                "勾选半托管服务失败",
                lambda: self.workflow_adapter.enable_semi_managed(
                    product_query=product_query,
                    store_name=store_name,
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
                ),
            ),
            StateName.VERIFY_NOT_PUBLISHED: (
                "verify_not_published",
                "E999",
                "未发布状态校验失败",
                lambda: self.workflow_adapter.verify_not_published(
                    product_query=product_query,
                    store_name=store_name,
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
        try:
            result = call()
        except Exception as exc:
            raise V1ExecutionError(error_code, error_title, f"{action_name}: {exc}") from exc

        if not result.get("ok"):
            raise V1ExecutionError(error_code, error_title, self._workflow_failure_detail(action_name, result))
        if state_name == StateName.CLAIM_PRODUCT and result.get("evidence", {}).get("note_verified") is False:
            raise V1ExecutionError(error_code, error_title, f"{action_name} note_verified false")
        if state_name == StateName.SAVE_ONLY:
            save_result = self._extract_save_result(result)
            if not save_result or save_result.get("ok") is not True:
                raise V1ExecutionError(error_code, error_title, f"{action_name} save_result missing or false")
        return result

    def _workflow_failure_detail(self, action_name: str, result: Mapping[str, Any]) -> str:
        stage = result.get("stage") or "unknown_stage"
        page_url = result.get("page_url") or "unknown_url"
        parts = [f"{action_name} failed at {stage}: {page_url}"]

        for value in (result.get("message"), result.get("reason"), result.get("error")):
            if value:
                parts.append(str(value))

        evidence = result.get("evidence") if isinstance(result.get("evidence"), Mapping) else {}
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

    async def _run_workflow_action_async(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        state_name: StateName,
        claim_mark: str,
        defaults: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.workflow_adapter is None:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._workflow_executor,
            self._run_workflow_action,
            task,
            job,
            state_name,
            claim_mark,
            defaults,
        )

    def _noop_workflow_result(self, action_name: str, product_query: str, store_name: str) -> dict[str, Any]:
        return {
            "ok": True,
            "action": action_name,
            "stage": "noop_adapter_action",
            "page_title": None,
            "page_url": None,
            "screenshot_url": None,
            "product_query": product_query,
            "store_name": store_name,
            "evidence": {
                "action": action_name,
                "noop": True,
                "reason": "workflow_adapter method not available",
                "product_query": product_query,
                "store_name": store_name,
            },
        }

    def _write_evidence(self, task_id: int, job_id: int, state_name: StateName) -> Path:
        path = SCREENSHOT_DIR / f"v1_task_{task_id}_job_{job_id}_{state_name.value}.txt"
        path.write_text(
            f"state={state_name.value}\ntask_id={task_id}\njob_id={job_id}\ncreated_at={now_iso()}\npublished=false\n",
            encoding="utf-8",
        )
        return path

    def _build_summary(
        self,
        task: dict[str, Any],
        job: dict[str, Any],
        mode: str,
        claim_mark: str,
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
            "claim_mark": claim_mark,
            "mode": mode,
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
            "published": False,
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

    def _save_result_for_mode(self, mode: str, workflow_results: list[dict[str, Any]]) -> dict[str, Any]:
        if mode in {"probe", "dry_run", "claim_only"}:
            return {"ok": True, "mode": mode, "message": "当前模式未执行保存动作", "published": False}
        save_result = next((self._extract_save_result(result) for result in reversed(workflow_results) if result.get("action") == "save_only"), None)
        if not save_result:
            raise V1ExecutionError("E999", "缺少保存证据", "save_only save_result missing")
        save_result["published"] = False
        return save_result

    def _extract_save_result(self, workflow_result: dict[str, Any]) -> dict[str, Any] | None:
        save_result = workflow_result.get("save_result")
        if save_result:
            return save_result
        evidence = workflow_result.get("evidence") or {}
        return evidence.get("save_result")

    def _store_name(self, task: dict[str, Any]) -> str:
        return task.get("payload", {}).get("store_name") or "Dang Kang"

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
        values: list[Any] = []
        if isinstance(payload, Mapping):
            values.extend([payload.get("source_url"), payload.get("url")])
            source_urls = payload.get("source_urls")
            if isinstance(source_urls, (list, tuple)):
                values.extend(source_urls)
        return [str(value).strip() for value in values if str(value or "").strip()]

    def _product(self, product_id: int | None) -> dict[str, Any] | None:
        if product_id is None:
            return None
        for product in self.repo.list_products():
            if product.get("id") == product_id:
                return product
        return None

    def _claim_mark(self, task: dict[str, Any]) -> str:
        base_mark = task.get("payload", {}).get("claim_mark", "AI认领")
        return f"{base_mark}-{task['id']}"


class V1ExecutionError(Exception):
    def __init__(self, error_code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.title = title
        self.detail = detail
