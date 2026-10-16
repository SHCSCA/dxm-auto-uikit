"""在已有只读检查中双读视频输入并截图；不把当前选择冒充初始默认或冻结来源。"""

import uuid
from datetime import datetime, timezone

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.native_video_dom_observation import collect_native_video_dom_observation
from src.services.structured_logging import get_logger, log_exception


def observe_video_input_diagnostic(page, *, screenshot_dir, describe_evidence):
    started = datetime.now(timezone.utc).isoformat()
    result = {'schema': 'dxm.native_video_input_diagnostic.v1', 'started_at': started,
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
        'write_attempted': False, 'default_provenance': 'not_bound_to_native_reveal',
        'double_read_completed': False, 'stable_across_screenshot': False,
        'limitations': ['NATIVE_VIDEO_INITIAL_DEFAULT_LIFECYCLE_NOT_BOUND',
                        'NATIVE_VIDEO_TRUSTED_FREEZE_SOURCE_NOT_BOUND']}
    navigations, listener_added = [], False
    frame, page_url = None, None

    def navigated(observed_frame):
        if observed_frame is frame or observed_frame is page.main_frame:
            navigations.append('main_frame_navigation')

    try:
        page_url = str(page.url)
        frame = page.main_frame
        listener_added = True
        page.on('framenavigated', navigated)
        before = collect_native_video_dom_observation(page)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot = screenshot_dir / f'native-video-input-{uuid.uuid4().hex}.png'
        page.screenshot(path=str(screenshot), full_page=True)
        after = collect_native_video_dom_observation(page)
        result.update({'page_url': page_url, 'before': before, 'after': after,
            'before_sha256': canonical_sha256(before), 'after_sha256': canonical_sha256(after),
            'evidence_ref': describe_evidence(screenshot),
            'double_read_completed': before.get('collected') is True and after.get('collected') is True})
        if not result['double_read_completed']:
            result['limitations'].append('NATIVE_VIDEO_INPUT_READ_INCOMPLETE')
    except Exception as exc:
        log_exception(get_logger('native_video.diagnostic'), 'native_video_input_diagnostic_failed', exc)
        result['limitations'].append('NATIVE_VIDEO_INPUT_DIAGNOSTIC_FAILED')
    finally:
        if listener_added:
            try:
                page.remove_listener('framenavigated', navigated)
            except Exception as exc:
                log_exception(get_logger('native_video.diagnostic'), 'native_video_diagnostic_cleanup_failed', exc)
                result['limitations'].append('NATIVE_VIDEO_INPUT_LISTENER_CLEANUP_FAILED')
    try:
        same_page = page_url == str(page.url) and frame is page.main_frame and not navigations
        result['same_page'] = same_page
        result['main_frame_navigation_count'] = len(navigations)
        result['stable_across_screenshot'] = (result['double_read_completed'] and same_page
            and result.get('before') == result.get('after')
            and 'NATIVE_VIDEO_INPUT_LISTENER_CLEANUP_FAILED' not in result['limitations'])
        if not result['stable_across_screenshot']:
            result['limitations'].append('NATIVE_VIDEO_INPUT_CHANGED_OR_UNPROVEN')
    except Exception as exc:
        log_exception(get_logger('native_video.diagnostic'), 'native_video_diagnostic_identity_failed', exc)
        result['limitations'].append('NATIVE_VIDEO_INPUT_IDENTITY_UNPROVEN')
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    return result


def video_diagnostic_summary(observation):
    return {key: observation[key] for key in ('schema', 'double_read_completed', 'stable_across_screenshot',
        'default_provenance', 'limitations', 'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed')}
