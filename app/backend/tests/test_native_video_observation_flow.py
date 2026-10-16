"""实际 producer/guard/JIT 接线的隔离正反例，不伪造真实原生成功。"""

from copy import deepcopy

import pytest

from src.batch_edit.scope_contract import canonical_sha256
from src.execution import native_video_observation_flow as subject
from src.execution.native_video_lifetime import NativeVideoLifetime
from tests.support.native_video_observation_flow_case import observation_flow_case


def run(case):
    return subject.observe_native_video_inputs(case.flow, **case.args)


def freeze(case):
    result = run(case)
    wrapper = result['native_video_input_observation']
    return {'lifecycle': deepcopy(wrapper['lifecycle']), 'inputs': deepcopy(wrapper['observation']['inputs']),
            'inputs_sha256': canonical_sha256(wrapper['observation']['inputs'])}


def assert_guard_cleaned(case):
    assert case.page.routes == []
    assert case.page.handlers['framenavigated'] == [case.owner._navigated]
    assert all(not handlers for event, handlers in case.page.handlers.items() if event != 'framenavigated')


def test_actual_producer_opens_once_double_reads_around_screenshot_and_keeps_same_live_owner(monkeypatch, tmp_path):
    case = observation_flow_case(monkeypatch, tmp_path)
    result = run(case)
    assert result['ok'] is True and result['write_attempted'] is False
    wrapper = result['native_video_input_observation']
    assert wrapper['lifecycle']['owner_observation_id'] == case.owner.owner_id
    assert wrapper['lifecycle']['native_defaults'] is True and wrapper['before'] == wrapper['after']
    assert case.events.count('entry_click') == 1
    assert case.events.index('entry_click') < case.events.index('raw_read') < case.events.index('screenshot')
    assert case.events.index('screenshot') < len(case.events) - 1 - case.events[::-1].index('raw_read')
    assert case.owner.observation == wrapper
    assert_guard_cleaned(case)


@pytest.mark.parametrize('fault,reason', [
    ('blocking', 'BLOCKING_MODAL'), ('ambiguous', 'ENTRY_NOT_UNIQUE'), ('disabled', 'ENTRY_NOT_UNIQUE'),
    ('invisible', 'ENTRY_NOT_UNIQUE'), ('identity', 'identity drift'), ('click', 'entry failure'),
    ('screenshot', 'screenshot failure'), ('extra_interaction', 'INTERACTION_OR_LIFETIME'),
    ('form_changed', 'MAIN_FORM_CHANGED'), ('read_drift', 'READBACK_DRIFT'),
    ('route_cleanup', 'CLEANUP_FAILED'), ('partial_listener', 'partial listener'),
])
def test_failure_never_sets_owner_observation_and_cleans_only_installed_guard_resources(monkeypatch, tmp_path, fault, reason):
    case = observation_flow_case(monkeypatch, tmp_path, fault=fault)
    with pytest.raises((RuntimeError, ValueError), match=reason):
        run(case)
    assert case.owner.observation is None
    assert_guard_cleaned(case)


@pytest.mark.parametrize('field,value', [('reveal_count', 1), ('entry_click_count', 1), ('visible_count', 1)])
def test_existing_or_previously_revealed_modal_cannot_be_relabelled_initial_defaults(monkeypatch, tmp_path, field, value):
    case = observation_flow_case(monkeypatch, tmp_path)
    case.page.value[field] = value
    with pytest.raises(RuntimeError, match='MODAL_NOT_INITIAL'):
        run(case)
    assert 'entry_click' not in case.events and case.owner.observation is None


def test_exact_same_owner_document_profile_and_raw_values_pass_jit_but_create_no_write_authority(monkeypatch, tmp_path):
    case = observation_flow_case(monkeypatch, tmp_path)
    record = freeze(case)
    assert subject.require_live_native_video_inputs(case.flow, record) is True
    assert 'write_authorization_created' not in record
    assert case.events.count('entry_click') == 1


@pytest.mark.parametrize('kind', ['owner_id', 'source_profile', 'values', 'session', 'reload', 'close', 'freeze_hash', 'reveal'])
def test_jit_rejects_stale_or_changed_runtime_owner_profile_or_input(monkeypatch, tmp_path, kind):
    case = observation_flow_case(monkeypatch, tmp_path)
    record = freeze(case)
    if kind == 'owner_id':
        case.owner.owner_id = 'b' * 32
    elif kind == 'source_profile':
        case.owner.profile.value['issues'] = ['NATIVE_VIDEO_STATIC_DUPLICATE_RESOURCE']
    elif kind == 'values':
        case.raw['instance']['uid'] = 8
    elif kind == 'session':
        case.flow.browser_session_id = lambda: 'session-2'
    elif kind == 'reload':
        case.page.navigate()
    elif kind == 'close':
        case.owner.close()
    elif kind == 'freeze_hash':
        record['inputs_sha256'] = '0' * 64
    else:
        case.page.value['entry_click_count'] = 2
    with pytest.raises((RuntimeError, ValueError)):
        subject.require_live_native_video_inputs(case.flow, record)


def test_new_python_owner_cannot_reuse_copied_observation_on_existing_document(monkeypatch, tmp_path):
    case = observation_flow_case(monkeypatch, tmp_path)
    record = freeze(case)
    current = NativeVideoLifetime(case.page, page_url=case.owner.page_url, session_id='session-1').start()
    current.observation = deepcopy(case.owner.observation)
    case.flow._native_video_lifetime = current
    with pytest.raises(RuntimeError):
        subject.require_live_native_video_inputs(case.flow, record)
    current.close(); case.owner.close()


@pytest.mark.parametrize('kind', ['deadline', 'session'])
def test_mid_observation_authority_change_cleans_guard_and_does_not_retain_candidate(monkeypatch, tmp_path, kind):
    case = observation_flow_case(monkeypatch, tmp_path)
    original = subject.collect_native_video_value_bindings

    def changed(page):
        result = original(page)
        if kind == 'deadline':
            case.flow._execution_evidence_context['deadline_monotonic'] = 0
        else:
            case.flow.browser_session_id = lambda: 'changed-session'
        return result

    monkeypatch.setattr(subject, 'collect_native_video_value_bindings', changed)
    with pytest.raises(RuntimeError, match='SESSION_OR_DEADLINE_DRIFT'):
        run(case)
    assert case.owner.observation is None
    assert_guard_cleaned(case)
