"""实际离线 Chromium/工厂/collector 验证观察窗口；不证明真实站点、可见登录或完整填写。"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from playwright.sync_api import sync_playwright

from src.execution.editor_control_inventory import editor_control_inventory_summary
from tests.support.editor_inventory_flow_case import editor_inventory_flow_case
from tests.support.native_video_guard_browser import local_video_server


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True,
            args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
        yield instance
        instance.close()


@pytest.fixture
def case(browser, tmp_path, monkeypatch):
    with editor_inventory_flow_case(browser, tmp_path, monkeypatch) as value:
        yield value


def observe(case):
    return case.flow.observe_editor_control_inventory(**case.args)


def test_actual_factory_collector_and_screenshot_observe_private_values_without_mutations_or_completeness(case, monkeypatch):
    page, events = case.page, []
    screenshot = page.screenshot

    def capture(**kwargs):
        events.append('screenshot')
        return screenshot(**kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError('只读清单不得调用写入或页面初始化')

    monkeypatch.setattr(page, 'screenshot', capture)
    monkeypatch.setattr(case.flow, '_ensure_page', forbidden)
    case.flow.set_mutation_authorizer(forbidden)
    page.evaluate('''()=>{window.inventoryWrites=[];window.inventoryWatch=new MutationObserver(records=>inventoryWrites.push(...records));
      inventoryWatch.observe(document.querySelector('.product-add-wrapper'),{subtree:true,attributes:true,childList:true,characterData:true});}''')
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    result = observe(case)
    raw = result['editor_inventory_observation']
    assert result['ok'] is True and events == ['screenshot']
    assert raw['before'] == raw['after'] and raw['effect_facts'] == {'request_facts': [], 'unexpected_effects': []}
    assert raw['before']['fields'][0]['original_value'] == 'Original title'
    assert raw['observation']['browser_session_id'] == case.flow.browser_session_id()
    assert raw['observation']['evidence_ref']['size'] > 0
    assert all(raw['after'][key] is False for key in ('executionAllowed', 'capabilityCertified', 'required_fields_complete', 'inputFreezeAllowed', 'write_attempted'))
    assert 'SECTION_NATIVE_ANCHOR_UNREVIEWED' in raw['after']['missing']
    assert 'Original title' not in json.dumps(editor_control_inventory_summary(raw['after']))
    assert page.evaluate('inventoryWrites.length') == 0 and requests == []
    assert case.transport.active is None and case.binding.require_live() is case.binding


@pytest.mark.parametrize('kind', ['page', 'context', 'session', 'thread', 'command', 'deadline', 'schema'])
def test_screenshot_rpc_cannot_cross_owner_or_command_changes(case, monkeypatch, kind):
    screenshot = case.page.screenshot

    def drift(**kwargs):
        result = screenshot(**kwargs)
        if kind == 'page':
            case.flow._page = case.context.new_page()
        elif kind == 'context':
            case.flow._context = object()
        elif kind == 'session':
            case.flow._browser_session_generation = 'different-session'
        elif kind == 'thread':
            case.flow._browser_session_thread_id = threading.get_ident() + 1
        elif kind == 'command':
            case.flow._execution_evidence_context['command_id'] = 'b' * 32
        elif kind == 'deadline':
            case.flow._execution_evidence_context['deadline_monotonic'] = 0
        else:
            case.args['category_schema']['normalized_schema']['properties']['title']['ui_section'] = 'other_info'
        return result

    monkeypatch.setattr(case.page, 'screenshot', drift)
    with pytest.raises(RuntimeError, match='OWNER|CLEANUP'):
        observe(case)
    assert case.transport.invalid is True and case.transport.active is None


def test_foreign_thread_refuses_before_any_playwright_rpc(case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('外线程不允许进入 Page RPC')

    monkeypatch.setattr(case.page, 'evaluate', forbidden)
    monkeypatch.setattr(case.page, 'screenshot', forbidden)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(RuntimeError, match='CONTEXT_OR_FROZEN_SCHEMA'):
            executor.submit(observe, case).result(timeout=5)
    assert case.transport.active is None and case.transport.invalid is False


@pytest.mark.parametrize('kind', ['field_value', 'target_identity'])
def test_independent_reads_after_screenshot_reject_value_or_target_changes(case, monkeypatch, kind):
    screenshot = case.page.screenshot

    def drift(**kwargs):
        result = screenshot(**kwargs)
        script = "document.querySelector('[name=sourceUrl]').value='changed'" if kind == 'field_value' else "document.querySelector('[name=storeName]').value='another-store'"
        case.page.evaluate(script)
        return result

    monkeypatch.setattr(case.page, 'screenshot', drift)
    with pytest.raises((RuntimeError, ValueError)) as error:
        observe(case)
    if kind == 'target_identity':
        assert error.value.reason_code == 'FROZEN_TARGET_PRODUCT_PAGE_IDENTITY_DRIFT'
    else:
        assert 'DRIFT' in str(error.value)
    assert case.transport.active is None


def test_actual_native_request_is_aborted_before_loopback_server_receives_it(case, monkeypatch):
    with local_video_server() as (base, hits):
        screenshot = case.page.screenshot

        def unexpected(**kwargs):
            result = screenshot(**kwargs)
            case.page.evaluate("url=>fetch(url,{method:'POST',body:'forbidden',mode:'no-cors'}).then(()=>true).catch(()=>false)", base + '/unexpected')
            return result

        monkeypatch.setattr(case.page, 'screenshot', unexpected)
        with pytest.raises(RuntimeError, match='TRANSPORT|UNEXPECTED'):
            observe(case)
        assert hits == [] and case.transport.invalid is True and case.transport.active is None


def test_first_collector_error_stops_before_screenshot_and_logs(case, monkeypatch, caplog):
    evaluate, calls = case.page.evaluate, []

    def failed(script, args=None):
        if 'dxm.editor_control_dom.v1' in script:
            raise RuntimeError('isolated inventory read failure')
        return evaluate(script, args)

    monkeypatch.setattr(case.page, 'evaluate', failed)
    monkeypatch.setattr(case.page, 'screenshot', lambda **kwargs: calls.append(kwargs))
    with pytest.raises(RuntimeError, match='READ_INCOMPLETE'):
        observe(case)
    assert calls == [] and case.transport.invalid is True
    assert 'editor_inventory_observation_failed' in caplog.text


@pytest.mark.parametrize('fault', ['partial_registration', 'cleanup_failure', 'cleanup_popup'])
def test_partial_guard_setup_or_cleanup_never_leaves_listeners_or_valid_source(case, monkeypatch, fault):
    page, attached = case.page, []
    on, remove = page.on, page.remove_listener

    def register(event, handler):
        attached.append((event, handler))
        on(event, handler)
        if fault == 'partial_registration' and event == 'download':
            raise RuntimeError('isolated registration failure')

    def unregister(event, handler):
        if fault == 'cleanup_popup' and event == 'popup':
            handler(object())
        remove(event, handler)
        attached.remove((event, handler))
        if fault == 'cleanup_failure' and event == 'download':
            raise RuntimeError('isolated cleanup failure')

    monkeypatch.setattr(page, 'on', register)
    monkeypatch.setattr(page, 'remove_listener', unregister)
    with pytest.raises(RuntimeError, match='registration failure|CLEANUP|UNEXPECTED'):
        observe(case)
    assert attached == [] and case.transport.active is None and case.transport.invalid is True


def test_live_modal_is_rejected_without_click_or_dismiss_fallback(case):
    case.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=dialog>synthetic modal</div>')")
    with pytest.raises(RuntimeError, match='MODAL_PRESENT'):
        observe(case)
    assert case.page.locator('[role=dialog]').count() == 1 and case.transport.invalid is True


def test_native_default_caret_has_real_dom_effects_but_production_observation_keeps_original_caret(case, tmp_path):
    page = case.page
    page.evaluate('''()=>{window.caretMutations=[];window.caretWatch=new MutationObserver(records=>caretMutations.push(...records));
      caretWatch.observe(document.querySelector('.product-add-wrapper'),{subtree:true,attributes:true});}''')
    page.screenshot(path=str(tmp_path / 'default-caret-control.png'), full_page=True)
    default_count = page.evaluate('caretMutations.length')
    assert default_count > 0
    page.evaluate('caretMutations.length=0')
    assert observe(case)['ok'] is True
    assert page.evaluate('caretMutations.length') == 0
    print(f'default_caret_mutation_count={default_count}; production_caret_initial_mutation_count=0')


def test_owner_change_after_first_internal_evaluate_stops_before_second_read_or_screenshot(case, monkeypatch):
    evaluate, reads, screenshots = case.page.evaluate, [], []

    def changed(script, args=None):
        result = evaluate(script, args)
        if 'dxm.editor_control_dom.v1' in script:
            reads.append(True)
            case.flow._browser_session_generation = 'replaced-after-read'
        return result

    monkeypatch.setattr(case.page, 'evaluate', changed)
    monkeypatch.setattr(case.page, 'screenshot', lambda **kwargs: screenshots.append(kwargs))
    with pytest.raises(RuntimeError, match='OWNER|CLEANUP'):
        observe(case)
    assert reads == [True] and screenshots == [] and case.transport.active is None
    assert case.transport.invalid is True


def test_prepared_but_unbound_page_is_not_silently_rebound_for_inventory(case):
    case.binding.close()
    with pytest.raises(RuntimeError, match='OWNER_UNBOUND'):
        observe(case)
    assert case.page not in case.transport.bindings and case.transport.active is None
