"""校验共享视频政策；默认值缺少当次原生观察时始终拒绝解析。"""

from copy import deepcopy
from urllib.parse import urlsplit

from src.services.structured_logging import get_logger, log_exception


_LOGGER = get_logger("native_video_inputs")
NATIVE_VIDEO_TRANSITIONS = {0: '无转场效果', 1: '自然', 2: '舒缓', 3: '动感', 4: '切换', 5: '柔和', 6: '覆盖'}


def _native_default(value):
    return isinstance(value, dict) and value == {'mode': 'native_default'}


def _validate_rule(rule):
    if not isinstance(rule, dict):
        raise ValueError('VIDEO_SHARED_GENERATION_RULE_INVALID')
    expected_keys = {'image_selection', 'transition', 'music'}
    if rule.get('image_selection') == 'first_product_images':
        expected_keys.add('image_count')
        valid_images = type(rule.get('image_count')) is int and 2 <= rule['image_count'] <= 8
    else:
        valid_images = rule.get('image_selection') == 'native_default'
    transition = rule.get('transition')
    if (set(rule) != expected_keys or not valid_images
            or not (_native_default(transition)
                    or type(transition) is int and transition in NATIVE_VIDEO_TRANSITIONS)):
        raise ValueError('VIDEO_SHARED_GENERATION_RULE_INVALID')
    music = rule['music']
    if not isinstance(music, dict) or not (
            _native_default(music) or music == {'mode': 'none'}
            or (set(music) == {'mode', 'id'} and music['mode'] == 'library'
                and isinstance(music['id'], str) and music['id'].strip() == music['id'] and bool(music['id']))):
        raise ValueError('VIDEO_SHARED_MUSIC_RULE_INVALID')


def validate_native_video_generation_rule(rule):
    """默认政策必须精确表达，不在政策校验阶段猜测弹窗实际值。"""
    try:
        _validate_rule(rule)
    except ValueError as exc:
        log_exception(_LOGGER, 'native_video_policy_rejected', exc)
        raise


def resolve_native_video_inputs(config, product_images, music_catalog, *, native_modal_observation=None):
    """解析明确输入；默认政策不提供生成、保存或生产能力授权。"""
    from src.batch_edit.plan_template_contract import validate_editor_actions

    try:
        validate_editor_actions({'video': config})
        rule = config.get('generation_rule')
        _validate_rule(rule)
        if (rule['image_selection'] == 'native_default'
                or _native_default(rule['transition']) or _native_default(rule['music'])):
            # 现有观察只有标签与选中态，尚无稳定值、当次绑定及可信生产来源。
            if native_modal_observation is None:
                raise ValueError('VIDEO_NATIVE_MODAL_OBSERVATION_REQUIRED')
            raise ValueError('VIDEO_NATIVE_MODAL_OBSERVATION_UNVERIFIED')
        if not isinstance(product_images, list) or any(not isinstance(value, str) for value in product_images):
            raise ValueError('VIDEO_PRODUCT_IMAGE_LIST_INVALID')
        selected = product_images[:rule['image_count']]
        if (len(selected) < 2 or len(set(selected)) != len(selected) or any(
                value != value.strip() or urlsplit(value).scheme not in {'http', 'https'} or not urlsplit(value).netloc
                or ',' in value or urlsplit(value).username is not None or urlsplit(value).password is not None for value in selected)):
            raise ValueError('VIDEO_SOURCE_IMAGES_INVALID')
        music = {'mode': 'none'}
        if rule['music']['mode'] == 'library':
            if not isinstance(music_catalog, list) or any(not isinstance(item, dict) for item in music_catalog):
                raise ValueError('VIDEO_MUSIC_CATALOG_REQUIRED')
            choices = [item for item in music_catalog if str(item.get('id', '')) == rule['music']['id']]
            if len(choices) != 1 or not isinstance(choices[0].get('fileUrl'), str) or not choices[0]['fileUrl'].strip():
                raise ValueError('VIDEO_MUSIC_ID_NOT_UNIQUE')
            music = {'mode': 'library', 'record': deepcopy(choices[0])}
        return {'images': list(selected), 'transition': rule['transition'],
                'transition_label': NATIVE_VIDEO_TRANSITIONS[rule['transition']], 'music': music}
    except (ValueError, TypeError) as exc:
        log_exception(_LOGGER, 'native_video_inputs_rejected', exc)
        raise
