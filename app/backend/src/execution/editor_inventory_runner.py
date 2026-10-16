"""在原回滚准备之前串行持久化只读清单；不推进步骤或签发能力。"""

import asyncio
import math
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event

from src.batch_edit.editor_inventory_contract import ACTION, STATE
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.services.structured_logging import get_logger, log_exception


_LOGGER = get_logger('editor.inventory_runner')


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _failure(runtime, command, exc, task_id, job_id):
    try:
        cancel = getattr(runtime, 'cancel_command', None)
        if command is not None and callable(cancel):
            cancel(command.command_id, command.runtime_id)
    except Exception as cleanup_error:
        log_exception(_LOGGER, 'editor_inventory_command_cleanup_failed', cleanup_error,
                      task_id=task_id, job_id=job_id)
    log_exception(_LOGGER, 'editor_inventory_observation_failed', exc, task_id=task_id, job_id=job_id)
    from src.execution.v1_runner import V1ExecutionError
    return V1ExecutionError('UNKNOWN', '编辑控件清单未能持久核实，已停止', str(exc))


def _release_reservation(runtime, command, timeout, task_id, job_id):
    try:
        decision = runtime.cancel_command(command.command_id, command.runtime_id)
        _require(isinstance(decision, dict) and decision.get('ok') is True
            and decision.get('status') == 'cancelled_before_start' and decision.get('commandId') == command.command_id
            and decision.get('runtimeId') == command.runtime_id, 'EDITOR_INVENTORY_RESERVATION_RELEASE_UNPROVEN')
        # 只有原执行线程确认尚未派发且取消成功，才消费被撤销的预约；异步取消端不能消费。
        try:
            runtime.run(command, timeout_seconds=timeout)
        except RuntimeError as exc:
            if str(exc) != 'BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START':
                raise
        else:
            raise RuntimeError('EDITOR_INVENTORY_CANCELLED_RESERVATION_CONSUMPTION_UNPROVEN')
    except Exception as exc:
        log_exception(_LOGGER, 'editor_inventory_reservation_release_failed', exc, task_id=task_id, job_id=job_id)


def _observe(runner, task_id, job_id, timeout, cancelled, owner):
    command, key, runtime = None, None, None
    reservation_attempted, dispatch_started = False, False
    try:
        _require(type(task_id) is int and task_id > 0 and type(job_id) is int and job_id > 0,
                 'EDITOR_INVENTORY_TASK_ID_INVALID')
        current = runner.repo.get_task_private(task_id)
        jobs = [item for item in (current or {}).get('jobs', []) if item.get('id') == job_id]
        _require(current and current.get('id') == task_id and len(jobs) == 1, 'EDITOR_INVENTORY_CURRENT_JOB_REQUIRED')
        job = jobs[0]
        plan = current.get('payload', {}).get('plan_snapshot', {})
        _require(current.get('mode') == 'batch_draft_save' and plan.get('path') == 'B'
            and current.get('status') == job.get('status') == 'running' and job.get('current_step_code') == STATE,
            'EDITOR_INVENTORY_CURRENT_STATE_INVALID')
        key = (task_id, job_id, STATE)
        _require(key not in runner._active_browser_agent_commands, 'EDITOR_INVENTORY_COMMAND_ALREADY_ACTIVE')
        runner._require_persistent_browser_agent_ready(execution_mode='batch_draft_save')
        runtime = runner.browser_agent_runtime
        _require(runtime is not None, 'EDITOR_INVENTORY_BROWSER_AGENT_REQUIRED')
        owner['runtime'] = runtime
        payload = compile_frozen_execution_payload(current, job)
        items = [item for item in plan.get('item_snapshots', []) if str(item.get('product_id')) == str(job['product_id'])]
        _require(len(items) == 1, 'EDITOR_INVENTORY_FROZEN_ITEM_REQUIRED')
        item = items[0]
        category_schema = deepcopy(item['category_schema'])
        _require(canonical_sha256(category_schema['normalized_schema']) == category_schema['schema_hash']
            == payload['category_schema_hash'], 'EDITOR_INVENTORY_FROZEN_SCHEMA_DRIFT')
        # 命令只能携带数据库原快照的私有副本；来源事务还会独立复核原始快照行。
        command = BrowserAgentCommand(command_id=uuid.uuid4().hex,
            idempotency_key=f'editor-inventory:{runtime.runtime_id}:{task_id}:{job_id}:{payload["payload_hash"]}',
            deadline=(datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(),
            expected_page='editor', runtime_id=runtime.runtime_id, task_id=task_id, job_id=job_id,
            state=STATE, action=ACTION, execution_mode='batch_draft_save', params={
                'defaults': frozen_execution_defaults(payload), 'category_schema': category_schema,
                'product_query': str(job['product_id']), 'store_name': plan['session_context']['shop_name'],
                'shop_id': str(item['shop_id']), 'target_identity': deepcopy(item['target_identity'])})
        owner['command'] = command
        _require(not cancelled.is_set(), 'EDITOR_INVENTORY_OBSERVATION_CANCELLED')
        runner.repo.reserve_editor_control_inventory(task_id, job_id, command.to_payload())
        _require(not cancelled.is_set() and runner.browser_agent_runtime is runtime
            and command.runtime_id == runtime.runtime_id, 'EDITOR_INVENTORY_RUNTIME_DRIFT')
        reservation_attempted = True
        reservation = runtime.reserve_command(command)
        _require(isinstance(reservation, dict) and reservation.get('ok') is True,
            'EDITOR_INVENTORY_RESERVATION_REJECTED:' + str(reservation.get('reasonCode') if isinstance(reservation, dict) else 'INVALID_RESULT'))
        _require(not cancelled.is_set() and runner.browser_agent_runtime is runtime
            and command.runtime_id == runtime.runtime_id, 'EDITOR_INVENTORY_RUNTIME_DRIFT')
        _require(runner._active_browser_agent_commands.setdefault(key, command) is command,
            'EDITOR_INVENTORY_COMMAND_ALREADY_ACTIVE')
        _require(not cancelled.is_set() and runner.browser_agent_runtime is runtime
            and command.runtime_id == runtime.runtime_id, 'EDITOR_INVENTORY_RUNTIME_DRIFT')
        dispatch_started = True
        result = runtime.run(command, timeout_seconds=timeout)
        _require(not cancelled.is_set() and runner.browser_agent_runtime is runtime
            and command.runtime_id == runtime.runtime_id, 'EDITOR_INVENTORY_RUNTIME_DRIFT')
        source = runner.repo.persist_editor_control_inventory(task_id, job_id, command.to_payload(), result)
        _require(not cancelled.is_set(), 'EDITOR_INVENTORY_OBSERVATION_CANCELLED')
        return {'source_sha256': source['source_sha256'], 'executionAllowed': False, 'capabilityCertified': False,
            'inputFreezeAllowed': False, 'required_fields_complete': False}
    except Exception as exc:
        raise _failure(runtime, command, exc, task_id, job_id) from exc
    finally:
        if reservation_attempted and not dispatch_started:
            _release_reservation(runtime, command, timeout, task_id, job_id)
        if key is not None and runner._active_browser_agent_commands.get(key) is command:
            runner._active_browser_agent_commands.pop(key, None)


async def run_editor_control_inventory_observation(runner, *, task_id, job_id):
    """只接收任务标识，所有输入在既有执行线程重读；失败时不运行原回滚准备。"""
    cancelled, future, owner = Event(), None, {}
    try:
        timeout = float(runner.workflow_action_timeout_seconds)
        _require(math.isfinite(timeout) and timeout > 0, 'EDITOR_INVENTORY_TIMEOUT_INVALID')
        future = asyncio.get_running_loop().run_in_executor(None, _observe, runner, task_id, job_id, timeout, cancelled, owner)
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout + 10)
    except (asyncio.CancelledError, asyncio.TimeoutError) as exc:
        cancelled.set()
        if future is not None:
            # 超时后仍在收口的线程必须被观察，不让迟到异常成为无人接收的后台失败。
            def finished(value):
                try:
                    value.result()
                except BaseException as late_error:
                    log_exception(_LOGGER, 'editor_inventory_late_completion_failed', late_error,
                                  task_id=task_id, job_id=job_id)
            future.add_done_callback(finished)
        raise _failure(owner.get('runtime'), owner.get('command'), exc, task_id, job_id) from exc
    except Exception as exc:
        from src.execution.v1_runner import V1ExecutionError
        if isinstance(exc, V1ExecutionError):
            raise
        raise _failure(None, None, exc, task_id, job_id) from exc
