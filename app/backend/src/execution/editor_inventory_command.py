"""核对只读命令的输入自洽性；数据库原快照权威由仓储事务复验。"""

from src.batch_edit.frozen_execution_contract import frozen_execution_defaults, validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.services.structured_logging import get_logger, log_exception


_PARAMS = frozenset({'defaults', 'category_schema', 'product_query', 'store_name', 'shop_id', 'target_identity'})
_LOGGER = get_logger('editor.inventory_command')


def _require(condition):
    if not condition:
        raise ValueError('EDITOR_INVENTORY_OBSERVATION_COMMAND_INVALID')


def validate_editor_inventory_command(command):
    """不接收首写回执或 mutation scope，不将自洽性升级为写授权。"""
    from src.execution.browser_agent_protocol import canonical_frozen_target_identity

    try:
        _require(command.state == 'PREPARE_ROLLBACK' and command.action == 'observe_editor_control_inventory'
            and command.execution_mode == 'batch_draft_save' and command.expected_page == 'editor'
            and command.pre_dispatch_page in (None, 'editor') and command.post_dispatch_page in (None, 'editor')
            and isinstance(command.params, dict) and set(command.params) == _PARAMS)
        for identity in (command.task_id, command.job_id):
            _require(type(identity) in {int, str} and str(identity).isascii() and str(identity).isdecimal()
                and int(identity) > 0 and str(int(identity)) == str(identity))
        params = command.params
        payload = validate_frozen_execution_defaults(params['defaults'])
        _require(canonical_sha256(params['defaults']) == canonical_sha256(frozen_execution_defaults(payload))
            and payload.get('schema') == 'dxm.batch_draft_save.execution_payload.v1'
            and payload.get('execution_path') == 'B' and payload.get('save_stage', 'SAVE1') == 'SAVE1'
            and isinstance(params['product_query'], str) and params['product_query'] == payload.get('product_id'))
        category = params['category_schema']
        _require(isinstance(category, dict) and isinstance(category.get('normalized_schema'), dict)
            and canonical_sha256(category['normalized_schema']) == category.get('schema_hash') == payload.get('category_schema_hash'))
        for key in ('store_name', 'shop_id'):
            value = params[key]
            _require(isinstance(value, str) and bool(value) and value == ' '.join(value.split()))
        target = canonical_frozen_target_identity(params['target_identity'], store_name=params['store_name'])
        _require(canonical_sha256(target) == canonical_sha256(params['target_identity']) and target['stable_identity']['kind'] == 'product_id'
            and target['stable_identity']['value'] == params['product_query'])
        return payload
    except Exception as exc:
        log_exception(_LOGGER, 'editor_inventory_command_rejected', exc)
        raise ValueError('EDITOR_INVENTORY_OBSERVATION_COMMAND_INVALID') from exc
