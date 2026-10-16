from copy import deepcopy

import pytest

from src.batch_edit.native_video_inputs import (
    resolve_native_video_inputs, validate_native_video_generation_rule,
)
from src.batch_edit.plan_template_contract import PlanTemplateContractError, validate_editor_actions
from src.batch_edit.scope_contract import canonical_sha256


EXPLICIT_RULE = {
    'image_selection': 'first_product_images', 'image_count': 5,
    'transition': 1, 'music': {'mode': 'none'},
}


def _config(rule):
    return {'enabled': True, 'failure_strategy': 'pause', 'max_wait_seconds': 300,
            'poll_interval_seconds': 5, 'generation_rule': deepcopy(rule)}


def _default_rule(kind):
    rule = deepcopy(EXPLICIT_RULE)
    if kind in {'transition', 'both', 'all'}:
        rule['transition'] = {'mode': 'native_default'}
    if kind in {'music', 'both', 'all'}:
        rule['music'] = {'mode': 'native_default'}
    if kind in {'images', 'all'}:
        rule['image_selection'] = 'native_default'
        rule.pop('image_count')
    return rule


@pytest.mark.parametrize('kind', ['transition', 'music', 'both', 'images', 'all'])
def test_exact_native_default_policies_are_shared_hash_bound_and_not_mutated(kind):
    rule = _default_rule(kind)
    before = deepcopy(rule)
    validate_native_video_generation_rule(rule)
    validate_editor_actions({'video': _config(rule)})
    assert rule == before
    assert canonical_sha256(_config(rule)) != canonical_sha256(_config(EXPLICIT_RULE))


@pytest.mark.parametrize('kind', ['transition', 'music', 'both', 'images', 'all'])
def test_native_defaults_require_independent_current_modal_observation(kind, caplog):
    config = _config(_default_rule(kind))
    before = deepcopy(config)
    with pytest.raises(ValueError, match='VIDEO_NATIVE_MODAL_OBSERVATION_REQUIRED'):
        resolve_native_video_inputs(config, ['https://example.invalid/a.jpg'] * 5, [])
    assert config == before
    assert 'native_video_inputs_rejected' in caplog.text
    assert 'https://example.invalid/a.jpg' not in caplog.text


@pytest.mark.parametrize('observation', [
    {}, True,
    {'transition': 0, 'music': {'mode': 'none'}},
    {'schema': 'dxm.editor_content_surface.v1', 'action': 'video', 'surface_match_count': 1,
     'transitions': {'matches': [{'selected': True, 'labels': ['自然']}]},
     'music': {'matches': [{'selected': True, 'labels': ['无音乐']}]},
     'write_attempted': False, 'execution_allowed': False},
    {'browser_session_id': 'private-session', 'product_id': 'other-product',
     'modal_id': 'historical-modal', 'transition': 2, 'music': {'mode': 'library', 'id': '31'}},
])
def test_unreviewed_or_mismatched_observations_never_resolve_defaults(observation):
    with pytest.raises(ValueError, match='VIDEO_NATIVE_MODAL_OBSERVATION_UNVERIFIED'):
        resolve_native_video_inputs(_config(_default_rule('all')), [], [], native_modal_observation=observation)


@pytest.mark.parametrize('field,value', [
    ('transition', 'native_default'),
    ('transition', {'mode': 'native_default', 'value': 0}),
    ('transition', {'mode': 'default'}),
    ('music', 'native_default'),
    ('music', {'mode': 'native_default', 'id': '31'}),
    ('music', {'mode': 'native_default', 'value': None}),
    ('image_selection', {'mode': 'native_default'}),
])
def test_default_policy_markers_reject_ambiguous_values_and_guessed_defaults(field, value):
    rule = deepcopy(EXPLICIT_RULE)
    rule[field] = value
    with pytest.raises(PlanTemplateContractError, match='VIDEO_SHARED_'):
        validate_editor_actions({'video': _config(rule)})


def test_native_image_policy_cannot_mix_with_first_n_or_silently_change_count():
    native = _default_rule('images')
    with pytest.raises(ValueError, match='VIDEO_SHARED_GENERATION_RULE_INVALID'):
        validate_native_video_generation_rule({**native, 'image_count': 5})
    explicit = deepcopy(EXPLICIT_RULE)
    explicit.pop('image_count')
    with pytest.raises(ValueError, match='VIDEO_SHARED_GENERATION_RULE_INVALID'):
        validate_native_video_generation_rule(explicit)
    for count in (1, True, 9):
        with pytest.raises(ValueError, match='VIDEO_SHARED_GENERATION_RULE_INVALID'):
            validate_native_video_generation_rule({**EXPLICIT_RULE, 'image_count': count})
    assert _config(EXPLICIT_RULE)['generation_rule']['image_count'] == 5


def test_explicit_generation_rule_keeps_existing_values_and_independent_music_copy():
    from src.batch_edit import video_generator

    assert video_generator.resolve_native_video_inputs is resolve_native_video_inputs
    assert video_generator.validate_native_video_generation_rule is validate_native_video_generation_rule
    images = [f'https://example.invalid/{index}.jpg' for index in range(7)]
    explicit = _config(EXPLICIT_RULE)
    assert resolve_native_video_inputs(explicit, images, []) == {
        'images': images[:5], 'transition': 1, 'transition_label': '自然', 'music': {'mode': 'none'},
    }
    rule = {**EXPLICIT_RULE, 'transition': 0, 'music': {'mode': 'library', 'id': '31'}}
    catalog = [{'id': 31, 'fileUrl': 'https://example.invalid/music.mp3'}]
    resolved = resolve_native_video_inputs(_config(rule), images, catalog)
    assert resolved['transition'] == 0
    assert resolved['transition_label'] == '无转场效果'
    assert resolved['music']['record'] == catalog[0]
    resolved['music']['record']['id'] = 'changed'
    assert catalog[0]['id'] == 31
