"""复核视频只读来源的当前任务、批准、队列与首写前序，不创建派发权。"""

from functools import wraps

from src.batch_edit.frozen_execution_contract import (
    compile_frozen_execution_payload, frozen_scope_field_bindings, validate_frozen_execution_defaults,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.db import loads
from src.execution.e3_authority_contract import parse_strict_utc_timestamp
from src.services.structured_logging import get_logger, log_exception


def require(condition, code):
    if not condition:
        raise ValueError(code)


def source_boundary(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            log_exception(get_logger('native_video.input_source'), 'native_video_input_source_rejected', exc,
                          operation=function.__name__)
            raise
    return checked


def rows(conn, task, job, kind):
    records = []
    for row in conn.execute('SELECT meta_json,created_at FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type=? ORDER BY id',
                            (task['id'], job['id'], kind)).fetchall():
        record = loads(row['meta_json'], {})
        require(isinstance(record, dict) and row['created_at'] == record.get('created_at', record.get('reserved_at', record.get('frozen_at'))),
                'VIDEO_INPUT_EVIDENCE_ROW_TIME_DRIFT')
        records.append(record)
    return records


def _scope(conn, task, job, execution, command, now):
    from src.real_dxm_write_scope import validate_real_dxm_write_scope
    from src.state_machine.batch_draft_authorization import build_batch_draft_save_task_facts, verify_authorization_context

    payload = task['payload']; plan = payload['plan_snapshot']; authorization = payload['real_dxm_write_authorization']
    scope_hash = authorization['scope_sha256']
    row = conn.execute('SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?', (scope_hash,)).fetchone()
    require(row and row['task_id'] == task['id'] and row['status'] == 'consumed', 'VIDEO_INPUT_SCOPE_NOT_CONSUMED')
    scope = validate_real_dxm_write_scope(loads(row['scope_json'], {}), now=now)
    approval = payload.get('manual_approval', {})
    instant = parse_strict_utc_timestamp(now, field='video source now')
    context = approval.get('authorization_context', {})
    stage = build_batch_draft_save_task_facts(task_id=task['id'], store_id=task['store_id'],
        product_ids=payload['product_ids'], plan_snapshot_id=payload['plan_snapshot_id'],
        plan_snapshot_hash=payload['plan_snapshot_hash'], path='B', real_authorization=authorization)
    require(approval.get('approved') is True and approval.get('source') == 'server'
        and approval.get('consumed') is True and approval.get('consumed_at')
        and instant <= parse_strict_utc_timestamp(approval.get('expires_at'), field='video parent approval expiry')
        and verify_authorization_context(context).get('ok') is True
        and context.get('stage_task_facts') == approval.get('stage_task_facts') == stage,
        'VIDEO_INPUT_PARENT_APPROVAL_INVALID')
    require(authorization.get('publish_allowed') is False and payload.get('publish_allowed') is False
        and row['approval_sha256'] == authorization.get('approval_sha256')
        and row['approval_nonce_sha256'] == authorization.get('approval_nonce_sha256') == row['scope_nonce_sha256']
        and row['snapshot_id'] == payload['plan_snapshot_id'] and row['snapshot_sha256'] == plan['snapshot_hash']
        and row['shop_id'] == str(task['store_id']) and row['expires_at'] == scope['expiresAt']
        and row['account_ref_hash'] == scope['account']['accountContextHash']
        and row['product_order_sha256'] == canonical_sha256(authorization['ordered_product_ids'])
        and row['approval_stage'] == scope['stage'] and bool(row['approval_consumed_at'])
        and row['expires_at'] == authorization.get('approval_expires_at')
        and scope['scopeSha256'] == scope_hash
        and scope['snapshot'] == {'snapshotId': payload['plan_snapshot_id'], 'snapshotSha256': plan['snapshot_hash'], 'taskId': task['id']}
        and scope['runtime']['browserRuntimeId'] == command.runtime_id
        and context.get('runtime_instance_id') == scope['runtime']['runtimeInstanceId']
        and context.get('browser_session_id') == scope['runtime']['browserSessionId']
        and context.get('git_head') == scope['git']['head'] and context.get('worktree_identity') == scope['worktree']
        and context.get('l2_evidence_fingerprint') == scope['l2']['evidenceFingerprint'], 'VIDEO_INPUT_SCOPE_AUTHORITY_DRIFT')
    item = next(item for item in plan['item_snapshots'] if str(item['product_id']) == str(job['product_id']))
    scoped = next(item for item in scope['orderedProducts'] if str(item['productId']) == str(job['product_id']))
    require(str(scope['shop']['shopId']) == str(task['store_id']) == str(item['shop_id'])
        and command.params['shop_id'] == str(item['shop_id']) and command.params['store_name'] == scope['shop']['shopName']
        and command.params['target_identity'] == item['target_identity']
        and command.params['product_query'] == str(job['product_id'])
        and scoped['allowedFields'] == frozen_scope_field_bindings(item)
        and [str(item['productId']) for item in scope['orderedProducts']] == [str(item['product_id']) for item in task['jobs']],
        'VIDEO_INPUT_TARGET_OR_QUEUE_DRIFT')
    return scope


def load_context(conn, *, task, job, command, now, consumer_command=None):
    from src.batch_edit.native_video_observation_contract import ACTION, STATE
    from src.execution.batch_dispatch_authority import _load_task_by_id, snapshot_row_authority_in_transaction
    from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command

    require(task and job, 'VIDEO_INPUT_SOURCE_STATE_INVALID')
    actual = _load_task_by_id(conn, task['id'])
    current = next((item for item in actual['jobs'] if item['id'] == job['id']), None)
    require(canonical_sha256(task) == canonical_sha256(actual) and current == job, 'VIDEO_INPUT_CURRENT_TASK_DRIFT')
    parsed = BrowserAgentCommand(**command)
    validate_browser_agent_command(parsed)
    require(parsed.to_payload() == command and parsed.state == STATE and parsed.action == ACTION
        and parsed.expected_page == 'editor' and parsed.execution_mode == 'batch_draft_save'
        and parsed.task_id == task['id'] and parsed.job_id == job['id']
        and task.get('status') == job.get('status') == 'running' and task['payload'].get('path') == 'B',
        'VIDEO_INPUT_SOURCE_STATE_INVALID')
    expected_step = STATE
    active = parsed
    if consumer_command is not None:
        active = BrowserAgentCommand(**consumer_command)
        validate_browser_agent_command(active)
        require(active.to_payload() == consumer_command and active.state == 'BATCH_VIDEO_SUBMIT'
            and active.action == 'submit_editor_video' and active.execution_mode == 'batch_draft_save'
            and active.expected_page == 'editor' and active.task_id == parsed.task_id and active.job_id == parsed.job_id
            and active.runtime_id == parsed.runtime_id and active.command_id != parsed.command_id
            and all(active.params.get(key) == parsed.params.get(key)
                for key in ('defaults', 'product_query', 'store_name', 'shop_id', 'target_identity')),
            'VIDEO_INPUT_CONSUMER_COMMAND_INVALID')
        expected_step = 'BATCH_VIDEO_SUBMIT'
    require(job.get('current_step_code') == expected_step, 'VIDEO_INPUT_CURRENT_STEP_INVALID')
    statuses = [item['status'] for item in task['jobs']]; index = task['jobs'].index(job)
    require(statuses.count('running') == 1 and all(value in {'completed', 'succeeded'} for value in statuses[:index])
        and all(value == 'pending' for value in statuses[index + 1:])
        and int(task.get('completed_jobs') or 0) == index and int(task.get('failed_jobs') or 0) == 0,
        'VIDEO_INPUT_QUEUE_PROGRESS_INVALID')
    require(parse_strict_utc_timestamp(now, field='video source now')
        <= parse_strict_utc_timestamp(active.deadline, field='video command deadline'), 'VIDEO_INPUT_COMMAND_EXPIRED')
    execution = compile_frozen_execution_payload(task, job)
    validate_frozen_execution_defaults(parsed.params['defaults'], expected_payload=execution)
    policy = execution.get('editor_actions', {}).get('video', {})
    require(policy.get('enabled') is True and policy.get('failure_strategy') == 'pause'
        and policy.get('generation_rule') == {'image_selection': 'native_default',
            'transition': {'mode': 'native_default'}, 'music': {'mode': 'native_default'}}, 'VIDEO_INPUT_FROZEN_POLICY_INVALID')
    scope = _scope(conn, task, job, execution, parsed, now)
    authority = snapshot_row_authority_in_transaction(conn, task['id'])
    binding = {'snapshot_sha256': task['payload']['plan_snapshot']['snapshot_hash'], 'scope_sha256': scope['scopeSha256'],
        'snapshot_row_authority_sha256': canonical_sha256(authority), 'task_payload_sha256': canonical_sha256(task['payload']),
        'policy_sha256': canonical_sha256(policy), 'execution_payload_hash': execution['payload_hash'],
        'ordered_jobs': [{'job_id': item['id'], 'product_id': str(item['product_id'])} for item in task['jobs']]}
    return {'command': parsed, 'execution': execution, 'scope': scope, 'binding': binding, 'authority': authority}


def first_fill_source(conn, *, task, job, facts, screenshot_root, now):
    from src.execution.action_result_contract import validate_action_result_envelope
    from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command
    from src.execution.browser_agent_worker import load_browser_agent_action_source
    from src.services.evidence_ref import validate_evidence_ref

    records = rows(conn, task, job, 'path_b_editor_source')
    require(len(records) == 1, 'VIDEO_INPUT_FIRST_FILL_SOURCE_REQUIRED')
    record = records[0]; command = record.get('command', {}); result = record.get('action_result', {})
    require(record.get('schema') == 'dxm.path_b_editor_source.v1'
        and record.get('source_sha256') == canonical_sha256({key: value for key, value in record.items() if key != 'source_sha256'})
        and record.get('source_sha256') == facts['command'].params['first_fill_source_sha256']
        and record.get('task_id') == task['id'] and record.get('job_id') == job['id']
        and str(record.get('product_id')) == str(job['product_id'])
        and all(record.get(key) == facts['binding'][key] for key in (
            'snapshot_sha256', 'scope_sha256', 'snapshot_row_authority_sha256', 'execution_payload_hash')),
        'VIDEO_INPUT_FIRST_FILL_SOURCE_DRIFT')
    parsed = BrowserAgentCommand(**command)
    validate_browser_agent_command(parsed)
    require(parsed.to_payload() == command and parsed.state == 'FILL_BASE_INFO' and parsed.action == 'fill_editor_required_defaults'
        and parsed.task_id == task['id'] and parsed.job_id == job['id'] and parsed.execution_mode == 'batch_draft_save'
        and parsed.expected_page == 'editor' and parsed.runtime_id == facts['command'].runtime_id
        and parsed.command_id != facts['command'].command_id
        and all(parsed.params.get(key) == facts['command'].params[key] for key in ('defaults', 'store_name', 'target_identity')),
        'VIDEO_INPUT_FIRST_FILL_COMMAND_DRIFT')
    session = facts['scope']['runtime']['browserSessionId']
    require(record.get('artifacts') == load_browser_agent_action_source(command, result, browser_session_id=session),
            'VIDEO_INPUT_FIRST_FILL_FILES_DRIFT')
    envelope = validate_action_result_envelope(result, expected_state='FILL_BASE_INFO', expected_action=parsed.action,
        expected_page='editor', execution_mode='batch_draft_save', expected_runtime_id=parsed.runtime_id,
        expected_browser_session_id=session, expected_execution_payload=facts['execution'])
    require(envelope['ok'] is True and envelope['evidence']['refs'] and all(
        validate_evidence_ref({key: ref[key] for key in ('path', 'sha256', 'size')}, screenshot_root=screenshot_root).get('ok') is True
        for ref in envelope['evidence']['refs']), 'VIDEO_INPUT_FIRST_FILL_EVIDENCE_INVALID')
    require(parse_strict_utc_timestamp(record['created_at'], field='first fill source')
        <= parse_strict_utc_timestamp(now, field='video source now'), 'VIDEO_INPUT_FIRST_FILL_TIME_INVALID')
    return record
