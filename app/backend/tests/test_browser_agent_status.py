from __future__ import annotations

from src.services.browser_agent_status import build_browser_hud


def test_browser_agent_status_maps_acquisition_steps_to_chinese_hud():
    open_page = build_browser_hud({
        "task_name": "数据采集认领",
        "step": "OPEN_DATA_ACQUISITION",
        "status": "running",
        "store_name": "Dang Kang",
    })
    assert open_page["title"] == "正在打开数据采集"
    assert open_page["line1"] == "进入店小秘数据采集页"
    assert open_page["line2"] == "店铺：Dang Kang"
    assert open_page["phase"] == "第一段：数据采集认领"
    assert open_page["severity"] == "running"
    assert open_page["requires_user_action"] is False

    claim = build_browser_hud({
        "task_name": "数据采集认领",
        "step": "CLAIM_TO_DRAFT_BOX",
        "status": "running",
    })
    assert claim["title"] == "正在认领商品"
    assert claim["line1"] == "把当前商品认领到采集箱"
    assert claim["human_next"] == "检查商品是否已进入采集箱"

    verify = build_browser_hud({
        "task_name": "数据采集认领",
        "step": "VERIFY_DRAFT_BOX_CLAIM",
        "status": "running",
    })
    assert verify["title"] == "正在确认采集箱"
    assert verify["line1"] == "检查商品是否已进入采集箱"
    assert verify["human_next"] == "选择该采集箱商品继续编辑保存"


def test_browser_agent_status_maps_save_steps_to_chinese_hud():
    editor = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "OPEN_EDIT_PAGE",
        "status": "running",
    })
    assert editor["title"] == "正在打开编辑页"
    assert editor["line1"] == "进入采集箱商品编辑页"
    assert editor["phase"] == "第二段：采集箱编辑保存"

    fill = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "FILL_BASE_INFO",
        "status": "running",
    })
    assert fill["title"] == "正在编辑商品"
    assert fill["line1"] == "正在填写标题"
    assert fill["human_next"] == "继续填写价格、图片和物流信息"

    media = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "FILL_MEDIA",
        "status": "running",
    })
    assert media["title"] == "正在编辑商品"
    assert media["line1"] == "正在处理图片"

    save = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })
    assert save["title"] == "正在只保存"
    assert save["line1"] == "只点击保存，不发布"
    assert save["guard"] == "只保存不发布"
    assert save["human_next"] == "确认商品没有发布"

    verify = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "VERIFY_NOT_PUBLISHED",
        "status": "running",
    })
    assert verify["title"] == "正在检查结果"
    assert verify["line1"] == "确认商品没有发布"
    assert verify["human_next"] == "查看保存结果和未发布证明"


def test_browser_agent_status_tells_user_browser_stays_open_after_terminal_states():
    done = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "RELEASE_LOCK",
        "status": "success",
    })
    assert done["title"] == "任务完成"
    assert "真实浏览器保持打开" in done["human_next"]
    assert done["requires_user_action"] is False

    failed = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "TASK_FAILED",
        "status": "failed",
    })
    assert failed["title"] == "当前步骤失败"
    assert "真实浏览器保持打开" in failed["human_next"]
    assert failed["requires_user_action"] is True


def test_browser_agent_status_does_not_put_step_code_in_maintenance_detail_for_normal_steps():
    hud = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })

    assert hud["maintenance_detail"] is None


def test_browser_agent_status_hides_unknown_technical_step_from_default_copy():
    hud = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "SOME_INTERNAL_STEP",
        "status": "failed",
        "error": "Cannot switch to a different thread",
    })

    assert hud["title"] == "当前步骤需要处理"
    assert hud["line1"] == "请按控制台提示处理后重试"
    assert hud["severity"] == "error"
    assert hud["requires_user_action"] is True
    assert "SOME_INTERNAL_STEP" not in hud["title"]
    assert "Cannot switch" not in hud["line1"]
    assert "Cannot switch" in hud["maintenance_detail"]
