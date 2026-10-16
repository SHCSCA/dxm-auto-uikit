"""隔离执行真实只读 Flow 方法；页面、网络和静态捕获均为零外部动作替身。"""

import hashlib
from copy import deepcopy
from types import SimpleNamespace

from src.execution import dxm_login_flow as flow_module
from src.execution import editor_readonly_inspection as inspection
from src.execution import native_video_diagnostic as diagnostic_module
from src.execution import native_video_script_capture as capture_module
from src.services.dxm_plan_reader import DxmPlanReader
from tests.support.editor_inspection_flow_spy import install_inspection_spies


def readonly_flow_case(monkeypatch, tmp_path, fault=None, blocked_requests=0):
    events, captures = [], []
    form = [{'field': 'synthetic', 'value': 'private-form-value'}]
    envelope = {'synthetic_reader': True}
    diagnostic = {'schema': 'dxm.native_video_input_diagnostic.v1',
        'double_read_completed': True, 'stable_across_screenshot': True,
        'default_provenance': 'not_bound_to_native_reveal', 'limitations': ['TEST_NOT_PRODUCTION'],
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
        'before': {'actual': 'private-video-before'}, 'after': {'actual': 'private-video-after'}}

    class Locator:
        def __init__(self, page, kind):
            self.page, self.kind = page, kind

        def count(self):
            if self.kind == 'existing':
                return 0
            return 2 if fault == 'ambiguous' and self.kind == 'entry' else 1

        def is_visible(self):
            return True

        def is_enabled(self):
            return True

        def locator(self, selector):
            assert selector == 'button' and self.kind == 'entry'
            return self

        def filter(self, **kwargs):
            assert kwargs['has_text'].fullmatch('图片生成视频') or kwargs['has_text'].fullmatch('一键翻译')
            return self

        def aria_snapshot(self, **_kwargs):
            return 'synthetic entry'

        def evaluate_all(self, _script):
            return [{'text': 'synthetic entry'}]

        def evaluate(self, script):
            return deepcopy(form) if script == inspection.EDITOR_READONLY_FORM_SCRIPT else []

        def click(self, **_kwargs):
            assert self.kind == 'entry'
            events.append('reveal_click')
            if fault == 'reveal':
                raise RuntimeError('synthetic-reveal-failure')

        def wait_for(self, **_kwargs):
            events.append('surface_wait')

    class Page:
        url = 'about:blank'
        closed = False

        def __init__(self):
            self.handlers = {}

        def on(self, event, handler):
            self.handlers.setdefault(event, []).append(handler)

        def remove_listener(self, event, handler):
            self.handlers[event].remove(handler)

        def route_web_socket(self, pattern, _handler):
            assert pattern == '**/*'
            events.append('websocket_guard')

        def goto(self, url, **_kwargs):
            events.append('goto')
            if fault == 'goto':
                raise RuntimeError('synthetic-goto-failure')
            self.url = url

        def wait_for_function(self, script, **_kwargs):
            assert script in (inspection.EDITOR_READONLY_READY_SCRIPT, inspection.EDITOR_READONLY_HYDRATED_SCRIPT)

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

        def locator(self, selector):
            if selector == '[role="dialog"]:visible,.ant-modal:visible':
                kind = 'existing'
            elif selector == '.product-add-wrapper':
                kind = 'form'
            elif selector in (inspection.EDITOR_VIDEO_SURFACE_BINDING, inspection.EDITOR_TRANSLATION_SURFACE_BINDING):
                kind = 'surface'
            else:
                assert selector in [value[0] for value in inspection.EDITOR_DIALOG_REVEAL_BINDINGS.values()]
                kind = 'entry'
            return Locator(self, kind)

        def evaluate(self, script, *_args):
            assert script in (inspection.EDITOR_READONLY_DOM_SCRIPT, inspection.EDITOR_READONLY_OVERLAYS_SCRIPT,
                              inspection.EDITOR_CONTENT_ACTION_SURFACE_SCRIPT)
            return {'raw': 'private-dom-or-surface'}

        def close(self):
            events.append('page_close')
            self.closed = True

    page = Page()

    class Capture:
        def __init__(self, observed_page, *, expected_page_url):
            assert observed_page is page
            assert expected_page_url == 'https://www.dianxiaomi.com/web/smt/edit?id=8101'
            self.closed = False
            self.handler = lambda _request: None
            captures.append(self)

        def start(self):
            events.append('capture_start')
            page.on('request', self.handler)
            return self

        def close(self):
            events.append('capture_close')
            page.remove_listener('request', self.handler)
            self.closed = True
            if fault == 'capture_close':
                raise RuntimeError('synthetic-capture-cleanup-failure')

        def snapshot(self):
            events.append('capture_snapshot')
            assert self.closed and not page.closed and 'reader_after' not in events
            return {'window_closed': True, 'reviewed_resources_match': True,
                    'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False}

    def read_details(**kwargs):
        assert kwargs == {'shop_id': '91', 'product_ids': ['8101']}
        if 'reader_before' not in events:
            events.append('reader_before')
        else:
            assert page.closed and all(capture.closed for capture in captures)
            assert not page.handlers.get('request')
            events.append('reader_after')
            if fault == 'reader_drift':
                return {'changed': True}
        return deepcopy(envelope)

    def observe(observed_page, **kwargs):
        assert observed_page is page and kwargs['screenshot_dir'] == tmp_path / 'screenshots'
        events.append('video_diagnostic')
        if fault == 'diagnostic':
            raise RuntimeError('synthetic-diagnostic-failure')
        return deepcopy(diagnostic)

    def describe(path):
        content = path.read_bytes()
        return {'path': str(path), 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest().upper()}

    def cdp_send(method, params):
        assert method == 'Network.setBypassServiceWorker' and params == {'bypass': True}
        events.append('bypass_service_worker')

    context = SimpleNamespace(new_page=lambda: page, new_cdp_session=lambda _: SimpleNamespace(send=cdp_send))
    flow = SimpleNamespace(_positive_reader_id=lambda value, **_: value,
        read_e2_product_details=read_details, _draft_reader_session=lambda: (None, context, 'browser-1'),
        _evidence_descriptor=describe, _evidence_observed_at=lambda: '2026-10-16T00:00:00Z',
        _context=context, _page=None, browser_session_id=lambda: 'browser-1')
    guard = SimpleNamespace(install=lambda _: events.append('guard_install'),
        bind_page=lambda _: events.append('guard_bind'),
        summary=lambda: {'blocked_request_count': blocked_requests}, websockets=[])
    monkeypatch.setattr(flow_module, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(flow_module, 'SCREENSHOT_DIR', tmp_path / 'screenshots')
    monkeypatch.setattr(DxmPlanReader, '_validated_envelope', staticmethod(lambda _: ('browser-1', 'account-1', {'products': [{}]})))
    monkeypatch.setattr(DxmPlanReader, '_session_ref', staticmethod(lambda *_: 'session-ref'))
    monkeypatch.setattr(DxmPlanReader, '_validated_product_detail', staticmethod(lambda _, **__: ('8101', {'subject': 'Synthetic', 'sourceUrl': 'https://fixture.invalid/product', 'categoryId': '17'})))
    monkeypatch.setattr(inspection, 'wait_editor_form_stable', lambda *_: {'ok': True, 'snapshot': deepcopy(form)})
    monkeypatch.setattr(capture_module, 'PassiveNativeVideoScriptCapture', Capture)
    monkeypatch.setattr(diagnostic_module, 'observe_video_input_diagnostic', observe)
    install_inspection_spies(monkeypatch, flow, page, guard, events, tmp_path, observe)
    return SimpleNamespace(flow=flow, guard=guard, page=page, events=events, captures=captures, root=tmp_path)
