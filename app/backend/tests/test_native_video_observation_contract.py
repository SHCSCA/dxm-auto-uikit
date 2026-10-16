"""严格观察的正反例只验证局部合同，不构成 Worker 生产来源或 READY。"""

import pytest
from hashlib import sha256

from src.batch_edit.native_video_observation_contract import ACTION, STATE, validate_observation
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from src.execution.native_video_read_contract import NATIVE_VIDEO_READ_BODIES
from tests.support.native_video_observation_case import make_observation


@pytest.fixture
def case():
    payload = {'execution_path': 'B', 'save_stage': 'SAVE1', 'payload_hash': 'A' * 64, 'product_id': '10001'}
    target = build_frozen_product_target_identity(product_id='10001', store_name='fixture-store',
        source_urls=['https://detail.1688.com/offer/10001.html'])
    context = {'command_id': 'command-1', 'state': STATE, 'command_action': ACTION, 'mode': 'batch_draft_save',
               'task_id': 1, 'job_id': 2, 'runtime_id': 'runtime-1', 'browser_session_id': 'session-1'}
    args = {'payload': payload, 'target_identity': target, 'shop_id': 'shop-1', 'context': context}
    return make_observation(**args, evidence_ref={'path': 'private/video.png', 'sha256': 'B' * 64, 'size': 100}), args


def test_complete_native_false_branch_requires_full_initial_lifecycle_and_preserves_values(case):
    wrapper, args = case
    result = validate_observation(wrapper, **args)
    assert result == wrapper and result is not wrapper
    assert result['observation']['inputs']['music'] == {'mode': 'none'}
    assert result['observation']['inputs']['transition'] == 1
    assert result['before']['executionAllowed'] is False
    assert len(args['target_identity']['stable_identity']['fingerprint']) == 64
    result['observation']['inputs']['images'].reverse()
    assert result != wrapper


@pytest.mark.parametrize('section,key,value,reason', [
    ('lifecycle', 'page_lifetime_observed', False, 'INITIAL_DEFAULT'),
    ('lifecycle', 'document_navigation_count', 2, 'INITIAL_DEFAULT'),
    ('lifecycle', 'document_navigation_count', True, 'INITIAL_DEFAULT'),
    ('lifecycle', 'same_document', False, 'INITIAL_DEFAULT'),
    ('lifecycle', 'reveal_count', 2, 'INITIAL_DEFAULT'),
    ('lifecycle', 'visible_before', 1, 'INITIAL_DEFAULT'),
    ('lifecycle', 'interaction_count', 2, 'INITIAL_DEFAULT'),
    ('lifecycle', 'unexpected_interactions', ['music_click'], 'INITIAL_DEFAULT'),
    ('lifecycle', 'native_component_uid', 8, 'INITIAL_DEFAULT'),
    ('lifecycle', 'owner_observation_id', 'A' * 32, 'OWNER_IDENTITY'),
    ('lifecycle', 'document_time_origin', float('nan'), 'OWNER_IDENTITY'),
    ('lifecycle', 'document_time_origin', 1, 'OWNER_IDENTITY'),
    ('source_profile', 'document_invalid', True, 'PROFILE_UNBOUND'),
    ('source_profile', 'reviewed_resources_match', False, 'PROFILE_UNBOUND'),
    ('source_profile', 'issues', ['SOURCE_DRIFT'], 'PROFILE_UNBOUND'),
    ('source_profile', 'body_read_count', 3, 'PROFILE_UNBOUND'),
    ('source_profile', 'inputFreezeAllowed', True, 'PROFILE_UNBOUND'),
    ('observation', 'write_attempted', True, 'INPUTS_OR_TIME'),
    ('observation', 'page_url', 'https://www.dianxiaomi.com/web/smt/edit?id=10001&other=1', 'IDENTITY'),
    ('observation', 'browser_session_id', 'other-session', 'IDENTITY'),
    ('effect_facts', 'unexpected_effects', ['request'], 'EFFECT_UNPROVEN'),
])
def test_missing_lifecycle_or_scope_cannot_be_replaced_by_a_silent_music_label(case, section, key, value, reason):
    wrapper, args = case
    wrapper[section][key] = value
    with pytest.raises(ValueError, match=reason):
        validate_observation(wrapper, **args)


@pytest.mark.parametrize('mutate,reason', [
    (lambda w: w['after']['images']['dom_urls'].reverse(), 'READBACK_DRIFT'),
    (lambda w: w['source_profile']['resources'][0].update(sha256='0' * 64), 'RESOURCE_DRIFT'),
    (lambda w: w['source_profile']['resources'].__setitem__(1, w['source_profile']['resources'][0]), 'COVERAGE_DRIFT'),
    (lambda w: w['observation']['inputs'].update(transition=0), 'INPUTS_OR_TIME'),
    (lambda w: w['observation']['inputs'].update(music={'mode': 'library', 'id': 'caller-id'}), 'INPUTS_OR_TIME'),
    (lambda w: w['command'].update(command_id='other-command'), 'COMMAND_DRIFT'),
    (lambda w: w.update(completed_at='2026-10-15T00:00:00Z'), 'TIME_INVALID'),
    (lambda w: w['effect_facts']['request_facts'].append({'method': 'POST', 'path': '/api/picToVideo/transToVideo.json',
        'request_sha256': 'D' * 64, 'allowed': True}), 'REQUEST_FORBIDDEN'),
])
def test_observation_consistency_and_source_bytes_are_required(case, mutate, reason):
    wrapper, args = case
    mutate(wrapper)
    with pytest.raises(ValueError, match=reason):
        validate_observation(wrapper, **args)


def test_invalid_page_identity_logs_one_global_boundary_error(case, caplog):
    wrapper, args = case
    wrapper['observation']['page_url'] = None
    with pytest.raises(ValueError, match='IDENTITY_DRIFT'):
        validate_observation(wrapper, **args)
    assert 'native_video_observation_rejected' in caplog.text


@pytest.mark.parametrize('path', NATIVE_VIDEO_READ_BODIES)
def test_observer_only_native_read_requires_exact_reviewed_body_digest(case, path):
    wrapper, args = case
    request = {'method': 'POST', 'path': path, 'allowed': True,
        'request_sha256': sha256(NATIVE_VIDEO_READ_BODIES[path][1].encode()).hexdigest().upper()}
    wrapper['effect_facts']['request_facts'] = [request]
    assert validate_observation(wrapper, **args) == wrapper
    request['request_sha256'] = sha256(b'{"caller":true}').hexdigest().upper()
    with pytest.raises(ValueError, match='NATIVE_READ_BODY_DRIFT'):
        validate_observation(wrapper, **args)
