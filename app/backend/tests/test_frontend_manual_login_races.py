"""实际 App 的合成会话竞态；离线响应不提供真实登录或店铺资格。"""

import json

from playwright.sync_api import expect

from test_frontend_e1_browser import browser, vite_origin
from test_frontend_manual_login_browser import _install_api


def _json(route, payload):
    route.fulfill(status=200, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))


def _shops(shop_id):
    return {'source': 'api', 'session_bound': True, 'session_ref': f'synthetic-{shop_id}',
        'shops': [{'id': shop_id, 'name': f'合成店铺{shop_id}', 'platform': 'smt', 'shop_type': 'POP'}]}


def _open(page, origin, state=None):
    _install_api(page, state if state is not None else {})
    page.goto(origin, wait_until='domcontentloaded')
    page.locator('[data-section="dxm_access"]').click()
    access = page.get_by_role('region', name='登录店小秘', exact=True)
    expect(access.get_by_role('button', name='手动登录', exact=True)).to_be_enabled()
    return access


def _settle(page):
    page.evaluate('() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))')


def test_manual_handoff_discards_late_previous_shop_response(browser, vite_origin):
    page = browser.new_page(); access = _open(page, vite_origin)
    held = []
    page.route('**/api/dxm/draft-reader/shops', lambda route: held.append(route))
    with page.expect_request('**/api/dxm/draft-reader/shops'):
        page.get_by_title('重新读取真实店铺', exact=True).click()
    access.get_by_role('button', name='手动登录', exact=True).click()
    expect(access.get_by_text('等待手动登录', exact=True).first).to_be_visible()
    assert len(held) == 1
    with page.expect_response('**/api/dxm/draft-reader/shops'):
        _json(held[0], _shops('old'))
    _settle(page)
    selector = page.get_by_role('combobox', name='选择当前店铺', exact=True)
    expect(selector.locator('option[value="old"]')).to_have_count(0)
    expect(selector).to_have_value('')
    page.close()


def test_continue_starts_new_session_shop_read_without_waiting_for_old_request(browser, vite_origin):
    page = browser.new_page(); access = _open(page, vite_origin)
    held = []

    def shops(route):
        held.append(route)
        if len(held) == 2:
            _json(route, _shops('new'))

    page.route('**/api/dxm/draft-reader/shops', shops)
    with page.expect_request('**/api/dxm/draft-reader/shops'):
        page.get_by_title('重新读取真实店铺', exact=True).click()
    access.get_by_role('button', name='手动登录', exact=True).click()
    expect(access.get_by_text('等待手动登录', exact=True).first).to_be_visible()
    page.route('**/api/dxm/login/continue', lambda route: _json(route, {
        'ok': True, 'stage': 'login_success', 'reason_code': 'LOGIN_READER_READY',
        'logged_in': True, 'reader_ready': True, 'message': '合成检测通过'}))
    # 新会话必须能独立读取，不能等旧请求完成后借用它的返回值。
    with page.expect_request('**/api/dxm/draft-reader/shops', timeout=2000):
        access.get_by_role('button', name='验证码完成后检测登录状态', exact=True).click()
    selector = page.get_by_role('combobox', name='选择当前店铺', exact=True)
    expect(selector).to_have_value('new')
    assert len(held) == 2, '新会话检测复用了旧会话的在途店铺 Promise'
    _json(held[0], _shops('old')); _settle(page)
    expect(selector).to_have_value('new')
    expect(selector.locator('option[value="old"]')).to_have_count(0)
    page.close()


def test_pending_manual_open_cannot_reacquire_old_login_from_fresh_runtime_poll(browser, vite_origin):
    page = browser.new_page(); state = {}; access = _open(page, vite_origin, state)
    held = []
    page.route('**/api/dxm/workflow/manual-login', lambda route: held.append(route))
    access.get_by_role('button', name='手动登录', exact=True).click()
    expect(access.get_by_text('已登录，继续下一步', exact=True)).to_have_count(0)

    state['old_login'] = True
    # 真实轮询在请求发起后返回旧账号绿态，仍不能覆盖正在打开的手动会话。
    with page.expect_response('**/api/runtime/status?*', timeout=8000):
        page.wait_for_timeout(5100)
    _settle(page)
    expect(access.get_by_text('已登录，继续下一步', exact=True)).to_have_count(0)
    expect(access.get_by_role('button', name='验证码完成后检测登录状态')).to_be_disabled()
    assert len(held) == 1
    state['old_login'] = False
    _json(held[0], {'ok': True, 'stage': 'manual_login_required',
        'reason_code': 'MANAGED_MANUAL_LOGIN_REQUIRED', 'logged_in': False,
        'reader_ready': False, 'browser_visible': True})
    expect(access.get_by_text('等待手动登录', exact=True).first).to_be_visible()
    page.close()
