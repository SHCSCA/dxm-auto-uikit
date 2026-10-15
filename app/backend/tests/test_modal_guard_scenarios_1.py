from playwright.sync_api import sync_playwright

from tests.test_login_flow import (
    DxmLoginFlow, DummyLiveClient, DummyGuideOverlayPage,
    DummyImportantReminderModalPage, DummyReminderDropdownPage,
    DummyPersistentModalUntilEscapePage,
)

def test_modal_guard_preserves_unbound_plugin_guide(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyGuideOverlayPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_preserves_unbound_important_reminder(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImportantReminderModalPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_preserves_unbound_reminder_dropdown(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyReminderDropdownPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_never_escapes_unbound_modal(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyPersistentModalUntilEscapePage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'
    assert page.presses == []
