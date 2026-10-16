"""首次原生弹窗的私有默认值诊断；缺证保留，不建立输入冻结或执行来源。"""

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.native_video_value_bindings import collect_native_video_value_bindings, validate_value_bindings
from src.services.structured_logging import get_logger, log_exception


def observe_inspection_video(owner, *, screenshot_dir, describe_evidence):
    import uuid
    result = {'schema': 'dxm.native_video_input_diagnostic.v1', 'executionAllowed': False,
        'capabilityCertified': False, 'inputFreezeAllowed': False, 'write_attempted': False,
        'default_provenance': 'unverified', 'double_read_completed': False,
        'stable_across_screenshot': False, 'limitations': ['NATIVE_VIDEO_TRUSTED_FREEZE_SOURCE_NOT_BOUND']}
    owner.require_document()
    lifetime = owner.rpc(owner.lifetime.read)
    if any(lifetime[key] != 1 for key in ('reveal_count', 'entry_click_count', 'visible_count')):
        raise RuntimeError('EDITOR_INSPECTION_VIDEO_REVEAL_UNPROVEN')
    profile = owner.rpc(owner.lifetime.profile.snapshot)
    before = owner.rpc(collect_native_video_value_bindings, owner.page)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = screenshot_dir / f'native-video-inspection-{uuid.uuid4().hex}.png'
    owner.rpc(owner.page.screenshot, path=str(path), full_page=True, caret='initial')
    after = owner.rpc(collect_native_video_value_bindings, owner.page)
    final = owner.rpc(owner.lifetime.read)
    current_profile = owner.rpc(owner.lifetime.profile.snapshot)
    result.update(before=before, after=after, before_sha256=canonical_sha256(before), after_sha256=canonical_sha256(after),
        lifecycle_before=lifetime, lifecycle_after=final, evidence_ref=describe_evidence(path))
    try:
        first_values, actual = validate_value_bindings(before), validate_value_bindings(after)
        if any(canonical_sha256(first) != canonical_sha256(second) for first, second in
                ((before, after), (first_values, actual), (lifetime, final), (profile, current_profile),
                 (before['document_time_origin'], lifetime['document_time_origin']))):
            raise ValueError('NATIVE_VIDEO_INSPECTION_READBACK_DRIFT')
        result['double_read_completed'] = True
        result['stable_across_screenshot'] = True
        if current_profile['reviewed_resources_match'] is True:
            result.update(default_provenance='initial_native_modal_observed', actual=actual)
        else:
            result['limitations'].append('NATIVE_VIDEO_STATIC_PROFILE_UNVERIFIED')
    except ValueError as exc:
        log_exception(get_logger('editor.inspection'), 'editor_inspection_video_values_unverified', exc)
        result['limitations'].append('NATIVE_VIDEO_DEFAULT_VALUES_UNVERIFIED')
        result['limitations'].extend(sorted(set(before.get('missing', []) + after.get('missing', []))))
    return result


def finalize_inspection_video(owner, diagnostic, profile):
    final = owner.rpc(owner.lifetime.read)
    raw = owner.rpc(collect_native_video_value_bindings, owner.page)
    if (canonical_sha256(final) != canonical_sha256(diagnostic['lifecycle_after'])
            or canonical_sha256(raw) != canonical_sha256(diagnostic['after'])):
        raise RuntimeError('NATIVE_VIDEO_INSPECTION_FINAL_READBACK_DRIFT')
    if profile['reviewed_resources_match'] is not True:
        diagnostic['default_provenance'] = 'unverified'
        diagnostic.pop('actual', None)
        if 'NATIVE_VIDEO_STATIC_PROFILE_UNVERIFIED' not in diagnostic['limitations']:
            diagnostic['limitations'].append('NATIVE_VIDEO_STATIC_PROFILE_UNVERIFIED')
