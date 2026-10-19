"""合成事件只验证诊断与原清理顺序，不证明真实 transport、网络或登录能力。"""

from types import SimpleNamespace
from io import StringIO

import pytest

from src.execution import manual_login_context, manual_login_navigation as module
from tests.support.manual_login_case import Browser, Context, Page, make_case


class Emitter:
    def __init__(self):
        self.listeners, self.closed, self.connected = {}, False, True
        self.service_workers, self.main_frame = [], object()
        self._impl_obj = SimpleNamespace(_routes=[], _web_socket_routes=[])

    def on(self, name, callback):
        self.__dict__.setdefault('listeners', {}).setdefault(name, []).append(callback)
        if getattr(self, 'fail_registration', False):
            raise ValueError('private registration detail')

    def remove_listener(self, name, callback):
        listeners = self.__dict__.setdefault('listeners', {}).get(name, [])
        if callback in listeners:
            listeners.remove(callback)
        if getattr(self, 'fail_removal', False):
            raise ValueError('private removal detail')

    def emit(self, name, *args):
        for callback in list(self.listeners.get(name, [])):
            callback(*args)

    def is_closed(self):
        return self.closed

    def is_connected(self):
        return self.connected


@pytest.fixture
def records(monkeypatch):
    events = []
    monkeypatch.setattr(module, 'log_event', lambda _logger, event, **fields: events.append((event, fields)))
    return events


@pytest.fixture
def case(monkeypatch, records):
    browser, context, page = Emitter(), Emitter(), Emitter()
    context._impl_obj._routes, context._impl_obj._web_socket_routes = [object()], [object()]
    transport = SimpleNamespace(installed=True, invalid=False, active=None,
        _policy=lambda: pytest.fail('诊断不得调用政策校验'))
    monkeypatch.setitem(module._TRANSPORTS, context, transport)
    tracker = module.ManualLoginNavigation(SimpleNamespace(stopped=False))
    tracker.bind_browser(browser)
    tracker.bind_context(context)
    tracker.bind_page(page)
    return SimpleNamespace(tracker=tracker, browser=browser, context=context, page=page, transport=transport)


def request(case, failure='net::ERR_FAILED'):
    return SimpleNamespace(failure=failure, frame=case.page.main_frame, is_navigation_request=lambda: True,
        url='https://private.invalid/SECRET', headers={'private': 'SECRET'}, body='SECRET')


def test_failure_snapshot_is_frozen_before_cleanup_and_returns_only_a_copy(case, records):
    before = case.tracker.snapshot_failure()
    assert before['context_open'] is before['browser_connected'] is True
    assert before['transport_invalid'] is before['transport_active'] is False
    assert before['context_http_route_count'] == before['context_ws_route_count'] == 1
    case.context.closed = case.transport.invalid = True
    case.context.emit('close')
    case.browser.connected = False
    assert case.tracker.snapshot_failure() == before
    before['context_open'] = False
    assert case.tracker.snapshot_failure()['context_open'] is True
    assert len([event for event, _ in records if event.endswith('failure_before_cleanup')]) == 1
    case.tracker.close()


@pytest.mark.parametrize('cause', ['serviceworker', 'context_close', 'disconnected', 'active', 'invalid'])
def test_preexisting_failure_facts_are_not_confused_with_later_cleanup(case, cause):
    if cause == 'serviceworker':
        case.transport.invalid = True
        case.context.emit('serviceworker', object())
    elif cause == 'context_close':
        case.context.closed = case.transport.invalid = True
        case.context.emit('close')
    elif cause == 'disconnected':
        case.browser.connected = False
        case.browser.emit('disconnected')
    else:
        setattr(case.transport, cause, object() if cause == 'active' else True)
    facts = case.tracker.snapshot_failure()
    assert facts['serviceworker_count'] == (cause == 'serviceworker')
    assert facts['context_close_count'] == (cause == 'context_close')
    assert facts['browser_disconnected_count'] == (cause == 'disconnected')
    assert facts['transport_active'] is (cause == 'active')
    case.tracker.close()


@pytest.mark.parametrize('failure', ['net::ERR_FAILED', 'net::ERR_NAME_NOT_RESOLVED', None,
    'net::ERR_FAILED https://private.invalid/SECRET', 'net::ERR_FAILED\nSECRET', 'net::ERR_' + 'A' * 65])
def test_only_complete_bounded_native_error_codes_are_logged(case, records, failure):
    case.context.emit('requestfailed', request(case, failure))
    facts = case.tracker.snapshot_failure()
    accepted = failure in {'net::ERR_FAILED', 'net::ERR_NAME_NOT_RESOLVED'}
    assert facts['request_failure_code'] == (failure if accepted else None)
    assert facts['navigation_failure_count'] == facts['main_navigation_failure_count'] == 1
    assert facts['unclassified_failure_count'] == (not accepted)
    assert all(token not in str(records) for token in ('SECRET', 'private.invalid', 'headers', 'body'))
    assert all(type(value) in (bool, int, str, type(None)) for value in facts.values())
    case.tracker.close()


@pytest.mark.parametrize('value', [None, 0, 1, 'open'])
def test_non_boolean_closed_return_is_unknown_instead_of_coerced(case, value):
    case.context.is_closed = lambda: value
    facts = case.tracker.snapshot_failure()
    assert facts['context_open'] is None and facts['read_error_count'] == 1
    case.tracker.close()


def test_missing_objects_are_nullable_without_read_error_noise(records):
    tracker = module.ManualLoginNavigation(SimpleNamespace())
    facts = tracker.snapshot_failure()
    assert facts['context_present'] is facts['browser_present'] is facts['transport_present'] is False
    assert facts['context_open'] is facts['browser_connected'] is facts['transport_invalid'] is None
    assert facts['read_error_count'] == 0
    tracker.close()


def test_partial_registration_and_removal_failure_clean_exact_callbacks_and_disable_late_events(case, records):
    case.tracker.close()
    external = lambda *_: None
    case.context.on('close', external)
    case.context.fail_registration = case.context.fail_removal = True
    tracker = module.ManualLoginNavigation(SimpleNamespace())
    tracker.bind_context(case.context)
    old_callbacks = list(tracker._listeners)
    tracker.close()
    assert case.context.listeners['close'] == [external]
    assert all(not listeners for name, listeners in case.context.listeners.items() if name != 'close')
    counts = dict(tracker._counts)
    for _, _, callback in old_callbacks:
        callback(request(case))
    assert tracker._counts == counts and counts['registration_error_count'] == counts['removal_error_count'] == 3
    assert 'private registration detail' not in str(records) and 'private removal detail' not in str(records)


def test_old_callbacks_cannot_pollute_new_tracker(case):
    callbacks = list(case.tracker._listeners)
    case.tracker.close()
    fresh = module.ManualLoginNavigation(SimpleNamespace())
    fresh.bind_context(case.context)
    for _, _, callback in callbacks:
        callback(request(case))
    assert fresh._counts['requestfailed_count'] == 0
    case.context.emit('requestfailed', request(case))
    assert fresh._counts['requestfailed_count'] == 1
    fresh.close()


def test_callback_read_snapshot_and_logging_failures_do_not_escape(case, records, monkeypatch):
    class BrokenRequest:
        @property
        def failure(self):
            raise ValueError('SECRET')
    case.context.emit('requestfailed', BrokenRequest())
    case.context.emit('requestfailed')
    assert case.tracker._counts['read_error_count'] == 2 and case.tracker._counts['callback_error_count'] == 1
    monkeypatch.setattr(case.tracker, '_snapshot', lambda: (_ for _ in ()).throw(ValueError('SECRET')))
    monkeypatch.setattr(module, 'log_event', lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError('SECRET')))
    stream = StringIO()
    monkeypatch.setattr(module._HANDLER, 'stream', stream)
    facts = case.tracker.snapshot_failure()
    assert facts['snapshot_complete'] is False and facts['snapshot_error_count'] == 1
    assert 'manual_login_navigation_log_failed' in stream.getvalue() and 'SECRET' not in stream.getvalue()
    case.tracker.close()


@pytest.mark.parametrize('fail_goto', [False, True])
def test_actual_manual_flow_always_detaches_and_freezes_before_original_revocation(monkeypatch, tmp_path, records, fail_goto):
    production = make_case(monkeypatch, tmp_path)
    boundaries, recorder = [], module.log_event
    def record_boundary(logger, event, **fields):
        if event.endswith('failure_before_cleanup'):
            boundaries.append((production.flow._managed_manual_login.stopped,
                production.flow.browser_session_id() is not None, production.flow._context is not None))
        recorder(logger, event, **fields)
    monkeypatch.setattr(module, 'log_event', record_boundary)
    for kind in (Browser, Context, Page):
        monkeypatch.setattr(kind, 'on', Emitter.on, raising=False)
        monkeypatch.setattr(kind, 'remove_listener', Emitter.remove_listener, raising=False)
    external = lambda *_: None
    production.browser.on('disconnected', external)
    trackers, original_tracker, original_error = [], module.ManualLoginNavigation, RuntimeError('original goto failure')
    def track(owner):
        tracker = original_tracker(owner)
        trackers.append(tracker)
        return tracker
    monkeypatch.setattr(manual_login_context, 'ManualLoginNavigation', track)
    transport = SimpleNamespace(installed=True, invalid=False, active=None)
    def prepare(context):
        monkeypatch.setitem(module._TRANSPORTS, context, transport)
        context.service_workers = []
        context._impl_obj = SimpleNamespace(_routes=[object()], _web_socket_routes=[object()])
        context.on('close', lambda *_: setattr(transport, 'invalid', True))
    monkeypatch.setattr('src.execution.managed_browser_context.prepare_native_video_transport', prepare)
    if fail_goto:
        def fail(page, *_args, **_kwargs):
            raise original_error
        monkeypatch.setattr(Page, 'goto', fail)
        with pytest.raises(RuntimeError, match='MANAGED_MANUAL_LOGIN_OPEN_FAILED') as caught:
            production.flow.open_managed_manual_login()
        assert caught.value.__cause__ is original_error
        assert boundaries == [(False, True, True)]
        fields = next(fields for event, fields in records if event.endswith('failure_before_cleanup'))
        assert fields['context_open'] is True and fields['transport_invalid'] is False
        assert fields['context_close_count'] == 0
        assert production.browser.contexts[-1].closed and transport.invalid
        assert production.flow._page is production.flow._context is production.flow.browser_session_id() is None
        assert production.flow._managed_manual_login.stopped
    else:
        assert production.flow.open_managed_manual_login()['logged_in'] is False
        assert not any(event.endswith('failure_before_cleanup') for event, _ in records)
    assert trackers[0]._closed and trackers[0]._listeners == []
    assert production.browser.listeners['disconnected'] == [external]
    assert all(value == [] for name, value in production.browser.contexts[-1].listeners.items()
        if name in {'requestfailed', 'serviceworker'})
