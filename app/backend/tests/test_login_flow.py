from pathlib import Path
import asyncio
import ctypes
import hashlib
import json
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from src.execution import dxm_login_flow as dxm_login_flow_module
from src.execution.browser_agent_protocol import (
    MutationCommandContractError,
    canonical_frozen_target_identity,
)
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import (
    DxmLoginFlow,
    FrozenTargetIdentityError,
    MutationAuthorizationError,
    WORKFLOW_READY_TERMS,
    WORKFLOW_TARGETS,
)
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


def _frozen_product_target(
    product_id: str,
    *,
    store_name: str = 'Alpha Store',
    source_url: str = 'https://detail.1688.com/offer/1013604102950.html',
) -> dict[str, object]:
    store_fingerprint = hashlib.sha256(
        json.dumps(
            {'source': 'structured_store_cell', 'store_name': store_name},
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest().upper()
    return {
        'schema_version': 'dxm_draft_box_target.v1',
        'store_fingerprint': store_fingerprint,
        'stable_identity': {
            'kind': 'product_id',
            'value': product_id,
            'fingerprint': hashlib.sha256(f'product_id:{product_id}'.encode('utf-8')).hexdigest().upper(),
        },
        'source_urls': [source_url],
    }


def _save_only_kwargs() -> dict[str, object]:
    return {
        'target_identity': _frozen_product_target('130658341178856048'),
        'store_name': 'Alpha Store',
        'baseline_field_integrity': {
            'ok': True,
            'kind': 'structured_nonempty_form_state',
            'field_count': 1,
            'nonempty_field_count': 1,
            'sha256': 'B' * 64,
        },
        'required_readback_complete': True,
    }


def _legacy_explicit_editor_defaults(**overrides: object) -> dict[str, object]:
    """Keep legacy page-unit fixtures explicit under the frozen execution contract."""
    values: dict[str, object] = {
        'category_keyword': 'Action Figures',
        'category_match': 'Action Figures',
        'title_override': 'Marvel Action Figure Collectible Toy',
        'declared_value': '5.00',
        'stock': '100',
        'weight': '0.03',
        'length': '10',
        'width': '10',
        'height': '2',
        'gross_weight': '0.03',
        'delivery_days': '7',
        'freight_template_priorities': ['40g普货包裹'],
        'service_template_priorities': ['Service Template for New Sellers'],
        'eu_responsible_priorities': ['EU Responsible Person'],
        'manufacturer_priorities': ['Manufacturer'],
        'customs_product_name_priorities': ['Action Figure'],
        'is_original_box': '否',
        'logistics_attribute': '普货',
        'tax_quote_text': '不含关税报价',
        'sku_code': 'SKU-001',
        'retail_price': '58.82',
        'jit_stock': '100',
        'product_price': '49.00',
        'supply_price': '48.62',
    }
    values.update(overrides)
    return values


def _complete_editor_defaults_state(**overrides: object) -> dict[str, object]:
    """Return the exact post-fill readback required by the current editor contract."""
    defaults = _legacy_explicit_editor_defaults()
    values: dict[str, object] = {
        'title': defaults['title_override'],
        'declared_value': defaults['declared_value'],
        'stock': defaults['stock'],
        'weight': defaults['weight'],
        'length': defaults['length'],
        'width': defaults['width'],
        'height': defaults['height'],
        'delivery_days': defaults['delivery_days'],
        'gross_weight': defaults['gross_weight'],
        'sku_code': defaults['sku_code'],
        'freight_template': defaults['freight_template_priorities'][0],
        'service_template': defaults['service_template_priorities'][0],
        'category_text': defaults['category_match'],
    }
    values.update(overrides)
    return {
        'missing': [],
        'values': values,
        'customs_configured': True,
        'category_selected': True,
        'category_text': values['category_text'],
    }


def _applied_attribute_reference_template() -> dict[str, object]:
    """Return exact evidence that the configured attribute template is already applied."""
    name = '立牌类谷子属性模板'
    return {
        'attribute_info': {
            'ok': True,
            'section': 'attribute_info',
            'names': [name],
            'required': True,
            'expected_value': name,
            'value_after': name,
            'exact_readback': True,
        },
    }


def _complete_save_network_capture(events: list[dict[str, object]] | None = None) -> dict[str, object]:
    captured = events or [{
        'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
        'method': 'POST',
        'status': 200,
        'mutation_kind': 'save_request',
        'request_observed': True,
        'json': {'code': 0, 'msg': '保存成功'},
    }]
    return {
        'events': captured,
        'network_audit': {
            'scope': 'same_origin_write_window',
            'complete': True,
            'window_closed': True,
            'registered_listener_count': 2,
            'removed_listener_count': 2,
            'mutation_request_count': 1,
            'save_request_count': 1,
            'other_mutation_request_count': 0,
            # A SAVE_ONLY proof is only valid after the current category/schema
            # has been re-read through the read-only endpoint.
            'read_only_schema_request_count': 1,
            'publish_request_count': 0,
        },
        'publish_signal': {
            'detected': False,
            'kind': 'network_route_classification',
            'request_count': 0,
        },
    }


def _bind_frozen_editor_action(
    flow,
    monkeypatch,
    *,
    product_id: str = '130658341178856048',
    store_name: str = 'Dang Kang',
    source_url: str = 'https://detail.1688.com/offer/1013604102950.html',
) -> dict[str, object]:
    kwargs = _frozen_action_kwargs(
        product_id,
        store_name=store_name,
        source_url=source_url,
    )
    normalized = canonical_frozen_target_identity(kwargs['target_identity'], store_name=store_name)
    digest = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest().upper()
    state = flow.get_state()
    state['target_identity_sha256'] = digest
    flow._write_state(state)
    readback = _frozen_identity_readback(kwargs['target_identity'], store_name=store_name)
    monkeypatch.setattr(flow, '_require_frozen_editor_identity', lambda *_args, **_kwargs: dict(readback))
    monkeypatch.setattr(flow, '_require_frozen_product_page_identity', lambda *_args, **_kwargs: dict(readback))
    return kwargs


def _frozen_action_kwargs(
    product_id: str = '130658341178856048',
    *,
    store_name: str = 'Dang Kang',
    source_url: str = 'https://detail.1688.com/offer/1013604102950.html',
) -> dict[str, object]:
    target_identity = _frozen_product_target(
        product_id,
        store_name=store_name,
        source_url=source_url,
    )
    return {
        'target_identity': target_identity,
        'target_source_urls': list(target_identity['source_urls']),
    }


def _frozen_identity_readback(
    target_identity: dict[str, object],
    *,
    store_name: str = 'Dang Kang',
) -> dict[str, object]:
    normalized = canonical_frozen_target_identity(
        target_identity,
        store_name=store_name,
    )
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest().upper()
    return {
        'target_identity': normalized,
        'target_identity_sha256': digest,
        'target_identity_evidence': {'ok': True, 'kind': 'test_frozen_exact_identity'},
        'product_identity_match': True,
        'store_identity_match': True,
        'store_match': True,
        'source_identity_match': True,
    }


def test_canonical_frozen_target_identity_rejects_pure_alpha_product_id():
    with pytest.raises(MutationCommandContractError) as exc_info:
        canonical_frozen_target_identity(
            _frozen_product_target('abcde'),
            store_name='Alpha Store',
        )

    assert exc_info.value.reason_code == 'MUTATION_TARGET_INVALID'


@pytest.mark.parametrize('product_id', ['abc1e', '130658341178856048'])
def test_canonical_frozen_target_identity_accepts_product_id_with_digit(product_id):
    normalized = canonical_frozen_target_identity(
        _frozen_product_target(product_id),
        store_name='Alpha Store',
    )

    assert normalized is not None
    assert normalized['stable_identity']['value'] == product_id


def test_pre_edit_frozen_target_identity_rejects_pure_alpha_product_id(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with pytest.raises(FrozenTargetIdentityError) as exc_info:
        flow._normalize_frozen_target_identity(
            _frozen_product_target('abcde'),
            store_name='Alpha Store',
        )

    assert exc_info.value.reason_code == 'FROZEN_TARGET_PRODUCT_ID_INVALID'


@pytest.mark.parametrize('product_id', ['abc1e', '130658341178856048'])
def test_pre_edit_frozen_target_identity_accepts_product_id_with_digit(tmp_path, product_id):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    normalized, _digest = flow._normalize_frozen_target_identity(
        _frozen_product_target(product_id),
        store_name='Alpha Store',
    )

    assert normalized['stable_identity']['value'] == product_id


def _arm_editor_action_test(flow, monkeypatch, tmp_path, *, action='save_only'):
    flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 'test'})
    frozen_target = canonical_frozen_target_identity(
        _save_only_kwargs()['target_identity'],
        store_name='Alpha Store',
    )
    monkeypatch.setattr(
        flow,
        '_require_frozen_product_page_identity',
        lambda *_args, **_kwargs: frozen_target,
    )
    monkeypatch.setattr(
        flow,
        '_capture_save_field_integrity_snapshot',
        lambda *_args, **_kwargs: dict(_save_only_kwargs()['baseline_field_integrity']),
    )
    proof_path = (tmp_path / f'{action}-proof.png').resolve()
    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', lambda *_args, **_kwargs: {
        'path': str(proof_path), 'sha256': 'A' * 64, 'size': 1,
    })
    monkeypatch.setattr(flow, '_artifact_url', lambda _path: f'/artifacts/{action}-proof.png')


def _execute_authorized_operation(context, operation):
    pre_dispatch_guard = context.get('_pre_dispatch_guard')
    if callable(pre_dispatch_guard):
        guard_result = pre_dispatch_guard()
        guard_ok = guard_result is True or (
            isinstance(guard_result, dict) and guard_result.get('ok') is True
        )
        if not guard_ok:
            return {
                'ok': False,
                'executed': False,
                'reason_code': 'MUTATION_TARGET_DRIFT',
                'guard_result': guard_result,
            }
    operation_result = operation()
    return {
        'ok': True,
        'executed': True,
        'operation_result': operation_result,
        'reason_code': 'OK',
    }


class _FakeExactSaveElementHandle:
    """Minimal ElementHandle seam for exact-save dispatch contract tests."""

    def __init__(self, events: list[str], *, dispatch_error: Exception | None = None):
        self.events = events
        self.dispatch_error = dispatch_error
        self.evaluate_calls = 0

    def as_element(self):
        return self

    def evaluate(self, _script):
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            self.events.append('target_guard')
            return {
                'ok': True,
                'text': '保存',
                'at_point_text': '保存',
                'exact_save_count': 1,
                'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 20},
                'reason': None,
            }
        self.events.append('dispatch')
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return {'ok': True, 'dispatched': True, 'method': 'dom_exact_text'}

    def dispose(self):
        return None


class _FakeExactSaveJSHandle:
    def __init__(self, element: _FakeExactSaveElementHandle):
        self.element = element

    def as_element(self):
        return self.element

    def dispose(self):
        return None


def _install_exact_save_handle(page, events: list[str], *, dispatch_error: Exception | None = None):
    element = _FakeExactSaveElementHandle(events, dispatch_error=dispatch_error)
    page.evaluate_handle = lambda _script: _FakeExactSaveJSHandle(element)
    return element


class DummyLoginFlow:
    def __init__(self):
        self.started_with = None
        self.continued = False
        self.navigated_to = None
        self.performed_action = None
        self.state = {
            'ok': False,
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
            'ok': False,
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
            'ok': True,
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
        wait_result = {
            'ready': True,
            'expected_identity': target,
            'loading': False,
            'readiness': {
                'ok': True,
                'expected_identity': target,
                'loading': False,
                'business_marker': target,
                'blocking_modal': None,
            },
        }
        self.state = {
            'ok': True,
            'stage': 'workflow_navigation',
            'label': '已到达业务页',
            'message': f'已导航到 {target}',
            'next_action': '继续执行当前业务节点。',
            'requires_user_action': False,
            'screenshot_url': f'/artifacts/screenshots/{target}.png',
            'page_title': target,
            'page_url': f'https://www.dianxiaomi.com/{target}',
            'current_nav': target,
            'wait_result': wait_result,
            'navigation_result': {'wait_result': wait_result},
        }
        return self.state

    def perform_draft_box_action(
        self,
        action: str,
        note_text: str | None = None,
        product_query: str | None = None,
        store_name: str | None = None,
        target_source_urls: list[str] | None = None,
        target_identity: dict[str, object] | None = None,
    ):
        self.performed_action = (
            action,
            note_text,
            product_query,
            store_name,
            target_source_urls,
            target_identity,
        )
        if action == 'edit':
            self.state = {
                'ok': True,
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
            'ok': True,
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


def test_login_start_reports_explicit_reason_and_reader_not_ready(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')
    monkeypatch.setattr(flow, '_open_login_page_and_fill', lambda *_args: {
        'page_title': '店小秘官网登录页',
        'page_url': 'https://www.dianxiaomi.com/',
        'browser_visible': True,
    })

    state = flow.start_login('demo-user', 'demo-pass')

    assert state['reason_code'] == 'LOGIN_INTERACTION_REQUIRED'
    assert state['logged_in'] is False
    assert state['reader_ready'] is False


def test_login_start_publishes_opening_reason_before_browser_work_finishes(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')
    browser_started = threading.Event()
    release_browser = threading.Event()

    def blocking_open(*_args):
        browser_started.set()
        release_browser.wait(timeout=2)
        return {
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
            'login_check': {
                'logged_in': False,
                'business_page_ready': False,
                'loading': False,
            },
            'browser_visible': True,
        }

    monkeypatch.setattr(flow, '_open_login_page_and_fill', blocking_open)
    worker = threading.Thread(target=lambda: flow.start_login('demo-user', 'demo-pass'))

    worker.start()
    assert browser_started.wait(timeout=1)
    opening_state = flow.get_state()
    release_browser.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert opening_state['reason_code'] == 'LOGIN_OPENING'
    assert opening_state['logged_in'] is False
    assert opening_state['reader_ready'] is False


def test_login_start_reuses_authenticated_home_and_returns_reader_ready(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')
    monkeypatch.setattr(flow, '_open_login_page_and_fill', lambda *_args: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'browser_visible': True,
        'visible_logged_in': True,
        'reader_ready': True,
        'reader_reason_code': 'LOGIN_READER_READY',
        'browser_session_id': 'session-1',
        'account_ref': 'account-1',
    })

    state = flow.start_login('demo-user', 'demo-pass')

    assert state['ok'] is True
    assert state['stage'] == 'login_success'
    assert state['reason_code'] == 'LOGIN_READER_READY'
    assert state['logged_in'] is True
    assert state['reader_ready'] is True
    assert state['browser_session_id'] == 'session-1'
    assert state['account_ref'] == 'account-1'


def test_login_open_preserves_current_authenticated_home_before_navigation(
    monkeypatch,
    tmp_path,
):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')

    class HomePage:
        url = 'https://www.dianxiaomi.com/web/home'

    page = HomePage()
    monkeypatch.setattr(flow, '_ensure_page', lambda: page)
    monkeypatch.setattr(flow, '_page_looks_logged_in', lambda candidate: candidate is page)
    monkeypatch.setattr(flow, '_safe_live_hud_page_title', lambda _page: '店小秘--首页')
    monkeypatch.setattr(flow, '_visible_reader_session_status', lambda: {
        'reader_ready': True,
        'reason_code': 'LOGIN_READER_READY',
        'browser_session_id': 'session-1',
        'account_ref': 'account-1',
    })
    monkeypatch.setattr(
        flow,
        '_goto_sterile',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('authenticated home must not be navigated to the login root')
        ),
    )

    state = flow._open_login_page_and_fill('demo-user', 'demo-pass')

    assert state['visible_logged_in'] is True
    assert state['reader_ready'] is True
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'


def test_login_start_discards_partial_playwright_runtime_after_launch_failure(
    monkeypatch,
    tmp_path,
):
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime-state.json')

    class PartialPlaywright:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    partial = PartialPlaywright()

    def fail_after_playwright_start(*_args):
        flow._playwright = partial
        flow._browser_session_thread_id = threading.get_ident()
        raise RuntimeError('DevTools endpoint unavailable')

    monkeypatch.setattr(flow, '_open_login_page_and_fill', fail_after_playwright_start)

    state = flow.start_login('demo-user', 'demo-pass')

    assert state['reason_code'] == 'LOGIN_BROWSER_START_FAILED'
    assert partial.stopped is True
    assert flow._playwright is None
    assert flow._browser_session_thread_id is None


def test_persisted_reader_ready_state_is_invalidated_without_current_runtime_session(tmp_path):
    state_file = tmp_path / 'runtime-state.json'
    state_file.write_text(json.dumps({
        'ok': True,
        'stage': 'login_success',
        'reason_code': 'LOGIN_READER_READY',
        'logged_in': True,
        'reader_ready': True,
        'browser_session_id': 'previous-process-session',
        'account_ref': 'previous-account',
        'page_url': 'https://www.dianxiaomi.com/web/home',
    }), encoding='utf-8')

    restarted_flow = DxmLoginFlow(DummyLiveClient(), state_file=state_file)
    state = restarted_flow.get_state()

    assert state['ok'] is False
    assert state['reason_code'] == 'BROWSER_SESSION_UNAVAILABLE'
    assert state['logged_in'] is False
    assert state['reader_ready'] is False


def test_live_state_revokes_cached_reader_ready_when_visible_session_has_died(monkeypatch, tmp_path):
    state_file = tmp_path / 'runtime-state.json'
    state_file.write_text(json.dumps({
        'ok': True,
        'stage': 'login_success',
        'reason_code': 'LOGIN_READER_READY',
        'logged_in': True,
        'reader_ready': True,
        'browser_session_id': 'current-process-session',
        'account_ref': 'current-account',
        'page_url': 'https://www.dianxiaomi.com/web/home',
    }), encoding='utf-8')
    flow = DxmLoginFlow(DummyLiveClient(), state_file=state_file)
    flow._browser_session_generation = 'current-process-session'
    flow._browser_session_context_id = 1
    flow._browser_session_browser_id = 2

    def missing_session():
        from src.services.dxm_draft_reader import DxmDraftReaderError
        raise DxmDraftReaderError(
            'BROWSER_SESSION_UNAVAILABLE',
            'visible session disconnected',
        )

    monkeypatch.setattr(flow, '_draft_reader_session', missing_session)

    state = flow.get_live_state()

    assert state['ok'] is False
    assert state['reason_code'] == 'BROWSER_SESSION_UNAVAILABLE'
    assert state['logged_in'] is False
    assert state['reader_ready'] is False
    assert state['browser_session_id'] is None
    assert state['account_ref'] is None
    assert json.loads(state_file.read_text(encoding='utf-8'))['reader_ready'] is False


def test_live_state_promotes_authenticated_home_after_async_login_redirect(monkeypatch, tmp_path):
    state_file = tmp_path / 'runtime-state.json'
    state_file.write_text(json.dumps({
        'ok': False,
        'stage': 'login_failed',
        'reason_code': 'LOGIN_REQUIRED',
        'logged_in': False,
        'reader_ready': False,
        'page_url': 'https://www.dianxiaomi.com/',
    }), encoding='utf-8')
    flow = DxmLoginFlow(DummyLiveClient(), state_file=state_file)

    class HomePage:
        url = 'https://www.dianxiaomi.com/web/home?ts=1'

    home_page = HomePage()
    monkeypatch.setattr(flow, '_promote_dxm_page_from_connected_browser', lambda: home_page)
    monkeypatch.setattr(flow, '_page_looks_logged_in', lambda page: page is home_page)
    monkeypatch.setattr(flow, '_visible_reader_session_status', lambda: {
        'reader_ready': True,
        'reason_code': 'LOGIN_READER_READY',
        'browser_session_id': 'visible-session',
        'account_ref': 'account-proof',
    })

    state = flow.get_live_state()

    assert state['ok'] is True
    assert state['reason_code'] == 'LOGIN_READER_READY'
    assert state['logged_in'] is True
    assert state['reader_ready'] is True
    assert state['page_url'] == home_page.url
    assert state['browser_session_id'] == 'visible-session'
    assert state['account_ref'] == 'account-proof'


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


def test_live_status_uses_the_same_visible_playwright_session_as_login_and_reader(monkeypatch):
    class VisibleSessionFlow(DummyLoginFlow):
        def __init__(self):
            super().__init__()
            self.state = {
                'ok': False,
                'stage': 'login_required',
                'reason_code': 'DXM_PAGE_REQUIRED',
                'logged_in': False,
                'reader_ready': False,
                'page_url': 'about:blank',
            }

        def check_visible_login_state(self):
            raise AssertionError('live-status must not start another Playwright operation')

        def probe_visible_session(self):
            raise AssertionError('live-status must not start another Playwright operation')

        def get_live_state(self):
            return self.state

    class ForbiddenSplitProbe:
        def probe_session(self):
            raise AssertionError('live-status must not use a second login-state source')

    monkeypatch.setattr(main_module, 'login_flow', VisibleSessionFlow())
    monkeypatch.setattr(main_module, 'live_client', ForbiddenSplitProbe())
    monkeypatch.setattr(main_module, '_assert_batch_browser_available', lambda: None)

    result = main_module.dxm_live_status()

    assert result['logged_in'] is False
    assert result['reader_ready'] is False
    assert result['reason_code'] == 'DXM_PAGE_REQUIRED'


def test_live_status_fails_fast_instead_of_waiting_behind_login(monkeypatch):
    class BlockingLoginFlow(DummyLoginFlow):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def start_login(self, username: str, password: str):
            self.started.set()
            self.release.wait(timeout=2)
            return super().start_login(username, password)

        def check_visible_login_state(self):
            return {'ok': False, 'stage': 'login_required', 'reason_code': 'LOGIN_REQUIRED'}

    flow = BlockingLoginFlow()
    monkeypatch.setattr(main_module, 'login_flow', flow)
    monkeypatch.setattr(main_module, '_assert_batch_browser_available', lambda: None)
    login_thread = threading.Thread(
        target=lambda: main_module.dxm_login_start(LoginStartRequest(username='u', password='p')),
    )
    status_result: list[dict] = []
    status_thread = threading.Thread(target=lambda: status_result.append(main_module.dxm_live_status()))

    login_thread.start()
    assert flow.started.wait(timeout=1)
    status_thread.start()
    status_thread.join(timeout=0.2)
    returned_without_waiting = not status_thread.is_alive()
    flow.release.set()
    login_thread.join(timeout=2)
    status_thread.join(timeout=2)

    assert returned_without_waiting is True
    assert status_result[0]['reason_code'] == 'DXM_SESSION_BUSY'
    assert status_result[0]['reader_ready'] is False


def test_draft_reader_fails_fast_instead_of_waiting_behind_login(monkeypatch):
    class BlockingFlow(DummyLoginFlow):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def start_login(self, username: str, password: str):
            self.started.set()
            self.release.wait(timeout=2)
            return super().start_login(username, password)

        def read_draft_shops(self):
            return {
                'browser_session_id': 'session',
                'account_ref': 'account',
                'payload': {'code': 0, 'data': {'shopMap': {}}},
            }

    flow = BlockingFlow()
    monkeypatch.setattr(main_module, 'login_flow', flow)
    monkeypatch.setattr(main_module, 'workflow_adapter', DxmWorkflowAdapter(flow))
    monkeypatch.setattr(main_module, '_assert_batch_browser_available', lambda: None)
    login_thread = threading.Thread(
        target=lambda: main_module.dxm_login_start(LoginStartRequest(username='u', password='p')),
    )
    reader_errors: list[Exception] = []
    reader_thread = threading.Thread(
        target=lambda: _capture_exception(main_module.dxm_draft_reader_shops, reader_errors),
    )

    login_thread.start()
    assert flow.started.wait(timeout=1)
    reader_thread.start()
    reader_thread.join(timeout=0.2)
    returned_without_waiting = not reader_thread.is_alive()
    flow.release.set()
    login_thread.join(timeout=2)
    reader_thread.join(timeout=2)

    assert returned_without_waiting is True
    assert len(reader_errors) == 1
    assert getattr(reader_errors[0], 'status_code', None) == 409
    assert reader_errors[0].detail['reason_code'] == 'DXM_SESSION_BUSY'


def _capture_exception(callback, target: list[Exception]) -> None:
    try:
        callback()
    except Exception as exc:  # noqa: BLE001 - thread result is asserted by the caller.
        target.append(exc)


def test_cdp_attach_reuses_the_existing_dxm_tab_instead_of_about_blank(tmp_path):
    class Page:
        def __init__(self, url: str):
            self.url = url

        def is_closed(self):
            return False

    class Context:
        def __init__(self):
            self.pages = [Page('about:blank'), Page('https://www.dianxiaomi.com/web/home')]

        def is_closed(self):
            return False

        def on(self, *_args):
            return None

    class Browser:
        def __init__(self):
            self.contexts = [Context()]

        def is_connected(self):
            return True

        def on(self, *_args):
            return None

    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime.json')
    flow._browser = Browser()

    page = flow._page_from_connected_external_browser(profile_dir=tmp_path, port=3386)

    assert page.url == 'https://www.dianxiaomi.com/web/home'


def test_visible_session_probe_reports_about_blank_without_opening_or_navigating(monkeypatch, tmp_path):
    class Page:
        url = 'about:blank'

        def is_closed(self):
            return False

    class Context:
        def is_closed(self):
            return False

    class Browser:
        def is_connected(self):
            return True

    page = Page()
    context = Context()
    page.context = context
    flow = DxmLoginFlow(DummyLiveClient(), state_file=tmp_path / 'runtime.json')
    flow._page = page
    flow._context = context
    flow._browser = Browser()
    flow._browser_session_thread_id = threading.get_ident()
    flow._browser_session_generation = 'visible-session'
    flow._browser_session_context_id = id(context)
    flow._browser_session_browser_id = id(flow._browser)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_ensure_page', lambda: pytest.fail('status probe must not create a page'))
    monkeypatch.setattr(flow, '_goto_sterile', lambda *_args, **_kwargs: pytest.fail('status probe must not navigate'))

    state = flow.probe_visible_session()

    assert state['logged_in'] is False
    assert state['reader_ready'] is False
    assert state['reason_code'] == 'DXM_PAGE_REQUIRED'
    assert state['page_url'] == 'about:blank'


def test_draft_box_target_opens_status_zero_collection_list():
    assert WORKFLOW_TARGETS['draft_box']['url'].endswith('/web/smt/smtProductList/draft?status=0')


class ScopeConnectedBrowser:
    def is_connected(self):
        return True

    def on(self, *_args):
        return None


class ScopeOpenContext:
    def is_closed(self):
        return False

    def on(self, *_args):
        return None


def _bind_visible_scope_session(flow, page):
    browser = ScopeConnectedBrowser()
    context = ScopeOpenContext()
    page.context = context
    flow._browser = browser
    flow._context = context
    flow._page = page
    flow._browser_session_thread_id = threading.get_ident()
    flow._bind_browser_context_generation(context)
    flow._is_headless = lambda: False
    return flow


class ScopeSnapshotPage:
    url = WORKFLOW_TARGETS['draft_box']['url']

    def __init__(self, snapshot, *, loading=False):
        self.snapshot = snapshot
        self.loading = loading
        self.evaluate_calls = []

    def title(self):
        return '店小秘--速卖通商品箱'

    def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        if 'businessMarkerCount' in script:
            return {
                'readyState': 'complete',
                'loading': self.loading,
                'loadingCount': 1 if self.loading else 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '店铺账号 | 标题/产品ID',
            }
        return self.snapshot


def test_capture_draft_box_scope_returns_ordered_readonly_current_session_snapshot(monkeypatch, tmp_path):
    class DraftBoxPage:
        url = WORKFLOW_TARGETS['draft_box']['url']

        def __init__(self):
            self.evaluate_calls = []

        def title(self):
            return '店小秘--速卖通商品箱'

        def evaluate(self, script, arg=None):
            self.evaluate_calls.append((script, arg))
            if 'businessMarkerCount' in script:
                return {
                    'readyState': 'complete',
                    'loading': False,
                    'loadingCount': 0,
                    'blockingModal': None,
                    'businessMarker': '标题/产品ID',
                    'businessMarkerCount': 1,
                    'bodyExcerpt': '店铺账号 | 标题/产品ID',
                }
            return {
                'items': [
                    {
                        'domIndex': 4,
                        'title': '第一个商品',
                        'productId': 'DXM-2002',
                        'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
                        'storeEvidence': {
                            'store_name': 'Alpha Store',
                            'cell_text': '「Alpha Store」',
                            'source': 'structured_store_cell',
                            'column_index': 2,
                        },
                        'rowText': '第一个商品 产品ID：DXM-2002 「Alpha Store」 编辑',
                    },
                    {
                        'domIndex': 7,
                        'title': '第二个商品',
                        'productId': None,
                        'sourceUrls': ['https://www.aliexpress.com/item/1005011837878679.html?spm=scope'],
                        'storeEvidence': {
                            'store_name': 'Beta Store',
                            'cell_text': '「Beta Store」',
                            'source': 'structured_store_cell',
                            'column_index': 2,
                        },
                        'rowText': '第二个商品 「Beta Store」 编辑',
                    },
                ],
                'visibleRowCount': 2,
                'filter': {
                    'controls': [{'key': 'search', 'value': '待处理', 'source': 'visible_input'}],
                },
                'sort': {
                    'keys': [{'key': '创建时间', 'direction': 'descending'}],
                    'dom_order_authoritative': True,
                },
                'pagination': {
                    'current_page': 1,
                    'page_size': 20,
                    'total_items': 2,
                },
            }

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DraftBoxPage()
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=2)

    assert result['schema'] == 'dxm_draft_box_scope_capture.v1'
    assert result['ok'] is True
    assert result['stage'] == 'draft_box_scope_captured'
    assert [item['position'] for item in result['items']] == [1, 2]
    assert result['items'][0]['stable_identity'] == {
        'kind': 'product_id',
        'value': 'DXM-2002',
        'fingerprint': result['items'][0]['stable_identity']['fingerprint'],
    }
    assert result['items'][1]['stable_identity']['kind'] == 'source_url'
    assert result['items'][1]['stable_identity']['value'].startswith('https://www.aliexpress.com/item/')
    assert result['facts']['pagination']['current_page'] == 1
    assert result['facts']['runtime']['browser_session_id'] == flow.browser_session_id()
    assert result['facts']['runtime']['page_kind'] == 'draft_box'
    assert result['evidence']['kind'] == 'live_dom_snapshot'
    assert len(result['evidence']['dom_sha256']) == 64
    assert result['evidence']['dom_digest'] == hashlib.sha256(
        json.dumps(
            result['evidence']['refs'],
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
    ).hexdigest().upper()
    assert result['zero_write_proof'] == {
        'ok': True,
        'strategy': 'current_visible_page_dom_read',
        'navigation_attempted': False,
        'interactive_action_attempted': False,
        'mutation_dispatch_attempted': False,
    }
    assert len(page.evaluate_calls) == 2


def test_capture_draft_box_scope_uses_one_deterministic_primary_for_multiple_source_urls(tmp_path):
    source_urls = [
        'https://mobile.yangkeduo.com/goods.html?goods_id=877361738237',
        'https://detail.1688.com/offer/1013604102950.html',
    ]
    page = ScopeSnapshotPage({
        'items': [{
            'domIndex': 0,
            'title': '多来源商品',
            'productId': None,
            'sourceUrls': source_urls,
            'storeEvidence': {
                'store_name': 'Alpha Store',
                'cell_text': '「Alpha Store」',
                'source': 'structured_store_cell',
                'column_index': 2,
            },
            'rowText': '多来源商品 「Alpha Store」 编辑',
        }],
        'visibleRowCount': 1,
        'filter': {'controls': []},
        'sort': {'keys': [], 'dom_order_authoritative': True},
        'pagination': {'current_page': 1, 'page_size': 20, 'total_items': 1},
    })
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is True
    item = result['items'][0]
    assert item['source_urls'] == sorted(item['source_urls'])
    assert item['source_url'] == item['source_urls'][0]
    assert item['stable_identity']['value'] == item['source_url']


def test_capture_draft_box_scope_reads_offline_draft_box_dom_without_network_or_click(monkeypatch, tmp_path):
    html = '''
    <html>
      <head>
        <title>店小秘--速卖通商品箱</title>
        <style>
          table, input, button, a, .ant-pagination, [data-page-size] { display: block; width: 240px; height: 28px; }
          tr, td, th { display: table-row; width: 300px; height: 30px; }
        </style>
      </head>
      <body>
        <input data-filter-key="search" value="待处理" placeholder="搜索内容" />
        <table>
          <thead><tr><th>店铺账号</th><th aria-sort="descending">创建时间</th><th>标题/产品ID</th></tr></thead>
          <tbody>
            <tr class="vxe-body--row" data-product-id="DXM-1001">
              <td class="title-cell" data-product-title="商品 A">商品 A 产品ID：DXM-1001</td>
              <td class="store-cell" data-store-name="Alpha Store">「Alpha Store」</td>
              <td><a href="https://detail.1688.com/offer/1013604102950.html">来源</a></td>
              <td><button>编辑</button></td>
            </tr>
            <tr class="vxe-body--row">
              <td class="title-cell" data-product-title="商品 B">商品 B</td>
              <td class="store-cell" data-store-name="Beta Store">「Beta Store」</td>
              <td><a href="https://www.aliexpress.com/item/1005011837878679.html?spm=offline">来源</a></td>
              <td><button>编辑</button></td>
            </tr>
          </tbody>
        </table>
        <div class="ant-pagination"><span class="ant-pagination-item-active">1</span><span>共 2 条</span></div>
        <span data-page-size="20">20 / 页</span>
      </body>
    </html>
    '''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        context.route(
            '**/*',
            lambda route: route.fulfill(
                status=200,
                headers={'Content-Type': 'text/html; charset=utf-8'},
                body=html,
            ),
        )
        page = context.new_page()
        page.goto(WORKFLOW_TARGETS['draft_box']['url'])
        requests_after_load = []
        page.on('request', lambda request: requests_after_load.append((request.method, request.url)))
        flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
        flow._browser = browser
        flow._context = context
        flow._page = page
        flow._browser_session_thread_id = threading.get_ident()
        flow._bind_browser_context_generation(context)
        monkeypatch.setattr(flow, '_is_headless', lambda: False)

        result = flow.capture_draft_box_scope(max_items=2)

        context.close()
        browser.close()

    assert result['ok'] is True, (result['reason_code'], result['message'])
    assert [item['title'] for item in result['items']] == ['商品 A', '商品 B']
    assert result['items'][0]['stable_identity']['kind'] == 'product_id'
    assert result['items'][1]['stable_identity']['kind'] == 'source_url'
    assert result['facts']['filter']['controls'][0]['value'] == '待处理'
    assert result['facts']['sort']['keys'] == [{'key': '创建时间', 'direction': 'descending'}]
    assert result['facts']['pagination']['total_items'] == 2
    assert requests_after_load == []


@pytest.mark.parametrize(
    ("row_html", "expected_reason"),
    [
        (
            '''
            <tr class="vxe-body--row" data-row-key="row_0001" data-id="internal_0001">
              <td class="title-cell" data-product-title="普通商品">普通商品</td>
              <td class="store-cell" data-store-name="Alpha Store">「Alpha Store」</td>
              <td><a href="https://example.com/help">帮助</a></td>
            </tr>
            ''',
            'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE',
        ),
        (
            '''
            <tr class="vxe-body--row">
              <td class="title-cell" data-product-title="普通商品">普通商品</td>
              <td class="store-cell" data-store-name="Alpha Store">「Alpha Store」</td>
              <td><a href="https://www.dianxiaomi.com/web/smt/edit?id=abcde">编辑</a></td>
            </tr>
            ''',
            'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE',
        ),
        (
            '''
            <tr class="vxe-body--row">
              <td class="title-cell" data-product-title="普通商品">普通商品</td>
              <td class="store-cell" data-store-name="Alpha Store">「Alpha Store」</td>
              <td><a href="https://static.dianxiaomi.com/help/guide?id=abcde">来源</a></td>
            </tr>
            ''',
            'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE',
        ),
        (
            '''
            <tr class="vxe-body--row">
              <td class="title-cell" data-product-title="普通商品">普通商品</td>
              <td class="store-cell" data-store-name="Alpha Store">「Alpha Store」</td>
              <td><a href="https://example.com/product/ordinary-link">来源</a></td>
            </tr>
            ''',
            'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE',
        ),
        (
            '''
            <tr class="vxe-body--row" data-product-id="DXM-1001">
              <td class="title-cell" data-product-title="「Pokemon」立牌">「Pokemon」立牌 产品ID：DXM-1001</td>
              <td><a href="https://detail.1688.com/offer/1013604102950.html">来源</a></td>
            </tr>
            ''',
            'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE',
        ),
    ],
)
def test_capture_draft_box_scope_rejects_unproven_product_source_and_store_identity(
    monkeypatch,
    tmp_path,
    row_html,
    expected_reason,
):
    html = f'''
    <html>
      <head>
        <title>店小秘--速卖通商品箱</title>
        <style>
          table, input, button, a {{ display: block; width: 240px; height: 28px; }}
          tr, td, th {{ display: table-row; width: 300px; height: 30px; }}
        </style>
      </head>
      <body>
        <table>
          <thead><tr><th>标题/产品ID</th><th>店铺账号</th><th>来源</th></tr></thead>
          <tbody>{row_html}</tbody>
        </table>
      </body>
    </html>
    '''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        context.route(
            '**/*',
            lambda route: route.fulfill(
                status=200,
                headers={'Content-Type': 'text/html; charset=utf-8'},
                body=html,
            ),
        )
        page = context.new_page()
        page.goto(WORKFLOW_TARGETS['draft_box']['url'])
        flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
        flow._browser = browser
        flow._context = context
        flow._page = page
        flow._browser_session_thread_id = threading.get_ident()
        flow._bind_browser_context_generation(context)
        monkeypatch.setattr(flow, '_is_headless', lambda: False)

        result = flow.capture_draft_box_scope(max_items=1)

        context.close()
        browser.close()

    assert result['ok'] is False
    assert result['reason_code'] == expected_reason
    assert result['items'] == []
    assert result['zero_write_proof']['mutation_dispatch_attempted'] is False


def test_capture_draft_box_scope_distinguishes_expired_login_without_dom_scan(tmp_path):
    class LoginPage:
        url = 'https://www.dianxiaomi.com/login'

        def __init__(self):
            self.evaluate_calls = 0

        def title(self):
            return '店小秘登录'

        def evaluate(self, *_args):
            self.evaluate_calls += 1
            raise AssertionError('登录失效后不得扫描商品箱 DOM')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = LoginPage()
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'LOGIN_REQUIRED'
    assert result['items'] == []
    assert result['zero_write_proof']['ok'] is True
    assert page.evaluate_calls == 0


def test_capture_draft_box_scope_rejects_page_drift_without_navigation_or_dom_scan(tmp_path):
    class ProductListPage:
        url = 'https://www.dianxiaomi.com/product/productList.htm'

        def __init__(self):
            self.evaluate_calls = 0

        def title(self):
            return '店小秘--产品列表'

        def evaluate(self, *_args):
            self.evaluate_calls += 1
            raise AssertionError('页面漂移后不得扫描商品箱 DOM')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = ProductListPage()
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'DRAFT_BOX_PAGE_NOT_PROVEN'
    assert result['page']['kind'] is None
    assert result['facts']['runtime']['page_kind'] is None
    assert result['zero_write_proof']['navigation_attempted'] is False
    assert page.evaluate_calls == 0


def test_capture_draft_box_scope_distinguishes_ready_empty_list(tmp_path):
    page = ScopeSnapshotPage({
        'items': [],
        'visibleRowCount': 0,
        'filter': {'controls': []},
        'sort': {'keys': [], 'dom_order_authoritative': True},
        'pagination': {'current_page': 1, 'page_size': 20, 'total_items': 0},
    })
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'DRAFT_BOX_EMPTY'
    assert result['page']['kind'] == 'draft_box'
    assert result['page']['ready'] is True
    assert result['items'] == []
    assert result['evidence']['refs'] == []
    assert len(page.evaluate_calls) == 2


def test_capture_draft_box_scope_distinguishes_loading_page_from_empty_list(tmp_path):
    page = ScopeSnapshotPage({'items': []}, loading=True)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'DRAFT_BOX_PAGE_NOT_READY'
    assert result['items'] == []
    assert len(page.evaluate_calls) == 1


def test_capture_draft_box_scope_fails_closed_when_item_has_no_stable_identity(tmp_path):
    page = ScopeSnapshotPage({
        'items': [{
            'domIndex': 0,
            'title': '缺少稳定身份的商品',
            'productId': None,
            'sourceUrls': [],
            'storeEvidence': {
                'store_name': 'Alpha Store',
                'cell_text': '「Alpha Store」',
                'source': 'structured_store_cell',
                'column_index': 2,
            },
            'rowText': '缺少稳定身份的商品 「Alpha Store」 编辑',
        }],
        'visibleRowCount': 1,
        'filter': {'controls': []},
        'sort': {'keys': [], 'dom_order_authoritative': True},
        'pagination': {'current_page': 1, 'page_size': 20, 'total_items': 1},
    })
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'DRAFT_BOX_ITEM_IDENTITY_INCOMPLETE'
    assert result['items'] == []
    assert result['evidence']['dom_digest'] is None
    assert result['zero_write_proof']['mutation_dispatch_attempted'] is False


def test_capture_draft_box_scope_rejects_duplicate_identity_as_ambiguous(tmp_path):
    def item(dom_index, title):
        return {
            'domIndex': dom_index,
            'title': title,
            'productId': 'DXM-DUPLICATE-1',
            'sourceUrls': [],
            'storeEvidence': {
                'store_name': 'Alpha Store',
                'cell_text': '「Alpha Store」',
                'source': 'structured_store_cell',
                'column_index': 2,
            },
            'rowText': f'{title} 产品ID：DXM-DUPLICATE-1 「Alpha Store」 编辑',
        }

    page = ScopeSnapshotPage({
        'items': [item(0, '重复商品 A'), item(1, '重复商品 B')],
        'visibleRowCount': 2,
        'filter': {'controls': []},
        'sort': {'keys': [], 'dom_order_authoritative': True},
        'pagination': {'current_page': 1, 'page_size': 20, 'total_items': 2},
    })
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _bind_visible_scope_session(flow, page)

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'DRAFT_BOX_ITEM_IDENTITY_AMBIGUOUS'
    assert result['items'] == []
    assert result['evidence']['refs'] == []


@pytest.mark.parametrize('max_items', [None, True, 0, 101, -1, 1.5])
def test_capture_draft_box_scope_bounds_max_items_before_accessing_browser(max_items, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    result = flow.capture_draft_box_scope(max_items=max_items)

    assert result['ok'] is False
    assert result['reason_code'] == 'INVALID_MAX_ITEMS'
    assert result['browser_session_id'] is None
    assert result['items'] == []


def test_capture_draft_box_scope_does_not_create_browser_when_live_session_is_missing(tmp_path, monkeypatch):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_ensure_page', lambda: pytest.fail('范围捕获不得创建新浏览器'))
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: pytest.fail('范围捕获不得加载或创建会话'))

    result = flow.capture_draft_box_scope(max_items=20)

    assert result['ok'] is False
    assert result['reason_code'] == 'BROWSER_SESSION_UNAVAILABLE'
    assert result['browser_session_id'] is None
    assert result['zero_write_proof']['navigation_attempted'] is False


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
    url = WORKFLOW_TARGETS['draft_box']['url']

    def __init__(self, row_info):
        self.row_info = row_info

    def goto(self, url, *args, **kwargs):
        self.url = url

    def title(self):
        return '店小秘--速卖通产品'

    def wait_for_timeout(self, timeout):
        return None

    def screenshot(self, path, full_page=True):
        return None

    def locator(self, selector):
        class Locator:
            def inner_text(self, timeout=None):
                return '标题/产品ID 搜索内容 编辑'

        if selector == 'body':
            return Locator()
        raise AssertionError(f'unexpected selector: {selector}')

    def evaluate(self, script, arg=None):
        if 'businessMarker' in script:
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '标题/产品ID',
            }
        if isinstance(arg, list):
            return {
                'ready': True,
                'ready_term': arg[0] if arg else None,
                'loading': False,
                'rows': 1,
                'inputs': 1,
                'text_excerpt': '标题/产品ID 搜索内容',
            }
        if isinstance(arg, str) and 'draft_box_search' not in script:
            return {'ok': True, 'strategy': 'dummy_visible_search', 'input': {}, 'clicked': '搜索'}
        if (
            'rowIndex:picked.idx' in script
            or 'sourceMatches' in script
            or 'claimMatches' in script
        ):
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


def test_live_browser_hud_page_events_only_mark_reapply_pending():
    flow = DxmLoginFlow(DummyLiveClient())
    context = DummyHudContext()
    page = DummyHudPage(context=context)
    flow._page = page

    flow.update_live_hud({
        'state': 'CLAIM_TO_COLLECTION_BOX',
        'human_title': '正在认领到采集箱',
        'human_action': '从已有待认领商品认领商品',
    })

    assert 'framenavigated' in page.handlers
    assert 'domcontentloaded' in page.handlers
    assert 'page' in context.handlers

    page.hud_payloads.clear()
    page.emit('framenavigated')
    assert page.hud_payloads == []
    assert flow._live_hud_reapply_pending is True

    page.hud_payloads.clear()
    page.emit('domcontentloaded')
    assert page.hud_payloads == []
    assert flow._live_hud_reapply_pending is True

    new_page = DummyHudPage(context=context)
    context.emit('page', new_page)
    assert new_page.handlers == {}
    assert new_page.hud_payloads == []
    assert flow._live_hud_reapply_pending is True
    flow._reapply_live_hud_if_available(new_page)
    assert new_page.hud_payloads[-1]['human_title'] == '正在认领到采集箱'


def test_live_browser_hud_caches_status_before_page_exists():
    flow = DxmLoginFlow(DummyLiveClient())
    result = flow.update_live_hud({
        'state': 'OPEN_DATA_ACQUISITION',
        'human_title': '正在打开数据采集',
        'human_action': '进入店小秘已有待认领列表',
    })
    assert result['updated'] is False
    assert result['reason'] == 'live_browser_page_missing'

    page = DummyHudPage()
    flow._reapply_live_hud_if_available(page)

    assert page.hud_payloads[-1]['state'] == 'OPEN_DATA_ACQUISITION'
    assert page.hud_payloads[-1]['human_action'] == '进入店小秘已有待认领列表'


def test_live_browser_hud_payload_update_uses_runtime_timeout(monkeypatch):
    flow = DxmLoginFlow(DummyLiveClient())
    page = DummyHudPage()
    flow._page = page
    calls = []

    def fail_payload_update(_page, _script, _payload, *, timeout=3000):
        calls.append(timeout)
        raise RuntimeError('hud update timed out')

    monkeypatch.setattr(flow, '_evaluate_page_function_with_runtime_timeout', fail_payload_update)

    result = flow.update_live_hud({
        'state': 'OPEN_DATA_ACQUISITION',
        'human_title': '正在打开待认领商品列表',
        'human_action': '进入店小秘已有待认领列表',
    })

    assert result['ok'] is False
    assert result['updated'] is False
    assert result['reason'] == 'live_browser_hud_apply_failed'
    assert calls and calls[-1] <= 1000


class DummyClaimMarkDraftPage(DummyDraftPage):
    def __init__(self):
        super().__init__({'ok': False, 'matches': []})
        self.find_arg = None

    def evaluate(self, script, arg=None):
        if 'rowIndex:picked.idx' in script or 'claimMatches' in script:
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
        if 'rowIndex:picked.idx' in script or 'sourceMatches' in script:
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


def _is_structured_save_status_snapshot_script(script):
    return isinstance(script, str) and '__DXM_STRUCTURED_SAVE_STATUS_SNAPSHOT__' in script


class DummySemiPage:
    url = 'https://www.dianxiaomi.com/web/smt/semi?id=123'

    def __init__(self, save_result):
        self.save_result = save_result
        self.handlers = {}

    def title(self):
        return '半托管信息'

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        if _is_structured_save_status_snapshot_script(script):
            return {'ok': True, 'entries': []}
        return self.save_result

    def evaluate_handle(self, _script):
        return DummyExactSaveHandle(self)

    def on(self, event_name, callback):
        self.handlers.setdefault(event_name, []).append(callback)

    def remove_listener(self, event_name, callback):
        callbacks = self.handlers.get(event_name, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def _dispatch_exact_save(self):
        return None

    def wait_for_timeout(self, timeout):
        return None

    def screenshot(self, path, full_page=True):
        return None


class DummyExactSaveHandle:
    def __init__(self, page):
        self.page = page
        self.disposed = False

    def as_element(self):
        return self

    def evaluate(self, script):
        if 'target.click()' in script:
            self.page._dispatch_exact_save()
            return {'ok': True, 'dispatched': True, 'method': 'dom_exact_text'}
        return {
            'ok': True,
            'text': '保存',
            'at_point_text': '保存',
            'exact_save_count': 1,
            'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40},
            'reason': None,
        }

    def dispose(self):
        self.disposed = True


class DummySaveOnlyScriptPage(DummySemiPage):
    def __init__(self):
        super().__init__({'ok': False, 'reason': '命中发布按钮：立即发布', 'published': False})
        self.script = ''

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        if _is_structured_save_status_snapshot_script(script):
            return {'ok': True, 'entries': []}
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
        values = dict(arg or {})

        def exact_detail(field_name, expected_value):
            expected = str(expected_value)
            return {
                'ok': True,
                'located': True,
                'strategy': 'column_header',
                'expected_value': expected,
                'value_before': expected,
                'value_after': expected,
            }

        freight_template = str((values.get('freight_template_priorities') or [''])[0])
        service_template = str((values.get('service_template_priorities') or [''])[0])
        return {
            'product_price': True,
            'supply_price': True,
            'weight': True,
            'length': True,
            'width': True,
            'height': True,
            'stock': True,
            'goods_code': True,
            'freight_template': True,
            'service_template': True,
            'variant_rows': [{'index': 0, 'structured_control_count': 8}],
            'variant_rows_present': True,
            'field_details': {
                'product_price': exact_detail('product_price', values['product_price']),
                'supply_price': exact_detail('supply_price', values['supply_price']),
                'weight': exact_detail('weight', values['weight']),
                'length': exact_detail('length', values['length']),
                'width': exact_detail('width', values['width']),
                'height': exact_detail('height', values['height']),
                'jit_stock': exact_detail('jit_stock', values['stock']),
                'goods_code': exact_detail('goods_code', values['sku_code']),
                'freight_template': exact_detail('freight_template', freight_template),
                'service_template': exact_detail('service_template', service_template),
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


class DummyEditorVariantsCustomNamesPage(DummySemiPage):
    def __init__(self):
        super().__init__({})
        self.script = ''

    def evaluate(self, script, arg=None):
        self.script = script
        base = {
            'declared_value': {'matched': 5, 'filled': 5},
            'stock': {'matched': 5, 'filled': 5},
            'weight': {'matched': 5, 'filled': 5},
            'length': {'matched': 5, 'filled': 5},
            'width': {'matched': 5, 'filled': 5},
            'height': {'matched': 5, 'filled': 5},
            'logistics_attribute_visible': True,
            'logistics_icon_count': 0,
            'variant_scope_found': True,
        }
        if (
            'validCustomName' not in script
            or 'variant_custom_names' not in script
            or 'fillVariantOriginalBox' not in script
            or 'variant_original_box' not in script
        ):
            return {
                **base,
                'ok': False,
                'missing': ['variant_custom_names', 'original_box'],
                'variant_custom_names': {'matched': 5, 'filled': 0, 'values': []},
                'variant_original_box': {'matched': 5, 'filled': 0, 'values': []},
            }
        return {
            **base,
            'ok': True,
            'missing': [],
            'variant_custom_names': {
                'matched': 5,
                'filled': 5,
                'values': [
                    {'before': '5CM亚克力立牌 记得撕膜 ', 'expected_value': '5CM Acrylic', 'value_after': '5CM Acrylic', 'filled': True, 'ok': True},
                    {'before': '6CM亚克力立牌 记得撕膜 ', 'expected_value': '6CM Acrylic', 'value_after': '6CM Acrylic', 'filled': True, 'ok': True},
                    {'before': '8CM亚克力立牌 记得撕膜 ', 'expected_value': '8CM Acrylic', 'value_after': '8CM Acrylic', 'filled': True, 'ok': True},
                    {'before': '10CM亚克力立牌 记得撕膜 ', 'expected_value': '10CM Acrylic', 'value_after': '10CM Acrylic', 'filled': True, 'ok': True},
                    {'before': '12CM亚克力立牌 记得撕膜 ', 'expected_value': '12CM Acrylic', 'value_after': '12CM Acrylic', 'filled': True, 'ok': True},
                ],
            },
            'variant_original_box': {
                'matched': 5,
                'filled': 5,
                'values': [
                    {'before': '', 'after': '0', 'ok': True},
                    {'before': '', 'after': '0', 'ok': True},
                    {'before': '', 'after': '0', 'ok': True},
                    {'before': '', 'after': '0', 'ok': True},
                    {'before': '', 'after': '0', 'ok': True},
                ],
            },
        }


class DummySaveOnlyVerifyPage(DummySemiPage):
    def __init__(self, verify_result):
        super().__init__({
            'ok': True,
            'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40},
            'clicked': True,
            'message': '已点击保存',
            'published': False,
        })
        self.verify_result = verify_result
        self.evaluate_calls = 0
        self.snapshot_calls = 0
        self.clicks = []

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicks.append((x, y))

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        if _is_structured_save_status_snapshot_script(script):
            entries = []
            if self.snapshot_calls > 0 and self.verify_result.get('ok') is True:
                entries = [{
                    'id': 'new-save-status',
                    'text': self.verify_result.get('success_text') or '保存成功',
                    'status': '',
                    'source': 'ant-message-notice',
                }]
            self.snapshot_calls += 1
            return {'ok': True, 'entries': entries}
        self.evaluate_calls += 1
        return self.save_result


class DummyNetworkRequest:
    url = 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    method = 'POST'
    resource_type = 'xhr'


class DummyNetworkResponse:
    url = 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    status = 200

    def __init__(self, request=None):
        self._request = request or DummyNetworkRequest()

    @property
    def request(self):
        return self._request

    def json(self):
        return {
            'code': 0,
            'msg': 'Successful',
            'data': {
                'code': 0,
                'msg': '您的产品编辑成功！',
                'productId': '130658341344670934',
            },
        }


class DummySaveOnlyNetworkPage(DummySemiPage):
    def __init__(self):
        super().__init__({'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40}, 'published': False})
        self.evaluate_calls = 0
        self.snapshot_calls = 0
        self.clicks = []

    @property
    def mouse(self):
        return self

    def click(self, x, y):
        self.clicks.append((x, y))

    def _dispatch_exact_save(self):
        request = DummyNetworkRequest()
        for handler in list(self.handlers.get('request', [])):
            handler(request)
        response = DummyNetworkResponse(request)
        for handler in list(self.handlers.get('response', [])):
            handler(response)

    def evaluate(self, script, arg=None):
        if _is_dismiss_blocking_modals_script(script):
            return {'visible': False}
        if _is_visible_blocking_modal_state_script(script):
            return {'visible': False}
        if _is_structured_save_status_snapshot_script(script):
            self.snapshot_calls += 1
            return {'ok': True, 'entries': []}
        self.evaluate_calls += 1
        return self.save_result


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
    url = WORKFLOW_TARGETS['draft_box']['url']

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


class DummyDataAcquisitionReadyWaitPage:
    url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

    def __init__(self):
        self.ready_calls = 0
        self.dismiss_calls = 0

    def evaluate(self, script, arg=None):
        if arg is None:
            self.dismiss_calls += 1
            return {'visible': False}
        if 'document.body' in script or 'innerText' in script:
            raise AssertionError('data acquisition ready check must not scan full body text')
        self.ready_calls += 1
        if self.ready_calls == 1:
            return {
                'ready': False,
                'ready_term': None,
                'loading': True,
                'loading_count': 1,
                'rows': 0,
                'inputs': 0,
                'text_excerpt': '加载中',
                'url': self.url,
                'title': '店小秘--免费的跨境电商ERP',
                'loading_text': '',
            }
        return {
            'ready': True,
            'ready_term': '数据采集',
            'loading': False,
            'loading_count': 0,
            'rows': 1,
            'inputs': 8,
            'text_excerpt': '数据采集 认领 采集箱',
            'url': self.url,
            'title': '店小秘--数据采集',
            'loading_text': '',
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
                'text': '种类(Kind): Other 取消 确定',
                'select_rect': None,
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
            'has_customs_area': True,
            'select_error': False,
            'product_name_value': '钥匙扣(keychain)',
            'kind_value': 'Other',
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
            'has_product_name': True,
            'has_kind': True,
            'has_customs_area': True,
            'select_error': False,
            'product_name_value': 'keychain',
            'kind_value': 'Other',
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


def test_login_success_copy_describes_controlled_two_stage_start_boundary():
    state = main_module.build_login_state({"logged_in": True})

    operator_copy = f"{state['message']} {state['next_action']}"
    assert "claim_only 可按 Stage A 审批启动" in operator_copy
    assert "single_save 可按 Stage B 审批启动" in operator_copy
    assert "batch_save 和发布仍关闭" in operator_copy
    assert "claim_only、batch_save 和发布仍未放行" not in operator_copy


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


def test_legacy_draft_box_action_endpoint_does_not_dispatch_after_guard_stub(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/draft-box/action', json={'action': 'remark', 'note_text': 'AI认领'})

    assert response.status_code == 200
    assert response.json() is None
    assert flow.performed_action is None


def test_workflow_check_login_uses_adapter_contract(monkeypatch):
    flow = DummyLoginFlow()
    flow.state = {
        'ok': True,
        'stage': 'login_success',
        'page_title': '店小秘首页',
        'page_url': 'https://www.dianxiaomi.com/index.htm',
        'screenshot_url': '/artifacts/screenshots/home.png',
        'logged_in': True,
        'reader_ready': True,
        'reason_code': 'LOGIN_READER_READY',
        'login_check': {
            'logged_in': True,
            'business_page_ready': True,
            'loading': False,
        },
    }
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))
    monkeypatch.setattr('src.main._assert_batch_browser_available', lambda: None)

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
    monkeypatch.setattr('src.main._assert_batch_browser_available', lambda: None)

    client = TestClient(app)
    response = client.post('/api/dxm/workflow/open-draft-box')

    assert response.status_code == 200
    data = response.json()
    assert flow.navigated_to == 'draft_box'
    assert data['ok'] is True
    assert data['action'] == 'open_draft_box'
    assert data['evidence']['current_nav'] == 'draft_box'


def test_legacy_workflow_claim_endpoint_does_not_dispatch_after_guard_stub(monkeypatch):
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
    assert response.json() is None
    assert flow.performed_action is None


def test_legacy_workflow_open_editor_endpoint_does_not_dispatch_after_guard_stub(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main.workflow_adapter', DxmWorkflowAdapter(flow))
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/workflow/open-editor')

    assert response.status_code == 200
    assert response.json() is None
    assert flow.performed_action is None


def test_legacy_edit_action_endpoint_does_not_dispatch_after_guard_stub(monkeypatch):
    flow = DummyLoginFlow()
    monkeypatch.setattr('src.main.login_flow', flow)
    monkeypatch.setattr('src.main._assert_direct_real_dxm_mutation_allowed', lambda payload: None)

    client = TestClient(app)
    response = client.post('/api/dxm/draft-box/action', json={'action': 'edit'})

    assert response.status_code == 200
    assert response.json() is None
    assert flow.performed_action is None


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

    assert live_client.probed is False
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
    monkeypatch.setattr(
        flow,
        'read_draft_shops',
        lambda: pytest.fail('visible home login detection must not run the draft Reader'),
    )
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert state['stage'] == 'login_success'
    assert state['browser_visible'] is True
    assert '返回工作台进入采集箱选品' in state['next_action']
    assert '不会保存或发布' in state['next_action']
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


def test_continue_login_accepts_visible_dxm_home_without_legacy_menu_markers(monkeypatch, tmp_path):
    class RedesignedLoggedInHomePage(DummyLoggedInHomePage):
        def inner_text(self, timeout: int = 0):
            return '店小秘 工作空间 欢迎回来'

    live_client = DummyLiveClient(logged_in=False)
    live_client.cookie_file = tmp_path / 'cookies.json'
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = RedesignedLoggedInHomePage()
    flow._context = DummyCookieContext()

    monkeypatch.setattr(flow, '_ensure_page', lambda: page)
    monkeypatch.setattr(
        flow,
        '_click_first_available',
        lambda *args, **kwargs: pytest.fail('DXM home must not click login controls'),
    )
    monkeypatch.setattr(
        flow,
        'read_draft_shops',
        lambda: pytest.fail('visible home login detection must not run the draft Reader'),
    )
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert state['stage'] == 'login_success'
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert state.get('account_ref') is None


def test_continue_login_reports_reader_ready_reason_code(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=False), state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'visible_logged_in': True,
        'reader_ready': True,
        'reader_reason_code': 'LOGIN_READER_READY',
    })
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert state['ok'] is True
    assert state['logged_in'] is True
    assert state['reader_ready'] is True
    assert state['reason_code'] == 'LOGIN_READER_READY'


def test_continue_login_uses_visible_home_without_reader_or_headless_cookie_probe(monkeypatch, tmp_path):
    class AsyncioGuardLiveClient(DummyLiveClient):
        def probe_session(self):
            self.probed = True
            raise AssertionError('continue_login must not start a second Playwright runtime')

    live_client = AsyncioGuardLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
        'visible_logged_in': True,
    })
    monkeypatch.setattr(
        flow,
        'read_draft_shops',
        lambda: pytest.fail('visible home login detection must not run the draft Reader'),
    )
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert live_client.probed is False
    assert state['stage'] == 'login_success'
    assert state['requires_user_action'] is False
    assert state['browser_visible'] is True
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert state.get('account_ref') is None
    assert '登录成功' in state['message']
    assert close_calls == []


def test_continue_login_accepts_visible_home_without_running_reader_account_proof(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=False)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    reader_calls = []

    monkeypatch.setattr(flow, '_submit_login_after_captcha', lambda: {
        'page_title': '店小秘--首页',
        'page_url': 'https://www.dianxiaomi.com/web/home',
        'screenshot_url': '/artifacts/screenshots/login-result.png',
        'visible_logged_in': True,
    })
    monkeypatch.setattr(
        flow,
        'read_draft_shops',
        lambda: reader_calls.append('called') or (_ for _ in ()).throw(
            RuntimeError('authenticated account identity missing')
        ),
    )
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    state = flow.continue_login()

    assert live_client.probed is False
    assert reader_calls == []
    assert state['stage'] == 'login_success'
    assert state['requires_user_action'] is False
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert state.get('account_ref') is None


def test_check_visible_login_state_uses_execution_browser_with_saved_cookies(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    live_client.cookie_file = tmp_path / 'cookies.json'
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._context = DummyCookieContext()
    page = DummyLoggedInHomePage()
    visited = []
    ensured_with_cookies = []
    foreground_calls = []

    monkeypatch.setattr(flow, '_ensure_page', lambda: pytest.fail('login check must use saved cookies'))
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: ensured_with_cookies.append(True) or page)
    monkeypatch.setattr(
        flow,
        '_goto_sterile',
        lambda page_arg, url, **_kwargs: visited.append((page_arg, url)),
    )
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: foreground_calls.append('front') or True)
    monkeypatch.setattr(
        flow,
        '_visible_reader_session_status',
        lambda: {'reader_ready': True, 'reason_code': 'READER_READY'},
    )
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *_args, **_kwargs: pytest.fail('login check must not inject the HUD before the DXM home page is readable'),
    )

    state = flow.check_visible_login_state()

    assert live_client.probed is False
    assert ensured_with_cookies == [True]
    assert visited == [(page, 'https://www.dianxiaomi.com/web/home')]
    assert foreground_calls == ['front']
    assert state['stage'] == 'login_success'
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/home'
    assert state['browser_visible'] is True
    assert live_client.cookie_file.exists()

    monkeypatch.setenv('DXM_WORKFLOW_ACTION_RUNTIME', 'browser_agent')
    adapter_result = DxmWorkflowAdapter(flow).check_login_state()

    assert adapter_result['ok'] is True
    assert adapter_result['stage'] == 'login_success'
    assert adapter_result['contract_facts']['postconditions'] == {
        'business_page_ready': True,
        'loading_absent': True,
        'session_authenticated': True,
    }


def test_check_visible_login_state_skips_screenshot_to_avoid_blocking(monkeypatch, tmp_path):
    class VisibleLoginPage:
        url = 'https://www.dianxiaomi.com/web/home'

        def __init__(self):
            self.screenshot_calls = 0

        def wait_for_timeout(self, timeout):
            return None

        def locator(self, selector):
            assert selector == 'body'
            return self

        def inner_text(self, timeout=0):
            return '欢迎登录 店小秘'

        def title(self):
            return '店小秘官网登录页'

        def screenshot(self, **_kwargs):
            self.screenshot_calls += 1
            raise AssertionError('login state check must not block on screenshot capture')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = VisibleLoginPage()

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_sterile', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *_args, **_kwargs: pytest.fail('login state check must not inject the HUD before the DXM home page is readable'),
    )
    monkeypatch.setattr(
        flow,
        '_safe_live_hud_page_title',
        lambda _page: pytest.fail('login state check must not read page title after readiness decision'),
    )

    state = flow.check_visible_login_state()

    assert state['stage'] == 'login_failed'
    assert page.screenshot_calls == 0
    assert state['screenshot_url'] is None


def test_check_visible_login_state_accepts_home_url_but_keeps_reader_fail_closed(monkeypatch, tmp_path):
    class BlankHomePage:
        url = 'https://www.dianxiaomi.com/web/home'

        def wait_for_timeout(self, timeout):
            return None

        def locator(self, selector):
            assert selector == 'body'
            return self

        def inner_text(self, timeout=0):
            return ''

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = BlankHomePage()

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_sterile', lambda *_args, **_kwargs: None)

    state = flow.check_visible_login_state()

    assert state['stage'] == 'login_success'
    assert state['logged_in'] is True
    assert state['reader_ready'] is False
    assert state['reason_code'] == 'BROWSER_SESSION_UNAVAILABLE'
    assert state['login_check']['reason'] == 'home_body_unavailable'


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
    assert '商品箱' in state['message']


def test_navigation_state_preserves_exact_readiness_observations(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    wait_result = {
        'ready': True,
        'expected_identity': 'data_acquisition',
        'loading': False,
        'readiness': {
            'ok': True,
            'expected_identity': 'data_acquisition',
            'business_marker': '已有待认领商品',
            'loading': False,
            'blocking_modal': None,
        },
    }
    navigation_result = {
        'page_title': '数据采集',
        'page_url': 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
        'target': 'data_acquisition',
        'wait_result': wait_result,
        'dismissed_blocking_modals': 0,
    }
    monkeypatch.setattr(flow, '_navigate_in_session', lambda target: navigation_result)

    state = flow.navigate_post_login('data_acquisition')

    assert state['wait_result'] == wait_result
    assert state['navigation_result'] == navigation_result


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

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
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

    state = flow.perform_draft_box_action(
        'remark',
        note_text='AI认领',
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

    assert state['stage'] == 'draft_box_action'
    assert state['current_nav'] == 'draft_box'
    assert state['current_action'] == 'remark'
    assert state['note_text'] == 'AI认领'
    assert state['product_query'] == '崩坏3钥匙扣'
    assert state['store_name'] == 'Dang Kang'
    assert state['note_verified'] is True
    assert '备注: AI认领' in state['target_row_text']
    assert state['draft_action_result']['note_verified'] is True


def test_dxm_login_flow_perform_draft_box_action_keeps_browser_session_on_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/remark.png',
        'action': action,
        'note_text': note_text,
        'note_verified': True,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))

    state = flow.perform_draft_box_action(
        'remark',
        note_text='AI认领',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

    assert state['stage'] == 'draft_box_action'
    assert close_calls == []


def test_dxm_login_flow_edit_action_enters_editor_page(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_perform_draft_box_action', lambda action, note_text=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
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

    state = flow.perform_draft_box_action(
        'edit',
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

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


def test_perform_draft_box_action_visible_mode_skips_full_modal_dismiss(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    settle_calls = []
    goto_calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

        def goto(self, url, *, wait_until, timeout):
            goto_calls.append((url, wait_until, timeout))
            self.url = url

        def title(self):
            return '店小秘--编辑速卖通产品'

        def screenshot(self, **_kwargs):
            return None

    page = FakePage()

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_with_live_hud', lambda *_args, **_kwargs: pytest.fail('visible draft action should not inject HUD before page settles'))
    monkeypatch.setattr(
        flow,
        '_settle_visible_draft_box',
        lambda target_page, expected_identity: settle_calls.append((target_page, expected_identity)) or {'ready': True, 'ready_term': 'visible_draft_box_settle'},
    )
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: pytest.fail('visible draft action should use sterile settle instead of wait_ready'))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: pytest.fail('visible draft action should not run full modal dismiss'))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: {'rowText': '目标商品 「Dang Kang」 编辑', 'sourceUrls': [], 'actions': []})
    monkeypatch.setattr(flow, '_open_editor_from_draft_box', lambda target_page, **_kwargs: target_page)
    monkeypatch.setattr(flow, '_extract_editor_page_meta', lambda _page: {'sections': [], 'top_actions': [], 'fields': []})
    target = _frozen_action_kwargs()['target_identity']
    monkeypatch.setattr(
        flow,
        '_verify_opened_editor_target',
        lambda *_args, **_kwargs: _frozen_identity_readback(target),
    )

    result = flow._perform_draft_box_action(
        'edit',
        product_query='目标商品',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

    assert result['action'] == 'edit'
    assert goto_calls == [('https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0', 'domcontentloaded', 45000)]
    assert settle_calls == [(page, 'draft_box')]


def test_perform_draft_box_edit_keeps_editor_result_when_screenshot_times_out(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: True)

    class DraftPage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

        def goto(self, url, *, wait_until, timeout):
            self.url = url

    class EditorPage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

        def title(self):
            return '店小秘--编辑速卖通产品'

        def screenshot(self, **_kwargs):
            raise RuntimeError('Page.screenshot: Timeout 30000ms exceeded')

    row = {
        'rowText': '正版玩具总动员攀爬吊饰钥匙扣挂件 「Dang Kang」 编辑',
        'sourceUrls': ['https://detail.1688.com/offer/1057791519266.html'],
        'actions': [],
    }

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: DraftPage())
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: {'ready': True, 'ready_term': '店铺账号'})
    monkeypatch.setattr(flow, '_settle_visible_draft_box', lambda _page, expected_identity: {'ready': expected_identity == 'draft_box', 'ready_term': '店铺账号'})
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: row)
    monkeypatch.setattr(flow, '_open_editor_from_draft_box', lambda _page, **_kwargs: EditorPage())
    monkeypatch.setattr(flow, '_extract_editor_page_meta', lambda _page: {'sections': ['基本信息'], 'top_actions': ['保存'], 'fields': ['产品信息']})
    target_kwargs = _frozen_action_kwargs(
        source_url='https://detail.1688.com/offer/1057791519266.html',
    )
    monkeypatch.setattr(
        flow,
        '_verify_opened_editor_target',
        lambda *_args, **_kwargs: _frozen_identity_readback(target_kwargs['target_identity']),
    )

    result = flow._perform_draft_box_action(
        'edit',
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        **target_kwargs,
    )

    assert result['page_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    assert result['screenshot_url'] is None
    assert 'Page.screenshot' in result['screenshot_error']
    assert result['target_source_urls'] == ['https://detail.1688.com/offer/1057791519266.html']


def test_visible_editor_workflow_screenshot_skips_full_page_capture(monkeypatch, tmp_path):
    class VisibleEditorPage(DummyOpenSemiPage):
        def screenshot(self, **_kwargs):
            raise AssertionError('visible editor workflow must not take full-page screenshots')

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    page = VisibleEditorPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    result = flow._capture_optional_workflow_screenshot(
        page,
        tmp_path / 'visible-editor.png',
        trace_prefix='visible_editor',
    )

    assert result['ok'] is False
    assert result['screenshot_url'] is None
    assert result['error'] == 'visible_editor_screenshot_skipped'
    assert any(event['event'] == 'visible_editor:screenshot_skipped' for event in flow.recent_workflow_events())


def test_navigate_draft_box_visible_mode_uses_sterile_settle(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    settle_calls = []
    goto_calls = []
    hud_reapply_calls = []
    screenshot_calls = []

    class FakePage:
        url = 'about:blank'

        def goto(self, url, *, wait_until, timeout):
            goto_calls.append((url, wait_until, timeout))
            self.url = url

        def title(self):
            return '店小秘--商品箱'

        def screenshot(self, *, path, full_page, timeout):
            screenshot_calls.append((path, full_page, timeout))

    page = FakePage()

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_with_live_hud', lambda *_args, **_kwargs: pytest.fail('visible draft navigation should not inject HUD before settle'))
    monkeypatch.setattr(flow, '_settle_visible_draft_box', lambda target_page, expected_identity: settle_calls.append((target_page, expected_identity)) or {
        'ready': True,
        'ready_term': '标题/产品ID',
        'loading': False,
        'rows': 1,
        'inputs': 1,
        'text_excerpt': '标题/产品ID 编辑',
        'title': '店小秘--商品箱',
    })
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: pytest.fail('visible draft navigation should not use full wait_ready'))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: pytest.fail('visible draft navigation should not run full modal dismiss'))
    monkeypatch.setattr(flow, '_reapply_live_hud_if_available', lambda target_page: hud_reapply_calls.append(target_page))

    result = flow._navigate_in_session('draft_box')

    assert result['target'] == 'draft_box'
    assert result['wait_result']['ready'] is True
    assert result['dismissed_blocking_modals'] == 0
    assert goto_calls == [('https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0', 'domcontentloaded', 45000)]
    assert settle_calls == [(page, 'draft_box')]
    assert hud_reapply_calls == []
    assert screenshot_calls == []


def test_settle_visible_draft_box_uses_process_sleep_instead_of_playwright_wait(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    sleeps = []

    class BlockingWaitPage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

        def wait_for_timeout(self, _timeout):
            raise AssertionError('visible draft settle must not depend on Playwright wait_for_timeout')

    monkeypatch.setattr(dxm_login_flow_module, 'time', type('TimeShim', (), {
        'monotonic': staticmethod(lambda: 1_000_000.0),
        'sleep': staticmethod(lambda seconds: sleeps.append(seconds)),
    }))
    monkeypatch.setattr(flow, '_browser_readiness_gate', lambda *_args, **_kwargs: {
        'ok': True,
        'business_marker': '标题/产品ID',
        'loading': False,
        'body_excerpt': '标题/产品ID 编辑',
        'page_title': '店小秘--商品箱',
    })

    result = flow._settle_visible_draft_box(BlockingWaitPage(), expected_identity='draft_box')

    assert result['ready'] is True
    assert sleeps == [3]


def test_settle_visible_draft_box_passes_expected_identity_to_readiness_gate(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class DraftBoxPage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

    calls = []
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(
        flow,
        '_browser_readiness_gate',
        lambda page, **kwargs: calls.append((page, kwargs)) or {
            'ok': True,
            'business_marker': '标题/产品ID',
            'loading': False,
            'body_excerpt': '标题/产品ID',
            'page_title': '店小秘--商品箱',
        },
    )

    page = DraftBoxPage()
    result = flow._settle_visible_draft_box(page, expected_identity='draft_box')

    assert result['ready'] is True
    assert result['read_source'] == 'browser_readiness_gate'
    assert calls == [(page, {
        'label': '商品箱',
        'expected_identity': 'draft_box',
        'ready_terms': WORKFLOW_READY_TERMS['draft_box'],
    })]


def test_settle_visible_draft_box_propagates_readiness_gate_failure(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class Page:
        url = WORKFLOW_TARGETS['data_acquisition']['url']

    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(flow, '_browser_readiness_gate', lambda *_args, **_kwargs: {
        'ok': False,
        'reason': 'wrong_route',
        'loading': False,
        'page_title': '店小秘--商品箱',
    })

    result = flow._settle_visible_draft_box(Page(), expected_identity='draft_box')

    assert result['ready'] is False
    assert result['read_error'] == 'wrong_route'
    assert result['expected_identity'] == 'draft_box'


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
    flow._browser = type('ConnectedBrowser', (), {'is_connected': lambda self: True})()

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


def test_ensure_page_uses_persistent_context_for_visible_browser_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    profile_dir = tmp_path / 'browser-agent-profile'
    monkeypatch.setenv('DXM_WORKFLOW_PROFILE_DIR', str(profile_dir))
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FreshPage:
        url = 'about:blank'

        def __init__(self):
            self.closed = False

        def is_closed(self):
            return self.closed

    class CleanContext:
        def __init__(self):
            self.pages = []
            self.kwargs = None

        def is_closed(self):
            return False

        def new_page(self):
            page = FreshPage()
            self.pages.append(page)
            return page

    class Browser:
        def __init__(self):
            self.contexts = [CleanContext()]

        def is_connected(self):
            return True

        def new_context(self, **kwargs):
            context = CleanContext()
            context.kwargs = kwargs
            self.contexts.append(context)
            return context

    class Chromium:
        def __init__(self):
            self.browsers = []

        def launch(self, **kwargs):
            raise AssertionError('visible persistent profile must launch external Chrome for CDP attach')

        def connect_over_cdp(self, endpoint, **_kwargs):
            self.endpoint = endpoint
            browser = Browser()
            self.browsers.append(browser)
            return browser

        def launch_persistent_context(self, profile_path, **kwargs):
            raise AssertionError('visible persistent profile must not use Playwright launch_persistent_context')

    class FakePlaywright:
        def __init__(self):
            self.chromium = Chromium()

    class FakeStarter:
        def __init__(self):
            self.playwright = FakePlaywright()

        def start(self):
            return self.playwright

    starter = FakeStarter()
    launched = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(command, **_kwargs):
        launched['command'] = command
        return FakeProcess()

    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: starter)
    monkeypatch.setattr(dxm_login_flow_module, 'chrome_launch_options', lambda headless: {'headless': headless, 'executable_path': 'C:/Chrome/chrome.exe'})
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fake_popen)

    page = flow._ensure_page()

    browser = starter.playwright.chromium.browsers[0]
    context = browser.contexts[0]
    assert page is context.pages[0]
    assert page is flow._page
    assert starter.playwright.chromium.endpoint.startswith('http://127.0.0.1:')
    assert any(str(arg).startswith('--remote-debugging-port=') for arg in launched['command'])
    assert f'--user-data-dir={profile_dir.resolve()}' in launched['command']
    start_event = next(event for event in flow.recent_workflow_events() if event['event'] == 'ensure_page:external_cdp_chrome_start')
    assert start_event['has_no_sandbox_arg'] is False


def test_ensure_page_detaches_browser_session_created_on_another_thread(monkeypatch, tmp_path):
    # Cross-thread detachment is independent of the visible CDP façade. Keep
    # this fixture on the in-process headless path so it tests only detachment.
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    monkeypatch.delenv('DXM_LOGIN_HEADED', raising=False)
    monkeypatch.delenv('DXM_DESKTOP', raising=False)
    monkeypatch.delenv('DXM_WORKFLOW_PERSISTENT_PROFILE', raising=False)
    monkeypatch.delenv('DXM_WORKFLOW_PROFILE_DIR', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class OldPage:
        url = 'https://www.dianxiaomi.com/web/home'

        def is_closed(self):
            return False

    class FreshPage:
        url = 'about:blank'

        def is_closed(self):
            return False

    class Context:
        def __init__(self):
            self.pages = []

        def is_closed(self):
            return False

        def new_page(self):
            page = FreshPage()
            self.pages.append(page)
            return page

    class Browser:
        def __init__(self):
            self.contexts = []

        def is_connected(self):
            return True

        def new_context(self, **_kwargs):
            context = Context()
            self.contexts.append(context)
            return context

    class Chromium:
        def __init__(self):
            self.browsers = []

        def launch(self, **_kwargs):
            browser = Browser()
            self.browsers.append(browser)
            return browser

    class FakePlaywright:
        def __init__(self):
            self.chromium = Chromium()

    class FakeStarter:
        def __init__(self):
            self.playwright = FakePlaywright()

        def start(self):
            return self.playwright

    starter = FakeStarter()
    old_page = OldPage()
    flow._page = old_page
    flow._context = object()
    flow._browser = object()
    flow._playwright = object()
    flow._browser_session_thread_id = -1
    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: starter)

    page = flow._ensure_page()

    assert page is not old_page
    assert isinstance(page, FreshPage)
    assert flow._browser_session_thread_id is not None
    assert flow.recent_workflow_events()[0]['event'] == 'browser_session:detached_cross_thread_reuse'


def test_ensure_page_can_use_persistent_profile_when_requested(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    monkeypatch.setenv('DXM_WORKFLOW_PERSISTENT_PROFILE', '1')
    profile_dir = tmp_path / 'browser-agent-profile'
    monkeypatch.setenv('DXM_WORKFLOW_PROFILE_DIR', str(profile_dir))
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FreshPage:
        url = 'about:blank'

    class PersistentContext:
        def __init__(self):
            self.pages = []
            self.kwargs = None
            self.profile_path = None
            self.browser = None

        def is_closed(self):
            return False

        def new_page(self):
            page = FreshPage()
            self.pages.append(page)
            return page

    class Chromium:
        def __init__(self):
            self.browsers = []

        def launch(self, **_kwargs):
            raise AssertionError('persistent profile mode should not launch clean browser')

        def connect_over_cdp(self, endpoint, **_kwargs):
            self.endpoint = endpoint
            context = PersistentContext()
            browser = type('Browser', (), {
                'contexts': [context],
                'is_connected': lambda self: True,
            })()
            self.browsers.append(browser)
            return browser

        def launch_persistent_context(self, profile_path, **kwargs):
            raise AssertionError('persistent profile mode should use external Chrome CDP attach')

    class FakePlaywright:
        def __init__(self):
            self.chromium = Chromium()

    class FakeStarter:
        def __init__(self):
            self.playwright = FakePlaywright()

        def start(self):
            return self.playwright

    starter = FakeStarter()
    launched = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(command, **_kwargs):
        launched['command'] = command
        return FakeProcess()

    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: starter)
    monkeypatch.setattr(dxm_login_flow_module, 'chrome_launch_options', lambda headless: {'headless': headless, 'executable_path': 'C:/Chrome/chrome.exe'})
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fake_popen)

    page = flow._ensure_page()

    context = starter.playwright.chromium.browsers[0].contexts[0]
    assert page is context.pages[0]
    assert starter.playwright.chromium.endpoint.startswith('http://127.0.0.1:')
    assert f'--user-data-dir={profile_dir.resolve()}' in launched['command']


def test_workflow_profile_dir_enables_persistent_visible_profile_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv('DXM_WORKFLOW_PERSISTENT_PROFILE', raising=False)
    monkeypatch.setenv('DXM_WORKFLOW_PROFILE_DIR', str(tmp_path / 'browser-agent-profile'))
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    assert flow._use_persistent_visible_profile() is True


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
    monkeypatch.setattr(
        flow,
        '_find_draft_box_row',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('未找到目标商品行')),
    )

    state = flow.perform_draft_box_action(
        'remark',
        note_text='AI认领',
        product_query='不存在',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

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
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: row)
    monkeypatch.setattr(flow, '_find_draft_box_row_by_frozen_target', lambda *_args, **_kwargs: row)

    state = flow.perform_draft_box_action(
        'remark',
        note_text='AI认领-19-31',
        product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
        store_name='Dang Kang',
        **_frozen_action_kwargs(),
    )

    assert state['stage'] == 'draft_box_action'
    assert state['note_verified'] is True
    assert state['target_row_text'] == row['rowText']


def test_find_draft_box_row_blocks_ambiguous_product_match(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDraftPage({'ok': False, 'ambiguous': True, 'matches': [{'rowText': '重复商品A'}, {'rowText': '重复商品B'}]})

    with pytest.raises(RuntimeError, match='目标商品行不唯一'):
        flow._find_draft_box_row(
            page,
            product_query='重复商品',
            store_name='Dang Kang',
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )


def test_find_draft_box_row_rejects_claim_mark_without_canonical_source(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyClaimMarkDraftPage()

    with pytest.raises(FrozenTargetIdentityError) as exc_info:
        flow._find_draft_box_row(
            page,
            product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
            store_name='Dang Kang',
            claim_mark='AI认领-19-31',
        )

    assert exc_info.value.reason_code == 'EXACT_SOURCE_IDENTITY_REQUIRED'


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


def test_find_draft_box_row_matches_exact_canonical_pdd_source_url(tmp_path):
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
              <td>小马宝莉夏日泳装列柔柔碧琪珍奇云宝苹果嘉儿亚克力8CM10CM立牌 「Dang Kang」</td>
              <td><a href="https://mobile.yangkeduo.com/goods.html?refer_share_id=abc&goods_id=877361738237&_oak_share_ticket=xyz#pushState">来源</a></td>
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
        row = flow._find_draft_box_row(
            page,
            product_query='标题可能已变',
            store_name='Dang Kang',
            target_source_urls=['https://mobile.yangkeduo.com/goods.html?refer_share_id=abc&goods_id=877361738237&_oak_share_ticket=xyz'],
        )
        browser.close()

    assert row['matchedBy'] == 'source_url'
    assert 'goods_id=877361738237' in row['sourceUrls'][0]


def test_find_draft_box_runtime_snapshot_ignores_table_wrapper_duplicate(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: True)
    html = '''
    <html>
      <head>
        <style>
          .table, .row { display: block; }
          button, a { display: inline-block; width: 72px; height: 24px; }
        </style>
      </head>
      <body>
        <div class="table">
          <div class="row wrapper">
            图片 标题/产品ID 分组 价格 库存 运费模板 时间 操作
            <div class="row product">
              <div class="store-cell">拼多多 宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值 「Dang Kang」</div>
              <a href="https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663">来源</a>
              <button>移入待发布</button><button>编辑</button><button>发布</button><button>更多</button>
            </div>
          </div>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        row = flow._find_draft_box_row_with_runtime_snapshot(
            page,
            product_query='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
            store_name='Dang Kang',
            claim_mark='AI-OPS-20260709',
            target_source_urls=['https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663'],
        )
        browser.close()

    assert row is not None
    assert row['matchedBy'] == 'source_url'
    assert row['rowText'].startswith('拼多多 宝可梦精灵球')
    assert '图片 标题/产品ID' not in row['rowText']


def test_find_draft_box_row_matches_exact_canonical_aliexpress_source_url(tmp_path):
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
              <td>Sanrio Hello Kitty Shake Magnetic Phone Stand 「Dang Kang」</td>
              <td><a href="https://www.aliexpress.com/item/1005011837878679.html?spm=a2g0o.productlist.main.1">来源</a></td>
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
        row = flow._find_draft_box_row(
            page,
            product_query='店小秘展示标题已被改写',
            store_name='Dang Kang',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html?spm=a2g0o.productlist.main.1'],
        )
        browser.close()

    assert row['matchedBy'] == 'source_url'
    assert '1005011837878679' in row['sourceUrls'][0]


def test_find_draft_box_row_uses_runtime_timeout_helper(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    def fake_evaluate(target_page, function_source, arg, *, timeout):
        calls.append((target_page, function_source, arg, timeout))
        return {
            'ok': True,
            'rowIndex': 2,
            'rowText': '目标商品 「Dang Kang」 移入待发布 编辑 发布 更多',
            'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
            'actions': [],
            'matchedBy': 'source_url',
        }

    monkeypatch.setattr(flow, '_evaluate_page_function_with_runtime_timeout', fake_evaluate, raising=False)
    page = object()

    row = flow._find_draft_box_row(
        page,
        '目标商品',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert row['matchedBy'] == 'source_url'
    assert calls
    assert calls[0][0] is page
    assert calls[0][2]['frag'] is None
    assert calls[0][3] == 3000


def test_find_draft_box_row_visible_mode_uses_runtime_snapshot_before_locator_or_large_scan(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    foreground_calls = []

    runtime_row = {
        'ok': True,
        'rowIndex': 0,
        'rowText': '目标商品 「Dang Kang」 编辑 更多',
        'sourceUrls': ['https://detail.1688.com/offer/1057791519266.html'],
        'actions': [{'txt': '编辑', 'tag': 'A', 'href': '/web/smt/edit?id=1', 'rect': {}}],
        'matchedBy': 'source_url',
    }
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: foreground_calls.append('front') or True)
    monkeypatch.setattr(flow, '_find_draft_box_row_with_runtime_snapshot', lambda *args, **kwargs: runtime_row)
    monkeypatch.setattr(
        flow,
        '_find_draft_box_row_with_bounded_locators',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('visible draft-box lookup must not use locator path')),
    )

    def fail_large_scan(*_args, **_kwargs):
        raise AssertionError('visible draft-box lookup must not run the large page evaluate scan')

    monkeypatch.setattr(flow, '_evaluate_page_function_with_runtime_timeout', fail_large_scan, raising=False)

    row = flow._find_draft_box_row(
        object(),
        product_query='目标商品',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1057791519266.html'],
    )

    assert row is runtime_row
    assert row['matchedBy'] == 'source_url'


def test_find_draft_box_row_visible_runtime_snapshot_reports_empty_or_loading(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    foreground_calls = []
    calls = []

    def fake_runtime(target_page, function_source, arg, *, timeout):
        calls.append((target_page, arg, timeout))
        return {
            'ok': False,
            'reason': 'draft_box_empty',
            'loading': True,
            'empty': True,
            'rowCount': 0,
            'textExcerpt': '暂无数据 LOADING',
        }

    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: foreground_calls.append('front') or True)
    monkeypatch.setattr(flow, '_evaluate_page_function_with_runtime_timeout', fake_runtime, raising=False)

    with pytest.raises(RuntimeError, match='真实商品箱当前没有找到本次商品'):
        flow._find_draft_box_row_with_runtime_snapshot(
            object(),
            product_query='目标商品',
            store_name='Dang Kang',
            claim_mark='AI-OPS',
            target_source_urls=['https://detail.1688.com/offer/1057791519266.html'],
        )

    assert foreground_calls == ['front']
    assert calls[0][1]['frag'] == '目标商品'
    assert calls[0][2] == 2500


def test_draft_box_claimed_product_title_prefers_row_title_over_source_url(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    title = flow._draft_box_claimed_product_title(
        product_query='https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663',
        row_text='拼多多 宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值 「Dang Kang」 「零 29.94 CNY」 创建： 2026-07-03 移入待发布 编辑 发布 更多',
        category_name='立牌类谷子',
        claimed={'title': ''},
    )

    assert title == '宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值'


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


def test_find_draft_box_row_rejects_title_match_when_authorized_source_url_not_rendered(tmp_path):
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
              <td>小马宝莉夏日泳装列柔柔碧琪珍奇云宝苹果嘉儿亚克力8CM10CM立牌 「Dang Kang」</td>
              <td><button>移入待发布</button><button>编辑</button><button>更多</button></td>
            </tr>
            <tr class="vxe-body--row">
              <td>Another Product 「Dang Kang」</td>
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
                product_query='小马宝莉夏日泳装列柔柔碧琪珍奇云宝苹果嘉儿亚克力8CM10CM立牌',
                store_name='Dang Kang',
                target_source_urls=['https://mobile.yangkeduo.com/goods.html?goods_id=877361738237'],
            )
        browser.close()


def test_find_draft_box_row_handles_virtualized_div_rows_without_picking_table_container(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <body>
        <div class="vxe-table">
          <div class="vxe-table--body-wrapper">
            <div class="vxe-body--row">
              <div class="store-cell">拼多多 小马宝莉夏日泳装列柔柔碧琪珍奇云宝苹果嘉儿亚克力8CM10CM立牌 「Dang Kang」</div>
              <a href="https://mobile.yangkeduo.com/goods.html?goods_id=877361738237">来源</a>
              创建： 2026-06-30 13:15:22 移入待发布 编辑 发布 更多
              <button>编辑</button>
            </div>
            <div class="vxe-body--row">
              拼多多 其它商品 「PI XIU」 创建： 2026-06-30 13:10:00 移入待发布 编辑 发布 更多
            </div>
          </div>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        row = flow._find_draft_box_row(
            page,
            product_query='小马宝莉夏日泳装列柔柔碧琪珍奇云宝苹果嘉儿亚克力8CM10CM立牌',
            store_name='Dang Kang',
            target_source_urls=['https://mobile.yangkeduo.com/goods.html?goods_id=877361738237'],
        )
        browser.close()

    assert row['matchedBy'] == 'source_url'
    assert row['rowText'].count('创建：') == 1


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


def test_data_acquisition_source_urls_require_exact_canonical_match(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    assert flow._source_urls_match(
        ['HTTPS://DETAIL.1688.COM:443/offer/1013604102950.html#fragment'],
        ['https://detail.1688.com/offer/1013604102950.html'],
    ) is True
    assert flow._source_urls_match(
        ['https://detail.1688.com/offer/1013604102950.html.evil'],
        ['https://detail.1688.com/offer/1013604102950.html'],
    ) is False
    assert flow._source_urls_match(
        ['https://detail.1688.com/offer/1013604102950.html?fake=1'],
        ['https://detail.1688.com/offer/1013604102950.html'],
    ) is False


def test_find_data_acquisition_target_rejects_title_candidate_with_fake_source(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    authorized = ['https://detail.1688.com/offer/1013604102950.html']
    source_fallback_calls = []
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target_by_product_query_script',
        lambda *_args, **_kwargs: {
            'ok': True,
            'matchedBy': 'product_query_exact_script',
            'rowText': '目标标题 认领',
            'actionText': '认领',
            'actionRect': {'x': 10, 'y': 20, 'w': 30, 'h': 20},
            'sourceUrls': [authorized[0] + '.evil'],
        },
    )
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target_by_source_url',
        lambda *_args, **_kwargs: source_fallback_calls.append(True) or {
            'ok': False,
            'reason': 'exact source missing',
        },
    )

    result = flow._find_data_acquisition_claim_target(
        object(),
        product_query='目标标题',
        target_source_urls=authorized,
    )

    assert result['ok'] is False
    assert source_fallback_calls == [True]


def test_source_url_lookup_never_falls_back_to_title_when_exact_url_missing(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    title_fallback_calls = []

    class EmptyPage:
        def locator(self, _selector):
            return object()

    monkeypatch.setattr(flow, '_locator_count', lambda _locator: 0)
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target_by_product_query_locator',
        lambda *_args, **_kwargs: title_fallback_calls.append(True) or {
            'ok': True,
            'matchedBy': 'product_query_after_collect',
        },
    )

    result = flow._find_data_acquisition_claim_target_by_source_url(
        EmptyPage(),
        ['https://detail.1688.com/offer/1013604102950.html'],
        product_query='完全相同标题',
    )

    assert result['ok'] is False
    assert title_fallback_calls == []


def test_find_data_acquisition_claim_target_by_source_url_uses_bounded_locators(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          tr, button, a { display: block; width: 240px; height: 28px; }
        </style>
      </head>
      <body>
        <table>
          <tr class="vxe-body--row">
            <td>真实待认领商品</td>
            <td><a href="https://detail.1688.com/offer/1013604102950.html">来源</a></td>
            <td><button>认领</button></td>
          </tr>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        monkeypatch.setattr(
            page,
            'evaluate',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('source lookup must not run page-wide evaluate')),
        )

        row = flow._find_data_acquisition_claim_target_by_source_url(
            page,
            ['https://detail.1688.com/offer/1013604102950.html'],
        )
        browser.close()

    assert row['ok'] is True
    assert row['matchedBy'] == 'source_url'


def test_find_data_acquisition_claim_target_does_not_match_url_authorized_row_by_title_only(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          tr, button { display: block; width: 320px; height: 32px; }
        </style>
      </head>
      <body>
        <table>
          <tr class="vxe-body--row">
            <td>Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand</td>
            <td><button>认领</button></td>
          </tr>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        row = flow._find_data_acquisition_claim_target_by_source_url(
            page,
            ['https://www.aliexpress.com/item/1005011837878679.html'],
            product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
        )
        browser.close()

    assert row['ok'] is False
    assert '未找到来源链接对应的可认领商品行' in row['reason']


def test_source_url_lookup_does_not_fallback_to_title_amid_unrelated_page_links(tmp_path):
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
        <a href="https://www.dianxiaomi.com/help">帮助中心</a>
        <table>
          <tr class="vxe-body--row">
            <td>Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand</td>
            <td><button>认领</button></td>
          </tr>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        row = flow._find_data_acquisition_claim_target_by_source_url(
            page,
            ['https://www.aliexpress.com/item/1005011837878679.html'],
            product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
        )
        browser.close()

    assert row['ok'] is False
    assert '未找到来源链接对应的可认领商品行' in row['reason']


def test_product_query_locator_uses_exact_claim_actions_not_page_containers(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          button, a, span { display: inline-block; width: 96px; height: 24px; }
        </style>
      </head>
      <body>
        <div>导航 产品 数据 认领 采集箱</div>
        <section>链接采集 自动认领 采集并一键发布 开始采集</section>
        <table>
          <tr class="vxe-body--row">
            <td>Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand</td>
            <td><button>认领</button></td>
          </tr>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        row = flow._find_data_acquisition_claim_target_by_product_query_locator(
            page,
            'Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
            target_source_urls=[],
        )
        browser.close()

    assert row is not None
    assert row['ok'] is True
    assert row['matchedBy'] == 'product_query_after_collect'
    assert 'Sanrio Hello Kitty' in row['rowText']


def test_find_data_acquisition_claim_target_by_source_url_rejects_unverified_first_result(tmp_path):
    class PageWithoutResponsiveDom:
        viewport_size = {'width': 1440, 'height': 900}

        def locator(self, *_args, **_kwargs):
            raise RuntimeError('DOM is busy')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    row = flow._find_data_acquisition_claim_target_by_source_url(
        PageWithoutResponsiveDom(),
        ['https://www.aliexpress.com/item/1005011837878679.html'],
        product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
    )

    assert row['ok'] is False
    assert '未找到来源链接对应的可认领商品行' in row['reason']


def test_visible_data_acquisition_source_url_does_not_use_coordinate_fallback(monkeypatch, tmp_path):
    class VisibleDataAcquisitionPage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        viewport_size = {'width': 1440, 'height': 900}

        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError('DOM is still loading')

        def locator(self, *_args, **_kwargs):
            raise RuntimeError('DOM is still loading')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')

    row = flow._find_data_acquisition_claim_target(
        VisibleDataAcquisitionPage(),
        product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert row['ok'] is False
    assert row.get('matchedBy') != 'source_url_search_first_result'
    assert '授权来源' in row['reason'] or '未找到来源链接' in row['reason']


def test_workflow_trace_keeps_recent_events_and_notifies_listener(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    observed = []

    flow.set_workflow_event_listener(observed.append)
    flow._trace_workflow_event(
        'data_acquisition_claim:target_find_start',
        human_step='定位待认领商品',
        token_count=2,
    )

    recent = flow.recent_workflow_events()
    assert recent[-1]['event'] == 'data_acquisition_claim:target_find_start'
    assert recent[-1]['human_step'] == '定位待认领商品'
    assert observed[-1] == recent[-1]


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
              <td>真实待认领商品</td>
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
            product_query='真实待认领商品',
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )
        result = flow._assert_data_acquisition_claim_click_safe(
            page,
            target,
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )
        browser.close()

    assert result['ok'] is True
    assert '认领' in result['action_text']


def test_data_acquisition_claim_click_safety_rejects_list_reorder_to_other_source(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    authorized = ['https://detail.1688.com/offer/1013604102950.html']
    target = {
        'matchedBy': 'source_url',
        'rowText': '授权商品 认领',
        'actionText': '认领',
        'actionRect': {'x': 10, 'y': 20, 'w': 30, 'h': 20},
        'sourceUrls': authorized,
    }

    class ReorderedPage:
        def evaluate(self, *_args, **_kwargs):
            return {
                'ok': True,
                'action_text': '认领',
                'row_text': '另一商品 认领',
                'source_urls': ['https://detail.1688.com/offer/999.html'],
                'page_url': 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
            }

    with pytest.raises(RuntimeError, match='来源与授权目标不一致'):
        flow._assert_data_acquisition_claim_click_safe(
            ReorderedPage(),
            target,
            target_source_urls=authorized,
        )


def test_data_acquisition_claim_click_safety_rejects_source_url_first_result_coordinate(tmp_path):
    class PageThatRejectsEvaluate:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('deprecated coordinate fallback should be rejected before page script')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    target = {
        'matchedBy': 'source_url_search_first_result',
        'rowText': 'Sanrio Hello Kitty 来源URL搜索结果首行 认领',
        'actionText': '认领',
        'actionRect': {'x': 1310, 'y': 683, 'w': 60, 'h': 22},
    }

    with pytest.raises(RuntimeError, match='不再允许使用固定坐标认领'):
        flow._assert_data_acquisition_claim_click_safe(PageThatRejectsEvaluate(), target)


def test_click_rect_center_prefers_browser_input_before_dom_click(monkeypatch, tmp_path):
    class FakeCdp:
        def __init__(self):
            self.events = []

        def send(self, method, payload):
            self.events.append((method, payload))

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class BlockingMouse:
        def click(self, *_args, **_kwargs):
            raise AssertionError('Playwright mouse click should not run when CDP input succeeds')

    class FakePage:
        def __init__(self, cdp):
            self.context = FakeContext(cdp)
            self.mouse = BlockingMouse()
            self.evaluated = []
            self.calls = []

        def bring_to_front(self):
            self.calls.append('bring_to_front')

        def evaluate(self, script, payload):
            raise AssertionError('DOM click should not run before browser input events')

    cdp = FakeCdp()
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: False)
    page = FakePage(cdp)

    flow._click_rect_center(page, {'x': 100, 'y': 200, 'w': 40, 'h': 20})

    assert [method for method, _payload in cdp.events] == [
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
    ]
    assert [payload['type'] for _method, payload in cdp.events] == [
        'mouseMoved',
        'mousePressed',
        'mouseReleased',
    ]
    assert page.calls == ['bring_to_front']


def test_click_rect_center_prefers_cdp_before_native_window_click(monkeypatch, tmp_path):
    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            return {}

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class BlockingMouse:
        def click(self, *_args, **_kwargs):
            raise AssertionError('Playwright mouse should not run when CDP input succeeds')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self, cdp):
            self.context = FakeContext(cdp)
            self.mouse = BlockingMouse()

        def bring_to_front(self):
            pass

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('DOM click should not run when CDP input succeeds')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: True)
    monkeypatch.setattr(
        flow,
        '_click_point_with_native_window',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('native screen click should be fallback only')),
    )

    cdp = FakeCdp()
    page = FakePage(cdp)
    flow._click_rect_center(page, {'x': 100, 'y': 200, 'w': 40, 'h': 20})

    assert [method for method, _payload in cdp.calls] == [
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
    ]


def test_click_rect_center_falls_back_to_native_window_click_when_cdp_fails(monkeypatch, tmp_path):
    class FailingCdp:
        def send(self, *_args, **_kwargs):
            raise RuntimeError('cdp unavailable')

    class FakeContext:
        def new_cdp_session(self, page):
            return FailingCdp()

    class BlockingMouse:
        def click(self, *_args, **_kwargs):
            raise AssertionError('Playwright mouse should not run when native window click succeeds')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        context = FakeContext()
        mouse = BlockingMouse()

        def bring_to_front(self):
            pass

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    native_calls = []
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: True)
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda page, x, y: native_calls.append((page, x, y)) or True)

    page = FakePage()
    flow._click_rect_center(page, {'x': 100, 'y': 200, 'w': 40, 'h': 20})

    assert native_calls == [(page, 120.0, 210.0)]


def test_window_handle_to_int_treats_empty_windows_handles_as_zero(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    assert flow._window_handle_to_int(None) == 0
    assert flow._window_handle_to_int(ctypes.c_void_p(None)) == 0
    assert flow._window_handle_to_int(6817464) == 6817464
    assert flow._window_handle_to_int(ctypes.c_void_p(6817464)) == 6817464


def test_native_click_screen_point_scales_css_coordinates_for_dpi(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._native_click_screen_point(
        {'left': 122, 'top': 238, 'width': 2060, 'height': 1465},
        809.25,
        245.17,
        {'innerWidth': 1373.33, 'innerHeight': 976.67, 'devicePixelRatio': 1.5},
    )

    assert result['screen'] == {'x': 1336, 'y': 606}
    assert round(result['scale']['x'], 2) == 1.5
    assert round(result['scale']['y'], 2) == 1.5


def test_native_click_content_rect_is_clamped_to_window_and_virtual_screen(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    virtual_screen = {'left': 0, 'top': 0, 'width': 3840, 'height': 1200}
    window_rect = {'left': 2202, 'top': 240, 'right': 3634, 'bottom': 1460, 'width': 1432, 'height': 1220}
    oversized_content_rect = {
        'left': 2210,
        'top': 240,
        'right': 4484,
        'bottom': 1329,
        'width': 2274,
        'height': 1089,
    }

    clamped = flow._clamp_native_content_rect(
        oversized_content_rect,
        window_rect=window_rect,
        virtual_screen=virtual_screen,
    )
    point = flow._native_click_screen_point(
        clamped,
        1180.5779876708984,
        99.97814655303955,
        {
            'innerWidth': 1487,
            'innerHeight': 1142,
            'visualViewportWidth': 1487.41259765625,
            'visualViewportHeight': 1142.3077392578125,
            'devicePixelRatio': 0.95333331823349,
        },
    )

    assert clamped == {'left': 2210, 'top': 240, 'right': 3634, 'bottom': 1200, 'width': 1424, 'height': 960}
    assert flow._screen_point_inside_virtual_screen(point['screen'], virtual_screen) is True
    assert point['screen']['x'] < 3840


def test_window_position_match_score_supports_secondary_monitor(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    score = flow._window_position_match_score(
        {'left': 2060, 'top': 120, 'width': 1510, 'height': 980},
        {'screenX': 2060, 'screenY': 120, 'outerWidth': 1510, 'outerHeight': 980},
    )

    assert score >= 100


def test_window_restore_check_accepts_left_secondary_monitor(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    needs_restore = flow._window_needs_restore_to_primary_screen(
        {'left': -1920, 'top': 80, 'width': 1600, 'height': 950},
        virtual_screen={'left': -1920, 'top': 0, 'width': 3840, 'height': 1080},
    )

    assert needs_restore is False


def test_window_restore_check_moves_window_outside_virtual_desktop(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    needs_restore = flow._window_needs_restore_to_primary_screen(
        {'left': -5000, 'top': 80, 'width': 1600, 'height': 950},
        virtual_screen={'left': -1920, 'top': 0, 'width': 3840, 'height': 1080},
    )

    assert needs_restore is True


def test_window_restore_check_treats_tiny_window_as_not_operable(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    needs_restore = flow._window_needs_restore_to_primary_screen(
        {'left': -1200, 'top': 80, 'width': 220, 'height': 160},
        virtual_screen={'left': -1920, 'top': 0, 'width': 3840, 'height': 1080},
    )

    assert needs_restore is True


def test_native_click_viewport_metrics_uses_cdp_timeout_instead_of_page_evaluate(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            return {
                'result': {
                    'value': {
                        'innerWidth': 1440,
                        'innerHeight': 900,
                        'screenX': 2000,
                        'screenY': 80,
                        'outerWidth': 1500,
                        'outerHeight': 960,
                    }
                }
            }

    cdp = FakeCdp()

    class FakeContext:
        def new_cdp_session(self, page):
            return cdp

    class FakePage:
        context = FakeContext()

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('native viewport metrics must not use blocking page.evaluate')

    result = flow._browser_viewport_metrics_for_native_click(FakePage())

    assert result['innerWidth'] == 1440
    assert cdp.calls[0][0] == 'Runtime.evaluate'
    assert cdp.calls[0][1]['timeout'] <= 1000


def test_native_click_viewport_metrics_skips_when_cdp_unavailable_without_page_evaluate(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakeContext:
        def new_cdp_session(self, page):
            raise RuntimeError('cdp unavailable')

    class FakePage:
        context = FakeContext()

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('fallback page.evaluate can hang visible DXM editor pages')

    result = flow._browser_viewport_metrics_for_native_click(FakePage())

    assert result == {}
    assert flow.recent_workflow_events()[-1]['event'] == 'click_rect:native_viewport_metrics_skipped'


def test_visible_editor_title_native_input_uses_win32_only_click_path(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    click_calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def fake_click(page, x, y, **kwargs):
        click_calls.append({'page': page, 'x': x, 'y': y, **kwargs})
        return True

    reads = iter(['', '真实商品标题'])

    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: next(reads))
    monkeypatch.setattr(flow, '_click_point_with_native_window', fake_click)
    monkeypatch.setattr(flow, '_replace_active_field_with_native_clipboard_text', lambda text: True)

    result = flow._fill_visible_editor_title_with_native_input(FakePage(), '真实商品标题')

    assert result['ok'] is True
    assert click_calls[0]['use_viewport_metrics'] is False


def test_visible_editor_title_native_input_rejects_empty_readback_after_every_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    click_calls = []
    paste_calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: '')
    monkeypatch.setattr(
        flow,
        '_click_point_with_native_window',
        lambda *args, **kwargs: click_calls.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(
        flow,
        '_replace_active_field_with_native_clipboard_text',
        lambda text: paste_calls.append(text) or True,
    )

    result = flow._fill_visible_editor_title_with_native_input(FakePage(), 'Pokemon Poke Ball Toy Model')
    events = [event['event'] for event in flow.recent_workflow_events()]

    assert result == {'ok': False, 'reason': 'visible_editor_title_native_input_failed'}
    assert len(click_calls) == 3
    assert paste_calls == ['Pokemon Poke Ball Toy Model'] * 3
    assert events.count('visible_editor_title:native_empty_readback') == 3
    assert 'visible_editor_title:native_done' not in events


def test_visible_editor_title_native_input_rejects_unverified_clipboard_write(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    reads = iter(['宝可梦中文标题', '宝可梦中文标题', '宝可梦中文标题', '宝可梦中文标题'])

    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: next(reads, '宝可梦中文标题'))
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *args, **kwargs: True)
    monkeypatch.setattr(flow, '_replace_active_field_with_native_clipboard_text', lambda text: True)

    result = flow._fill_visible_editor_title_with_native_input(
        FakePage(),
        'Pokemon Poke Ball Toy Model',
        force_replace=True,
    )

    assert result['ok'] is False
    assert result['reason'] == 'visible_editor_title_native_input_failed'
    assert any(event['event'] == 'visible_editor_title:native_value_mismatch' for event in flow.recent_workflow_events())


def test_visible_editor_title_native_input_accepts_existing_dom_value_without_native_click(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    def fail_native_click(*_args, **_kwargs):
        raise AssertionError('existing visible title must not require a native click')

    monkeypatch.setattr(flow, '_click_point_with_native_window', fail_native_click)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <input name="subject"
              value="宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值"
              style="position:absolute;left:40px;top:180px;width:700px;height:32px" />
          </body>
        </html>
        ''')

        result = flow._fill_visible_editor_title_with_native_input(
            page,
            '宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
        )
        browser.close()

    assert result['ok'] is True
    assert result['already_present'] is True
    assert result['method'] == 'dom_existing_value'


def test_visible_editor_later_steps_require_dom_readback_instead_of_trusting_visible_page(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class NoDomPage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def title(self):
            return '店小秘编辑页'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible editor preserve path must not run page.evaluate')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible editor preserve path must not take Playwright screenshots')

        def __getattr__(self, _name):
            raise AssertionError('visible editor must not use an unavailable page DOM API')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    with pytest.raises(AssertionError, match='must not run page.evaluate'):
        flow._fill_editor_variants_on_page(NoDomPage(), _legacy_explicit_editor_defaults())
    with pytest.raises(AssertionError, match='must not run page.evaluate'):
        flow._fill_media_assets_on_page(
            NoDomPage(),
            _legacy_explicit_editor_defaults(eu_outer_package_filename='package.jpg'),
        )
    with pytest.raises(AssertionError, match='must not (run page.evaluate|use an unavailable page DOM API)'):
        flow._fill_compliance_defaults_on_page(NoDomPage(), _legacy_explicit_editor_defaults())


def test_visible_semi_managed_defaults_require_dom_readback_instead_of_trusting_visible_page(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class NoDomPage:
        url = 'https://www.dianxiaomi.com/web/smt/editFromSmt'

        def title(self):
            return '店小秘半托管页'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible semi managed preserve path must not run page.evaluate')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible semi managed preserve path must not take Playwright screenshots')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    with pytest.raises(AssertionError, match='must not run page.evaluate'):
        flow._fill_semi_managed_defaults_on_page(NoDomPage(), _legacy_explicit_editor_defaults())


def test_visible_editor_fill_semi_action_does_not_regoto_current_editor(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    state_file = tmp_path / 'runtime.json'
    state_file.write_text(
        '{"page_url":"https://www.dianxiaomi.com/web/smt/edit?id=123","source_editor_url":"https://www.dianxiaomi.com/web/smt/edit?id=123"}',
        encoding='utf-8',
    )
    flow = DxmLoginFlow(live_client, state_file=state_file)

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible fill_semi action must not run page.evaluate')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: FakePage())
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('visible fill_semi action must not re-goto editor')),
    )
    monkeypatch.setattr(
        flow,
        '_fill_semi_managed_defaults_on_page',
        lambda *_args, **_kwargs: {'stage': 'semi_managed_defaults_filled'},
    )

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'fill_semi_managed_defaults',
        _legacy_explicit_editor_defaults(),
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'semi_managed_defaults_filled'
    assert result['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'


def test_visible_editor_save_prefill_requires_main_image_dom_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class NoDomTitlePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def title(self):
            raise AssertionError('visible save prefill must not read page.title')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_media_assets_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'media_assets_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(
        flow,
        '_repair_product_main_images_on_page',
        lambda page: (_ for _ in ()).throw(AssertionError('visible save prefill must not run main-image DOM repair')),
    )

    with pytest.raises(AssertionError, match='must not run main-image DOM repair'):
        flow._prepare_editor_page_for_save(NoDomTitlePage(), _legacy_explicit_editor_defaults())


def test_visible_editor_save_only_fails_fast_when_exact_save_locator_is_not_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class NoDomPage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def title(self):
            raise AssertionError('visible save guard must not read page.title')

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible save guard must not run page.evaluate')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible save guard must not take Playwright screenshot')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_visible_exact_save_button_state',
        lambda page: {'ok': False, 'reason': '未找到精确保存按钮', 'published': None},
    )
    monkeypatch.setattr(
        flow,
        '_click_point_with_native_window',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('unsafe save target must not be clicked')),
    )

    result = flow._save_only_on_page(NoDomPage(), **_save_only_kwargs())

    assert result['stage'] == 'save_only_failed'
    assert result['save_result']['reason'] == '未找到精确保存按钮'
    assert result['save_result']['clicked'] is False


def test_visible_editor_save_only_clicks_exact_save_with_native_window(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', lambda *_args, **_kwargs: {
        'path': str((tmp_path / 'visible-save-proof.png').resolve()), 'sha256': 'A' * 64, 'size': 1,
    })
    monkeypatch.setattr(flow, '_artifact_url', lambda _path: '/artifacts/visible-save-proof.png')
    clicks = []

    class VisibleSavePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def wait_for_timeout(self, _timeout):
            return None

        def title(self):
            raise AssertionError('visible save path must not read page.title')

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible save path must use bounded helper, not direct page.evaluate')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible save path must not take Playwright screenshot')

    locator_state = {
        'ok': True,
        'text': '保存',
        'at_point_text': '保存',
        'exact_save_count': 1,
        'rect': {'x': 120.0, 'y': 240.0, 'w': 80.0, 'h': 32.0},
        'viewport': {'innerWidth': 1440, 'innerHeight': 900, 'devicePixelRatio': 1},
        'forbidden_actions': [{'text': '保存并移入待发布', 'rect': {'x': 220, 'y': 240, 'w': 160, 'h': 32}}],
    }
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_visible_exact_save_button_state', lambda page: locator_state)
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda page, rect: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_network_save_result', lambda events: {'ok': True, 'message': '您的产品编辑成功！', 'code': 0})
    monkeypatch.setattr(flow, '_structured_save_status_snapshot', lambda *_args, **_kwargs: {'ok': True, 'entries': []})
    monkeypatch.setattr(
        flow,
        '_visible_save_success_state',
        lambda page, *, baseline=None: {'ok': True, 'success_text': '保存成功', 'published': False},
    )
    def authorized_native_click(page, x, y, **kwargs):
        clicks.append({'x': x, 'y': y, **kwargs})
        authorization = flow._dispatch_authorized_mutation(
            kwargs['mutation_action'],
            lambda: True,
            pre_dispatch_guard=kwargs['pre_dispatch_guard'],
        )
        return authorization['operation_result']

    monkeypatch.setattr(flow, '_click_point_with_native_window', authorized_native_click)

    result = flow._save_only_on_page(VisibleSavePage(), **_save_only_kwargs())

    assert result['stage'] == 'save_only'
    assert result['page_title'] == '店小秘编辑页'
    assert result['save_result']['clicked'] is True
    assert result['save_result']['click_method'] == 'native_exact_save'
    assert result['save_result']['network_save_result']['ok'] is True
    assert result['save_result']['mutation_authorization']['executed'] is True
    assert result['save_result']['exact_save_target'] is True
    assert result['save_result']['save_click_dispatched'] is True
    assert result['save_result']['network_save_success'] is True
    assert result['save_result']['page_save_success'] is True
    assert result['save_result']['publish_action_clicked'] is False
    assert len(clicks) == 1
    assert clicks[0]['x'] == 160.0
    assert clicks[0]['y'] == 256.0
    assert clicks[0]['use_viewport_metrics'] is False
    assert clicks[0]['viewport_metrics_override'] == locator_state['viewport']
    assert clicks[0]['mutation_action'] == 'save_only_click'
    assert callable(clicks[0]['pre_dispatch_guard'])


def test_visible_editor_save_only_stops_when_native_exact_save_click_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class VisibleSavePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def wait_for_timeout(self, _timeout):
            return None

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_visible_exact_save_button_state',
        lambda page: {'ok': True, 'text': '保存', 'rect': {'x': 10, 'y': 20, 'w': 40, 'h': 20}, 'viewport': {'innerWidth': 1200, 'innerHeight': 800}},
    )
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda page, rect: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *args, **kwargs: False)

    result = flow._save_only_on_page(VisibleSavePage(), **_save_only_kwargs())

    assert result['stage'] == 'save_only_failed'
    assert result['save_result']['reason'] == 'native_exact_save_click_failed'
    assert result['save_result']['clicked'] is False


def test_visible_exact_save_button_state_uses_independent_devtools_probe(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def fake_devtools_probe(page, script, *, timeout=1800):
        calls.append({'page': page, 'script': script, 'timeout': timeout})
        return {
            'ok': True,
            'text': '保存',
            'rect': {'x': 100, 'y': 200, 'w': 80, 'h': 32},
            'viewport': {'innerWidth': 1440, 'innerHeight': 900, 'devicePixelRatio': 1},
            'published': False,
        }

    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fake_devtools_probe, raising=False)
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible save locator must not use Playwright Runtime.evaluate')),
    )

    state = flow._visible_exact_save_button_state(FakePage())

    assert state['ok'] is True
    assert state['text'] == '保存'
    assert calls and calls[0]['timeout'] == 1800


def test_visible_exact_save_button_state_fails_fast_when_devtools_probe_is_unavailable(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    monkeypatch.setattr(
        flow,
        '_evaluate_visible_page_function_via_devtools',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('DevTools target unavailable')),
        raising=False,
    )
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('devtools failure must not fall back to Playwright Runtime.evaluate')),
    )
    monkeypatch.setattr(flow, '_capture_native_dxm_content_snapshot', lambda page: None, raising=False)

    state = flow._visible_exact_save_button_state(FakePage())

    assert state['ok'] is False
    assert state['published'] is None
    assert 'DevTools target unavailable' in state['reason']


def test_visible_exact_save_button_state_does_not_trust_native_toolbar_pixels_when_devtools_times_out(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def bgra_snapshot(width, height, rects):
        pixels = bytearray([255, 255, 255, 255] * width * height)
        for rect in rects:
            x0, y0, w, h = rect['box']
            r, g, b = rect['rgb']
            for y in range(y0, y0 + h):
                for x in range(x0, x0 + w):
                    index = (y * width + x) * 4
                    pixels[index:index + 4] = bytes((b, g, r, 255))
        return {'width': width, 'height': height, 'pixels': bytes(pixels), 'format': 'bgra'}

    snapshot = bgra_snapshot(
        900,
        260,
        [
            {'box': (320, 62, 135, 34), 'rgb': (255, 105, 55)},  # 保存并移入待发布
            {'box': (468, 62, 58, 34), 'rgb': (255, 105, 55)},   # 保存
            {'box': (540, 62, 72, 34), 'rgb': (0, 153, 102)},    # 发布
        ],
    )
    monkeypatch.setattr(
        flow,
        '_evaluate_visible_page_function_via_devtools',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('独立 DevTools 调用超时。')),
        raising=False,
    )
    monkeypatch.setattr(flow, '_capture_native_dxm_content_snapshot', lambda page: snapshot, raising=False)

    state = flow._visible_exact_save_button_state(FakePage())

    assert state['ok'] is False
    assert '精确文本定位通道不可用' in state['reason']
    assert state['native_fallback'] is None
    assert state['published'] is None


def test_visible_save_success_state_uses_independent_devtools_probe(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def fake_devtools_probe(page, script, *, timeout=1800):
        calls.append({'page': page, 'script': script, 'timeout': timeout})
        return {
            'ok': True,
            'entries': [{'id': 'new-toast', 'text': '保存成功', 'status': '', 'source': 'ant-message-notice'}],
        }

    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fake_devtools_probe, raising=False)
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible success check must not use Playwright Runtime.evaluate')),
    )

    state = flow._visible_save_success_state(FakePage(), baseline={'ok': True, 'entries': []})

    assert state['ok'] is True
    assert state['success_text'] == '保存成功'
    assert calls and calls[0]['timeout'] == 1800


@pytest.mark.parametrize(
    ('baseline_entries', 'current_entries', 'expected_ok', 'expected_reason'),
    [
        ([], [], False, 'structured_save_success_missing'),
        (
            [{'id': 'old-toast', 'text': '保存成功', 'status': '', 'source': 'ant-message-notice'}],
            [{'id': 'old-toast', 'text': '保存成功', 'status': '', 'source': 'ant-message-notice'}],
            False,
            'stale_save_success_status',
        ),
        (
            [],
            [{'id': 'new-toast', 'text': '保存成功', 'status': '', 'source': 'ant-message-notice'}],
            True,
            None,
        ),
    ],
    ids=['body-text-only', 'unchanged-old-toast', 'new-toast'],
)
def test_visible_save_success_requires_new_structured_status_transition(
    monkeypatch,
    tmp_path,
    baseline_entries,
    current_entries,
    expected_ok,
    expected_reason,
):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    probes = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    def fake_devtools_probe(page, script, arg=None, *, timeout=1800):
        probes.append((page, script, arg, timeout))
        return {'ok': True, 'entries': current_entries}

    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fake_devtools_probe, raising=False)

    state = flow._visible_save_success_state(
        FakePage(),
        baseline={'ok': True, 'entries': baseline_entries},
    )

    assert state['ok'] is expected_ok
    assert state.get('reason') == expected_reason
    assert 'document.body' not in probes[0][1]
    assert '__DXM_STRUCTURED_SAVE_STATUS_SNAPSHOT__' in probes[0][1]


def test_visible_save_success_state_reports_visible_validation_error(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <div class="ant-message-notice" style="position:absolute;left:20px;top:20px">
              产品信息中有错误，请检查：产品分类 请选择分类
            </div>
          </body>
        </html>
        ''')
        monkeypatch.setattr(
            flow,
            '_evaluate_visible_page_function_via_devtools',
            lambda target_page, script, *, timeout=1800: target_page.evaluate(script),
            raising=False,
        )

        state = flow._visible_save_success_state(page, baseline={'ok': True, 'entries': []})
        browser.close()

    assert state['ok'] is False
    assert state['reason'] == '保存后页面提示：产品信息中有错误，请检查：产品分类 请选择分类'
    assert state['validation_error'] is True


def test_visible_runtime_evaluate_uses_independent_devtools_when_port_is_available(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._remote_debugging_port = 24680
    calls = []

    class FakeContext:
        def new_cdp_session(self, _page):
            raise AssertionError('visible external Chrome must not use Playwright CDP session')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'
        context = FakeContext()

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible external Chrome must not fall back to page.evaluate')

    def fake_devtools_probe(page, script, arg=None, *, timeout=3000):
        calls.append({'page': page, 'script': script, 'arg': arg, 'timeout': timeout})
        return {'ok': True, 'rowCount': 1, 'arg': arg}

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fake_devtools_probe, raising=False)

    result = flow._evaluate_page_function_with_runtime_timeout(
        FakePage(),
        '({target}) => ({ok:true,target})',
        {'target': 'Spongebo'},
        timeout=2500,
    )

    assert result['ok'] is True
    assert result['arg'] == {'target': 'Spongebo'}
    assert calls == [{
        'page': calls[0]['page'],
        'script': '({target}) => ({ok:true,target})',
        'arg': {'target': 'Spongebo'},
        'timeout': 2500,
    }]


def test_visible_native_viewport_metrics_use_independent_devtools(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._remote_debugging_port = 24680
    calls = []

    class FakeContext:
        def new_cdp_session(self, _page):
            raise AssertionError('visible external Chrome must not use Playwright CDP for viewport metrics')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'
        context = FakeContext()

    def fake_devtools_probe(page, script, arg=None, *, timeout=3000):
        calls.append({'page': page, 'script': script, 'arg': arg, 'timeout': timeout})
        return {
            'innerWidth': 1440,
            'innerHeight': 900,
            'screenX': 80,
            'screenY': 80,
            'outerWidth': 1600,
            'outerHeight': 950,
        }

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_evaluate_visible_page_function_via_devtools', fake_devtools_probe, raising=False)

    metrics = flow._browser_viewport_metrics_for_native_click(FakePage())

    assert metrics['innerWidth'] == 1440
    assert metrics['outerHeight'] == 950
    assert len(calls) == 1
    assert calls[0]['arg'] is None
    assert calls[0]['timeout'] == 900


def test_run_coroutine_from_sync_uses_worker_thread_when_event_loop_is_running(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    caller_thread_id = threading.get_ident()

    async def sample():
        return {'ok': True, 'thread_id': threading.get_ident()}

    async def call_from_running_loop():
        return flow._run_coroutine_from_sync(lambda: sample(), timeout_s=1.0)

    result = asyncio.run(call_from_running_loop())

    assert result['ok'] is True
    assert result['thread_id'] != caller_thread_id


def test_visible_persistent_browser_launches_external_cdp_without_playwright_pipe(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    launched = {}

    class FakePage:
        url = 'about:blank'

    class FakeContext:
        pages = [FakePage()]

        def is_closed(self):
            return False

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def is_connected(self):
            return True

    class FakeChromium:
        def connect_over_cdp(self, endpoint, **_kwargs):
            launched['endpoint'] = endpoint
            return FakeBrowser()

        def launch_persistent_context(self, *_args, **_kwargs):
            raise AssertionError('visible persistent browser must not use Playwright launch_persistent_context')

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    class FakeProcess:
        pid = 12345

    def fake_popen(command, **_kwargs):
        launched['command'] = command
        return FakeProcess()

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_use_persistent_visible_profile', lambda: True)
    monkeypatch.setattr(flow, '_workflow_browser_profile_dir', lambda: tmp_path / 'dxm_workflow')
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: FakeSyncPlaywright())
    monkeypatch.setattr(dxm_login_flow_module, 'chrome_launch_options', lambda headless: {'headless': headless, 'executable_path': 'C:/Chrome/chrome.exe'})
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fake_popen)

    page = flow._ensure_page()

    assert page.url == 'about:blank'
    assert launched['endpoint'].startswith('http://127.0.0.1:')
    assert launched['command'][0] == 'C:/Chrome/chrome.exe'
    assert any(arg.startswith('--remote-debugging-port=') for arg in launched['command'])
    assert '--remote-debugging-pipe' not in launched['command']


def test_visible_persistent_browser_reuses_existing_profile_devtools_port(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    launched = {}
    profile_dir = tmp_path / 'dxm_workflow'

    class FakePage:
        url = 'about:blank'

    class FakeContext:
        pages = [FakePage()]

        def is_closed(self):
            return False

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def is_connected(self):
            return True

    class FakeChromium:
        def connect_over_cdp(self, endpoint, **_kwargs):
            launched['endpoint'] = endpoint
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    def fail_popen(*_args, **_kwargs):
        raise AssertionError('existing profile browser must be reused instead of launching another port')

    monkeypatch.setattr(flow, '_devtools_http_ready_on_port', lambda port: port == 3386)
    monkeypatch.setattr(
        flow,
        '_chrome_command_lines_for_profile',
        lambda _profile: [f'"C:/Chrome/chrome.exe" --remote-debugging-port=3386 --user-data-dir="{profile_dir}" about:blank'],
    )
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fail_popen)
    flow._playwright = FakePlaywright()

    page = flow._launch_visible_persistent_context_over_cdp(
        profile_dir,
        {'executable_path': 'C:/Chrome/chrome.exe', 'args': ['--remote-debugging-port=6570']},
    )

    assert page.url == 'about:blank'
    assert launched['endpoint'] == 'http://127.0.0.1:3386'
    assert flow._remote_debugging_port == 3386


def test_ensure_page_promotes_home_opened_by_async_login_redirect(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FakePage:
        def __init__(self, url):
            self.url = url
            self.context = None

        def is_closed(self):
            return False

    login_page = FakePage('https://www.dianxiaomi.com/')
    home_page = FakePage('https://www.dianxiaomi.com/web/home?ts=1')

    class FakeContext:
        pages = [login_page, home_page]

        def is_closed(self):
            return False

    context = FakeContext()
    login_page.context = context
    home_page.context = context

    class FakeBrowser:
        contexts = [context]

        def is_connected(self):
            return True

    flow._page = login_page
    flow._context = context
    flow._browser = FakeBrowser()
    flow._browser_session_thread_id = threading.get_ident()

    assert flow._ensure_page() is home_page
    assert flow._context is context


def test_existing_profile_devtools_port_recycles_process_when_http_is_unreachable(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    profile_dir = tmp_path / 'dxm_workflow'
    terminated_profiles = []

    monkeypatch.setattr(
        flow,
        '_chrome_command_lines_for_profile',
        lambda _profile: [f'"C:/Chrome/chrome.exe" --remote-debugging-port=3386 --user-data-dir="{profile_dir}" about:blank'],
    )
    monkeypatch.setattr(flow, '_devtools_http_ready_on_port', lambda port: False)
    monkeypatch.setattr(
        flow,
        '_terminate_existing_profile_chrome_processes',
        lambda profile: terminated_profiles.append(profile),
    )

    assert flow._existing_profile_devtools_port(profile_dir) is None
    assert terminated_profiles == [profile_dir]


def test_visible_browser_defaults_to_persistent_workflow_profile(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    monkeypatch.delenv('DXM_WORKFLOW_PERSISTENT_PROFILE', raising=False)
    monkeypatch.delenv('DXM_DESKTOP', raising=False)
    monkeypatch.delenv('DXM_WORKFLOW_PROFILE_DIR', raising=False)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    assert flow._use_persistent_visible_profile() is True


def test_visible_persistent_browser_restarts_existing_profile_when_page_runtime_hangs(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    profile_dir = tmp_path / 'dxm_workflow'
    attempts = []
    launched = {}
    terminated_profiles = []

    class FakePage:
        url = 'about:blank'

    class FakeContext:
        pages = [FakePage()]

        def is_closed(self):
            return False

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def is_connected(self):
            return True

    class FakeChromium:
        def connect_over_cdp(self, endpoint, **kwargs):
            attempts.append(endpoint)
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeProcess:
        pid = 56789

    def fake_popen(command, **_kwargs):
        launched['command'] = command
        return FakeProcess()

    monkeypatch.setattr(flow, '_devtools_http_ready_on_port', lambda port: port == 3386)
    monkeypatch.setattr(flow, '_devtools_page_runtime_healthy_on_port', lambda port: False if port == 3386 else True)
    monkeypatch.setattr(
        flow,
        '_chrome_command_lines_for_profile',
        lambda _profile: [f'"C:/Chrome/chrome.exe" --remote-debugging-port=3386 --user-data-dir="{profile_dir}" about:blank'],
    )
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(flow, '_allocate_loopback_port', lambda: 45212)
    monkeypatch.setattr(
        flow,
        '_terminate_existing_profile_chrome_processes',
        lambda profile: terminated_profiles.append(profile),
        raising=False,
    )
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fake_popen)
    flow._playwright = FakePlaywright()

    page = flow._launch_visible_persistent_context_over_cdp(
        profile_dir,
        {'executable_path': 'C:/Chrome/chrome.exe', 'args': ['--remote-debugging-port=6570']},
    )

    assert page.url == 'about:blank'
    assert terminated_profiles == [profile_dir]
    assert attempts == ['http://127.0.0.1:45212']
    assert any(arg == '--remote-debugging-port=45212' for arg in launched['command'])
    assert flow._remote_debugging_port == 45212


def test_visible_persistent_browser_restarts_stale_existing_profile_when_cdp_connect_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    profile_dir = tmp_path / 'dxm_workflow'
    attempts = []
    launched = {}
    terminated_profiles = []

    class FakePage:
        url = 'about:blank'

    class FakeContext:
        pages = [FakePage()]

        def is_closed(self):
            return False

        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def is_connected(self):
            return True

    class FakeChromium:
        def connect_over_cdp(self, endpoint, **kwargs):
            attempts.append((endpoint, kwargs.get('timeout')))
            if endpoint == 'http://127.0.0.1:3386':
                raise TimeoutError('stale browser CDP did not finish attaching')
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeProcess:
        pid = 45678

    def fake_popen(command, **_kwargs):
        launched['command'] = command
        return FakeProcess()

    monkeypatch.setattr(flow, '_devtools_http_ready_on_port', lambda port: port == 3386)
    monkeypatch.setattr(
        flow,
        '_chrome_command_lines_for_profile',
        lambda _profile: [f'"C:/Chrome/chrome.exe" --remote-debugging-port=3386 --user-data-dir="{profile_dir}" about:blank'],
    )
    monkeypatch.setattr(flow, '_wait_for_visible_devtools_http', lambda port: {'Browser': 'Chrome/test'})
    monkeypatch.setattr(flow, '_allocate_loopback_port', lambda: 45211)
    monkeypatch.setattr(
        flow,
        '_terminate_existing_profile_chrome_processes',
        lambda profile: terminated_profiles.append(profile),
        raising=False,
    )
    monkeypatch.setattr(dxm_login_flow_module.subprocess, 'Popen', fake_popen)
    flow._playwright = FakePlaywright()

    page = flow._launch_visible_persistent_context_over_cdp(
        profile_dir,
        {'executable_path': 'C:/Chrome/chrome.exe', 'args': ['--remote-debugging-port=6570']},
    )

    assert page.url == 'about:blank'
    assert attempts[0][0] == 'http://127.0.0.1:3386'
    assert attempts[0][1] <= 10000
    assert terminated_profiles == [profile_dir]
    assert attempts[-1] == ('http://127.0.0.1:45211', attempts[-1][1])
    assert any(arg == '--remote-debugging-port=45211' for arg in launched['command'])
    assert flow._remote_debugging_port == 45211


def test_visible_editor_semi_entry_steps_require_dom_verification(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class NoDomPage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def title(self):
            return '店小秘编辑页'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible semi entry preserve path must not run page.evaluate')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible semi entry preserve path must not take Playwright screenshots')

        def __getattr__(self, _name):
            raise AssertionError('visible semi entry must not use an unavailable page DOM API')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    with pytest.raises(AssertionError, match='must not run page.evaluate'):
        flow._enable_semi_managed_on_page(NoDomPage())
    with pytest.raises(AssertionError, match='must not (run page.evaluate|use an unavailable page DOM API)'):
        flow._open_semi_managed_page_from_editor(
            NoDomPage(),
            _legacy_explicit_editor_defaults(),
        )


def test_data_acquisition_claim_rect_click_prefers_page_mouse_for_visible_claim_page(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    class FakeMouse:
        def click(self, x, y, **kwargs):
            clicks.append((x, y, kwargs))

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        mouse = FakeMouse()

    monkeypatch.setattr(
        flow,
        '_click_rect_center',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('claim click must use page mouse before native/window fallback')),
    )

    flow._click_data_acquisition_claim_rect_center(FakePage(), {'x': 100, 'y': 200, 'w': 40, 'h': 20}, purpose='认领按钮')

    assert clicks == [(120.0, 210.0, {'delay': 50})]
    assert flow.recent_workflow_events()[-1]['event'] == 'data_acquisition_claim:page_mouse_click_done'


def test_claim_click_revalidates_inside_dispatch_helper_immediately_before_mouse(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakeMouse:
        def click(self, *_args, **_kwargs):
            events.append('dispatch')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        mouse = FakeMouse()

    def authorize(_context, operation):
        events.append('authorize')
        guard_result = _context['_pre_dispatch_guard']()
        if guard_result.get('ok') is not True:
            return {'ok': False, 'executed': False, 'reason_code': 'MUTATION_TARGET_DRIFT'}
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(
        authorize,
        {'task_id': 1, 'job_id': 2, 'state': 'CLAIM_TO_DRAFT_BOX', 'mode': 'claim_only'},
    )

    flow._click_data_acquisition_claim_rect_center(
        FakePage(),
        {'x': 10, 'y': 20, 'w': 30, 'h': 20},
        purpose='认领按钮',
        mutation_action='claim_open_dialog_click',
        pre_dispatch_guard=lambda: events.append('target_guard') or {'ok': True},
    )

    assert events == ['authorize', 'target_guard', 'dispatch']


def test_claim_click_target_drift_after_authorization_never_dispatches_mouse(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakeMouse:
        def click(self, *_args, **_kwargs):
            events.append('dispatch')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        mouse = FakeMouse()

    def authorize(_context, operation):
        events.append('authorize')
        guard_result = _context['_pre_dispatch_guard']()
        if guard_result.get('ok') is not True:
            return {'ok': False, 'executed': False, 'reason_code': 'MUTATION_TARGET_DRIFT'}
        return {
            'ok': True,
            'executed': True,
            'operation_result': operation(),
        }

    flow.set_mutation_authorizer(authorize, {'task_id': 1})

    with pytest.raises(MutationAuthorizationError, match='MUTATION_TARGET_DRIFT'):
        flow._click_data_acquisition_claim_rect_center(
            FakePage(),
            {'x': 10, 'y': 20, 'w': 30, 'h': 20},
            purpose='认领按钮',
            mutation_action='claim_open_dialog_click',
            pre_dispatch_guard=lambda: events.append('target_guard') or {
                'ok': False,
                'reason': 'claim row changed during authorization',
            },
        )

    assert events == ['authorize', 'target_guard']


def test_exact_save_revalidates_immediately_before_dom_dispatch(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakePage:
        def __init__(self):
            _install_exact_save_handle(self, events)

        def locator(self, *_args, **_kwargs):
            raise AssertionError('DOM exact save path should complete')

        def wait_for_timeout(self, _timeout):
            events.append('wait')

    def authorize(_context, operation):
        events.append('authorize')
        guard_result = _context['_pre_dispatch_guard']()
        if guard_result.get('ok') is not True:
            return {'ok': False, 'executed': False, 'reason_code': 'MUTATION_TARGET_DRIFT'}
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(
        authorize,
        {'task_id': 3, 'job_id': 4, 'state': 'SAVE_ONLY', 'mode': 'single_save'},
    )

    assert flow._click_exact_save_button(FakePage(), mutation_action='save_only_click') is True
    assert events == ['authorize', 'target_guard', 'dispatch']


def test_exact_save_dispatch_error_never_retries_with_locator_or_coordinate_click(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakePage:
        def __init__(self):
            _install_exact_save_handle(self, events, dispatch_error=RuntimeError('DOM dispatch failed'))

        def wait_for_timeout(self, _timeout):
            events.append('wait')

        def locator(self, _selector):
            events.append('locator_fallback')
            raise AssertionError('failed authorized operation must not enter locator fallback')

    def authorize(_context, operation):
        events.append('authorize')
        guard_result = _context['_pre_dispatch_guard']()
        if guard_result.get('ok') is not True:
            return {'ok': False, 'executed': False, 'reason_code': 'MUTATION_TARGET_DRIFT'}
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})
    monkeypatch.setattr(
        flow,
        '_click_rect_center',
        lambda *_args, **_kwargs: events.append('coordinate_fallback'),
    )

    with pytest.raises(RuntimeError, match='MUTATION_OPERATION_FAILED'):
        flow._click_exact_save_button(FakePage(), mutation_action='save_only_click')

    assert events == ['authorize', 'target_guard', 'dispatch']


def test_exact_save_locator_executes_only_inside_authorizer(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakePage:
        def __init__(self):
            _install_exact_save_handle(self, events)

    def authorize(_context, operation):
        events.append('authorize')
        guard_result = _context['_pre_dispatch_guard']()
        if guard_result.get('ok') is not True:
            return {'ok': False, 'executed': False, 'reason_code': 'MUTATION_TARGET_DRIFT'}
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})

    assert flow._click_exact_save_button(FakePage(), mutation_action='save_only_click') is True
    assert events == ['authorize', 'target_guard', 'dispatch']


def test_click_rect_page_mouse_executes_only_inside_authorizer(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakeMouse:
        def click(self, *_args, **_kwargs):
            events.append('mouse_click')

    class FakePage:
        mouse = FakeMouse()

        def bring_to_front(self):
            return None

    def authorize(_context, operation):
        events.append('authorize')
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})
    monkeypatch.setattr(flow, '_click_point_with_cdp', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *_args, **_kwargs: False)

    flow._click_rect_center(
        FakePage(),
        {'x': 10, 'y': 20, 'w': 30, 'h': 20},
        mutation_action='save_only_click',
    )

    assert events == ['authorize', 'mouse_click']


def test_native_mouse_events_execute_only_inside_authorizer(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakeApi:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    class FakeUser32:
        def __init__(self):
            self.IsWindowVisible = FakeApi(lambda _hwnd: True)
            self.GetWindowTextLengthW = FakeApi(lambda _hwnd: len('店小秘'))
            self.GetWindowTextW = FakeApi(self._window_text)
            self.GetWindowRect = FakeApi(self._window_rect)
            self.GetClassNameW = FakeApi(self._class_name)
            self.GetWindowThreadProcessId = FakeApi(self._process_id)
            self.GetForegroundWindow = FakeApi(lambda: 101)
            self.SetCursorPos = FakeApi(lambda _x, _y: True)
            self.mouse_event = FakeApi(lambda flag, *_args: events.append(('mouse_event', int(flag))))
            self.EnumWindows = FakeApi(lambda callback, lparam: callback(101, lparam) or True)
            self.EnumChildWindows = FakeApi(lambda _hwnd, callback, lparam: callback(201, lparam) or True)

        @staticmethod
        def _window_text(_hwnd, buffer, _length):
            buffer.value = '店小秘'
            return len(buffer.value)

        @staticmethod
        def _window_rect(hwnd, rect_pointer):
            rect = rect_pointer._obj
            if int(getattr(hwnd, 'value', hwnd) or 0) == 201:
                rect.left, rect.top, rect.right, rect.bottom = 0, 80, 1200, 800
            else:
                rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1200, 800
            return True

        @staticmethod
        def _class_name(hwnd, buffer, _length):
            value = int(getattr(hwnd, 'value', hwnd) or 0)
            buffer.value = 'Chrome_RenderWidgetHostHWND' if value == 201 else 'Chrome_WidgetWin_1'
            return len(buffer.value)

        @staticmethod
        def _process_id(_hwnd, pid_pointer):
            pid_pointer._obj.value = 13
            return 1

    class Windll:
        user32 = FakeUser32()

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    binding = {
        'session_id': 'session-1',
        'browser_id': 1,
        'context_id': 2,
        'page_id': 3,
        'page_url': FakePage.url,
        'target_id': 'target-1',
        'browser_pid': 13,
    }

    def authorize(_context, operation):
        events.append('authorize')
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setattr(ctypes, 'windll', Windll(), raising=False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_resolve_native_browser_identity', lambda _page: binding)
    monkeypatch.setattr(flow, '_select_owned_native_window', lambda windows, **_kwargs: windows[0])
    monkeypatch.setattr(flow, '_force_foreground_bound_window', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow, '_win32_virtual_screen', lambda _user32: {'left': 0, 'top': 0, 'right': 1920, 'bottom': 1080, 'width': 1920, 'height': 1080})
    monkeypatch.setattr(flow, '_current_native_binding_snapshot', lambda *_args, **_kwargs: {**binding, 'window_hwnd': 101, 'foreground_hwnd': 101})

    clicked = flow._click_point_with_native_window(
        FakePage(),
        100,
        100,
        viewport_metrics_override={'innerWidth': 1200, 'innerHeight': 720, 'devicePixelRatio': 1},
        mutation_action='save_only_click',
    )

    assert clicked is True
    assert events == ['authorize', ('mouse_event', 0x0002), ('mouse_event', 0x0004)]


def test_cdp_press_release_executes_only_inside_authorizer(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    events = []

    class FakeCdp:
        def send(self, method, payload):
            assert method == 'Input.dispatchMouseEvent'
            events.append(payload['type'])
            return {}

    class FakeContext:
        def new_cdp_session(self, _page):
            return FakeCdp()

    class FakePage:
        context = FakeContext()

    def authorize(_context, operation):
        events.append('authorize')
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    flow.set_mutation_authorizer(authorize, {'task_id': 3})

    clicked = flow._click_point_with_cdp(
        FakePage(),
        100,
        200,
        mutation_action='save_only_click',
    )

    assert clicked is True
    assert events == ['mouseMoved', 'authorize', 'mousePressed', 'mouseReleased']


def test_click_rect_center_skips_dom_runtime_when_cdp_input_succeeds(monkeypatch, tmp_path):
    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            assert method == 'Input.dispatchMouseEvent'
            return {}

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class BlockingMouse:
        def click(self, *_args, **_kwargs):
            raise AssertionError('Playwright mouse click should not run when CDP input succeeds')

    class FakePage:
        def __init__(self, cdp):
            self.context = FakeContext(cdp)
            self.mouse = BlockingMouse()
            self.calls = []

        def bring_to_front(self):
            self.calls.append('bring_to_front')

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('DOM click must not run when CDP input succeeds')

    cdp = FakeCdp()
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_force_foreground_dxm_window', lambda: False)
    page = FakePage(cdp)

    flow._click_rect_center(page, {'x': 100, 'y': 200, 'w': 40, 'h': 20})

    assert [method for method, _payload in cdp.calls] == [
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
    ]
    assert [payload['type'] for method, payload in cdp.calls if method == 'Input.dispatchMouseEvent'] == [
        'mouseMoved',
        'mousePressed',
        'mouseReleased',
    ]
    assert page.calls == ['bring_to_front']


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
            'rowText': '真实待认领商品 认领',
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
        'rowText': '真实待认领商品 保存并移入待发布 发布',
        'actionText': '认领',
        'actionRect': {'x': 1, 'y': 1, 'w': 96, 'h': 24},
    }

    with pytest.raises(RuntimeError, match='目标商品行包含保存、发布或待发布动作'):
        flow._assert_data_acquisition_claim_click_safe(None, target)


def test_search_data_acquisition_uses_source_url_only_as_match_context(tmp_path):
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

    assert result['query_source'] == 'product_query'
    assert result['query'] == '错误标题不应用于 URL 模式'
    assert result['source_match_only'] is True
    assert source_value == ''
    assert title_value == '错误标题不应用于 URL 模式'


def test_search_data_acquisition_does_not_collect_when_only_source_url_is_present(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html>
      <head>
        <style>
          input, button { display: inline-block; width: 220px; height: 28px; }
        </style>
      </head>
      <body>
        <section>数据采集 <button>开始采集</button></section>
        <input id="source" placeholder="来源链接 / URL" />
        <button>认领</button>
      </body>
    </html>
    '''

    def fail_ready_wait(*args, **kwargs):
        raise AssertionError('data acquisition search must not run page-ready probing after search')

    monkeypatch.setattr(flow, '_wait_for_page_ready', fail_ready_wait)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        result = flow._search_data_acquisition(
            page,
            product_query='https://detail.1688.com/offer/1013604102950.html',
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
        )

        source_value = page.locator('#source').input_value()
        browser.close()

    assert result['query_source'] == 'none'
    assert result['source_match_only'] is True
    assert result['filled'] is False
    assert result['clicked_search'] is False
    assert 'clicked_start_collect' not in result
    assert source_value == ''


def test_data_acquisition_claim_uses_source_url_only_to_match_existing_rows(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    source_url = 'https://www.aliexpress.com/item/1005011837878679.html'

    monkeypatch.setattr('src.execution.dxm_login_flow.time.sleep', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flow, '_wait_for_data_acquisition_ready_for_claim', lambda *_args, **_kwargs: {
        'first_input_rect': {'x': 10, 'y': 10, 'w': 420, 'h': 100},
        'start_collect_rect': {'x': 500, 'y': 10, 'w': 120, 'h': 40},
    })
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_blocking_modals', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_assert_data_acquisition_claim_click_safe', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda *_args, **_kwargs: {'dispatched': True, 'method': 'test_click'},
    )
    monkeypatch.setattr(flow, '_complete_data_acquisition_claim_dialog', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target', lambda *_args, **_kwargs: {
        'ok': True,
        'matchedBy': 'source_url',
        'title': '真实商品',
        'sourceUrls': [source_url],
        'rowText': '真实商品 认领',
        'actionText': '认领',
        'actionRect': {'x': 100, 'y': 100, 'w': 80, 'h': 32},
    })

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <section>数据采集</section>
            <textarea id="source-box" placeholder="请填写产品的网址，多个网址用Enter换行" style="display:block;width:620px;height:120px"></textarea>
            <input id="keyword-box" placeholder="搜索标题或关键词" style="display:block;width:260px;height:32px" />
            <button id="start-collect" onclick="window.__startedCollect = (window.__startedCollect || 0) + 1">开始采集</button>
            <button>搜索</button>
            <table><tr><td>真实商品</td><td><button>认领</button></td></tr></table>
          </body>
        </html>
        ''')
        monkeypatch.setattr(flow, '_open_data_acquisition_page_for_claim', lambda *_args, **_kwargs: page)

        result = flow._perform_data_acquisition_claim(
            claim_mark='AI-OPS',
            product_query='真实商品',
            category_name='立牌类谷子',
            store_name='Dang Kang',
            target_source_urls=[source_url],
        )
        source_value = page.locator('#source-box').input_value()
        keyword_value = page.locator('#keyword-box').input_value()
        started_collect = page.evaluate('window.__startedCollect || 0')
        browser.close()

    assert result['published'] is None
    assert result['claim_click_receipt'] == {'dispatched': True, 'method': 'test_click'}
    assert source_value == ''
    assert keyword_value == '真实商品'
    assert started_collect == 0


def test_source_url_input_helper_is_disabled_for_no_collection_scope(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr('src.execution.dxm_login_flow.time.sleep', lambda *_args, **_kwargs: None)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <section>
              <label>填写产品的网址，多个网址用 Enter 换行</label>
              <textarea id="source-box" style="display:block;width:520px;height:120px"></textarea>
              <button id="start-collect" onclick="window.__startedCollect = (window.__startedCollect || 0) + 1">开始采集</button>
              <button>认领</button>
            </section>
          </body>
        </html>
        ''')

        result = flow._search_data_acquisition_source_url_input(
            page,
            'https://detail.1688.com/offer/1013604102950.html',
            ['https://detail.1688.com/offer/1013604102950.html'],
        )
        source_value = page.locator('#source-box').input_value()
        started_collect = page.evaluate('window.__startedCollect || 0')
        browser.close()

    assert result['filled'] is False
    assert result['clicked_search'] is False
    assert '不新建商品' in result['reason']
    assert source_value == ''
    assert started_collect == 0


def test_source_url_rect_fill_closes_notice_before_native_paste(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda page: calls.append(('dismiss', page)) or True)
    monkeypatch.setattr(flow, '_bring_page_to_front_for_click', lambda page: calls.append(('front', page)) or True)
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda page, x, y: calls.append(('click', x, y)) or True)
    monkeypatch.setattr(flow, '_replace_active_field_with_native_clipboard_text', lambda text: calls.append(('paste', text)) or True)

    result = flow._fill_data_acquisition_source_url_input_rect(
        FakePage(),
        'https://www.aliexpress.com/item/1005011837878679.html',
        {'x': 100, 'y': 200, 'w': 600, 'h': 120},
    )

    assert result['ok'] is False
    assert '不新建商品' in result['reason']
    assert calls == []


def test_start_collect_click_helper_is_disabled_for_no_collection_scope(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def locator(self, *_args, **_kwargs):
            raise AssertionError('start collect rect path must not query locators')

    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda page: calls.append(('dismiss', page)) or True)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_blocking_modals', lambda page: calls.append(('dismiss_blocking', page)) or 1)
    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: calls.append(('click', rect)))

    result = flow._click_data_acquisition_start_collect(
        FakePage(),
        start_collect_rect={'x': 800, 'y': 500, 'w': 120, 'h': 40},
    )

    assert result['ok'] is False
    assert '不新建商品' in result['reason']
    assert calls == []


def test_collect_result_ready_when_claim_actions_visible_even_if_loading(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        def wait_for_timeout(self, _timeout):
            raise AssertionError('visible claim actions should not wait for spinner to disappear')

    monkeypatch.setattr(flow, '_data_acquisition_visible_loading_state', lambda _page: {'loading': True, 'loading_count': 1, 'loading_text': 'LOADING'})
    monkeypatch.setattr(flow, '_count_exact_data_acquisition_claim_actions', lambda _page: 2)

    result = flow._wait_data_acquisition_collect_result(FakePage(), timeout=3000)

    assert result['ok'] is True
    assert result['loading'] is True
    assert result['loading_count'] == 1
    assert result['claim_count'] == 2


def test_visible_data_acquisition_collect_result_waits_until_loading_clears(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    loading_states = [
        {'loading': True, 'loading_count': 1, 'loading_text': 'LOADING'},
        {'loading': False, 'loading_count': 0, 'loading_text': ''},
    ]
    claim_counts = [0, 1]
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_collect_result_state',
        lambda _page: (_ for _ in ()).throw(AssertionError('visible collect result wait must not use runtime probe')),
    )
    monkeypatch.setattr(flow, '_data_acquisition_visible_loading_state', lambda _page: loading_states.pop(0))
    monkeypatch.setattr(flow, '_count_exact_data_acquisition_claim_actions', lambda _page: claim_counts.pop(0))
    sleeps = []
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = flow._wait_data_acquisition_collect_result(FakePage(), timeout=90000)

    assert result['ok'] is True
    assert result['loading'] is False
    assert result['claim_count'] == 1
    assert result['strategy'] == 'visible_locator_collect_result'
    assert sleeps == [3, 1.0]


def test_visible_data_acquisition_collect_result_waits_for_target_when_source_url_provided(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_data_acquisition_visible_loading_state', lambda _page: {'loading': False, 'loading_count': 0, 'loading_text': ''})
    monkeypatch.setattr(flow, '_count_exact_data_acquisition_claim_actions', lambda _page: 20)
    target_states = [
        {'ready': False, 'reason': '目标商品尚未出现在待认领结果中'},
        {'ready': True, 'matched_by': 'source_url'},
    ]
    monkeypatch.setattr(flow, '_data_acquisition_collect_target_state', lambda *_args, **_kwargs: target_states.pop(0))
    sleeps = []
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = flow._wait_data_acquisition_collect_result(
        FakePage(),
        timeout=90000,
        product_query='Sanrio Hello Kitty',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert result['ok'] is True
    assert result['claim_count'] == 20
    assert result['target_ready'] is True
    assert result['target_state']['matched_by'] == 'source_url'
    assert sleeps == [3, 1.0]


def test_source_input_value_snapshot_ignores_checkbox_value_on(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <input type="checkbox" checked />
            <textarea placeholder="产品的网址" style="display:block;width:640px;height:120px"></textarea>
          </body>
        </html>
        ''')
        result = flow._data_acquisition_source_input_value_snapshot(
            page,
            'https://www.aliexpress.com/item/1005011837878679.html',
        )
        browser.close()

    assert result['found'] is True
    assert result['selector'].startswith('textarea')
    assert result['value_excerpt'] == ''
    assert result['contains_expected'] is False


def test_source_url_rect_fill_reports_failure_when_native_and_keyboard_miss_field(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakeMouse:
        def click(self, x, y):
            calls.append(('mouse_click', x, y))

    class FakeKeyboard:
        def press(self, key):
            calls.append(('key_press', key))

        def insert_text(self, text):
            calls.append(('insert_text', text))

    class FakePage:
        mouse = FakeMouse()
        keyboard = FakeKeyboard()

    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: False)
    monkeypatch.setattr(flow, '_bring_page_to_front_for_click', lambda _page: True)
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow, '_replace_active_field_with_native_clipboard_text', lambda _text: True)
    monkeypatch.setattr(
        flow,
        '_data_acquisition_source_input_value_snapshot',
        lambda *_args, **_kwargs: {'found': True, 'value_excerpt': 'on', 'contains_expected': False},
    )

    result = flow._fill_data_acquisition_source_url_input_rect(
        FakePage(),
        'https://www.aliexpress.com/item/1005011837878679.html',
        {'x': 100, 'y': 200, 'w': 400, 'h': 100},
    )

    assert result['ok'] is False
    assert '不新建商品' in result['reason']
    assert calls == []


def test_find_data_acquisition_claim_target_rejects_product_query_without_source_before_url_scan(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    product_target = {
        'ok': True,
        'matchedBy': 'product_query_after_collect',
        'actionRect': {'x': 1, 'y': 2, 'w': 3, 'h': 4},
    }
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target_by_product_query_locator', lambda *_args, **_kwargs: product_target)
    source_result = {'ok': False, 'reason': 'exact source missing'}
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target_by_source_url', lambda *_args, **_kwargs: source_result)

    result = flow._find_data_acquisition_claim_target(
        object(),
        product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert result['ok'] is False
    assert '授权来源' in result['reason']


def test_find_data_acquisition_claim_target_by_product_query_script_with_source_url(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <table>
              <tr><td>其他商品</td><td><button>认领</button></td></tr>
              <tr>
                <td>速卖通 Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand</td>
                <td><a href="https://www.aliexpress.com/item/1005011837878679.html">来源</a></td>
                <td><button style="display:block;width:64px;height:28px">认领</button></td>
              </tr>
            </table>
          </body>
        </html>
        ''')

        result = flow._find_data_acquisition_claim_target(
            page,
            product_query='Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
        )
        browser.close()

    assert result['ok'] is True
    assert result['matchedBy'] == 'source_url'
    assert 'Sanrio Hello Kitty' in result['rowText']
    assert result['actionRect']['w'] > 0


def test_find_data_acquisition_claim_target_product_query_uses_cdp_timeout(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    target = {
        'ok': True,
        'matchedBy': 'product_query_exact_script',
        'rowText': 'Sanrio Hello Kitty Shake 认领',
        'sourceUrls': ['https://www.aliexpress.com/item/1005011837878679.html'],
        'actionRect': {'x': 1200, 'y': 500, 'w': 64, 'h': 28},
    }

    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            assert method == 'Runtime.evaluate'
            assert payload['returnByValue'] is True
            assert payload['timeout'] <= 2500
            return {'result': {'value': target}}

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class FakePage:
        def __init__(self, cdp):
            self.context = FakeContext(cdp)

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('product target lookup must not use bare page.evaluate')

    cdp = FakeCdp()
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target_by_product_query_locator',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('CDP result should not fall back to locator lookup')),
    )

    result = flow._find_data_acquisition_claim_target_by_product_query_script(
        FakePage(cdp),
        'Sanrio Hello Kitty Shake For Magsafe Magnetic Phone Griptok Grip Tok Stand',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert result == target
    assert len(cdp.calls) == 1


def test_source_url_search_fails_fast_when_source_textarea_missing(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    def fail_heavy_scan(*_args, **_kwargs):
        raise AssertionError('missing primary input must not fall back to heavy DOM/CDP scan')

    monkeypatch.setattr(flow, '_fill_data_acquisition_source_url_input', fail_heavy_scan)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('<html><body><button>开始采集</button></body></html>')

        result = flow._search_data_acquisition_source_url_input(
            page,
            'https://www.aliexpress.com/item/1005011837878679.html',
            ['https://www.aliexpress.com/item/1005011837878679.html'],
        )
        browser.close()

    assert result['filled'] is False
    assert result['clicked_search'] is False
    assert '不新建商品' in result['reason']


def test_source_url_dom_fill_uses_cdp_runtime_timeout(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            assert method == 'Runtime.evaluate'
            assert payload['timeout'] <= 2500
            assert '1005011837878679' in payload['expression']
            return {'result': {'value': {'ok': True, 'selector': 'textarea:nth(0)', 'tag': 'textarea'}}}

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class FakePage:
        def __init__(self):
            self.cdp = FakeCdp()
            self.context = FakeContext(self.cdp)

        def evaluate(self, script, payload=None):
            raise AssertionError('source URL DOM fill must not use unbounded page.evaluate')

    page = FakePage()

    result = flow._fill_data_acquisition_source_url_input(
        page,
        'https://www.aliexpress.com/item/1005011837878679.html',
    )

    assert result['ok'] is False
    assert '不新建商品' in result['reason']
    assert page.cdp.calls == []


def test_data_acquisition_source_url_tokens_prioritize_path_product_id(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    tokens = flow._data_acquisition_source_url_tokens([
        'https://www.aliexpress.com/item/1005011837878679.html?pdp_npi=4%40dis%2112000056736085391%21sh',
    ])

    assert tokens[0] == '1005011837878679'
    assert '2112000056736085391' in tokens


def test_data_acquisition_source_url_tokens_ignore_short_query_noise(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    tokens = flow._data_acquisition_source_url_tokens([
        'https://www.aliexpress.com/item/1005011837878679.html?pdp_npi=4%40dis%21USD%21US+%245.92%21US+%240.99%21%21%2139.89%216.65%21%400b5dcc3217821154652661366e8fcc%2112000056736085391%21sh%21US%216005040146%21X'
    ])

    assert tokens[0] == '1005011837878679'
    assert '2112000056736085391' in tokens
    assert '245' not in tokens
    assert '592' not in tokens
    assert '099' not in tokens


def test_data_acquisition_claim_state_keeps_search_and_target_evidence(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    claim_target = {
        'matchedBy': 'source_url',
        'rowText': '真实待认领商品行 来源 1013604102950 认领',
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
        'message': '已进入店小秘已有待认领列表，可以继续认领到采集箱。',
        'target_source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
        'search_result': search_result,
        'claim_target': claim_target,
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
    })

    state = flow.claim_from_data_acquisition(
        'AI-OPS-1',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert state['stage'] == 'data_acquisition_claim'
    assert state['ok'] is True
    assert state['search_result']['query_source'] == 'target_source_url'
    assert state['claim_target']['matchedBy'] == 'source_url'
    assert '真实待认领商品行' in state['claim_target']['rowText']


def test_data_acquisition_claim_does_not_fail_when_visible_screenshot_fails(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 1})
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self):
            self.screenshot_calls = []

        def wait_for_timeout(self, _timeout):
            return None

        def screenshot(self, **kwargs):
            self.screenshot_calls.append(kwargs)
            raise RuntimeError('visible page screenshot timed out')

        def title(self):
            raise AssertionError('visible data acquisition claim must not read page.title() after action completion')

    page = FakePage()
    target = {
        'ok': True,
        'matchedBy': 'source_url',
        'title': '真实待认领商品',
        'categoryName': '立牌类谷子',
        'sourceUrls': ['https://www.aliexpress.com/item/1005011837878679.html'],
        'rowText': '真实待认领商品 认领',
        'actionRect': {'x': 100, 'y': 200, 'w': 80, 'h': 30},
    }

    monkeypatch.setattr(flow, '_open_data_acquisition_page_for_claim', lambda *_args, **_kwargs: page)
    monkeypatch.setattr(flow, '_wait_for_data_acquisition_ready_for_claim', lambda _page: {'first_input_rect': None})
    monkeypatch.setattr(flow, '_search_data_acquisition', lambda *_args, **_kwargs: {
        'query_source': 'target_source_url',
        'filled': True,
        'clicked_search': True,
    })
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target', lambda *_args, **_kwargs: target)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_blocking_modals', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_assert_data_acquisition_claim_click_safe', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda *_args, **_kwargs: {
            'dispatched': True,
            'authorization': {'executed': True},
        },
    )
    monkeypatch.setattr(flow, '_complete_data_acquisition_claim_dialog', lambda *_args, **_kwargs: {'ok': True})

    result = flow._perform_data_acquisition_claim(
        claim_mark='AI-OPS',
        product_query='真实待认领商品',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert result['claimed_product']['title'] == '真实待认领商品'
    assert result['page_title'] == '店小秘--数据采集'
    assert result['page_url'] == 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
    assert result['screenshot_url'] is None
    assert 'screenshot timed out' in result['screenshot_error']
    assert page.screenshot_calls[-1]['full_page'] is False
    assert page.screenshot_calls[-1]['timeout'] == 5000
    assert flow.recent_workflow_events()[-1]['event'] == 'data_acquisition_claim:done'


def test_data_acquisition_claim_refinds_target_after_dismissing_modals(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def wait_for_timeout(self, _timeout):
            return None

        def title(self):
            return '店小秘--数据采集'

    page = FakePage()
    stale_target = {
        'ok': True,
        'matchedBy': 'source_url',
        'title': 'Sanrio Hello Kitty',
        'categoryName': '立牌类谷子',
        'sourceUrls': ['https://www.aliexpress.com/item/1005011837878679.html'],
        'rowText': 'Sanrio Hello Kitty 认领',
        'actionText': '认领',
        'actionRect': {'x': 100, 'y': 200, 'w': 80, 'h': 30},
    }
    fresh_target = {
        **stale_target,
        'actionRect': {'x': 320, 'y': 420, 'w': 80, 'h': 30},
        'matchedBy': 'source_url',
    }
    targets = [stale_target, fresh_target]
    safety_targets = []
    clicked_rects = []

    def fake_find(*_args, **_kwargs):
        return targets.pop(0)

    monkeypatch.setattr(flow, '_open_data_acquisition_page_for_claim', lambda *_args, **_kwargs: page)
    monkeypatch.setattr(flow, '_wait_for_data_acquisition_ready_for_claim', lambda _page: {'first_input_rect': None})
    monkeypatch.setattr(flow, '_search_data_acquisition', lambda *_args, **_kwargs: {
        'query_source': 'target_source_url',
        'filled': True,
        'clicked_search': True,
    })
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target', fake_find)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_blocking_modals', lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(flow, '_assert_data_acquisition_claim_click_safe', lambda _page, target, **_kwargs: safety_targets.append(target) or {'ok': True})
    monkeypatch.setattr(flow, '_click_data_acquisition_claim_rect_center', lambda _page, rect, **_kwargs: clicked_rects.append(rect))
    monkeypatch.setattr(flow, '_complete_data_acquisition_claim_dialog', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})

    result = flow._perform_data_acquisition_claim(
        claim_mark='AI-OPS',
        product_query='Sanrio Hello Kitty',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert result['claim_target']['matchedBy'] == 'source_url'
    assert safety_targets == [fresh_target]
    assert clicked_rects == [fresh_target['actionRect']]
    assert targets == []


def test_data_acquisition_claim_stops_when_source_collection_did_not_start(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        def wait_for_timeout(self, _timeout):
            return None

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: FakePage())
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda *args, **kwargs: None)
    monkeypatch.setattr(flow, '_wait_for_data_acquisition_ready_for_claim', lambda *args, **kwargs: {'first_input_rect': None})
    monkeypatch.setattr(flow, '_search_data_acquisition', lambda *args, **kwargs: {
        'query': 'https://www.aliexpress.com/item/1005011837878679.html',
        'query_source': 'target_source_url',
        'filled': True,
        'clicked_search': False,
        'reason': '未找到可点击的蓝色“开始采集”按钮',
    })

    def fail_if_target_lookup_runs(*args, **kwargs):
        raise AssertionError('采集没有启动时不应该继续查找认领按钮')

    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target', fail_if_target_lookup_runs)

    with pytest.raises(RuntimeError, match='开始采集'):
        flow._perform_data_acquisition_claim(
            claim_mark='AI-OPS-1',
            product_query='真实商品',
            category_name='立牌类谷子',
            store_name='Dang Kang',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
        )


def test_data_acquisition_claim_does_not_wait_six_seconds_before_search(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self):
            self.waits = []

        def wait_for_timeout(self, timeout):
            self.waits.append(timeout)
            if timeout >= 2000:
                raise AssertionError('data acquisition search must not wait several seconds before filling source URL')

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flow,
        '_wait_for_data_acquisition_ready_for_claim',
        lambda *_args, **_kwargs: {'first_input_rect': {'x': 1, 'y': 2, 'w': 300, 'h': 80}},
    )
    monkeypatch.setattr(
        flow,
        '_search_data_acquisition',
        lambda *_args, **_kwargs: {'query_source': 'target_source_url', 'filled': True, 'clicked_search': True},
    )
    monkeypatch.setattr(flow, '_find_data_acquisition_claim_target', lambda *_args, **_kwargs: {'ok': False, 'reason': 'stop after search'})

    with pytest.raises(RuntimeError, match='stop after search'):
        flow._perform_data_acquisition_claim(
            claim_mark='AI-OPS',
            store_name='Dang Kang',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
        )

    assert all(timeout < 2000 for timeout in page.waits)


def test_data_acquisition_claim_reuses_current_page_without_second_goto(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def wait_for_timeout(self, _timeout):
            return None

    page = FakePage()
    flow._page = page
    monkeypatch.setattr(
        flow,
        '_ensure_page_with_cookies',
        lambda: (_ for _ in ()).throw(AssertionError('current data acquisition page must be reused')),
    )
    sterile_gotos = []
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda page, url, **_kwargs: sterile_gotos.append((page, url)))
    monkeypatch.setattr(flow, '_attach_and_reapply_live_hud_page', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flow,
        '_wait_for_data_acquisition_ready_for_claim',
        lambda *_args, **_kwargs: {
            'first_input_rect': {'x': 1, 'y': 2, 'w': 300, 'h': 80},
            'start_collect_rect': {'x': 10, 'y': 20, 'w': 120, 'h': 36},
        },
    )
    monkeypatch.setattr(
        flow,
        '_search_data_acquisition',
        lambda *_args, **_kwargs: {'query_source': 'target_source_url', 'filled': True, 'clicked_search': True},
    )
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target',
        lambda *_args, **_kwargs: {'ok': False, 'reason': 'stop after ready reuse'},
    )

    with pytest.raises(RuntimeError, match='stop after ready reuse'):
        flow._perform_data_acquisition_claim(
            claim_mark='AI-OPS',
            store_name='Dang Kang',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
        )

    assert sterile_gotos == []


def test_data_acquisition_claim_recovers_when_reused_page_is_closed_during_ready_check(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        def __init__(self, url):
            self.url = url
            self.waits = []

        def wait_for_timeout(self, timeout):
            self.waits.append(timeout)

    target_url = WORKFLOW_TARGETS['data_acquisition']['url']
    first_page = FakePage(target_url)
    second_page = FakePage('about:blank')
    pages = [first_page, second_page]
    ensure_calls = []
    goto_calls = []
    wait_calls = []

    def fake_ensure_page():
        ensure_calls.append(True)
        return pages.pop(0)

    def fake_wait_for_data_acquisition_ready(page, *_args, **_kwargs):
        wait_calls.append(page)
        if len(wait_calls) == 1:
            raise RuntimeError('Page.evaluate: Target page, context or browser has been closed')
        return {'first_input_rect': {'x': 1, 'y': 2, 'w': 300, 'h': 80}}

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', fake_ensure_page)
    monkeypatch.setattr(flow, '_attach_and_reapply_live_hud_page', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda page, url, **_kwargs: (goto_calls.append((page, url)), setattr(page, 'url', url)))
    monkeypatch.setattr(flow, '_wait_for_data_acquisition_ready_for_claim', fake_wait_for_data_acquisition_ready)
    monkeypatch.setattr(
        flow,
        '_search_data_acquisition',
        lambda *_args, **_kwargs: {'query_source': 'target_source_url', 'filled': True, 'clicked_search': True},
    )
    monkeypatch.setattr(
        flow,
        '_find_data_acquisition_claim_target',
        lambda *_args, **_kwargs: {'ok': False, 'reason': 'stop after recovered ready'},
    )

    with pytest.raises(RuntimeError, match='stop after recovered ready'):
        flow._perform_data_acquisition_claim(
            claim_mark='AI-OPS',
            store_name='Dang Kang',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
        )

    assert len(ensure_calls) == 2
    assert wait_calls == [first_page, second_page]
    assert goto_calls == [(second_page, target_url)]


def test_data_acquisition_ready_requires_real_controls_not_url_snapshot(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        viewport_size = {'width': 1440, 'height': 1024}

        def wait_for_timeout(self, _timeout):
            raise AssertionError('data acquisition ready poll must not depend on Playwright wait_for_timeout')

    monkeypatch.setattr(flow, '_dismiss_data_acquisition_blocking_modals', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        flow,
        '_data_acquisition_operable_snapshot',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('URL-only snapshot must not be used')),
        raising=False,
    )
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state',
        lambda *_args, **_kwargs: {
            'ready': True,
            'ready_term': 'existing_claim_action_ready',
            'first_input_rect': None,
            'start_collect_rect': None,
            'loading': False,
            'loading_count': 0,
            'claim_count': 1,
            'strategy': 'locator_probe',
        },
    )
    sleeps = []
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = flow._wait_for_page_ready(
        FakePage(),
        ['数据采集'],
        label='数据采集',
        expected_identity='data_acquisition',
        timeout=5000,
        dismiss_strategy='data_acquisition',
    )

    assert result['ready'] is True
    assert result['ready_term'] == 'existing_claim_action_ready'
    assert result['claim_count'] == 1
    assert result['first_input_rect'] is None
    assert result['start_collect_rect'] is None
    assert sleeps == [3.0]


def test_visible_data_acquisition_claim_ready_waits_three_seconds_then_checks_controls(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    sleeps = []
    locator_checks = []

    class FakeContext:
        def new_cdp_session(self, _page):
            raise AssertionError('visible data acquisition claim ready must not use CDP runtime probe')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        context = FakeContext()

        def locator(self, *_args, **_kwargs):
            raise AssertionError('test patches locator inspection at the method seam')

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible data acquisition claim ready must not run page scripts')

        def title(self):
            raise AssertionError('visible data acquisition claim ready must not query page title')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('claim ready must not inspect DOM before the page settles')),
    )
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state_with_runtime',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('claim ready must not use runtime probe')),
    )

    def fake_locator_probe(page, terms):
        locator_checks.append((page, terms))
        return {
            'ready': True,
            'ready_term': 'existing_claim_action_ready',
            'loading': False,
            'loading_count': 0,
            'rows': 1,
            'inputs': 0,
            'claim_count': 1,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '数据采集 已有认领按钮',
            'url': FakePage.url,
            'title': '',
            'loading_text': '',
            'locator_probe_available': True,
        }

    monkeypatch.setattr(flow, '_inspect_data_acquisition_ready_state_with_locators', fake_locator_probe)

    result = flow._wait_for_data_acquisition_ready_for_claim(FakePage())

    assert result['ready'] is True
    assert result['strategy'] == 'visible_locator_condition_wait'
    assert result['ready_term'] == 'existing_claim_action_ready'
    assert result['claim_count'] == 1
    assert result['first_input_rect'] is None
    assert result['start_collect_rect'] is None
    assert sleeps == [3.0]
    assert len(locator_checks) == 1


def test_visible_data_acquisition_claim_ready_polls_until_claim_actions_appear(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    current_time = [0.0]
    sleeps = []
    checks = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

    states = [
        {
            'ready': False,
            'ready_term': None,
            'loading': True,
            'loading_count': 1,
            'rows': 0,
            'inputs': 1,
            'claim_count': 0,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '数据采集 正在加载',
            'url': FakePage.url,
            'title': '',
            'loading_text': 'LOADING',
            'locator_probe_available': True,
        },
        {
            'ready': False,
            'ready_term': None,
            'loading': False,
            'loading_count': 0,
            'rows': 0,
            'inputs': 1,
            'claim_count': 0,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '数据采集 等待列表',
            'url': FakePage.url,
            'title': '',
            'loading_text': '',
            'locator_probe_available': True,
        },
        {
            'ready': True,
            'ready_term': 'existing_claim_action_ready',
            'loading': False,
            'loading_count': 0,
            'rows': 1,
            'inputs': 1,
            'claim_count': 1,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '数据采集 已有认领按钮',
            'url': FakePage.url,
            'title': '',
            'loading_text': '',
            'locator_probe_available': True,
        },
    ]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    def fake_probe(_page, _terms):
        index = min(len(checks), len(states) - 1)
        checks.append(index)
        return dict(states[index])

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'monotonic', lambda: current_time[0])
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', fake_sleep)
    monkeypatch.setattr(flow, '_inspect_data_acquisition_ready_state_with_locators', fake_probe)

    result = flow._wait_for_data_acquisition_ready_for_claim(FakePage())

    assert result['ready'] is True
    assert result['ready_term'] == 'existing_claim_action_ready'
    assert result['strategy'] == 'visible_locator_condition_wait'
    assert checks == [0, 1, 2]
    assert sleeps == [3.0, 1.0, 1.0]


def test_visible_data_acquisition_claim_ready_blocks_when_page_still_loading(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    current_time = [0.0]

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible data acquisition claim ready must not run page scripts')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'monotonic', lambda: current_time[0])
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: current_time.__setitem__(0, current_time[0] + seconds))
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state_with_locators',
        lambda *_args, **_kwargs: {
            'ready': False,
            'ready_term': None,
            'loading': True,
            'loading_count': 1,
            'loading_items': [{
                'selector': '.vxe-loading',
                'text': 'LOADING',
                'rect': {'x': 940, 'y': 550, 'w': 280, 'h': 180},
            }],
            'rows': 0,
            'inputs': 1,
            'claim_count': 0,
            'first_input_rect': {'x': 20, 'y': 40, 'w': 500, 'h': 100},
            'start_collect_rect': {'x': 700, 'y': 220, 'w': 120, 'h': 36},
            'text_excerpt': '数据采集 来源链接输入框 开始采集',
            'url': FakePage.url,
            'title': '',
            'loading_text': 'LOADING',
            'locator_probe_available': True,
        },
    )

    with pytest.raises(RuntimeError, match='加载标记 .vxe-loading=LOADING'):
        flow._wait_for_data_acquisition_ready_for_claim(FakePage())
    timeout_event = flow.recent_workflow_events()[-1]
    assert timeout_event['event'] == 'wait_ready:timeout'
    assert timeout_event['fast_fail'] is True
    assert '加载标记 .vxe-loading=LOADING' in timeout_event['diagnostic']
    assert '当前地址 https://www.dianxiaomi.com/web/productCrawl/dataAcquisition' in timeout_event['diagnostic']


def test_visible_data_acquisition_claim_ready_ignores_ambient_loading_when_claim_action_visible(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    current_time = [0.0]
    sleeps = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible data acquisition claim ready must not run page scripts')

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'monotonic', lambda: current_time[0])
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', fake_sleep)
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state_with_locators',
        lambda *_args, **_kwargs: {
            'ready': False,
            'ready_term': None,
            'loading': True,
            'loading_count': 1,
            'rows': 1,
            'inputs': 1,
            'claim_count': 1,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '已有待认领商品 认领 LOADING',
            'url': FakePage.url,
            'title': '',
            'loading_text': 'LOADING',
            'locator_probe_available': True,
        },
    )

    result = flow._wait_for_data_acquisition_ready_for_claim(FakePage())

    assert result['ready'] is True
    assert result['claim_count'] == 1
    assert result['loading'] is True
    assert result['ready_term'] == 'existing_claim_action_ready'
    assert sleeps == [3.0]


def test_visible_data_acquisition_claim_ready_reports_collect_form_as_wrong_page(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    current_time = [0.0]

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible data acquisition claim ready must not run page scripts')

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(dxm_login_flow_module.time, 'monotonic', lambda: current_time[0])
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: current_time.__setitem__(0, current_time[0] + seconds))
    monkeypatch.setattr(
        flow,
        '_inspect_data_acquisition_ready_state_with_locators',
        lambda *_args, **_kwargs: {
            'ready': False,
            'ready_term': None,
            'loading': False,
            'loading_count': 0,
            'rows': 0,
            'inputs': 1,
            'claim_count': 0,
            'has_collect_form': True,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '请填写产品的网址 开始采集',
            'url': FakePage.url,
            'title': '',
            'loading_text': '',
            'locator_probe_available': True,
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        flow._wait_for_data_acquisition_ready_for_claim(FakePage())

    message = str(excinfo.value)
    assert '已有待认领列表未显示可认领商品' in message
    assert '当前停留在店小秘新建商品输入区' in message
    assert '系统不会填写链接或新建商品' in message
    assert '系统不会填写链接、不会点击开始采集、不会新建商品' in message
    assert '未完全加载' not in message
    assert flow.recent_workflow_events()[-1]['fast_fail'] is True


def test_data_acquisition_ready_requires_existing_claim_action_not_collect_form(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        target_url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        source_placeholder = '\u8bf7\u586b\u5199\u4ea7\u54c1\u7684\u7f51\u5740\uff0c\u591a\u4e2a\u7f51\u5740\u7528Enter\u6362\u884c'
        other_button = '\u5176\u4ed6\u6309\u94ae'
        start_collect = '\u5f00\u59cb\u91c7\u96c6'
        data_acquisition = '\u6570\u636e\u91c7\u96c6'

        def load_data_acquisition_html(html: str):
            page.route(target_url, lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))
            page.goto(target_url, wait_until='domcontentloaded')
            page.unroute(target_url)

        load_data_acquisition_html(f'''
        <html>
          <body>
            <textarea placeholder="{source_placeholder}" style="display:block;width:640px;height:130px"></textarea>
            <button>{other_button}</button>
          </body>
        </html>
        ''')
        ready_without_start_collect = flow._inspect_data_acquisition_ready_state(page, [data_acquisition])

        load_data_acquisition_html(f'''
        <html>
          <body>
            <textarea placeholder="{source_placeholder}" style="display:block;width:640px;height:130px"></textarea>
            <button style="display:block;width:120px;height:40px">{start_collect}</button>
            <div class="vxe-loading" style="display:block;width:240px;height:120px">LOADING</div>
          </body>
        </html>
        ''')
        loading = flow._inspect_data_acquisition_ready_state(page, [data_acquisition])

        load_data_acquisition_html(f'''
        <html>
          <body>
            <textarea placeholder="{source_placeholder}" style="display:block;width:640px;height:130px"></textarea>
            <button style="display:block;width:120px;height:40px">{start_collect}</button>
          </body>
        </html>
        ''')
        collect_form_only = flow._inspect_data_acquisition_ready_state(page, [data_acquisition])

        load_data_acquisition_html(f'''
        <html>
          <body>
            <textarea placeholder="{source_placeholder}" style="display:block;width:640px;height:130px"></textarea>
            <button style="display:block;width:120px;height:40px">{start_collect}</button>
            <table><tr><td>真实待认领商品</td><td><button style="display:block;width:90px;height:32px">认领</button></td></tr></table>
          </body>
        </html>
        ''')
        ready = flow._inspect_data_acquisition_ready_state(page, [data_acquisition])
        browser.close()

    assert ready_without_start_collect['ready'] is False
    assert ready_without_start_collect['start_collect_rect'] is None
    assert ready_without_start_collect['has_collect_form'] is True
    assert loading['ready'] is False
    assert loading['loading'] is True
    assert collect_form_only['ready'] is False
    assert collect_form_only['start_collect_rect'] is None
    assert collect_form_only['has_collect_form'] is True
    assert ready['ready'] is True
    assert ready['ready_term'] == 'existing_claim_action_ready'
    assert ready['claim_count'] == 1
    assert ready['start_collect_rect'] is None


def test_data_acquisition_ready_ignores_non_blocking_lazy_loading_class(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.route(
            'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition',
            lambda route: route.fulfill(
                body='''
                <html>
                  <body>
                    <table>
                      <tr class="vxe-body--row">
                        <td><div class="image-loading" style="display:block;width:70px;height:70px">图片加载</div></td>
                        <td>真实待认领商品</td>
                        <td><button style="display:block;width:90px;height:32px">认领</button></td>
                      </tr>
                    </table>
                  </body>
                </html>
                ''',
                content_type='text/html; charset=utf-8',
            ),
        )
        page.goto('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', wait_until='domcontentloaded')

        state = flow._inspect_data_acquisition_ready_state(page, ['数据采集'])
        browser.close()

    assert state['ready'] is True
    assert state['ready_term'] == 'existing_claim_action_ready'
    assert state['claim_count'] == 1
    assert state['loading'] is False
    assert state['loading_count'] == 0


def test_data_acquisition_ready_probe_uses_bounded_runtime_not_unbounded_evaluate(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def locator(self, *_args, **_kwargs):
            raise AssertionError('visible data acquisition ready probe must not use Playwright locators')

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('data acquisition ready probe must not use unbounded page.evaluate')

    page = FakePage()
    calls = []

    def fake_bounded_runtime(target_page, function_source, *, timeout):
        calls.append({
            'page': target_page,
            'function_source': function_source,
            'timeout': timeout,
        })
        return {
            'ready': True,
            'ready_term': 'existing_claim_action_ready',
            'loading': False,
            'rows': 1,
            'inputs': 1,
            'claim_count': 1,
            'first_input_rect': None,
            'start_collect_rect': None,
            'text_excerpt': '数据采集 认领',
            'url': page.url,
            'title': '店小秘--数据采集',
            'loading_text': '',
        }

    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', fake_bounded_runtime)

    result = flow._inspect_data_acquisition_ready_state(page, ['数据采集'])

    assert result['ready'] is True
    assert len(calls) == 1
    assert calls[0]['page'] is page
    assert calls[0]['timeout'] <= 3000
    assert '数据采集' in calls[0]['function_source']


def test_data_acquisition_ready_probe_prefers_locator_boxes_over_runtime(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_count_exact_data_acquisition_claim_actions', lambda _page: 1)

    class FakeLocator:
        def __init__(self, rect):
            self.rect = rect

        @property
        def first(self):
            return self

        def bounding_box(self, timeout=0):
            return self.rect

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def locator(self, selector):
            if 'placeholder' in selector:
                return FakeLocator({'x': 10, 'y': 20, 'width': 300, 'height': 80})
            if '开始采集' in selector:
                return FakeLocator({'x': 500, 'y': 600, 'width': 120, 'height': 40})
            return FakeLocator(None)

        def title(self):
            return '店小秘--数据采集'

    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('runtime probe should not run')),
    )

    result = flow._inspect_data_acquisition_ready_state(FakePage(), ['数据采集'])

    assert result['ready'] is True
    assert result['ready_term'] == 'existing_claim_action_ready'
    assert result['claim_count'] == 1
    assert result['first_input_rect'] is None
    assert result['start_collect_rect'] is None


def test_visible_workflow_browser_honors_explicit_persistent_profile_opt_out(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    profile_dir = tmp_path / 'dxm-workflow-profile'
    calls = {}

    class FakePage:
        url = 'about:blank'

    class FakeContext:
        def __init__(self):
            self.pages = []
            self.browser = None
            self.init_scripts = []

        def is_closed(self):
            return False

        def add_init_script(self, script):
            self.init_scripts.append(script)

        def new_page(self):
            page = FakePage()
            self.pages.append(page)
            return page

    class FakeBrowser:
        def __init__(self):
            self.contexts = []

        def is_connected(self):
            return True

        def new_context(self, **kwargs):
            calls['context_kwargs'] = kwargs
            context = FakeContext()
            self.contexts.append(context)
            return context

    class FakeChromium:
        def launch(self, **kwargs):
            calls['launch_kwargs'] = kwargs
            return FakeBrowser()

        def launch_persistent_context(self, user_data_dir, **kwargs):
            raise AssertionError('visible workflow should not use persistent profile by default')

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_workflow_browser_profile_dir', lambda: profile_dir)
    monkeypatch.delenv('DXM_DESKTOP', raising=False)
    monkeypatch.setenv('DXM_WORKFLOW_PERSISTENT_PROFILE', '0')
    monkeypatch.delenv('DXM_WORKFLOW_PROFILE_DIR', raising=False)
    monkeypatch.setattr(dxm_login_flow_module, 'sync_playwright', lambda: FakeSyncPlaywright())

    page = flow._ensure_page()

    assert isinstance(page, FakePage)
    assert calls['launch_kwargs']['headless'] is False
    assert calls['context_kwargs']['ignore_https_errors'] is True
    assert '--new-window' in calls['launch_kwargs']['args']
    assert '--disable-session-crashed-bubble' in calls['launch_kwargs']['args']
    assert '--hide-crash-restore-bubble' in calls['launch_kwargs']['args']


def test_data_acquisition_claim_failure_recovery_does_not_read_page_title(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class LoadingPage:
        @property
        def url(self):
            return 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def title(self):
            return '不应该读取标题'

    flow._page = LoadingPage()
    monkeypatch.setattr(
        flow,
        '_perform_data_acquisition_claim',
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError('未找到可填写来源链接的搜索框')),
    )

    state = flow.claim_from_data_acquisition(
        'AI-OPS-1',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert state['stage'] == 'data_acquisition_claim_failed'
    assert state['page_url'] == 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
    assert state['page_title'] == '店小秘官网登录页'


def test_draft_box_claim_verification_carries_data_acquisition_target(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
        'claim_target': {
            'matchedBy': 'source_url',
            'rowText': '真实待认领商品行 来源 1013604102950 认领',
            'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
        },
        'search_result': {'query_source': 'product_query', 'clicked_search': True},
    })
    monkeypatch.setattr(flow, '_verify_draft_box_claim', lambda **kwargs: {
        'page_title': '速卖通采集箱',
        'page_url': 'https://www.dianxiaomi.com/web/smt/smtProductList/draft',
        'screenshot_url': '/artifacts/screenshots/verify.png',
        'target_source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
        'draft_box_match': {
            'matched_by': 'source_url',
            'matched_value': 'https://detail.1688.com/offer/1013604102950.html',
            'row_text': '采集箱商品行 真实待认领商品 AI-OPS-1',
            'source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
            'store_name': 'Dang Kang',
        },
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
            'row_text': '采集箱商品行 真实待认领商品 AI-OPS-1',
        },
    })

    state = flow.verify_draft_box_claim('AI-OPS-1')

    assert state['stage'] == 'draft_box_claim_verified'
    assert state['claim_target']['matchedBy'] == 'source_url'
    assert '真实待认领商品行' in state['claim_target']['rowText']
    assert '采集箱商品行' in state['claimed_product']['row_text']
    assert state['draft_box_match'] == {
        'matched_by': 'source_url',
        'matched_value': 'https://detail.1688.com/offer/1013604102950.html',
        'row_text': '采集箱商品行 真实待认领商品 AI-OPS-1',
        'source_urls': ['https://detail.1688.com/offer/1013604102950.html'],
        'store_name': 'Dang Kang',
    }
    assert set(state['verification_result']) >= {
        'claimed_product',
        'draft_box_match',
        'claim_target',
        'search_result',
    }
    assert state['verification_result']['claim_target'] == state['claim_target']
    assert state['verification_result']['search_result'] == {
        'query_source': 'product_query',
        'clicked_search': True,
    }


def test_verify_draft_box_claim_from_visible_data_acquisition_uses_commit_navigation(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({'task_id': 1, 'job_id': 1, 'state': 'VERIFY_DRAFT_BOX_CLAIM', 'command_id': 'commit-nav'})
    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', lambda *_args, **_kwargs: {
        'path': str((tmp_path / 'commit-nav-proof.png').resolve()), 'sha256': 'A' * 64, 'size': 1,
    })
    monkeypatch.setattr(flow, '_artifact_url', lambda _path: '/artifacts/commit-nav-proof.png')
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    calls = []
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claim_dialog': {'store_selection': {'observed_store_name': 'Dang Kang', 'selected': True, 'selected_store_names': ['Dang Kang'], 'selection_evidence': {'input_checked': True}}},
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://www.aliexpress.com/item/1005011837878679.html',
        },
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def add_init_script(self, _script):
            return None

        def on(self, _event, _callback):
            return None

        def goto(self, url, *, wait_until, timeout):
            calls.append(('goto', url, wait_until, timeout))
            self.url = url

        def wait_for_timeout(self, _timeout):
            return None

        def screenshot(self, **_kwargs):
            return None

        def title(self):
            return '店小秘--采集箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '商品箱 店铺账号 搜索内容 标题/产品ID 编辑',
            }

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: calls.append(('notice',)) or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: calls.append(('native_points',)) or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: calls.append(('escape',)) or True)
    monkeypatch.setattr(flow, '_navigate_visible_dxm_with_native_address_bar', lambda _page, _url: calls.append(('native_nav_failed', _url)) and False)
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: {'ready': True, 'title': '店小秘--采集箱'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: 0)
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: calls.append(('search',)))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: {
        'rowText': '采集箱商品行 真实待认领商品 Dang Kang',
        'sourceUrls': ['https://www.aliexpress.com/item/1005011837878679.html'],
        'storeEvidence': {'store_name': 'Dang Kang', 'cell_text': '「Dang Kang」', 'source': 'structured_store_cell'},
        'matchedBy': 'source_url',
    })

    result = flow._verify_draft_box_claim(
        claim_mark='AI-OPS',
        product_query='真实待认领商品',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html'],
    )

    assert ('notice',) in calls
    assert ('native_points',) in calls
    assert ('escape',) in calls
    goto_call = next(call for call in calls if call[0] == 'goto')
    assert goto_call[2] == 'commit'
    assert goto_call[3] == 15000
    assert result['claimed_product']['row_text'] == '采集箱商品行 真实待认领商品 Dang Kang'
    assert result['draft_box_match'] == {
        'matched_by': 'source_url',
        'matched_value': 'https://www.aliexpress.com/item/1005011837878679.html',
        'raw_matched_by': 'source_url',
        'row_text': '采集箱商品行 真实待认领商品 Dang Kang',
        'source_urls': ['https://www.aliexpress.com/item/1005011837878679.html'],
        'store_name': 'Dang Kang',
        'store_evidence': {'store_name': 'Dang Kang', 'cell_text': '「Dang Kang」', 'source': 'structured_store_cell'},
        'store_observation': {
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang'],
            'selection_evidence': {'input_checked': True},
            'draft_box_cell_evidence': {'store_name': 'Dang Kang', 'cell_text': '「Dang Kang」', 'source': 'structured_store_cell'},
        },
    }


def test_semantic_draft_box_match_rejects_claim_mark_only_row_without_authorized_hint(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with pytest.raises(RuntimeError, match='真实'):
        flow._semantic_draft_box_match(
            {
                'rowText': 'AI-OPS 认领成功 Dang Kang',
                'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
                'matchedBy': 'claim_mark',
            },
            target_source_urls=[],
            store_name='Dang Kang',
        )


def test_semantic_draft_box_match_rejects_url_substring_instead_of_exact_canonical_match(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with pytest.raises(RuntimeError, match='来源'):
        flow._semantic_draft_box_match(
            {
                'rowText': '真实待认领商品 Dang Kang',
                'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html-copy'],
                'matchedBy': 'source_url',
            },
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
            store_name='Dang Kang',
        )


def test_semantic_draft_box_match_rejects_store_name_only_in_unstructured_row_text(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with pytest.raises(RuntimeError, match='结构化店铺单元格'):
        flow._semantic_draft_box_match(
            {
                'rowText': '真实待认领商品 Dang Kang',
                'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
                'matchedBy': 'source_url',
            },
            target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
            store_name='Dang Kang',
            store_selection={
                'observed_store_name': 'Dang Kang',
                'selected': True,
                'selected_store_names': ['Dang Kang'],
                'selection_evidence': {'input_checked': True},
            },
        )


def test_verify_draft_box_claim_continues_when_visible_commit_goto_times_out_after_url_changes(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({'task_id': 2, 'job_id': 2, 'state': 'VERIFY_DRAFT_BOX_CLAIM', 'command_id': 'timeout-nav'})
    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', lambda *_args, **_kwargs: {
        'path': str((tmp_path / 'timeout-nav-proof.png').resolve()), 'sha256': 'B' * 64, 'size': 1,
    })
    monkeypatch.setattr(flow, '_artifact_url', lambda _path: '/artifacts/timeout-nav-proof.png')
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    calls = []
    draft_url = WORKFLOW_TARGETS['draft_box']['url']
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claim_dialog': {'store_selection': {'observed_store_name': 'Dang Kang', 'selected': True, 'selected_store_names': ['Dang Kang'], 'selection_evidence': {'input_checked': True}}},
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def add_init_script(self, _script):
            return None

        def on(self, _event, _callback):
            return None

        def goto(self, url, *, wait_until, timeout):
            calls.append(('goto', url, wait_until, timeout))
            self.url = url
            raise TimeoutError('Page.goto: Timeout 15000ms exceeded')

        def wait_for_timeout(self, timeout):
            calls.append(('wait', timeout))

        def screenshot(self, **_kwargs):
            return None

        def title(self):
            return '店小秘--采集箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '商品箱 店铺账号 搜索内容 标题/产品ID 编辑',
            }

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: calls.append(('notice',)) or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: calls.append(('native_points',)) or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: calls.append(('escape',)) or True)
    monkeypatch.setattr(flow, '_navigate_visible_dxm_with_native_address_bar', lambda _page, _url: calls.append(('native_nav_failed', _url)) and False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: calls.append(('search',)))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: {
        'rowText': '采集箱商品行 真实待认领商品 AI-OPS Dang Kang',
        'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
        'storeEvidence': {'store_name': 'Dang Kang', 'cell_text': 'Dang Kang', 'source': 'structured_store_cell'},
        'matchedBy': 'source_url',
    })

    result = flow._verify_draft_box_claim(
        claim_mark='AI-OPS',
        product_query='真实待认领商品',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert ('goto', draft_url, 'commit', 15000) in calls
    assert ('wait', 3000) in calls
    assert result['claimed_product']['row_text'] == '采集箱商品行 真实待认领商品 AI-OPS Dang Kang'


def test_verify_draft_box_claim_from_visible_data_acquisition_prefers_native_address_navigation(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({'task_id': 3, 'job_id': 3, 'state': 'VERIFY_DRAFT_BOX_CLAIM', 'command_id': 'native-nav'})
    monkeypatch.setattr(flow, '_capture_scoped_evidence_screenshot', lambda *_args, **_kwargs: {
        'path': str((tmp_path / 'native-nav-proof.png').resolve()), 'sha256': 'C' * 64, 'size': 1,
    })
    monkeypatch.setattr(flow, '_artifact_url', lambda _path: '/artifacts/native-nav-proof.png')
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    calls = []
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claim_dialog': {'store_selection': {'observed_store_name': 'Dang Kang', 'selected': True, 'selected_store_names': ['Dang Kang'], 'selection_evidence': {'input_checked': True}}},
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
        },
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def add_init_script(self, _script):
            return None

        def on(self, _event, _callback):
            return None

        def goto(self, *_args, **_kwargs):
            raise AssertionError('native address navigation should avoid page.goto in visible DXM mode')

        def wait_for_timeout(self, _timeout):
            return None

        def screenshot(self, **_kwargs):
            return None

        def title(self):
            return '店小秘--采集箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '商品箱 店铺账号 搜索内容 标题/产品ID 编辑',
            }

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: calls.append(('notice',)) or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: calls.append(('native_points',)) or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: calls.append(('escape',)) or True)
    def navigate_with_native_address_bar(target_page, target_url):
        calls.append(('native_nav', target_url))
        target_page.url = target_url
        return True

    monkeypatch.setattr(flow, '_navigate_visible_dxm_with_native_address_bar', navigate_with_native_address_bar)
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: {'ready': True, 'title': '店小秘--采集箱'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: 0)
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: calls.append(('search',)))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: {
        'rowText': '采集箱商品行 真实待认领商品 Dang Kang',
        'sourceUrls': ['https://detail.1688.com/offer/1013604102950.html'],
        'storeEvidence': {'store_name': 'Dang Kang', 'cell_text': 'Dang Kang', 'source': 'structured_store_cell'},
        'matchedBy': 'source_url',
    })

    result = flow._verify_draft_box_claim(
        claim_mark='AI-OPS',
        product_query='真实待认领商品',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert any(call[0] == 'native_nav' for call in calls)
    assert result['claimed_product']['row_text'] == '采集箱商品行 真实待认领商品 Dang Kang'


def test_browser_readiness_gate_rejects_wrong_route_even_when_draft_box_markers_match(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class WrongRoutePage:
        url = WORKFLOW_TARGETS['data_acquisition']['url']

        def title(self):
            return '店小秘--商品箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '商品箱 店铺账号 搜索内容 标题/产品ID 编辑',
            }

    result = flow._browser_readiness_gate(
        WrongRoutePage(),
        label='商品箱',
        expected_identity='draft_box',
        ready_terms=WORKFLOW_READY_TERMS['draft_box'],
    )

    assert result['ok'] is False
    assert result['reason'] == 'wrong_route'
    assert result['expected_identity'] == 'draft_box'
    assert result['page_url'] == WORKFLOW_TARGETS['data_acquisition']['url']


def test_browser_readiness_gate_rejects_title_and_body_without_business_dom_marker(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class BodyOnlyDraftBoxPage:
        url = WORKFLOW_TARGETS['draft_box']['url']

        def title(self):
            return '店小秘--商品箱 标题/产品ID'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': None,
                'businessMarkerCount': 0,
                'bodyExcerpt': '商品箱 店铺账号 搜索内容 标题/产品ID 编辑',
            }

    result = flow._browser_readiness_gate(
        BodyOnlyDraftBoxPage(),
        label='商品箱',
        expected_identity='draft_box',
        ready_terms=WORKFLOW_READY_TERMS['draft_box'],
    )

    assert result['ok'] is False
    assert result['reason'] == 'target_not_ready'
    assert result['business_marker'] is None


def test_browser_readiness_gate_requires_route_marker_and_no_loading(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class ReadyDraftBoxPage:
        url = WORKFLOW_TARGETS['draft_box']['url']

        def title(self):
            return '店小秘--商品箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'complete',
                'loading': False,
                'loadingCount': 0,
                'blockingModal': None,
                'businessMarker': '标题/产品ID',
                'businessMarkerCount': 1,
                'bodyExcerpt': '商品箱',
            }

    result = flow._browser_readiness_gate(
        ReadyDraftBoxPage(),
        label='商品箱',
        expected_identity='draft_box',
        ready_terms=WORKFLOW_READY_TERMS['draft_box'],
    )

    assert result['ok'] is True
    assert result['expected_identity'] == 'draft_box'
    assert result['business_marker'] == '标题/产品ID'
    assert result['loading'] is False


def test_browser_readiness_gate_blocks_loading_draft_box_page(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class LoadingDraftBoxPage:
        url = WORKFLOW_TARGETS['draft_box']['url']

        def title(self):
            return '店小秘--商品箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'interactive',
                'loading': True,
                'loadingCount': 1,
                'blockingModal': None,
                'bodyExcerpt': '商品箱 加载中',
            }

    result = flow._browser_readiness_gate(
        LoadingDraftBoxPage(),
        label='商品箱',
        expected_identity='draft_box',
        ready_terms=WORKFLOW_READY_TERMS['draft_box'],
    )

    assert result['ok'] is False
    assert result['reason'] == 'page_loading'
    assert result['requires_user_action'] is True
    assert result['loading'] is True


def test_verify_draft_box_claim_stops_when_readiness_gate_reports_loading(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    flow._write_state({'stage': 'data_acquisition_claim', 'claimed_product': {'title': '真实待认领商品'}})
    calls = []

    class LoadingDraftBoxPage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def add_init_script(self, _script):
            return None

        def on(self, _event, _callback):
            return None

        def wait_for_timeout(self, timeout):
            calls.append(('wait', timeout))

        def screenshot(self, **_kwargs):
            return None

        def title(self):
            return '店小秘--商品箱'

        def evaluate(self, _script, _arg=None):
            return {
                'readyState': 'interactive',
                'loading': True,
                'loadingCount': 1,
                'blockingModal': None,
                'bodyExcerpt': '商品箱 加载中',
            }

    page = LoadingDraftBoxPage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: True)
    monkeypatch.setattr(flow, '_navigate_visible_dxm_with_native_address_bar', lambda _page, _url: setattr(page, 'url', _url) or True)
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: calls.append(('search',)))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('should not search rows while page is loading')))

    result = flow._verify_draft_box_claim(
        'AI-OPS',
        product_query='真实待认领商品',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert result['ok'] is False
    assert result['stage'] == 'draft_box_claim_page_not_ready'
    assert result['reason'] == 'page_loading'
    assert ('search',) not in calls


def test_verify_draft_box_claim_stops_when_draft_url_shows_login_page(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.delenv('DXM_LOGIN_HEADLESS', raising=False)
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    calls = []
    draft_url = WORKFLOW_TARGETS['draft_box']['url']
    flow._write_state({
        'stage': 'data_acquisition_claim',
        'claimed_product': {
            'title': '真实待认领商品',
            'category_name': '立牌类谷子',
            'source_url': 'https://detail.1688.com/offer/1013604102950.html',
        },
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def add_init_script(self, _script):
            return None

        def on(self, _event, _callback):
            return None

        def goto(self, url, *, wait_until, timeout):
            calls.append(('goto', url, wait_until, timeout))
            self.url = url
            raise TimeoutError('Page.goto: Timeout 15000ms exceeded')

        def wait_for_timeout(self, timeout):
            calls.append(('wait', timeout))

        def screenshot(self, **_kwargs):
            return None

        def title(self):
            return '店小秘官网登录页'

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: calls.append(('notice',)) or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: calls.append(('native_points',)) or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: calls.append(('escape',)) or True)
    monkeypatch.setattr(flow, '_navigate_visible_dxm_with_native_address_bar', lambda _page, _url: calls.append(('native_nav_failed', _url)) and False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: calls.append(('search',)))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('should not search draft rows on login page')))

    result = flow._verify_draft_box_claim(
        claim_mark='AI-OPS',
        product_query='真实待认领商品',
        category_name='立牌类谷子',
        store_name='Dang Kang',
        target_source_urls=['https://detail.1688.com/offer/1013604102950.html'],
    )

    assert ('goto', draft_url, 'commit', 15000) in calls
    assert ('search',) not in calls
    assert result['ok'] is False
    assert result['stage'] == 'draft_box_claim_login_required'
    assert result['requires_user_action'] is True
    assert '登录' in result['message']


def test_verify_draft_box_claim_public_api_preserves_login_required_state(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_verify_draft_box_claim', lambda **_kwargs: {
        'ok': False,
        'stage': 'draft_box_claim_login_required',
        'label': '需要重新登录店小秘',
        'message': '商品箱页面打开后显示登录页，当前真实浏览器登录态已失效或被店小秘重定向。',
        'next_action': '请在真实浏览器中重新登录店小秘，然后重新执行待认领入箱确认。',
        'requires_user_action': True,
        'page_title': '店小秘官网登录页',
        'page_url': WORKFLOW_TARGETS['draft_box']['url'],
        'browser_visible': True,
    })

    state = flow.verify_draft_box_claim('AI-OPS')

    assert state['stage'] == 'draft_box_claim_login_required'
    assert state['requires_user_action'] is True
    assert state['page_title'] == '店小秘官网登录页'
    assert state['page_url'] == WORKFLOW_TARGETS['draft_box']['url']
    assert state['label'] == '需要重新登录店小秘'


def test_window_restore_verification_rejects_still_offscreen_window(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    virtual_screen = {'left': 0, 'top': 0, 'width': 3840, 'height': 1200}
    before = {'left': -32000, 'top': -32000, 'width': 160, 'height': 28}
    after = {'left': -32000, 'top': -32000, 'width': 160, 'height': 28}

    result = flow._window_restore_succeeded(before, after, virtual_screen=virtual_screen)

    assert result['ok'] is False
    assert result['before_needs_restore'] is True
    assert result['after_needs_restore'] is True
    assert result['after_rect'] == after


def test_native_click_screen_point_requires_virtual_screen_bounds(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    virtual_screen = {'left': 0, 'top': 0, 'width': 3840, 'height': 1200}

    assert flow._screen_point_inside_virtual_screen({'x': 100, 'y': 100}, virtual_screen) is True
    assert flow._screen_point_inside_virtual_screen({'x': -1, 'y': 100}, virtual_screen) is False
    assert flow._screen_point_inside_virtual_screen({'x': 100, 'y': 1200}, virtual_screen) is False


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
    assert '授权来源' in row['reason']


def test_add_note_verifies_only_target_row(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage()
    clicks = []
    row_info = {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]}
    target_identity = _frozen_product_target('130658341178856048', store_name='Dang Kang')
    target_readback = _frozen_identity_readback(target_identity, store_name='Dang Kang')

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: clicks.append(rect))
    monkeypatch.setattr(flow, '_find_draft_box_row_by_frozen_target', lambda *_args, **_kwargs: dict(row_info))

    result = flow._add_note_to_draft_row(
        page,
        row_info,
        'AI认领-12-34',
        store_name='Dang Kang',
        target_identity=target_identity,
        target_identity_sha256=target_readback['target_identity_sha256'],
    )

    assert result['verified'] is False
    assert 'rowTexts.find' not in page.verify_script
    assert clicks[0] == {'x': 5, 'y': 6, 'w': 7, 'h': 8}


def test_add_note_accepts_modify_remark_menu_label(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage(menu_label='修改备注')
    clicks = []
    row_info = {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]}
    target_identity = _frozen_product_target('130658341178856048', store_name='Dang Kang')
    target_readback = _frozen_identity_readback(target_identity, store_name='Dang Kang')

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: clicks.append(rect))
    monkeypatch.setattr(flow, '_find_draft_box_row_by_frozen_target', lambda *_args, **_kwargs: dict(row_info))

    flow._add_note_to_draft_row(
        page,
        row_info,
        'AI认领-12-34',
        store_name='Dang Kang',
        target_identity=target_identity,
        target_identity_sha256=target_readback['target_identity_sha256'],
    )

    assert clicks[1] == {'x': 1, 'y': 2, 'w': 3, 'h': 4}


def test_add_note_reloads_the_exact_frozen_target_when_current_filter_is_empty(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyNoteVerifyScriptPage()
    row_info = {'rowIndex': 2, 'actions': [{'txt': '更多', 'tag': 'A', 'cls': 'ant-dropdown-trigger', 'rect': {'x': 5, 'y': 6, 'w': 7, 'h': 8}}]}
    target_identity = _frozen_product_target('130658341178856048', store_name='Dang Kang')
    target_readback = _frozen_identity_readback(target_identity, store_name='Dang Kang')
    exact_reads = []

    def exact_row_readback(*_args, **kwargs):
        exact_reads.append(kwargs['target_identity_sha256'])
        if len(exact_reads) == 1:
            return dict(row_info)
        return {
            **row_info,
            'rowText': '目标商品 AI认领-47-514',
            'target_unique': True,
            'product_identity_match': True,
            'store_identity_match': True,
            'source_identity_match': True,
        }

    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: None)
    monkeypatch.setattr(
        flow,
        '_find_draft_box_row_by_frozen_target',
        exact_row_readback,
    )
    page.note_visible_after_search = True

    result = flow._add_note_to_draft_row(
        page,
        row_info,
        'AI认领-47-514',
        store_name='Dang Kang',
        target_identity=target_identity,
        target_identity_sha256=target_readback['target_identity_sha256'],
    )

    assert result['verified'] is True
    assert result['verifiedBy'] == 'frozen_target_structured_row_readback'
    assert result['ownership_binding_match'] is True
    assert exact_reads and set(exact_reads) == {target_readback['target_identity_sha256']}


def test_search_draft_box_visible_mode_uses_editable_search_input(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: False)

    html = '''
    <html>
      <body>
        <input class="ant-input" style="display:none" value="">
        <div>
          <label>搜索内容</label>
          <input class="ant-input css-1oz1bg8 h32" name="tableSearchInput" value="">
          <button>搜索</button>
        </div>
        <table>
          <tr class="vxe-body--row">
            <td>目标商品</td>
            <td>编辑</td>
          </tr>
        </table>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            'https://www.dianxiaomi.com/**',
            lambda route: route.fulfill(status=200, body=html, content_type='text/html'),
        )
        page.goto('https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0')

        flow._search_draft_box(page, product_query='目标商品', store_name='Dang Kang')

        value = page.locator('input[name="tableSearchInput"]').input_value()
        browser.close()

    assert value == '目标商品'


def test_submit_visible_draft_box_search_clicks_real_search_button_not_wrapper(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    html = '''
    <html>
      <body>
        <div class="search-panel">
          <label>搜索内容</label>
          <input class="ant-input css-1oz1bg8 h32" name="tableSearchInput" value="">
          <button id="realSearch" onclick="window.__clickedSearch = (window.__clickedSearch || 0) + 1">搜索</button>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = flow._submit_visible_draft_box_search(page, '目标商品')
        value = page.locator('input[name="tableSearchInput"]').input_value()
        clicked = page.evaluate('() => window.__clickedSearch || 0')
        browser.close()

    assert result['clicked'] == '搜索'
    assert value == '目标商品'
    assert clicked == 1


def test_search_draft_box_visible_mode_does_not_submit_empty_query_for_store_only(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    submit_calls = []
    monkeypatch.setattr(flow, '_submit_visible_draft_box_search', lambda *_args, **_kwargs: submit_calls.append('submit') or {'ok': True})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda *_args, **_kwargs: 0)

    class Page:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

        def wait_for_timeout(self, _timeout):
            raise AssertionError('store-only visible search should not wait for empty submit')

    flow._search_draft_box(Page(), product_query=None, store_name='Dang Kang')

    assert submit_calls == []


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


def test_perform_draft_box_edit_updates_active_page_to_editor(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    draft_page = DummyDraftPage({'ok': True})
    editor_page = DummyDraftPage({'ok': True})
    editor_page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    flow._page = draft_page

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: draft_page)
    monkeypatch.setattr(flow, '_goto_with_live_hud', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flow, '_wait_for_page_ready', lambda *_args, **_kwargs: {'ready': True})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: {
        'rowText': '目标商品 「Dang Kang」 编辑',
        'sourceUrls': ['https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663'],
    })
    monkeypatch.setattr(flow, '_open_editor_from_draft_box', lambda *_args, **_kwargs: editor_page)
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})
    monkeypatch.setattr(flow, '_extract_editor_page_meta', lambda _page: {'sections': [], 'top_actions': [], 'fields': []})
    frozen_kwargs = _frozen_action_kwargs(
        store_name='Dang Kang',
        source_url='https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663',
    )
    frozen_readback = _frozen_identity_readback(frozen_kwargs['target_identity'], store_name='Dang Kang')
    monkeypatch.setattr(flow, '_verify_opened_editor_target', lambda *_args, **_kwargs: dict(frozen_readback))

    result = flow._perform_draft_box_action(
        'edit',
        product_query='目标商品',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['page_url'] == editor_page.url
    assert flow._page is editor_page


def test_perform_draft_box_edit_reuses_matching_open_editor_before_search(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        def __init__(self, url, title='店小秘--速卖通产品', match=None):
            self.url = url
            self._title = title
            self.match = match
            self.gotos = []

        def title(self):
            return self._title

        def goto(self, url, **_kwargs):
            self.gotos.append(url)
            self.url = url

        def evaluate(self, *_args, **_kwargs):
            if self.match is not None:
                return self.match
            return {'ok': False}

    draft_page = FakePage('https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0')
    editor_page = FakePage(
        'https://www.dianxiaomi.com/web/smt/edit?id=130658341178856048',
        title='店小秘--编辑速卖通产品',
        match={
            'ok': True,
            'matchedBy': 'product_id',
            'current_editor_product_id': '130658341178856048',
            'observed_product_ids': ['130658341178856048'],
            'observed_source_urls': ['https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663'],
            'observed_store_names': ['Dang Kang'],
            'store_identity_match': True,
            'textExcerpt': '宝可梦精灵球玩具模型周边礼物3D打印球体摆件',
        },
    )

    class Context:
        pages = [draft_page, editor_page]

    flow._context = Context()
    flow._page = draft_page

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: draft_page)
    monkeypatch.setattr(flow, '_goto_with_live_hud', lambda *_args, **_kwargs: pytest.fail('matching editor should be reused before draft search'))
    monkeypatch.setattr(flow, '_find_draft_box_row', lambda *_args, **_kwargs: pytest.fail('matching editor should avoid draft row lookup'))
    monkeypatch.setattr(flow, '_search_draft_box', lambda *_args, **_kwargs: pytest.fail('matching editor should avoid draft search'))
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})
    monkeypatch.setattr(flow, '_extract_editor_page_meta', lambda _page: {'sections': [], 'top_actions': [], 'fields': []})
    monkeypatch.setattr(flow, '_reapply_live_hud_if_available', lambda _page: None)
    frozen_kwargs = _frozen_action_kwargs(
        store_name='Dang Kang',
        source_url='https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663',
    )
    frozen_readback = _frozen_identity_readback(frozen_kwargs['target_identity'], store_name='Dang Kang')
    monkeypatch.setattr(flow, '_verify_opened_editor_target', lambda *_args, **_kwargs: dict(frozen_readback))

    result = flow._perform_draft_box_action(
        'edit',
        product_query='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['page_url'] == editor_page.url
    assert result['editor_reused'] is True
    assert result['matched_by'] == 'product_id'
    assert flow._page is editor_page
    assert draft_page.gotos == []


def test_editor_page_target_match_requires_exact_canonical_source_when_url_authorized(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''
            <div>Visible Matched Product Title</div>
            <a href="https://www.aliexpress.com/item/1005011837878679.html?spm=actual">source</a>
        ''')
        result = flow._editor_page_matches_target(
            page,
            product_query='Visible Matched Product Title',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html?spm=authorized'],
        )
        browser.close()

    assert result['ok'] is False
    assert result['matchedBy'] == 'source_url_missing'
    assert result['titleMatched'] is True


def test_editor_page_target_match_accepts_exact_canonical_source_url(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''
            <a href="https://www.aliexpress.com/item/1005011837878679.html?spm=authorized#ignored">source</a>
        ''')
        result = flow._editor_page_matches_target(
            page,
            product_query='Different Product Title',
            target_source_urls=['https://www.aliexpress.com/item/1005011837878679.html?spm=authorized'],
        )
        browser.close()

    assert result['ok'] is True
    assert result['matchedBy'] == 'source_url'
    assert result['sourceUrls'] == ['https://www.aliexpress.com/item/1005011837878679.html?spm=authorized']


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

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
        'ok': True,
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
    assert state['ok'] is True
    assert state['current_action'] == 'enable_semi_managed'
    assert state['product_query'] == '崩坏3钥匙扣'
    assert state['store_name'] == 'Dang Kang'
    assert state['semi_managed_enabled'] is True
    assert state['editor_action_result']['semi_managed_enabled'] is True


def test_dxm_login_flow_perform_editor_action_keeps_browser_session_on_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    close_calls = []
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
        'ok': True,
        'stage': action,
        'page_title': '店小秘--编辑速卖通产品',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'screenshot_url': '/artifacts/screenshots/editor.png',
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: close_calls.append('closed'))

    state = flow.perform_editor_action('fill_editor_required_defaults')

    assert state['stage'] == 'fill_editor_required_defaults'
    assert state['ok'] is True
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
    assert state['ok'] is False
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

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)

    def fake_verify(page, product_query=None, store_name=None, expected_source_urls=None):
        seen['expected_source_urls'] = expected_source_urls
        return {'stage': 'edit_ownership_verified', 'page_url': page.url, 'published': False}

    monkeypatch.setattr(flow, '_verify_edit_ownership_on_page', fake_verify)
    frozen_kwargs = _bind_frozen_editor_action(
        flow,
        monkeypatch,
        store_name='Dang Kang',
        source_url='https://mobile.yangkeduo.com/goods2.html?goods_id=917858747237',
    )

    result = flow._perform_editor_action(
        'verify_edit_ownership',
        product_query='绝区零妄想天使南宫羽猫咪话筒麦克风cos道具',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert seen['expected_source_urls'] == ['https://mobile.yangkeduo.com/goods2.html?goods_id=917858747237']


def test_verify_edit_ownership_does_not_reopen_draft_when_editor_url_is_known(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    editor_url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    flow._write_state({
        'stage': 'editor_page',
        'page_url': editor_url,
        'target_source_urls': ['https://detail.1688.com/offer/1057791519266.html'],
    })

    class EditorPage(DummyOpenSemiPage):
        def __init__(self):
            super().__init__()
            self.url = editor_url

    page = EditorPage()
    seen = {}

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: 0)
    monkeypatch.setattr(flow, '_open_editor_page_for_product', lambda *_args, **_kwargs: pytest.fail('known editor url should not reopen draft box'))

    def fake_verify(target_page, product_query=None, store_name=None, expected_source_urls=None):
        seen['page_url'] = target_page.url
        seen['expected_source_urls'] = expected_source_urls
        return {'stage': 'edit_ownership_verified', 'page_url': target_page.url, 'published': False}

    monkeypatch.setattr(flow, '_verify_edit_ownership_on_page', fake_verify)
    frozen_kwargs = _bind_frozen_editor_action(
        flow,
        monkeypatch,
        store_name='Dang Kang',
        source_url='https://detail.1688.com/offer/1057791519266.html',
    )

    result = flow._perform_editor_action(
        'verify_edit_ownership',
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert seen['page_url'] == editor_url
    assert seen['expected_source_urls'] == ['https://detail.1688.com/offer/1057791519266.html']


def test_visible_editor_body_wait_requires_structured_marker_after_settle(monkeypatch, tmp_path):
    wait_calls = []

    class VisibleEditorPage(DummyOpenSemiPage):
        def wait_for_function(self, script, *, arg, timeout):
            wait_calls.append((script, arg, timeout))

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    sleeps = []

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_wait_for_body_text_with_runtime',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible editor wait must not use runtime probe')),
        raising=False,
    )
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda seconds: sleeps.append(seconds))

    result = flow._wait_for_body_text(
        VisibleEditorPage(),
        ['基本信息', '产品信息'],
        timeout=9000,
        expected_identity='editor',
    )

    assert result is True
    assert sleeps == [3.0]
    assert wait_calls[0][1:] == (['基本信息', '产品信息'], 9000)
    assert 'document.body' not in wait_calls[0][0]
    assert 'loadingOverlay' in wait_calls[0][0]


def test_visible_editor_verify_ownership_uses_editor_url_without_page_evaluate(monkeypatch, tmp_path):
    title_calls = []

    class VisibleEditorPage(DummyOpenSemiPage):
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible editor ownership check must not call page.evaluate')

        def title(self):
            title_calls.append(1)
            raise AssertionError('visible editor ownership check must not call page.title')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374',
        'target_source_urls': ['https://detail.1688.com/offer/1057791519266.html'],
    })

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})

    result = flow._verify_edit_ownership_on_page(
        VisibleEditorPage(),
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        expected_source_urls=['https://detail.1688.com/offer/1057791519266.html'],
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert result['page_title'] == '店小秘编辑页'
    assert result['fill_result']['verified_by'] == 'visible_editor_url_state'
    assert result['fill_result']['source_matched'] is True
    assert title_calls == []


def test_visible_editor_action_blocks_when_real_editor_is_still_loading(monkeypatch, tmp_path):
    editor_url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341351030322'

    class VisibleEditorPage(DummyOpenSemiPage):
        url = editor_url

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('loading editor must stop before ownership/content actions')

        def title(self):
            raise AssertionError('loading editor must stop before title reads')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': editor_url,
        'target_source_urls': ['https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663'],
    })

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: VisibleEditorPage())
    monkeypatch.setattr(flow, '_wait_for_visible_editor_loaded', lambda *args, **kwargs: False, raising=False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_capture_optional_workflow_screenshot', lambda *_args, **_kwargs: {'screenshot_url': None})
    frozen_kwargs = _bind_frozen_editor_action(
        flow,
        monkeypatch,
        store_name='Dang Kang',
        source_url='https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663',
    )

    result = flow._perform_editor_action(
        'verify_edit_ownership',
        product_query='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'verify_edit_ownership_failed'
    assert result['fill_result']['reason'] == 'editor_page_not_ready'
    assert result['message'] == '编辑页仍在加载或关键商品信息为空，未继续执行。'


def test_visible_editor_action_skips_full_modal_scan(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    editor_url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    flow._write_state({
        'stage': 'editor_page',
        'page_url': editor_url,
        'target_source_urls': ['https://detail.1688.com/offer/1057791519266.html'],
    })
    page = DummyOpenSemiPage()
    page.url = editor_url
    dismiss_contexts = []

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_visible_editor_loaded', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible editor must not run full modal scan')),
    )
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals_if_visible',
        lambda _page, *, context: dismiss_contexts.append(context) or 0,
    )
    monkeypatch.setattr(
        flow,
        '_verify_edit_ownership_on_page',
        lambda *_args, **_kwargs: {'stage': 'edit_ownership_verified', 'published': False},
    )
    frozen_kwargs = _bind_frozen_editor_action(
        flow,
        monkeypatch,
        store_name='Dang Kang',
        source_url='https://detail.1688.com/offer/1057791519266.html',
    )

    result = flow._perform_editor_action(
        'verify_edit_ownership',
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert dismiss_contexts == ['editor_action:after_ready']


def test_visible_editor_required_defaults_state_uses_bounded_probe_not_page_evaluate(monkeypatch, tmp_path):
    class VisibleEditorPage(DummyOpenSemiPage):
        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible editor defaults state must not use unbounded page.evaluate')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    calls = []

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_evaluate_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: calls.append(True) or {
            'missing': [],
            'values': {},
            'customs_configured': False,
            'category_selected': True,
            'category_text': 'ACG Stand',
        },
    )

    state = flow._editor_required_defaults_state(
        VisibleEditorPage(),
        expected_category_match='ACG Stand',
    )

    assert calls
    assert state['category_selected'] is True
    assert state.get('visible_probe_skipped') is not True


def test_verify_edit_ownership_keeps_business_failure_when_screenshot_times_out(tmp_path):
    class LoginPageAtEditorUrl(DummyOpenSemiPage):
        def __init__(self):
            super().__init__()
            self.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

        def title(self):
            return '店小秘官网登录页'

        def evaluate(self, script, arg=None):
            return {
                'ok': False,
                'reason': '编辑页未显示商品信息，当前页面可能仍是登录页。',
                'query_matched': False,
                'source_matched': False,
                'store_matched': False,
                'has_editor_signals': False,
                'body_excerpt': '店小秘官网登录页',
            }

        def screenshot(self, **_kwargs):
            raise RuntimeError('Page.screenshot: Timeout 30000ms exceeded')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow._is_headless = lambda: True
    result = flow._verify_edit_ownership_on_page(
        LoginPageAtEditorUrl(),
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        expected_source_urls=['https://detail.1688.com/offer/1057791519266.html'],
    )

    assert result['stage'] == 'verify_edit_ownership_failed'
    assert result['message'] == '编辑页未显示商品信息，当前页面可能仍是登录页。'
    assert result['screenshot_url'] is None
    assert 'Page.screenshot' in result['screenshot_error']
    assert result['page_title'] == '店小秘官网登录页'


def test_verify_edit_ownership_uses_evaluated_title_when_title_call_is_unavailable(tmp_path):
    class VisibleEditorPage(DummyOpenSemiPage):
        def evaluate(self, script, arg=None):
            return {
                'ok': True,
                'reason': None,
                'query_matched': True,
                'source_matched': False,
                'store_matched': True,
                'has_editor_signals': True,
                'page_title': '店小秘--编辑速卖通产品',
                'page_url': self.url,
                'body_excerpt': '基本信息 产品信息 正版玩具总动员攀爬吊饰钥匙扣挂件 Dang Kang',
            }

        def title(self):
            raise AssertionError('visible editor ownership should not call page.title after page scripts returned metadata')

        def screenshot(self, **_kwargs):
            raise RuntimeError('Page.screenshot: Timeout 15000ms exceeded')

    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow._is_headless = lambda: True

    result = flow._verify_edit_ownership_on_page(
        VisibleEditorPage(),
        product_query='正版玩具总动员攀爬吊饰钥匙扣挂件',
        store_name='Dang Kang',
        expected_source_urls=['https://detail.1688.com/offer/1057791519266.html'],
    )

    assert result['stage'] == 'edit_ownership_verified'
    assert result['page_title'] == '店小秘--编辑速卖通产品'
    assert result['page_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    assert 'Page.screenshot' in result['screenshot_error']


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

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {
        'stage': 'editor_variants_filled',
        'page_url': page.url,
        'published': False,
    })

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'fill_editor_variants',
        defaults=_legacy_explicit_editor_defaults(),
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'editor_variants_filled'
    assert page.gotos == []


def test_perform_editor_action_uses_open_editor_page_from_context_before_goto(monkeypatch, tmp_path):
    class StaleDraftPage(DummyOpenSemiPage):
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

    class CurrentEditorPage(DummyOpenSemiPage):
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._write_state({
        'stage': 'editor_page',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
    })
    draft_page = StaleDraftPage()
    editor_page = CurrentEditorPage()

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: draft_page)
    monkeypatch.setattr(flow, '_context_pages', lambda: [draft_page, editor_page])
    monkeypatch.setattr(flow, '_goto_with_live_hud', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('should reuse open editor page')))
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {
        'stage': 'editor_variants_filled',
        'page_url': page.url,
        'used_editor_page': page is editor_page,
        'published': False,
    })

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'fill_editor_variants',
        defaults=_legacy_explicit_editor_defaults(),
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'editor_variants_filled'
    assert result['used_editor_page'] is True
    assert flow._page is editor_page


def test_dxm_login_flow_perform_editor_action_allows_verify_not_published(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_perform_editor_action', lambda action, defaults=None, product_query=None, store_name=None, target_source_urls=None, target_identity=None: {
        'ok': True,
        'stage': 'not_published_verified',
        'page_title': '店小秘--编辑速卖通半托管',
        'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt',
        'screenshot_url': '/artifacts/screenshots/not-published.png',
        'published': False,
    })
    monkeypatch.setattr(flow, '_close_browser_session', lambda: None)

    state = flow.perform_editor_action('verify_not_published', product_query='崩坏3钥匙扣', store_name='Dang Kang')

    assert state['stage'] == 'not_published_verified'
    assert state['ok'] is True
    assert state['published'] is False


def test_open_semi_managed_page_records_source_editor_url(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'compliance_defaults_filled'})
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

    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_media_assets_on_page', lambda page, defaults=None, **_kwargs: next(media_results))
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(
        DummyOpenSemiPage(),
        _legacy_explicit_editor_defaults(
            eu_outer_package_filename='微信图片_202504092228421.jpg',
        ),
    )

    assert state['stage'] == 'semi_managed_page'


def test_open_semi_managed_page_refills_variants_and_compliance_on_same_page(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: calls.append('base') or {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: calls.append('variants') or {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: calls.append('compliance') or {'stage': 'compliance_defaults_filled'})
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

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(
        flow,
        '_fill_editor_required_defaults_on_page',
        lambda page, defaults=None, **_kwargs: calls.append('base') or {
            'stage': 'editor_required_defaults_filled',
            'fill_result': {'customs_supervision': {'ok': False, 'reason': '海关监管弹窗未打开'}},
        },
    )
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: calls.append('variants') or {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_media_assets_on_page', lambda page, defaults=None, **_kwargs: calls.append('media') or {'stage': 'media_assets_filled', 'fill_result': {'eu_outer_package_image': {'ok': True}}})
    monkeypatch.setattr(flow, '_media_result_has_verified_eu_outer_package', lambda result: True)
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: calls.append('compliance') or {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: calls.append('main_images') or {'ok': True})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: calls.append(('customs_after_repairs', names)) or {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: calls.append('enable') or {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': False, 'is_semi_page': True})

    state = flow._open_semi_managed_page_from_editor(
        DummyOpenSemiPage(),
        _legacy_explicit_editor_defaults(
            eu_outer_package_filename='微信图片_202504092228421.jpg',
            customs_product_name_priorities=['keychain'],
        ),
    )

    assert state['stage'] == 'semi_managed_page'
    assert calls[:5] == ['base', 'variants', 'media', 'compliance', 'main_images']
    assert calls[5] == ('customs_after_repairs', ['keychain'])
    assert calls[6] == 'enable'


def test_open_semi_managed_page_stops_when_same_page_variants_fail(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'fill_editor_variants_failed', 'message': '缺少变体字段'})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'open_semi_managed_page_failed'
    assert state['label'] == '普通编辑页变体信息未通过'
    assert state['preflight_results']['variants']['stage'] == 'fill_editor_variants_failed'


def test_open_semi_managed_page_stops_when_main_images_still_invalid(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'compliance_defaults_filled'})
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
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_open_semi_managed_page_from_editor', lambda page, defaults=None, **_kwargs: reopened.append(defaults) or {'stage': 'semi_managed_page'})
    monkeypatch.setattr(flow, '_fill_semi_managed_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'semi_managed_defaults_filled'})

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)

    result = flow._perform_editor_action(
        'fill_semi_managed_defaults',
        defaults=_legacy_explicit_editor_defaults(),
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'semi_managed_defaults_filled'
    assert result['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    assert page.gotos == ['https://www.dianxiaomi.com/web/smt/edit?id=123']
    assert reopened == [_legacy_explicit_editor_defaults()]


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
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(flow, '_open_semi_managed_page_from_editor', lambda page, defaults=None, **_kwargs: reopened.append(defaults) or {'stage': 'semi_managed_page'})
    monkeypatch.setattr(flow, '_fill_semi_managed_defaults_on_page', lambda page, defaults=None, **_kwargs: prefilled.append(defaults) or {'stage': 'semi_managed_defaults_filled', 'ok': True})
    monkeypatch.setattr(flow, '_save_only_on_page', lambda page, **_kwargs: {'stage': 'save_only_done', 'save_result': {'ok': True, 'published': False}})

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)

    result = flow._perform_editor_action(
        'save_only',
        defaults=_legacy_explicit_editor_defaults(),
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'save_only_done'
    assert result['source_editor_url'] == 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    assert page.gotos == ['https://www.dianxiaomi.com/web/smt/edit?id=123']
    assert reopened == [_legacy_explicit_editor_defaults()]
    assert prefilled == [_legacy_explicit_editor_defaults()]


def test_save_only_from_editor_page_does_not_require_semi_managed_prefill(monkeypatch, tmp_path):
    class EditorPage(DummySemiPage):
        url = 'about:blank'

        def __init__(self):
            super().__init__({'ok': True})
            self.gotos = []

        def goto(self, url, **kwargs):
            self.gotos.append((url, kwargs))
            self.url = url

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    editor_url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    flow._write_state({
        'stage': 'editor_page',
        'page_url': editor_url,
    })
    page = EditorPage()
    waits = []
    saves = []
    prefill_calls = []

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('editor save should open the page before attaching HUD')),
    )
    monkeypatch.setattr(
        flow,
        '_wait_for_body_text',
        lambda page, terms, timeout=15000, expected_identity=None: waits.append((terms, timeout, expected_identity)) or True,
    )
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(
        flow,
        '_fill_semi_managed_defaults_on_page',
        lambda page, defaults=None, **_kwargs: (_ for _ in ()).throw(AssertionError('semi managed prefill should not run for editor save')),
    )
    monkeypatch.setattr(
        flow,
        '_fill_editor_required_defaults_on_page',
        lambda page, defaults=None, **_kwargs: prefill_calls.append(('required', defaults)) or {'stage': 'editor_required_defaults_filled'},
    )
    monkeypatch.setattr(
        flow,
        '_fill_editor_variants_on_page',
        lambda page, defaults=None, **_kwargs: prefill_calls.append(('variants', defaults)) or {'stage': 'editor_variants_filled'},
    )
    monkeypatch.setattr(
        flow,
        '_fill_media_assets_on_page',
        lambda page, defaults=None, **_kwargs: prefill_calls.append(('media', defaults)) or {'stage': 'media_assets_filled'},
    )
    monkeypatch.setattr(
        flow,
        '_fill_compliance_defaults_on_page',
        lambda page, defaults=None, **_kwargs: prefill_calls.append(('compliance', defaults)) or {'stage': 'compliance_defaults_filled'},
    )
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: prefill_calls.append(('main_images', None)) or {'ok': True})
    monkeypatch.setattr(
        flow,
        '_capture_save_field_integrity_snapshot',
        lambda _page: {
            'ok': True,
            'kind': 'structured_nonempty_form_state',
            'field_count': 10,
            'nonempty_field_count': 10,
            'sha256': 'B' * 64,
        },
    )
    monkeypatch.setattr(
        flow,
        '_save_only_on_page',
        lambda page, **_kwargs: saves.append(page.url) or {'stage': 'save_only_done', 'save_result': {'ok': True, 'published': False}},
    )

    explicit_defaults = _legacy_explicit_editor_defaults()
    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'save_only',
        defaults=explicit_defaults,
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'save_only_done'
    assert result['source_editor_url'] == editor_url
    assert page.gotos == [(editor_url, {'wait_until': 'domcontentloaded', 'timeout': 45000})]
    assert waits == [(['基本信息', '产品信息', '保存'], 15000, 'editor')]
    assert prefill_calls == [
        ('required', explicit_defaults),
        ('variants', explicit_defaults),
        ('media', explicit_defaults),
        ('compliance', explicit_defaults),
        ('main_images', None),
    ]
    assert saves == [editor_url]


def test_save_only_from_editor_page_stops_when_required_template_fill_fails(monkeypatch, tmp_path):
    page = DummySemiPage({'ok': True})
    page.url = 'about:blank'
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    editor_url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    flow._write_state({
        'stage': 'editor_page',
        'page_url': editor_url,
    })
    page.gotos = []

    def goto(url, **kwargs):
        page.gotos.append((url, kwargs))
        page.url = url

    page.goto = goto
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_wait_for_visible_editor_loaded', lambda *args, **kwargs: True)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda page, terms, timeout=15000, expected_identity=None: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(
        flow,
        '_fill_editor_required_defaults_on_page',
        lambda page, defaults=None, **_kwargs: {
            'stage': 'fill_editor_required_defaults_failed',
            'label': '普通编辑页仍有必填项缺失',
            'message': '普通编辑页缺少字段：english_title, freight_template',
            'fill_result': {'missing': ['english_title', 'freight_template']},
            'published': False,
        },
    )
    monkeypatch.setattr(
        flow,
        '_save_only_on_page',
        lambda page, **_kwargs: (_ for _ in ()).throw(AssertionError('save must not run before editor fields are filled')),
    )

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'save_only',
        defaults=_legacy_explicit_editor_defaults(title_override='English title from template'),
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'save_only_failed'
    assert result['label'] == '保存前编辑页配置未完成'
    assert '普通编辑页缺少字段' in result['message']
    assert result['source_editor_url'] == editor_url
    assert result['save_result']['ok'] is False
    assert result['save_result']['reason'] == 'editor_prefill_failed'
    assert result['published'] is None


def test_editor_required_defaults_state_accepts_existing_category_value(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <div class="ant-form-item" style="position:absolute;left:40px;top:120px;width:900px;height:48px">
              <label>产品分类</label>
              <span>手办/可动人形/机器人(Action Figures)</span>
              <button>选择分类</button>
              <button>自动识别分类</button>
            </div>
            <input type="text" value="Hazbin Hotel Alastor Acrylic Stand Keychain Colorful Bag Pendant Card" style="position:absolute;left:40px;top:180px;width:700px;height:32px" />
          </body>
        </html>
        ''')

        state = flow._editor_required_defaults_state(page, expected_category_match='Action Figures')
        browser.close()

    assert state['category_selected'] is True
    assert 'category' not in state['missing']
    assert 'ActionFigures' in state['category_text'].replace(' ', '')


def test_editor_required_defaults_state_rejects_placeholder_category(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body>
            <div class="ant-form-item" style="position:absolute;left:40px;top:120px;width:900px;height:48px">
              <label>产品分类</label>
              <span>----请选择分类----</span>
              <button>选择分类</button>
              <button>自动识别分类</button>
            </div>
            <input type="text" value="Hazbin Hotel Alastor Acrylic Stand Keychain Colorful Bag Pendant Card" style="position:absolute;left:40px;top:180px;width:700px;height:32px" />
          </body>
        </html>
        ''')

        state = flow._editor_required_defaults_state(page, expected_category_match='Action Figures')
        browser.close()

    assert state['category_selected'] is False
    assert 'category' in state['missing']


def test_verify_not_published_from_editor_page_does_not_reopen_with_hud(monkeypatch, tmp_path):
    page = DummySemiPage({'ok': True})
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    editor_url = page.url
    flow._write_state({
        'stage': 'save_only',
        'page_url': editor_url,
        'save_result': {'ok': True, 'published': False, 'success_text': '编辑成功'},
    })
    waits = []
    verified = []

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('verify should not reopen editor with HUD')),
    )
    monkeypatch.setattr(
        flow,
        '_wait_for_body_text',
        lambda page, terms, timeout=15000, expected_identity=None: waits.append((terms, timeout, expected_identity)) or True,
    )
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: 0)
    monkeypatch.setattr(
        flow,
        '_verify_not_published_on_page',
        lambda page, product_query, store_name, **_kwargs: verified.append((product_query, store_name)) or {
            'stage': 'not_published_verified',
            'published': False,
            'fill_result': {'proof_kind': 'structured_unpublished_status', 'status_text': '待发布'},
        },
    )

    frozen_kwargs = _bind_frozen_editor_action(flow, monkeypatch)
    result = flow._perform_editor_action(
        'verify_not_published',
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        **frozen_kwargs,
    )

    assert result['stage'] == 'not_published_verified'
    assert result['source_editor_url'] == editor_url
    assert waits == [(['基本信息', '产品信息', '保存'], 15000, 'editor')]
    assert verified == [('崩坏3钥匙扣', 'Dang Kang')]


def test_verify_not_published_rejects_prior_save_success_without_current_structured_proof(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path, action='verify_not_published')
    page = DummySemiPage({
        'ok': False,
        'save_only_term': None,
        'publish_risk_term': None,
        'published': False,
        'proof_kind': None,
        'status_text': None,
        'reason': 'structured_unpublished_status_missing',
    })

    target = _frozen_action_kwargs()['target_identity']
    state = flow._verify_not_published_on_page(
        page,
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        target_identity=target,
    )

    assert state['stage'] == 'verify_not_published_failed'
    assert state['fill_result']['reason'] == 'structured_unpublished_status_missing'
    assert 'verified_by_prior_save_result' not in state['fill_result']
    assert state['published'] is None


def test_verify_not_published_rejects_structured_published_status(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path, action='verify_not_published')
    page = DummySemiPage({
        'ok': False,
        'proof_kind': 'structured_product_status',
        'status_text': '已上架',
        'status_source': 'data-product-status',
        'target_bound': True,
        'publish_risk_term': '已上架',
        'published': True,
        'reason': 'structured_status_is_published',
    })

    target = _frozen_action_kwargs()['target_identity']
    state = flow._verify_not_published_on_page(
        page,
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        target_identity=target,
    )

    assert state['stage'] == 'verify_not_published_failed'
    assert state['message'] == '已上架'
    assert state['published'] is True
    assert state['fill_result']['publish_risk_term'] == '已上架'


def test_verify_not_published_does_not_use_generic_body_text_as_proof(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path, action='verify_not_published')
    scripts = []

    class BodyTextOnlyPage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def evaluate(self, script, _arg=None):
            scripts.append(script)
            return {
                'ok': False,
                'proof_kind': None,
                'status_text': None,
                'reason': 'structured_unpublished_status_missing',
                'published': False,
            }

        def title(self):
            return '店小秘编辑页'

    target = _frozen_action_kwargs()['target_identity']
    state = flow._verify_not_published_on_page(
        BodyTextOnlyPage(),
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        target_identity=target,
    )

    assert state['stage'] == 'verify_not_published_failed'
    assert 'document.body' not in scripts[0]
    assert 'data-product-status' in scripts[0]


def test_verify_not_published_preserves_network_save_evidence_separately(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    save_result = {
        'ok': True,
        'page_save_result': {'ok': True, 'success_text': '保存成功'},
        'network_save_result': {'ok': True, 'method': 'POST', 'code': 0},
        'network_events': [{'method': 'POST', 'status': 200}],
        'published': False,
    }
    unpublished_proof = {
        'ok': True,
        'proof_kind': 'structured_unpublished_status',
        'status_text': '待发布',
        'status_source': 'data-product-status',
        'target_bound': True,
        'published': False,
    }
    save_evidence_ref = {'path': 'save.png', 'sha256': 'a' * 64}
    unpublished_evidence_ref = {'path': 'unpublished.png', 'sha256': 'b' * 64}
    flow._write_state({
        'stage': 'save_only',
        'current_action': 'save_only',
        'save_result': save_result,
        'evidence_ref': save_evidence_ref,
    })
    monkeypatch.setattr(flow, '_perform_editor_action', lambda *_args, **_kwargs: {
        'ok': True,
        'stage': 'not_published_verified',
        'fill_result': unpublished_proof,
        'evidence_ref': unpublished_evidence_ref,
        'published': False,
    })

    state = flow.perform_editor_action(
        'verify_not_published',
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
    )

    assert state['save_result'] == save_result
    assert state['fill_result'] == unpublished_proof
    assert state['fill_result'] is not state['save_result']
    assert state['save_evidence_ref'] == save_evidence_ref
    assert state['unpublished_evidence_ref'] == unpublished_evidence_ref
    assert state['save_evidence_ref'] != state['unpublished_evidence_ref']


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


def test_dismiss_blocking_modals_removes_stuck_notice_after_repeated_ignore(monkeypatch, tmp_path):
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

    assert dismissed == 3
    assert len(clicks) == 2
    assert remaining == 0
    assert flow._last_dismiss_blocking_modals_trace[-1]['fallback'] == 'remove_stuck_notice_modal'


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


def test_remove_stuck_notice_modal_removes_stacked_safe_notices(tmp_path):
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

    assert removed['removed'] is True
    assert removed['removed_count'] == 2
    assert remaining == 0


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


def test_dismiss_data_acquisition_blocking_modals_clicks_plain_guide_skip(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <div class="guide-overlay" style="position:fixed;left:20px;top:20px;width:300px;height:160px;background:#111;color:#fff;z-index:9999">
              <div>1/5</div>
              <div>下一步</div>
              <div id="skip" style="position:absolute;right:16px;bottom:12px;width:56px;height:28px">跳过</div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)
            target_page.evaluate("document.querySelector('.guide-overlay')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] in {'跳过', 'guide:跳过', 'standalone:跳过'}


def test_dismiss_data_acquisition_blocking_modals_prefers_guide_skip_over_next(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001">
              <div class="guide-body" style="position:absolute;left:200px;top:200px;width:525px;height:138px">
                <div class="guide-title">安装店小秘采集插件</div>
                <div class="guide-btn flex">
                  <button style="width:71px;height:32px">下一步</button>
                  <button style="width:120px;height:32px">下载采集插件</button>
                  <div id="skip" style="display:inline-block;width:56px;height:32px">跳过</div>
                </div>
              </div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)
            target_page.evaluate("document.querySelector('.guide-overlay')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] in {'跳过', 'standalone:跳过'}


def test_dismiss_data_acquisition_blocking_modals_clicks_notice_button_not_footer(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1024})
        page.set_content(
            '''
            <div class="ant-modal-wrap bullet-layer notice-list-modal notice-list-modal--offline"
                 style="position:fixed;inset:0;z-index:3000">
              <div class="ant-modal" style="position:absolute;left:240px;top:67px;width:960px;height:640px;background:white">
                <div class="ant-modal-content">
                  <div class="notice-list-modal__body" style="height:560px">线下活动 小秘公告</div>
                  <div class="ant-modal-footer" style="position:absolute;left:0;bottom:0;width:960px;height:64px">
                    <div class="notice-list-modal__footer" style="width:960px;height:64px">
                      <button id="real-close" style="position:absolute;left:878px;top:16px;width:58px;height:32px">
                        <span>关闭</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            clicks.append(rect)
            target_page.evaluate("document.querySelector('.notice-list-modal')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks
    assert clicks[0]['w'] <= 70
    assert clicks[0]['h'] <= 40
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] == '关闭'


def test_complete_data_acquisition_claim_dialog_rejects_missing_requested_store_option(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            assert method == 'Runtime.evaluate'
            assert payload['timeout'] <= 2500
            assert '认领' in payload['expression']
            return {
                'result': {
                    'value': {
                        'ok': True,
                        'submitted': False,
                        'submit_text': '认领',
                        'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
                        'clicked_options': [],
                    }
                }
            }

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self):
            self.cdp = FakeCdp()
            self.context = FakeContext(self.cdp)

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('认领弹窗扫描不能使用无超时 page.evaluate')

        def wait_for_timeout(self, *_args, **_kwargs):
            pass

    page = FakePage()
    monkeypatch.setattr(flow, '_click_data_acquisition_claim_rect_center', lambda target_page, rect, **_kwargs: clicks.append(rect))

    result = flow._complete_data_acquisition_claim_dialog(page, category_name='QA_CATEGORY', store_name='Dang Kang')

    assert result['ok'] is False
    assert result['submitted'] is False
    assert 'Dang Kang' in result['reason']
    assert clicks == []
    assert page.cdp.calls


def test_complete_data_acquisition_claim_dialog_rejects_store_click_without_selected_readback(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_text': '确定',
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'text': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
        {
            'ok': True,
            'requested_store_name': 'Dang Kang',
            'observed_store_name': 'Dang Kang',
            'selected': False,
            'selection_evidence': {'input_checked': False, 'aria_checked': 'false'},
        },
    ])
    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', lambda *_args, **_kwargs: next(scans))
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda _page, rect, **kwargs: clicks.append((rect, kwargs.get('purpose'))) or {'dispatched': True},
    )

    result = flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert result['ok'] is False
    assert result['submitted'] is False
    assert result['store_selection']['selected'] is False
    assert [purpose for _, purpose in clicks] == ['认领弹窗选项']


def test_complete_data_acquisition_claim_dialog_rejects_missing_real_click_receipt(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: {
            'ok': True,
            'submitted': False,
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
    )
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda _page, _rect, **kwargs: clicks.append(kwargs.get('purpose')),
    )

    result = flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert result['ok'] is False
    assert result['submitted'] is False
    assert '点击回执' in result['reason']
    assert clicks == ['认领弹窗选项']


def test_complete_data_acquisition_claim_dialog_requires_and_returns_exact_store_selection_readback(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_text': '确定',
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'text': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
        {
            'ok': True,
            'requested_store_name': 'Dang Kang',
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang'],
            'selection_evidence': {
                'input_checked': True,
                'aria_checked': 'true',
                'aria_selected': None,
                'class_name': 'ant-checkbox-wrapper ant-checkbox-wrapper-checked',
            },
        },
    ])
    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', lambda *_args, **_kwargs: next(scans))
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda _page, rect, **kwargs: clicks.append((rect, kwargs.get('purpose'))) or {'dispatched': True},
    )
    flow.set_mutation_authorizer(
        _execute_authorized_operation,
        {'task_id': 7, 'job_id': 11, 'state': 'CLAIM_TO_DRAFT_BOX', 'mode': 'claim_only'},
    )

    result = flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert result['ok'] is True
    assert result['submitted'] is True
    assert result['store_selection']['observed_store_name'] == 'Dang Kang'
    assert result['store_selection']['selected'] is True
    assert result['submit_click_receipt']['dispatched'] is True
    assert [purpose for _, purpose in clicks] == ['认领弹窗选项', '认领弹窗确认']


def test_complete_data_acquisition_claim_dialog_rejects_another_selected_store(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_text': '确定',
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'text': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
        {
            'ok': True,
            'requested_store_name': 'Dang Kang',
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang', 'Another Store'],
            'selection_evidence': {'input_checked': True},
        },
    ])
    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', lambda *_args, **_kwargs: next(scans))
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda _page, rect, **kwargs: clicks.append((rect, kwargs.get('purpose'))) or {'dispatched': True},
    )

    result = flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert result['ok'] is False
    assert result['submitted'] is False
    assert result['store_selection']['selected_store_names'] == ['Dang Kang', 'Another Store']
    assert [purpose for _, purpose in clicks] == ['认领弹窗选项']


def test_claim_dialog_revalidates_at_confirm_click_and_does_not_click_when_expired(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
        {
            'ok': True,
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang'],
            'selection_evidence': {'input_checked': True},
        },
    ])
    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', lambda *_args, **_kwargs: next(scans))
    def fake_click(_page, _rect, **kwargs):
        mutation_action = kwargs.get('mutation_action')
        def operation():
            clicks.append(kwargs.get('purpose'))
            return {'dispatched': True}

        if not mutation_action:
            return operation()
        return flow._dispatch_authorized_mutation(mutation_action, operation)['operation_result']

    monkeypatch.setattr(flow, '_click_data_acquisition_claim_rect_center', fake_click)
    flow.set_mutation_authorizer(
        lambda _context, _operation: {'ok': False, 'reason_code': 'AUTH_LEASE_EXPIRED'},
        {'task_id': 7, 'job_id': 8, 'state': 'CLAIM_TO_DRAFT_BOX', 'mode': 'claim_only'},
    )

    with pytest.raises(RuntimeError, match='AUTH_LEASE_EXPIRED'):
        flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert clicks == ['认领弹窗选项']


def test_claim_dialog_confirm_rechecks_live_button_and_store_inside_authorized_operation(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []
    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
        },
        {
            'ok': True,
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang'],
            'selection_evidence': {'input_checked': True},
        },
    ])
    monkeypatch.setattr(flow, '_evaluate_zero_arg_page_function_with_runtime_timeout', lambda *_args, **_kwargs: next(scans))
    monkeypatch.setattr(
        flow,
        '_assert_data_acquisition_claim_dialog_submit_safe',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MutationAuthorizationError('MUTATION_TARGET_DRIFT: store changed')
        ),
    )

    def fake_click(_page, _rect, **kwargs):
        if not kwargs.get('mutation_action'):
            clicks.append(kwargs.get('purpose'))
            return {'dispatched': True}
        guard = kwargs.get('pre_dispatch_guard')
        assert callable(guard)
        def operation():
            guard()
            clicks.append(kwargs.get('purpose'))
            return {'dispatched': True}
        return flow._dispatch_authorized_mutation(
            kwargs['mutation_action'],
            operation,
        )['operation_result']

    monkeypatch.setattr(flow, '_click_data_acquisition_claim_rect_center', fake_click)
    flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 7})

    with pytest.raises(MutationAuthorizationError, match='MUTATION_TARGET_DRIFT'):
        flow._complete_data_acquisition_claim_dialog(object(), store_name='Dang Kang')

    assert clicks == ['认领弹窗选项']


@pytest.mark.parametrize('invalid_result', [None, True, 'unexpected'])
def test_mutation_authorizer_malformed_result_fails_closed(tmp_path, invalid_result):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow.set_mutation_authorizer(
        lambda _context, _operation: invalid_result,
        {'task_id': 7, 'job_id': 8, 'state': 'CLAIM_TO_DRAFT_BOX', 'mode': 'claim_only'},
    )

    with pytest.raises(RuntimeError, match='AUTH_REVALIDATION_FAILED'):
        flow._dispatch_authorized_mutation('claim_confirm_click', lambda: True)


def test_dispatch_authorized_mutation_rejection_never_executes_operation(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []
    flow.set_mutation_authorizer(
        lambda _context, _operation: {'ok': False, 'reason_code': 'AUTH_LEASE_EXPIRED'},
        {'task_id': 7, 'job_id': 8, 'state': 'CLAIM_TO_DRAFT_BOX', 'mode': 'claim_only'},
    )

    with pytest.raises(RuntimeError, match='AUTH_LEASE_EXPIRED'):
        flow._dispatch_authorized_mutation(
            'claim_confirm_click',
            lambda: operation_calls.append('clicked') or True,
        )

    assert operation_calls == []


def test_dispatch_authorized_mutation_without_authorizer_never_executes_operation(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []

    with pytest.raises(RuntimeError, match='AUTH_VERIFIER_MISSING'):
        flow._dispatch_authorized_mutation(
            'claim_confirm_click',
            lambda: operation_calls.append('clicked') or True,
        )

    assert operation_calls == []


def test_dispatch_authorized_mutation_executes_operation_exactly_once(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []

    def authorize(context, operation):
        operation_result = operation()
        return {
            'ok': True,
            'executed': True,
            'operation_result': operation_result,
            'reason_code': 'OK',
            'mutation_action': context['mutation_action'],
        }

    flow.set_mutation_authorizer(authorize, {'task_id': 7})

    result = flow._dispatch_authorized_mutation(
        'claim_confirm_click',
        lambda: operation_calls.append('clicked') or {'clicked': True},
    )

    assert operation_calls == ['clicked']
    assert result['ok'] is True
    assert result['executed'] is True
    assert result['operation_result'] == {'clicked': True}
    assert result['reason_code'] == 'OK'
    assert result['mutation_action'] == 'claim_confirm_click'
    assert result['authorization_facts']['ok'] is True
    assert result['authorization_facts']['executed'] is True
    assert result['authorization_facts']['mutation_action'] == 'claim_confirm_click'


def test_dispatch_authorized_mutation_blocks_second_operation_attempt(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []

    def authorize(_context, operation):
        operation()
        operation()
        return {'ok': True, 'executed': True, 'operation_result': True}

    flow.set_mutation_authorizer(authorize, {'task_id': 7})

    with pytest.raises(RuntimeError, match='MUTATION_OPERATION_MULTIPLE_EXECUTIONS'):
        flow._dispatch_authorized_mutation(
            'claim_confirm_click',
            lambda: operation_calls.append('clicked') or True,
        )

    assert operation_calls == ['clicked']


def test_dispatch_authorized_mutation_rejects_success_without_executed_proof(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []
    flow.set_mutation_authorizer(
        lambda _context, _operation: {
            'ok': True,
            'executed': False,
            'operation_result': None,
            'reason_code': 'OK',
        },
        {'task_id': 7},
    )

    with pytest.raises(RuntimeError, match='MUTATION_OPERATION_NOT_EXECUTED'):
        flow._dispatch_authorized_mutation(
            'claim_confirm_click',
            lambda: operation_calls.append('clicked') or True,
        )

    assert operation_calls == []


def test_dispatch_authorized_mutation_operation_error_is_not_retried(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    operation_calls = []

    def authorize(_context, operation):
        operation_result = operation()
        return {'ok': True, 'executed': True, 'operation_result': operation_result}

    def failing_operation():
        operation_calls.append('attempt')
        raise RuntimeError('dispatch exploded')

    flow.set_mutation_authorizer(authorize, {'task_id': 7})

    with pytest.raises(RuntimeError, match='MUTATION_OPERATION_FAILED'):
        flow._dispatch_authorized_mutation('claim_confirm_click', failing_operation)

    assert operation_calls == ['attempt']


def test_save_click_revalidates_at_exact_mutation_instant(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    clicks = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit'

        def evaluate(self, *_args, **_kwargs):
            return {'ok': True, 'rect': {'x': 10, 'y': 20, 'w': 80, 'h': 30}, 'published': False}

        def wait_for_timeout(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: False)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: 0)
    monkeypatch.setattr(flow, '_visible_blocking_modal_state', lambda _page: {'visible': False})
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    def fake_save_click(_page, **kwargs):
        def operation():
            clicks.append('save')
            return True

        return flow._dispatch_authorized_mutation(
            kwargs['mutation_action'],
            operation,
        )['operation_result']

    monkeypatch.setattr(flow, '_click_exact_save_button', fake_save_click)
    monkeypatch.setattr(flow, '_click_rect_center', lambda *_args, **_kwargs: clicks.append('rect'))
    flow.set_mutation_authorizer(
        lambda _context, _operation: {'ok': False, 'reason_code': 'AUTH_CONTEXT_MISMATCH'},
        {'task_id': 9, 'job_id': 10, 'state': 'SAVE_ONLY', 'mode': 'single_save'},
    )

    with pytest.raises(RuntimeError, match='AUTH_CONTEXT_MISMATCH'):
        flow._save_only_on_page(FakePage(), **_save_only_kwargs())

    assert clicks == []


def test_draft_box_evidence_paths_are_unique_and_content_attested(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    base = tmp_path / 'draft-box.png'

    flow.set_execution_evidence_context({
        'task_id': 1,
        'job_id': 2,
        'state': 'VERIFY_DRAFT_BOX_CLAIM',
        'command_id': 'command-a',
    })
    first = flow._scoped_evidence_path(base, action='verify_draft_box_claim')
    first.write_bytes(b'first-proof')
    first_ref = flow._evidence_descriptor(first)

    flow.set_execution_evidence_context({
        'task_id': 1,
        'job_id': 2,
        'state': 'VERIFY_DRAFT_BOX_CLAIM',
        'command_id': 'command-b',
    })
    second = flow._scoped_evidence_path(base, action='verify_draft_box_claim')
    second.write_bytes(b'second-proof')
    second_ref = flow._evidence_descriptor(second)

    assert first != second
    assert 'task_1_job_2_VERIFY_DRAFT_BOX_CLAIM_command-a' in first.name
    assert first_ref['path'] == str(first.resolve())
    assert first_ref['sha256'] != second_ref['sha256']
    assert first_ref['size'] == len(b'first-proof')


def test_scoped_evidence_capture_is_exclusive_and_does_not_overwrite(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({
        'task_id': 1,
        'job_id': 2,
        'state': 'SAVE_ONLY',
        'command_id': 'command-exclusive',
    })

    class FakePage:
        def screenshot(self, *, path, **_kwargs):
            Path(path).write_bytes(b'first-exclusive-proof')

    first = flow._capture_scoped_evidence_screenshot(
        FakePage(),
        tmp_path / 'save.png',
        action='save_only',
        full_page=True,
    )

    with pytest.raises(RuntimeError, match='EVIDENCE_PATH_ALREADY_EXISTS'):
        flow._capture_scoped_evidence_screenshot(
            FakePage(),
            tmp_path / 'save.png',
            action='save_only',
            full_page=True,
        )

    assert Path(first['path']).read_bytes() == b'first-exclusive-proof'
    assert first['sha256'] == hashlib.sha256(b'first-exclusive-proof').hexdigest().upper()
    assert first['size'] == len(b'first-exclusive-proof')


def test_visible_save_only_requires_network_and_page_success(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({
        'task_id': 3,
        'job_id': 4,
        'state': 'SAVE_ONLY',
        'command_id': f'command-save-proof-{tmp_path.parent.name}-{tmp_path.name}',
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def wait_for_timeout(self, _timeout):
            return None

        def screenshot(self, *, path, **_kwargs):
            Path(path).write_bytes(b'save-proof')

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(flow, '_visible_exact_save_button_state', lambda _page: {
        'ok': True,
        'rect': {'x': 10, 'y': 20, 'w': 80, 'h': 30},
        'viewport': {'screenX': 80, 'screenY': 80, 'outerWidth': 1600, 'outerHeight': 950},
    })
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow, '_structured_save_status_snapshot', lambda *_args, **_kwargs: {'ok': True, 'entries': []})
    monkeypatch.setattr(
        flow,
        '_visible_save_success_state',
        lambda _page, *, baseline=None: {'ok': True, 'success_text': '保存成功'},
    )
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {'ok': False})

    result = flow._save_only_on_page(FakePage(), **_save_only_kwargs())

    assert result['ok'] is False
    assert result['stage'] == 'save_only_failed'
    assert result['save_result']['page_save_result']['ok'] is True
    assert result['save_result']['network_save_result']['ok'] is False
    assert set(result['evidence_ref']) == {'path', 'sha256', 'size'}
    assert Path(result['evidence_ref']['path']).read_bytes() == b'save-proof'


def test_verify_not_published_returns_content_attested_evidence(monkeypatch, tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    flow.set_execution_evidence_context({
        'task_id': 5,
        'job_id': 6,
        'state': 'VERIFY_NOT_PUBLISHED',
        'command_id': f'command-unpublished-proof-{tmp_path.parent.name}-{tmp_path.name}',
    })

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def evaluate(self, *_args, **_kwargs):
            return {
                'ok': True,
                'proof_kind': 'structured_unpublished_status',
                'status_text': '待发布',
                'status_source': 'data-product-status',
                'target_bound': True,
                'status_scope_unique': True,
                'bound_candidate_count': 1,
                'publish_risk_term': None,
                'published': False,
            }

        def screenshot(self, *, path, **_kwargs):
            Path(path).write_bytes(b'unpublished-proof')

        def title(self):
            return '店小秘编辑页'

    target = _frozen_action_kwargs()['target_identity']
    monkeypatch.setattr(
        flow,
        '_require_frozen_product_page_identity',
        lambda *_args, **_kwargs: _frozen_identity_readback(target),
    )
    result = flow._verify_not_published_on_page(
        FakePage(),
        product_query='崩坏3钥匙扣',
        store_name='Dang Kang',
        target_identity=target,
    )

    assert result['ok'] is True
    assert result['stage'] == 'not_published_verified'
    assert result['fill_result']['proof_kind'] == 'structured_unpublished_status'
    assert result['fill_result']['status_text'] == '待发布'
    assert set(result['evidence_ref']) == {'path', 'sha256', 'size'}
    assert Path(result['evidence_ref']['path']).read_bytes() == b'unpublished-proof'


def test_complete_data_acquisition_claim_dialog_prefers_exact_store_option_over_modal_container(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.set_content(
            '''
            <div class="ant-modal" style="position:fixed;left:250px;top:80px;width:900px;height:520px;background:white">
              <div style="padding:20px">选择店铺-认领到采集箱</div>
              <div style="position:absolute;left:40px;top:80px;width:820px;height:300px">
                    <label class="ant-checkbox-wrapper" style="position:absolute;left:20px;top:40px;width:130px;height:26px">
                      <span class="ant-checkbox"><input type="checkbox"></span><span>Dang Kang</span>
                </label>
                <label class="ant-checkbox-wrapper" style="position:absolute;left:170px;top:40px;width:100px;height:26px">
                  <span class="ant-checkbox"></span><span>JX TOY</span>
                </label>
              </div>
              <button style="position:absolute;right:80px;bottom:40px;width:60px;height:32px">确定</button>
            </div>
            '''
        )

        def click_dialog_target(target_page, rect, **kwargs):
            purpose = kwargs.get('purpose')
            clicks.append((rect, purpose))
            if purpose == '认领弹窗选项':
                target_page.mouse.click(rect['x'] + rect['w'] / 2, rect['y'] + rect['h'] / 2)
            return {'dispatched': True}

        monkeypatch.setattr(flow, '_click_data_acquisition_claim_rect_center', click_dialog_target)
        flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 1})

        result = flow._complete_data_acquisition_claim_dialog(page, category_name='立牌类谷子', store_name='Dang Kang')
        browser.close()

    assert result['ok'] is True
    assert result['submitted'] is True
    assert clicks[0][1] == '认领弹窗选项'
    assert clicks[0][0]['w'] < 180
    assert clicks[0][0]['h'] < 40
    assert clicks[1][1] == '认领弹窗确认'


def test_complete_data_acquisition_claim_dialog_visible_mode_scans_and_submits(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicks = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def wait_for_timeout(self, *_args, **_kwargs):
            pass

    scans = iter([
        {
            'ok': True,
            'submitted': False,
            'submit_text': '确定',
            'submit_rect': {'x': 100, 'y': 120, 'w': 80, 'h': 32},
            'option_rects': [{'label': 'Dang Kang', 'rect': {'x': 30, 'y': 80, 'w': 120, 'h': 28}}],
            'clicked_options': ['Dang Kang'],
        },
        {
            'ok': True,
            'requested_store_name': 'Dang Kang',
            'observed_store_name': 'Dang Kang',
            'selected': True,
            'selected_store_names': ['Dang Kang'],
            'selection_evidence': {'input_checked': True},
        },
    ])
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: next(scans),
    )
    monkeypatch.setattr(
        flow,
        '_click_data_acquisition_claim_rect_center',
        lambda target_page, rect, **kwargs: clicks.append((rect, kwargs.get('purpose'))) or {'dispatched': True},
    )
    flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 1})

    result = flow._complete_data_acquisition_claim_dialog(FakePage(), category_name='立牌类谷子', store_name='Dang Kang')

    assert result['ok'] is True
    assert result['submitted'] is True
    assert clicks == [
        ({'x': 30, 'y': 80, 'w': 120, 'h': 28}, '认领弹窗选项'),
        ({'x': 100, 'y': 120, 'w': 80, 'h': 32}, '认领弹窗确认'),
    ]


def test_dismiss_data_acquisition_blocking_modals_uses_bounded_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakeCdp:
        def __init__(self):
            self.calls = []

        def send(self, method, payload):
            self.calls.append((method, payload))
            assert method == 'Runtime.evaluate'
            assert payload['timeout'] <= 2500
            assert 'guide-overlay' in payload['expression']
            raise RuntimeError('Runtime.evaluate timed out')

    class FakeContext:
        def __init__(self, cdp):
            self.cdp = cdp

        def new_cdp_session(self, page):
            return self.cdp

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self):
            self.cdp = FakeCdp()
            self.context = FakeContext(self.cdp)

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('data acquisition modal scan must not use unbounded page.evaluate')

    page = FakePage()

    dismissed = flow._dismiss_data_acquisition_blocking_modals(page)

    assert dismissed == 0
    assert page.cdp.calls


def test_dismiss_data_acquisition_blocking_modals_removes_blank_guide_overlay(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <button id="start">开始采集</button>
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001;background:rgba(0,0,0,.5)"></div>
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001">
              <div class="guide-body" style="display:none">1/5 下一步 跳过</div>
            </div>
            '''
        )

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        visible_overlays = page.locator('.guide-overlay').evaluate_all(
            """els => els.filter(el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }).length"""
        )
        browser.close()

    assert dismissed == 1
    assert visible_overlays == 0
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] == 'removed:blank-guide-overlay'


def test_dismiss_data_acquisition_blocking_modals_handles_notice_then_guide(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <div class="notice-list-modal" style="position:fixed;left:100px;top:80px;width:700px;height:420px;z-index:3000;background:white">
              <div>线下活动 小秘公告</div>
              <button id="close-notice" style="position:absolute;right:20px;bottom:20px;width:80px;height:32px">关闭</button>
            </div>
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001;background:rgba(0,0,0,.5)"></div>
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001">
              <div class="guide-body" style="display:none">1/5 下一步 跳过</div>
            </div>
            '''
        )

        def fake_click(target_page, rect):
            target_page.evaluate("document.querySelector('.notice-list-modal')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        notice_count = page.locator('.notice-list-modal').count()
        visible_overlays = page.locator('.guide-overlay').evaluate_all(
            """els => els.filter(el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }).length"""
        )
        browser.close()

    assert dismissed == 2
    assert notice_count == 0
    assert visible_overlays == 0
    assert {item['clicked'] for item in flow._last_dismiss_blocking_modals_trace} == {
        '关闭',
        'removed:blank-guide-overlay',
    }


def test_dismiss_data_acquisition_visible_browser_uses_native_only_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakeContext:
        def new_cdp_session(self, page):
            raise AssertionError('visible browser modal cleanup must not use CDP runtime scan')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def __init__(self):
            self.context = FakeContext()

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError('visible browser modal cleanup must not run page scripts')

    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda page: calls.append('notice') or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda page, trace: calls.append('native_points') or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda page: calls.append('escape') or True)

    page = FakePage()
    dismissed = flow._dismiss_data_acquisition_blocking_modals(page)

    assert dismissed == 0
    assert calls == ['notice', 'native_points', 'escape']


def test_dismiss_data_acquisition_visible_browser_falls_back_to_bounded_guide_scan(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def wait_for_timeout(self, timeout):
            calls.append(('wait', timeout))

    page = FakePage()
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda target_page: calls.append('notice') or True)
    monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda target_page, trace: calls.append('native_points') or 0)
    monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda target_page: calls.append('escape') or True)
    monkeypatch.setattr(flow, '_dismiss_data_acquisition_plugin_guide_with_runtime', lambda target_page, trace: 0)
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda target_page, script, timeout=2000: calls.append(('scan', timeout)) or {
            'visible': True,
            'clicked': '跳过',
            'rect': {'x': 340, 'y': 310, 'w': 56, 'h': 28},
            'text': '安装店小秘采集插件 1/5 下一步 下载采集插件 跳过',
        },
    )
    monkeypatch.setattr(flow, '_click_rect_center', lambda target_page, rect: calls.append(('click', rect)))

    dismissed = flow._dismiss_data_acquisition_blocking_modals(page)

    assert dismissed == 1
    assert ('scan', 2000) in calls
    assert ('click', {'x': 340, 'y': 310, 'w': 56, 'h': 28}) in calls
    assert flow._last_dismiss_blocking_modals_trace[-1]['clicked'] == '跳过'


def test_dismiss_data_acquisition_visible_browser_removes_plugin_guide_when_skip_click_sticks(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content(
            '''
            <button id="start">开始采集</button>
            <div class="guide-overlay" style="position:fixed;left:0;top:0;width:100%;height:100%;z-index:2001">
              <div id="guideBody" class="guide-body guide-bottom"
                   style="position:absolute;left:258px;top:247px;width:525px;height:138px;background:#111;color:#fff;z-index:10001">
                <div>安装店小秘采集插件</div>
                <div>支持谷歌、360、Edge、紫鸟浏览器安装采集插件，如何安装&gt;&gt;</div>
                <div class="guide-btn flex" style="position:absolute;left:30px;bottom:12px;width:480px;height:32px">
                  <button style="width:71px;height:32px">下一步</button>
                  <button style="width:126px;height:32px">下载采集插件</button>
                  <div class="m-left10 pointer" style="display:inline-block;width:26px;height:32px;cursor:pointer">跳过</div>
                </div>
              </div>
            </div>
            '''
        )

        monkeypatch.setattr(flow, '_is_data_acquisition_page_url', lambda _page: True)
        monkeypatch.setattr(flow, '_dismiss_data_acquisition_notice_with_native_click', lambda _page: False)
        monkeypatch.setattr(flow, '_click_data_acquisition_visible_dismiss_points', lambda _page, _trace: 0)
        monkeypatch.setattr(flow, '_press_native_escape_for_visible_dxm', lambda _page: False)
        monkeypatch.setattr(
            flow,
            '_click_rect_center',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('known plugin guide should be removed without native coordinate click')),
        )

        dismissed = flow._dismiss_data_acquisition_blocking_modals(page)
        visible_overlays = page.locator('.guide-overlay, .guide-body').evaluate_all(
            """els => els.filter(el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }).length"""
        )
        browser.close()

    assert dismissed == 1
    assert visible_overlays == 0
    assert flow._last_dismiss_blocking_modals_trace[-1]['clicked'] == 'runtime:guide-skip'


def test_open_data_acquisition_visible_page_reuses_loaded_page(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakeContext:
        def add_init_script(self, script):
            raise AssertionError('data acquisition sterile open must not inject scripts before loading')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'
        context = FakeContext()

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda target_page, url, **kwargs: calls.append(('sterile_goto', url, kwargs)))
    monkeypatch.setattr(flow, '_attach_and_reapply_live_hud_page', lambda _page: calls.append(('reuse',)))

    result = flow._open_data_acquisition_page_for_claim('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition')

    assert result is page
    assert calls == [('reuse',)]


def test_open_data_acquisition_non_current_page_uses_sterile_goto_without_notice_script(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    scripts = []
    gotos = []

    class FakeContext:
        def add_init_script(self, script):
            scripts.append(script)

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/home'
        context = FakeContext()

    page = FakePage()
    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', lambda target_page, url, **kwargs: gotos.append((url, kwargs)))

    flow._open_data_acquisition_page_for_claim('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition')
    flow._open_data_acquisition_page_for_claim('https://www.dianxiaomi.com/web/productCrawl/dataAcquisition', force_goto=True)

    assert scripts == []
    assert len(gotos) == 2


def test_open_data_acquisition_navigation_requires_identity_marker_and_no_loading(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/'

    page = FakePage()

    def fake_sterile_goto(target_page, url, **_kwargs):
        calls.append(('sterile_goto', url))
        target_page.url = url

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', lambda: page)
    monkeypatch.setattr(flow, '_goto_data_acquisition_sterile', fake_sterile_goto)
    monkeypatch.setattr(
        flow,
        '_browser_readiness_gate',
        lambda target_page, **kwargs: calls.append(('readiness', kwargs)) or {
            'ok': True,
            'business_marker': '认领',
            'loading': False,
            'page_url': target_page.url,
            'page_title': '店小秘--数据采集',
        },
    )
    monkeypatch.setattr(
        flow,
        '_wait_for_page_ready',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('open-only data acquisition must not run DOM readiness probe')),
    )
    monkeypatch.setattr(
        flow,
        '_goto_with_live_hud',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('open-only data acquisition must not inject live HUD before loading')),
    )

    result = flow._navigate_in_session('data_acquisition')

    assert calls == [
        ('sterile_goto', WORKFLOW_TARGETS['data_acquisition']['url']),
        ('readiness', {
            'label': '已有待认领列表',
            'expected_identity': 'data_acquisition',
            'ready_terms': WORKFLOW_READY_TERMS['data_acquisition'],
        }),
    ]
    assert result['page_url'] == WORKFLOW_TARGETS['data_acquisition']['url']
    assert result['wait_result']['ready_term'] == '认领'
    assert result['screenshot_url'] is None
    assert result['dismissed_blocking_modals'] == 0


def test_ensure_data_acquisition_page_reuses_visible_page_without_restarting_playwright(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class OldDataAcquisitionPage:
        url = 'https://www.dianxiaomi.com/web/productCrawl/dataAcquisition'

        def is_closed(self):
            return False

    flow._page = OldDataAcquisitionPage()
    flow._context = object()
    flow._browser = object()
    flow._playwright = object()

    def fake_ensure_page_with_cookies():
        raise AssertionError('visible data acquisition page must not restart Playwright')

    monkeypatch.setattr(flow, '_ensure_page_with_cookies', fake_ensure_page_with_cookies)

    result = flow._ensure_data_acquisition_page_with_cookies()

    assert result is flow._page
    assert flow._context is not None
    assert flow._browser is not None
    assert flow._playwright is not None
    assert flow.recent_workflow_events()[-1]['event'] == 'ensure_page:reuse_visible_data_acquisition_page'


def test_new_visible_browser_context_does_not_preinstall_data_acquisition_scripts(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    scripts = []

    class FakeBrowser:
        def new_context(self, **kwargs):
            assert kwargs['ignore_https_errors'] is True

            class FakeContext:
                def add_init_script(self, script):
                    scripts.append(script)

            return FakeContext()

    context = flow._new_browser_context(FakeBrowser())

    assert context is not None
    assert scripts == []


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


def test_dismiss_blocking_modals_prefers_topmost_notice_modal(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelectorAll('.ant-modal-wrap').forEach(el => el.remove())")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks
    assert flow._last_dismiss_blocking_modals_trace[0]['clicked'] == 'modal-close'


def test_dismiss_blocking_modals_allows_notice_copy_with_publish_word(monkeypatch, tmp_path):
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
            target_page.evaluate("document.querySelector('.notice-list-modal')?.remove()")

        monkeypatch.setattr(flow, '_click_rect_center', fake_click)

        dismissed = flow._dismiss_blocking_modals(page)
        browser.close()

    assert dismissed == 1
    assert clicks
    assert flow._last_dismiss_blocking_modals_trace[0]['dangerous'] is False


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

    result = flow._wait_for_page_ready(
        page,
        ['标题/产品ID'],
        label='速卖通采集箱',
        expected_identity='draft_box',
        timeout=3000,
    )

    assert result['ready'] is True
    assert result['ready_term'] == '标题/产品ID'
    assert page.ready_calls == 2
    assert page.dismiss_calls == 2


def test_wait_for_data_acquisition_ready_uses_real_control_probe(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDataAcquisitionReadyWaitPage()
    probes = []

    def fake_probe(_page, _terms):
        probes.append(1)
        return {
            'ready': True,
            'ready_term': 'data_acquisition_form_ready',
            'loading': False,
            'loading_count': 0,
            'rows': 0,
            'inputs': 1,
            'first_input_rect': {'x': 20, 'y': 40, 'w': 500, 'h': 100},
            'start_collect_rect': {'x': 700, 'y': 220, 'w': 120, 'h': 36},
            'text_excerpt': '数据采集 开始采集',
            'url': page.url,
            'title': '店小秘--数据采集',
            'loading_text': '',
            'strategy': 'test_control_probe',
        }

    monkeypatch.setattr(flow, '_inspect_data_acquisition_ready_state', fake_probe)
    monkeypatch.setattr(
        flow,
        '_data_acquisition_operable_snapshot',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('URL-only snapshot must not be used')),
        raising=False,
    )
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)

    result = flow._wait_for_page_ready(
        page,
        ['数据采集', '认领', '采集箱'],
        label='数据采集',
        expected_identity='data_acquisition',
        timeout=3000,
        dismiss_strategy='data_acquisition',
    )

    assert result['ready'] is True
    assert result['ready_term'] == 'data_acquisition_form_ready'
    assert result['strategy'] == 'test_control_probe'
    assert len(probes) == 1
    assert page.ready_calls == 0
    assert page.dismiss_calls == 0


def test_wait_for_data_acquisition_search_results_skip_dismiss_but_probe_controls(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyDataAcquisitionReadyWaitPage()
    probes = []

    def fake_probe(_page, _terms):
        probes.append(1)
        return {
            'ready': True,
            'ready_term': 'data_acquisition_form_ready',
            'loading': False,
            'loading_count': 0,
            'rows': 1,
            'inputs': 1,
            'first_input_rect': {'x': 20, 'y': 40, 'w': 500, 'h': 100},
            'start_collect_rect': {'x': 700, 'y': 220, 'w': 120, 'h': 36},
            'text_excerpt': '数据采集 开始采集 认领',
            'url': page.url,
            'title': '店小秘--数据采集',
            'loading_text': '',
            'strategy': 'test_control_probe',
        }

    monkeypatch.setattr(flow, '_inspect_data_acquisition_ready_state', fake_probe)
    monkeypatch.setattr(dxm_login_flow_module.time, 'sleep', lambda _seconds: None)

    result = flow._wait_for_page_ready(
        page,
        ['数据采集', '认领', '采集箱', '暂无数据'],
        label='数据采集搜索结果',
        expected_identity='data_acquisition',
        timeout=3000,
        dismiss_strategy='data_acquisition_no_dismiss',
    )

    assert result['ready'] is True
    assert result['strategy'] == 'test_control_probe'
    assert len(probes) == 1
    assert page.ready_calls == 0
    assert page.dismiss_calls == 0


def test_open_semi_managed_page_fails_on_product_info_error(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_editor_required_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_required_defaults_filled'})
    monkeypatch.setattr(flow, '_fill_editor_variants_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'editor_variants_filled'})
    monkeypatch.setattr(flow, '_fill_compliance_defaults_on_page', lambda page, defaults=None, **_kwargs: {'stage': 'compliance_defaults_filled'})
    monkeypatch.setattr(flow, '_repair_product_main_images_on_page', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_enable_semi_managed_on_page', lambda page: {'stage': 'semi_managed_enabled', 'screenshot_url': '/artifacts/screenshots/semi.png'})
    monkeypatch.setattr(flow, '_semi_managed_page_state', lambda page: {'blocked': True, 'message': '产品信息中有错误，请检查'})

    state = flow._open_semi_managed_page_from_editor(DummyOpenSemiPage())

    assert state['stage'] == 'open_semi_managed_page_failed'
    assert state['published'] is None
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


def test_visible_editor_attribute_reference_uses_safe_modal_probe(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    events = []
    contexts = []
    selected_templates = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

        def wait_for_timeout(self, _timeout):
            pass

    def eval_runtime(_page, _script, arg, *, timeout=3000):
        assert timeout == 2500
        if isinstance(arg, list):
            return {'ok': True, 'already_selected': True, 'text': arg[0]}
        raise AssertionError(f'unexpected runtime arg: {arg!r}')

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(flow, '_evaluate_page_function_with_runtime_timeout', eval_runtime)
    monkeypatch.setattr(flow, '_trace_workflow_event', lambda event, **payload: events.append((event, payload)))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible editor must not use heavy modal scan')))
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda _page, *, context: contexts.append(context) or 0)
    monkeypatch.setattr(
        flow,
        '_choose_ant_select_near_label',
        lambda page, label, names: selected_templates.append((label, names)) or {'ok': True, 'text': names[0]},
    )
    flow.set_mutation_authorizer(_execute_authorized_operation, {'task_id': 1})

    result = flow._apply_reference_templates_on_page(FakePage(), ['立牌类谷子属性模板'])

    assert result == {'ok': True, 'already_selected': True, 'text': '立牌类谷子属性模板'}
    assert contexts == ['apply_reference_templates:before_probe']

    results = flow._apply_dxm_reference_templates_on_page(
        FakePage(),
        {
            'attribute_info': {'names': ['立牌类谷子属性模板'], 'required': True},
            'freight': {'names': ['40g普货包裹'], 'required': True},
        },
    )

    assert results['attribute_info']['ok'] is True
    assert results['attribute_info']['text'] == '立牌类谷子属性模板'
    assert results['attribute_info'].get('deferred_to_category_attributes') is not True
    assert selected_templates == [('运费模板', ['40g普货包裹'])]
    assert results['freight']['ok'] is True
    assert results['freight']['text'] == '40g普货包裹'
    assert [event for event, _payload in events] == [
        'dxm_reference_template:start',
        'dxm_reference_template:done',
        'dxm_reference_template:start',
        'dxm_reference_template:done',
    ]


def test_devtools_target_selection_requires_one_exact_page_url(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class Page:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123#section'

    exact = {
        'id': 'exact',
        'type': 'page',
        'url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'webSocketDebuggerUrl': 'ws://exact',
    }
    substring = {
        'id': 'substring',
        'type': 'page',
        'url': 'https://www.dianxiaomi.com/web/smt/edit?id=1234',
        'webSocketDebuggerUrl': 'ws://substring',
    }

    assert flow._select_devtools_page_target(Page(), [substring]) is None
    assert flow._select_devtools_page_target(Page(), [substring, exact]) is exact
    assert flow._select_devtools_page_target(Page(), [exact, dict(exact, id='duplicate')]) is None


def test_browser_process_selection_uses_exact_port_and_profile(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    profile = tmp_path / 'profile'
    records = [
        {'pid': 11, 'name': 'chrome.exe', 'command_line': f'chrome.exe --remote-debugging-port=19222 --user-data-dir="{profile}"'},
        {'pid': 12, 'name': 'chrome.exe', 'command_line': f'chrome.exe --remote-debugging-port=9222 --user-data-dir="{profile}2"'},
        {'pid': 13, 'name': 'msedge.exe', 'command_line': f'msedge.exe --remote-debugging-port=9222 --user-data-dir="{profile}"'},
    ]

    assert flow._select_browser_process_id(records, port=9222, profile_dir=profile) == 13
    assert flow._select_browser_process_id(
        [records[2], dict(records[2], pid=14)],
        port=9222,
        profile_dir=profile,
    ) is None


def test_owned_native_window_selection_rejects_wrong_pid_and_ambiguity(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    metrics = {'screenX': 80, 'screenY': 80, 'outerWidth': 1600, 'outerHeight': 950}
    correct = {
        'hwnd': 101,
        'pid': 13,
        'class': 'Chrome_WidgetWin_1',
        'visible': True,
        'rect': {'left': 80, 'top': 80, 'width': 1600, 'height': 950},
    }
    wrong_pid = {**correct, 'hwnd': 102, 'pid': 99}

    assert flow._select_owned_native_window([wrong_pid, correct], expected_pid=13, viewport_metrics=metrics) is correct
    assert flow._select_owned_native_window(
        [correct, {**correct, 'hwnd': 103}],
        expected_pid=13,
        viewport_metrics=metrics,
    ) is None
    assert flow._select_owned_native_window([wrong_pid], expected_pid=13, viewport_metrics=metrics) is None


def test_native_binding_snapshot_rejects_any_identity_drift(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    expected = {
        'session_id': 'session-1',
        'browser_id': 1,
        'context_id': 2,
        'page_id': 3,
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=123',
        'target_id': 'target-1',
        'browser_pid': 13,
        'window_hwnd': 101,
        'foreground_hwnd': 101,
    }

    assert flow._native_binding_snapshot_matches(expected, dict(expected)) is True
    for field in expected:
        changed = dict(expected)
        changed[field] = f'drift-{field}'
        assert flow._native_binding_snapshot_matches(expected, changed) is False


def test_apply_reference_templates_matches_real_product_attribute_template_select(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicked_rects = []

    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: clicked_rects.append(dict(rect)))
    html = '''
    <html>
      <body style="height:9000px">
        <div class="form-card" style="position:absolute;left:100px;top:5000px;width:1100px;height:220px">
          <div class="form-card-header">
            <span>属性信息</span>
            <div class="d-selector">
              <div class="ant-select in-selector" style="width:240px;height:32px"
                onclick="document.querySelector('.ant-select-dropdown').style.display='block'">
                <div class="ant-select-selector" style="width:240px;height:32px">
                  <span class="ant-select-selection-placeholder">请选择【产品属性模板】</span>
                </div>
              </div>
            </div>
          </div>
          <div class="form-card-content">产品属性 适用年龄(Recommend Age) 必选属性</div>
        </div>
        <div class="ant-select-dropdown" style="display:none;position:absolute;left:110px;top:5050px;width:240px;height:96px">
          <div class="ant-select-item-option" style="display:flex;width:232px;height:32px"
            onclick="document.querySelector('.ant-select').textContent='万代立牌'">万代立牌</div>
          <div class="ant-select-item-option" style="display:flex;width:232px;height:32px">bilibili动漫周边</div>
          <div class="ant-select-item-option" style="display:flex;width:232px;height:32px">万代</div>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        result = flow._apply_reference_templates_on_page(page, ['万代立牌'])
        browser.close()

    assert result['ok'] is True
    assert result['verified']['ok'] is True
    assert clicked_rects
    assert 0 <= clicked_rects[0]['y'] <= 800


def test_apply_reference_templates_treats_existing_attribute_template_text_as_applied(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    html = '''
    <html>
      <body>
        <section>
          <h3>属性信息</h3>
          <div>产品属性模板</div>
          <div class="ant-select" style="width:240px;height:32px">
            <div class="ant-select-selector">万代立牌 万代立牌</div>
          </div>
        </section>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        result = flow._apply_reference_templates_on_page(page, ['万代立牌'])
        browser.close()

    assert result['ok'] is True
    assert result['already_selected'] is True
    assert '万代立牌' in result['text']


def test_visible_editor_text_field_prefers_stable_subject_selector(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_trace_workflow_event', lambda *_args, **_kwargs: None)
    html = '''
    <html>
      <body>
        <label>页面上没有可用的标题标签</label>
        <input name="subject" value="旧标题" />
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        result = flow._fill_text_inputs_after_label_locator(page, '产品标题', ['新标题'])
        value = page.locator('input[name="subject"]').input_value()
        browser.close()

    assert result['ok'] is True
    assert result['method'] == 'visible_known_selector'
    assert result['selector'] == 'input[name="subject"]:visible'
    assert value == '新标题'


def test_visible_editor_text_field_prefers_visible_subject_when_hidden_duplicate_exists(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_trace_workflow_event', lambda *_args, **_kwargs: None)
    html = '''
    <html>
      <body>
        <input name="subject" value="隐藏标题" style="display:none" />
        <input name="subject" value="可见标题" />
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        result = flow._fill_text_inputs_after_label_locator(page, '产品标题', ['新标题'])
        hidden_value = page.locator('input[name="subject"]').nth(0).input_value()
        visible_value = page.locator('input[name="subject"]').nth(1).input_value()
        browser.close()

    assert result['ok'] is True
    assert result['method'] == 'visible_known_selector'
    assert result['selector'] == 'input[name="subject"]:visible'
    assert hidden_value == '隐藏标题'
    assert visible_value == '新标题'


def test_visible_editor_text_field_falls_back_to_label_locator(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_trace_workflow_event', lambda *_args, **_kwargs: None)
    html = '''
    <html>
      <body>
        <label>自定义字段</label>
        <input value="旧值" />
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)

        result = flow._fill_text_inputs_after_label_locator(page, '自定义字段', ['新值'])
        value = page.locator('input').input_value()
        browser.close()

    assert result['ok'] is True
    assert result['method'] == 'visible_label_following_locator'
    assert value == '新值'


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


def test_click_ant_option_near_rect_dispatches_option_event_when_mouse_click_noops(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: None)
    html = '''
    <html>
      <head>
        <style>
          .ant-select { position: fixed; left: 300px; top: 200px; width: 250px; height: 32px; }
          .ant-select-dropdown { position: fixed; left: 300px; top: 240px; width: 250px; }
          .ant-select-item-option { height: 28px; padding: 4px 8px; }
        </style>
      </head>
      <body>
        <div class="ant-select"><span class="ant-select-selection-placeholder">请选择运费模板</span></div>
        <div class="ant-select-dropdown">
          <div class="ant-select-item-option" role="option"
            onmousedown="document.querySelector('.ant-select').textContent='石油40g普货包裹.'"
            onclick="document.querySelector('.ant-select').textContent='石油40g普货包裹.'">石油40g普货包裹.</div>
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
            ['石油40g普货包裹.'],
            {'x': 300, 'y': 200, 'w': 250, 'h': 32},
        )
        selected_text = page.locator('.ant-select').inner_text()
        browser.close()

    assert result['ok'] is True
    assert result['text'] == '石油40g普货包裹.'
    assert result['click_method'] == 'dom_dispatch'
    assert selected_text == '石油40g普货包裹.'


def test_choose_ant_select_near_label_refreshes_offscreen_rect_by_input_id(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicked_rects = []

    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: clicked_rects.append(dict(rect)))
    monkeypatch.setattr(flow, '_click_ant_option_near_rect', lambda page, priorities, rect, required=True: {'ok': True, 'text': priorities[0]})
    monkeypatch.setattr(flow, '_verify_ant_select_value', lambda page, input_id, rect, priorities: {'ok': True, 'text': priorities[0]})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content('''
        <html>
          <body style="height:9000px">
            <div class="ant-form-item" style="position:absolute;left:40px;top:7600px;width:700px;height:48px">
              <label>运费模板</label>
              <div class="ant-select" style="position:absolute;left:240px;top:0;width:250px;height:32px">
                <div class="ant-select-selector" style="width:250px;height:32px">
                  <input id="form_item_freightTemplateId" />
                  <span>请选择运费模板</span>
                </div>
              </div>
            </div>
          </body>
        </html>
        ''')

        result = flow._choose_ant_select_near_label(page, '运费模板', ['40g普货包裹'])
        browser.close()

    assert result['ok'] is True
    assert clicked_rects
    assert 0 <= clicked_rects[0]['y'] <= 800


def test_choose_ant_select_near_label_recomputes_rect_after_locator_scroll(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    clicked_rects = []

    class FakeLocator:
        def __init__(self, page):
            self.page = page

        @property
        def first(self):
            return self

        def scroll_into_view_if_needed(self, timeout=None):
            self.page.scrolled = True

    class FakeKeyboard:
        def press(self, key):
            pass

    class FakePage:
        def __init__(self):
            self.scrolled = False
            self.keyboard = FakeKeyboard()

        def wait_for_timeout(self, timeout):
            pass

        def locator(self, selector):
            assert selector == '#form_item_freightTemplateId'
            return FakeLocator(self)

        def evaluate(self, script, arg=None):
            if isinstance(arg, str):
                return {
                    'rect': {'x': 320, 'y': 7600, 'w': 250, 'h': 32},
                    'text': '请选择运费模板',
                    'input_id': 'form_item_freightTemplateId',
                }
            if isinstance(arg, dict) and arg.get('inputId') == 'form_item_freightTemplateId':
                return {
                    'rect': {'x': 320, 'y': 220, 'w': 250, 'h': 32},
                    'text': '请选择运费模板',
                    'input_id': 'form_item_freightTemplateId',
                }
            raise AssertionError(f'unexpected evaluate arg: {arg!r}')

    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: clicked_rects.append(dict(rect)))
    monkeypatch.setattr(flow, '_click_ant_option_near_rect', lambda page, priorities, rect, required=True: {'ok': True, 'text': priorities[0]})
    monkeypatch.setattr(flow, '_verify_ant_select_value', lambda page, input_id, rect, priorities: {'ok': True, 'text': priorities[0]})

    page = FakePage()
    result = flow._choose_ant_select_near_label(page, '运费模板', ['40g普货包裹'])

    assert result['ok'] is True
    assert page.scrolled is True
    assert clicked_rects[0]['y'] == 220


def test_choose_ant_select_near_label_dispatches_selector_when_rect_click_does_not_open(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakeLocator:
        @property
        def first(self):
            return self

        def scroll_into_view_if_needed(self, timeout=None):
            pass

    class FakeKeyboard:
        def press(self, key):
            pass

    class FakePage:
        def __init__(self):
            self.keyboard = FakeKeyboard()
            self.opened = False

        def wait_for_timeout(self, timeout):
            pass

        def locator(self, selector):
            return FakeLocator()

        def evaluate(self, script, arg=None):
            if isinstance(arg, str):
                return {
                    'rect': {'x': 320, 'y': 220, 'w': 250, 'h': 32},
                    'text': '请选择运费模板',
                    'input_id': 'form_item_freightTemplateId',
                }
            if isinstance(arg, dict) and arg.get('inputId') == 'form_item_freightTemplateId':
                if 'selector' in script and 'dispatchEvent' in script:
                    self.opened = True
                    return {'opened': True, 'expanded': True}
                return {
                    'rect': {'x': 320, 'y': 220, 'w': 250, 'h': 32},
                    'text': '请选择运费模板',
                    'input_id': 'form_item_freightTemplateId',
                }
            raise AssertionError(f'unexpected evaluate arg: {arg!r}')

    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: None)

    def click_option(page, priorities, rect, required=True):
        assert page.opened is True
        return {'ok': True, 'text': priorities[0]}

    monkeypatch.setattr(flow, '_click_ant_option_near_rect', click_option)
    monkeypatch.setattr(flow, '_verify_ant_select_value', lambda page, input_id, rect, priorities: {'ok': True, 'text': priorities[0]})

    result = flow._choose_ant_select_near_label(FakePage(), '运费模板', ['40g普货包裹'])

    assert result['ok'] is True


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


def test_check_choice_by_text_verifies_real_checked_state_when_coordinate_click_noops(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: None)
    html = '''
    <html>
      <head>
        <style>
          label { display:block; width:240px; height:32px; margin:40px; }
          input { width:16px; height:16px; }
        </style>
      </head>
      <body>
        <label class="ant-radio-wrapper">
          <span class="ant-radio"><input type="radio" name="tax" value="no"></span>
          <span>不含关税报价</span>
        </label>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        result = flow._check_choice_by_text(page, '不含关税报价')
        checked = page.evaluate("document.querySelector('input[name=tax]').checked")
        browser.close()

    assert result['ok'] is True
    assert result['checked'] is True
    assert checked is True


def test_click_exact_save_button_dispatches_exact_element_handle_when_coordinate_helper_noops(monkeypatch, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        pytest.skip(f'Playwright unavailable: {exc}')

    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    monkeypatch.setattr(flow, '_click_rect_center', lambda page, rect: None)
    html = '''
    <html>
      <head>
        <style>
          body { height: 2000px; }
          button { margin-top: 120px; width: 70px; height: 32px; }
        </style>
      </head>
      <body>
        <button onclick="window.saved = true">保存</button>
        <button onclick="window.published = true">发布</button>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.set_content(html)
        clicked = flow._click_exact_save_button(page)
        state = page.evaluate("({saved: Boolean(window.saved), published: Boolean(window.published)})")
        browser.close()

    assert clicked is True
    assert state == {'saved': True, 'published': False}


def test_fill_editor_required_defaults_rejects_unsupported_reference_templates_before_write(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page, **_kwargs: {'missing': []})

    state = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            dxm_reference_templates_resolved={
                'description': {'names': ['详情模板'], 'required': True},
                'compliance': {'names': ['合规模板'], 'required': True},
                'semi_managed': {'names': ['半托管模板'], 'required': True},
            },
        ),
    )

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['failure_code'] == 'UNSUPPORTED_REFERENCE_TEMPLATE_RUNTIME'
    assert state['fill_result']['write_attempted'] is False
    assert state['fill_result']['missing'] == [
        'dxm_reference_templates.description',
        'dxm_reference_templates.compliance',
        'dxm_reference_templates.semi_managed',
    ]


def test_visible_editor_applies_attribute_template_before_manual_attributes(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({})
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    applied = []

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_apply_reference_templates_on_page',
        lambda seen_page, names: applied.append((seen_page, names)) or {'ok': True, 'text': names[0]},
    )

    results = flow._apply_dxm_reference_templates_on_page(
        page,
        {
            'dxm_reference_templates_resolved': {
                'attribute_info': {'names': ['立牌类谷子属性模板'], 'required': True},
            },
        },
    )

    assert applied == [(page, ['立牌类谷子属性模板'])]
    assert results['attribute_info']['ok'] is True
    assert results['attribute_info']['text'] == '立牌类谷子属性模板'
    assert results['attribute_info'].get('deferred_to_category_attributes') is not True


def test_fill_editor_required_defaults_skips_manual_attributes_when_template_applied(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(
        flow,
        '_apply_dxm_reference_templates_on_page',
        lambda page, values: {
            'attribute_info': {
                'ok': True,
                'text': '立牌类谷子属性模板',
                'section': 'attribute_info',
                'names': ['立牌类谷子属性模板'],
                'required': True,
            },
            'freight': {'ok': True, 'section': 'freight', 'names': ['40g普货包裹'], 'required': True},
            'service': {'ok': True, 'section': 'service', 'names': ['Service Template for New Sellers'], 'required': True},
        },
    )
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_fill_category_required_attributes',
        lambda page: (_ for _ in ()).throw(AssertionError('template success must not default to manual attribute filling')),
    )
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page, **_kwargs: _complete_editor_defaults_state())

    state = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            dxm_reference_templates_resolved={
                'attribute_info': {'names': ['立牌类谷子属性模板'], 'required': True},
                'freight': {'names': ['40g普货包裹'], 'required': True},
                'service': {'names': ['Service Template for New Sellers'], 'required': True},
            },
        ),
    )

    assert state['stage'] == 'editor_required_defaults_filled'
    assert state['fill_result']['category_attributes'] == {
        'ok': True,
        'skipped': True,
        'via_template': True,
        'reason': '属性引用模板已套用，默认不手动填写类目属性。',
    }


def test_fill_editor_required_defaults_blocks_missing_required_attribute_template(monkeypatch, tmp_path):
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

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: reference_results)
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_fill_category_required_attributes',
        lambda page: (_ for _ in ()).throw(AssertionError('required template miss must not default to manual attributes')),
    )
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page, **_kwargs: {'missing': []})

    state = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            dxm_reference_templates_resolved={
                'attribute_info': {'names': ['万代立牌'], 'required': True},
                'freight': {'names': ['40g普货包裹'], 'required': True},
                'service': {'names': ['Service Template for New Sellers'], 'required': True},
            },
        ),
    )

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['label'] == '店小秘引用模板失败'
    assert state['fill_result']['missing'] == ['dxm_reference_templates.attribute_info']
    attribute_info = state['fill_result']['dxm_reference_template_results']['attribute_info']
    assert attribute_info['ok'] is False
    assert attribute_info.get('deferred_to_category_attributes') is not True


def test_fill_editor_required_defaults_rejects_configured_optional_template_miss_before_manual_fill(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(
        flow,
        '_apply_dxm_reference_templates_on_page',
        lambda page, values: {
            'attribute_info': {
                'ok': False,
                'reason': '未找到匹配选项',
                'options': [],
                'section': 'attribute_info',
                'names': ['可选属性模板'],
                'required': False,
            },
            'freight': {'ok': True, 'section': 'freight', 'names': ['40g普货包裹'], 'required': True},
            'service': {'ok': True, 'section': 'service', 'names': ['Service Template for New Sellers'], 'required': True},
        },
    )
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_fill_category_required_attributes',
        lambda page: (_ for _ in ()).throw(AssertionError('template miss must not default to manual attribute filling')),
    )
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda page, **_kwargs: _complete_editor_defaults_state())

    state = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            dxm_reference_templates_resolved={
                'attribute_info': {'names': ['可选属性模板'], 'required': False},
                'freight': {'names': ['40g普货包裹'], 'required': True},
                'service': {'names': ['Service Template for New Sellers'], 'required': True},
            },
        ),
    )

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['label'] == '店小秘引用模板失败'
    assert state['fill_result']['missing'] == ['dxm_reference_templates.attribute_info']
    attribute_info = state['fill_result']['dxm_reference_template_results']['attribute_info']
    assert attribute_info['ok'] is False
    assert attribute_info['required'] is False
    assert attribute_info.get('deferred_to_category_attributes') is not True


def test_fill_packaging_info_fills_base_and_gross_dimensions(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    html = '''
    <html><body>
      <style>input { width: 100px; height: 32px; }</style>
      <section>
        <label>重量(kg)<input placeholder="请输入重量" value="" /></label>
        <label>包装尺寸(cm)
          <input placeholder="长" value="" />
          <input placeholder="宽" value="" />
          <input placeholder="高" value="" />
        </label>
      </section>
      <div style="height: 120px"></div>
      <section>
        <label>包装后重量<input id="form_item_grossWeight" value="" /></label>
        <label>包装后尺寸
          <input value="" />
          <input value="" />
          <input value="" />
        </label>
      </section>
    </body></html>
    '''

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html)

            result = flow._fill_packaging_info(page, gross_weight='0.03', dimensions=['10', '10', '2'])
            values = page.evaluate('''() => ({
              base_weight: document.querySelector('[placeholder="请输入重量"]').value,
              base_length: document.querySelector('[placeholder="长"]').value,
              base_width: document.querySelector('[placeholder="宽"]').value,
              base_height: document.querySelector('[placeholder="高"]').value,
              gross_weight: document.getElementById('form_item_grossWeight').value,
              all_values: Array.from(document.querySelectorAll('input')).map(el => el.value),
            })''')
        finally:
            browser.close()

    assert result['ok'] is True
    assert values['base_weight'] == '0.03'
    assert values['base_length'] == '10'
    assert values['base_width'] == '10'
    assert values['base_height'] == '2'
    assert values['gross_weight'] == '0.03'
    assert values['all_values'][-3:] == ['10', '10', '2']


def test_fill_editor_required_defaults_rejects_downstream_owned_required_fields(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })

    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda page: None)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: _applied_attribute_reference_template())
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_visible_editor_text_input_state', lambda _page, label: {'ok': True, 'value': 'SKU-OK'} if label == '商品编码' else {'ok': False})
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': False, 'reason': '后续合规步骤处理'})
    monkeypatch.setattr(
        flow,
        '_editor_required_defaults_state',
        lambda page, **_kwargs: {
            **_complete_editor_defaults_state(),
            'missing': ['declared_value', 'weight', 'customs_supervision'],
        },
    )

    state = flow._fill_editor_required_defaults_on_page(page, _legacy_explicit_editor_defaults())

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['fill_result']['missing'] == ['customs_supervision', 'declared_value', 'weight']
    assert state['published'] is None


def test_visible_editor_fill_defaults_uses_safe_modal_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    safe_contexts = []

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_fill_visible_editor_title_with_native_input', lambda page, title, **kwargs: {'ok': True, 'title': title})
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible editor must not run heavy modal scan')),
    )
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals_if_visible',
        lambda _page, *, context: safe_contexts.append(context) or 0,
    )
    monkeypatch.setattr(
        flow,
        '_apply_dxm_reference_templates_on_page',
        lambda page, values: {
            'attribute_info': {
                'ok': True,
                'section': 'attribute_info',
                'names': ['立牌类谷子属性模板'],
                'required': True,
            },
        },
    )
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: 'Pokemon Poke Ball Toy Model')
    monkeypatch.setattr(
        flow,
        '_visible_editor_text_input_state',
        lambda _page, label: {
            'ok': label in {'商品编码', '发货期限'},
            'value': {'商品编码': 'SKU-001', '发货期限': '7'}.get(label, ''),
        },
    )
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_category_required_attributes', lambda page: {'ok': True})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_editor_required_defaults_state',
        lambda page, **_kwargs: _complete_editor_defaults_state(title='Pokemon Poke Ball Toy Model'),
    )

    state = flow._fill_editor_required_defaults_on_page(page, _legacy_explicit_editor_defaults(title_override='Pokemon Poke Ball Toy Model'))

    assert state['stage'] == 'editor_required_defaults_filled'
    assert safe_contexts == [
        'fill_editor_required_defaults:after_category',
        'fill_editor_required_defaults:before_selects',
        'fill_editor_required_defaults:before_validation',
    ]


def test_visible_editor_fill_defaults_blocks_when_required_sections_remain_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({
        'title': True,
        'remaining_chinese_attributes': [],
    })
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda _page, *, context: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: _applied_attribute_reference_template())
    monkeypatch.setattr(flow, '_fill_visible_editor_title_with_native_input', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: 'Pokemon Poke Ball Toy Model')
    monkeypatch.setattr(
        flow,
        '_visible_editor_text_input_state',
        lambda _page, label: {
            'ok': label in {'商品编码', '发货期限'},
            'value': {'商品编码': 'SKU-001', '发货期限': '7'}.get(label, ''),
        },
    )
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': False, 'reason': '包装字段为空'})

    state = flow._fill_editor_required_defaults_on_page(page, _legacy_explicit_editor_defaults(title_override='Pokemon Poke Ball Toy Model'))

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['label'] == '包装信息未完成'
    assert state['fill_result']['missing'] == ['packaging']


def test_visible_editor_required_defaults_state_uses_runtime_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({})
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    calls = []

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_evaluate_page_function_with_runtime_timeout',
        lambda probe_page, script, _expected_category, timeout=2000: calls.append((probe_page, timeout)) or {
            'missing': ['freight_template', 'service_template'],
            'values': {
                'freight_template': '请选择运费模板',
                'service_template': '请选择服务模板',
            },
            'category_selected': True,
        },
    )

    state = flow._editor_required_defaults_state(page, expected_category_match='ACG Stand')

    assert calls
    assert state['missing'] == ['freight_template', 'service_template']
    assert state.get('visible_probe_skipped') is not True


def _native_snapshot(width: int, height: int, blue_rects: list[tuple[int, int, int, int]]) -> dict:
    pixels = bytearray([245, 245, 245, 255] * width * height)
    for x, y, w, h in blue_rects:
        for yy in range(max(y, 0), min(y + h, height)):
            for xx in range(max(x, 0), min(x + w, width)):
                index = (yy * width + xx) * 4
                pixels[index:index + 4] = bytes([180, 130, 60, 255])
    return {'width': width, 'height': height, 'pixels': bytes(pixels)}


def test_native_loading_spinner_detector_accepts_compact_center_spinner(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    snapshot = _native_snapshot(
        1000,
        800,
        [
            (486, 350, 12, 12),
            (520, 358, 12, 12),
            (540, 390, 12, 12),
            (520, 422, 12, 12),
            (486, 430, 12, 12),
            (455, 410, 12, 12),
            (448, 375, 12, 12),
            (465, 355, 12, 12),
        ],
    )

    assert flow._native_snapshot_has_loading_spinner(snapshot) is True


def test_native_loading_spinner_detector_ignores_scattered_editor_blue_controls(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    snapshot = _native_snapshot(
        1000,
        800,
        [
            (330, 170, 90, 26),
            (600, 230, 120, 28),
            (430, 320, 80, 80),
            (530, 430, 90, 80),
            (360, 560, 160, 30),
            (650, 620, 120, 26),
        ],
    )

    assert flow._native_snapshot_has_loading_spinner(snapshot) is False


def test_native_loading_spinner_detector_accepts_spinner_with_scattered_blue_controls(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    snapshot = _native_snapshot(
        1200,
        900,
        [
            # Real DXM edit pages contain unrelated blue controls across the page.
            (330, 170, 90, 26),
            (760, 250, 110, 30),
            (950, 300, 80, 28),
            (1080, 560, 120, 30),
            # The loading mark itself is a group of small blue dots/letters.
            (585, 420, 8, 8),
            (615, 400, 8, 8),
            (650, 395, 8, 8),
            (685, 410, 8, 8),
            (705, 445, 8, 8),
            (695, 480, 8, 8),
            (665, 505, 8, 8),
            (625, 505, 8, 8),
            (595, 480, 8, 8),
            (575, 450, 8, 8),
            (610, 455, 44, 8),
        ],
    )

    assert flow._native_snapshot_has_loading_spinner(snapshot) is True


def test_visible_editor_ready_state_blocks_when_devtools_times_out_without_field_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummySemiPage({})
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_evaluate_page_function_with_runtime_timeout',
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('独立 DevTools 调用超时。')),
    )
    monkeypatch.setattr(
        flow,
        '_visible_editor_native_loading_state',
        lambda _page: {
            'loading': False,
            'reason': '原生窗口未检测到加载动画',
            'source': 'native_snapshot',
        },
    )

    state = flow._visible_editor_ready_state(page, product_query='宝可梦')

    assert state['ready'] is False
    assert state['source'] == 'native_snapshot'
    assert state['dom_error'] == '独立 DevTools 调用超时。'
    assert state['reason'] == '无法确认编辑页关键字段已加载'


def test_visible_editor_category_selection_reports_control_channel_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_editor_required_defaults_state',
        lambda _page, **_kwargs: {
            'missing': ['editor_state_probe'],
            'values': {},
            'category_selected': False,
            'category_text': '',
        },
    )
    monkeypatch.setattr(flow, '_dismiss_blocking_modals_if_visible', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(flow, '_wait_for_body_text', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('独立 DevTools 调用超时。')),
    )

    result = flow._select_editor_category(page, keyword='立牌', match_text='ACG Stand')

    assert result['ok'] is False
    assert '真实浏览器控制通道暂时不可用' in result['reason']
    assert any(event['event'] == 'select_editor_category:scroll_top_failed' for event in flow.recent_workflow_events())


def test_visible_editor_category_failure_does_not_take_blocking_screenshot(monkeypatch, tmp_path):
    class VisibleEditorPage(DummyOpenSemiPage):
        def title(self):
            raise AssertionError('visible category failure must not read title through Playwright')

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError('visible category failure must not take blocking screenshot')

    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = VisibleEditorPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': False,
            'reason': '真实浏览器控制通道暂时不可用，未能定位产品分类按钮；请重启执行浏览器后重试。',
        },
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(),
    )

    assert result['stage'] == 'fill_editor_required_defaults_failed'
    assert result['page_title'] == '店小秘编辑页'
    assert result['screenshot_url'] is None
    assert '真实浏览器控制通道暂时不可用' in result['message']


def test_visible_editor_fill_defaults_reuses_editor_state_when_title_present(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    editor_state = {
        'missing': ['english_title', 'declared_value', 'delivery_days'],
        'values': {'title': 'Pokemon Poke Ball 3D Printed Display Toy'},
        'category_selected': True,
        'category_text': '产品分类立牌类谷子(ACGStand)选择分类自动识别分类',
    }
    validation_state = _complete_editor_defaults_state(
        title='Pokemon Poke Ball 3D Printed Display Toy',
        category_text=editor_state['category_text'],
    )
    state_reads = []

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': True,
            'already_selected': True,
            'text': editor_state['category_text'],
            'editor_state': editor_state,
        },
    )
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda *args, **kwargs: _applied_attribute_reference_template())
    monkeypatch.setattr(flow, '_missing_required_reference_template_results', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True, 'text': text})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: 'Pokemon Poke Ball 3D Printed Display Toy')
    monkeypatch.setattr(
        flow,
        '_visible_editor_text_input_state',
        lambda _page, label: {
            'ok': label in {'商品编码', '发货期限'},
            'value': {'商品编码': 'SKU-001', '发货期限': '7'}.get(label, ''),
        },
    )

    def fake_editor_state(_page, **_kwargs):
        state_reads.append(True)
        return validation_state

    monkeypatch.setattr(flow, '_editor_required_defaults_state', fake_editor_state)
    monkeypatch.setattr(
        flow,
        '_fill_visible_editor_title_with_native_input',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('title already present in editor state must not be rewritten')
        ),
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            title_override='中文商品标题',
            category_match=editor_state['category_text'],
        ),
    )

    assert result['stage'] == 'editor_required_defaults_filled'
    assert result['fill_result']['fields']['title'] is True
    assert result['fill_result']['fields']['title_strategy'] == 'preserve_existing_visible_editor_state'
    assert state_reads == [True]


def test_visible_editor_fill_defaults_blocks_chinese_title_without_template_strategy(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    editor_state = {
        'missing': ['english_title', 'declared_value', 'delivery_days'],
        'values': {'title': '宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值'},
        'category_selected': True,
        'category_text': '产品分类立牌类谷子(ACGStand)选择分类自动识别分类',
    }

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': True,
            'already_selected': True,
            'text': editor_state['category_text'],
            'editor_state': editor_state,
        },
    )
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda *args, **kwargs: {})
    monkeypatch.setattr(flow, '_missing_required_reference_template_results', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        flow,
        '_fill_visible_editor_title_with_native_input',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('Chinese title must not be rewritten without a template title strategy')
        ),
    )
    monkeypatch.setattr(
        flow,
        '_fill_packaging_info',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('packaging must not run before title template is resolved')
        ),
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            title_override='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
            category_match=editor_state['category_text'],
        ),
    )

    assert result['stage'] == 'fill_editor_required_defaults_failed'
    assert result['label'] == '标题模板未就绪'
    assert result['fill_result']['missing'] == ['category.title_strategy']


def test_visible_editor_fill_defaults_applies_source_title_template_strategy(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    filled_titles = []

    editor_state = {
        'missing': ['english_title', 'declared_value', 'delivery_days'],
        'values': {'title': '宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值'},
        'category_selected': True,
        'category_text': '产品分类立牌类谷子(ACGStand)选择分类自动识别分类',
    }
    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': True,
            'already_selected': True,
            'text': editor_state['category_text'],
            'editor_state': editor_state,
        },
    )
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda *args, **kwargs: _applied_attribute_reference_template())
    monkeypatch.setattr(flow, '_missing_required_reference_template_results', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *_args, **_kwargs: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_visible_editor_existing_title_value',
        lambda _page: filled_titles[-1][0] if filled_titles else '',
    )
    monkeypatch.setattr(
        flow,
        '_visible_editor_text_input_state',
        lambda _page, label: {
            'ok': label in {'商品编码', '发货期限'},
            'value': {'商品编码': 'SKU-001', '发货期限': '7'}.get(label, ''),
        },
    )
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True, 'text': text})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(
        flow,
        '_editor_required_defaults_state',
        lambda _page, **_kwargs: _complete_editor_defaults_state(
            title=filled_titles[-1][0],
            category_text=editor_state['category_text'],
        ),
    )
    monkeypatch.setattr(
        flow,
        '_fill_visible_editor_title_with_native_input',
        lambda _page, title, **kwargs: filled_titles.append((title, kwargs)) or {'ok': True, 'method': 'native_coordinate_clipboard'},
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            title_override='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
            title_strategy='按来源标题生成英文标题',
            source_title='宝可梦精灵球玩具模型周边礼物3D打印球体摆件神奇宝贝高颜值',
            category_match=editor_state['category_text'],
        ),
    )

    assert result['stage'] == 'editor_required_defaults_filled'
    assert result['fill_result']['fields']['title'] is True
    assert result['fill_result']['fields']['title_strategy'] == 'template_source_title_english'
    assert filled_titles[0][0] == 'ACGStand Collectible Product'
    assert flow._is_safe_english_title(filled_titles[0][0]) is True
    assert filled_titles[0][1]['force_replace'] is True


def test_visible_editor_fill_defaults_blocks_invalid_goods_code_without_template_strategy(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    editor_state = {
        'missing': ['declared_value', 'delivery_days'],
        'values': {'title': 'Pokemon Poke Ball 3D Printed Display Toy'},
        'category_selected': True,
        'category_text': '产品分类立牌类谷子(ACGStand)选择分类自动识别分类',
    }

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': True,
            'already_selected': True,
            'text': editor_state['category_text'],
            'editor_state': editor_state,
        },
    )
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda *args, **kwargs: {})
    monkeypatch.setattr(flow, '_missing_required_reference_template_results', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(flow, '_visible_editor_text_input_state', lambda _page, label: {'ok': True, 'value': '893543996663-仙子伊布'} if label == '商品编码' else {'ok': False})
    monkeypatch.setattr(
        flow,
        '_fill_text_inputs_near_label',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('invalid goods code must not be rewritten without an explicit template strategy')
        ),
    )
    monkeypatch.setattr(
        flow,
        '_fill_packaging_info',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('packaging must not run before goods code template is resolved')
        ),
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            sku_code='893543996663-仙子伊布',
            category_match=editor_state['category_text'],
        ),
    )

    assert result['stage'] == 'fill_editor_required_defaults_failed'
    assert result['label'] == '商品编码模板未就绪'
    assert result['fill_result']['missing'] == ['sku.goods_code_strategy']


def test_visible_editor_fill_defaults_applies_template_goods_code_strategy(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    page = DummyOpenSemiPage()
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'
    filled = []

    editor_state = {
        'missing': ['declared_value', 'delivery_days'],
        'values': {'title': 'Pokemon Poke Ball 3D Printed Display Toy'},
        'category_selected': True,
        'category_text': '产品分类立牌类谷子(ACGStand)选择分类自动识别分类',
    }
    validation_state = _complete_editor_defaults_state(
        title='Pokemon Poke Ball 3D Printed Display Toy',
        sku_code='893543996663',
        category_text=editor_state['category_text'],
    )

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)
    monkeypatch.setattr(
        flow,
        '_select_editor_category',
        lambda *_args, **_kwargs: {
            'ok': True,
            'already_selected': True,
            'text': editor_state['category_text'],
            'editor_state': editor_state,
        },
    )
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda *args, **kwargs: _applied_attribute_reference_template())
    monkeypatch.setattr(flow, '_missing_required_reference_template_results', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(flow, '_visible_editor_existing_title_value', lambda _page: 'Pokemon Poke Ball 3D Printed Display Toy')

    def visible_text_state(_page, label):
        if label == '商品编码':
            return {'ok': True, 'value': '893543996663' if filled else '893543996663-仙子伊布'}
        if label == '发货期限':
            return {'ok': True, 'value': '7'}
        return {'ok': False, 'value': ''}

    def fill_text(_page, label, values):
        if label == '商品编码':
            filled.append((label, values))
        return {'ok': True, 'filled': values}

    monkeypatch.setattr(flow, '_visible_editor_text_input_state', visible_text_state)
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', fill_text)
    monkeypatch.setattr(flow, '_fill_packaging_info', lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(flow, '_choose_ant_select_near_label', lambda page, label, names: {'ok': True, 'text': names[0] if names else label})
    monkeypatch.setattr(flow, '_check_choice_by_text', lambda page, text: {'ok': True, 'text': text})
    monkeypatch.setattr(flow, '_fill_customs_supervision_attribute', lambda page, names: {'ok': True})
    monkeypatch.setattr(flow, '_editor_required_defaults_state', lambda _page, **_kwargs: validation_state)
    monkeypatch.setattr(
        flow,
        '_fill_visible_editor_title_with_native_input',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('title already present in editor state must not be rewritten')
        ),
    )

    result = flow._fill_editor_required_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(
            sku_code='893543996663-仙子伊布',
            goods_code_strategy='按来源商品ID生成安全货号',
            source_urls=['https://mobile.yangkeduo.com/goods.html?goods_id=893543996663'],
            category_match=editor_state['category_text'],
        ),
    )

    assert result['stage'] == 'editor_required_defaults_filled'
    assert result['fill_result']['fields']['sku_code'] is True
    assert result['fill_result']['fields']['sku_code_strategy'] == 'template_source_goods_id'
    assert filled == [('商品编码', ['893543996663'])]


def test_dxm_goods_code_sanitizer_removes_chinese_suffix(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    assert flow._safe_dxm_goods_code('893543996663-仙子伊布', fallback='610274761685-DK-AD-10CM') == '893543996663'
    assert flow._safe_dxm_goods_code('  SKU_123.45-A ', fallback='') == 'SKU_123.45-A'


def test_visible_editor_text_input_fills_labeled_ant_container(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    html = '''
    <html><body>
      <style>
        .ant-form-item { width: 520px; height: 96px; }
        input { width: 280px; height: 32px; }
      </style>
      <div class="ant-form-item ant-form-item-has-error">
        <label>商品编码</label>
        <div class="ant-form-item-control">
          <input class="ant-input ant-input-status-error" value="893543996663-仙子伊布" />
        </div>
        <div class="ant-form-item-explain">商品编码必须为50个字符以内的数字、英文及部分特殊字符！</div>
      </div>
    </body></html>
    '''

    monkeypatch.setattr(flow, '_is_visible_dxm_editor_page', lambda _page: True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html)

            result = flow._fill_text_inputs_near_label(page, '商品编码', ['893543996663'])
            value = page.locator('input').first.input_value()
        finally:
            browser.close()

    assert result['ok'] is True
    assert result['method'] == 'visible_labeled_container'
    assert value == '893543996663'


def test_visible_editor_fill_defaults_fails_fast_when_required_text_fields_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(dxm_login_flow_module.os, 'name', 'nt', raising=False)
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    events = []
    page = DummySemiPage({})
    page.url = 'https://www.dianxiaomi.com/web/smt/edit?id=130658341347985374'

    monkeypatch.setattr(flow, '_is_headless', lambda: False)
    monkeypatch.setattr(flow, '_trace_workflow_event', lambda event, **payload: events.append((event, payload)))
    monkeypatch.setattr(flow, '_select_editor_category', lambda *args, **kwargs: {'ok': True, 'text': 'Action Figures', 'category_text': 'Action Figures'})
    monkeypatch.setattr(flow, '_dismiss_editor_modals', lambda *args, **kwargs: 0)
    monkeypatch.setattr(flow, '_apply_dxm_reference_templates_on_page', lambda page, values: {})
    monkeypatch.setattr(flow, '_fill_visible_editor_title_with_native_input', lambda *args, **kwargs: {'ok': False, 'reason': 'not found'})
    monkeypatch.setattr(flow, '_fill_text_inputs_near_label', lambda *args, **kwargs: {'ok': False, 'reason': 'not found'})
    monkeypatch.setattr(flow, '_visible_editor_text_input_state', lambda _page, label: {'ok': True, 'value': 'SKU-OK'} if label == '商品编码' else {'ok': False})
    monkeypatch.setattr(
        flow,
        '_fill_packaging_info',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('packaging must not run when required text fields are missing')),
    )
    monkeypatch.setattr(flow, '_safe_live_hud_page_title', lambda page: '店小秘编辑页')

    state = flow._fill_editor_required_defaults_on_page(page, _legacy_explicit_editor_defaults(title_override='Pokemon Poke Ball Toy Model'))

    assert state['stage'] == 'fill_editor_required_defaults_failed'
    assert state['fill_result']['missing'] == ['title', 'delivery_days']
    assert events[-1][0] == 'editor_base_fields:required_text_failed'


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

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_semi_original_box', lambda page, value: {
        'ok': True,
        'located': True,
        'expected_value': value,
        'value_after': value,
    })
    monkeypatch.setattr(flow, '_fill_semi_logistics_attribute', lambda page, value: {
        'ok': True,
        'located': True,
        'expected_value': value,
        'value_after': value,
    })
    monkeypatch.setattr(
        flow,
        '_capture_save_field_integrity_snapshot',
        lambda _page: {
            'ok': True,
            'kind': 'structured_nonempty_form_state',
            'field_count': 10,
            'nonempty_field_count': 10,
            'sha256': 'B' * 64,
        },
    )

    state = flow._fill_semi_managed_defaults_on_page(
        page,
        _legacy_explicit_editor_defaults(jit_stock='100', supply_price='48.62'),
    )

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['field_details']['jit_stock']['value_after'] == '100'
    assert 'expected_value' in page.script
    assert page.values['stock'] == '100'
    assert page.values['supply_price'] == '48.62'
    assert 'headerCandidates' in page.script
    assert 'tableInputsByHeader' in page.script
    assert 'table_column' in page.script
    assert 'field_details' in page.script
    assert 'Object.getOwnPropertyDescriptor' in page.script


def test_fill_editor_variants_rejects_missing_structured_logistics_control(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEditorVariantsLogisticsOnlyPage()
    state = flow._fill_editor_variants_on_page(page, _legacy_explicit_editor_defaults())

    assert state['stage'] == 'fill_editor_variants_failed'
    assert state['fill_result']['missing'] == ['logistics_attribute']
    assert state['fill_result']['logistics_attribute_detail'] == {
        'ok': False,
        'write_attempted': False,
        'reason': 'structured_variant_logistics_control_required',
    }
    assert state['published'] is None


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
    monkeypatch.setattr(
        flow,
        '_verify_editor_variant_logistics_attribute',
        lambda _page, value: {
            'ok': True,
            'located': True,
            'expected_value': value,
            'value_after': value,
            'row_count': 6,
            'filled_count': 6,
            'missing_rows': [],
        },
    )

    state = flow._fill_editor_variants_on_page(page, _legacy_explicit_editor_defaults(logistics_attribute='普货'))

    assert state['stage'] == 'editor_variants_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['logistics_attribute_detail']['icon_count'] == 6
    assert calls == [(page, '普货')]


def test_fill_editor_variants_writes_configured_safe_custom_names_before_save(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEditorVariantsCustomNamesPage()

    configured_names = ['5CM Acrylic', '6CM Acrylic', '8CM Acrylic', '10CM Acrylic', '12CM Acrylic']
    state = flow._fill_editor_variants_on_page(
        page,
        _legacy_explicit_editor_defaults(variant_custom_names=configured_names),
    )

    custom_names = state['fill_result']['variant_custom_names']['values']
    assert state['stage'] == 'editor_variants_filled'
    assert state['fill_result']['missing'] == []
    assert custom_names[0]['before'] == '5CM亚克力立牌 记得撕膜 '
    assert custom_names[0]['expected_value'] == '5CM Acrylic'
    assert custom_names[0]['value_after'] == '5CM Acrylic'
    assert all(item['ok'] for item in custom_names)
    assert [item['value_after'] for item in custom_names] == configured_names
    assert all(len(item['value_after']) <= 20 for item in custom_names)
    assert all(not re.search(r'[\u4e00-\u9fff]', item['value_after']) for item in custom_names)
    assert state['fill_result']['variant_original_box']['filled'] == 5


def test_category_attribute_priorities_do_not_invent_unfrozen_defaults(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    assert flow._category_attribute_priorities('材质(Material)') == []
    assert flow._category_attribute_priorities('是否带电(Is Electric)') == []
    assert flow._category_attribute_priorities('系列(Mfg Series Number)') == []
    assert flow._category_attribute_priorities('动漫电影游戏名称(ACG Name)') == []


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
    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_fill_semi_original_box', lambda page, value: {
        'ok': True,
        'located': True,
        'expected_value': value,
        'value_after': value,
    })
    monkeypatch.setattr(flow, '_fill_semi_logistics_attribute', lambda page, value: {
        'ok': True,
        'located': True,
        'expected_value': value,
        'value_after': value,
    })

    html = '''
    <html>
      <body>
        <div class="ant-form-item">
          <label>运费模板</label>
          <div class="ant-select-selection-item">40g普货包裹</div>
        </div>
        <div class="ant-form-item">
          <label>服务模板</label>
          <div class="ant-select-selection-item">Service Template for New Sellers</div>
        </div>
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
                <tr><th>sku图片</th><th>*产品价格（CNY）</th><th>供应价</th><th>SKU编码</th><th>* JIT库存</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><img alt="" /></td>
                  <td><input data-field="productPrice" value="48.62" /></td>
                  <td><input data-field="supplyPrice" value="48.62" /></td>
                  <td><input data-field="skuCode" placeholder="SKU编码" value="" /></td>
                  <td><input data-field="jitStock" value="0" /></td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>
      </body>
    </html>
    '''

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f'Playwright browser unavailable: {exc}')
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.set_content(html)
            state = flow._fill_semi_managed_defaults_on_page(
                page,
                _legacy_explicit_editor_defaults(
                    jit_stock='100',
                    product_price='49.00',
                    supply_price='48.62',
                ),
            )
            values = page.evaluate('''() => Object.fromEntries(
              Array.from(document.querySelectorAll('[data-field]')).map(el => [el.dataset.field, el.value])
            )''')
        finally:
            browser.close()

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['field_details']['jit_stock']['value_before'] == '0'
    assert state['fill_result']['field_details']['jit_stock']['value_after'] == '100'
    assert values == {
        'weight': '0.03',
        'length': '10',
        'width': '10',
        'height': '2',
        'productPrice': '49.00',
        'supplyPrice': '48.62',
        'skuCode': 'SKU-001',
        'jitStock': '100',
    }


def test_fill_semi_managed_defaults_accepts_retail_price_and_original_box_select(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._is_headless = lambda: True
    html = '''
        <html>
          <body>
            <div class="ant-form-item">
              <label>运费模板</label>
              <div class="ant-select-selection-item">40g普货包裹</div>
            </div>
            <div class="ant-form-item">
              <label>服务模板</label>
              <div class="ant-select-selection-item">Service Template for New Sellers</div>
            </div>
            <table>
              <thead>
                <tr>
                  <th>颜色</th><th>产品价格(CNY)</th><th>供应价</th><th>JIT库存</th><th>SKU编码</th>
                  <th>重量(kg)</th><th>包装尺寸(cm)</th><th>是否原箱</th><th>物流属性</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>白色</td>
                  <td><input data-field="productPrice" placeholder="产品价格" value="58.82" /></td>
                  <td><input data-field="supplyPrice" placeholder="供应价" value="48.62" /></td>
                  <td><input data-field="jitStock" placeholder="JIT库存" value="99" /></td>
                  <td><input data-field="skuCode" placeholder="SKU编码" value="SKU-001" /></td>
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
                _legacy_explicit_editor_defaults(
                    jit_stock='100',
                    product_price='49.00',
                    is_original_box='否',
                ),
            )
            values = page.evaluate('''() => Object.fromEntries(
              Array.from(document.querySelectorAll('[data-field]')).map(el => [el.dataset.field, el.value])
            )''')
        finally:
            browser.close()

    assert state['stage'] == 'semi_managed_defaults_filled'
    assert state['fill_result']['missing'] == []
    assert state['fill_result']['original_box']['ok'] is True
    assert values['productPrice'] == '49.00'
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


def test_fill_media_assets_fails_closed_when_eu_picker_is_unavailable(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    flow._is_headless = lambda: True
    page = DummyMediaNoEntryPage()

    state = flow._fill_media_assets_on_page(page, _legacy_explicit_editor_defaults(eu_outer_package_filename='微信图片_202504092228421.jpg'))

    assert state['stage'] == 'fill_media_assets_failed'
    assert state['published'] is None
    assert state['message'] == '欧盟外包装图槽位没有可点击的图片选择入口'
    eu_result = state['fill_result']['eu_outer_package_image']
    assert eu_result['ok'] is False
    assert eu_result['reason'] == '欧盟外包装图槽位没有可点击的图片选择入口'
    assert eu_result['verified'] == {'ok': False, 'reason': '欧盟外包装图槽位仍为空'}
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

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
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


def test_fill_customs_supervision_selects_exact_product_name_after_frozen_kind(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyCustomsPage()

    monkeypatch.setattr(
        flow,
        '_click_ant_option_near_rect',
        lambda page, priorities, anchor_rect, required=True: {'ok': True, 'text': '钥匙扣(keychain)'},
    )

    state = flow._fill_customs_supervision_attribute(page, ['钥匙扣(keychain)'])

    assert state['ok'] is True
    assert state['selected'] == '钥匙扣(keychain)'
    assert state['confirm_steps'] == 3
    assert page.waited_for_function is True
    assert page.keyboard.presses == []
    assert len(page.mouse.clicks) == 5


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


def test_fill_customs_supervision_rejects_existing_product_name_outside_frozen_priorities(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    page = DummyEnglishCustomsUpdatePage()

    state = flow._fill_customs_supervision_attribute(page, ['钥匙扣', 'keychain'])

    assert state['ok'] is False
    assert state['already_configured'] is True
    assert state['exact_readback'] is False
    assert state['reason'] == 'customs_product_name_readback_mismatch'
    assert state['write_attempted'] is False
    assert page.mouse.clicks == []
    assert page.timeouts == []


def test_save_only_rejects_publish_buttons(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySemiPage({'ok': False, 'reason': '命中发布按钮：保存并发布', 'published': False})

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert state['published'] is None
    assert '保存并发布' in state['message']


def test_save_only_dismisses_blocking_modals_before_locating_save(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    calls = []

    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: calls.append('dismiss') or 1)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['network_save_result']['ok'] is True
    assert state['save_result']['page_save_result']['ok'] is False
    assert calls == ['dismiss']
    assert page.evaluate_calls == 1
    assert page.snapshot_calls == 2


@pytest.mark.parametrize(
    ('baseline_entries', 'current_entries', 'expected_stage', 'expected_reason'),
    [
        ([], [], 'save_only_failed', 'structured_save_success_missing'),
        (
            [{'id': 'old-toast', 'text': '已保存', 'status': '', 'source': 'role-status'}],
            [{'id': 'old-toast', 'text': '已保存', 'status': '', 'source': 'role-status'}],
            'save_only_failed',
            'stale_save_success_status',
        ),
        (
            [],
            [{'id': 'new-toast', 'text': '产品编辑成功', 'status': '', 'source': 'ant-notification-notice'}],
            'save_only',
            None,
        ),
    ],
    ids=['body-text-only', 'unchanged-old-toast', 'new-toast'],
)
def test_other_save_only_requires_new_structured_status_transition(
    monkeypatch,
    tmp_path,
    baseline_entries,
    current_entries,
    expected_stage,
    expected_reason,
):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)

    class StructuredSavePage:
        url = 'https://www.dianxiaomi.com/web/smt/edit?id=123'

        def __init__(self):
            self.snapshot_calls = 0
            self.action_calls = 0

        def evaluate(self, script, arg=None):
            if _is_dismiss_blocking_modals_script(script):
                return {'visible': False}
            if _is_visible_blocking_modal_state_script(script):
                return {'visible': False}
            if '__DXM_STRUCTURED_SAVE_STATUS_SNAPSHOT__' in script:
                entries = baseline_entries if self.snapshot_calls == 0 else current_entries
                self.snapshot_calls += 1
                return {'ok': True, 'entries': entries}
            self.action_calls += 1
            if self.action_calls == 1:
                return {
                    'ok': True,
                    'rect': {'x': 10, 'y': 20, 'w': 30, 'h': 40},
                    'message': '已定位保存按钮',
                    'published': False,
                }
            return {'ok': True, 'success_text': '已保存', 'published': False}

        def wait_for_timeout(self, _timeout):
            return None

        def title(self):
            return '店小秘编辑页'

    page = StructuredSavePage()
    monkeypatch.setattr(flow, '_is_headless', lambda: True)
    monkeypatch.setattr(flow, '_click_exact_save_button', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow, '_capture_save_network_events', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, '_finalize_save_network_audit', lambda *_args: _complete_save_network_capture())
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {'ok': True, 'method': 'POST', 'code': 0})

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == expected_stage
    assert state['save_result']['page_save_result'].get('reason') == expected_reason
    assert state['save_result']['network_save_result']['ok'] is True


def test_save_only_stops_when_blocking_modal_remains_after_dismiss(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    flow._last_dismiss_blocking_modals_trace = [{'clicked': 'modal-close'}]

    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda target_page: 10)
    monkeypatch.setattr(
        flow,
        '_visible_blocking_modal_state',
        lambda target_page: {'visible': True, 'text': '距离活动结束仅剩 我知道了'},
    )

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert page.clicks == []
    assert state['save_result']['reason'] == '保存前弹窗未能关闭'
    assert state['save_result']['blocking_modal']['visible'] is True


def test_save_only_script_checks_publish_risk_before_clicking_save(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyScriptPage()

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    for word in ['发布', '立即发布', '继续发布', '保存并发布', '确认发布', '提交发布', '保存并移入待发布', '移入待发布']:
        assert word in page.script
    assert "querySelectorAll('button,a,[role=\"button\"]')" in page.script


def test_save_only_script_prioritizes_exact_save_button_when_publish_button_is_visible(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyScriptPage()

    flow._save_only_on_page(page, **_save_only_kwargs())

    assert page.script.index("const exactSaves = candidates.filter") < page.script.index("const forbidden = candidates.find")


def test_click_exact_save_button_ignores_save_and_move_to_publish(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(
            '''
            <button onclick="window.clicked='move'">保存并移入待发布</button>
            <button onclick="window.clicked='save'">保存</button>
            <button onclick="window.clicked='publish'">发布</button>
            '''
        )

        clicked = flow._click_exact_save_button(page)
        value = page.evaluate('window.clicked')
        browser.close()

    assert clicked is True
    assert value == 'save'


def test_save_only_fails_when_success_prompt_missing_after_click(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': False,
        'clicked': True,
        'reason': '未检测到保存成功提示',
        'success_text': None,
        'published': False,
    })

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert page.evaluate_calls == 1
    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['ok'] is False
    assert 'structured_save_success_missing' in state['message']


def test_save_only_fails_when_page_success_has_no_network_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': True,
        'clicked': True,
        'success_text': '产品编辑成功',
        'published': False,
    })

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert page.evaluate_calls == 1
    assert state['stage'] == 'save_only_failed'
    assert state['save_result']['ok'] is False
    assert state['save_result']['page_save_result']['ok'] is True
    assert state['save_result']['network_events'] == []
    assert state['save_result']['network_save_result'] == {
        'ok': False,
        'reason': '未捕获唯一保存接口请求',
        'receipt_count': 0,
        'receipt_complete': False,
    }


def test_save_only_succeeds_only_when_page_and_network_both_succeed(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyVerifyPage({
        'ok': True,
        'clicked': True,
        'success_text': '产品编辑成功',
        'published': False,
    })
    monkeypatch.setattr(flow, '_network_save_result', lambda _events: {
        'ok': True,
        'message': '您的产品编辑成功！',
        'method': 'POST',
        'code': 0,
    })
    monkeypatch.setattr(flow, '_save_network_audit_complete', lambda *_args: True)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only'
    assert state['save_result']['ok'] is True
    assert state['save_result']['page_save_result']['ok'] is True
    assert state['save_result']['network_save_result']['ok'] is True


def test_save_only_rejects_network_success_without_page_success(monkeypatch, tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    _arm_editor_action_test(flow, monkeypatch, tmp_path)
    page = DummySaveOnlyNetworkPage()
    monkeypatch.setattr(flow, '_click_point_with_native_window', lambda page, x, y, **_kwargs: False)
    monkeypatch.setattr(flow, '_click_point_with_cdp', lambda page, x, y, **_kwargs: False)

    state = flow._save_only_on_page(page, **_save_only_kwargs())

    assert state['stage'] == 'save_only_failed'
    assert page.clicks == []
    assert state['save_result']['ok'] is False
    assert state['save_result']['save_click_dispatched'] is True
    assert state['save_result']['page_save_success'] is False
    assert state['save_result']['network_save_success'] is True
    assert state['published'] is None


def test_dismiss_blocking_modals_if_visible_skips_heavy_scan_when_no_modal(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: {'visible': False},
    )
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('heavy modal scan must be skipped')),
    )

    dismissed = flow._dismiss_blocking_modals_if_visible(FakePage(), context='test')

    assert dismissed == 0
    assert flow.recent_workflow_events()[-1]['event'] == 'blocking_modal_check:none'


def test_dismiss_blocking_modals_if_visible_skips_script_probe_for_visible_browser(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADED', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible browser must not run script probe')),
    )
    monkeypatch.setattr(
        flow,
        '_dismiss_blocking_modals',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('visible browser must not run heavy modal scan')),
    )

    dismissed = flow._dismiss_blocking_modals_if_visible(FakePage(), context='test')

    assert dismissed == 0
    assert flow.recent_workflow_events()[-1]['event'] == 'blocking_modal_check:skipped_visible_browser'


def test_dismiss_blocking_modals_if_visible_uses_heavy_scan_for_real_modal(monkeypatch, tmp_path):
    monkeypatch.setenv('DXM_LOGIN_HEADLESS', '1')
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')
    calls = []

    class FakePage:
        url = 'https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0'

    monkeypatch.setattr(
        flow,
        '_evaluate_zero_arg_page_function_with_runtime_timeout',
        lambda *_args, **_kwargs: {'visible': True, 'text': '系统公告 知道了'},
    )
    monkeypatch.setattr(flow, '_dismiss_blocking_modals', lambda _page: calls.append('dismiss') or 1)

    dismissed = flow._dismiss_blocking_modals_if_visible(FakePage(), context='test')

    assert dismissed == 1
    assert calls == ['dismiss']
    assert flow.recent_workflow_events()[-1]['event'] == 'blocking_modal_check:dismissed'


def test_network_save_result_prefers_real_add_json_over_related_history_calls(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._network_save_result([
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/addProductBrandHistory.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'mutation_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': 123},
        },
    ])

    assert result['ok'] is True
    assert result['url'] == 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    assert result['msg'] == '您的产品编辑成功！'


def test_network_save_result_requires_post_2xx_for_real_smt_add_json(tmp_path):
    live_client = DummyLiveClient(logged_in=True)
    flow = DxmLoginFlow(live_client, state_file=tmp_path / 'runtime.json')

    result = flow._network_save_result([
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'GET',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 200,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
        {
            'url': 'https://www.dianxiaomi.com/api/smtProduct/add.json',
            'method': 'POST',
            'request_observed': True,
            'mutation_kind': 'save_request',
            'status': 500,
            'json': {'code': 0, 'msg': 'Successful', 'data': {'msg': '您的产品编辑成功！', 'code': 0}},
        },
    ])

    assert result['ok'] is False
    assert result['url'] == 'https://www.dianxiaomi.com/api/smtProduct/add.json'
    assert result['code'] == 0


def test_browser_session_generation_tracks_actual_context_lifecycle(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FakeBrowser:
        def __init__(self):
            self.connected = True
            self.callbacks = {}

        def is_connected(self):
            return self.connected

        def on(self, event, callback):
            self.callbacks[event] = callback

        def disconnect(self):
            self.connected = False
            self.callbacks['disconnected']()

    class FakeContext:
        def __init__(self):
            self.closed = False
            self.callbacks = {}

        def is_closed(self):
            return self.closed

        def on(self, event, callback):
            self.callbacks[event] = callback

        def close(self):
            self.closed = True
            self.callbacks['close']()

    browser = FakeBrowser()
    first_context = FakeContext()
    flow._browser = browser
    flow._context = first_context

    assert flow.browser_session_id() is None
    first_generation = flow._bind_browser_context_generation(first_context)
    assert flow.browser_session_id() == first_generation
    assert flow._bind_browser_context_generation(first_context) == first_generation

    first_context.close()
    assert flow.browser_session_id() is None

    second_context = FakeContext()
    flow._context = second_context
    second_generation = flow._bind_browser_context_generation(second_context)
    assert second_generation != first_generation
    assert flow.browser_session_id() == second_generation

    browser.disconnect()
    assert flow.browser_session_id() is None


def test_browser_session_id_is_cross_thread_read_only_and_never_probes_playwright(tmp_path):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FakeBrowser:
        allow_probe = True

        def is_connected(self):
            if not self.allow_probe:
                raise AssertionError('browser_session_id must not call browser.is_connected')
            return True

        def on(self, *_args):
            return None

    class FakeContext:
        allow_probe = True

        def is_closed(self):
            if not self.allow_probe:
                raise AssertionError('browser_session_id must not call context.is_closed')
            return False

        def on(self, *_args):
            return None

    browser = FakeBrowser()
    context = FakeContext()
    flow._browser = browser
    flow._context = context
    generation = flow._bind_browser_context_generation(context)
    assert flow.browser_session_id() == generation

    browser.allow_probe = False
    context.allow_probe = False
    results = []
    errors = []

    def read_from_api_thread():
        try:
            results.append(flow.browser_session_id())
        except Exception as exc:  # noqa: BLE001 - regression captures any cross-thread probe.
            errors.append(exc)

    thread = threading.Thread(target=read_from_api_thread)
    thread.start()
    thread.join(timeout=5)

    assert errors == []
    assert results == [generation]
    assert flow._browser_session_context_id == id(context)
    assert flow._browser_session_browser_id == id(browser)


@pytest.mark.parametrize('invalid_part', ['browser', 'context'])
def test_bind_browser_context_generation_rejects_inactive_objects(tmp_path, invalid_part):
    flow = DxmLoginFlow(DummyLiveClient(logged_in=True), state_file=tmp_path / 'runtime.json')

    class FakeBrowser:
        connected = invalid_part != 'browser'

        def is_connected(self):
            return self.connected

        def on(self, *_args):
            return None

    class FakeContext:
        closed = invalid_part == 'context'

        def is_closed(self):
            return self.closed

        def on(self, *_args):
            return None

    flow._browser = FakeBrowser()
    flow._context = FakeContext()

    with pytest.raises(RuntimeError, match='BROWSER_SESSION_OBJECT_INACTIVE'):
        flow._bind_browser_context_generation(flow._context)

    assert flow.browser_session_id() is None
