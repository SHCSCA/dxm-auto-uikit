"""生成命令只绑定仓储唯一输入冻结；复验不创建派发权或完成回执。"""

import re
from copy import deepcopy
from dataclasses import replace

from src.batch_edit.native_video_input_freeze import FREEZE_TYPE, require_input_freeze
from src.batch_edit.native_video_input_source_context import require, rows, source_boundary
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command


REFERENCE = 'native_video_input_freeze_sha256'
_PARAMS = frozenset({'defaults', 'product_query', 'store_name', 'shop_id', 'target_identity',
    'target_source_urls', 'batch_queue_guard'})


def _command(value):
    parsed = BrowserAgentCommand(**value)
    validate_browser_agent_command(parsed)
    require(parsed.to_payload() == value and parsed.state == 'BATCH_VIDEO_SUBMIT'
        and parsed.action == 'submit_editor_video' and parsed.execution_mode == 'batch_draft_save'
        and parsed.expected_page == 'editor', 'VIDEO_INPUT_GENERATION_COMMAND_INVALID')
    require(_PARAMS <= set(parsed.params) <= _PARAMS | {REFERENCE}, 'VIDEO_INPUT_GENERATION_PARAMS_INVALID')
    return parsed


@source_boundary
def bind_generation_input_freeze(conn, *, task, job, generation_command, screenshot_root, now):
    require(conn.in_transaction and task and job, 'VIDEO_INPUT_TRANSACTION_REQUIRED')
    parsed = _command(generation_command)
    require(parsed.task_id == task['id'] and parsed.job_id == job['id'], 'VIDEO_INPUT_GENERATION_COMMAND_INVALID')
    records = rows(conn, task, job, FREEZE_TYPE)
    require(len(records) == 1, 'VIDEO_INPUT_PERSISTED_FREEZE_REQUIRED')
    record = records[0]; reference = record.get('freeze_sha256')
    require(isinstance(reference, str) and re.fullmatch('[0-9A-F]{64}', reference) is not None
        and reference == canonical_sha256({key: value for key, value in record.items() if key != 'freeze_sha256'}),
        'VIDEO_INPUT_FREEZE_HASH_DRIFT')
    if REFERENCE in parsed.params:
        require(parsed.params[REFERENCE] == reference, 'VIDEO_INPUT_GENERATION_REFERENCE_CONFLICT')
    bound = replace(parsed, params={**deepcopy(parsed.params), REFERENCE: reference})
    # 选择与完整消费同处一个事务，公开历史分页不能决定唯一性。
    require_input_freeze(conn, task=task, job=job, freeze_sha256=reference, screenshot_root=screenshot_root,
        now=now, generation_command=bound.to_payload())
    validate_browser_agent_command(bound)
    return bound.to_payload()


@source_boundary
def require_generation_input_freeze(repo, command):
    parsed = _command(command.to_payload())
    reference = parsed.params.get(REFERENCE)
    require(isinstance(reference, str) and re.fullmatch('[0-9A-F]{64}', reference) is not None,
            'VIDEO_INPUT_GENERATION_REFERENCE_INVALID')
    # 此事务在 Worker 的 ledger.begin_dispatch 之前结束，不在账本事务内另开连接。
    return repo.require_native_video_input_freeze(parsed.task_id, parsed.job_id,
        freeze_sha256=reference, generation_command=parsed.to_payload())
