"""清单观察只返回诊断摘要；原值仅留在私有观察产物内。"""

from copy import deepcopy

from src.batch_edit.editor_inventory_contract import ACTION, POSTCONDITIONS, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
from src.execution.editor_control_inventory import editor_control_inventory_summary
from src.services.structured_logging import get_logger, log_exception


def observe_with_adapter(adapter, *, defaults, category_schema, product_query, store_name, target_identity, shop_id):
    try:
        target = adapter._require_frozen_target_identity(ACTION, target_identity, store_name)
        payload = validate_frozen_execution_defaults(defaults)
        context = deepcopy(adapter._execution_evidence_context)
        before = deepcopy({'defaults': defaults, 'category_schema': category_schema, 'product_query': product_query,
            'store_name': store_name, 'target_identity': target, 'shop_id': shop_id})
        if context.get('browser_session_id') != adapter.browser_session_id():
            raise RuntimeError('EDITOR_INVENTORY_ADAPTER_SESSION_DRIFT')
        result = dict(adapter.login_flow.observe_editor_control_inventory(**before))
        validate_observation(result.get('editor_inventory_observation'), payload=payload, category_schema=category_schema,
            target_identity=target, shop_id=shop_id, context=context)
        if adapter._execution_evidence_context != context or adapter.browser_session_id() != context['browser_session_id']:
            raise RuntimeError('EDITOR_INVENTORY_ADAPTER_COMMAND_DRIFT')
        return adapter._result(ACTION, result, before_values=before)
    except Exception as exc:
        log_exception(get_logger('editor.inventory_adapter'), 'editor_inventory_adapter_failed', exc)
        raise


def validate_adapter_observation(sources, before_values, context):
    validate_observation(sources.get('editor_inventory_observation'),
        payload=before_values['defaults']['_frozen_execution_payload'], category_schema=before_values['category_schema'],
        target_identity=before_values['target_identity'], shop_id=before_values['shop_id'], context=context)
    return dict.fromkeys(POSTCONDITIONS, True)


def inventory_after_values(sources):
    raw = sources.get('editor_inventory_observation', {}).get('after')
    return {'editor_control_inventory': editor_control_inventory_summary(raw)}
