"""沿既有 Runner 与 BrowserAgent 预约、观察并追加输入冻结，不推进队列。"""

import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.batch_edit.native_video_input_source_context import require
from src.batch_edit.native_video_observation_contract import ACTION, STATE
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.services.structured_logging import get_logger, log_exception


def _first_fill_reference(runner, task, job, provided):
    if provided is not None:
        require(isinstance(provided, str) and re.fullmatch('[0-9A-F]{64}', provided) is not None,
                'VIDEO_INPUT_FIRST_FILL_REFERENCE_INVALID')
        return provided
    sources = [row.get('meta') for row in runner.repo.list_evidences(task['id'])
        if row.get('job_id') == job['id'] and row.get('evidence_type') == 'path_b_editor_source'
        and row.get('meta', {}).get('command', {}).get('state') == 'FILL_BASE_INFO']
    require(len(sources) == 1, 'VIDEO_INPUT_FIRST_FILL_SOURCE_REQUIRED')
    source = sources[0]
    require(source.get('schema') == 'dxm.path_b_editor_source.v1' and source.get('task_id') == task['id']
        and source.get('job_id') == job['id'] and str(source.get('product_id')) == str(job['product_id'])
        and source.get('source_sha256') == canonical_sha256({key: value for key, value in source.items() if key != 'source_sha256'}),
        'VIDEO_INPUT_FIRST_FILL_REFERENCE_INVALID')
    return source['source_sha256']


def run_native_video_input_observation(runner, *, task, job, first_fill_source_sha256=None):
    command, key = None, None
    try:
        current = runner.repo.get_task_private(task['id'])
        actual_job = next((item for item in (current or {}).get('jobs', []) if item['id'] == job['id']), None)
        require(current and actual_job and current.get('status') == actual_job.get('status') == 'running'
            and actual_job.get('current_step_code') == STATE and current.get('mode') == 'batch_draft_save',
            'VIDEO_INPUT_SOURCE_STATE_INVALID')
        key = (int(current['id']), int(actual_job['id']), STATE)
        require(key not in runner._active_browser_agent_commands, 'VIDEO_INPUT_COMMAND_ALREADY_ACTIVE')
        reference = _first_fill_reference(runner, current, actual_job, first_fill_source_sha256)
        payload = compile_frozen_execution_payload(current, actual_job)
        item = next(item for item in current['payload']['plan_snapshot']['item_snapshots']
                    if str(item['product_id']) == str(actual_job['product_id']))
        target = item['target_identity']; runtime = runner.browser_agent_runtime
        require(runtime is not None, 'VIDEO_INPUT_BROWSER_AGENT_REQUIRED')
        command = BrowserAgentCommand(command_id=uuid.uuid4().hex,
            idempotency_key=f'native-video-input:{current["id"]}:{actual_job["id"]}:{reference}',
            deadline=(datetime.now(timezone.utc)+timedelta(seconds=runner.workflow_action_timeout_seconds)).isoformat(),
            expected_page='editor', runtime_id=runtime.runtime_id, task_id=current['id'], job_id=actual_job['id'],
            state=STATE, action=ACTION, execution_mode='batch_draft_save', params={
                'defaults': frozen_execution_defaults(payload), 'product_query': str(actual_job['product_id']),
                'shop_id': str(item['shop_id']), 'store_name': current['payload']['plan_snapshot']['session_context']['shop_name'],
                'target_identity': deepcopy(target), 'first_fill_source_sha256': reference})
        runner.repo.reserve_native_video_inputs(current['id'], actual_job['id'], command.to_payload())
        runner._active_browser_agent_commands[key] = command
        result = runtime.run(command, timeout_seconds=runner.workflow_action_timeout_seconds)
        source = runner.repo.persist_native_video_inputs(current['id'], actual_job['id'], command.to_payload(), result)
        freeze = runner.repo.persist_native_video_input_freeze(current['id'], actual_job['id'], source_sha256=source['source_sha256'])
        return {**result, 'workflow_runtime': 'browser_agent', 'browser_agent_command': command.to_payload(),
            'native_video_input_source_sha256': source['source_sha256'], 'native_video_input_freeze_sha256': freeze['freeze_sha256']}
    except Exception as exc:
        runner._cancel_browser_agent_command(command)
        log_exception(get_logger('native_video.input_runner'), 'native_video_input_observation_failed', exc,
                      task_id=task.get('id') if isinstance(task, dict) else None,
                      job_id=job.get('id') if isinstance(job, dict) else None)
        from src.execution.v1_runner import V1ExecutionError
        raise V1ExecutionError('UNKNOWN', '原生视频输入未能持久核实，已停止', str(exc)) from exc
    finally:
        if key is not None and runner._active_browser_agent_commands.get(key) is command:
            runner._active_browser_agent_commands.pop(key, None)
