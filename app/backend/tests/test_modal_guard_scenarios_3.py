from playwright.sync_api import sync_playwright

from tests.test_login_flow import (
    DxmLoginFlow, DummyLiveClient, DummyGuideOverlayPage,
    DummyImportantReminderModalPage, DummyReminderDropdownPage,
    DummyPersistentModalUntilEscapePage,
)

def test_modal_guard_preserves_unbound_campaign(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <div class="dxm-campaign-layer" style="position:fixed;left:240px;top:120px;width:620px;height:280px;background:white;z-index:9999">
              <h3>重要提醒</h3>
              <div>您的活动权益即将结束，查看最新特惠</div>
              <button id="next" style="position:absolute;right:24px;bottom:18px;width:80px;height:32px">下一步</button>
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


def test_modal_guard_preserves_dialog_with_mask(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="ant-modal-root">
              <div class="ant-modal-mask" style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99998"></div>
              <div class="ant-modal-wrap comm-vip-tips-modal important-remind comm-modal" role="dialog"
                   style="position:fixed;left:120px;top:80px;width:620px;height:220px;background:white;z-index:99999">
                <div class="ant-modal-content">
                  <div class="ant-modal-title">重要提醒</div>
                  <div>您购买的 图片空间 将在 <span>2天后</span> 过期</div>
                  <a class="ant-dropdown-link ant-dropdown-trigger" style="position:absolute;left:480px;top:170px;width:90px;height:24px">忽略提示</a>
                </div>
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


def test_modal_guard_does_not_click_unbound_next_button(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 520})
        page.set_content(
            '''
            <div class="ant-modal-root">
              <div class="ant-modal-mask" style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99998"></div>
              <div class="ant-modal-wrap bullet-layer notice-list-modal" role="dialog"
                   style="position:fixed;left:160px;top:70px;width:520px;height:280px;background:white;z-index:99999">
                <div class="notice-list-modal__header">重要通知</div>
                <div class="notice-content__title">店小秘618钜惠今日启动</div>
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


def test_modal_guard_preserves_stacked_unbound_notices(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 760})
        page.set_content(
            '''
            <div class="ant-modal-wrap comm-vip-tips-modal important-remind comm-modal" role="dialog"
                 style="position:fixed;left:320px;top:120px;width:620px;height:220px;background:white;z-index:99999">
              <div class="ant-modal-content">
                <div class="ant-modal-title">重要提醒</div>
                <div>您购买的 VIP1 将在3天后 过期，功能将被停用</div>
                <a class="ant-dropdown-link ant-dropdown-trigger" style="position:absolute;left:480px;top:170px;width:90px;height:24px">忽略提示</a>
              </div>
            </div>
            <div class="ant-modal-wrap bullet-layer notice-list-modal" role="dialog"
                 style="position:fixed;left:240px;top:80px;width:760px;height:440px;background:white;z-index:100000">
              <button class="ant-modal-close ant-modal-close-x" style="position:absolute;right:16px;top:16px;width:32px;height:32px">x</button>
              <div class="notice-list-modal__header">线下活动</div>
              <h2>小秘公告 TikTok Shop 美区HOME行业 圣诞专题四城招品会</h2>
              <p>报名链接：https://www.hudongba.com/dis/q1x45n9vm8</p>
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
