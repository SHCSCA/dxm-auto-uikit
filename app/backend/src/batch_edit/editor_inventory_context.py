"""同事务复核原 Schema、批准和只读任务现场，不创建动作派发权。"""

from functools import wraps

from src.batch_edit.editor_inventory_contract import ACTION, PARAMS, STATE
from src.batch_edit.editor_inventory_snapshot import require
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_scope_field_bindings, validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.db import loads
from src.execution.e3_authority_contract import parse_strict_utc_timestamp
from src.services.structured_logging import get_logger, log_exception


def source_boundary(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            log_exception(get_logger('editor.inventory_source'), 'editor_inventory_source_rejected', exc, operation=function.__name__)
            raise
    return checked


def rows(conn, task, job, kind):
    records = []
    for row in conn.execute('SELECT meta_json,created_at FROM job_evidences WHERE task_id=? AND job_id=? AND evidence_type=? ORDER BY id',
            (task['id'], job['id'], kind)).fetchall():
        record = loads(row['meta_json'], {})
        require(isinstance(record, dict) and row['created_at'] == record.get('created_at', record.get('reserved_at')),
            'EDITOR_INVENTORY_ROW_TIME_DRIFT')
        records.append(record)
    return records


def _scope(conn, task, job, parsed, now, item):
    from src.real_dxm_write_scope import validate_real_dxm_write_scope
    from src.state_machine.batch_draft_authorization import build_batch_draft_save_task_facts, verify_authorization_context

    payload = task['payload']; plan = payload['plan_snapshot']; authorization = payload['real_dxm_write_authorization']
    scope_hash = authorization['scope_sha256']
    row = conn.execute('SELECT * FROM real_dxm_write_scopes WHERE scope_sha256=?', (scope_hash,)).fetchone()
    require(row and row['task_id'] == task['id'] and row['status'] == 'consumed', 'EDITOR_INVENTORY_SCOPE_NOT_CONSUMED')
    scope = validate_real_dxm_write_scope(loads(row['scope_json'], {}), now=now)
    approval = payload.get('manual_approval', {}); context = approval.get('authorization_context', {})
    stage = build_batch_draft_save_task_facts(task_id=task['id'], store_id=task['store_id'], product_ids=payload['product_ids'],
        plan_snapshot_id=payload['plan_snapshot_id'], plan_snapshot_hash=payload['plan_snapshot_hash'], path='B', real_authorization=authorization)
    require(approval.get('approved') is True and approval.get('source') == 'server' and approval.get('consumed') is True
        and approval.get('consumed_at') and verify_authorization_context(context).get('ok') is True
        and parse_strict_utc_timestamp(now, field='inventory now') <= parse_strict_utc_timestamp(approval.get('expires_at'), field='inventory approval expiry')
        and context.get('stage_task_facts') == approval.get('stage_task_facts') == stage, 'EDITOR_INVENTORY_PARENT_APPROVAL_INVALID')
    require(authorization.get('publish_allowed') is False and payload.get('publish_allowed') is False
        and row['approval_sha256'] == authorization.get('approval_sha256')
        and row['approval_nonce_sha256'] == authorization.get('approval_nonce_sha256') == row['scope_nonce_sha256']
        and row['snapshot_id'] == payload['plan_snapshot_id'] and row['snapshot_sha256'] == plan['snapshot_hash']
        and row['shop_id'] == str(task['store_id']) and row['expires_at'] == scope['expiresAt'] == authorization.get('approval_expires_at')
        and row['account_ref_hash'] == scope['account']['accountContextHash']
        and row['product_order_sha256'] == canonical_sha256(authorization['ordered_product_ids'])
        and row['approval_stage'] == scope['stage'] and bool(row['approval_consumed_at']) and scope['scopeSha256'] == scope_hash
        and scope['snapshot'] == {'snapshotId': payload['plan_snapshot_id'], 'snapshotSha256': plan['snapshot_hash'], 'taskId': task['id']}
        and scope['runtime']['browserRuntimeId'] == parsed.runtime_id
        and context.get('runtime_instance_id') == scope['runtime']['runtimeInstanceId']
        and context.get('browser_session_id') == scope['runtime']['browserSessionId']
        and context.get('git_head') == scope['git']['head'] and context.get('worktree_identity') == scope['worktree']
        and context.get('l2_evidence_fingerprint') == scope['l2']['evidenceFingerprint'], 'EDITOR_INVENTORY_SCOPE_AUTHORITY_DRIFT')
    scoped = [row for row in scope['orderedProducts'] if str(row['productId']) == str(job['product_id'])]
    require(len(scoped) == 1 and str(scope['shop']['shopId']) == str(task['store_id']) == str(item['shop_id'])
        and parsed.params['shop_id'] == str(item['shop_id']) and parsed.params['store_name'] == scope['shop']['shopName']
        and canonical_sha256(parsed.params['target_identity']) == canonical_sha256(item['target_identity'])
        and parsed.params['product_query'] == str(job['product_id']) and scoped[0]['allowedFields'] == frozen_scope_field_bindings(item)
        and [str(row['productId']) for row in scope['orderedProducts']] == [str(row['product_id']) for row in task['jobs']],
        'EDITOR_INVENTORY_TARGET_OR_QUEUE_DRIFT')
    return scope


def load_context(conn, *, task, job, command, now):
    from src.execution.batch_dispatch_authority import _load_task_by_id, snapshot_row_authority_in_transaction
    from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command

    require(conn.in_transaction and task and job, 'EDITOR_INVENTORY_TRANSACTION_OR_TASK_REQUIRED')
    actual = _load_task_by_id(conn, task['id'])
    current = next((row for row in actual['jobs'] if row['id'] == job['id']), None)
    require(canonical_sha256(task) == canonical_sha256(actual) and current == job, 'EDITOR_INVENTORY_CURRENT_TASK_DRIFT')
    parsed = BrowserAgentCommand(**command); validate_browser_agent_command(parsed)
    require(parsed.to_payload() == command and parsed.state == STATE and parsed.action == ACTION
        and parsed.expected_page == 'editor' and parsed.execution_mode == task.get('mode') == 'batch_draft_save'
        and parsed.task_id == task['id'] and parsed.job_id == job['id'] and set(parsed.params) == PARAMS
        and task.get('status') == job.get('status') == 'running' and job.get('current_step_code') == STATE
        and task['payload'].get('path') == 'B', 'EDITOR_INVENTORY_COMMAND_OR_STATE_INVALID')
    index = task['jobs'].index(job); statuses = [row['status'] for row in task['jobs']]
    require(statuses.count('running') == 1 and all(value in {'completed', 'succeeded'} for value in statuses[:index])
        and all(value == 'pending' for value in statuses[index+1:]) and int(task.get('completed_jobs') or 0) == index
        and int(task.get('failed_jobs') or 0) == 0, 'EDITOR_INVENTORY_QUEUE_PROGRESS_INVALID')
    require(parse_strict_utc_timestamp(now, field='inventory now') <= parse_strict_utc_timestamp(parsed.deadline, field='inventory deadline'),
        'EDITOR_INVENTORY_COMMAND_EXPIRED')
    authority = snapshot_row_authority_in_transaction(conn, task['id'])
    snapshot = conn.execute('SELECT snapshot_json FROM plan_snapshots WHERE id=?', (task['payload']['plan_snapshot_id'],)).fetchone()
    plan = loads(snapshot['snapshot_json'], {})
    items = [item for item in plan['item_snapshots'] if str(item['product_id']) == str(job['product_id'])]
    require(plan.get('path') == 'B' and len(items) == 1, 'EDITOR_INVENTORY_FROZEN_ITEM_INVALID')
    item = items[0]; category = item.get('category_schema')
    execution = compile_frozen_execution_payload(task, job)
    validate_frozen_execution_defaults(parsed.params['defaults'], expected_payload=execution)
    require(isinstance(category, dict) and isinstance(category.get('normalized_schema'), dict)
        and parsed.params['category_schema'] == category and canonical_sha256(parsed.params['category_schema']) == canonical_sha256(category)
        and canonical_sha256(category['normalized_schema']) == category.get('schema_hash') == execution['category_schema_hash'],
        'EDITOR_INVENTORY_ORIGINAL_SCHEMA_DRIFT')
    scope = _scope(conn, task, job, parsed, now, item)
    dispatched = conn.execute("SELECT id FROM mutation_dispatch_ledger WHERE task_id=? AND job_id=? AND status NOT IN ('RESERVED','CANCELLED_BEFORE_DISPATCH')",
        (task['id'], job['id'])).fetchone()
    require(not dispatched, 'EDITOR_INVENTORY_ALREADY_DISPATCHED')
    binding = {'snapshot_sha256': plan['snapshot_hash'], 'snapshot_row_authority_sha256': canonical_sha256(authority),
        'scope_sha256': scope['scopeSha256'], 'task_payload_sha256': canonical_sha256(task['payload']),
        'execution_payload_hash': execution['payload_hash'], 'category_schema_sha256': canonical_sha256(category),
        'ordered_jobs': [{'job_id': row['id'], 'product_id': str(row['product_id'])} for row in task['jobs']]}
    return {'command': parsed, 'execution': execution, 'scope': scope, 'binding': binding, 'category_schema': category}
