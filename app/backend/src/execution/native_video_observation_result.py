"""输入观察结果必须属于实际只读命令，且不能夹带视频完成或写入授权。"""

from src.batch_edit.native_video_observation_contract import ACTION, STATE, POSTCONDITIONS, validate_observation


def validate_native_video_observation_result(envelope, *, execution_mode, expected_payload):
    before = envelope['before_values']
    raw = envelope['evidence']['observations']['native_video_input_observation']
    context = {**raw['command'], 'command_action': envelope['action'], 'mode': execution_mode,
        'runtime_id': envelope['page_identity']['runtime_id'], 'browser_session_id': envelope['page_identity']['browser_session_id']}
    payload = before['defaults']['_frozen_execution_payload']
    if (envelope['action'] != ACTION or envelope['attempted_state'] != STATE
            or expected_payload is not None and payload != expected_payload):
        raise ValueError('VIDEO_INPUT_OBSERVATION_PAYLOAD_OR_COMMAND_DRIFT')
    observed = validate_observation(raw, payload=payload, target_identity=before['target_identity'],
        shop_id=before['shop_id'], context=context)
    if (envelope['after_values'] != {'native_video_inputs': observed['observation']['inputs']}
            or envelope['postconditions'] != dict.fromkeys(POSTCONDITIONS, True)
            or envelope['page_identity']['url'] != observed['observation']['page_url']
            or 'mandatory_capability_receipts' in envelope['evidence']['observations']):
        raise ValueError('VIDEO_INPUT_OBSERVATION_RESULT_DRIFT')
