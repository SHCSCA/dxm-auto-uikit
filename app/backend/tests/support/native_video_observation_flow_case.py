"""合成页面执行真实观察 Flow/guard；不把 spy profile 或输入替身当生产来源。"""

import hashlib
import time
from copy import deepcopy
from types import SimpleNamespace

from src.batch_edit.native_video_observation_contract import ACTION, STATE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution import native_video_observation_flow as subject
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from src.execution.native_video_lifetime import NativeVideoLifetime
from tests.support.native_video_lifetime_case import FakePage, URL, install_profile_spy, install_transport_spy
from tests.support.native_video_observation_case import make_bindings


def observation_flow_case(monkeypatch, tmp_path, fault=None):
    events = []

    class Locator:
        def __init__(self, page, kind):
            self.page, self.kind = page, kind

        def count(self):
            if self.kind == 'blocking':
                return 1 if fault == 'blocking' else 0
            return 2 if fault == 'ambiguous' and self.kind == 'entry' else 1

        def locator(self, selector):
            assert self.kind == 'entry' and selector == 'button'
            return self

        def filter(self, **kwargs):
            assert kwargs['has_text'].fullmatch('图片生成视频')
            return self

        def is_visible(self):
            return fault != 'invisible'

        def is_enabled(self):
            return fault != 'disabled'

        def click(self, **_kwargs):
            events.append('entry_click')
            if fault == 'click':
                raise RuntimeError('synthetic entry failure')
            self.page.value.update(reveal_count=1, entry_click_count=1, visible_count=1)
            if fault == 'extra_interaction':
                self.page.value['unexpected_interactions'] = ['click']
            if fault == 'form_changed':
                self.page.form.append({'value': 'changed'})

        def wait_for(self, **_kwargs):
            events.append('modal_visible')

        def evaluate(self, _script):
            return deepcopy(self.page.form)

    class Page(FakePage):
        def __init__(self):
            super().__init__()
            self.form = [{'value': 'initial'}]
            self.context.events = events
            if fault == 'route_cleanup':
                self.context.cleanup_error = RuntimeError('synthetic route cleanup failure')
            self.value['document_time_origin'] = 1792108800000.0

        def locator(self, selector):
            return Locator(self, 'blocking' if selector == '[role="dialog"]:visible,.ant-modal:visible' else
                'form' if selector == '.product-add-wrapper' else 'entry' if selector == '.product-add-wrapper .video-operate' else 'surface')

        def route(self, pattern, handler):
            self.context.route(pattern, handler)

        def unroute(self, pattern, handler):
            self.context.unroute(pattern, handler)

        def on(self, event, handler):
            super().on(event, handler)
            if fault == 'partial_listener' and event == 'download':
                raise RuntimeError('synthetic partial listener failure')

        def wait_for_load_state(self, *_args, **_kwargs):
            events.append('network_idle')

        def screenshot(self, *, path, **_kwargs):
            events.append('screenshot')
            if fault == 'screenshot':
                raise RuntimeError('synthetic screenshot failure')
            from pathlib import Path
            Path(path).write_bytes(b'isolated screenshot fixture')

    install_profile_spy(monkeypatch)
    page = Page()
    transport = install_transport_spy(monkeypatch, page)
    owner = NativeVideoLifetime(page, page_url=URL, session_id='session-1').start()
    page.navigate()
    payload = {'execution_path': 'B', 'save_stage': 'SAVE1', 'payload_hash': 'A' * 64, 'product_id': '10001',
        'editor_actions': {'video': {'enabled': True, 'failure_strategy': 'pause', 'generation_rule': {
            'image_selection': 'native_default', 'transition': {'mode': 'native_default'}, 'music': {'mode': 'native_default'}}}}}
    target = build_frozen_product_target_identity(product_id='10001', store_name='fixture-store',
        source_urls=['https://detail.1688.com/offer/10001.html'])
    context = {'command_id': 'command-1', 'state': STATE, 'command_action': ACTION, 'mode': 'batch_draft_save',
        'task_id': 1, 'job_id': 2, 'runtime_id': 'runtime-1', 'browser_session_id': 'session-1',
        'deadline_monotonic': time.monotonic() + 60}
    times = iter(['2026-10-16T00:00:01Z', '2026-10-16T00:00:02Z'])

    def descriptor(path):
        body = path.read_bytes()
        return {'path': str(path), 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest().upper()}

    def identity(*_args, **_kwargs):
        events.append('identity')
        if fault == 'identity':
            raise RuntimeError('synthetic identity drift')

    flow = SimpleNamespace(_page=page, _native_video_lifetime=owner, _execution_evidence_context=context,
        browser_session_id=lambda: 'session-1', _evidence_observed_at=lambda: next(times),
        _normalize_frozen_target_identity=lambda *_args, **_kwargs: (deepcopy(target), canonical_sha256(target)),
        _require_frozen_product_page_identity=identity, _evidence_descriptor=descriptor)
    raw = make_bindings()
    reads = []

    def collect(actual_page):
        assert actual_page is page
        reads.append(True); events.append('raw_read')
        result = deepcopy(raw)
        if fault == 'read_drift' and len(reads) == 2:
            result['instance']['uid'] = 8
        return result

    monkeypatch.setattr(subject, 'validate_frozen_execution_defaults', lambda _defaults: deepcopy(payload))
    monkeypatch.setattr(subject, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setattr(subject, 'collect_native_video_value_bindings', collect)
    return SimpleNamespace(flow=flow, page=page, owner=owner, events=events, raw=raw, payload=payload, transport=transport,
        args={'defaults': {'isolated': True}, 'product_query': '10001', 'store_name': 'fixture-store', 'shop_id': '91', 'target_identity': target})
