"""同一 Python owner 和页面生命周期的隔离异常回归，不构成页面授权。"""

from types import SimpleNamespace

import pytest

from src.execution import native_video_lifetime as subject
from tests.support.native_video_lifetime_case import FakePage, URL, install_profile_spy, started_owner


def test_owner_installs_before_navigation_observes_exact_document_and_closes_only_own_listener(monkeypatch):
    page, owner = started_owner(monkeypatch)
    foreign = lambda _frame: None
    page.on('framenavigated', foreign)
    assert page.events[0][0] == 'init_script' and page.events[2][0] == 'goto'
    assert owner.profile.expect_navigation is True and owner.profile.expected_url == URL
    assert owner.read()['document_time_origin'] == 1000.0
    assert owner.origin == 1000.0 and owner.navigation_count == 1
    owner.close(); owner.close()
    assert owner.closed and owner.profile.closed
    assert page.handlers['framenavigated'] == [foreign]
    assert page.events.count(('remove', 'framenavigated')) == 1
    with pytest.raises(RuntimeError, match='DOCUMENT_DRIFT'):
        owner.read()


def test_attaching_a_new_owner_after_goto_cannot_reconstruct_old_document_authority(monkeypatch):
    page, previous = started_owner(monkeypatch)
    previous.read(); previous.close()
    current = subject.NativeVideoLifetime(page, page_url=URL, session_id='session-1').start()
    assert current.owner_id != previous.owner_id
    assert sum(kind == 'init_script' for kind, _ in page.events) == 1
    with pytest.raises(RuntimeError, match='DOCUMENT_DRIFT'):
        current.read()
    current.close()


@pytest.mark.parametrize('change,reason', [
    (lambda page, owner: page.navigate(), 'DOCUMENT_DRIFT'),
    (lambda page, owner: page.navigate(URL.replace('10001', '10002')), 'DOCUMENT_DRIFT'),
    (lambda page, owner: setattr(page, 'main_frame', SimpleNamespace(url=URL)), 'DOCUMENT_DRIFT'),
    (lambda page, owner: page.value.update(closed_count=1), 'INTERACTION_OR_LIFETIME'),
    (lambda page, owner: page.value.update(duplicate_modal_seen=True), 'INTERACTION_OR_LIFETIME'),
    (lambda page, owner: page.value.update(unexpected_interactions=['click']), 'INTERACTION_OR_LIFETIME'),
    (lambda page, owner: page.value.update(document_time_origin=2000.0), 'DOCUMENT_ORIGIN_DRIFT'),
])
def test_document_and_interaction_drift_cannot_reuse_initial_default(monkeypatch, change, reason):
    page, owner = started_owner(monkeypatch)
    owner.read()
    change(page, owner)
    with pytest.raises(RuntimeError, match=reason):
        owner.read()
    owner.close()


def test_partial_listener_registration_is_removed_and_profile_closed(monkeypatch, caplog):
    install_profile_spy(monkeypatch)
    page = FakePage(); page.on_error = RuntimeError('partially registered listener')
    owner = subject.NativeVideoLifetime(page, page_url=URL, session_id='session-1')
    with pytest.raises(RuntimeError, match='partially registered'):
        owner.start()
    assert owner.closed and owner.profile.closed and page.handlers['framenavigated'] == []
    assert 'native_video_lifetime_start_failed' in caplog.text


def test_profile_start_failure_cleans_lifetime_listener_and_logs(monkeypatch, caplog):
    install_profile_spy(monkeypatch)
    page = FakePage()
    owner = subject.NativeVideoLifetime(page, page_url=URL, session_id='session-1')
    owner.profile.start_error = RuntimeError('profile start failed')
    with pytest.raises(RuntimeError, match='profile start failed'):
        owner.start()
    assert owner.closed and owner.profile.closed and page.handlers['framenavigated'] == []
    assert 'native_video_lifetime_start_failed' in caplog.text


def test_cleanup_listener_failure_invalidates_owner_and_records_error(monkeypatch, caplog):
    page, owner = started_owner(monkeypatch)
    page.cleanup_error = RuntimeError('listener cleanup failed')
    owner.close()
    assert owner.closed and owner.invalid and owner.listener_added is False
    assert 'native_video_lifetime_cleanup_failed' in caplog.text
    with pytest.raises(RuntimeError, match='DOCUMENT_DRIFT'):
        owner.read()


def test_profile_close_failure_still_attempts_lifetime_listener_cleanup(monkeypatch):
    page, owner = started_owner(monkeypatch)
    owner.profile.close_error = RuntimeError('profile close failed')
    with pytest.raises(RuntimeError, match='profile close failed'):
        owner.close()
    assert owner.closed and page.handlers['framenavigated'] == []


def test_begin_failure_cannot_leave_a_previous_owner_attached(monkeypatch, caplog):
    page, old = started_owner(monkeypatch)
    flow = SimpleNamespace(_execution_evidence_context={'mode': 'batch_draft_save'},
        _native_video_lifetime=old, browser_session_id=lambda: 'session-1')
    page.on_error = RuntimeError('new registration failed')
    subject.begin_native_video_lifetime(flow, page, URL)
    assert old.closed and flow._native_video_lifetime is None
    assert 'native_video_page_observation_unavailable' in caplog.text


@pytest.mark.parametrize('mode,url', [
    ('single_save', URL), ('batch_draft_save', URL.replace('https:', 'http:')),
    ('batch_draft_save', URL.replace('www.dianxiaomi.com', 'other.invalid')),
    ('batch_draft_save', URL + '&other=1'),
])
def test_non_product_or_non_batch_navigation_does_not_create_an_owner(monkeypatch, mode, url):
    install_profile_spy(monkeypatch)
    page = FakePage()
    flow = SimpleNamespace(_execution_evidence_context={'mode': mode}, browser_session_id=lambda: 'session-1')
    subject.begin_native_video_lifetime(flow, page, url)
    assert not hasattr(flow, '_native_video_lifetime') and page.events == []
