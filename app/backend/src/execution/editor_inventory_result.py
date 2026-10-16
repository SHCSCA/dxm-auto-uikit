"""只读清单的 ActionResult 只证明观察有效，不证明填写完整或可恢复。"""

from src.batch_edit.editor_inventory_contract import ACTION, STATE, POSTCONDITIONS, validate_observation
from src.batch_edit.frozen_execution_contract import frozen_execution_defaults, validate_frozen_execution_defaults
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.editor_control_inventory import editor_control_inventory_summary
from src.services.structured_logging import get_logger, log_exception


def validate_editor_inventory_result(envelope, *, execution_mode, expected_payload):
    try:
        before = envelope['before_values']
        raw = envelope['evidence']['observations']['editor_inventory_observation']
        context = {**raw['command'], 'command_action': envelope['action'], 'mode': execution_mode,
            'runtime_id': envelope['page_identity']['runtime_id'], 'browser_session_id': envelope['page_identity']['browser_session_id']}
        payload = validate_frozen_execution_defaults(before['defaults'], expected_payload=expected_payload)
        if (envelope['action'] != ACTION or envelope['attempted_state'] != STATE
                or expected_payload is not None and payload != expected_payload
                or canonical_sha256(before['defaults']) != canonical_sha256(frozen_execution_defaults(payload))
                or set(before) != {'defaults', 'category_schema', 'product_query', 'store_name', 'shop_id', 'target_identity'}
                or before['product_query'] != str(payload['product_id'])):
            raise ValueError('EDITOR_INVENTORY_RESULT_COMMAND_OR_PAYLOAD_DRIFT')
        observed = validate_observation(raw, payload=payload, category_schema=before['category_schema'],
            target_identity=before['target_identity'], shop_id=before['shop_id'], context=context)
        forbidden = {'mandatory_capability_receipts', 'rollback_preparation', 'path_b_section_receipts'}
        if (envelope['after_values'] != {'editor_control_inventory': editor_control_inventory_summary(observed['after'])}
                or envelope['postconditions'] != dict.fromkeys(POSTCONDITIONS, True)
                or envelope['page_identity']['url'] != observed['observation']['page_url']
                or forbidden.intersection(envelope['evidence']['observations'])):
            raise ValueError('EDITOR_INVENTORY_RESULT_DRIFT')
    except Exception as exc:
        log_exception(get_logger('editor.inventory_result'), 'editor_inventory_result_rejected', exc)
        if isinstance(exc, ValueError):
            raise
        raise ValueError('EDITOR_INVENTORY_RESULT_MALFORMED') from exc
