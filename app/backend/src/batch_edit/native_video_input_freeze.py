"""仅追加可信视频输入引用；数据库消费不替代活页面复核或写入授权。"""

from copy import deepcopy

from src.batch_edit.native_video_input_source import require_inputs
from src.batch_edit.native_video_input_source_context import require, rows, source_boundary
from src.batch_edit.scope_contract import canonical_sha256
from src.db import dumps, loads
from src.execution.e3_authority_contract import parse_strict_utc_timestamp


FREEZE_TYPE = 'path_b_native_video_input_freeze'


def _body(task, job, source, now):
    wrapper = source['observation']; observation = wrapper['observation']
    return {'schema': 'dxm.native_video_input_freeze.v1', 'task_id': task['id'], 'job_id': job['id'],
        'product_id': str(job['product_id']), 'binding': deepcopy(source['binding']),
        'observation_source_sha256': source['source_sha256'], 'observation_command_id': source['command']['command_id'],
        'inputs': deepcopy(observation['inputs']), 'inputs_sha256': canonical_sha256(observation['inputs']),
        'lifecycle': deepcopy(wrapper['lifecycle']), 'lifecycle_sha256': canonical_sha256(wrapper['lifecycle']),
        'page_url': observation['page_url'], 'browser_session_id': observation['browser_session_id'],
        'target_identity_sha256': observation['target_identity_sha256'], 'frozen_at': now,
        'write_authorization_created': False, 'live_recheck_required': True}


@source_boundary
def append_input_freeze(conn, *, task, job, source_sha256, screenshot_root, now):
    require(conn.in_transaction, 'VIDEO_INPUT_TRANSACTION_REQUIRED')
    require(not rows(conn, task, job, FREEZE_TYPE), 'VIDEO_INPUT_FREEZE_ALREADY_RECORDED')
    source = require_inputs(conn, task=task, job=job, source_sha256=source_sha256, screenshot_root=screenshot_root, now=now)
    require(parse_strict_utc_timestamp(source['created_at'], field='video source creation')
        <= parse_strict_utc_timestamp(now, field='video input freeze'), 'VIDEO_INPUT_FREEZE_TIME_INVALID')
    body = _body(task, job, source, now)
    record = {**body, 'freeze_sha256': canonical_sha256(body)}
    conn.execute('INSERT INTO job_evidences(task_id,job_id,evidence_type,file_path,meta_json,created_at) VALUES(?,?,?,?,?,?)',
        (task['id'], job['id'], FREEZE_TYPE, source['artifacts']['result']['path'], dumps(record), now))
    return record


def _generation_authority(conn, *, task, job, command, record, source):
    from src.execution.batch_dispatch_authority import LiveDispatchFacts, validate_in_transaction
    from src.execution.browser_agent_protocol import BrowserAgentCommand, mutation_target_hash, validate_browser_agent_command

    parsed = BrowserAgentCommand(**command)
    validate_browser_agent_command(parsed)
    require(parsed.state == 'BATCH_VIDEO_SUBMIT' and parsed.action == 'submit_editor_video'
        and parsed.params.get('native_video_input_freeze_sha256') == record['freeze_sha256']
        and parsed.task_id == task['id'] and parsed.job_id == job['id'], 'VIDEO_INPUT_GENERATION_REFERENCE_INVALID')
    row = conn.execute('SELECT scope_json FROM real_dxm_write_scopes WHERE scope_sha256=?',
                       (record['binding']['scope_sha256'],)).fetchone()
    scope = loads(row['scope_json'], {}) if row else {}
    require(scope, 'VIDEO_INPUT_SCOPE_NOT_CONSUMED')
    # 这些事实来自已批准作用域，只复验现存批准；真正点击仍须重新采样活运行时与页面。
    approved = LiveDispatchFacts(runtime_instance_id=scope['runtime']['runtimeInstanceId'],
        browser_runtime_id=scope['runtime']['browserRuntimeId'], browser_session_id=scope['runtime']['browserSessionId'],
        git_head=scope['git']['head'], worktree_identity=scope['worktree'], l2_status=scope['l2']['status'],
        l2_evidence_fingerprint=scope['l2']['evidenceFingerprint'], account_ref_hash=scope['account']['accountContextHash'])
    decision = validate_in_transaction(conn, parsed, {'browser_session_id': record['browser_session_id'],
        'page_url': record['page_url'], 'page_kind': 'editor', 'target_hash': mutation_target_hash(parsed.action, parsed.params)}, approved)
    require(decision.ok is True, 'VIDEO_INPUT_GENERATION_AUTHORITY_DRIFT:' + decision.reason_code)
    require(parsed.command_id != source['command']['command_id'], 'VIDEO_INPUT_GENERATION_REFERENCE_INVALID')


@source_boundary
def require_input_freeze(conn, *, task, job, freeze_sha256, screenshot_root, now, generation_command=None):
    records = rows(conn, task, job, FREEZE_TYPE)
    require(len(records) == 1, 'VIDEO_INPUT_PERSISTED_FREEZE_REQUIRED')
    record = records[0]
    require(isinstance(freeze_sha256, str) and isinstance(record, dict)
        and record.get('freeze_sha256') == freeze_sha256
        and freeze_sha256 == canonical_sha256({key: value for key, value in record.items() if key != 'freeze_sha256'}),
        'VIDEO_INPUT_FREEZE_HASH_DRIFT')
    source = require_inputs(conn, task=task, job=job, source_sha256=record['observation_source_sha256'],
        screenshot_root=screenshot_root, now=now, consumer_command=generation_command)
    require(record == {**_body(task, job, source, record['frozen_at']), 'freeze_sha256': freeze_sha256}, 'VIDEO_INPUT_FREEZE_DRIFT')
    require(parse_strict_utc_timestamp(source['created_at'], field='video source creation')
        <= parse_strict_utc_timestamp(record['frozen_at'], field='video input freeze')
        <= parse_strict_utc_timestamp(now, field='video input consumption'), 'VIDEO_INPUT_FREEZE_TIME_INVALID')
    if generation_command is not None:
        _generation_authority(conn, task=task, job=job, command=generation_command, record=record, source=source)
    return deepcopy(record)
