"""原始线缆正例可复读；任何内层码都不能单独证明生成或投放成功。"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from src.core.config_bus import ConfigurationError, configuration_scope
from src.execution.native_video_network_contract import (
    NativeVideoNetworkLimits, require_reviewed_video_success, validate_video_wire_observation,
)
from src.execution.native_video_wire import NativeVideoWireError, raw_facts, reopen_body, request_values
from tests.support.native_video_network_case import (
    GENERATION_BODY, MEDIA, UUID, assert_no_authority, complete, make_case, reseal,
    Request, exchange,
)


def validate(case, record):
    return validate_video_wire_observation(record, expected_scope=case.scope, limits=case.capture.limits)


def test_complete_original_bytes_reopen_uuid_chain_and_full_media_without_success_authority():
    case = make_case()
    complete(case)
    record = case.capture.private_facts()
    assert record['wire_complete'] is True
    assert_no_authority(record)
    facts = validate(case, record)
    assert facts['generation']['uuid'] == UUID
    assert facts['last_progress']['outer_code'] == 0 and facts['last_progress']['process_code'] == 1
    assert facts['media_candidate'] == MEDIA
    assert facts['business_success_proven'] is facts['placement_proven'] is False
    assert reopen_body(record['exchanges'][0]['request_body'], maximum=65536) == GENERATION_BODY
    assert all(item['request_body']['base64'] and item['response_body']['base64'] for item in record['exchanges'])
    record['exchanges'][0]['request_body']['base64'] = 'changed'
    assert case.capture.private_facts()['wire_complete'] is True


@pytest.mark.parametrize('code', [-1, 0, 1, 2, 99])
def test_static_progress_codes_remain_unreviewed_even_with_complete_media(code):
    case = make_case()
    complete(case, progress_code=code)
    record = case.capture.private_facts()
    assert record['wire_complete'] is True
    assert validate(case, record)['last_progress']['process_code'] == code
    with pytest.raises(NativeVideoWireError, match='SUCCESS_SEMANTICS_UNREVIEWED'):
        require_reviewed_video_success(record, expected_scope=case.scope, limits=case.capture.limits)
    assert_no_authority(record)


@pytest.mark.parametrize('field', ['scope', 'window', 'exchanges', 'observation_sha256', 'success_semantics'])
def test_missing_record_bindings_are_rejected(field):
    case = make_case(); complete(case)
    record = case.capture.private_facts(); del record[field]
    with pytest.raises(NativeVideoWireError):
        validate(case, record)


@pytest.mark.parametrize('change', ['hash', 'body', 'uuid', 'input', 'scope', 'order', 'extra_success', 'flag'])
def test_tampering_or_rehashed_inconsistent_facts_cannot_replace_original_causality(change):
    case = make_case(); complete(case)
    record = case.capture.private_facts()
    if change == 'hash':
        record['observation_sha256'] = '0' * 64
    elif change == 'body':
        record['exchanges'][1]['response_body']['base64'] = 'dGFtcGVyZWQ='
    elif change == 'uuid':
        record['exchanges'][1]['request_body'] = raw_facts(b'uuid=other-native-uuid', maximum=65536)
    elif change == 'input':
        record['exchanges'][0]['request_body'] = raw_facts(GENERATION_BODY.replace(b'transition=4', b'transition=3'), maximum=65536)
    elif change == 'scope':
        record['scope']['browser_session_id'] = 'other-session'
    elif change == 'order':
        record['exchanges'][1]['request_at'] = record['window']['started_at']
    elif change == 'extra_success':
        record['generation_success'] = True
    else:
        record['inputFreezeAllowed'] = True
    if change != 'hash':
        reseal(record)
    with pytest.raises(NativeVideoWireError):
        validate(case, record)


@pytest.mark.parametrize('field,value', [('task_id', True), ('job_id', 0), ('product_id', '08101'),
    ('browser_session_id', ''), ('inputs_sha256', 'invalid'), ('source_page_url', 'https://www.dianxiaomi.com/web/smt/edit?id=8102')])
def test_scope_rejects_ambiguous_identity_and_page(field, value):
    case = make_case()
    with pytest.raises(NativeVideoWireError):
        replace(case.scope, **{field: value}).validate()


@pytest.mark.parametrize('field,value', [('state', 'BATCH_VIDEO_PLACE'), ('action', 'place_editor_video'),
    ('task_id', '71'), ('params', {'caller_success': True}), ('expected_page', 'draft_box')])
def test_exact_existing_command_pair_and_full_command_digest_are_required(field, value):
    case = make_case()
    case.capture.command = replace(case.command, **{field: value})
    with pytest.raises(NativeVideoWireError, match='COMMAND_DRIFT'):
        case.capture.start()
    assert case.page.registered == []


@pytest.mark.parametrize('raw', [b'imgs=a&imgs=b&transition=1&musicUrl=&platform=smt',
    GENERATION_BODY + b'&caller_success=true', GENERATION_BODY.replace(b'transition=4', b'transition=04'),
    GENERATION_BODY.replace(b'platform=smt', b'platform=lazada'), b'uuid=one&uuid=two'])
def test_ambiguous_extra_or_noncurrent_wire_fields_are_not_normalized(raw):
    with pytest.raises(NativeVideoWireError):
        request_values('progress' if raw.startswith(b'uuid=') else 'generation', raw)


@pytest.mark.parametrize('name,value', [('DXM_VIDEO_NETWORK_MAX_BODY_BYTES', '127'),
    ('DXM_VIDEO_NETWORK_MAX_EVENTS', '03'), ('DXM_VIDEO_NETWORK_MAX_WINDOW_SECONDS', 'nan')])
def test_configuration_bounds_are_frozen_through_the_bus(name, value):
    with configuration_scope({name: value}), pytest.raises(ConfigurationError):
        make_case()


def test_public_summary_and_logs_never_export_private_uuid_media_or_raw_bytes(caplog):
    case = make_case(); complete(case)
    summary = case.capture.summary()
    assert summary['wire_complete'] is True
    text = json.dumps(summary) + caplog.text
    assert all(raw not in text for raw in (UUID, MEDIA, 'private-a.png', 'base64'))
    assert_no_authority(summary)
    with pytest.raises(NativeVideoWireError):
        validate(case, deepcopy(summary))


def test_invalid_direct_limit_objects_cannot_bypass_global_ceilings():
    with pytest.raises(NativeVideoWireError, match='LIMITS_INVALID'):
        NativeVideoNetworkLimits(100000000, 3, 300)


def test_actual_browser_time_and_body_observation_time_cannot_be_resealed_out_of_order():
    case = make_case(); complete(case)
    original = case.capture.private_facts()
    for field in ('browser_timing', 'body_observed_at'):
        record = deepcopy(original)
        if field == 'browser_timing':
            record['exchanges'][1][field]['startTime'] = record['exchanges'][0][field]['startTime'] - 1
        else:
            record['exchanges'][1][field] = record['window']['started_at']
        reseal(record)
        with pytest.raises(NativeVideoWireError):
            validate(case, record)


def test_native_object_uuid_and_running_empty_media_preserve_raw_shape_without_defaulting():
    case = make_case(); case.capture.start()
    generation = Request(case.page, response={'code': 0, 'data': {'uuid': UUID, 'native_field': 'preserved'}})
    exchange(case, generation)
    exchange(case, Request(case.page, 'progress', response={'code': 0, 'data': {'processMsg': {'code': 0, 'data': ''}}}))
    case.capture.close()
    record = case.capture.private_facts()
    derived = validate(case, record)
    assert derived['generation']['uuid'] == UUID and derived['media_candidate'] is None
    raw = reopen_body(record['exchanges'][0]['response_body'], maximum=65536)
    assert json.loads(raw)['data']['native_field'] == 'preserved'
    assert_no_authority(record)


def test_close_reentered_by_body_pump_does_not_remove_listeners_or_read_twice():
    case = make_case(); case.capture.start()
    request = exchange(case, Request(case.page))
    body = request.response_value.body
    def reenter_close():
        case.capture.close()
        assert case.page.removed == []
        return body()
    request.response_value.body = reenter_close
    case.capture.close()
    assert request.response_value.reads == 1
    assert case.page.registered == case.page.removed
    assert case.capture.private_facts()['wire_complete'] is True


def test_native_timing_overlap_is_preserved_but_never_claims_physical_or_business_success():
    case = make_case(); case.capture.start()
    generation = exchange(case, Request(case.page))
    progress = Request(case.page, 'progress')
    progress.timing['startTime'] = generation.timing['startTime'] + 1
    exchange(case, progress); case.capture.close()
    record = case.capture.private_facts()
    assert record['wire_complete'] is True
    assert validate(case, record)['physical_completion_order'] == 'unproven'
    assert case.capture.summary()['physical_completion_order'] == 'unproven'
    with pytest.raises(NativeVideoWireError, match='SUCCESS_SEMANTICS_UNREVIEWED'):
        require_reviewed_video_success(record, expected_scope=case.scope, limits=case.capture.limits)
