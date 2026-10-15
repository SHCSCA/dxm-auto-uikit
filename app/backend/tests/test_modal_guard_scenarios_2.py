from playwright.sync_api import sync_playwright

from tests.test_login_flow import (
    DxmLoginFlow, DummyLiveClient, DummyGuideOverlayPage,
    DummyImportantReminderModalPage, DummyReminderDropdownPage,
    DummyPersistentModalUntilEscapePage,
)

def test_modal_guard_never_deletes_stuck_notice(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 760})
        page.set_content(
            '''
            <div class="ant-modal-wrap comm-vip-tips-modal important-remind comm-modal" role="dialog"
                 style="position:fixed;left:0;top:0;width:1200px;height:760px;background:rgba(0,0,0,.15);z-index:99999">
              <div class="ant-modal css-1oz1bg8"
                   style="position:absolute;left:370px;top:100px;width:700px;height:280px;background:white">
                <div class="ant-modal-content">
                  <div class="ant-modal-title">重要提醒</div>
                  <div>您购买的 VIP1 将在3天后 过期，功能将被停用，超出的图片空间将被冻结</div>
                  <div class="ant-modal-footer" style="position:absolute;left:15px;top:210px;width:670px;height:26px">
                    <a class="ant-dropdown-link ant-dropdown-trigger"
                       style="position:absolute;right:0;top:5px;width:72px;height:15px">忽略提示</a>
                  </div>
                </div>
              </div>
            </div>
            '''
        )

        def fake_click(_target_page, rect):
            clicks.append(rect)

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        remaining = page.locator('.ant-modal-wrap').count()
        browser.close()

    assert dismissed == 0
    assert clicks == []
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'blocking_modal_preserved_fail_closed'
    assert flow._last_dismiss_blocking_modals_trace[-1]['reason'] == 'exact_semantic_close_control_not_bound'
    assert remaining == 1


def test_modal_guard_does_not_click_unbound_ignore_prompt(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 500, 'height': 260})
        page.set_content(
            '''
            <div class="ant-modal-wrap" style="position:fixed;left:0;top:0;width:420px;height:220px;background:white;display:block">
              <button class="ant-modal-close" style="position:absolute;left:360px;top:10px;width:20px;height:20px"></button>
              <div style="padding:50px">距离活动结束仅剩 1 小时</div>
              <button id="ignore" style="position:absolute;left:40px;top:140px;width:90px;height:30px">忽略提示</button>
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


def test_modal_guard_never_deletes_stacked_notices(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 760})
        page.set_content(
            '''
            <div class="ant-modal-wrap comm-vip-tips-modal important-remind comm-modal" role="dialog"
                 style="position:fixed;left:0;top:0;width:1200px;height:760px;background:rgba(0,0,0,.15);z-index:99999">
              <div class="ant-modal-title">重要提醒</div>
              <div>您购买的 VIP1 将在3天后 过期，功能将被停用</div>
              <a>忽略提示</a>
            </div>
            <div class="ant-modal-wrap bullet-layer notice-list-modal notice-list-modal--offline" role="dialog"
                 style="position:fixed;left:0;top:0;width:1200px;height:760px;background:rgba(0,0,0,.15);z-index:99998">
              <div class="notice-list-modal__header">线下活动</div>
              <div class="notice-list-modal__body">小秘公告 TikTok Shop 美区活动报名</div>
              <button class="ant-modal-close">x</button>
            </div>
            '''
        )

        removed = flow._remove_stuck_notice_modal(page)
        remaining = page.locator('.ant-modal-wrap').count()
        browser.close()

    assert removed == {'removed': False, 'reason': 'DOM_MODAL_MUTATION_FALLBACK_FORBIDDEN'}
    assert remaining == 2


def test_modal_guard_preserves_unbound_standalone_prompt(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 900, 'height': 500})
        page.set_content(
            '''
            <div class="activity-popover" style="position:fixed;left:300px;top:180px;width:320px;height:60px;background:white;z-index:9999">
              <div id="ignore" style="position:absolute;left:20px;top:16px;width:110px;height:28px">忽略提示</div>
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
