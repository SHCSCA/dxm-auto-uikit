from __future__ import annotations

import os
import json
import threading
import time

import pytest

from src.execution.browser_agent_protocol import BrowserAgentCommand
import src.execution.browser_agent_worker as browser_agent_worker
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.services.browser_agent_status import build_browser_hud


def test_browser_agent_status_maps_acquisition_steps_to_chinese_hud():
    open_page = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "OPEN_DATA_ACQUISITION",
        "status": "running",
        "store_name": "Dang Kang",
    })
    assert open_page["title"] == "正在打开待认领商品列表"
    assert open_page["line1"] == "进入店小秘已有待认领列表"
    assert open_page["line2"] == "店铺：Dang Kang"
    assert open_page["phase"] == "第一段：待认领商品"
    assert open_page["severity"] == "running"
    assert open_page["requires_user_action"] is False

    claim = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "CLAIM_TO_DRAFT_BOX",
        "status": "running",
    })
    assert claim["title"] == "正在认领已有商品"
    assert claim["line1"] == "把已有待认领商品认领到商品箱"
    assert claim["human_next"] == "检查商品是否已进入商品箱"

    verify = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "VERIFY_DRAFT_BOX_CLAIM",
        "status": "running",
    })
    assert verify["title"] == "正在确认商品箱"
    assert verify["line1"] == "检查商品是否已进入商品箱"
    assert verify["human_next"] == "选择该商品箱商品继续编辑保存"


def test_browser_agent_status_maps_save_steps_to_chinese_hud():
    editor = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "OPEN_EDIT_PAGE",
        "status": "running",
    })
    assert editor["title"] == "正在打开编辑页"
    assert editor["line1"] == "进入商品编辑页"
    assert editor["phase"] == "第二段：商品箱编辑保存"

    fill = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "FILL_BASE_INFO",
        "status": "running",
    })
    assert fill["title"] == "正在编辑商品"
    assert fill["line1"] == "正在填写标题"
    assert fill["human_next"] == "继续填写价格、图片和物流信息"

    media = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "FILL_MEDIA",
        "status": "running",
    })
    assert media["title"] == "正在编辑商品"
    assert media["line1"] == "正在处理图片"

    save = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })
    assert save["title"] == "正在只保存"
    assert save["line1"] == "只点击保存，不发布"
    assert save["guard"] == "只保存不发布"
    assert save["human_next"] == "确认商品没有发布"

    verify = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "VERIFY_NOT_PUBLISHED",
        "status": "running",
    })
    assert verify["title"] == "正在检查结果"
    assert verify["line1"] == "确认商品没有发布"
    assert verify["human_next"] == "查看保存结果和未发布证明"


def test_browser_agent_status_tells_user_browser_stays_open_after_terminal_states():
    done = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "RELEASE_LOCK",
        "status": "success",
    })
    assert done["title"] == "任务完成"
    assert "真实浏览器保持打开" in done["human_next"]
    assert done["requires_user_action"] is False

    failed = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "TASK_FAILED",
        "status": "failed",
    })
    assert failed["title"] == "当前步骤失败"
    assert "真实浏览器保持打开" in failed["human_next"]
    assert failed["requires_user_action"] is True


def test_browser_agent_status_failed_session_points_to_login_recheck():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "PRECHECK_SESSION",
        "status": "failed",
        "error": "执行浏览器还没有登录店小秘；请在打开的真实浏览器完成登录后再检测。",
    })

    assert hud["title"] == "需要登录店小秘"
    assert hud["line1"] == "执行浏览器还没有登录店小秘；请在打开的真实浏览器完成登录后再检测。"
    assert hud["human_next"] == "在真实浏览器完成登录后重新检测"
    assert hud["phase"] == "等待登录"
    assert hud["requires_user_action"] is True


def test_browser_agent_status_does_not_put_step_code_in_maintenance_detail_for_normal_steps():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })

    assert hud["maintenance_detail"] is None


def test_browser_agent_status_hides_unknown_technical_step_from_default_copy():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
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


def test_browser_agent_runtime_reports_last_internal_claim_step_on_timeout():
    class SlowClaimAdapter:
        def __init__(self):
            self.listener = None

        def set_workflow_event_listener(self, listener):
            self.listener = listener

        def recent_workflow_events(self):
            return [{
                "event": "data_acquisition_claim:target_find_start",
                "human_step": "定位待认领商品",
            }]

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            if self.listener:
                self.listener({
                    "event": "data_acquisition_claim:target_find_start",
                    "human_step": "定位待认领商品",
                })
            time.sleep(0.2)
            return {"ok": True}

    runtime = BrowserAgentRuntime(SlowClaimAdapter())
    command = BrowserAgentCommand(
        task_id=40,
        job_id=40,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        step_label="认领到商品箱",
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=0.02)

    status = runtime.status()
    assert status["healthy"] is False
    assert status["currentStep"] == "定位待认领商品"
    assert "定位待认领商品" in status["lastError"]
    assert any(event["action"] == "workflow_trace" and event["step"] == "定位待认领商品" for event in status["events"])
    runtime.shutdown()


def test_browser_agent_runtime_applies_hud_inside_agent_thread_before_action():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["human_action"]))
            return {"ok": True, "updated": True, "hud": hud}

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.calls.append(("claim",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "page_title": "店小秘--待认领列表",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=41,
        job_id=41,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS", "store_name": "Dang Kang"},
        step_label="认领到商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls[0] == ("hud", "CLAIM_TO_DRAFT_BOX", "把已有待认领商品认领到商品箱")
    assert adapter.calls[1] == ("claim",)
    assert adapter.calls[-1][0] == "hud"
    status = runtime.status()
    assert status["hud"]["state"] == "CLAIM_TO_DRAFT_BOX"
    assert status["message"] == "把已有待认领商品认领到商品箱"
    assert status["nextAction"] == "检查商品是否已进入商品箱"
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_navigation_actions():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def open_draft_box(self):
            self.calls.append(("open_draft_box",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=41,
        job_id=41,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("open_draft_box",)]
    status = runtime.status()
    assert status["status"] == "idle"
    assert status["hud"]["status"] == "success"
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_open_editor():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def open_editor(self, **kwargs):
            self.calls.append(("open_editor", kwargs.get("product_query")))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1",
                "page_title": "店小秘--编辑产品",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=42,
        job_id=42,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={"store_name": "Dang Kang", "product_query": "目标商品"},
        step_label="打开编辑页",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("open_editor", "目标商品")]
    assert runtime.status()["hud"]["status"] == "success"
    runtime.shutdown()


@pytest.mark.parametrize(
    ("action", "state"),
    [
        ("verify_edit_ownership", "VERIFY_EDIT_OWNERSHIP"),
        ("fill_editor_required_defaults", "FILL_EDITOR_REQUIRED_DEFAULTS"),
        ("save_only", "SAVE_ONLY"),
        ("verify_not_published", "VERIFY_NOT_PUBLISHED"),
    ],
)
def test_browser_agent_runtime_defers_page_hud_for_editor_and_save_actions(action, state):
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def verify_edit_ownership(self, **kwargs):
            self.calls.append(("verify_edit_ownership", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

        def fill_editor_required_defaults(self, **kwargs):
            self.calls.append(("fill_editor_required_defaults", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

        def save_only(self, **kwargs):
            self.calls.append(("save_only", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

        def verify_not_published(self, **kwargs):
            self.calls.append(("verify_not_published", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=43,
        job_id=43,
        state=state,
        action=action,
        params={"store_name": "Dang Kang", "product_query": "目标商品"},
        step_label="编辑页动作",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert all(call[0] != "hud" for call in adapter.calls)
    assert adapter.calls == [(action, "目标商品")]
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_login_check():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def check_login_state(self):
            self.calls.append(("check_login_state",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
                "page_title": "店小秘--首页",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=41,
        job_id=41,
        state="PRECHECK_SESSION",
        action="check_login_state",
        params={"store_name": "Dang Kang"},
        step_label="检查店小秘登录状态",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("check_login_state",)]
    status = runtime.status()
    assert status["status"] == "idle"
    assert status["hud"]["status"] == "success"
    runtime.shutdown()


def test_browser_agent_runtime_writes_request_result_and_trace_files(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_agent_worker, "DATA_DIR", tmp_path)

    class TraceWritingAdapter:
        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, _hud):
            return {"ok": True, "updated": True}

        def open_draft_box(self):
            trace_file = os.environ.get("DXM_WORKFLOW_TRACE_FILE")
            assert trace_file
            with open(trace_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "navigate:return", "human_step": "商品箱页面已打开"}, ensure_ascii=False) + "\n")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    runtime = BrowserAgentRuntime(TraceWritingAdapter())
    command = BrowserAgentCommand(
        task_id=88,
        job_id=99,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    request_file = result["browser_agent_request_file"]
    result_file = result["browser_agent_result_file"]
    trace_file = result["workflow_trace_file"]
    assert os.path.exists(request_file)
    assert os.path.exists(result_file)
    assert os.path.exists(trace_file)
    assert json.loads(open(request_file, encoding="utf-8").read())["action"] == "open_draft_box"
    persisted = json.loads(open(result_file, encoding="utf-8").read())
    assert persisted["ok"] is True
    assert persisted["result"]["ok"] is True
    assert "商品箱页面已打开" in open(trace_file, encoding="utf-8").read()
    runtime.shutdown()


def test_browser_agent_runtime_does_not_apply_success_hud_after_failed_action():
    class FailedNavigationAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["human_action"]))
            if len([call for call in self.calls if call[0] == "hud"]) > 1:
                raise AssertionError("failed browser action must not write a success HUD")
            return {"ok": True, "updated": True, "hud": hud}

        def open_draft_box(self):
            self.calls.append(("open_draft_box",))
            return {
                "ok": False,
                "stage": "workflow_navigation_failed",
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "message": "商品箱静置后仍未加载完成",
            }

    adapter = FailedNavigationAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=42,
        job_id=42,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is False
    assert adapter.calls == [
        ("open_draft_box",),
    ]
    status = runtime.status()
    assert status["status"] == "failed"
    assert status["healthy"] is False
    assert "商品箱静置后仍未加载完成" in status["lastError"]
    runtime.shutdown()


def test_browser_agent_runtime_enables_stable_visible_workflow_profile(monkeypatch, tmp_path):
    captured = {}

    class Adapter:
        def set_workflow_event_listener(self, _listener):
            return None

        def open_draft_box(self):
            captured["persistent"] = os.environ.get("DXM_WORKFLOW_PERSISTENT_PROFILE")
            captured["profile_dir"] = os.environ.get("DXM_WORKFLOW_PROFILE_DIR")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    data_dir = tmp_path / "data"
    monkeypatch.delenv("DXM_WORKFLOW_PERSISTENT_PROFILE", raising=False)
    monkeypatch.delenv("DXM_WORKFLOW_PROFILE_DIR", raising=False)
    monkeypatch.setenv("DXM_DATA_DIR", str(data_dir))

    runtime = BrowserAgentRuntime(Adapter())
    command = BrowserAgentCommand(
        task_id=43,
        job_id=43,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert captured["persistent"] == "1"
    assert captured["profile_dir"] == str(data_dir / "browser_profiles" / "dxm_workflow")
    assert runtime.status()["profile_dir"] == captured["profile_dir"]
    runtime.shutdown()


def test_browser_agent_runtime_shutdown_closes_browser_on_agent_thread():
    class Adapter:
        def __init__(self):
            self.action_thread = None
            self.close_thread = None

        def set_workflow_event_listener(self, _listener):
            return None

        def open_draft_box(self):
            self.action_thread = threading.get_ident()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

        def close_browser_session(self):
            self.close_thread = threading.get_ident()

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        task_id=44,
        job_id=44,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    runtime.run(command, timeout_seconds=1)
    runtime.shutdown()

    assert adapter.close_thread == adapter.action_thread


def test_browser_agent_runtime_resume_releases_manual_takeover_state():
    runtime = BrowserAgentRuntime()
    takeover = runtime.request_manual_takeover()
    assert takeover["manualTakeover"] is True
    assert takeover["status"] == "manual_takeover"

    resumed = runtime.resume()

    assert resumed["manualTakeover"] is False
    assert resumed["status"] == "idle"
    assert resumed["currentStep"] == "等待继续执行"
    assert any(event["action"] == "resume" for event in resumed["events"])
    runtime.shutdown()


def test_browser_agent_runtime_blocks_commands_during_manual_takeover():
    class Adapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            raise AssertionError("agent command must not run during manual takeover")

    runtime = BrowserAgentRuntime(Adapter())
    runtime.request_manual_takeover()
    command = BrowserAgentCommand(
        task_id=42,
        job_id=42,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        step_label="认领到商品箱",
    )

    with pytest.raises(RuntimeError, match="人工接管"):
        runtime.run(command, timeout_seconds=1)

    status = runtime.status()
    assert status["manualTakeover"] is True
    assert status["status"] == "manual_takeover"
    runtime.shutdown()
