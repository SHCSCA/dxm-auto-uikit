"""独立最终观察的 ActionResult 必须与自身命令和实际双读完全一致。"""

from src.batch_edit.content_observation_contract import POSTCONDITIONS, validate_observation


def validate_content_observation_result(envelope, *, execution_mode, expected_payload):
    before = envelope['before_values']
    raw = envelope['evidence']['observations']['content_finalize_observation']
    context = {**raw['command'], 'command_action': envelope['action'], 'mode': execution_mode,
        'runtime_id': envelope['page_identity']['runtime_id'], 'browser_session_id': envelope['page_identity']['browser_session_id']}
    payload = before['defaults']['_frozen_execution_payload']
    if expected_payload is not None and payload != expected_payload:
        raise ValueError('CONTENT_OBSERVATION_PAYLOAD_DRIFT')
    observed = validate_observation(raw, payload=payload, target_identity=before['target_identity'],
        shop_id=before['shop_id'], context=context)
    if (envelope['after_values'] != {'content_observation': observed['observation']}
            or envelope['postconditions'] != dict.fromkeys(POSTCONDITIONS, True)
            or envelope['page_identity']['url'] != observed['observation']['page_url']
            or 'mandatory_capability_receipts' in envelope['evidence']['observations']):
        raise ValueError('CONTENT_OBSERVATION_RESULT_DRIFT')
