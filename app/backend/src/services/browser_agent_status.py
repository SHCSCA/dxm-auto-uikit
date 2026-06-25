from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


RUNNING_STATUSES = {"running", "started", "in_progress", "info", "ok"}
ERROR_STATUSES = {"failed", "error", "blocked"}
USER_ACTION_STATES = {"WAITING_CAPTCHA", "MANUAL_APPROVAL_REQUIRED", "MANUAL_TAKEOVER"}

STEP_COPY: dict[str, dict[str, Any]] = {
    "PRECHECK_CONFIG": {
        "phase": "准备执行",
        "title": "开始任务",
        "line1": "检查任务、店铺登录和只保存边界",
        "next": "打开真实浏览器",
        "progress_index": 1,
    },
    "PRECHECK_SESSION": {
        "phase": "准备执行",
        "title": "开始任务",
        "line1": "确认店小秘已经登录",
        "next": "确认只保存边界",
        "progress_index": 1,
    },
    "PRECHECK_PUBLISH_GUARD": {
        "phase": "准备执行",
        "title": "开始任务",
        "line1": "确认本次只保存，不发布",
        "next": "打开业务页面",
        "progress_index": 1,
    },
    "OPEN_DATA_ACQUISITION": {
        "phase": "第一段：数据采集认领",
        "title": "正在打开数据采集",
        "line1": "进入店小秘数据采集页",
        "next": "把当前商品认领到采集箱",
        "progress_index": 2,
    },
    "CLAIM_TO_DRAFT_BOX": {
        "phase": "第一段：数据采集认领",
        "title": "正在认领商品",
        "line1": "把当前商品认领到采集箱",
        "next": "检查商品是否已进入采集箱",
        "progress_index": 3,
    },
    "VERIFY_DRAFT_BOX_CLAIM": {
        "phase": "第一段：数据采集认领",
        "title": "正在确认采集箱",
        "line1": "检查商品是否已进入采集箱",
        "next": "选择该采集箱商品继续编辑保存",
        "progress_index": 3,
    },
    "OPEN_DRAFT_LIST": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在打开采集箱",
        "line1": "进入店小秘采集箱",
        "next": "定位本次商品",
        "progress_index": 2,
    },
    "FIND_PRODUCT": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在定位商品",
        "line1": "查找本次要编辑保存的商品",
        "next": "打开商品编辑页",
        "progress_index": 3,
    },
    "ITEM_LOCKING": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在锁定商品",
        "line1": "确认本次只处理当前商品",
        "next": "打开商品编辑页",
        "progress_index": 3,
    },
    "CLAIM_PRODUCT": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在标记商品",
        "line1": "写入本次任务识别标记",
        "next": "确认商品匹配",
        "progress_index": 3,
    },
    "VERIFY_LIST_OWNERSHIP": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在确认商品",
        "line1": "确认采集箱里的商品就是本次任务商品",
        "next": "打开商品编辑页",
        "progress_index": 3,
    },
    "OPEN_EDIT_PAGE": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在打开编辑页",
        "line1": "进入采集箱商品编辑页",
        "next": "填写标题和基础信息",
        "progress_index": 4,
    },
    "VERIFY_EDIT_OWNERSHIP": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在确认编辑页",
        "line1": "确认当前编辑页属于本次商品",
        "next": "填写标题和基础信息",
        "progress_index": 4,
    },
    "FILL_BASE_INFO": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在编辑商品",
        "line1": "正在填写标题",
        "next": "继续填写价格、图片和物流信息",
        "progress_index": 5,
    },
    "SELECT_CATEGORY": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在选择分类",
        "line1": "确认商品分类和属性",
        "next": "填写价格库存",
        "progress_index": 6,
    },
    "FILL_VARIANTS": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在编辑商品",
        "line1": "正在填写价格、库存和 SKU",
        "next": "处理图片素材",
        "progress_index": 7,
    },
    "FILL_MEDIA": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在编辑商品",
        "line1": "正在处理图片",
        "next": "填写包装、物流和合规信息",
        "progress_index": 8,
    },
    "FILL_COMPLIANCE": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在完善资料",
        "line1": "正在填写合规和海关信息",
        "next": "设置半托管信息",
        "progress_index": 9,
    },
    "ENABLE_SEMI_MANAGED": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在设置半托管",
        "line1": "选择半托管服务，不触碰发布入口",
        "next": "填写包装物流信息",
        "progress_index": 9,
    },
    "OPEN_SEMI_MANAGED_PAGE": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在设置半托管",
        "line1": "进入半托管编辑页",
        "next": "填写包装物流信息",
        "progress_index": 9,
    },
    "FILL_SEMI_GOODS": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在设置包装物流",
        "line1": "填写重量、尺寸和物流信息",
        "next": "填写半托管 SKU 信息",
        "progress_index": 9,
    },
    "FILL_SEMI_VARIANTS": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在设置包装物流",
        "line1": "填写半托管 SKU、价格和库存",
        "next": "保存前检查",
        "progress_index": 9,
    },
    "PRE_SAVE_GUARD_CHECK": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在保存前检查",
        "line1": "确认页面不会触发发布",
        "next": "只点击保存",
        "progress_index": 9,
    },
    "SAVE_ONLY": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在只保存",
        "line1": "只点击保存，不发布",
        "next": "确认商品没有发布",
        "progress_index": 10,
    },
    "VERIFY_SAVE_RESULT": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在确认保存",
        "line1": "读取店小秘保存成功提示",
        "next": "确认商品没有发布",
        "progress_index": 10,
    },
    "VERIFY_NOT_PUBLISHED": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在检查结果",
        "line1": "确认商品没有发布",
        "next": "查看保存结果和未发布证明",
        "progress_index": 11,
    },
    "WRITE_REPORT": {
        "phase": "第二段：采集箱编辑保存",
        "title": "正在生成结果",
        "line1": "记录保存结果和未发布证明",
        "next": "任务完成",
        "progress_index": 12,
    },
    "RELEASE_LOCK": {
        "phase": "第二段：采集箱编辑保存",
        "title": "任务完成",
        "line1": "保存完成并确认未发布",
        "next": "查看结果报告",
        "progress_index": 12,
    },
    "TASK_FAILED": {
        "phase": "需要人工处理",
        "title": "当前步骤失败",
        "line1": "请按页面提示处理后重试，真实保存不会继续",
        "next": "查看结果与问题",
        "progress_index": 12,
        "severity": "error",
    },
}

STEP_ALIASES = {
    "OPEN_EDITOR": "OPEN_EDIT_PAGE",
    "FILL_TITLE": "FILL_BASE_INFO",
    "FILL_IMAGES": "FILL_MEDIA",
}

USER_ACTION_COPY = {
    "WAITING_CAPTCHA": {
        "phase": "等待人工处理",
        "title": "需要你处理验证码",
        "line1": "请在真实店小秘浏览器里完成验证码或二次确认",
        "next": "完成后回到控制台检测登录状态",
        "severity": "warning",
    },
    "MANUAL_APPROVAL_REQUIRED": {
        "phase": "等待人工确认",
        "title": "需要你人工确认只保存",
        "line1": "请确认本次任务只保存、不发布",
        "next": "确认后才会启动真实浏览器保存",
        "severity": "warning",
    },
    "MANUAL_TAKEOVER": {
        "phase": "人工接管中",
        "title": "需要你接管真实浏览器",
        "line1": "请在真实浏览器里检查或修正当前页面",
        "next": "处理完成后在控制台交还 Agent",
        "severity": "warning",
    },
}


def build_browser_hud(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    raw_step = str(payload.get("step") or payload.get("step_code") or payload.get("state") or payload.get("code") or "WAITING").strip()
    step = STEP_ALIASES.get(raw_step.upper(), raw_step.upper())
    status = str(payload.get("status") or payload.get("severity") or "running").strip().lower()
    copy = USER_ACTION_COPY.get(step) or STEP_COPY.get(step)
    unknown = copy is None
    if copy is None:
        copy = {
            "phase": "需要处理",
            "title": "当前步骤需要处理",
            "line1": "请按控制台提示处理后重试",
            "next": "查看问题处理",
        }

    title = str(payload.get("title") or payload.get("human_title") or copy["title"])
    line1 = str(payload.get("line1") or payload.get("human_action") or copy["line1"])
    line2 = str(payload.get("line2") or _default_line2(payload))
    next_step = str(payload.get("next_step") or payload.get("human_next") or copy["next"])
    severity = str(payload.get("severity") or copy.get("severity") or _severity(status, unknown))
    requires_user_action = payload.get("requires_user_action")
    if requires_user_action is None:
        requires_user_action = bool(step in USER_ACTION_STATES or status in ERROR_STATUSES or unknown)

    return {
        "title": title,
        "line1": line1,
        "line2": line2,
        "state": step,
        "step_code": step,
        "phase": str(payload.get("phase") or copy["phase"]),
        "status": status,
        "severity": severity,
        "human_title": title,
        "human_action": line1,
        "human_next": next_step,
        "next_step": next_step,
        "store_name": str(payload.get("store_name") or "等待店铺"),
        "task_name": str(payload.get("task_name") or "DXM 自动化任务"),
        "guard": str(payload.get("guard") or "只保存不发布"),
        "progress_index": payload.get("progress_index") or copy.get("progress_index"),
        "progress_total": payload.get("progress_total") or 12,
        "requires_user_action": bool(requires_user_action),
        "maintenance_detail": _maintenance_detail(payload, include_step=bool(unknown or status in ERROR_STATUSES)),
        "updated_at": str(payload.get("updated_at") or _now()),
    }


def _severity(status: str, unknown: bool) -> str:
    if status in ERROR_STATUSES or unknown:
        return "error"
    if status in RUNNING_STATUSES:
        return "running"
    if status == "success":
        return "success"
    return "info"


def _default_line2(payload: Mapping[str, Any]) -> str:
    store_name = str(payload.get("store_name") or "").strip()
    if store_name:
        return f"店铺：{store_name}"
    task_name = str(payload.get("task_name") or "").strip()
    if task_name:
        return f"任务：{task_name}"
    return "真实浏览器会保持打开"


def _maintenance_detail(payload: Mapping[str, Any], *, include_step: bool = False) -> str | None:
    detail = str(payload.get("maintenance_detail") or payload.get("error") or "").strip()
    raw_step = str(payload.get("step") or payload.get("step_code") or payload.get("state") or payload.get("code") or "").strip()
    if detail and raw_step:
        return f"{raw_step}: {detail}"
    if detail:
        return detail
    return raw_step if include_step and raw_step else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
