from copy import deepcopy
from datetime import datetime
import json

import pytest

from src.batch_edit.content_finalize_sources import require_reviewed_video_source
from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError
from src.batch_edit.native_video_inputs import resolve_native_video_inputs
from src.execution import native_video_diagnostic as diagnostic


class SyntheticPage:
    def __init__(self, *, screenshot_effect=None, screenshot_error=None,
                 registration_error=None, cleanup_error=None, cleanup_effect=None):
        self.url = 'https://example.invalid/editor?id=synthetic-product'
        self.main_frame = object()
        self.listeners = {}
        self.events = []
        self.screenshot_effect = screenshot_effect
        self.screenshot_error = screenshot_error
        self.registration_error = registration_error
        self.cleanup_error, self.cleanup_effect = cleanup_error, cleanup_effect
        self.cleanup_attempts = 0

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)
        if self.registration_error:
            raise self.registration_error

    def remove_listener(self, event, handler):
        self.cleanup_attempts += 1
        if self.cleanup_effect:
            self.cleanup_effect(self)
        if self.cleanup_error:
            raise self.cleanup_error
        self.listeners[event].remove(handler)

    def emit(self, event, value):
        for handler in list(self.listeners.get(event, [])):
            handler(value)

    def screenshot(self, *, path, full_page):
        self.events.append('screenshot')
        assert full_page is True
        if self.screenshot_error:
            raise self.screenshot_error
        if self.screenshot_effect:
            self.screenshot_effect(self)
        from pathlib import Path
        Path(path).write_bytes(b'synthetic-diagnostic-screenshot')


def candidate():
    return {'schema': 'dxm.native_video_dom_diagnostic.v1', 'collected': True,
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False,
        'actual': {'images': {'selectedUrlsCandidate': ['https://example.invalid/private-raw-image.jpg']},
                   'music': {'candidates': [{'text': 'private-raw-music'}], 'stableId': None}},
        'missing': ['VIDEO_MUSIC_STABLE_ID_OR_SILENCE_MISSING']}


def install_reads(monkeypatch, page, values):
    reads = iter(values)

    def collect(observed_page):
        assert observed_page is page
        page.events.append('read')
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)

    monkeypatch.setattr(diagnostic, 'collect_native_video_dom_observation', collect)


def observe(page, tmp_path, *, describe_evidence=None):
    return diagnostic.observe_video_input_diagnostic(page, screenshot_dir=tmp_path / 'screenshots',
        describe_evidence=describe_evidence or (lambda path: {'path': str(path), 'size': path.stat().st_size}))


def assert_no_authority(result):
    assert result['executionAllowed'] is False
    assert result['capabilityCertified'] is False
    assert result['inputFreezeAllowed'] is False
    assert result['write_attempted'] is False
    assert result['default_provenance'] == 'not_bound_to_native_reveal'


def test_two_independent_reads_bracket_screenshot_but_remain_diagnostic(monkeypatch, tmp_path):
    page = SyntheticPage()
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    assert page.events == ['read', 'screenshot', 'read']
    assert result['double_read_completed'] is True
    assert result['stable_across_screenshot'] is True
    assert result['before'] == result['after']
    assert result['before_sha256'] == result['after_sha256']
    assert datetime.fromisoformat(result['started_at']).tzinfo is not None
    assert datetime.fromisoformat(result['completed_at']) >= datetime.fromisoformat(result['started_at'])
    assert_no_authority(result)
    assert not any(page.listeners.values())


def test_raw_observation_values_and_page_identity_never_escape_summary(monkeypatch, tmp_path):
    page = SyntheticPage()
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    summary = diagnostic.video_diagnostic_summary(result)
    assert set(summary) == {'schema', 'double_read_completed', 'stable_across_screenshot', 'default_provenance',
        'limitations', 'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'}
    serialized = json.dumps(summary)
    for raw in ('private-raw-image', 'private-raw-music', 'synthetic-product', 'screenshots'):
        assert raw not in serialized
    assert all(summary[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))


@pytest.mark.parametrize('drift', ['raw_value', 'url', 'main_frame', 'same_url_navigation'])
def test_drift_during_screenshot_cannot_be_reported_as_stable(monkeypatch, tmp_path, drift):
    before, after = candidate(), candidate()
    if drift == 'raw_value':
        after['actual']['images']['selectedUrlsCandidate'].reverse()
        after['actual']['images']['selectedUrlsCandidate'].append('https://example.invalid/drift.jpg')
    def effect(page):
        if drift == 'url':
            page.url += '&drift=true'
        elif drift == 'main_frame':
            page.main_frame = object()
        elif drift == 'same_url_navigation':
            page.emit('framenavigated', page.main_frame)
    page = SyntheticPage(screenshot_effect=effect)
    install_reads(monkeypatch, page, [before, after])
    result = observe(page, tmp_path)
    assert result['stable_across_screenshot'] is False
    assert 'NATIVE_VIDEO_INPUT_CHANGED_OR_UNPROVEN' in result['limitations']
    assert_no_authority(result)
    assert not any(page.listeners.values())


@pytest.mark.parametrize('read_index', [0, 1])
def test_read_exception_is_logged_without_leaking_raw_value(monkeypatch, tmp_path, caplog, read_index):
    page = SyntheticPage()
    values = [candidate(), candidate()]
    values[read_index] = RuntimeError('synthetic read unavailable')
    install_reads(monkeypatch, page, values)
    result = observe(page, tmp_path)
    assert result['double_read_completed'] is False
    assert result['stable_across_screenshot'] is False
    assert 'NATIVE_VIDEO_INPUT_DIAGNOSTIC_FAILED' in result['limitations']
    assert 'native_video_input_diagnostic_failed' in caplog.text
    assert 'private-raw-image' not in caplog.text
    assert_no_authority(result)
    assert not any(page.listeners.values())


def test_two_real_collector_failure_envelopes_do_not_form_stable_success(tmp_path, caplog):
    page = SyntheticPage()
    def unavailable(_script):
        raise RuntimeError('synthetic DOM read unavailable')
    page.evaluate = unavailable
    result = observe(page, tmp_path)
    assert result['stable_across_screenshot'] is False
    assert result['double_read_completed'] is False
    assert 'NATIVE_VIDEO_INPUT_READ_INCOMPLETE' in result['limitations']
    assert 'native_video_dom_diagnostic_failed' in caplog.text
    assert_no_authority(result)
    assert not any(page.listeners.values())


def test_screenshot_failure_is_logged_and_skips_second_read(monkeypatch, tmp_path, caplog):
    page = SyntheticPage(screenshot_error=RuntimeError('synthetic screenshot unavailable'))
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    assert page.events == ['read', 'screenshot']
    assert result['double_read_completed'] is False
    assert result['stable_across_screenshot'] is False
    assert 'native_video_input_diagnostic_failed' in caplog.text
    assert_no_authority(result)
    assert not any(page.listeners.values())


@pytest.mark.parametrize('phase', ['registration', 'cleanup'])
def test_listener_failure_is_logged_attempts_cleanup_and_cannot_stabilize(monkeypatch, tmp_path, caplog, phase):
    error = RuntimeError('synthetic listener unavailable')
    page = SyntheticPage(registration_error=error if phase == 'registration' else None,
                         cleanup_error=error if phase == 'cleanup' else None)
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    assert page.cleanup_attempts == 1
    assert result['stable_across_screenshot'] is False
    if phase == 'registration':
        assert result['double_read_completed'] is False
        assert 'native_video_input_diagnostic_failed' in caplog.text
        assert not any(page.listeners.values())
    else:
        assert 'native_video_diagnostic_cleanup_failed' in caplog.text
        assert 'NATIVE_VIDEO_INPUT_LISTENER_CLEANUP_FAILED' in result['limitations']
    assert_no_authority(result)


def test_main_frame_navigation_during_cleanup_invalidates_final_stability(monkeypatch, tmp_path):
    page = SyntheticPage(cleanup_effect=lambda observed: observed.emit('framenavigated', observed.main_frame))
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    assert result['double_read_completed'] is True
    assert result['stable_across_screenshot'] is False
    assert result['main_frame_navigation_count'] == 1
    assert 'NATIVE_VIDEO_INPUT_CHANGED_OR_UNPROVEN' in result['limitations']
    assert_no_authority(result)
    assert not any(page.listeners.values())


def test_diagnostic_is_rejected_by_native_input_parser_and_finalize_source(monkeypatch, tmp_path):
    page = SyntheticPage()
    install_reads(monkeypatch, page, [candidate(), candidate()])
    result = observe(page, tmp_path)
    config = {'enabled': True, 'failure_strategy': 'pause', 'max_wait_seconds': 300,
        'poll_interval_seconds': 5, 'generation_rule': {'image_selection': 'native_default',
            'transition': {'mode': 'native_default'}, 'music': {'mode': 'native_default'}}}
    with pytest.raises(ValueError, match='VIDEO_NATIVE_MODAL_OBSERVATION_UNVERIFIED'):
        resolve_native_video_inputs(config, [], [], native_modal_observation=result)
    with pytest.raises(FrozenExecutionContractError) as failure:
        require_reviewed_video_source({'BATCH_VIDEO_SUBMIT': result, 'BATCH_VIDEO_PLACE': result})
    assert failure.value.reason_code == 'CONTENT_FINALIZE_VIDEO_SOURCE_NOT_BOUND'
    assert_no_authority(result)
