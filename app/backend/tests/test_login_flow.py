from pathlib import Path
import threading
import time

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from src.execution import dxm_login_flow as dxm_login_flow_module
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow, WORKFLOW_TARGETS
from src.models import LoginContinueRequest, LoginStartRequest
from src.main import app
import src.main as main_module


class DummyLiveClient:
    def __init__(self, logged_in: bool = False):
        self.logged_in = logged_in
        self.probed = False
        self.cookie_file = Path('/tmp/dummy-cookies.json')

    def probe_session(self):
        self.probed = True
        if self.logged_in:
            return {
                'logged_in': True,
                'title': '店小秘首页',
                'final_url': 'https://www.dianxiaomi.com/index.htm',
                'home_screenshot_url': '/artifacts/screenshots/home.png',
            }
        return {
            'logged_in': False,
            'title': '店小秘官网登录页',
            'final_url': 'https://www.dianxiaomi.com/',
        }

    def has_cookie_session(self):
        return True

    def load_cookies(self):
        return []


class DummyLoginFlow:
    def __init__(self):
        self.started_with = None
        self.continued = False
        self.navigated_to = None
        self.performed_action = None
        self.state = {
            'stage': 'opening_login_page',
            'label': '待登录',
            'message': '还没有真实店小秘会话，应该从官网登录开始。',
            'next_action': '打开官网登录页，填账号密码，进入验证码等待态。',
            'requires_user_action': True,
            'screenshot_url': None,
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
        }

    def get_state(self):
        return self.state

    def start_login(self, username: str, password: str):
        self.started_with = (username, password)
        self.state = {
            'stage': 'waiting_captcha',
            'label': '等待验证码',
            'message': '账号密码已填写，等待用户输入验证码。',
            'next_action': '用户完成验证码后，点击继续登录。',
            'requires_user_action': True,
            'screenshot_url': None,
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
        }
        return self.state

    def continue_login(self):
        self.continued = True
        self.state = {
            'stage': 'login_success',
            'label': '已登录',
            'message': '登录成功，已进入真实店小秘后台。',
            'next_action': '继续进入数据采集与采集箱流程。',
            'requires_user_action': False,
            'screenshot_url': None,
            'page_title': '店小秘首页',
            'page_url': 'https://www.dianxiaomi.com/index.htm',
        }
        return self.state

    def navigate_post_login(self, target: str):
        self.navigated_to = target
        self.state = {
            'stage': 'workflow_navigation',
            'label': '已到达业务页',
            'message': f'已导航到 {target}',
            'next_action': '继续执行当前业务节点。',
            'requires_user_action': False,
            'screenshot_url': f'/artifacts/screenshots/{target}.png',
            'page_title': target,
            'page_url': f'https://www.dianxiaomi.com/{target}',
            'current_nav': target,
        }
        return self.state

    def perform_draft_box_action(
        self,
        action: str,
        note_text: str | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
    ):
        self.performed_action = (action, note_text, product_query, store_name, target_source_urls)
        if action == 'edit':
            self.state = {
                'stage': 'editor_page',
                'label': '已进入编辑界面',
                'message': '已进入真实编辑界面，可继续读取字段与模板映射。',
                'next_action': '继续处理分类引导、属性信息与编辑页字段。',
                'requires_user_action': False,
                'screenshot_url': '/artifacts/screenshots/edit.png',
                'page_title': '店小秘--编辑速卖通产品',
                'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
                'current_nav': 'edit_page',
                'current_action': action,
                'note_text': note_text,
                'editor_sections': ['基本信息', '产品信息', '其他信息'],
                'top_actions': ['保存并移入待发布', '保存', '发布'],
                'detected_fields': ['产品标题', '产品分类', '半托管服务'],
            }
            return self.state
        self.state = {
            'stage': 'draft_box_action',
            'label': '采集箱动作已触发',
            'message': f'已执行 {action}',
            'next_action': '继续验证页面回显或进入下一步。',
            'requires_user_action': False,
            'screenshot_url': f'/artifacts/screenshots/{action}.png',
            'page_title': '速卖通采集箱',
            'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
            'current_nav': 'draft_box',
            'current_action': action,
            'note_text': note_text,
        }
        return self.state


def test_login_browser_is_headed_by_default_on_windows(monkeypatch):
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.delenv('DXM_LOGIN_HEADED', raising=False)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)

    flow = DxmLoginFlow(DummyLiveClient())

    assert flow._is_headless() is False


def test_login_browser_headless_can_be_explicitly_requested(monkeypatch):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)

    flow = DxmLoginFlow(DummyLiveClient())

    assert flow._is_headless() is True


def test_login_start_reports_visible_browser(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')
    monkeypatch.setattr(flow, '_open_login_page_and_fill', lambda username, password: {
        'page_title': '店小秘官网登录页',
        'page_url': 'https://www.dianxiaomi.com/',
        'screenshot_url': '/artifacts/screenshots/dianxiaomi_login_start.png',
        'browser_visible': True,
    })

    state = flow.start_login('demo-user', 'demo-pass')

    assert state['stage'] == 'waiting_captcha'
    assert state['browser_visible'] is True


def test_login_start_and_continue_are_dispatched_on_same_thread(monkeypatch):
    class ThreadRecordingLoginFlow:
        def __init__(self):
            self.calls: list[tuple[str, int]] = []
            self.started = threading.Event()

        def get_state(self):
            return {'stage': 'waiting_captcha'}

        def start_login(self, username: str, password: str):
            self.calls.append(('start', threading.get_ident()))
            self.started.set()
            time.sleep(0.15)
            return {'stage': 'waiting_captcha'}

        def continue_login(self):
            self.calls.append(('continue', threading.get_ident()))
            return {'stage': 'login_success'}

    flow = ThreadRecordingLoginFlow()
    monkeypatch.setattr(main_module, 'login_flow', flow)

    start_thread = threading.Thread(
        target=lambda: main_module.dxm_login_start(LoginStartRequest(username='u', password='p'))
    )
    continue_thread = threading.Thread(
        target=lambda: main_module.dxm_login_continue(LoginContinueRequest(confirm=True))
    )

    start_thread.start()
    assert flow.started.wait(timeout=2)
    continue_thread.start()
    start_thread.join(timeout=2)
    continue_thread.join(timeout=2)

    assert not start_thread.is_alive()
    assert not continue_thread.is_alive()
    assert [name for name, _ in flow.calls] == ['start', 'continue']
    assert flow.calls[0][1] == flow.calls[1][1]


def test_draft_box_target_opens_status_zero_collection_list():
    assert WORKFLOW_TARGETS['draft_box']['url'].endswith('/web/smt/smtProductList/draft?status=0')


class DummyPage:
    def __init__(self, text: str):
        self.text = text

    def locator(self, selector: str):
        assert selector == 'body'
        return self

    def inner_text(self, timeout: int = 0):
        return self.text


class DummyLoggedInHomePage:
    url = 'https://www.dianxiaomi.com/web/home'

    def __init__(self):
        self.screenshot_calls = []

    def locator(self, selector: str):
        assert selector == 'body'
        return self

    def inner_text(self, timeout: int = 0):
        return '店小秘 首页 产品 订单 客服 采购 仓库 物流 数据 财务 托管'

    def title(self):
        return '店小秘--首页'

    def wait_for_timeout(self, timeout):
        return None

    def screenshot(self, path, full_page=True):
        self.screenshot_calls.append((path, full_page))


class DummyCookieContext:
    def cookies(self):
        return [
            {
                'name': 'dxm-session',
                'value': 'session-value',
                'domain': '.dianxiaomi.com',
                'path': '/',
            }
        ]


class DummyDraftPage:
    url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft'

    def __init__(self, row_info):
        self.row_info = row_info

    def goto(self, *args, **kwargs):
        return None

    def title(self):
        return '店小秘--速卖通产品'

    def wait_for_timeout(self, timeout):
        return None

    def screenshot(self, path, full_page=True):
        return None

    def evaluate(self, script, arg=None):
        if isinstance(arg, list):
            return {
                'ready': True,
                'ready_term': arg[0] if arg else None,
                'loading': False,
                'rows': 1,
                'inputs': 1,
                'text_excerpt': '标题/产品ID 搜索内容',
            }
        if 'rowIndex:picked.idx' in script:
            return self.row_info
        return None


class DummyHudContext:
    def __init__(self):
        self.handlers = {}
        self.init_scripts = []

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event_name, callback):
        self.handlers.setdefault(event_name, []).append(callback)

    def emit(self, event_name, *args):
        for callback in self.handlers.get(event_name, []):
            callback(*args)


class DummyHudPage:
    def __init__(self, context=None):
        self.url = 'https://www.dianxiaomi.com/web/home'
        self.context = context
        self.init_scripts = []
        self.evaluations = []
        self.hud_payloads = []
        self.goto_calls = []
        self.handlers = {}

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event_name, callback):
        self.handlers.setdefault(event_name, []).append(callback)

    def emit(self, event_name, *args):
        for callback in self.handlers.get(event_name, []):
            callback(*args)

    def evaluate(self, script, arg=None):
        self.evaluations.append((script, arg))
        if isinstance(arg, dict) and arg.get('state'):
            self.hud_payloads.append(arg)
        return None

    def goto(self, url, *, wait_until, timeout):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url
        self.hud_payloads.clear()

    def title(self):
        return '店小秘--测试页'


def test_live_browser_hud_reapplies_after_navigation():
    flow = DxmLoginFlow(DummyLiveClient())
    page = DummyHudPage()
    flow._page = page

    result = flow.update_live_hud({
        'state': 'SAVE_ONLY',
        'human_title': '正在只保存',
        'human_action': '只点击保存，不发布',
    })
    assert result['updated'] is True
    assert page.hud_payloads[-1]['state'] == 'SAVE_ONLY'

    flow._goto_with_live_hud(
        page,
        'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0',
        wait_until='domcontentloaded',
        timeout=45000,
    )

    assert page.goto_calls[-1][0].endswith('/web/smt/smtProductList/draft?status=0')
    assert page.hud_payloads[-1]['state'] == 'SAVE_ONLY'
    assert page.hud_payloads[-1]['human_action'] == '只点击保存，不发布'


def test_live_browser_hud_reapplies_to_new_page_from_cached_state():
    flow = DxmLoginFlow(DummyLiveClient())
    old_page = DummyHudPage()
    new_page = DummyHudPage()
    flow._page = old_page

    flow.update_live_hud({
        'state': 'OPEN_EDIT_PAGE',
        'human_title': '正在打开编辑页',
        'human_action': '进入采集箱商品编辑页',
    })
    flow._reapply_live_hud_if_available(new_page)

    assert new_page.hud_payloads[-1]['state'] == 'OPEN_EDIT_PAGE'
    assert new_page.hud_payloads[-1]['human_title'] == '正在打开编辑页'


def test_live_browser_hud_reinjects_on_page_events_and_new_pages():
    flow = DxmLoginFlow(DummyLiveClient())
    context = DummyHudContext()
    page = DummyHudPage(context=context)
    flow._page = page

    flow.update_live_hud({
        'state': 'CLAIM_TO_COLLECTION_BOX',
        'human_title': '正在认领到采集箱',
        'human_action': '从数据采集认领商品',
    })

    assert 'framenavigated' in page.handlers
    assert 'domcontentloaded' in page.handlers
    assert 'page' in context.handlers

    page.hud_payloads.clear()
    page.emit('framenavigated')
    assert page.hud_payloads[-1]['state'] == 'CLAIM_TO_COLLECTION_BOX'

    page.hud_payloads.clear()
    page.emit('domcontentloaded')
    assert page.hud_payloads[-1]['human_action'] == '从数据采集认领商品'

    new_page = DummyHudPage(context=context)
    context.emit('page', new_page)
    assert 'framenavigated' in new_page.handlers
    assert new_page.hud_payloads[-1]['human_title'] == '正在认领到采集箱'


def test_live_browser_hud_caches_status_before_page_exists():
    flow = DxmLoginFlow(DummyLiveClient())
    result = flow.update_live_hud({
        'state': 'OPEN_DATA_ACQUISITION',
        'human_title': '正在打开数据采集',
        'human_action': '进入店小秘数据采集页',
    })
    assert result['updated'] is False
    assert result['reason'] == 'live_browser_page_missing'

    page = DummyHudPage()
    flow._reapply_live_hud_if_available(page)

    assert page.hud_payloads[-1]['state'] == 'OPEN_DATA_ACQUISITION'
    assert page.hud_payloads[-1]['human_action'] == '进入店小秘数据采集页'


class DummyClaimMarkDraftPage(DummyDraftPage):
    def __init__(self):
        super().__init__({'ok': False, 'matches': []})
        self.find_arg = None

    def evaluate(self, script, arg=None):
        if 'rowIndex:picked.idx' in script:
            self.find_arg = arg
            if arg.get('claimMark') == 'AI认领-19-31':
                return {
                    'ok': True,
                    'rowIndex': 4,
                    'rowText': 'Hazbin Hotel Alastor Acrylic Stand Keychain 备注:AI认领-19-31 「Dang Kang」 编辑 更多',
                    'actions': [{'txt': '编辑', 'tag': 'A', 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}],
                }
            return {'ok': False, 'matches': []}
        return super().evaluate(script, arg)


class DummySourceUrlDraftPage(DummyDraftPage):
    def __init__(self):
        super().__init__({'ok': False, 'matches': []})
        self.find_arg = None

    def evaluate(self, script, arg=None):
        if 'rowIndex:picked.idx' in script:
            self.find_arg = arg
            if arg.get('targetSourceUrls') == ['https://detail.1688.com/offer/1013604102950.html']:
                return {
                    'ok': True,
                    'rowIndex': 1,
                    'rowText': '1688 Hazbin Hotel Alastor Acrylic Stand Keychain Colorful Bag Pendant Card 「Dang Kang」 编辑 更多',
                    'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
                    'actions': [{'txt': '编辑', 'tag': 'A', 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}],
                    'matchedBy': 'source_url',
                }
            return {'ok': False, 'matches': []}
        return super().evaluate(script, arg)


def _is_dismiss_blocking_modals_script(script):
    return isinstance(script, str) and 'notice-list-modal' in script and 'guide-overlay' in script


def _is_visible_blocking_modal_state_script(script):
    return isinstance(script, str) and '__DXM_BLOCKING_MODAL_STATE__' in script


class DummySemiPage:
    url = 'https://www.dianxiaomi.com/web/smt/semi?id=123'

    def __init__(self, save_result):
        self.save_result = save_result

    def title(self):
        return '半托管信息'

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        return self.save_result

    def wait_for_timeout(self, timeout):
        return None

    def screenshot(self, path, full_page=True):
        return None


class DummySaveOnlyScriptPage(DummySemiPage):
    def __init__(self):
        super().__init__({'ok': False, 'reason': '命中发布按钮：立即发布', 'published': False})
        self.script = ''

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        self.script = script
        return self.save_result


class DummySemiManagedFieldsPage(DummySemiPage):
    def __init__(self):
        super().__init__({})
        self.script = ''
        self.values = None

    def evaluate(self, script, arg=None):
        self.script = script
        self.values = arg
        return {
            'product_price': True,
            'weight': True,
            'length': True,
            'width': True,
            'height': True,
            'stock': True,
            'field_details': {
                'product_price': {'ok': True, 'located': True, 'strategy': 'column_header', 'value_before': '48.62', 'value_after': '48.62', 'accepted_existing': True},
                'weight': {'ok': True, 'located': True, 'strategy': 'column_header', 'value_before': '0.03', 'value_after': '0.03'},
                'stock': {'ok': True, 'located': True, 'strategy': 'column_header', 'value_before': '0', 'value_after': '100'},
            },
        }


class DummyEditorVariantsLogisticsOnlyPage(DummySemiPage):
    def __init__(self):
        super().__init__({})

    def evaluate(self, script, arg=None):
        return {
            'ok': False,
            'missing': ['logistics_attribute'],
            'declared_value': {'matched': 1, 'filled': 1},
            'stock': {'matched': 1, 'filled': 1},
            'weight': {'matched': 1, 'filled': 1},
            'length': {'matched': 1, 'filled': 1},
            'width': {'matched': 1, 'filled': 1},
            'height': {'matched': 1, 'filled': 1},
            'logistics_attribute_visible': False,
            'variant_scope_found': True,
        }


class DummyEditorVariantsWithLogisticsIconsPage(DummySemiPage):
    def __init__(self):
        super().__init__({})

    def evaluate(self, script, arg=None):
        return {
            'ok': True,
            'missing': [],
            'declared_value': {'matched': 6, 'filled': 6},
            'stock': {'matched': 6, 'filled': 6},
            'weight': {'matched': 6, 'filled': 6},
            'length': {'matched': 6, 'filled': 6},
            'width': {'matched': 6, 'filled': 6},
            'height': {'matched': 6, 'filled': 6},
            'logistics_attribute_visible': True,
            'logistics_icon_count': 6,
            'variant_scope_found': True,
        }


class DummySaveOnlyVerifyPage(DummySemiPage):
    def __init__(self, verify_result):
        super().__init__({'ok': True, 'clicked': True, 'message': '已点击保存', 'published': False})
        self.verify_result = verify_result
        self.evaluate_calls = 0

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return self.save_result
        return self.verify_result


class DummyNetworkResponse:
    url = 'https://www.dianxiaomi.com/api/smt/product/save'
    status = 200

    @property
    def request(self):
        class Request:
            method = 'POST'

        return Request()

    def json(self):
        return {'code': 0, 'msg': '产品已保存到「待发布」'}


class DummySaveOnlyNetworkPage(DummySemiPage):
    def __init__(self):
        super().__init__({'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}, 'published': False})
        self.evaluate_calls = 0
        self.response_handler = None
        self.clicks = []

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicks.append((x, y))
        if self.response_handler:
            self.response_handler(DummyNetworkResponse())

    def on(self, event, handler):
        assert event == 'response'
        self.response_handler = handler

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return self.save_result
        return {
            'ok': False,
            'clicked': True,
            'reason': '未检测到保存成功提示',
            'success_text': None,
            'published': False,
        }


class DummyDangerousModalPage:
    def evaluate(self, script, arg=None):
        self.script = script
        return {'visible': True, 'dangerous': True, 'reason': '检测到危险弹窗：确认发布'}


class DummyGuideOverlayPage:
    def __init__(self):
        self.clicked = False

    def evaluate(self, script, arg=None):
        if self.clicked:
            return {'visible': False}
        return {
            'visible': True,
            'clicked': 'guide:跳过',
            'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40},
            'text': '安装店小秘采集插件 1/5 下一步 跳过',
        }

    def wait_for_timeout(self, timeout):
        return None


class DummyImportantReminderModalPage:
    def __init__(self):
        self.clicked = False

    def evaluate(self, script, arg=None):
        if self.clicked:
            return {'visible': False}
        return {
            'visible': True,
            'clicked': '忽略提示',
            'rect': {'x': 983, 'y': 315, 'w': 72, 'h': 15},
            'text': '重要提醒 您购买的 图片空间 将在2天后 过期，超出的图片空间将被冻结 查看详情 >> 忽略提示',
        }

    def wait_for_timeout(self, timeout):
        return None


class DummyReminderDropdownPage:
    def __init__(self):
        self.clicked = False

    def evaluate(self, script, arg=None):
        if self.clicked:
            return {'visible': False}
        return {
            'visible': True,
            'clicked': 'dropdown:2天内不提示',
            'rect': {'x': 1000, 'y': 345, 'w': 90, 'h': 24},
            'text': '关闭提示 2天内不提示',
        }

    def wait_for_timeout(self, timeout):
        return None


class DummyPersistentModalUntilEscapePage:
    def __init__(self):
        self.closed = False
        self.clicks = []
        self.presses = []
        self.keyboard = self

    def evaluate(self, script, arg=None):
        if self.closed:
            return {'visible': False}
        return {
            'visible': True,
            'clicked': 'modal-close',
            'rect': {'x': 120, 'y': 20, 'w': 24, 'h': 24},
            'text': '距离活动结束仅剩 我知道了',
        }

    def press(self, key):
        self.presses.append(key)
        if key == 'Escape':
            self.closed = True

    def wait_for_timeout(self, timeout):
        return None


class DummyReadyWaitPage:
    def __init__(self):
        self.ready_calls = 0
        self.dismiss_calls = 0

    def evaluate(self, script, arg=None):
        if arg is None:
            self.dismiss_calls += 1
            return {'visible': False}
        self.ready_calls += 1
        if self.ready_calls == 1:
            return {
                'ready': False,
                'loading': True,
                'rows': 0,
                'inputs': 0,
                'text_excerpt': 'LOADING',
                'url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
                'title': '',
            }
        return {
            'ready': True,
            'ready_term': '标题/产品ID',
            'loading': False,
            'rows': 2,
            'inputs': 3,
            'text_excerpt': '标题/产品ID 搜索内容',
            'url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
            'title': '店小秘--速卖通产品',
        }

    def wait_for_timeout(self, timeout):
        return None


class DummyNoteVerifyScriptPage:
    url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft'

    def __init__(self, menu_label='备注'):
        self.evaluate_calls = 0
        self.verify_script = ''
        self.note_visible_after_search = False
        self.menu_label = menu_label

    def wait_for_timeout(self, timeout):
        return None

    def evaluate(self, script, arg=None):
        self.evaluate_calls += 1
        if 'safeRemark' in script:
            return {'ok': True, 'text': self.menu_label, 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}
        if 'li.ant-dropdown-menu-item' in script:
            return {'ok': True, 'text': self.menu_label, 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}
        if '未找到备注弹窗' in script:
            return {'ok': True}
        if 'rowTexts' in script:
            self.verify_script = script
            return {'verified': False, 'rowText': '目标行未写入备注'}
        if 'claim_mark_store_search' in script:
            if self.note_visible_after_search:
                return {
                    'verified': True,
                    'rowText': '1688 Anime Peripherals Ron Weasley Figurine 备注:AI认领-47-514 「Dang Kang」 编辑 更多',
                    'verifiedBy': 'claim_mark_store_search',
                }
            return {'verified': False, 'rowText': '', 'matchCount': 0, 'verifiedBy': 'claim_mark_store_search'}
        return None


class DummyOpenSemiPage(DummySemiPage):
    url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def __init__(self):
        super().__init__(True)

    def title(self):
        return '店小秘--编辑速卖通产品'

    def goto(self, url, **kwargs):
        self.url = url


class DummyProductMainImagesPage(DummyOpenSemiPage):
    def __init__(self, images):
        super().__init__()
        self.images = images
        self.actions = []

    def evaluate(self, script, arg=None):
        if 'dangerousTerms' in script:
            return {'visible': False}
        if 'first_invalid_delete' in script:
            return None
        if 'clicked_invalid' in script:
            clicked_invalid = []
            for image in self.images:
                if image['checked'] and not image['valid']:
                    image['checked'] = False
                    clicked_invalid.append({'index': image['index'], 'text': image['text']})
            valid_count = sum(1 for image in self.images if image['valid'])
            target = min(2, max(1, valid_count))
            selected_valid = sum(1 for image in self.images if image['checked'] and image['valid'])
            clicked_valid = []
            for image in self.images:
                if selected_valid >= target:
                    break
                if image['valid'] and not image['checked']:
                    image['checked'] = True
                    selected_valid += 1
                    clicked_valid.append({'index': image['index'], 'text': image['text']})
            action = {'found': True, 'clicked_invalid': clicked_invalid, 'clicked_valid': clicked_valid}
            self.actions.append(action)
            return action
        if 'productMainImgModule' in script:
            selected_invalid = [image for image in self.images if image['checked'] and not image['valid']]
            selected_valid = [image for image in self.images if image['checked'] and image['valid']]
            valid_images = [image for image in self.images if image['valid']]
            return {
                'found': True,
                'total': len(self.images),
                'valid_count': len(valid_images),
                'selected_valid_count': len(selected_valid),
                'selected_invalid_count': len(selected_invalid),
                'selected_invalid': selected_invalid,
                'selected_valid': selected_valid,
                'images': self.images,
            }
        return super().evaluate(script, arg)


class DummyMediaNoEntryPage:
    url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def __init__(self):
        self.scripts = []
        self.timeouts = []

    def title(self):
        return '店小秘--编辑速卖通产品'

    def evaluate(self, script, arg=None):
        self.scripts.append(script)
        if '欧盟外包装图槽位仍为空' in script:
            return {'ok': False, 'reason': '欧盟外包装图槽位仍为空'}
        if '欧盟外包装图槽位没有可点击的图片选择入口' in script:
            return {'ok': False, 'reason': '欧盟外包装图槽位没有可点击的图片选择入口'}
        if 'const modal = Array.from' in script and 'dangerousTerms' in script:
            return {'visible': False}
        return {'ok': False, 'reason': 'unexpected script'}

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)

    def screenshot(self, path, full_page=True):
        return None


class DummyMarketingGeneratePage:
    def __init__(self):
        self.timeouts = []
        self.clicked = []

    def evaluate(self, script, arg=None):
        return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}, 'text': '一键生成'}

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicked.append((x, y))


class DummyMarketingWhiteBackgroundDialogOpenerPage:
    def __init__(self):
        self.evaluate_calls = 0
        self.timeouts = []
        self.clicked = []
        self.scripts = []

    def evaluate(self, script, arg=None):
        self.scripts.append(script)
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return {'ok': True, 'trigger_rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
        return {'ok': True, 'item_rect': {'x': 50, 'y': 60, 'w': 70, 'h': 80}, 'text': '图片白底'}

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicked.append((x, y))


class DummyImageSlotPickerScriptPage(DummyMediaNoEntryPage):
    def __init__(self):
        super().__init__()
        self.script = ''

    def evaluate(self, script, arg=None):
        self.script = script
        return {'ok': False, 'reason': 'stop after script capture'}


class DummyBankMenuScriptPage(DummyMediaNoEntryPage):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.ready_after_missing_menu = False

    def evaluate(self, script, arg=None):
        if 'dangerousTerms' in script:
            self.scripts.append(script)
            return {'visible': False}
        self.calls += 1
        self.scripts.append(script)
        if self.calls == 1:
            return {'ok': False, 'reason': '未看到图片银行（速卖通）菜单'}
        if self.ready_after_missing_menu:
            return {'ok': True, 'text': '从图片银行选择'}
        return {'ok': False, 'reason': '图片银行弹窗未打开'}


class DummyImageSlotFlowPage(DummyMediaNoEntryPage):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.clicked = []

    def evaluate(self, script, arg=None):
        self.calls += 1
        self.scripts.append(script)
        if 'dangerousTerms' in script:
            return {'visible': False}
        if self.calls == 1:
            return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
        if 'hasBankMenu' in script:
            return {'ok': True, 'has_bank_menu': True, 'has_image_dialog': False}
        if 'requireMenu' in script:
            return {'ok': True, 'text': '图片银行（速卖通）'}
        if '图片银行弹窗未打开' in script:
            return {'ok': True, 'text': '从图片银行选择'}
        return {'ok': False, 'reason': 'unexpected script'}

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicked.append((x, y))


class DummyMarketingGeometryScriptPage(DummyMarketingWhiteBackgroundDialogOpenerPage):
    def evaluate(self, script, arg=None):
        self.scripts.append(script)
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return {'ok': True, 'trigger_rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
        return {'ok': False, 'reason': 'stop after scoped menu script capture'}


class DummyWhiteBackgroundMissingDialogPage:
    def __init__(self):
        self.calls = 0
        self.clicked = []
        self.timeouts = []

    def evaluate(self, script, arg=None):
        self.calls += 1
        if self.calls == 1:
            return {'ok': True, 'skipped': True, 'reason': '未出现图片白底弹窗'}
        if self.calls == 2:
            return {'ok': True, 'trigger_rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
        if self.calls == 3:
            return {'ok': True, 'text': '图片白底', 'item_rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
        return {'ok': True, 'skipped': True, 'reason': '未出现图片白底弹窗'}

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicked.append((x, y))

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)


class DummyImageBankNoSearchInputPage:
    def __init__(self):
        self.clicked = []
        self.timeouts = []

    def evaluate(self, script, arg=None):
        if '图片银行未找到可输入图片名称的搜索框' in script:
            return {'ok': False, 'reason': '图片银行未找到可输入图片名称的搜索框'}
        return {'ok': False, 'reason': 'unexpected script'}


class DummySafeModalPage:
    def __init__(self, result):
        self.results = list(result) if isinstance(result, list) else [result]
        self.clicked = []

    def evaluate(self, script, arg=None):
        self.script = script
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]

    def wait_for_timeout(self, timeout):
        return None

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicked.append((x, y))


class DummyMouse:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))


class DummyKeyboard:
    def __init__(self):
        self.presses = []

    def press(self, key):
        self.presses.append(key)


class DummyCustomsPage:
    def __init__(self):
        self.evaluate_calls = 0
        self.waited_for_function = False
        self.timeouts = []
        self.mouse = DummyMouse()
        self.keyboard = DummyKeyboard()

    def evaluate(self, script, arg=None):
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return {'ok': False}
        if self.evaluate_calls == 2:
            return {'ok': True, 'candidates': 1, 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}
        if self.evaluate_calls == 3:
            return {
                'text': '种类(Kind): 请选择 取消 确定',
                'select_rect': {'x': 10, 'y': 20, 'w': 100, 'h': 30},
                'confirm_rect': {'x': 20, 'y': 30, 'w': 40, 'h': 20},
                'is_product_name_step': False,
            }
        if self.evaluate_calls == 4:
            return {
                'text': '品名(Product name): 钥匙扣(keychain) 取消 确定',
                'select_rect': {'x': 10, 'y': 20, 'w': 100, 'h': 30},
                'confirm_rect': {'x': 20, 'y': 30, 'w': 40, 'h': 20},
                'is_product_name_step': True,
            }
        if self.evaluate_calls == 5:
            return {
                'text': '品名(Product name): 钥匙扣(keychain) 税率代码 3926909989 取消 确定',
                'select_rect': None,
                'confirm_rect': {'x': 20, 'y': 50, 'w': 40, 'h': 20},
                'is_product_name_step': True,
            }
        if self.evaluate_calls == 6:
            return None
        return {
            'ok': True,
            'modal_still_open': False,
            'has_tax_code': True,
            'has_product_name': True,
            'select_error': False,
        }

    def wait_for_function(self, *args, **kwargs):
        self.waited_for_function = True

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)


class DummyConfiguredCustomsPage:
    def __init__(self):
        self.script = ''
        self.mouse = DummyMouse()
        self.keyboard = DummyKeyboard()

    def evaluate(self, script, arg=None):
        self.script = script
        return {
            'ok': True,
            'has_tax_code': True,
            'has_kind': True,
            'has_customs_area': True,
            'body_excerpt': '海关监管属性 添加全球海关监管属性 税率代码 3926400090 种类: 其他 更新海关监管',
        }


class DummyEnglishCustomsUpdatePage:
    def __init__(self):
        self.script = ''
        self.scripts = []
        self.mouse = DummyMouse()
        self.keyboard = DummyKeyboard()
        self.timeouts = []

    def evaluate(self, script, arg=None):
        self.script = script
        self.scripts.append(script)
        if 'dangerousTerms' in script:
            return {'visible': False}
        return {
            'ok': True,
            'has_tax_code': True,
            'has_product_name': True,
            'has_kind': False,
            'has_customs_area': True,
            'select_error': False,
            'product_name_value': 'ACGDecoration',
            'kind_value': '',
            'update_rect': {'x': 370, 'y': 607, 'w': 214, 'h': 32},
            'body_excerpt': '海关监管属性 添加全球海关监管属性 税率代码 8306210000 Product name: ACG Decoration 更新海关监管',
        }

    def wait_for_timeout(self, timeout):
        self.timeouts.append(timeout)


def test_login_start_returns_waiting_captcha(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)

    client = TestClient(app)
    response = client.post('/api/dxm/login/start', json={'username': 'demo-user', 'password': 'demo-pass'})

    assert response.status_code == 200
    data = response.json()
    assert flow.started_with == ('demo-user', 'demo-pass')
    assert data['stage'] == 'waiting_captcha'
    assert data['requires_user_action'] is True


def test_login_start_is_not_blocked_by_l2_gate(monkeypatch):
    import src.main as main

    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "failed"})

    client = TestClient(app)
    response = client.post('/api/dxm/login/start', json={'username': 'demo-user', 'password': 'demo-pass'})

    assert response.status_code == 200
    assert flow.started_with == ('demo-user', 'demo-pass')
    assert response.json()['requires_user_action'] is True


def test_login_start_returns_recoverable_state_when_browser_runner_crashes(monkeypatch):
    class CrashingLoginFlow(DummyLoginFlow):
        def start_login(self, username: str, password: str):
            raise RuntimeError('Internal Server Error')

    monkeypatch.setattr('src.main.login_flow', CrashingLoginFlow())

    client = TestClient(app)
    response = client.post('/api/dxm/login/start', json={'username': 'demo-user', 'password': 'demo-pass'})

    assert response.status_code == 200
    data = response.json()
    assert data['stage'] == 'login_failed'
    assert data['label'] == '打开失败'
    assert '真实店小秘登录浏览器启动失败' in data['message']
    assert 'Internal Server Error' not in data['message']
    assert data['raw_error'] == 'Internal Server Error'
    assert '关闭旧的 DXM Agent Console 或旧浏览器进程后重试' in data['next_action']
    assert data['requires_user_action'] is True


def test_login_continue_returns_recoverable_state_when_browser_runner_crashes(monkeypatch):
    class CrashingLoginFlow(DummyLoginFlow):
        def continue_login(self):
            raise RuntimeError('Target page, context or browser has been closed')

    monkeypatch.setattr('src.main.login_flow', CrashingLoginFlow())

    client = TestClient(app)
    response = client.post('/api/dxm/login/continue', json={'confirm': True})

    assert response.status_code == 200
    data = response.json()
    assert data['stage'] == 'login_failed'
    assert data['label'] == '检测失败'
    assert '真实店小秘登录态检测失败' in data['message']
    assert '真实浏览器窗口' in data['next_action']
    assert data['requires_user_action'] is True


def test_login_continue_returns_success_state(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)

    client = TestClient(app)
    response = client.post('/api/dxm/login/continue', json={})

    assert response.status_code == 200
    data = response.json()
    assert flow.continued is True
    assert data['stage'] == 'login_success'
    assert data['requires_user_action'] is False


def test_login_state_reads_from_login_flow(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)

    client = TestClient(app)
    response = client.get('/api/dxm/login-state')

    assert response.status_code == 200
    assert response.json()['stage'] == 'opening_login_page'


def test_navigate_endpoint_delegates_to_login_flow(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)

    client = TestClient(app)
    response = client.post('/api/dxm/navigate', json={'target': 'draft_box'})

    assert response.status_code == 200
    data = response.json()
    assert flow.navigated_to == 'draft_box'
    assert data['current_nav'] == 'draft_box'
    assert data['stage'] == 'workflow_navigation'


def test_navigate_endpoint_returns_recoverable_state_when_browser_session_crashes(monkeypatch):
    class CrashingLoginFlow(DummyLoginFlow):
        def navigate_post_login(self, target: str):
            raise RuntimeError('Target page, context or browser has been closed')

    monkeypatch.setattr('src.main.login_flow', CrashingLoginFlow())

    client = TestClient(app)
    response = client.post('/api/dxm/navigate', json={'target': 'draft_box'})

    assert response.status_code == 200
    data = response.json()
    assert data['stage'] == 'workflow_navigation_failed'
    assert data['label'] == '进入失败'
    assert '真实店小秘业务页进入失败' in data['message']
    assert '重新打开真实登录页' in data['next_action']
    assert data['raw_error'] == 'Target page, context or browser has been closed'
    assert data['requires_user_action'] is True


def test_draft_box_action_endpoint_delegates_to_login_flow_after_guard_passes(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/draft-box/action', json={'action': 'remark', 'note_text': 'AI认领'})

    assert response.status_code == 200
    data = response.json()
    assert flow.performed_action == ('remark', 'AI认领', None, None, None)
    assert data['current_action'] == 'remark'
    assert data['note_text'] == 'AI认领'


def test_workflow_check_login_uses_adapter_contract(monkeypatch):
    flow = DummyLoginFlow()
    flow.state = {
        'stage': 'login_success',
        'page_title': '店小秘首页',
        'page_url': 'https://www.dianxiaomi.com/index.htm',
        'screenshot_url': '/artifacts/screenshots/home.png',
    }
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))

    client = TestClient(app)
    response = client.get('/api/dxm/workflow/check-login')

    assert response.status_code == 200
    data = response.json()
    assert data['ok'] is True
    assert data['action'] == 'check_login_state'
    assert data['evidence']['stage'] == 'login_success'


def test_workflow_open_draft_box_uses_adapter_contract(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))

    client = TestClient(app)
    response = client.post('/api/dxm/workflow/open-draft-box')

    assert response.status_code == 200
    data = response.json()
    assert flow.navigated_to == 'draft_box'
    assert data['ok'] is True
    assert data['action'] == 'open_draft_box'
    assert data['evidence']['current_nav'] == 'draft_box'


def test_workflow_claim_product_uses_adapter_contract_after_guard_passes(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    source_urls = ['https://detail.1688.com/offer/1013604102950.html']
    response = client.post(
        '/api/dxm/workflow/claim-product',
        json={'action': 'remark', 'note_text': 'AI认领-1', 'target_source_urls': source_urls},
    )

    assert response.status_code == 200
    data = response.json()
    assert flow.performed_action == ('remark', 'AI认领-1', None, None, source_urls)
    assert data['action'] == 'claim_product'
    assert data['evidence']['note_text'] == 'AI认领-1'


def test_workflow_open_editor_uses_adapter_contract_after_guard_passes(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/workflow/open-editor')

    assert response.status_code == 200
    data = response.json()
    assert flow.performed_action == ('edit', None, None, None, None)
    assert data['action'] == 'open_editor'
    assert data['evidence']['stage'] == 'editor_page'


def test_edit_action_endpoint_returns_editor_page_after_guard_passes(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/draft-box/action', json={'action': 'edit'})

    assert response.status_code == 200
    data = response.json()
    assert flow.performed_action == ('edit', None, None, None, None)
    assert data['stage'] == 'editor_page'
    assert data['current_nav'] == 'edit_page'
    assert '编辑' in data['page_title']
    assert 'editor_sections' in data
    assert 'top_actions' in data
    assert 'detected_fields' in data


def test_dxm_login_flow_start_persists_browser_snapshot(monkeypatch, tmp_path):
    live_client = DummyLiveClient()
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    def fake_open_login_page(username: str, password: str):
        return {
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
            'screenshot_url': '/artifacts/screenshots/login.png',
        }

    monkeypatch.setattr(flow, '_open_login_page_and_fill', fake_open_login_page)

    state = flow.start_login('master', 'secret-123')

    assert state['stage'] == 'waiting_captcha'
    assert state['screenshot_url'] == '/artifacts/screenshots/login.png'
    assert state['password_mask'] == 's********3'
    assert Path(tmp_path / 'runtime.json').exists()


def test_dxm_login_flow_start_failure_keeps_open_browser_for_recovery(monkeypatch, tmp_path):
    live_client = DummyLiveClient()
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []
    flow._page = DummyHudPage()

    monkeypatch.setattr(flow, '_open_login_page_and_fill', lambda username, password: (_ for _ in ()).throw(RuntimeError('login form changed')))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.start_login('master', 'secret-123')

    assert state['stage'] == 'login_failed'
    assert state['requires_user_action'] is True
    assert state['browser_visible'] is True
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_dxm_login_flow_continue_records_login_failure(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘官网登录页',
        'page_url': 'https://www.dianxiaomi.com/',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))

    state = flow.continue_login()

    assert live_client.probed is True
    assert state['stage'] == 'login_failed'
    assert state['requires_user_action'] is True
    assert state['screenshot_url'] == '/artifacts/screenshots/login-result.png'
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_dxm_login_flow_continue_exception_keeps_visible_browser_for_recovery(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: (_ for _ in ()).throw(RuntimeError('captcha still pending')))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert state['stage'] == 'login_failed'
    assert state['requires_user_action'] is True
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert '重新打开官网登录页' in state['next_action']
    assert close_calls == []


def test_dxm_login_flow_continue_success_keeps_visible_browser_for_next_steps(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert state['stage'] == 'login_success'
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert '数据采集' in state['next_action']
    assert '采集箱' in state['next_action']
    assert close_calls == []


def test_submit_login_after_captcha_accepts_already_logged_in_visible_home(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=False)
    live_client.cookie_file = tmp_path / 'cookies.json'
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyLoggedInHomePage()
    flow._context = DummyCookieContext()

    monkeypatch.setattr(flow, '_ensure_page', lambda: page)
    monkeypatch.setattr(flow, '_click_first_available', lambda *args, **kwargs: pytest.fail('should not click login controls when page is already logged in'))

    state = flow._submit_login_after_captcha()

    assert state['page_title'] == '店小秘--首页'
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert live_client.cookie_file.exists()
    assert 'dxm-session' in live_client.cookie_file.read_text(encoding='utf-8')
    assert page.screenshot_calls


def test_continue_login_uses_visible_home_when_headless_cookie_probe_hits_asyncio_guard(monkeypatch, tmp_path):
    class AsyncioGuardLiveClient(DummyLiveClient):
        def probe_session(self):
            self.probed = True
            raise RuntimeError('It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.')

    live_client = AsyncioGuardLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
        'visible_logged_in': True,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert live_client.probed is True
    assert state['stage'] == 'login_success'
    assert state['requires_user_action'] is False
    assert state['browser_visible'] is True
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert '登录成功' in state['message']
    assert close_calls == []


def test_continue_login_prefers_visible_home_over_stale_cookie_probe(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
        'visible_logged_in': True,
    })
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert live_client.probed is True
    assert state['stage'] == 'login_success'
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'


def test_dxm_login_flow_navigate_updates_runtime_state(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_navigate_in_session', lambda target: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/draft-box.png',
        'target': target,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.navigate_post_login('draft_box')

    assert state['stage'] == 'workflow_navigation'
    assert state['current_nav'] == 'draft_box'
    assert state['screenshot_url'] == '/artifacts/screenshots/draft-box.png'
    assert '采集箱' in state['message']


def test_dxm_login_flow_navigate_keeps_visible_browser_for_operator(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_navigate_in_session', lambda target: {
        'page_title': '数据采集',
        'page_url': 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
        'screenshot_url': '/artifacts/screenshots/data-acquisition.png',
        'target': target,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.navigate_post_login('data_acquisition')

    assert state['stage'] == 'workflow_navigation'
    assert state['current_nav'] == 'data_acquisition'
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_dxm_login_flow_navigation_failure_keeps_visible_browser_for_recovery(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_navigate_in_session', lambda target: (_ for _ in ()).throw(RuntimeError('page changed')))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.navigate_post_login('data_acquisition')

    assert state['stage'] == 'workflow_navigation_failed'
    assert state['requires_user_action'] is True
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_dxm_login_flow_perform_draft_box_action_updates_state(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/remark.png',
        'action': action,
        'note_text': note_text,
        'product_query': product_query,
        'store_name': store_name,
        'note_verified': True,
        'target_row_text': '崩坏3钥匙扣爱莉希雅 备注: AI认领',
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_draft_box_action('remark', note_text='AI认领', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert state['stage'] == 'draft_box_action'
    assert state['current_nav'] == 'draft_box'
    assert state['current_action'] == 'remark'
    assert state['note_text'] == 'AI认领'
    assert state['product_query'] == '崩坏3钥匙扣'
    assert state['store_name'] == 'Dang Kang'
    assert state['note_verified'] is True
    assert '备注: AI认领' in state['target_row_text']


def test_dxm_login_flow_perform_draft_box_action_keeps_browser_session_on_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/remark.png',
        'action': action,
        'note_text': note_text,
        'note_verified': True,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))

    state = flow.perform_draft_box_action('remark', note_text='AI认领')

    assert state['stage'] == 'draft_box_action'
    assert close_calls == []


def test_dxm_login_flow_edit_action_enters_editor_page(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None: {
        'page_title': '店小秘--编辑速卖通产品',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123456',
        'screenshot_url': '/artifacts/screenshots/edit.png',
        'action': action,
        'note_text': note_text,
        'product_query': product_query,
        'store_name': store_name,
        'target_row_text': '崩坏3钥匙扣爱莉希雅',
        'editor_sections': ['基本信息', '店小秘信息', '其他信息'],
        'top_actions': ['保存并移入待发布', '保存', '发布'],
        'detected_fields': ['产品标题', '产品分类', '半托管服务'],
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_draft_box_action('edit', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert state['stage'] == 'editor_page'
    assert state['current_nav'] == 'edit_page'
    assert state['current_action'] == 'edit'
    assert state['product_query'] == '崩坏3钥匙扣'
    assert state['store_name'] == 'Dang Kang'
    assert state['target_row_text'] == '崩坏3钥匙扣爱莉希雅'
    assert '编辑' in state['page_title']
    assert '其他信息' in state['editor_sections']
    assert '发布' in state['top_actions']
    assert '半托管服务' in state['detected_fields']


def test_ensure_page_replaces_closed_page_in_existing_context(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class ClosedPage:
        def is_closed(self):
            return True

    class OpenPage:
        def is_closed(self):
            return False

    class OpenContext:
        def __init__(self):
            self.created_pages = []

        def is_closed(self):
            return False

        def new_page(self):
            page = OpenPage()
            self.created_pages.append(page)
            return page

    context = OpenContext()
    flow._page = ClosedPage()
    flow._context = context
    flow._browser = object()

    page = flow._ensure_page()

    assert isinstance(page, OpenPage)
    assert page is flow._page
    assert context.created_pages == [page]


def test_ensure_page_recreates_context_when_previous_context_closed(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class ClosedPage:
        def is_closed(self):
            return True

    class ClosedContext:
        def is_closed(self):
            return True

    class OpenPage:
        pass

    class OpenContext:
        def __init__(self):
            self.created_pages = []

        def is_closed(self):
            return False

        def new_page(self):
            page = OpenPage()
            self.created_pages.append(page)
            return page

    class ConnectedBrowser:
        def __init__(self):
            self.contexts = []

        def is_connected(self):
            return True

        def new_context(self, **kwargs):
            context = OpenContext()
            context.kwargs = kwargs
            self.contexts.append(context)
            return context

    browser = ConnectedBrowser()
    flow._page = ClosedPage()
    flow._context = ClosedContext()
    flow._browser = browser
    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: pytest.fail('should reuse connected browser'))

    page = flow._ensure_page()

    assert isinstance(page, OpenPage)
    assert flow._context is browser.contexts[0]
    assert browser.contexts[0].created_pages == [page]
    assert browser.contexts[0].kwargs['ignore_https_errors'] is True


def test_extract_editor_page_meta_reads_sections_buttons_and_fields(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyPage('基本信息 店小秘信息 其他信息 保存并移入待发布 保存 发布 产品标题 产品分类 半托管服务 欧盟责任人')

    meta = flow._extract_editor_page_meta(page)

    assert meta['sections'] == ['基本信息', '店小秘信息', '其他信息']
    assert meta['top_actions'] == ['保存并移入待发布', '保存', '发布']
    assert meta['fields'] == ['产品标题', '产品分类', '半托管服务', '欧盟责任人']


def test_dxm_login_flow_remark_action_reports_missing_target(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: DummyDraftPage({'ok': False, 'matches': []}))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_draft_box_action('remark', note_text='AI认领', product_query='不存在')

    assert state['stage'] == 'draft_box_action_failed'
    assert '未找到目标商品行' in state['message']


def test_dxm_login_flow_draft_box_action_failure_keeps_visible_browser_for_recovery(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('target row missing')))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.perform_draft_box_action('remark', note_text='AI-OPS', product_query='真实商品')

    assert state['stage'] == 'draft_box_action_failed'
    assert state['requires_user_action'] is True
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_remark_action_treats_existing_note_as_verified(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    row = {
        'ok': True,
        'rowIndex': 1,
        'rowText': 'Hazbin Hotel Alastor Acrylic Stand 备注:AI认领-19-31 「Dang Kang」 编辑 更多',
        'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}}],
    }

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: DummyDraftPage(row))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)
    monkeypatch.setattr(flow, '_add_note_to_draft_row', lambda *args, **kwargs: pytest.fail('existing note should not be rewritten'))

    state = flow.perform_draft_box_action(
        'remark',
        note_text='AI认领-19-31',
        product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
        store_name='Dang Kang',
    )

    assert state['stage'] == 'draft_box_action'
    assert state['note_verified'] is True
    assert state['target_row_text'] == row['rowText']


def test_find_draft_box_row_blocks_ambiguous_product_match(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDraftPage({'ok': False, 'ambiguous': True, 'matches': [{'rowText': '重复商品A'}, {'rowText': '重复商品B'}]})

    with pytest.raises(RuntimeError, match='目标商品行不唯一'):
        flow._find_draft_box_row(page, product_query='重复商品', store_name='Dang Kang')


def test_find_draft_box_row_can_match_existing_claim_mark_when_title_changed(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyClaimMarkDraftPage()

    row = flow._find_draft_box_row(
        page,
        product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
        store_name='Dang Kang',
        claim_mark='AI认领-19-31',
    )

    assert row['rowIndex'] == 4
    assert page.find_arg['claimMark'] == 'AI认领-19-31'


def test_find_draft_box_row_can_match_source_url_when_title_changed(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySourceUrlDraftPage()

    row = flow._find_draft_box_row(
        page,
        product_query='1688 Anime Peripherals Ron Weasley Figurine Acrylic Keychain Hermione Granger Figure Acrylic Pendant',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert row['rowIndex'] == 1
    assert row['matchedBy'] == 'source_url'
    assert page.find_arg['targetSourceUrls'] == ['https://detail.1688.com/offer/1013604102950.html']


def test_find_draft_box_row_does_not_fallback_when_target_source_url_misses(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button, a { display: inline-block; width: 72px; height: 24px; }
        </style>
      </head>
      <body>
        <table>
          <tbody>
            <tr class="vxe-body--row">
              <td>Visible Matched Title 「Dang Kang」</td>
              <td><a href="https://detail.1688.com/offer/111.html">来源</a></td>
              <td><button>编辑</button><button>更多</button></td>
            </tr>
            <tr class="vxe-body--row">
              <td>Another Product 「Dang Kang」</td>
              <td><a href="https://detail.1688.com/offer/222.html">来源</a></td>
              <td><button>编辑</button><button>更多</button></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        with pytest.raises(RuntimeError, match='未找到目标商品行'):
            flow._find_draft_box_row(
                page,
                product_query='Visible Matched Title',
                store_name='Dang Kang',
                target_source_urls=['https://detail.1688.com/offer/999.html'],
            )
        browser.close()


def test_find_data_acquisition_claim_target_prefers_source_url_when_query_text_misses(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button, a { display: inline-block; width: 96px; height: 24px; }
        </style>
      </head>
      <body>
        <table>
          <tbody>
            <tr class="vxe-body--row">
              <td>店小秘页面标题可能已被平台改写</td>
              <td><a href="https://detail.1688.com/offer/1013604102950.html">来源</a></td>
              <td><button>认领</button></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        row = flow._find_data_acquisition_claim_target(
            page,
            product_query='未指定商品',
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )
        browser.close()

    assert row['ok'] is True
    assert row['matchedBy'] == 'source_url'


def test_data_acquisition_claim_click_safety_allows_claim_button(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button, a { display: inline-block; width: 96px; height: 28px; }
        </style>
      </head>
      <body>
        <section>数据采集 <span>采集箱</span></section>
        <table>
          <tbody>
            <tr class="vxe-body--row">
              <td>真实采集商品</td>
              <td><a href="https://detail.1688.com/offer/1013604102950.html">来源</a></td>
              <td><button>认领</button></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        target = flow._find_data_acquisition_claim_target(
            page,
            product_query='真实采集商品',
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )
        result = flow._assert_data_acquisition_claim_click_safe(page, target)
        browser.close()

    assert result['ok'] is True
    assert '认领' in result['action_text']


def test_data_acquisition_claim_click_safety_blocks_save_button_misclick(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button { display: inline-block; width: 120px; height: 28px; }
        </style>
      </head>
      <body>
        <section>商品编辑页</section>
        <button id="save">保存</button>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        rect = page.locator('#save').bounding_box()
        target = {
            'rowText': '真实采集商品 认领',
            'actionText': '认领',
            'actionRect': {'x': rect['x'], 'y': rect['y'], 'w': rect['width'], 'h': rect['height']},
        }
        with pytest.raises(RuntimeError, match='保存、发布或待发布动作'):
            flow._assert_data_acquisition_claim_click_safe(page, target)
        browser.close()


def test_data_acquisition_claim_click_safety_blocks_forbidden_target_row(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    target = {
        'rowText': '真实采集商品 保存并移入待发布 发布',
        'actionText': '认领',
        'actionRect': {'x': 1, 'y': 1, 'w': 96, 'h': 24},
    }

    with pytest.raises(RuntimeError, match='目标商品行包含保存、发布或待发布动作'):
        flow._assert_data_acquisition_claim_click_safe(None, target)


def test_search_data_acquisition_prefers_target_source_url_input(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    source_url = 'https://detail.1688.com/offer/1013604102950.html'
    html = '''
    <html>
      <head>
        <style>
          input, button { display: inline-block; width: 220px; height: 28px; }
        </style>
      </head>
      <body>
        <section>数据采集 <button>搜索</button></section>
        <input id="title" placeholder="搜索标题或关键词" />
        <input id="source" placeholder="来源链接 / URL" />
        <table><tr><td>认领</td><td>采集箱</td></tr></table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        result = flow._search_data_acquisition(
            page,
            product_query='错误标题不应用于 URL 模式',
            target_source_urls=[source_url],
        )

        title_value = page.locator('#title').input_value()
        source_value = page.locator('#source').input_value()
        browser.close()

    assert result['query_source'] == 'target_source_url'
    assert result['query'] == source_url
    assert source_value == source_url
    assert title_value == ''


def test_data_acquisition_claim_state_keeps_search_and_target_evidence(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    claim_target = {
        'matchedBy': 'source_url',
        'rowText': '真实采集商品行 来源 1013604102950 认领',
        'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
    }
    search_result = {
        'query': 'https://detail.1688.com/offer/1013604102950.html',
        'query_source': 'target_source_url',
        'filled': True,
        'clicked_search': True,
    }

    monkeypatch.setattr(flow, '_perform_data_acquisition_claim', lambda **kwargs: {
        'page_title': '数据采集',
        'page_url': 'https://www.dianxiaomi.com/web/smt/collect/index.htm',
        'screenshot_url': '/artifacts/screenshots/claim.png',
        'message': '已在数据采集页提交认领到采集箱。',
        'target_source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
        'search_result': search_result,
        'claim_target': claim_target,
        'claimed_product': {
            'title': '真实采集商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
    })

    state = flow.claim_from_data_acquisition(
        'AI-OPS-1',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert state['stage'] == 'data_acquisition_claim'
    assert state['search_result']['query_source'] == 'target_source_url'
    assert state['claim_target']['matchedBy'] == 'source_url'
    assert '真实采集商品行' in state['claim_target']['rowText']


def test_draft_box_claim_verification_carries_data_acquisition_target(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claimed_product': {
            'title': '真实采集商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
        'claim_target': {
            'matchedBy': 'source_url',
            'rowText': '真实采集商品行 来源 1013604102950 认领',
            'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
        },
    })
    monkeypatch.setattr(flow, '_verify_draft_box_claim', lambda **kwargs: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/verify.png',
        'target_source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
        'claimed_product': {
            'title': '真实采集商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
            'row_text': '采集箱商品行 真实采集商品 AI-OPS-1',
        },
    })

    state = flow.verify_draft_box_claim('AI-OPS-1')

    assert state['stage'] == 'draft_box_claim_verified'
    assert state['claim_target']['matchedBy'] == 'source_url'
    assert '真实采集商品行' in state['claim_target']['rowText']
    assert '采集箱商品行' in state['claimed_product']['row_text']


def test_find_data_acquisition_claim_target_rejects_title_match_when_target_source_url_misses(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button, a { display: inline-block; width: 96px; height: 24px; }
        </style>
      </head>
      <body>
        <table>
          <tbody>
            <tr class="vxe-body--row">
              <td>Visible Matched Title</td>
              <td><a href="https://detail.1688.com/offer/111.html">来源</a></td>
              <td><button>认领</button></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        row = flow._find_data_acquisition_claim_target(
            page,
            product_query='Visible Matched Title',
            target_source_urls=['https://detail.1688.com/offer/999.html'],
        )
        browser.close()

    assert row['ok'] is False
    assert '未找到' in row['reason']


def test_add_note_verifies_only_target_row(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage()
    clicks = []

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: clicks.append(rect))

    result = flow._add_note_to_draft_row(
        page,
        {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]},
        'AI认领-12-34',
    )

    assert result['verified'] is False
    assert 'rowTexts.find' not in page.verify_script
    assert clicks[0] == {'x': 5, 'y': 6, 'w': 7, 'h': 8}


def test_add_note_accepts_modify_remark_menu_label(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage(menu_label='修改备注')
    clicks = []

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: clicks.append(rect))

    flow._add_note_to_draft_row(
        page,
        {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]},
        'AI认领-12-34',
    )

    assert clicks[1] == {'x': 1, 'y': 2, 'w': 3, 'h': 4}


def test_add_note_falls_back_to_store_search_when_current_filter_is_empty(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage()
    searches = []

    def fake_search(target_page, product_query=None, store_name=None):
        searches.append((product_query, store_name))
        target_page.note_visible_after_search = True

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: None)
    monkeypatch.setattr(flow, '_search_draft_box', fake_search)

    result = flow._add_note_to_draft_row(
        page,
        {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]},
        'AI认领-47-514',
        product_query='1688 Anime Peripherals Ron Weasley Figurine Acrylic Keychain',
        store_name='Dang Kang',
    )

    assert result['verified'] is True
    assert result['verifiedBy'] == 'claim_mark_store_search'
    assert searches == [(None, 'Dang Kang')]


def test_open_editor_from_draft_box_clicks_target_row_edit(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._context = object()
    page = DummyDraftPage({'ok': True})
    clicked = []

    def fake_click(target_page, rect):
        clicked.append(rect)
        target_page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    result = flow._open_editor_from_draft_box(
        page,
        row_info={'actions': [{'txt': '编辑', 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}]},
    )

    assert result is page
    assert clicked == [{'x': 10, 'y': 20, 'w': 30, 'h': 40}]


def test_open_editor_from_draft_box_finds_editor_page_when_popup_is_home(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDraftPage({'ok': True})
    popup_home = DummyDraftPage({'ok': True})
    popup_home.url = 'https://www.dianxiaomi.com/'
    popup_home.wait_for_load_state = lambda *args, **kwargs: None
    editor_page = DummyDraftPage({'ok': True})
    editor_page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    class NewPageInfo:
        value = popup_home

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class Context:
        def __init__(self):
            self.pages = [page]

        def expect_page(self, timeout=0):
            return NewPageInfo()

    context = Context()
    flow._context = context

    def fake_click(target_page, rect):
        context.pages.extend([popup_home, editor_page])

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    result = flow._open_editor_from_draft_box(
        page,
        row_info={'actions': [{'txt': '编辑', 'tag': 'A', 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}]},
    )

    assert result is editor_page


def test_open_editor_from_draft_box_prefers_dom_edit_event(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDraftPage({'ok': True})
    editor_page = DummyDraftPage({'ok': True})
    editor_page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    class Context:
        def __init__(self):
            self.pages = [page]

    context = Context()
    flow._context = context
    clicked = []

    def fake_dispatch(target_page, row_info):
        context.pages.append(editor_page)
        return {'ok': True, 'strategy': 'dom_mouse_event'}

    monkeypatch.setattr(flow, '_dispatch_draft_row_edit_event', fake_dispatch)
    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: clicked.append(rect))

    result = flow._open_editor_from_draft_box(
        page,
        row_info={'rowIndex': 3, 'rowText': '目标商品 编辑', 'actions': [{'txt': '编辑', 'tag': 'A', 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}]},
    )

    assert result is editor_page
    assert clicked == []


def test_dispatch_draft_row_edit_event_ignores_stale_row_index_for_text_match(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    row_text = (
        '1688 ENHYPEN Cute Cartoon Acrylic Keychain '
        '备注:AI认领-177-2643 「Dang Kang」 移入待发布 编辑 发布 更多'
    )
    filler = ''.join(
        '<div style="width:10px;height:10px"></div>'
        for _ in range(70)
    )
    html = f'''
    <html><body>
      {filler}
      <div class="target-row">
        {row_text}
        <a href="javascript:" onclick="window.__editClicked = true">编辑</a>
      </div>
    </body></html>
    '''

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.set_content(html)

            result = flow._dispatch_draft_row_edit_event(
                page,
                {
                    'rowIndex': 60,
                    'rowText': row_text,
                    'actions': [
                        {
                            'txt': '编辑',
                            'tag': 'A',
                            'href': 'javascript:',
                            'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4},
                        }
                    ],
                },
            )

            assert result['ok'] is True
            assert page.evaluate('window.__editClicked === true') is True
        finally:
            browser.close()


def test_dxm_login_flow_perform_editor_action_updates_state(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None: {
        'stage': 'semi_managed_enabled',
        'page_title': '店小秘--编辑速卖通产品',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'screenshot_url': '/artifacts/screenshots/semi.png',
        'semi_managed_visible': True,
        'semi_managed_enabled': True,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_editor_action('enable_semi_managed', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert state['stage'] == 'semi_managed_enabled'
    assert state['current_action'] == 'enable_semi_managed'
    assert state['product_query'] == '崩坏3钥匙扣'
    assert state['store_name'] == 'Dang Kang'
    assert state['semi_managed_enabled'] is True


def test_dxm_login_flow_perform_editor_action_keeps_browser_session_on_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None: {
        'stage': action,
        'page_title': '店小秘--编辑速卖通产品',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'screenshot_url': '/artifacts/screenshots/editor.png',
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))

    state = flow.perform_editor_action('fill_editor_required_defaults')

    assert state['stage'] == 'fill_editor_required_defaults'
    assert close_calls == []


def test_dxm_login_flow_editor_action_failure_keeps_visible_browser_for_recovery(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_perform_editor_action', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('save button changed')))
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.perform_editor_action('save_only')

    assert state['stage'] == 'save_only_failed'
    assert state['requires_user_action'] is True
    assert state['browser_visible'] is True
    assert '真实浏览器窗口会保留' in state['next_action']
    assert close_calls == []


def test_verify_edit_ownership_receives_target_source_urls_from_draft_row(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'target_source_urls': ['https://mobile.yangkeduo.com/goods2.html?goods_id=917858747237'],
    })
    page = DummyOpenSemiPage()
    seen = {}

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)

    def fake_verify(page, product_query=None, store_name=None, expected_source_urls=None):
        seen['expected_source_urls'] = expected_source_urls
        return {'stage': 'edit_ownership_verified', 'page_url': page.url, 'published': False}

    monkeypatch.setattr(flow, '_verify_edit_ownership_on_page', fake_verify)

    result = flow._perform_editor_action(
        'verify_edit_ownership',
        product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
        store_name='Dang Kang',
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert seen['expected_source_urls'] == ['https://mobile.yangkeduo.com/goods2.html?goods_id=917858747237']


def test_perform_editor_action_reuses_current_editor_page_without_reload(monkeypatch, tmp_path):
    class CurrentEditorPage(DummyOpenSemiPage):
        def __init__(self):
            super().__init__()
            self.gotos = []

        def goto(self, url, **kwargs):
            self.gotos.append(url)
            self.url = url

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })
    page = CurrentEditorPage()

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {
        'stage': 'editor_variants_filled',
        'page_url': page.url,
        'published': False,
    })

    result = flow._perform_editor_action('fill_editor_variants')

    assert result['stage'] == 'editor_variants_filled'
    assert page.gotos == []


def test_dxm_login_flow_perform_editor_action_allows_verify_not_published(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None: {
        'stage': 'not_published_verified',
        'page_title': '店小秘--编辑速卖通半托管',
        'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt',
        'screenshot_url': '/artifacts/screenshots/not-published.png',
        'published': False,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_editor_action('verify_not_published', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert state['stage'] == 'not_published_verified'
    assert state['published'] is False


def test_open_semi_managed_page_records_source_editor_url(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'semi_managed_page'
    assert state['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'


def test_semi_managed_page_state_accepts_inline_semi_managed_fields(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html><body>
      <section>基本信息 产品信息 编辑半托管信息</section>
      <section>半托管商品信息 包装尺寸 物流属性 重量 发货期</section>
    </body></html>
    '''

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html)

            state = flow._semi_managed_page_state(page)

            assert state['blocked'] is False
            assert state['is_semi_page'] is True
        finally:
            browser.close()


def test_open_semi_managed_page_allows_second_media_deferred_after_prior_eu_verified(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    media_results = iter([
        {
            'stage': 'media_assets_filled',
            'fill_result': {
                'image_slots': [
                    {
                        'label': '外包装/标签实拍图-欧盟',
                        'slot_key': 'eu_outer_package',
                        'ok': True,
                    }
                ],
                'eu_outer_package_image': {'ok': True},
            },
        },
        {
            'stage': 'media_assets_deferred',
            'message': '当前页面未出现图片槽位，已延后处理：外包装/标签实拍图-欧盟',
            'fill_result': {
                'image_slots': [
                    {
                        'label': '外包装/标签实拍图-欧盟',
                        'slot_key': 'eu_outer_package',
                        'deferred': True,
                    }
                ],
                'eu_outer_package_image': {'deferred': True},
            },
        },
    ])

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_media_assets_on_page', lambda page, defaults=None: next(media_results))
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(
        DummyOpenSemiPage(),
        {'image': {'eu_outer_package_filename': '微信图片_202504092228421.jpg'}},
    )

    assert state['stage'] == 'semi_managed_page'


def test_open_semi_managed_page_refills_variants_and_compliance_on_same_page(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: calls.append('base') or {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: calls.append('variants') or {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: calls.append('compliance') or {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: calls.append('main_images') or {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: calls.append('enable') or {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'semi_managed_page'
    assert calls == ['base', 'variants', 'compliance', 'main_images', 'enable']


def test_open_semi_managed_page_retries_customs_after_image_repairs(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    monkeypatch.setattr(
        flow,
        '_fill_editor_required_defaults_on_page',
        lambda page, defaults=None: calls.append('base') or {
            'stage': 'editor_required_defaults_filled',
            'fill_result': {'customs_supervision': {'ok': False, 'reason': '海关监管弹窗未打开'}},
        },
    )
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: calls.append('variants') or {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_media_assets_on_page', lambda page, defaults=None: calls.append('media') or {'stage': 'media_assets_filled', 'fill_result': {'eu_outer_package_image': {'ok': True}}})
    monkeypatch.setattr(flow, '_media_result_has_verified_eu_outer_package', lambda result: True)
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: calls.append('compliance') or {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: calls.append('main_images') or {'ok': True})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: calls.append(('customs_after_repairs', names)) or {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: calls.append('enable') or {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(
        DummyOpenSemiPage(),
        {'image': {'eu_outer_package_filename': '微信图片_202504092228421.jpg'}, 'compliance': {'customs_product_names': ['keychain']}},
    )

    assert state['stage'] == 'semi_managed_page'
    assert calls[:5] == ['base', 'variants', 'media', 'compliance', 'main_images']
    assert calls[5] == ('customs_after_repairs', ['keychain'])
    assert calls[6] == 'enable'


def test_open_semi_managed_page_stops_when_same_page_variants_fail(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {'stage': 'fill_editor_variants_failed', 'message': '缺少变体字段'})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'open_semi_managed_page_failed'
    assert state['label'] == '普通编辑页变体信息未通过'
    assert state['preflight_results']['variants']['stage'] == 'fill_editor_variants_failed'


def test_open_semi_managed_page_stops_when_main_images_still_invalid(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {
        'ok': False,
        'message': '主图仍存在无效已选图片，不能进入半托管信息。',
        'after': {'selected_invalid_count': 1},
    })

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'open_semi_managed_page_failed'
    assert state['label'] == '普通编辑页主图未通过'
    assert state['preflight_results']['main_images']['ok'] is False


def test_repair_product_main_images_clears_invalid_selected_images(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyProductMainImagesPage([
        {'index': 0, 'text': '选用 0 X 0', 'checked': True, 'valid': False, 'width': 0, 'height': 0, 'src': 'bad-a.jpg'},
        {'index': 1, 'text': '选用 800 X 800', 'checked': True, 'valid': True, 'width': 800, 'height': 800, 'src': 'good-a.jpg'},
        {'index': 2, 'text': '选用 800 X 800', 'checked': False, 'valid': True, 'width': 800, 'height': 800, 'src': 'good-b.jpg'},
    ])

    result = flow._repair_product_main_images_on_page(page)

    assert result['ok'] is True
    assert result['before']['selected_invalid_count'] == 1
    assert result['after']['selected_invalid_count'] == 0
    assert result['after']['selected_valid_count'] == 2
    assert page.actions[0]['clicked_invalid'] == [{'index': 0, 'text': '选用 0 X 0'}]
    assert page.actions[0]['clicked_valid'] == [{'index': 2, 'text': '选用 800 X 800'}]


def test_repair_product_main_images_fails_without_valid_candidate(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyProductMainImagesPage([
        {'index': 0, 'text': '选用 0 X 0', 'checked': True, 'valid': False, 'width': 0, 'height': 0, 'src': 'bad-a.jpg'},
    ])

    result = flow._repair_product_main_images_on_page(page)

    assert result['ok'] is False
    assert result['message'] == '主图模块没有可用的有效图片。'


def test_fill_semi_managed_reopens_from_source_editor_when_semi_url_is_bare(monkeypatch, tmp_path):
    class ReopenPage(DummySemiPage):
        url = 'about:blank'

        def __init__(self):
            super().__init__({'ok': True})
            self.gotos = []

        def goto(self, url, **kwargs):
            self.gotos.append(url)
            self.url = url

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'semi_managed_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt',
        'source_editor_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })
    page = ReopenPage()
    reopened = []

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_open_semi_managed_page_from_editor', lambda page, defaults=None: reopened.append(defaults) or {'stage': 'semi_managed_page'})
    monkeypatch.setattr(flow, '_fill_semi_managed_defaults_on_page', lambda page, defaults=None: {'stage': 'semi_managed_defaults_filled'})

    result = flow._perform_editor_action(
        'fill_semi_managed_defaults',
        defaults={'semi_managed': {'jit_stock': '100'}},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert result['stage'] == 'semi_managed_defaults_filled'
    assert result['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    assert page.gotos == ['https://www.dianxiaomi.com/web/smt/edit?id=123']
    assert reopened == [{'semi_managed': {'jit_stock': '100'}}]


def test_save_only_reopens_semi_page_from_source_editor_when_semi_url_is_bare(monkeypatch, tmp_path):
    class ReopenPage(DummySemiPage):
        url = 'about:blank'

        def __init__(self):
            super().__init__({'ok': True})
            self.gotos = []

        def goto(self, url, **kwargs):
            self.gotos.append(url)
            self.url = url

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'semi_managed_defaults_filled',
        'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt',
        'source_editor_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })
    page = ReopenPage()
    reopened = []
    prefilled = []

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_open_semi_managed_page_from_editor', lambda page, defaults=None: reopened.append(defaults) or {'stage': 'semi_managed_page'})
    monkeypatch.setattr(flow, '_fill_semi_managed_defaults_on_page', lambda page, defaults=None: prefilled.append(defaults) or {'stage': 'semi_managed_defaults_filled'})
    monkeypatch.setattr(flow, '_save_only_on_page', lambda page: {'stage': 'save_only_done', 'save_result': {'ok': True, 'published': False}})

    result = flow._perform_editor_action(
        'save_only',
        defaults={'semi_managed': {'jit_stock': '100'}},
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert result['stage'] == 'save_only_done'
    assert result['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    assert page.gotos == ['https://www.dianxiaomi.com/web/smt/edit?id=123']
    assert reopened == [{'semi_managed': {'jit_stock': '100'}}]
    assert prefilled == [{'semi_managed': {'jit_stock': '100'}}]


def test_verify_not_published_accepts_prior_save_success_without_publish_risk(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'ok': False,
        'save_only_term': None,
        'publish_risk_term': None,
        'published': False,
        'body_excerpt': '保存 立即发布',
    })

    state = flow._verify_not_published_on_page(
        page,
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        prior_save_result={'ok': True, 'published': False, 'success_text': '编辑成功'},
    )

    assert state['stage'] == 'not_published_verified'
    assert state['message'] == '编辑成功'
    assert state['fill_result']['verified_by_prior_save_result'] is True
    assert state['published'] is False


def test_verify_not_published_ignores_ambient_online_text_after_save_success(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'ok': False,
        'save_only_term': '待发布',
        'publish_risk_term': '已上架',
        'published': True,
        'body_excerpt': '产品菜单 已上架 下架 待发布 保存',
    })

    state = flow._verify_not_published_on_page(
        page,
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        prior_save_result={
            'ok': True,
            'published': False,
            'success_text': '编辑成功',
            'network_save_result': {'ok': True, 'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json'},
        },
    )

    assert state['stage'] == 'not_published_verified'
    assert state['message'] == '待发布'
    assert state['published'] is False
    assert state['fill_result']['ignored_ambient_publish_risk_term'] == '已上架'
    assert state['fill_result']['publish_risk_term'] is None


def test_dismiss_blocking_modals_rejects_publish_confirmation(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with pytest.raises(RuntimeError, match='危险弹窗'):
        flow._dismiss_blocking_modals(DummyDangerousModalPage())


def test_dismiss_blocking_modals_skips_collection_plugin_guide(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyGuideOverlayPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 1
    assert clicks == [{'x': 10, 'y': 20, 'w': 30, 'h': 40}]


def test_dismiss_blocking_modals_skips_important_reminder(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImportantReminderModalPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 1
    assert clicks == [{'x': 983, 'y': 315, 'w': 72, 'h': 15}]


def test_dismiss_blocking_modals_skips_reminder_dropdown(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyReminderDropdownPage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)
        page.clicked = True

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 1
    assert clicks == [{'x': 1000, 'y': 345, 'w': 90, 'h': 24}]


def test_dismiss_blocking_modals_uses_escape_when_same_close_click_repeats(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyPersistentModalUntilEscapePage()
    clicks = []

    def fake_click(_page, rect):
        clicks.append(rect)

    monkeypatch.setattr(flow, '_click_rect_center', fake_click)

    dismissed = flow._dismiss_blocking_modals(page)

    assert dismissed == 3
    assert clicks == [
        {'x': 120, 'y': 20, 'w': 24, 'h': 24},
        {'x': 120, 'y': 20, 'w': 24, 'h': 24},
    ]
    assert page.presses == ['Escape']
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'escape_after_repeated_click'


def test_dismiss_blocking_modals_prefers_ignore_prompt_over_close_button(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.ant-modal-wrap')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(40, abs=2)
    assert clicks[0]['w'] == pytest.approx(90, abs=2)


def test_dismiss_blocking_modals_handles_standalone_ignore_prompt(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.activity-popover')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(320, abs=2)
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] in {'忽略提示', 'standalone:忽略提示'}


def test_dismiss_blocking_modals_handles_dxm_campaign_next_step(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.dxm-campaign-layer')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(756, abs=4)
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] in {'下一步', 'standalone:下一步'}


def test_dismiss_blocking_modals_skips_ant_modal_mask_and_uses_dialog(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.ant-modal-root')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(600, abs=4)
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] in {'忽略提示', 'standalone:忽略提示'}


def test_dismiss_blocking_modals_skips_mask_for_notice_next_button(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.ant-modal-root')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(592, abs=4)
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] == '下一条'


def test_dismiss_blocking_modals_ignores_inline_logistics_notice(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.ant-modal-root')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(592, abs=4)
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] == '下一条'


def test_dismiss_blocking_modals_prefers_small_clickable_standalone_prompt(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.important-remind')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(340, abs=4)
    assert clicks[0]['w'] == pytest.approx(90, abs=4)


def test_dismiss_blocking_modals_prefers_text_span_inside_wide_prompt(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.important-remind')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks[0]['x'] == pytest.approx(380, abs=4)
    assert clicks[0]['w'] == pytest.approx(64, abs=4)


def test_wait_for_page_ready_loops_until_loading_disappears(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyReadyWaitPage()

    result = flow._wait_for_page_ready(page, ['标题/产品ID'], label='速卖通采集箱', timeout=3000)

    assert result['ready'] is True
    assert result['ready_term'] == '标题/产品ID'
    assert page.ready_calls == 2
    assert page.dismiss_calls == 2


def test_open_semi_managed_page_fails_on_product_info_error(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': True, 'message': '产品信息中有错误，请检查'})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'open_semi_managed_page_failed'
    assert state['published'] is False
    assert '产品信息中有错误' in state['message']


def test_extract_eu_outer_package_filename_from_nested_config(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    filename = flow._extract_eu_outer_package_filename({
        'image': {
            'eu_outer_package_image': {
                'filename': '微信图片_202504092228421.jpg',
            },
        },
    })

    assert filename == '微信图片_202504092228421.jpg'


def test_extract_eu_outer_package_filename_from_image_slots(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    filename = flow._extract_eu_outer_package_filename({
        'image': {
            'slots': [
                {'label': '产品本体标签图-欧盟', 'filename': 'body.jpg'},
                {'slot_key': 'eu_outer_package', 'filename': '微信图片_202504092228421.jpg'},
            ],
        },
    })

    assert filename == '微信图片_202504092228421.jpg'


def test_extract_marketing_scene_filename_from_image_slots(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    filename = flow._extract_marketing_scene_filename({
        'image': {
            'slots': [
                {'slot_key': 'marketing_white_1_1', 'strategy': 'generate', 'label': '(1:1白底图)'},
                {'slot_key': 'marketing_scene_3_4', 'filename': 'scene-750x1000.jpg', 'label': '(3:4场景图)'},
                {'slot_key': 'eu_outer_package', 'filename': '微信图片_202504092228421.jpg'},
            ],
        },
    })

    assert filename == 'scene-750x1000.jpg'


def test_extract_marketing_scene_filename_falls_back_to_eu_outer_package(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    filename = flow._extract_marketing_scene_filename({
        'image': {
            'slots': [
                {'slot_key': 'marketing_white_1_1', 'strategy': 'generate', 'label': '(1:1白底图)'},
                {'slot_key': 'marketing_scene_3_4', 'strategy': 'generate', 'label': '(3:4场景图)'},
                {'slot_key': 'eu_outer_package', 'filename': '微信图片_202504092228421.jpg'},
            ],
        },
    })

    assert filename == '微信图片_202504092228421.jpg'


def test_extract_image_slots_excludes_marketing_slots_with_filenames(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    slots = flow._extract_image_slots({
        'image': {
            'slots': [
                {'slot_key': 'marketing_scene_3_4', 'filename': 'scene-750x1000.jpg', 'label': '(3:4场景图)'},
                {'slot_key': 'eu_outer_package', 'filename': '微信图片_202504092228421.jpg'},
            ],
        },
    })

    assert slots == [{
        'label': '外包装/标签实拍图-欧盟',
        'filename': '微信图片_202504092228421.jpg',
        'slot_key': 'eu_outer_package',
        'source': 'smt_image_bank',
    }]


def test_flatten_editor_defaults_consumes_grouped_templates(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    flattened = flow._flatten_editor_defaults({
        'category': {'category_keyword': '立牌', 'category_match': 'ACG Stand'},
        'logistics': {'weight': '0.04', 'length': '11', 'freight_templates': ['石油40g普货包裹.']},
        'semi_managed': {'jit_stock': '100', 'original_box': '否'},
        'compliance': {'eu_responsible_names': ['Jacqueiline Marti']},
    })

    assert flattened['category_keyword'] == '立牌'
    assert flattened['category_match'] == 'ACG Stand'
    assert flattened['weight'] == '0.04'
    assert flattened['length'] == '11'
    assert flattened['freight_template_priorities'] == ['石油40g普货包裹.']
    assert flattened['jit_stock'] == '100'
    assert flattened['is_original_box'] == '否'
    assert flattened['eu_responsible_priorities'] == ['Jacqueiline Marti']


def test_apply_dxm_reference_templates_uses_attribute_reference_control(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    monkeypatch.setattr(
        flow,
        '_apply_reference_templates_on_page',
        lambda page, names: calls.append(names) or {'ok': True, 'text': '立牌类谷子'},
    )

    results = flow._apply_dxm_reference_templates_on_page(
        object(),
        {'attribute_info': {'names': ['立牌类谷子'], 'required': True}},
    )

    assert calls == [['立牌类谷子']]
    assert results['attribute_info']['ok'] is True
    assert results['attribute_info']['text'] == '立牌类谷子'


def test_apply_dxm_reference_templates_records_label_select_sections(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    def choose(page, label, names):
        calls.append((label, names))
        return {'ok': True, 'text': names[0]}

    monkeypatch.setattr(flow, '_choose_ant_select_near_label', choose)

    results = flow._apply_dxm_reference_templates_on_page(
        object(),
        {
            'freight': {'names': ['40g普货包裹'], 'required': True},
            'service': {'names': ['Service Template for New Sellers'], 'required': True},
            'eu_responsible': {'names': ['Jacqueiline Marti'], 'required': True},
            'manufacturer': {'names': ['jiyang county thunder'], 'required': True},
        },
    )

    assert calls == [
        ('运费模板', ['40g普货包裹']),
        ('服务模板', ['Service Template for New Sellers']),
        ('欧盟责任人', ['Jacqueiline Marti']),
        ('品牌制造商', ['jiyang county thunder']),
    ]
    assert {name: result['text'] for name, result in results.items()} == {
        'freight': '40g普货包裹',
        'service': 'Service Template for New Sellers',
        'eu_responsible': 'Jacqueiline Marti',
        'manufacturer': 'jiyang county thunder',
    }


def test_click_ant_option_near_rect_falls_back_to_visible_options(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          .ant-select-dropdown { position: fixed; left: 20px; top: 20px; width: 220px; }
          .ant-select-item-option { height: 28px; padding: 4px 8px; }
        </style>
      </head>
      <body>
        <div class="ant-select-dropdown">
          <div class="ant-select-item-option" role="option">万代立牌</div>
          <div class="ant-select-item-option" role="option">bilibili动漫周边</div>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        result = flow._click_ant_option_near_rect(
            page,
            ['万代立牌'],
            {'x': 900, 'y': 650, 'w': 180, 'h': 32},
        )
        browser.close()

    assert result['ok'] is True
    assert result['text'] == '万代立牌'
    assert result['strategy'] == 'global_visible_options'


def test_click_ant_option_near_rect_reopens_after_modal_dismissed(monkeypatch, tmp_path):
    class AntDropdownBlockedPage:
        def __init__(self):
            self.evaluate_calls = 0
            self.clicked = []
            self.timeouts = []

        def evaluate(self, script, arg=None):
            self.evaluate_calls += 1
            if self.evaluate_calls == 1:
                return {'no_match': True, 'options': [], 'candidate_count': 0, 'option_count': 0}
            return {
                'text': '万代立牌',
                'rect': {'x': 10, 'y': 20, 'w': 80, 'h': 30},
                'strategy': 'global_visible_options',
            }

        @property
        def mouse(self):
            return self

        def click(self, x, y):
            self.clicked.append((x, y))

        def wait_for_timeout(self, timeout):
            self.timeouts.append(timeout)

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = AntDropdownBlockedPage()
    dismissed = []

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: dismissed.append(True) or 1)

    result = flow._click_ant_option_near_rect(
        page,
        ['万代立牌'],
        {'x': 100, 'y': 200, 'w': 120, 'h': 32},
    )

    assert result['ok'] is True
    assert result['text'] == '万代立牌'
    assert len(page.clicked) == 2
    assert dismissed == [True]


def test_fill_editor_required_defaults_fails_when_required_description_template_missing(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page: {'missing': []})

    state = flow._fill_editor_required_defaults_on_page(
        page,
        {
            'dxm_reference_templates_resolved': {
                'description': {'names': ['详情模板'], 'required': True},
            },
        },
    )

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert 'dxm_reference_templates.description' in state['fill_result']['missing']
    assert state['fill_result']['dxm_reference_template_results']['description']['ok'] is False
    assert '描述' in state['fill_result']['dxm_reference_template_results']['description']['reason']


def test_fill_editor_required_defaults_defers_missing_attribute_template_to_filled_attributes(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    reference_results = {
        'attribute_info': {
            'ok': False,
            'reason': '未找到匹配选项',
            'options': [],
            'section': 'attribute_info',
            'names': ['万代立牌'],
            'required': True,
        },
        'freight': {'ok': True, 'section': 'freight', 'names': ['40g普货包裹'], 'required': True},
        'service': {'ok': True, 'section': 'service', 'names': ['Service Template for New Sellers'], 'required': True},
    }

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: reference_results)
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True, 'filled': ['attribute-fields']})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page: {'missing': []})

    state = flow._fill_editor_required_defaults_on_page(
        page,
        {
            'dxm_reference_templates_resolved': {
                'attribute_info': {'names': ['万代立牌'], 'required': True},
                'freight': {'names': ['40g普货包裹'], 'required': True},
                'service': {'names': ['Service Template for New Sellers'], 'required': True},
            },
        },
    )

    assert state['stage'] == 'editor_required_defaults_filled'
    assert state['fill_result']['missing'] == []
    attribute_info = state['fill_result']['dxm_reference_template_results']['attribute_info']
    assert attribute_info['ok'] is True
    assert attribute_info['deferred_to_category_attributes'] is True
    assert attribute_info['original_reason'] == '未找到匹配选项'


def test_fill_editor_required_defaults_defers_downstream_owned_fields(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: {})
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': False, 'reason': '后续合规步骤处理'})
    monkeypatch.setattr(
        flow,
        '_editor_required_defaults_state',
        lambda page: {'missing': ['declared_value', 'weight', 'customs_supervision']},
    )

    state = flow._fill_editor_required_defaults_on_page(page, {})

    assert state['stage'] == 'editor_required_defaults_filled'
    assert state['fill_result']['missing'] == []


def test_flatten_editor_defaults_consumes_semi_managed_price_aliases(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    flattened = flow._flatten_editor_defaults({
        'semi_managed': {
            'supply_price': '48.62',
            'product_price': '49.00',
            'price': '50.00',
        },
    })

    assert flattened['supply_price'] == '48.62'
    assert flattened['product_price'] == '49.00'


def test_flatten_editor_defaults_consumes_config_center_edit_page_aliases(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    flattened = flow._flatten_editor_defaults({
        'sku': {'sku_code': 'SKU-001', 'jit_stock': '88'},
        'pricing': {'product_price': '9.99', 'supply_price': '6.66', 'stock': '77'},
        'logistics': {'freight_template': '半托管运费模板', 'service_template': '无忧服务模板'},
        'compliance': {'customs_name': 'Acrylic stand'},
    })

    assert flattened['sku_code'] == 'SKU-001'
    assert flattened['jit_stock'] == '88'
    assert flattened['product_price'] == '9.99'
    assert flattened['supply_price'] == '6.66'
    assert flattened['stock'] == '77'
    assert flattened['freight_template_priorities'] == '半托管运费模板'
    assert flattened['service_template_priorities'] == '无忧服务模板'
    assert flattened['customs_product_name_priorities'] == 'Acrylic stand'


def test_fill_semi_managed_defaults_uses_column_header_strategy(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiManagedFieldsPage()

    monkeypatch.setattr(flow, '_fill_semi_original_box', lambda page, value: {'ok': True})
    monkeypatch.setattr(flow, '_fill_semi_logistics_attribute', lambda page, value: {'ok': True})

    state = flow._fill_semi_managed_defaults_on_page(
        page,
        {'semi_managed': {'jit_stock': '100', 'supply_price': '48.62'}},
    )

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['field_details']['stock']['value_after'] == '100'
    assert page.values['stock'] == '100'
    assert page.values['supply_price'] == '48.62'
    assert 'headerCandidates' in page.script
    assert 'tableInputsByHeader' in page.script
    assert 'table_column' in page.script
    assert 'field_details' in page.script
    assert 'Object.getOwnPropertyDescriptor' in page.script


def test_fill_editor_variants_defers_missing_logistics_attribute_when_table_fields_filled(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEditorVariantsLogisticsOnlyPage()
    flow._fill_semi_logistics_attribute = lambda target_page, value: {'ok': True, 'skipped': True}

    state = flow._fill_editor_variants_on_page(page, {})

    assert state['stage'] == 'editor_variants_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['logistics_attribute_detail']['skipped'] is True


def test_fill_editor_variants_confirms_each_logistics_icon_even_when_plain_goods_visible(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEditorVariantsWithLogisticsIconsPage()
    calls = []

    monkeypatch.setattr(
        flow,
        '_fill_editor_variant_logistics_attribute',
        lambda target_page, value: calls.append((target_page, value)) or {'ok': True, 'icon_count': 6},
    )

    state = flow._fill_editor_variants_on_page(page, {'logistics': {'logistics_attribute': '普货'}})

    assert state['stage'] == 'editor_variants_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['logistics_attribute_detail']['icon_count'] == 6
    assert calls == [(page, '普货')]


def test_category_attribute_priorities_choose_safe_defaults(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    assert flow._category_attribute_priorities('材质(Material)')[0] == 'Acrylic'
    assert flow._category_attribute_priorities('是否带电(Is Electric)')[0] == 'No'
    assert flow._category_attribute_priorities('系列(Mfg Series Number)')[0] == 'Resin'
    assert flow._category_attribute_priorities('动漫电影游戏名称(ACG Name)')[0] == 'Other'


def test_select_category_attribute_value_confirms_search_select_with_keyboard(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class Keyboard:
        def __init__(self):
            self.presses = []

        def press(self, key):
            self.presses.append(key)

    class Page:
        def __init__(self):
            self.keyboard = Keyboard()

        def wait_for_timeout(self, timeout):
            return None

    page = Page()
    clicked = []

    monkeypatch.setattr(flow, '_focus_category_attribute_input', lambda page, label, value: {'ok': True})
    monkeypatch.setattr(flow, '_visible_category_attribute_option', lambda page, priorities: {'text': '成品(Finished Goods)', 'rect': {'x': 1, 'y': 2, 'w': 3, 'h': 4}})
    monkeypatch.setattr(flow, '_category_attribute_row_state', lambda page, label: {'ok': True, 'text': '商品属性(Commodity Attribute) 成品(Finished Goods)'})
    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: clicked.append(rect))
    monkeypatch.setattr(flow, '_fill_category_attribute_free_text', lambda page, label, value: {'ok': False})

    result = flow._select_category_attribute_value(page, '商品属性(Commodity Attribute)', ['Finished Goods'])

    assert result['ok'] is True
    assert result['strategy'] == 'keyboard_select'
    assert page.keyboard.presses == ['ArrowDown', 'Enter']
    assert clicked == []


def test_fill_semi_managed_defaults_writes_real_table_dom(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_fill_semi_original_box', lambda page, value: {'ok': True})
    monkeypatch.setattr(flow, '_fill_semi_logistics_attribute', lambda page, value: {'ok': True})

    html = '''
    <html>
      <body>
        <div class="outer">
          货品信息 是否原箱 物流属性 重量 尺寸 变种信息 产品价格 SKU编码 货品编码 货品条码 JIT库存
          <section>
            <h3>货品信息</h3>
            <table>
              <thead>
                <tr><th>是否原箱</th><th>物流属性</th><th>* 重量（kg）</th><th>* 尺寸（cm）</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><input value="否" /></td>
                  <td><span>普货</span></td>
                  <td><input data-field="weight" value="" /></td>
                  <td>
                    <input data-field="length" value="" />
                    <input data-field="width" value="" />
                    <input data-field="height" value="" />
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
          <section>
            <h3>变种信息</h3>
            <table>
              <thead>
                <tr><th>sku图片</th><th>*产品价格（CNY）</th><th>SKU编码</th><th>货品编码</th><th>货品条码</th><th>* JIT库存</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><img alt="" /></td>
                  <td><input data-field="price" value="48.62" /></td>
                  <td><input value="7" /></td>
                  <td><input data-field="goods_code" placeholder="请输入" value="" /></td>
                  <td><input data-field="goods_barcode" placeholder="请输入" value="100" /></td>
                  <td><input data-field="stock" value="0" /></td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>
      </body>
    </html>
    '''

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.set_content(html)
            state = flow._fill_semi_managed_defaults_on_page(
                page,
                {'semi_managed': {'jit_stock': '100', 'product_price': '49.00', 'supply_price': '48.62'}},
            )
            values = page.evaluate('''() => Object.fromEntries(
              Array.from(document.querySelectorAll('[data-field]')).map(el => [el.dataset.field, el.value])
            )''')
            browser.close()
    except PlaywrightError as exc:
        pytest.skip(f'Playwright browser unavailable: {exc}')

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['field_details']['stock']['value_before'] == '0'
    assert state['fill_result']['field_details']['stock']['value_after'] == '100'
    assert values == {
        'weight': '0.03',
        'length': '10',
        'width': '10',
        'height': '2',
        'price': '49.00',
        'goods_code': '',
        'goods_barcode': '',
        'stock': '100',
    }


def test_fill_semi_managed_defaults_accepts_retail_price_and_original_box_select(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <body>
        <table>
          <thead>
            <tr>
              <th>颜色</th><th>零售价(CNY)</th><th>库存</th><th>重量(kg)</th>
              <th>包装尺寸(cm)</th><th>是否原箱</th><th>物流属性</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>白色</td>
              <td><input data-field="price" placeholder="零售价" value="58.82" /></td>
              <td><input data-field="stock" placeholder="库存" value="99" /></td>
              <td><input data-field="weight" placeholder="重量" value="0.04" /></td>
              <td>
                <input data-field="length" value="" />
                <input data-field="width" value="" />
                <input data-field="height" value="" />
              </td>
              <td>
                <select data-field="original_box">
                  <option value="">请选择</option>
                  <option value="1" selected>否</option>
                  <option value="2">是</option>
                </select>
              </td>
              <td>普货</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.set_content(html)

            state = flow._fill_semi_managed_defaults_on_page(
                page,
                {'semi_managed': {'jit_stock': '100', 'product_price': '49.00', 'is_original_box': '否'}},
            )
            values = page.evaluate('''() => Object.fromEntries(
              Array.from(document.querySelectorAll('[data-field]')).map(el => [el.dataset.field, el.value])
            )''')
        finally:
            browser.close()

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['original_box']['ok'] is True
    assert values['price'] == '49.00'
    assert values['original_box'] == '1'


def test_should_generate_marketing_images_from_image_template(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    assert flow._should_generate_marketing_images({'image': {'marketing_images_strategy': 'generate'}}) is True
    assert flow._should_generate_marketing_images({
        'image': {
            'slots': [
                {'label': '(1:1白底图)', 'strategy': 'generate'},
            ],
        },
    }) is True
    assert flow._should_generate_marketing_images({'image': {'slots': [{'label': '主图', 'strategy': 'generate'}]}}) is False


def test_should_process_marketing_images_when_config_marks_already_generated(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    assert flow._should_generate_marketing_images({'image': {'marketing_images_already_generated': True}}) is True
    assert flow._marketing_images_marked_already_generated({'image': {'already_generated': 'true'}}) is True


def test_generate_marketing_images_runs_white_background_conversion(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()
    states = iter([
        {'ok': False, 'missing': ['1:1白底图'], 'reason': '营销图片缺少：1:1白底图'},
        {'ok': True, 'missing': [], 'items': [{'text': '2000 X 2000 (1:1白底图)', 'has_image': True}]},
    ])
    white_background_calls = []

    monkeypatch.setattr(flow, '_marketing_images_state', lambda page: next(states))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(
        flow,
        '_apply_marketing_white_background',
        lambda page: white_background_calls.append(True) or {'ok': True, 'clicked': True},
        raising=False,
    )

    result = flow._generate_marketing_images_on_page(page)

    assert result['ok'] is True
    assert white_background_calls == [True]
    assert result['white_background'] == {'ok': True, 'clicked': True}


def test_generate_marketing_images_applies_white_background_to_existing_images(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()
    state = {'ok': True, 'missing': [], 'items': [{'text': '2000 X 2000 (1:1白底图)', 'has_image': True}]}
    white_background_calls = []

    monkeypatch.setattr(flow, '_marketing_images_state', lambda page: state)
    monkeypatch.setattr(
        flow,
        '_apply_marketing_white_background',
        lambda page: white_background_calls.append(True) or {'ok': True, 'clicked': True},
        raising=False,
    )

    result = flow._generate_marketing_images_on_page(page)

    assert result['ok'] is True
    assert result['already_generated'] is True
    assert white_background_calls == [True]
    assert result['white_background'] == {'ok': True, 'clicked': True}


def test_generate_marketing_images_accepts_existing_complete_images_when_white_background_menu_missing(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()
    state = {'ok': True, 'missing': [], 'items': [{'text': '800 X 800 (1:1白底图)', 'has_image': True}, {'text': '750 X 1000 (3:4场景图)', 'has_image': True}]}

    monkeypatch.setattr(flow, '_marketing_images_state', lambda page: state)
    monkeypatch.setattr(
        flow,
        '_apply_marketing_white_background',
        lambda page: {'ok': False, 'reason': '未找到图片白底菜单项'},
        raising=False,
    )

    result = flow._generate_marketing_images_on_page(page)

    assert result['ok'] is True
    assert result['already_generated'] is True
    assert result['warning'] == '未找到图片白底菜单项'
    assert result['after']['ok'] is True


def test_marketing_images_state_rejects_zero_dimension_scene_image(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class Page:
        def __init__(self):
            self.script = ''

        def evaluate(self, script, arg=None):
            self.script = script
            return {'ok': False, 'missing': ['3:4场景图']}

    page = Page()

    result = flow._marketing_images_state(page)

    assert result['missing'] == ['3:4场景图']
    assert 'width >= 750 && height >= 1000' in page.script
    assert '!hasNonZeroSize || !meetsRequiredSize' in page.script


def test_generate_marketing_images_does_not_regenerate_when_config_says_already_generated(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()

    monkeypatch.setattr(
        flow,
        '_marketing_images_state',
        lambda page: {'ok': False, 'missing': ['1:1白底图'], 'reason': '营销图片缺少：1:1白底图'},
    )

    result = flow._generate_marketing_images_on_page(page, allow_generate=False)

    assert result['ok'] is False
    assert result['already_generated'] is True
    assert page.clicked == []


def test_generate_marketing_images_uses_scene_fallback_filename(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()
    states = iter([
        {'ok': False, 'missing': ['3:4场景图'], 'reason': '营销图片缺少：3:4场景图'},
        {'ok': False, 'missing': ['3:4场景图'], 'reason': '营销图片缺少：3:4场景图'},
        {'ok': True, 'missing': [], 'items': [{'text': '750 X 1000 (3:4场景图)', 'has_image': True}]},
    ])
    fills = []

    monkeypatch.setattr(flow, '_marketing_images_state', lambda page: next(states))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_apply_marketing_white_background', lambda page: {'ok': True}, raising=False)
    monkeypatch.setattr(
        flow,
        '_fill_marketing_scene_image_by_filename',
        lambda page, filename: fills.append(filename) or {'ok': True, 'filename': filename},
    )

    result = flow._generate_marketing_images_on_page(page, scene_fallback_filename='scene-750x1000.jpg')

    assert result['ok'] is True
    assert fills == ['scene-750x1000.jpg']
    assert result['scene_fallback']['filename'] == 'scene-750x1000.jpg'


def test_generate_marketing_images_reports_missing_scene_fallback_filename(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeneratePage()
    states = iter([
        {'ok': False, 'missing': ['3:4场景图'], 'reason': '营销图片缺少：3:4场景图'},
        {'ok': False, 'missing': ['3:4场景图'], 'reason': '营销图片缺少：3:4场景图'},
    ])

    monkeypatch.setattr(flow, '_marketing_images_state', lambda page: next(states))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_apply_marketing_white_background', lambda page: {'ok': True}, raising=False)

    result = flow._generate_marketing_images_on_page(page)

    assert result['ok'] is False
    assert result['reason'] == '营销3:4场景图缺少备用图片文件名'


def test_open_marketing_image_picker_targets_market_img_item(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageSlotPickerScriptPage()

    result = flow._open_marketing_image_picker(page, '3:4场景图')

    assert result['ok'] is False
    assert '.market-img-item' in page.script
    assert '营销图片槽位附近出现危险动作' in page.script
    assert '保存并发布' in page.script


def test_remove_invalid_marketing_image_targets_delete_icon_safely(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageSlotPickerScriptPage()

    result = flow._remove_invalid_marketing_image(page, '3:4场景图')

    assert result['ok'] is False
    assert '.market-img-item' in page.script
    assert 'icon_delete' in page.script
    assert 'width < 750 || height < 1000' in page.script
    assert '保存并发布' in page.script


def test_open_marketing_white_background_dialog_uses_image_tool_menu(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingWhiteBackgroundDialogOpenerPage()

    result = flow._open_marketing_white_background_dialog(page)

    assert result['ok'] is True
    assert result['text'] == '图片白底'
    assert page.clicked == [(25.0, 40.0), (85.0, 100.0)]
    assert "const hasSize" in page.scripts[0]
    assert "cls.includes('icon')" not in page.scripts[0]
    assert "cls.includes('tool')" not in page.scripts[0]
    assert "cls.includes('dropdown')" not in page.scripts[0]
    assert "closestMenu" in page.scripts[1]
    assert "trigger}" not in page.scripts[1]


def test_open_marketing_white_background_dialog_has_geometry_fallback_and_scoped_menu(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMarketingGeometryScriptPage()

    result = flow._open_marketing_white_background_dialog(page)

    assert result['ok'] is False
    assert 'isLowerLeftTool' in page.scripts[0]
    assert 'isRightSideDanger' in page.scripts[0]
    assert '保存并移入待发布' in page.scripts[0]
    assert 'triggerRect' in page.scripts[1]
    assert 'nearTrigger' in page.scripts[1]
    assert "x.text === '图片白底'" in page.scripts[1]


def test_apply_marketing_white_background_fails_when_one_click_dialog_missing(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyWhiteBackgroundMissingDialogPage()

    result = flow._apply_marketing_white_background(page)

    assert result['ok'] is False
    assert result['reason'] == '点击图片白底后未出现一键白底弹窗'


def test_fill_image_slot_materializes_lazy_eu_qualification_area(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    states = iter([
        {'ok': False, 'missing_slot': True, 'reason': '未找到外包装/标签实拍图-欧盟槽位'},
        {'ok': False, 'reason': '欧盟外包装图槽位仍为空'},
        {'ok': True, 'filled_image_count': 1, 'filename_matched': True},
    ])
    materialized = []

    monkeypatch.setattr(flow, '_image_slot_state', lambda page, label, filename: next(states))
    monkeypatch.setattr(flow, '_materialize_image_slot_section', lambda page, label: materialized.append(label) or {'ok': True})
    monkeypatch.setattr(flow, '_fill_image_slot_asset_by_filename', lambda page, label, filename: {'ok': True})

    result = flow._fill_image_slot_by_filename(page, '外包装/标签实拍图-欧盟', '微信图片_202504092228421.jpg')

    assert result['ok'] is True
    assert materialized == ['外包装/标签实拍图-欧盟']


def test_eu_outer_package_existing_filled_image_without_filename_uses_configured_filename(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    fills = []
    states = iter([
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
    ])

    monkeypatch.setattr(flow, '_image_slot_state', lambda page, label, filename: next(states))
    monkeypatch.setattr(flow, '_remove_image_slot_existing_image', lambda page, label: {'ok': True})
    monkeypatch.setattr(flow, '_fill_image_slot_asset_by_filename', lambda page, label, filename: fills.append((label, filename)) or {'ok': True})

    result = flow._fill_image_slot_by_filename(page, '外包装/标签实拍图-欧盟', '微信图片_202504092228421.jpg')

    assert result['ok'] is False
    assert result['verified']['filename_matched'] is False
    assert result['reason'] == '欧盟外包装图未匹配配置文件名：微信图片_202504092228421.jpg'
    assert fills == [('外包装/标签实拍图-欧盟', '微信图片_202504092228421.jpg')]


def test_eu_outer_package_accepts_exact_image_bank_selection_when_row_hides_filename(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    states = iter([
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
    ])
    filename = '微信图片_202504092228421.jpg'
    clears = []

    monkeypatch.setattr(flow, '_image_slot_state', lambda page, label, filename: next(states))
    monkeypatch.setattr(flow, '_remove_image_slot_existing_image', lambda page, label: clears.append(label) or {'ok': True})
    monkeypatch.setattr(
        flow,
        '_fill_image_slot_asset_by_filename',
        lambda page, label, filename: {
            'ok': True,
            'selection': {
                'search': {'filled': True, 'search_text': filename},
                'picked': {'ok': True, 'text': filename},
            },
        },
    )

    result = flow._fill_image_slot_by_filename(page, '外包装/标签实拍图-欧盟', filename)

    assert result['ok'] is True
    assert result['selected_configured_filename'] is True
    assert result['verified']['filename_matched'] is False
    assert clears == ['外包装/标签实拍图-欧盟']


def test_eu_outer_package_rejects_existing_image_when_safe_clear_is_blocked(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    filename = '微信图片_202504092228421.jpg'
    fills = []

    monkeypatch.setattr(
        flow,
        '_image_slot_state',
        lambda page, label, filename: {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
    )
    monkeypatch.setattr(
        flow,
        '_remove_image_slot_existing_image',
        lambda page, label: {'ok': False, 'reason': '未找到确认按钮：确定/确认/删除'},
    )
    monkeypatch.setattr(flow, '_fill_image_slot_asset_by_filename', lambda page, label, filename: fills.append(filename) or {'ok': True})

    result = flow._fill_image_slot_by_filename(page, '外包装/标签实拍图-欧盟', filename)

    assert result['ok'] is False
    assert result['reason'] == '未找到确认按钮：确定/确认/删除'
    assert fills == []


def test_eu_outer_package_rejects_cdn_only_row_without_selection_evidence(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    filename = '微信图片_202504092228421.jpg'
    states = iter([
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
        {'ok': True, 'filled_image_count': 1, 'filename_matched': False},
    ])

    monkeypatch.setattr(flow, '_image_slot_state', lambda page, label, filename: next(states))
    monkeypatch.setattr(flow, '_remove_image_slot_existing_image', lambda page, label: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_fill_image_slot_asset_by_filename',
        lambda page, label, filename: {
            'ok': True,
            'filename': filename,
            'selection': {
                'filename': filename,
                'search': {'filled': True, 'search_text': filename},
                'picked': {'ok': True, 'text': 'cdn-only'},
            },
        },
    )

    result = flow._fill_image_slot_by_filename(page, '外包装/标签实拍图-欧盟', filename)

    assert result['ok'] is False
    assert result['reason'] == f'欧盟外包装图未匹配配置文件名：{filename}'


def test_fill_media_assets_marks_eu_outer_package_manual_required_when_picker_is_unavailable(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()

    state = flow._fill_media_assets_on_page(page, {'eu_outer_package_filename': '微信图片_202504092228421.jpg'})

    assert state['stage'] == 'media_assets_filled'
    assert state['published'] is False
    assert '发布前需人工补齐' in state['message']
    eu_result = state['fill_result']['eu_outer_package_image']
    assert eu_result['ok'] is True
    assert eu_result['manual_required'] is True
    assert eu_result['publish_ready'] is False
    assert '发布前需人工补齐' in eu_result['reason']
    joined_scripts = '\n'.join(page.scripts)
    assert '外包装/标签实拍图-欧盟' in joined_scripts
    assert '图片银行' in joined_scripts


def test_manual_required_eu_outer_package_is_not_publish_ready_verification(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    verified = flow._media_result_has_verified_eu_outer_package({
        'fill_result': {
            'eu_outer_package_image': {
                'ok': True,
                'manual_required': True,
                'publish_ready': False,
                'reason': '发布前需人工补齐',
            }
        }
    })

    assert verified is False


def test_image_slot_picker_does_not_click_existing_preview_images(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageSlotPickerScriptPage()

    flow._open_image_slot_picker(page, '外包装/标签实拍图-欧盟')

    assert 'single-image' not in page.script
    assert 'img-box' not in page.script
    assert "x.cls.includes('single-image')" not in page.script
    assert "x.el.tagName === 'IMG'" not in page.script
    assert '添加图片' in page.script
    assert '图片银行' in page.script


def test_image_slot_picker_supports_left_tool_icon_and_empty_add_slot(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageSlotPickerScriptPage()

    flow._open_image_slot_picker(page, '外包装/标签实拍图-欧盟')

    assert 'isLowerLeftTool' in page.script
    assert 'isEmptyAddSlot' in page.script
    assert 'isRightSideDanger' in page.script
    assert 'addPlaceholder' in page.script
    assert 'placeholder:true' in page.script
    assert '图片银行（速卖通）' in page.script


def test_eu_image_slot_flow_requires_smt_image_bank_menu(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageSlotFlowPage()

    monkeypatch.setattr(flow, '_select_image_bank_asset_by_filename', lambda page, filename: {'ok': True, 'filename': filename})

    result = flow._fill_image_slot_asset_by_filename(page, '外包装/标签实拍图-欧盟', '微信图片_202504092228421.jpg')

    assert result['ok'] is True
    assert any('requireMenu' in script for script in page.scripts)
    assert result['image_bank']['clicked']['text'] == '图片银行（速卖通）'


def test_image_slot_picker_retries_after_notice_modal_dismissed(monkeypatch, tmp_path):
    class NoticeBlockedImageSlotPage(DummyMediaNoEntryPage):
        def __init__(self):
            super().__init__()
            self.click_count = 0
            self.clicked = []

        def evaluate(self, script, arg=None):
            self.scripts.append(script)
            if 'labelCandidates' in script:
                return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
            if 'hasBankMenu' in script:
                return {
                    'ok': self.click_count >= 2,
                    'has_bank_menu': self.click_count >= 2,
                    'has_image_dialog': False,
                    'body_excerpt': '重要提醒 下一条 忽略提示',
                }
            return {'ok': False, 'reason': 'unexpected script'}

        @property
        def mouse(self):
            return self

        def click(self, x, y):
            self.click_count += 1
            self.clicked.append((x, y))

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = NoticeBlockedImageSlotPage()
    dismiss_calls = []

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: dismiss_calls.append(True) or (1 if len(dismiss_calls) == 1 else 0))

    result = flow._open_image_slot_picker(page, '外包装/标签实拍图-欧盟')

    assert result['ok'] is True
    assert page.click_count == 2
    assert len(dismiss_calls) == 2


def test_image_slot_picker_does_not_treat_image_space_notice_as_image_bank(tmp_path):
    class ImageSpaceNoticePage(DummyMediaNoEntryPage):
        def __init__(self):
            super().__init__()
            self.clicked = []
            self.opened_script = ''

        def evaluate(self, script, arg=None):
            self.scripts.append(script)
            if 'labelCandidates' in script:
                return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}}
            if 'dangerousTerms' in script:
                return {'visible': False}
            if 'hasBankMenu' in script:
                self.opened_script = script
                return {
                    'ok': False,
                    'has_bank_menu': False,
                    'has_image_dialog': False,
                    'body_excerpt': '重要提醒 您购买的 图片空间 将在2天后 过期 忽略提示',
                }
            return {'ok': False, 'reason': 'unexpected script'}

        @property
        def mouse(self):
            return self

        def click(self, x, y):
            self.clicked.append((x, y))

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = ImageSpaceNoticePage()

    result = flow._open_image_slot_picker(page, '外包装/标签实拍图-欧盟')

    assert result['ok'] is False
    assert "text.includes('图片') || text.includes('上传')" not in page.opened_script
    assert "text.includes('请输入图片名称')" in page.opened_script


def test_image_slot_asset_reopens_slot_when_bank_menu_is_blocked_by_notice(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyMediaNoEntryPage()
    open_calls = []
    bank_results = [
        {'ok': False, 'reason': '未看到图片银行（速卖通）菜单'},
        {'ok': True, 'clicked': {'text': '图片银行（速卖通）'}},
    ]
    dismiss_calls = []

    monkeypatch.setattr(flow, '_open_image_slot_picker', lambda target_page, slot_label: open_calls.append(slot_label) or {'ok': True, 'target': {'text': '添加图片'}})
    monkeypatch.setattr(flow, '_open_smt_image_bank_from_picker', lambda target_page, require_menu=False: bank_results.pop(0))
    monkeypatch.setattr(flow, '_select_image_bank_asset_by_filename', lambda target_page, filename: {'ok': True, 'filename': filename})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: dismiss_calls.append(True) or 1)

    result = flow._fill_image_slot_asset_by_filename(page, '外包装/标签实拍图-欧盟', '微信图片_202504092228421.jpg')

    assert result['ok'] is True
    assert open_calls == ['外包装/标签实拍图-欧盟', '外包装/标签实拍图-欧盟']
    assert result['picker']['retried_after_missing_bank_menu'] is True
    assert dismiss_calls


def test_open_smt_image_bank_requires_menu_or_existing_bank_dialog(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyBankMenuScriptPage()

    result = flow._open_smt_image_bank_from_picker(page)

    assert result['ok'] is False
    assert '图片银行' in result['reason']
    assert 'already_open' not in result


def test_open_smt_image_bank_stops_when_required_menu_missing_even_if_dialog_exists(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyBankMenuScriptPage()
    page.ready_after_missing_menu = True

    result = flow._open_smt_image_bank_from_picker(page, require_menu=True)

    assert result['ok'] is False
    assert result['reason'] == '未看到图片银行（速卖通）菜单'
    assert page.calls == 1


def test_select_image_bank_asset_requires_search_box(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyImageBankNoSearchInputPage()

    result = flow._select_image_bank_asset_by_filename(page, '微信图片_202504092228421.jpg')

    assert result['ok'] is False
    assert result['reason'] == '图片银行未找到可输入图片名称的搜索框'


def test_click_safe_modal_button_rejects_publish_confirmation(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySafeModalPage({'ok': False, 'reason': '检测到危险弹窗：继续发布'})

    result = flow._click_safe_modal_button(page, ['确定'])

    assert result['ok'] is False
    assert '继续发布' in result['reason']
    assert page.clicked == []


def test_click_safe_modal_button_dismisses_notice_modal_and_retries(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySafeModalPage([
        {'ok': False, 'reason': '未找到确认按钮：确定/确认/删除', 'modal_text': '小秘公告2026 活动通知'},
        {'ok': True, 'text': '确定', 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}},
    ])
    dismissed = []

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: dismissed.append(True) or 1)

    result = flow._click_safe_modal_button(page, ['确定', '确认', '删除'])

    assert result['ok'] is True
    assert dismissed == [True]
    assert page.clicked == [(25.0, 40.0)]


def test_fill_customs_supervision_selects_keychain_and_confirms_twice(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyCustomsPage()

    monkeypatch.setattr(
        flow,
        '_click_ant_option_near_rect',
        lambda page, priorities, anchor_rect, required=True: {'ok': True, 'text': '钥匙扣(keychain)'},
    )

    state = flow._fill_customs_supervision_attribute(page, ['钥匙扣', 'keychain'])

    assert state['ok'] is True
    assert state['selected'] == 'active-option'
    assert state['confirm_steps'] == 3
    assert page.waited_for_function is True
    assert page.keyboard.presses == ['Enter']
    assert len(page.mouse.clicks) == 6


def test_fill_customs_supervision_accepts_existing_update_state(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyConfiguredCustomsPage()

    state = flow._fill_customs_supervision_attribute(page, ['钥匙扣', 'keychain'])

    assert state['ok'] is True
    assert state['already_configured'] is True
    assert state['state']['has_tax_code'] is True
    assert page.mouse.clicks == []
    assert '更新海关监管' in page.script
    assert '添加全球海关监管属性' in page.script
    assert "valueAfterAny(['种类(Kind)', '种类'])" in page.script
    assert "replace(/^[：:]/" in page.script


def test_fill_customs_supervision_refreshes_existing_english_product_name(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEnglishCustomsUpdatePage()

    state = flow._fill_customs_supervision_attribute(page, ['钥匙扣', 'keychain'])

    assert state['ok'] is True
    assert state['already_configured'] is True
    assert state['updated_existing'] is True
    assert state['state']['has_product_name'] is True
    assert page.mouse.clicks == [(477.0, 623.0)]
    assert page.timeouts == [1500]
    assert any("Productname" in script for script in page.scripts)


def test_save_only_rejects_publish_buttons(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({'ok': False, 'reason': '命中发布按钮：保存并发布', 'published': False})

    state = flow._save_only_on_page(page)

    assert state['stage'] == 'save_only_failed'
    assert state['published'] is False
    assert '保存并发布' in state['message']


def test_save_only_dismisses_blocking_modals_before_locating_save(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyNetworkPage()
    calls = []

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: calls.append('dismiss') or 1)

    state = flow._save_only_on_page(page)

    assert state['stage'] == 'save_only'
    assert calls == ['dismiss']
    assert page.evaluate_calls == 2


def test_save_only_stops_when_blocking_modal_remains_after_dismiss(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyNetworkPage()
    flow._last_dismiss_blocking_modals_trace = [{'clicked': 'modal-close'}]

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: 10)
    monkeypatch.setattr(
        flow,
        '_visible_blocking_modal_state',
        lambda target_page: {'visible': True, 'text': '距离活动结束仅剩 我知道了'},
    )

    state = flow._save_only_on_page(page)

    assert state['stage'] == 'save_only_failed'
    assert page.clicks == []
    assert state['save_result']['reason'] == '保存前弹窗未能关闭'
    assert state['save_result']['blocking_modal']['visible'] is True


def test_save_only_script_checks_publish_risk_before_clicking_save(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyScriptPage()

    state = flow._save_only_on_page(page)

    assert state['stage'] == 'save_only_failed'
    for word in ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布']:
        assert word in page.script
    assert "querySelectorAll('button,a,[role=\"button\"]')" in page.script


def test_save_only_script_prioritizes_exact_save_button_when_publish_button_is_visible(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyScriptPage()

    flow._save_only_on_page(page)

    assert page.script.index("const save = candidates.find") < page.script.index("const forbidden = candidates.find")


def test_save_only_fails_when_success_prompt_missing_after_click(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyVerifyPage({
        'ok': False,
        'clicked': True,
        'reason': '未检测到保存成功提示',
        'success_text': None,
        'published': False,
    })

    state = flow._save_only_on_page(page)

    assert page.evaluate_calls == 2
    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['ok'] is False
    assert '未检测到保存成功提示' in state['message']


def test_save_only_succeeds_when_success_prompt_appears_after_click(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyVerifyPage({
        'ok': True,
        'clicked': True,
        'success_text': '产品编辑成功',
        'published': False,
    })

    state = flow._save_only_on_page(page)

    assert page.evaluate_calls == 2
    assert state['stage'] == 'save_only'
    assert state['save_result']['ok'] is True
    assert state['save_result']['network_events'] == []
    assert state['save_result']['network_save_result'] == {'ok': None, 'reason': '未捕获保存相关接口响应'}


def test_save_only_records_network_success_as_save_evidence(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySaveOnlyNetworkPage()

    state = flow._save_only_on_page(page)

    assert state['stage'] == 'save_only'
    assert page.clicks == [(25.0, 40.0)]
    assert state['save_result']['network_save_result']['ok'] is True
    assert state['save_result']['network_save_result']['method'] == 'POST'
    assert state['save_result']['network_save_result']['code'] == 0
    assert state['save_result']['network_save_result']['msg'] == '产品已保存到「待发布」'
    assert state['save_result']['network_events'][0]['method'] == 'POST'
    assert state['save_result']['network_events'][0]['status'] == 200
    assert state['save_result']['network_events'][0]['json']['msg'] == '产品已保存到「待发布」'


def test_network_save_result_prefers_real_add_json_over_related_history_calls(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._network_save_result([
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/addProductBrandHistory.json',
            'method': 'POST',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': 123},
        },
    ])

    assert result['ok'] is True
    assert result['url'] == 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    assert result['msg'] == '您的产品编辑成功！'
