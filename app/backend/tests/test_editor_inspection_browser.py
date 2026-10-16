"""离线真实浏览器只证实受管接线与拒绝边界，合成资源不属于生产证据。"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.execution.editor_inspection_owner import EditorInspectionOwner
from src.execution.editor_inspection_scope import EditorInspectionScope
from src.execution.native_video_read_contract import NATIVE_VIDEO_READ_BODIES
from tests.support.editor_inspection_browser_case import URL, URLS, inspection_browser_case, inspect


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True,
            args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
        yield instance
        instance.close()


def test_actual_flow_uses_unique_transport_and_collects_first_native_defaults(browser, tmp_path, monkeypatch):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        result = inspect(case)
        private = json.loads(Path(result['artifact']['path']).read_text(encoding='utf8'))
        assert result['ok'] is True and result['videoStaticSources']['reviewed_resources_match'] is True
        assert result['videoInputSummary']['default_provenance'] == 'initial_native_modal_observed'
        diagnostic = private['videoInputDiagnostic']
        assert diagnostic['actual']['transition'] == 4 and diagnostic['actual']['music'] == {'mode': 'none'}
        assert diagnostic['actual']['images'] == URLS
        assert case.screenshots[0]['formChanges'] == 0
        first = case.screenshots[0]['firstLifetime']
        assert first['entry_click_count'] == first['reveal_count'] == first['visible_count'] == 0
        assert diagnostic['lifecycle_before']['entry_click_count'] == diagnostic['lifecycle_after']['reveal_count'] == 1
        assert set(row['path'] for row in result['network']['native_read_facts']) == set(NATIVE_VIDEO_READ_BODIES)
        assert result['network']['native_read_request_count'] == 3 and result['network']['initial_navigation_count'] == 1
        assert all(result[key] is False for key in ('executionAllowed', 'capabilityCertified'))
        assert result['videoInputSummary']['inputFreezeAllowed'] is False
        assert 'Synthetic title' not in json.dumps(result) and 'fixture.invalid/a.png' not in json.dumps(result)
        assert case.reader_calls == [1, 1] and case.context.pages == [case.primary]
        assert case.flow._native_video_lifetime is case.production_owner and case.flow._execution_evidence_context is None
        assert not case.transport.invalid and case.transport.active is None and case.transport.bindings == set()
        assert case.context._impl_obj._routes == [case.transport.http_route]
        assert case.context._impl_obj._web_socket_routes == [case.transport.ws_route]
        assert all(page._impl_obj._routes == page._impl_obj._web_socket_routes == [] for page in case.context.pages)


@pytest.mark.parametrize('dialog', [None, 'translation'])
def test_nonvideo_inspection_keeps_existing_readonly_behavior_without_page_routes(browser, tmp_path, monkeypatch, dialog):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        result = inspect(case, dialog)
        assert result['ok'] is True and 'videoStaticSources' not in result
        assert 'videoInputSummary' not in result and result['network']['native_read_request_count'] == 0
        assert case.transport.active is None and case.transport.invalid is False
        assert case.primary._impl_obj._routes == case.primary._impl_obj._web_socket_routes == []


@pytest.mark.parametrize('kind', ['early', 'unknown_post', 'generation', 'poll', 'cancel'])
def test_forbidden_requests_never_reach_offline_reply_boundary(browser, tmp_path, monkeypatch, kind):
    paths = {'unknown_post': '/api/unknown', 'generation': '/api/picToVideo/transToVideo.json',
        'poll': '/api/checkProcess.json', 'cancel': '/api/cancelProcess.json'}
    options = {'early_native': True} if kind == 'early' else {'reveal_script':
        "fetch('" + paths[kind] + "',{method:'POST',body:'{}'}).catch(()=>null);"}
    with inspection_browser_case(browser, tmp_path, monkeypatch, **options) as case:
        with pytest.raises(RuntimeError):
            inspect(case)
        forbidden = list(NATIVE_VIDEO_READ_BODIES) if kind == 'early' else [paths[kind]]
        assert not any(any(url.endswith(path) for path in forbidden) for _, url, _ in case.delivered)
        assert case.transport.invalid and case.transport.active is None and case.transport.bindings == set()
        assert case.context.pages == [case.primary] and case.reader_calls == [1]
        assert list((tmp_path / 'editor_readonly_inspection').glob('*.json')) == []


def test_missing_internal_vnode_is_diagnostic_and_never_stable_defaults(browser, tmp_path, monkeypatch):
    with inspection_browser_case(browser, tmp_path, monkeypatch, bindings=False) as case:
        result = inspect(case)
        summary = result['videoInputSummary']
        assert summary['double_read_completed'] is False and summary['stable_across_screenshot'] is False
        assert summary['default_provenance'] == 'unverified' and summary['inputFreezeAllowed'] is False
        assert 'VIDEO_NATIVE_COMPONENT_BINDING_UNAVAILABLE' in summary['limitations']


@pytest.mark.parametrize('fault', ['reject', 'owner_drift'])
def test_normal_body_with_invalid_exit_always_cleans_scope(browser, tmp_path, monkeypatch, fault):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        page = case.context.new_page()
        owner = EditorInspectionOwner(case.flow, page, URL).start()
        scope = EditorInspectionScope(owner, case.guard)
        try:
            with pytest.raises(RuntimeError):
                with scope:
                    owner.rpc(page.goto, URL)
                    if fault == 'reject':
                        scope.reject('SYNTHETIC_REJECTION')
                    else:
                        case.flow._browser_session_generation = 'different-session'
            assert scope.listeners == [] and case.transport.active is None and case.transport.invalid
        finally:
            if owner.invalid or fault == 'owner_drift':
                with pytest.raises(RuntimeError, match='CLEANUP'):
                    owner.close()
            else:
                owner.close()
            page.close()


@pytest.mark.parametrize('fault', ['primary_close', 'primary_reload', 'primary_url'])
def test_primary_session_drift_during_rpc_is_not_silently_accepted(browser, tmp_path, monkeypatch, fault):
    with inspection_browser_case(browser, tmp_path, monkeypatch) as case:
        # 底层所有者用空白主页面证明同 URL reload，避免另装回复路由干扰被测政策。
        if fault == 'primary_reload':
            case.primary.goto('about:blank')
        page = case.context.new_page()
        owner = EditorInspectionOwner(case.flow, page, URL).start()
        try:
            def changed():
                if fault == 'primary_close':
                    case.primary.close()
                elif fault == 'primary_reload':
                    case.primary.reload()
                else:
                    case.primary.goto('about:blank#changed')
            with pytest.raises(RuntimeError, match='OWNER_DRIFT'):
                owner.rpc(changed)
            assert owner.invalid or case.primary.is_closed()
        finally:
            with pytest.raises(RuntimeError, match='CLEANUP'):
                owner.close()
            page.close()
