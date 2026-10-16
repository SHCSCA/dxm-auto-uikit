"""真实 Flow 导航入口必须先建立新文档观察；测试替身不连接任何会话。"""

from types import SimpleNamespace

import pytest

from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution import native_video_lifetime as lifetime_module


@pytest.mark.parametrize('method', ['_goto_with_live_hud', '_goto_sterile'])
def test_actual_navigation_hooks_begin_lifetime_before_goto(monkeypatch, method):
    events = []
    page = SimpleNamespace(url='about:blank')

    def begin(flow, observed, url):
        assert observed is page and url == 'https://www.dianxiaomi.com/web/smt/edit?id=10001'
        events.append('lifetime_begin')

    def goto(url, **_kwargs):
        events.append('goto'); page.url = url

    monkeypatch.setattr(lifetime_module, 'begin_native_video_lifetime', begin)
    page.goto = goto
    flow = SimpleNamespace(_trace_workflow_event=lambda *_args, **_kwargs: None,
        _attach_live_hud_runtime_hooks=lambda _page: events.append('attach_hud'),
        _reapply_live_hud_if_available=lambda _page: events.append('reapply_hud'))
    getattr(DxmLoginFlow, method)(flow, page, 'https://www.dianxiaomi.com/web/smt/edit?id=10001')
    assert events.index('lifetime_begin') < events.index('goto')
    assert events.count('lifetime_begin') == events.count('goto') == 1


def test_actual_flow_observation_method_delegates_to_single_producer(monkeypatch):
    from src.execution import native_video_observation_flow
    observed = []
    flow = SimpleNamespace()
    values = {'defaults': {'fixture': True}, 'product_query': '10001', 'store_name': 'fixture-store',
        'shop_id': '91', 'target_identity': {'fixture': True}}

    def produce(actual_flow, **kwargs):
        assert actual_flow is flow
        observed.append(kwargs)
        return {'ok': False, 'stage': 'isolated-delegation-only'}

    monkeypatch.setattr(native_video_observation_flow, 'observe_native_video_inputs', produce)
    assert DxmLoginFlow.observe_native_video_inputs(flow, **values)['ok'] is False
    assert observed == [values]
