"""原生视频默认输入的严格观察合同；来源表和当次 owner 生存期仍须独立验证。"""

import math
import re
from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.e3_authority_contract import parse_strict_utc_timestamp
from src.execution.native_video_script_capture import REVIEWED_VIDEO_SCRIPTS
from src.execution.native_video_value_bindings import PROFILE, validate_value_bindings
from src.services.structured_logging import get_logger, log_exception


SCHEMA = 'dxm.native_video_input_observation.v1'
STATE = 'BATCH_VIDEO_SELECT'
ACTION = 'observe_native_video_inputs'
POSTCONDITIONS = ('native_video_inputs_observed', 'native_video_defaults_stable', 'native_video_zero_write_proven')
_LOGGER = get_logger('native_video.observation_contract')


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9A-F]{64}', value) is not None


def command_binding(context):
    return {**{key: context.get(key) for key in ('command_id', 'state', 'task_id', 'job_id', 'runtime_id', 'browser_session_id')},
            'action': context.get('command_action')}


def _source_profile(value):
    _require(isinstance(value, dict) and set(value) == {'schema', 'profile', 'window_closed', 'document_bound',
        'document_invalid', 'reviewed_resources_match', 'missing_resources', 'resources', 'issues', 'body_read_count',
        'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'}, 'VIDEO_OBSERVATION_PROFILE_INVALID')
    _require(value['schema'] == 'dxm.native_video_static_capture.v1' and value['profile'] == PROFILE
        and type(value['window_closed']) is bool and value['document_bound'] is True and value['document_invalid'] is False
        and value['reviewed_resources_match'] is True and value['missing_resources'] == [] and value['issues'] == []
        and type(value['body_read_count']) is int and value['body_read_count'] == len(REVIEWED_VIDEO_SCRIPTS)
        and all(value[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed')),
        'VIDEO_OBSERVATION_PROFILE_UNBOUND')
    resources = value['resources']
    _require(isinstance(resources, list) and len(resources) == len(REVIEWED_VIDEO_SCRIPTS), 'VIDEO_OBSERVATION_RESOURCES_INCOMPLETE')
    names = []
    for resource in resources:
        _require(isinstance(resource, dict) and set(resource) == {'name', 'request_finished', 'sha256', 'matches_reviewed', 'size'}
            and resource['name'] in REVIEWED_VIDEO_SCRIPTS, 'VIDEO_OBSERVATION_RESOURCE_INVALID')
        names.append(resource['name'])
        expected_size, expected_hash = REVIEWED_VIDEO_SCRIPTS[resource['name']]
        _require(resource['request_finished'] is True and resource['matches_reviewed'] is True
            and type(resource['size']) is int and resource['size'] == expected_size
            and resource['sha256'] == expected_hash, 'VIDEO_OBSERVATION_RESOURCE_DRIFT')
    _require(set(names) == set(REVIEWED_VIDEO_SCRIPTS), 'VIDEO_OBSERVATION_RESOURCE_COVERAGE_DRIFT')


def _lifecycle(value, raw):
    _require(isinstance(value, dict) and set(value) == {'page_lifetime_observed', 'document_navigation_count',
        'same_document', 'reveal_count', 'visible_before', 'visible_after', 'interaction_count', 'unexpected_interactions',
        'native_defaults', 'native_component_uid', 'owner_observation_id', 'document_time_origin'}, 'VIDEO_OBSERVATION_LIFECYCLE_INVALID')
    for key, expected in {'document_navigation_count': 1, 'reveal_count': 1, 'visible_before': 0,
                          'visible_after': 1, 'interaction_count': 1}.items():
        _require(type(value[key]) is int and value[key] == expected, 'VIDEO_OBSERVATION_INITIAL_DEFAULT_UNPROVEN')
    _require(all(value[key] is True for key in ('page_lifetime_observed', 'same_document', 'native_defaults'))
        and value['unexpected_interactions'] == [] and type(value['native_component_uid']) is int
        and value['native_component_uid'] == raw['instance']['uid'], 'VIDEO_OBSERVATION_INITIAL_DEFAULT_UNPROVEN')
    origin = value['document_time_origin']
    _require(type(origin) in {int, float} and math.isfinite(origin) and origin > 0 and origin == raw['document_time_origin']
        and isinstance(value['owner_observation_id'], str) and re.fullmatch('[0-9a-f]{32}', value['owner_observation_id']) is not None,
        'VIDEO_OBSERVATION_OWNER_IDENTITY_INVALID')


def _effects(value):
    from src.execution.dxm_login_flow import DXM_E2_PLAN_READ_ALLOWLIST
    from src.execution.native_video_read_contract import NATIVE_VIDEO_READ_BODIES

    _require(isinstance(value, dict) and set(value) == {'request_facts', 'unexpected_effects'}
        and value['unexpected_effects'] == [] and isinstance(value['request_facts'], list), 'VIDEO_OBSERVATION_EFFECT_UNPROVEN')
    for request in value['request_facts']:
        _require(isinstance(request, dict) and set(request) == {'method', 'path', 'request_sha256', 'allowed'}
            and request['allowed'] is True and isinstance(request['path'], str)
            and _hash(request['request_sha256']), 'VIDEO_OBSERVATION_REQUEST_FORBIDDEN')
        native = NATIVE_VIDEO_READ_BODIES.get(request['path'])
        if native is not None:
            _require(request['method'] == 'POST' and request['request_sha256'] == sha256(native[1].encode()).hexdigest().upper(),
                     'VIDEO_OBSERVATION_NATIVE_READ_BODY_DRIFT')
        else:
            _require((request['method'], 'https://www.dianxiaomi.com' + request['path']) in DXM_E2_PLAN_READ_ALLOWLIST,
                     'VIDEO_OBSERVATION_REQUEST_FORBIDDEN')


def _validate(value, *, payload, target_identity, shop_id, context):
    _require(isinstance(value, dict) and set(value) == {'schema', 'command', 'execution_payload_hash', 'started_at',
        'completed_at', 'source_profile', 'lifecycle', 'before', 'after', 'effect_facts', 'observation'}, 'VIDEO_OBSERVATION_SHAPE_INVALID')
    _require(context.get('state') == STATE and context.get('command_action') == ACTION
        and context.get('mode') == 'batch_draft_save' and all(context.get(key) for key in
            ('command_id', 'runtime_id', 'browser_session_id', 'task_id', 'job_id')), 'VIDEO_OBSERVATION_COMMAND_INVALID')
    _require(value['schema'] == SCHEMA and value['command'] == command_binding(context)
        and payload.get('execution_path') == 'B' and payload.get('save_stage', 'SAVE1') == 'SAVE1'
        and _hash(value['execution_payload_hash']) and value['execution_payload_hash'] == payload['payload_hash'], 'VIDEO_OBSERVATION_COMMAND_DRIFT')
    start = parse_strict_utc_timestamp(value['started_at'], field='video observation start')
    end = parse_strict_utc_timestamp(value['completed_at'], field='video observation end')
    _require(start <= end, 'VIDEO_OBSERVATION_TIME_INVALID')
    _source_profile(value['source_profile'])
    _require(value['before'] == value['after'], 'VIDEO_OBSERVATION_READBACK_DRIFT')
    inputs = validate_value_bindings(value['before'])
    _lifecycle(value['lifecycle'], value['before'])
    _effects(value['effect_facts'])
    observation = value['observation']
    _require(isinstance(observation, dict) and set(observation) == {'product_id', 'shop_id', 'browser_session_id', 'page_url',
        'target_identity_sha256', 'observed_at', 'inputs', 'evidence_ref', 'write_attempted'}, 'VIDEO_OBSERVATION_VALUES_INVALID')
    page = urlsplit(observation['page_url'])
    product = str(payload['product_id'])
    _require(target_identity['stable_identity'].get('kind') == 'product_id'
        and target_identity['stable_identity'].get('value') == product
        and str(observation['product_id']) == product and str(observation['shop_id']) == str(shop_id)
        and observation['browser_session_id'] == context['browser_session_id']
        and observation['target_identity_sha256'] == canonical_sha256(target_identity)
        and page.scheme == 'https' and page.netloc == 'www.dianxiaomi.com' and page.path == '/web/smt/edit'
        and not page.fragment and parse_qs(page.query) == {'id': [product]}, 'VIDEO_OBSERVATION_IDENTITY_DRIFT')
    _require(observation['write_attempted'] is False and observation['observed_at'] == value['completed_at']
        and observation['inputs'] == inputs, 'VIDEO_OBSERVATION_INPUTS_OR_TIME_DRIFT')
    reference = observation['evidence_ref']
    _require(isinstance(reference, dict) and set(reference) == {'path', 'sha256', 'size'}
        and isinstance(reference['path'], str) and bool(reference['path']) and _hash(reference['sha256'])
        and type(reference['size']) is int and reference['size'] > 0, 'VIDEO_OBSERVATION_SCREENSHOT_INVALID')
    return deepcopy(value)


def validate_observation(value, *, payload, target_identity, shop_id, context):
    """只验证 Worker 观察的自洽性；字典本身不能替代生产来源或 owner 实例。"""
    try:
        return _validate(value, payload=payload, target_identity=target_identity, shop_id=shop_id, context=context)
    except Exception as exc:
        log_exception(_LOGGER, 'native_video_observation_rejected', exc)
        if isinstance(exc, ValueError):
            raise
        raise ValueError('VIDEO_OBSERVATION_MALFORMED') from exc
