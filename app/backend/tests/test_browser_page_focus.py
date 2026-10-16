import logging
from types import SimpleNamespace

import pytest

from src.execution.browser_page_focus import bring_controlled_page_to_front
from src.execution.dxm_login_flow import DxmLoginFlow


def test_controlled_page_is_focused_exactly_once():
    calls = []
    page = SimpleNamespace(bring_to_front=lambda: calls.append("focus"))
    assert bring_controlled_page_to_front(page) is True
    assert calls == ["focus"]


@pytest.mark.parametrize("page", [object(), SimpleNamespace(bring_to_front=False)])
def test_missing_focus_method_is_logged_and_never_claimed_successful(page, caplog):
    with caplog.at_level(logging.ERROR, logger="dxm.browser_page_focus"):
        assert bring_controlled_page_to_front(page) is False
    records = [record for record in caplog.records if record.message == "controlled_page_focus_failed"]
    assert len(records) == 1
    assert str(records[0].exc_info[1]) == "BROWSER_PAGE_FOCUS_METHOD_UNAVAILABLE"


def test_focus_exception_is_logged_without_retry(caplog):
    calls = []
    error = RuntimeError("page connection closed")

    def fail_focus():
        calls.append("focus")
        raise error

    with caplog.at_level(logging.ERROR, logger="dxm.browser_page_focus"):
        assert bring_controlled_page_to_front(SimpleNamespace(bring_to_front=fail_focus)) is False
    assert calls == ["focus"]
    records = [record for record in caplog.records if record.message == "controlled_page_focus_failed"]
    assert len(records) == 1 and records[0].exc_info[1] is error


def test_focus_method_lookup_exception_is_logged(caplog):
    class BrokenPage:
        @property
        def bring_to_front(self):
            raise RuntimeError("page unavailable")

    with caplog.at_level(logging.ERROR, logger="dxm.browser_page_focus"):
        assert bring_controlled_page_to_front(BrokenPage()) is False
    assert len([record for record in caplog.records if record.message == "controlled_page_focus_failed"]) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_flow_focus_never_enters_global_native_window_branch(tmp_path, monkeypatch, fails):
    flow = DxmLoginFlow(object(), state_file=tmp_path / "runtime.json")
    calls = []

    def reject_native(*_args, **_kwargs):
        pytest.fail("页面前置不得枚举或操作全局桌面窗口")

    def focus():
        calls.append("focus")
        if fails:
            raise RuntimeError("page unavailable")

    monkeypatch.setattr(flow, "_force_foreground_dxm_window", reject_native, raising=False)
    monkeypatch.setattr(flow, "_click_point_with_native_window", reject_native)
    assert flow._bring_page_to_front_for_click(SimpleNamespace(bring_to_front=focus)) is not fails
    assert calls == ["focus"]
