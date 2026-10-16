"""视频输入观察经现有 Adapter 返回；不签发视频完成回执。"""

from src.batch_edit.native_video_observation_contract import ACTION, POSTCONDITIONS, validate_observation
from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults


def observe_with_adapter(adapter, *, defaults, product_query, store_name, target_identity, shop_id):
    target = adapter._require_frozen_target_identity(ACTION, target_identity, store_name)
    payload = validate_frozen_execution_defaults(defaults)
    context = adapter._execution_evidence_context
    if context.get('browser_session_id') != adapter.browser_session_id():
        raise RuntimeError('VIDEO_INPUT_OBSERVATION_SESSION_DRIFT')
    result = dict(adapter.login_flow.observe_native_video_inputs(defaults=defaults, product_query=product_query,
        store_name=store_name, target_identity=target, shop_id=shop_id))
    validate_observation(result.get('native_video_input_observation'), payload=payload, target_identity=target,
                         shop_id=shop_id, context=context)
    return adapter._result(ACTION, result, before_values={'defaults': dict(defaults), 'product_query': product_query,
        'store_name': store_name, 'target_identity': target, 'shop_id': shop_id})


def validate_adapter_observation(sources, before_values, context):
    validate_observation(sources.get('native_video_input_observation'),
        payload=before_values['defaults']['_frozen_execution_payload'], target_identity=before_values['target_identity'],
        shop_id=before_values['shop_id'], context=context)
    return dict.fromkeys(POSTCONDITIONS, True)
