from playwright.sync_api import sync_playwright

from tests.test_login_flow import (
    DxmLoginFlow, DummyLiveClient, DummyGuideOverlayPage,
    DummyImportantReminderModalPage, DummyReminderDropdownPage,
    DummyPersistentModalUntilEscapePage,
)

def test_modal_guard_preserves_informational_notice(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="ant-modal-wrap bullet-layer notice-list-modal" role="dialog"
                 style="position:fixed;left:160px;top:70px;width:520px;height:280px;background:white;z-index:99999">
              <div class="notice-list-modal__header">小秘公告</div>
              <div>官方战略发布与圣诞品类方向说明，不是商品发布确认。</div>
              <button id="close" style="position:absolute;right:16px;bottom:14px;width:72px;height:28px">关闭</button>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_preserves_unbound_logistics_notice(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="logistics-attr-notice" style="position:relative;width:600px;height:40px">
              新增说明：平台物流属性更新，点击此处跳转设置
            </div>
            <div class="ant-modal-root">
              <div class="ant-modal-mask" style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99998"></div>
              <div class="ant-modal-wrap bullet-layer notice-list-modal" role="dialog"
                   style="position:fixed;left:160px;top:70px;width:520px;height:280px;background:white;z-index:99999">
                <div class="notice-list-modal__header">重要通知</div>
                <button id="next" style="position:absolute;right:16px;bottom:14px;width:72px;height:28px">下一条</button>
              </div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_does_not_click_unbound_small_prompt(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="important-remind" style="position:fixed;left:120px;top:80px;width:620px;height:220px;background:white;z-index:99999">
              <div>重要提醒</div>
              <div id="wide-footer" style="position:absolute;left:220px;top:170px;width:360px;height:26px">
                <a id="ignore" style="display:inline-block;width:90px;height:24px">忽略提示</a>
              </div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'


def test_modal_guard_does_not_click_unbound_span(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="important-remind" style="position:fixed;left:80px;top:80px;width:720px;height:220px;background:white;z-index:99999">
              <div>重要提醒</div>
              <a id="wide-ignore" style="position:absolute;left:300px;top:170px;width:360px;height:26px">
                <span id="ignore-text" style="display:inline-block;width:64px;height:24px">忽略提示</span>
              </a>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'
