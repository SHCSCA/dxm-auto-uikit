"""只追加原 Worker 的控件诊断来源；不改快照、恢复记录、lease 或 ledger。"""

from copy import deepcopy

from src.batch_edit.editor_inventory_context import load_context, rows, source_boundary
from src.batch_edit.editor_inventory_contract import ACTION, PARAMS, STATE, validate_observation
from src.batch_edit.editor_inventory_snapshot import require
from src.batch_edit.scope_contract import canonical_sha256
from src.db import dumps
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


COMMAND_TYPE = 'path_b_editor_inventory_command'
SOURCE_TYPE = 'path_b_editor_inventory_source'


def _insert(conn, task, job, kind, body, digest_key, now, file_path=None):
    record = {**body, digest_key: canonical_sha256(body)}
    conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)',
        (task['id'], job['id'], kind, file_path, dumps(record), now))
    return record


@source_boundary
def reserve_inventory(conn, *, task, job, command, screenshot_root, now):
    facts = load_context(conn, task=task, job=job, command=command, now=now)
    require(not rows(conn, task, job, COMMAND_TYPE) and not rows(conn, task, job, SOURCE_TYPE), 'EDITOR_INVENTORY_ALREADY_RESERVED')
    body = {'schema': 'dxm.editor_inventory_reservation.v1', 'command': deepcopy(command), 'binding': facts['binding'], 'reserved_at': now}
    return _insert(conn, task, job, COMMAND_TYPE, body, 'reservation_sha256', now)


def _verified(conn, *, task, job, command, action_result, screenshot_root, now):
    from src.execution.action_result_contract import validate_action_result_envelope
    from src.execution.browser_agent_worker import load_browser_agent_action_source
    from src.execution.editor_control_inventory import editor_control_inventory_summary
    from src.services.evidence_ref import validate_evidence_ref

    facts = load_context(conn, task=task, job=job, command=command, now=now)
    reservations = rows(conn, task, job, COMMAND_TYPE)
    require(len(reservations) == 1, 'EDITOR_INVENTORY_COMMAND_NOT_RESERVED')
    reservation = reservations[0]
    require(set(reservation) == {'schema', 'command', 'binding', 'reserved_at', 'reservation_sha256'}
        and reservation['schema'] == 'dxm.editor_inventory_reservation.v1' and reservation['command'] == command
        and reservation['binding'] == facts['binding'] and reservation['reservation_sha256'] == canonical_sha256(
            {key: item for key, item in reservation.items() if key != 'reservation_sha256'}), 'EDITOR_INVENTORY_RESERVATION_DRIFT')
    session = facts['scope']['runtime']['browserSessionId']
    artifacts = load_browser_agent_action_source(command, action_result, browser_session_id=session)
    envelope = validate_action_result_envelope(action_result, expected_state=STATE, expected_action=ACTION,
        expected_page='editor', execution_mode='batch_draft_save', expected_runtime_id=facts['command'].runtime_id,
        expected_browser_session_id=session, expected_execution_payload=facts['execution'])
    require(envelope['ok'] is True and 'mandatory_capability_receipts' not in envelope['evidence']['observations'],
        'EDITOR_INVENTORY_OBSERVATION_NOT_SUCCESSFUL')
    context = {**command, 'command_action': ACTION, 'mode': 'batch_draft_save', 'browser_session_id': session}
    wrapper = validate_observation(envelope['evidence']['observations'].get('editor_inventory_observation'), payload=facts['execution'],
        category_schema=facts['category_schema'], target_identity=command['params']['target_identity'], shop_id=command['params']['shop_id'], context=context)
    require(set(envelope['before_values']) == PARAMS and canonical_sha256(envelope['before_values']) == canonical_sha256(command['params'])
        and envelope['page_identity']['url'] == wrapper['observation']['page_url']
        and envelope['after_values'] == {'editor_control_inventory': editor_control_inventory_summary(wrapper['after'])},
        'EDITOR_INVENTORY_RESULT_BINDING_DRIFT')
    start = parse_strict_utc_timestamp(wrapper['started_at'], field='inventory start')
    end = parse_strict_utc_timestamp(wrapper['completed_at'], field='inventory end')
    require(parse_strict_utc_timestamp(reservation['reserved_at'], field='inventory reservation') <= start <= end
        <= parse_strict_utc_timestamp(now, field='inventory persistence'), 'EDITOR_INVENTORY_SOURCE_TIME_DRIFT')
    ref = wrapper['observation']['evidence_ref']
    refs = [item for item in envelope['evidence']['refs'] if {key: item[key] for key in ('path', 'sha256', 'size')} == ref]
    require(len(refs) == 1 and validate_evidence_ref(ref, screenshot_root=screenshot_root).get('ok') is True
        and start <= parse_strict_utc_timestamp(refs[0]['captured_at'], field='inventory screenshot') <= end,
        'EDITOR_INVENTORY_SCREENSHOT_DRIFT')
    return reservation, artifacts, wrapper


@source_boundary
def persist_inventory(conn, *, task, job, command, action_result, screenshot_root, now):
    require(not rows(conn, task, job, SOURCE_TYPE), 'EDITOR_INVENTORY_ALREADY_RECORDED')
    reservation, artifacts, wrapper = _verified(conn, task=task, job=job, command=command, action_result=action_result,
        screenshot_root=screenshot_root, now=now)
    body = {'schema': 'dxm.persisted_editor_inventory.v1', 'command': deepcopy(command), 'action_result': deepcopy(action_result),
        'reservation_sha256': reservation['reservation_sha256'], 'binding': reservation['binding'], 'artifacts': artifacts,
        'observation': wrapper, 'created_at': now, 'authorization_created': False}
    return _insert(conn, task, job, SOURCE_TYPE, body, 'source_sha256', now, artifacts['result']['path'])


@source_boundary
def require_inventory(conn, *, task, job, source_sha256, screenshot_root, now):
    records = rows(conn, task, job, SOURCE_TYPE)
    require(len(records) == 1, 'EDITOR_INVENTORY_PERSISTED_SOURCE_REQUIRED')
    record = records[0]
    require(set(record) == {'schema', 'command', 'action_result', 'reservation_sha256', 'binding', 'artifacts', 'observation',
        'created_at', 'authorization_created', 'source_sha256'} and record['schema'] == 'dxm.persisted_editor_inventory.v1'
        and record['authorization_created'] is False and record['source_sha256'] == source_sha256
        == canonical_sha256({key: item for key, item in record.items() if key != 'source_sha256'}), 'EDITOR_INVENTORY_SOURCE_HASH_DRIFT')
    reservation, artifacts, wrapper = _verified(conn, task=task, job=job, command=record['command'], action_result=record['action_result'],
        screenshot_root=screenshot_root, now=now)
    require(record['reservation_sha256'] == reservation['reservation_sha256'] and record['binding'] == reservation['binding']
        and record['artifacts'] == artifacts and canonical_sha256(record['observation']) == canonical_sha256(wrapper)
        and parse_strict_utc_timestamp(wrapper['completed_at'], field='inventory end')
            <= parse_strict_utc_timestamp(record['created_at'], field='inventory creation')
            <= parse_strict_utc_timestamp(now, field='inventory reread'), 'EDITOR_INVENTORY_SOURCE_DRIFT')
    return deepcopy(record)
