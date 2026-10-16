"""合成观察仅用于验证合同，不证明生产 DOM 可达或提供生产输入来源。"""

from copy import deepcopy

from src.batch_edit.native_video_observation_contract import SCHEMA, command_binding
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.native_video_script_capture import REVIEWED_VIDEO_SCRIPTS
from src.execution.native_video_value_bindings import PROFILE, SCHEMA as VALUE_SCHEMA, TRANSITION_GIFS


def make_bindings(*, images=None, transition=1):
    urls = images or ['https://fixture.invalid/selected-a.png', 'https://fixture.invalid/selected-b.png']
    return {'schema': VALUE_SCHEMA, 'collected': True, 'missing': [], 'document_time_origin': 1792108800000.0,
        'instance': {'uid': 7, 'type_name': 'ImgToVideoModal', 'mounted': True, 'visible': True, 'vnode_dom_bound': True},
        'images': {'sort_list_urls': list(urls), 'dom_urls': list(urls), 'loaded_urls': list(urls)},
        'transition': {'options': [{'raw_gif': gif, 'value': index, 'active': index == transition}
                                 for index, gif in enumerate(TRANSITION_GIFS)], 'selected_value': transition},
        'music': {'active_count': 1, 'none_branch_observed': True, 'stable_id': None},
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False}


def make_observation(*, payload, target_identity, context, shop_id, evidence_ref,
                     started_at='2026-10-16T00:00:01Z', completed_at='2026-10-16T00:00:02Z'):
    raw = make_bindings()
    return {'schema': SCHEMA, 'command': command_binding(context), 'execution_payload_hash': payload['payload_hash'],
        'started_at': started_at, 'completed_at': completed_at,
        'source_profile': {'schema': 'dxm.native_video_static_capture.v1', 'profile': PROFILE, 'window_closed': True,
            'document_bound': True, 'document_invalid': False, 'reviewed_resources_match': True, 'missing_resources': [],
            'resources': [{'name': name, 'request_finished': True, 'sha256': digest, 'matches_reviewed': True, 'size': size}
                          for name, (size, digest) in REVIEWED_VIDEO_SCRIPTS.items()], 'issues': [],
            'body_read_count': len(REVIEWED_VIDEO_SCRIPTS),
            'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False},
        'lifecycle': {'page_lifetime_observed': True, 'document_navigation_count': 1, 'same_document': True,
            'reveal_count': 1, 'visible_before': 0, 'visible_after': 1, 'interaction_count': 1, 'unexpected_interactions': [],
            'native_defaults': True, 'native_component_uid': 7, 'owner_observation_id': 'a' * 32,
            'document_time_origin': raw['document_time_origin']},
        'before': raw, 'after': deepcopy(raw), 'effect_facts': {'request_facts': [], 'unexpected_effects': []},
        'observation': {'product_id': str(payload['product_id']), 'shop_id': str(shop_id),
            'browser_session_id': context['browser_session_id'],
            'page_url': f'https://www.dianxiaomi.com/web/smt/edit?id={payload["product_id"]}',
            'target_identity_sha256': canonical_sha256(target_identity), 'observed_at': completed_at,
            'inputs': {'images': list(raw['images']['sort_list_urls']), 'transition': 1, 'music': {'mode': 'none'}},
            'evidence_ref': deepcopy(evidence_ref), 'write_attempted': False}}
