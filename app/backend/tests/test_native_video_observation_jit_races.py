"""RPC 处理事件后的权威必须重验；替身只复现时序，不提供生产来源。"""

from copy import deepcopy

import pytest

from src.batch_edit.scope_contract import canonical_sha256
from src.execution import native_video_observation_flow as subject
from tests.support.native_video_lifetime_case import started_owner
from tests.support.native_video_observation_flow_case import observation_flow_case


def _observe(case):
    return subject.observe_native_video_inputs(case.flow, **case.args)


def _observed(monkeypatch, tmp_path):
    case = observation_flow_case(monkeypatch, tmp_path)
    observation = _observe(case)['native_video_input_observation']
    freeze = {'lifecycle': deepcopy(observation['lifecycle']),
        'inputs': deepcopy(observation['observation']['inputs']),
        'inputs_sha256': canonical_sha256(observation['observation']['inputs'])}
    return case, freeze


def _drift(case, kind):
    if kind == 'close':
        case.owner.close()
    elif kind == 'navigation':
        case.page.navigate()
    elif kind == 'session':
        case.flow.browser_session_id = lambda: 'replacement-session'
    elif kind == 'owner':
        case.flow._native_video_lifetime = None
    elif kind == 'page':
        case.flow._page = object()
    elif kind == 'profile':
        case.owner.profile.value['issues'] = ['NATIVE_VIDEO_STATIC_DUPLICATE_RESOURCE']
    else:
        raise AssertionError('未知合成漂移类型')


@pytest.mark.parametrize('phase,kind', [
    ('raw', 'close'), ('raw', 'navigation'), ('raw', 'session'), ('raw', 'owner'),
    ('raw', 'page'), ('raw', 'profile'), ('snapshot', 'session'), ('snapshot', 'owner'), ('snapshot', 'page'),
])
def test_jit_rejects_owner_document_or_scope_change_while_rpc_returns(monkeypatch, tmp_path, phase, kind):
    case, freeze = _observed(monkeypatch, tmp_path)
    if phase == 'raw':
        original = subject.collect_native_video_value_bindings

        def changed(page):
            captured = original(page)
            _drift(case, kind)
            return captured

        monkeypatch.setattr(subject, 'collect_native_video_value_bindings', changed)
    else:
        original = case.owner.profile.snapshot

        def changed():
            captured = original()
            _drift(case, kind)
            return captured

        monkeypatch.setattr(case.owner.profile, 'snapshot', changed)
    with pytest.raises((RuntimeError, ValueError)):
        subject.require_live_native_video_inputs(case.flow, freeze)


@pytest.mark.parametrize('kind', ['close', 'navigation', 'frame'])
def test_lifetime_read_rechecks_python_owner_after_evaluate_pumps_events(monkeypatch, kind):
    page, owner = started_owner(monkeypatch)
    original = page.evaluate

    def changed(script):
        captured = original(script)
        if kind == 'close':
            owner.close()
        elif kind == 'navigation':
            page.navigate()
        else:
            page.main_frame = object()
        return captured

    monkeypatch.setattr(page, 'evaluate', changed)
    with pytest.raises(RuntimeError):
        owner.read()


def test_jit_rejects_external_freeze_identity_mutation_during_raw_read(monkeypatch, tmp_path):
    case, freeze = _observed(monkeypatch, tmp_path)
    original = subject.collect_native_video_value_bindings

    def changed(page):
        captured = original(page)
        freeze['lifecycle']['owner_observation_id'] = 'b' * 32
        return captured

    monkeypatch.setattr(subject, 'collect_native_video_value_bindings', changed)
    with pytest.raises((RuntimeError, ValueError)):
        subject.require_live_native_video_inputs(case.flow, freeze)
    assert case.owner.observation['lifecycle']['owner_observation_id'] == case.owner.owner_id


def test_failed_second_observation_revokes_previously_live_candidate(monkeypatch, tmp_path):
    case, freeze = _observed(monkeypatch, tmp_path)
    case.flow._evidence_observed_at = lambda: '2026-10-16T00:00:03Z'
    with pytest.raises(RuntimeError, match='MODAL_NOT_INITIAL'):
        _observe(case)
    with pytest.raises((RuntimeError, ValueError)):
        subject.require_live_native_video_inputs(case.flow, freeze)


@pytest.mark.parametrize('kind', ['profile', 'owner', 'context'])
def test_producer_rejects_authority_drift_during_double_read_before_persistable_success(monkeypatch, tmp_path, kind):
    case = observation_flow_case(monkeypatch, tmp_path)
    original = subject.collect_native_video_value_bindings

    def changed(page):
        captured = original(page)
        if kind == 'context':
            case.flow._execution_evidence_context = {**case.flow._execution_evidence_context, 'command_id': 'another-command'}
        else:
            _drift(case, kind)
        return captured

    monkeypatch.setattr(subject, 'collect_native_video_value_bindings', changed)
    with pytest.raises((RuntimeError, ValueError)):
        _observe(case)
    assert case.owner.observation is None
