"""实际挂载 App 的离线交互；合成 API 响应不证明店小秘登录或执行资格。"""

import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from test_frontend_e1_browser import browser, vite_origin


def _install_api(page: Page, state):
    requests = []

    def handle(route: Route):
        request = route.request; path = urlparse(request.url).path
        if request.method == 'POST':
            requests.append((path, request.post_data_json))
        if path == '/api/runtime/status':
            payload = {'runtimeIdentity': {}, 'backend': {'status': 'running', 'runtimeIdentity': {}},
                'frontend': {'status': 'running'}, 'dependencies': {},
                'agentConsole': {'status': 'idle', 'active': False, 'browserVisible': False},
                'browserAgent': {'status': 'idle', 'active': False, 'browserVisible': False,
                    'manualTakeover': False, 'needsRestart': False, 'executionLeaseActive': False,
                    'sessionOperationActive': False, 'reservedCommandCount': 0, **state.get('agent', {})},
                'realBrowser': {'status': 'idle', 'active': False, 'browserVisible': state.get('opened', False)},
                'dxmLogin': {'status': 'manual_login_required' if state.get('opened') else 'logged_out',
                    'loggedIn': False, 'readerReady': False, 'browserVisible': state.get('opened', False)}}
            if state.get('old_login'):
                payload['dxmLogin'] = {'status': 'login_success', 'loggedIn': True,
                    'readerReady': True, 'browserVisible': True}
        elif path == '/api/dxm/workflow/manual-login':
            if state.get('conflict'):
                route.fulfill(status=409, content_type='application/json', body=json.dumps({
                    'detail': {'message': '当前浏览器正在人工接管，不能替换登录会话。'}}, ensure_ascii=False))
                return
            state['opened'] = True
            payload = {'ok': True, 'stage': 'manual_login_required', 'reason_code': 'MANAGED_MANUAL_LOGIN_REQUIRED',
                'logged_in': False, 'reader_ready': False, 'browser_visible': True}
            if state.get('misleading'):
                state['opened'] = False
                payload.update(logged_in=True, reader_ready=True)
        elif path == '/api/dxm/login/continue':
            payload = {'ok': True, 'stage': 'manual_login_required', 'logged_in': False,
                'reader_ready': False, 'message': '请继续在真实浏览器完成登录。'}
        elif path == '/api/dxm/login/start':
            payload = {'ok': True, 'stage': 'waiting_captcha', 'logged_in': False,
                'reader_ready': False, 'message': '等待验证码'}
        elif path == '/api/runtime/logs':
            payload = {'source': 'backend', 'path': '', 'exists': False, 'cursor': 0, 'nextCursor': 0, 'lines': [], 'truncated': False}
        elif path == '/api/dxm/draft-reader/shops':
            payload = {'source': 'api', 'session_bound': False, 'shops': []}
        elif path == '/api/agent-console/status':
            payload = None
        elif path == '/api/delivery/workspace':
            payload = {}
        else:
            payload = []
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))

    page.route('**/api/**', handle)
    return requests


def _open(page, origin, state):
    requests = _install_api(page, state)
    page.goto(origin, wait_until='domcontentloaded')
    page.locator('[data-section="dxm_access"]').click()
    access = page.get_by_role('region', name='登录店小秘', exact=True)
    expect(access.get_by_role('button', name='手动登录', exact=True)).to_be_visible()
    return access, requests


def test_actual_app_manual_open_needs_no_credentials_and_keeps_detection_separate(browser: Browser, vite_origin: str):
    page = browser.new_page(); access, requests = _open(page, vite_origin, {})
    expect(access.get_by_placeholder('输入 DXM 账号')).to_have_value('')
    expect(access.get_by_placeholder('仅本次登录使用')).to_have_value('')
    manual = access.get_by_role('button', name='手动登录', exact=True)
    expect(manual).to_be_enabled(); manual.click()
    expect(access.get_by_text('等待手动登录', exact=True).first).to_be_visible()
    expect(manual).to_be_disabled()
    expect(access.get_by_text('已登录，继续下一步', exact=True)).to_have_count(0)
    detect = access.get_by_role('button', name='验证码完成后检测登录状态', exact=True)
    expect(detect).to_be_enabled(); detect.click()
    expect(page.get_by_role('alert').filter(has_text='请继续在真实浏览器完成登录')).to_be_visible()
    assert [(path, body) for path, body in requests if path == '/api/dxm/workflow/manual-login'] == [('/api/dxm/workflow/manual-login', {})]
    assert ('/api/dxm/login/continue', {'confirm': True}) in requests
    assert not any(path == '/api/dxm/login/start' or 'approve' in path or '/start' in path for path, _ in requests)
    page.close()


@pytest.mark.parametrize('agent', [{'manualTakeover': True}, {'status': 'running', 'active': True},
    {'executionLeaseActive': True}, {'reservedCommandCount': 1}])
def test_actual_app_disables_manual_open_while_browser_is_owned(browser: Browser, vite_origin: str, agent):
    page = browser.new_page(); access, requests = _open(page, vite_origin, {'agent': agent})
    expect(access.get_by_role('button', name='手动登录', exact=True)).to_be_disabled()
    assert not any(path == '/api/dxm/workflow/manual-login' for path, _ in requests)
    page.close()


@pytest.mark.parametrize('fault, message', [('conflict', '人工接管'), ('misleading', '未能确认')])
def test_actual_app_shows_failures_and_never_treats_ok_as_logged_in(browser: Browser, vite_origin: str, fault, message):
    page = browser.new_page(); access, requests = _open(page, vite_origin, {fault: True})
    access.get_by_role('button', name='手动登录', exact=True).click()
    expect(page.get_by_role('alert').filter(has_text=message)).to_be_visible()
    expect(access.get_by_text('已登录，继续下一步', exact=True)).to_have_count(0)
    expect(access.get_by_role('button', name='验证码完成后检测登录状态')).to_be_disabled()
    assert len([path for path, _ in requests if path == '/api/dxm/workflow/manual-login']) == 1
    page.close()


def test_existing_credential_form_still_calls_only_the_original_login_route(browser: Browser, vite_origin: str):
    page = browser.new_page(); access, requests = _open(page, vite_origin, {})
    access.get_by_placeholder('输入 DXM 账号').fill('synthetic-user')
    access.get_by_placeholder('仅本次登录使用').fill('synthetic-password')
    access.locator('form').get_by_role('button', name='打开真实登录页', exact=True).click()
    expect(page.get_by_test_id('operation-notice')).to_contain_text('等待验证码')
    assert ('/api/dxm/login/start', {'username': 'synthetic-user', 'password': 'synthetic-password'}) in requests
    assert not any(path == '/api/dxm/workflow/manual-login' for path, _ in requests)
    page.close()
