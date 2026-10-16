"""复用证据表预约并追加独立读回来源；候选字典和截图均不能替代 Worker 来源。"""

from src.batch_edit.content_finalize_sources import validate_known_content_sources
from src.batch_edit.content_observation_contract import ACTION, STATE, validate_observation
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_scope_field_bindings, validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.db import dumps, loads
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


COMMAND_TYPE = 'path_b_content_readback_command'
SOURCE_TYPE = 'path_b_content_readback_source'


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _rows(conn, task, job, kind):
    return [loads(row['meta_json'], {}) for row in conn.execute(
        'SELECT meta_json FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type=? ORDER BY id',
        (task['id'], job['id'], kind)).fetchall()]


def _facts(conn, *, task, job, command, now):
    from src.execution.batch_dispatch_authority import snapshot_row_authority_in_transaction
    from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command
    from src.real_dxm_write_scope import validate_real_dxm_write_scope

    parsed = BrowserAgentCommand(**command)
    validate_browser_agent_command(parsed)
    _require(parsed.to_payload() == command and parsed.state == STATE and parsed.action == ACTION
        and task and task.get('status') == 'running' and task.get('mode') == 'batch_draft_save'
        and job and job.get('task_id') == task['id'] and job.get('status') == 'running'
        and job.get('current_step_code') == STATE and parsed.task_id == task['id'] and parsed.job_id == job['id'],
        'CONTENT_OBSERVATION_SOURCE_STATE_INVALID')
    plan = task['payload']['plan_snapshot']
    _require(plan.get('path') == 'B', 'CONTENT_OBSERVATION_SOURCE_PATH_INVALID')
    execution = compile_frozen_execution_payload(task, job)
    validate_frozen_execution_defaults(parsed.params['defaults'], expected_payload=execution)
    scope_hash = task['payload']['real_dxm_write_authorization']['scope_sha256']
    row = conn.execute('SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?', (scope_hash,)).fetchone()
    _require(row and row['task_id'] == task['id'] and row['status'] == 'consumed', 'CONTENT_OBSERVATION_SCOPE_NOT_CONSUMED')
    scope = validate_real_dxm_write_scope(loads(row['scope_json'], {}), now=now)
    item = next(item for item in plan['item_snapshots'] if str(item['product_id']) == str(job['product_id']))
    scoped = next(item for item in scope['orderedProducts'] if str(item['productId']) == str(job['product_id']))
    _require(scope['snapshot'] == {'snapshotId': task['payload']['plan_snapshot_id'], 'snapshotSha256': plan['snapshot_hash'], 'taskId': task['id']}
        and parsed.runtime_id == scope['runtime']['browserRuntimeId']
        and str(task['store_id']) == str(scope['shop']['shopId']) == str(item['shop_id'])
        and parsed.params['shop_id'] == str(item['shop_id']) and parsed.params['store_name'] == scope['shop']['shopName']
        and parsed.params['target_identity'] == item['target_identity']
        and parsed.params['product_query'] == str(job['product_id'])
        and scoped['allowedFields'] == frozen_scope_field_bindings(item)
        and [str(item['productId']) for item in scope['orderedProducts']] == [str(item['product_id']) for item in task['jobs']],
        'CONTENT_OBSERVATION_SOURCE_AUTHORITY_DRIFT')
    _require(parse_strict_utc_timestamp(now, field='content source now') <= parse_strict_utc_timestamp(parsed.deadline, field='content command deadline'),
             'CONTENT_OBSERVATION_COMMAND_EXPIRED')
    authority = snapshot_row_authority_in_transaction(conn, task['id'])
    return parsed, execution, scope, authority


def _translation(conn, *, task, job, parsed, execution, scope, authority, screenshot_root, now):
    records = _rows(conn, task, job, 'path_b_editor_source')
    candidate = {'snapshot_sha256': task['payload']['plan_snapshot']['snapshot_hash'], 'scope_sha256': scope['scopeSha256'],
        'initial_execution_payload_hash': execution['payload_hash'],
        'observation': {'browser_session_id': scope['runtime']['browserSessionId'], 'observed_at': now}, 'receipts': {}}
    for record in records:
        _require(record.get('command', {}).get('runtime_id') == parsed.runtime_id, 'CONTENT_OBSERVATION_PREDECESSOR_RUNTIME_DRIFT')
        state = record.get('command', {}).get('state')
        capability = {'BATCH_WHOLESALE_FILL': 'wholesale', STATE: 'translation'}.get(state)
        if capability:
            candidate['receipts'][capability] = record.get('action_result', {}).get('evidence', {}).get('observations', {}).get('mandatory_capability_receipts', {}).get(capability)
    indexed = validate_known_content_sources(conn, task=task, job=job, candidate=candidate, records=records,
        screenshot_root=screenshot_root, snapshot_authority=authority)
    translation = indexed[STATE]
    _require(translation['source_sha256'] == parsed.params['translation_source_sha256']
        and translation['command']['command_id'] != parsed.command_id, 'CONTENT_OBSERVATION_PREDECESSOR_DRIFT')
    return translation


def reserve_observation(conn, *, task, job, command, screenshot_root, now):
    parsed, execution, scope, authority = _facts(conn, task=task, job=job, command=command, now=now)
    _translation(conn, task=task, job=job, parsed=parsed, execution=execution, scope=scope,
                 authority=authority, screenshot_root=screenshot_root, now=now)
    _require(not _rows(conn, task, job, COMMAND_TYPE) and not _rows(conn, task, job, SOURCE_TYPE),
             'CONTENT_OBSERVATION_ALREADY_RESERVED')
    body = {'schema': 'dxm.content_observation_reservation.v1', 'command': command,
        'snapshot_sha256': task['payload']['plan_snapshot']['snapshot_hash'], 'scope_sha256': scope['scopeSha256'],
        'snapshot_row_authority_sha256': canonical_sha256(authority), 'reserved_at': now}
    record = {**body, 'reservation_sha256': canonical_sha256(body)}
    conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json,created_at) VALUES(?,?,?,?,?)',
                 (task['id'], job['id'], COMMAND_TYPE, dumps(record), now))
    return record


def _verify_source(conn, *, task, job, command, action_result, screenshot_root, now):
    from src.execution.browser_agent_worker import load_browser_agent_action_source
    from src.execution.action_result_contract import validate_action_result_envelope
    from src.services.evidence_ref import validate_evidence_ref

    parsed, execution, scope, authority = _facts(conn, task=task, job=job, command=command, now=now)
    reserved = _rows(conn, task, job, COMMAND_TYPE)
    _require(len(reserved) == 1, 'CONTENT_OBSERVATION_COMMAND_NOT_RESERVED')
    reservation = reserved[0]
    _require(reservation.get('schema') == 'dxm.content_observation_reservation.v1'
        and reservation.get('command') == command
        and reservation.get('reservation_sha256') == canonical_sha256({key: value for key, value in reservation.items() if key != 'reservation_sha256'})
        and reservation.get('snapshot_sha256') == task['payload']['plan_snapshot']['snapshot_hash']
        and reservation.get('scope_sha256') == scope['scopeSha256']
        and reservation.get('snapshot_row_authority_sha256') == canonical_sha256(authority), 'CONTENT_OBSERVATION_RESERVATION_DRIFT')
    predecessor = _translation(conn, task=task, job=job, parsed=parsed, execution=execution, scope=scope,
        authority=authority, screenshot_root=screenshot_root, now=now)
    session = scope['runtime']['browserSessionId']
    artifacts = load_browser_agent_action_source(command, action_result, browser_session_id=session)
    envelope = validate_action_result_envelope(action_result, expected_state=STATE, expected_action=ACTION, expected_page='editor',
        execution_mode='batch_draft_save', expected_runtime_id=parsed.runtime_id, expected_browser_session_id=session,
        expected_execution_payload=execution)
    _require(envelope['ok'] is True, 'CONTENT_OBSERVATION_NOT_SUCCESSFUL')
    wrapper = envelope['evidence']['observations']['content_finalize_observation']
    context = {**command, 'command_action': ACTION, 'mode': parsed.execution_mode, 'browser_session_id': session}
    validated = validate_observation(wrapper, payload=execution, target_identity=parsed.params['target_identity'],
        shop_id=parsed.params['shop_id'], context=context)
    _require(envelope['before_values']['defaults'] == parsed.params['defaults']
        and envelope['before_values']['target_identity'] == parsed.params['target_identity']
        and envelope['before_values']['store_name'] == parsed.params['store_name']
        and envelope['before_values']['shop_id'] == parsed.params['shop_id'], 'CONTENT_OBSERVATION_RESULT_INPUT_DRIFT')
    start = parse_strict_utc_timestamp(validated['started_at'], field='content start')
    end = parse_strict_utc_timestamp(validated['completed_at'], field='content end')
    _require(parse_strict_utc_timestamp(predecessor['created_at'], field='translation source')
        <= parse_strict_utc_timestamp(reservation['reserved_at'], field='content reservation') <= start <= end
        <= parse_strict_utc_timestamp(now, field='content persistence')
        , 'CONTENT_OBSERVATION_SOURCE_TIME_DRIFT')
    ref = validated['observation']['evidence_ref']
    refs = [item for item in envelope['evidence']['refs'] if {key: item[key] for key in ('path', 'sha256', 'size')} == ref]
    _require(validate_evidence_ref(ref, screenshot_root=screenshot_root).get('ok') is True
        and len(refs) == 1
        and start <= parse_strict_utc_timestamp(refs[0]['captured_at'], field='content screenshot')
        <= parse_strict_utc_timestamp(now, field='content persistence'),
        'CONTENT_OBSERVATION_SCREENSHOT_DRIFT')
    return reservation, predecessor, artifacts, validated


def persist_observation(conn, *, task, job, command, action_result, screenshot_root, now):
    _require(not _rows(conn, task, job, SOURCE_TYPE), 'CONTENT_OBSERVATION_ALREADY_RECORDED')
    reservation, predecessor, artifacts, wrapper = _verify_source(conn, task=task, job=job, command=command,
        action_result=action_result, screenshot_root=screenshot_root, now=now)
    body = {'schema': 'dxm.persisted_content_observation.v1', 'command': command, 'action_result': action_result,
        'reservation_sha256': reservation['reservation_sha256'], 'translation_source_sha256': predecessor['source_sha256'],
        'artifacts': artifacts, 'observation': wrapper['observation'], 'created_at': now}
    record = {**body, 'source_sha256': canonical_sha256(body)}
    conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)',
        (task['id'], job['id'], SOURCE_TYPE, artifacts['result']['path'], dumps(record), now))
    return record


def require_observation(conn, *, task, job, source_sha256, screenshot_root):
    rows = _rows(conn, task, job, SOURCE_TYPE)
    _require(len(rows) == 1, 'CONTENT_OBSERVATION_PERSISTED_SOURCE_REQUIRED')
    record = rows[0]
    _require(isinstance(record, dict) and set(record) == {'schema', 'command', 'action_result', 'reservation_sha256',
        'translation_source_sha256', 'artifacts', 'observation', 'created_at', 'source_sha256'}
        and record['schema'] == 'dxm.persisted_content_observation.v1' and record['source_sha256'] == source_sha256
        and source_sha256 == canonical_sha256({key: value for key, value in record.items() if key != 'source_sha256'}),
        'CONTENT_OBSERVATION_SOURCE_HASH_DRIFT')
    reservation, predecessor, artifacts, wrapper = _verify_source(conn, task=task, job=job, command=record['command'],
        action_result=record['action_result'], screenshot_root=screenshot_root, now=record['created_at'])
    _require(record['reservation_sha256'] == reservation['reservation_sha256']
        and record['translation_source_sha256'] == predecessor['source_sha256'] and record['artifacts'] == artifacts
        and record['observation'] == wrapper['observation'], 'CONTENT_OBSERVATION_SOURCE_DRIFT')
    return record
