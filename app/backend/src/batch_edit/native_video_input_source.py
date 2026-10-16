"""预约并持久复验唯一 Worker 的视频输入观察；调用方值不能替代来源。"""

from copy import deepcopy

from src.batch_edit.native_video_input_source_context import (
    first_fill_source, load_context, require, rows, source_boundary,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import get_config_bus
from src.db import dumps
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


COMMAND_TYPE = 'path_b_video_input_command'
SOURCE_TYPE = 'path_b_video_input_source'


def _insert(conn, task, job, kind, body, digest_key, now, file_path=None):
    require(conn.in_transaction, 'VIDEO_INPUT_TRANSACTION_REQUIRED')
    record = {**body, digest_key: canonical_sha256(body)}
    conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)',
        (task['id'], job['id'], kind, file_path, dumps(record), now))
    return record


@source_boundary
def reserve_inputs(conn, *, task, job, command, screenshot_root, now):
    facts = load_context(conn, task=task, job=job, command=command, now=now)
    parent = first_fill_source(conn, task=task, job=job, facts=facts, screenshot_root=screenshot_root, now=now)
    require(not rows(conn, task, job, COMMAND_TYPE) and not rows(conn, task, job, SOURCE_TYPE), 'VIDEO_INPUT_ALREADY_RESERVED')
    body = {'schema': 'dxm.native_video_input_reservation.v1', 'command': command, 'binding': facts['binding'],
        'first_fill_source_sha256': parent['source_sha256'], 'reserved_at': now}
    return _insert(conn, task, job, COMMAND_TYPE, body, 'reservation_sha256', now)


def _verified(conn, *, task, job, command, action_result, screenshot_root, now, consumer_command=None):
    from src.batch_edit.native_video_observation_contract import ACTION, STATE, validate_observation
    from src.execution.action_result_contract import validate_action_result_envelope
    from src.execution.browser_agent_worker import load_browser_agent_action_source
    from src.services.evidence_ref import validate_evidence_ref

    facts = load_context(conn, task=task, job=job, command=command, now=now, consumer_command=consumer_command)
    reservations = rows(conn, task, job, COMMAND_TYPE)
    require(len(reservations) == 1, 'VIDEO_INPUT_COMMAND_NOT_RESERVED')
    reservation = reservations[0]
    require(isinstance(reservation, dict) and set(reservation) == {'schema', 'command', 'binding',
        'first_fill_source_sha256', 'reserved_at', 'reservation_sha256'}
        and reservation['schema'] == 'dxm.native_video_input_reservation.v1' and reservation['command'] == command
        and reservation['binding'] == facts['binding']
        and reservation['reservation_sha256'] == canonical_sha256({key: value for key, value in reservation.items() if key != 'reservation_sha256'}),
        'VIDEO_INPUT_RESERVATION_DRIFT')
    parent = first_fill_source(conn, task=task, job=job, facts=facts, screenshot_root=screenshot_root, now=now)
    require(reservation['first_fill_source_sha256'] == parent['source_sha256'], 'VIDEO_INPUT_PREDECESSOR_DRIFT')
    session = facts['scope']['runtime']['browserSessionId']
    artifacts = load_browser_agent_action_source(command, action_result, browser_session_id=session)
    envelope = validate_action_result_envelope(action_result, expected_state=STATE, expected_action=ACTION,
        expected_page='editor', execution_mode='batch_draft_save', expected_runtime_id=facts['command'].runtime_id,
        expected_browser_session_id=session, expected_execution_payload=facts['execution'])
    require(envelope['ok'] is True and 'mandatory_capability_receipts' not in envelope['evidence']['observations'],
            'VIDEO_INPUT_OBSERVATION_NOT_SUCCESSFUL')
    context = {**command, 'command_action': ACTION, 'mode': 'batch_draft_save', 'browser_session_id': session}
    observation = validate_observation(envelope['evidence']['observations'].get('native_video_input_observation'),
        payload=facts['execution'], target_identity=command['params']['target_identity'],
        shop_id=command['params']['shop_id'], context=context)
    observed = observation['observation']; before = envelope['before_values']
    require(all(before.get(key) == command['params'][key] for key in ('defaults', 'target_identity', 'store_name', 'shop_id'))
        and envelope['page_identity']['url'] == observed['page_url']
        and envelope['after_values'] == {'native_video_inputs': observed['inputs']}, 'VIDEO_INPUT_RESULT_INPUT_DRIFT')
    start = parse_strict_utc_timestamp(observation['started_at'], field='video observation start')
    end = parse_strict_utc_timestamp(observation['completed_at'], field='video observation end')
    instant = parse_strict_utc_timestamp(now, field='video source persistence')
    require(parse_strict_utc_timestamp(parent['created_at'], field='video first fill time')
        <= parse_strict_utc_timestamp(reservation['reserved_at'], field='video reservation time') <= start <= end <= instant,
        'VIDEO_INPUT_SOURCE_TIME_DRIFT')
    if consumer_command is not None:
        age_limit = get_config_bus().integer('DXM_NATIVE_VIDEO_INPUT_MAX_AGE_SECONDS', 60, minimum=1, maximum=600)
        require((instant - end).total_seconds() <= age_limit, 'VIDEO_INPUT_SOURCE_STALE')
    ref = observed['evidence_ref']
    refs = [item for item in envelope['evidence']['refs'] if {key: item[key] for key in ('path', 'sha256', 'size')} == ref]
    require(len(refs) == 1 and validate_evidence_ref(ref, screenshot_root=screenshot_root).get('ok') is True
        and start <= parse_strict_utc_timestamp(refs[0]['captured_at'], field='video screenshot time') <= end,
        'VIDEO_INPUT_SCREENSHOT_DRIFT')
    return reservation, parent, artifacts, observation


@source_boundary
def persist_inputs(conn, *, task, job, command, action_result, screenshot_root, now):
    require(not rows(conn, task, job, SOURCE_TYPE), 'VIDEO_INPUT_ALREADY_RECORDED')
    reservation, parent, artifacts, observation = _verified(conn, task=task, job=job, command=command,
        action_result=action_result, screenshot_root=screenshot_root, now=now)
    body = {'schema': 'dxm.persisted_native_video_input.v1', 'command': command, 'action_result': action_result,
        'reservation_sha256': reservation['reservation_sha256'], 'first_fill_source_sha256': parent['source_sha256'],
        'binding': reservation['binding'], 'artifacts': artifacts, 'observation': observation, 'created_at': now}
    return _insert(conn, task, job, SOURCE_TYPE, body, 'source_sha256', now, artifacts['result']['path'])


@source_boundary
def require_inputs(conn, *, task, job, source_sha256, screenshot_root, now, consumer_command=None):
    records = rows(conn, task, job, SOURCE_TYPE)
    require(len(records) == 1, 'VIDEO_INPUT_PERSISTED_SOURCE_REQUIRED')
    record = records[0]
    require(isinstance(source_sha256, str) and isinstance(record, dict) and set(record) == {'schema', 'command', 'action_result',
        'reservation_sha256', 'first_fill_source_sha256', 'binding', 'artifacts', 'observation', 'created_at', 'source_sha256'}
        and record['schema'] == 'dxm.persisted_native_video_input.v1' and record['source_sha256'] == source_sha256
        and source_sha256 == canonical_sha256({key: value for key, value in record.items() if key != 'source_sha256'}),
        'VIDEO_INPUT_SOURCE_HASH_DRIFT')
    reservation, parent, artifacts, observation = _verified(conn, task=task, job=job, command=record['command'],
        action_result=record['action_result'], screenshot_root=screenshot_root, now=now, consumer_command=consumer_command)
    require(record['reservation_sha256'] == reservation['reservation_sha256']
        and record['first_fill_source_sha256'] == parent['source_sha256'] and record['binding'] == reservation['binding']
        and record['artifacts'] == artifacts and record['observation'] == observation
        and parse_strict_utc_timestamp(observation['completed_at'], field='video observation end')
            <= parse_strict_utc_timestamp(record['created_at'], field='video source creation')
            <= parse_strict_utc_timestamp(now, field='video source reread'), 'VIDEO_INPUT_SOURCE_DRIFT')
    return deepcopy(record)
