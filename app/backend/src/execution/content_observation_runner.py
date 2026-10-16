"""沿唯一 BrowserAgent 追加独立观察，不进入新步骤或放开保存。"""

import uuid
from datetime import datetime, timedelta, timezone

from src.batch_edit.content_observation_contract import ACTION, STATE
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.services.structured_logging import get_logger, log_exception


def run_content_observation(runner, *, task, job, translation_command, translation_source_sha256):
    params = {key: translation_command.params[key] for key in ('defaults', 'product_query', 'store_name', 'shop_id', 'target_identity')}
    params['translation_source_sha256'] = translation_source_sha256
    command = BrowserAgentCommand(command_id=uuid.uuid4().hex,
        idempotency_key=f'content-observation:{task["id"]}:{job["id"]}:{translation_source_sha256}',
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=runner.workflow_action_timeout_seconds)).isoformat(),
        expected_page='editor', runtime_id=runner.browser_agent_runtime.runtime_id, task_id=task['id'], job_id=job['id'],
        state=STATE, action=ACTION, params=params, execution_mode='batch_draft_save')
    key = (int(task['id']), int(job['id']), STATE)
    try:
        runner.repo.reserve_content_observation(task['id'], job['id'], command.to_payload())
        runner._active_browser_agent_commands[key] = command
        result = runner.browser_agent_runtime.run(command, timeout_seconds=runner.workflow_action_timeout_seconds)
        source = runner.repo.persist_content_observation(task['id'], job['id'], command.to_payload(), result)
        return source['source_sha256']
    except Exception as exc:
        runner._cancel_browser_agent_command(command)
        log_exception(get_logger('content_observation'), 'content_observation_failed', exc, task_id=task['id'], job_id=job['id'])
        from src.execution.v1_runner import V1ExecutionError
        raise V1ExecutionError('UNKNOWN', '独立最终读回未能持久核实，已停止', str(exc)) from exc
    finally:
        runner._active_browser_agent_commands.pop(key, None)
