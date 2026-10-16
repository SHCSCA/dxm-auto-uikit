"""只读入口真实方法的隔离接线测试，不提供真实页面或生产成功证据。"""

import json
from pathlib import Path

import pytest

from src.execution.dxm_login_flow import DxmLoginFlow
from src.services.dxm_draft_reader import DxmDraftReaderError
from tests.support.native_video_readonly_case import readonly_flow_case


def inspect(case, dialog='video'):
    return DxmLoginFlow.inspect_editor_readonly(case.flow, shop_id='91', product_id='8101',
        session_ref='session-ref', guard=case.guard, observe_dialog=dialog)


def private_report(summary):
    return json.loads(Path(summary['artifact']['path']).read_text(encoding='utf-8'))


def assert_cleaned(case):
    assert case.page.closed
    assert all(capture.closed for capture in case.captures)
    assert case.page.handlers.get('request', []) == []
    if case.captures:
        assert case.events.index('capture_close') < case.events.index('page_close')


def test_actual_readonly_entry_starts_capture_before_goto_and_keeps_raw_inputs_private(monkeypatch, tmp_path):
    case = readonly_flow_case(monkeypatch, tmp_path)
    summary = inspect(case)
    assert case.events.index('capture_start') < case.events.index('goto')
    assert case.events.count('reveal_click') == 1
    assert case.events.index('reveal_click') < case.events.index('video_diagnostic')
    assert case.events.index('video_diagnostic') < case.events.index('capture_close')
    assert case.events.index('page_close') < case.events.index('reader_after') < case.events.index('capture_snapshot')
    assert_cleaned(case)
    report = private_report(summary)
    assert report['videoInputDiagnostic']['before']['actual'] == 'private-video-before'
    assert report['contentSurface']['raw'] == 'private-dom-or-surface'
    assert report['videoInputSummary'] == summary['videoInputSummary']
    for raw_key in ('dom', 'beforeDom', 'overlayDom', 'entryProbe', 'contentSurface', 'videoInputDiagnostic'):
        assert raw_key not in summary
    assert 'private-video-' not in json.dumps(summary)
    assert 'private-dom-or-surface' not in json.dumps(summary)
    assert summary['ok'] is True
    assert summary['executionAllowed'] is False and summary['capabilityCertified'] is False
    assert summary['videoInputSummary']['inputFreezeAllowed'] is False
    assert summary['videoStaticSources']['reviewed_resources_match'] is True
    assert summary['videoStaticSources']['inputFreezeAllowed'] is False


@pytest.mark.parametrize('dialog', [None, 'translation'])
def test_non_video_inspection_never_starts_video_capture_or_collects_video_inputs(monkeypatch, tmp_path, dialog):
    case = readonly_flow_case(monkeypatch, tmp_path)
    summary = inspect(case, dialog)
    assert case.captures == []
    assert 'video_diagnostic' not in case.events and 'capture_start' not in case.events
    assert case.events.count('reveal_click') == (1 if dialog else 0)
    assert case.events.index('page_close') < case.events.index('reader_after')
    assert 'videoInputSummary' not in summary and 'videoStaticSources' not in summary
    assert 'videoInputDiagnostic' not in private_report(summary)
    assert_cleaned(case)


@pytest.mark.parametrize('fault,message', [
    ('goto', 'synthetic-goto-failure'),
    ('diagnostic', 'synthetic-diagnostic-failure'),
    ('capture_close', 'synthetic-capture-cleanup-failure'),
])
def test_goto_diagnostic_and_capture_cleanup_exceptions_always_close_owned_page(monkeypatch, tmp_path, fault, message):
    case = readonly_flow_case(monkeypatch, tmp_path, fault=fault)
    with pytest.raises(RuntimeError, match=message):
        inspect(case)
    assert_cleaned(case)
    assert 'reader_after' not in case.events
    assert list(tmp_path.rglob('*.json')) == []


@pytest.mark.parametrize('fault,click_count', [('reveal', 1), ('ambiguous', 0)])
def test_reveal_failure_or_ambiguity_cannot_be_promoted_by_video_diagnostic(monkeypatch, tmp_path, fault, click_count):
    case = readonly_flow_case(monkeypatch, tmp_path, fault=fault)
    summary = inspect(case)
    assert summary['dialogObservation']['reasonCode'] == 'EDITOR_DIALOG_REVEAL_FAILED'
    assert summary['ok'] is False
    assert case.events.count('reveal_click') == click_count
    assert summary['videoInputSummary']['stable_across_screenshot'] is True
    assert summary['videoInputSummary']['inputFreezeAllowed'] is False
    assert case.events.index('page_close') < case.events.index('reader_after')
    assert_cleaned(case)


def test_existing_guard_failure_stays_failed_despite_stable_video_and_matching_static_sources(monkeypatch, tmp_path):
    case = readonly_flow_case(monkeypatch, tmp_path, blocked_requests=1)
    summary = inspect(case)
    assert summary['ok'] is False
    assert summary['network']['blocked_request_count'] == 1
    assert summary['videoInputSummary']['stable_across_screenshot'] is True
    assert summary['videoStaticSources']['reviewed_resources_match'] is True
    assert summary['executionAllowed'] is False and summary['capabilityCertified'] is False
    assert_cleaned(case)


def test_reader_after_drift_is_checked_only_after_capture_and_page_cleanup(monkeypatch, tmp_path):
    case = readonly_flow_case(monkeypatch, tmp_path, fault='reader_drift')
    with pytest.raises(DxmDraftReaderError) as failure:
        inspect(case)
    assert failure.value.reason_code == 'EDITOR_INSPECTION_DATA_DRIFT'
    assert case.events.index('page_close') < case.events.index('reader_after')
    assert_cleaned(case)
    assert list(tmp_path.rglob('*.json')) == []
