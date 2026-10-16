"""最终观察只通过现有 Adapter 合同返回，不签发任何必需能力回执。"""

from src.batch_edit.content_observation_contract import ACTION, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults


def observe_with_adapter(adapter, *, defaults, product_query, store_name, target_identity, shop_id):
    target = adapter._require_frozen_target_identity(ACTION, target_identity, store_name)
    payload = validate_frozen_execution_defaults(defaults)
    context = adapter._execution_evidence_context
    if context.get('browser_session_id') != adapter.browser_session_id():
        raise RuntimeError('CONTENT_OBSERVATION_SESSION_DRIFT')
    result = dict(adapter.login_flow.observe_content_finalize(defaults=defaults, product_query=product_query,
        store_name=store_name, target_identity=target, shop_id=shop_id))
    validate_observation(result.get('content_finalize_observation'), payload=payload, target_identity=target,
                         shop_id=shop_id, context=context)
    return adapter._result(ACTION, result, before_values={'defaults': dict(defaults), 'product_query': product_query,
        'store_name': store_name, 'target_identity': target, 'shop_id': shop_id})
