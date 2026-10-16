"""合成原生绑定仅验证诊断的跨模块身份与类型，不能提供现场默认或冻结。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.execution import editor_inspection_video as subject
from tests.support.native_video_observation_case import make_bindings


@pytest.mark.parametrize('change', ['origin', 'origin_type', 'second_read_type', 'failed_pair'])
def test_stable_dictionary_or_failed_pair_cannot_replace_native_document_identity(tmp_path, monkeypatch, change):
    raw = make_bindings()
    raw['document_time_origin'] = 1000
    reads = [deepcopy(raw), deepcopy(raw)]
    if change == 'origin':
        for value in reads:
            value['document_time_origin'] = 2000
    elif change == 'origin_type':
        for value in reads:
            value['document_time_origin'] = 1000.0
    elif change == 'second_read_type':
        reads[1]['document_time_origin'] = 1000.0
    else:
        for value in reads:
            value.update(collected=False, missing=['VIDEO_NATIVE_COMPONENT_BINDING_UNAVAILABLE'])
    iterator = iter(reads)
    monkeypatch.setattr(subject, 'collect_native_video_value_bindings', lambda _: deepcopy(next(iterator)))
    lifetime = {'document_time_origin': 1000, 'reveal_count': 1, 'entry_click_count': 1, 'visible_count': 1}
    profile = {'reviewed_resources_match': True}
    page = SimpleNamespace(screenshot=lambda path, **_: __import__('pathlib').Path(path).write_bytes(b'synthetic'))
    owner = SimpleNamespace(page=page, require_document=lambda: None, rpc=lambda function, *a, **k: function(*a, **k),
        lifetime=SimpleNamespace(read=lambda: deepcopy(lifetime), profile=SimpleNamespace(snapshot=lambda: deepcopy(profile))))
    result = subject.observe_inspection_video(owner, screenshot_dir=tmp_path, describe_evidence=lambda _: {'synthetic': True})
    assert result['default_provenance'] == 'unverified' and 'actual' not in result
    assert result['double_read_completed'] is False and result['stable_across_screenshot'] is False
    assert result['inputFreezeAllowed'] is False and result['executionAllowed'] is False
