"""合成缓存响应只验证诊断隐私与异常边界，不访问浏览器或网络。"""

import json
import logging
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.execution import reader_http_observation as module
from src.services.structured_logging import StructuredLogFormatter


@pytest.fixture
def output(monkeypatch):
    stream = StringIO()
    logger = logging.Logger('dxm.reader.http.test')
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredLogFormatter())
    logger.addHandler(handler)
    monkeypatch.setattr(module, '_LOGGER', logger)
    return stream


def records(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_only_two_cached_properties_are_read_and_unified_log_contains_no_private_payload(output):
    class CachedResponse:
        def __getattribute__(self, name):
            if name == 'status':
                return 503
            if name == 'ok':
                return False
            raise AssertionError('不得读取 private-account Cookie body headers url json')

    before = datetime.fromisoformat(datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
    facts = module.observe_reader_http_failure(CachedResponse(), operation='authenticated_user_info')
    after = datetime.now(timezone.utc)
    assert facts['http_status'] == 503 and facts['ok'] is False and facts['read_error_count'] == 0
    assert UUID(facts['request_id']).hex == facts['request_id']
    assert before <= datetime.fromisoformat(facts['observed_at'].replace('Z', '+00:00')) <= after
    event = records(output)[0]
    assert event['schema'] == 'dxm.log.v1' and event['event'] == 'reader_http_failure_observed'
    assert event['fields'] == facts
    assert all(token not in output.getvalue() for token in ('private-account', 'Cookie', 'headers', 'url', 'body'))


@pytest.mark.parametrize('status', [True, False, '403', 403.0, None, 99, 600, object()])
def test_status_requires_exact_bounded_integer_without_stringifying_rejected_value(output, status):
    facts = module.observe_reader_http_failure(SimpleNamespace(status=status, ok=False))
    assert facts['http_status'] is None and facts['ok'] is False and facts['read_error_count'] == 1
    assert records(output)[0]['fields']['exception_type'] == 'TypeError'


@pytest.mark.parametrize('ok', [0, 1, 'false', None, object()])
def test_ok_requires_exact_boolean_and_does_not_reconstruct_it_from_status(output, ok):
    facts = module.observe_reader_http_failure(SimpleNamespace(status=403, ok=ok))
    assert facts['http_status'] == 403 and facts['ok'] is None and facts['read_error_count'] == 1


@pytest.mark.parametrize('status,ok', [(403, True), (204, False)])
def test_inconsistent_cached_facts_are_preserved_without_replacing_http_validation(output, status, ok):
    facts = module.observe_reader_http_failure(SimpleNamespace(status=status, ok=ok))
    assert facts['http_status'] == status and facts['ok'] is ok and facts['read_error_count'] == 0


def test_getter_failure_does_not_skip_other_property_or_expose_exception_text(output):
    class BrokenResponse:
        @property
        def status(self):
            raise RuntimeError('https://private.invalid/?token=private-tail')

        @property
        def ok(self):
            return False

    facts = module.observe_reader_http_failure(BrokenResponse())
    assert facts['http_status'] is None and facts['ok'] is False and facts['read_error_count'] == 1
    assert records(output)[0]['fields']['exception_type'] == 'RuntimeError'
    assert 'private' not in output.getvalue() and 'https' not in output.getvalue()


def test_missing_response_properties_are_unknown_and_each_failure_is_recorded(output):
    facts = module.observe_reader_http_failure(object())
    assert facts['http_status'] is facts['ok'] is None and facts['read_error_count'] == 2
    failures = records(output)[:2]
    assert [entry['fields']['property'] for entry in failures] == ['status', 'ok']
    assert all(entry['fields']['exception_type'] == 'AttributeError' for entry in failures)


def test_unknown_exception_class_and_invalid_operation_are_not_logged_as_private_text(output):
    private_error = type('private_account_class', (Exception,), {})

    class BrokenResponse:
        @property
        def status(self):
            raise private_error('private-tail')

        ok = False

    facts = module.observe_reader_http_failure(BrokenResponse(), operation='private-operation')
    assert facts['operation'] == 'unknown'
    assert records(output)[1]['fields']['exception_type'] == 'Exception'
    assert 'private' not in output.getvalue()


def test_primary_log_failure_uses_same_structured_fallback_without_masking_original_error(output, monkeypatch):
    def broken_log(*_args, **_kwargs):
        raise ValueError('private-tail')

    stream = StringIO()
    monkeypatch.setattr(module, 'log_event', broken_log)
    monkeypatch.setattr(module._HANDLER, 'stream', stream)
    original = RuntimeError('original-reader-error')
    with pytest.raises(RuntimeError) as raised:
        try:
            raise original
        except RuntimeError:
            facts = module.observe_reader_http_failure(SimpleNamespace(status=429, ok=False))
            raise
    assert raised.value is original and facts['http_status'] == 429
    event = json.loads(stream.getvalue())
    assert event['schema'] == 'dxm.log.v1' and event['event'] == 'reader_http_observation_log_failed'
    assert event['fields'] == {'exception_type': 'ValueError'}
    assert 'private-tail' not in stream.getvalue()


def test_all_log_sinks_failing_never_escape_or_change_response(output, monkeypatch):
    def broken_log(*_args, **_kwargs):
        raise OSError('private-tail')

    monkeypatch.setattr(module, 'log_event', broken_log)
    monkeypatch.setattr(module._FALLBACK, 'warning', broken_log)
    response = SimpleNamespace(status=500, ok=False)
    facts = module.observe_reader_http_failure(response)
    assert response.__dict__ == {'status': 500, 'ok': False}
    assert facts['http_status'] == 500 and facts['ok'] is False


def test_correlation_generation_failure_is_logged_as_type_only_and_never_escapes(output, monkeypatch):
    def broken_uuid():
        raise OSError('private-tail')

    monkeypatch.setattr(module, 'uuid4', broken_uuid)
    facts = module.observe_reader_http_failure(SimpleNamespace(status=403, ok=False))
    assert facts['request_id'] is None and facts['http_status'] is None
    assert records(output)[0]['fields']['exception_type'] == 'OSError'
    assert 'private-tail' not in output.getvalue()


def test_correlation_id_is_fresh_and_diagnostic_does_not_assert_business_authority(output):
    first = module.observe_reader_http_failure(SimpleNamespace(status=403, ok=False))
    second = module.observe_reader_http_failure(SimpleNamespace(status=403, ok=False))
    assert first['request_id'] != second['request_id']
    assert set(first) == {'operation', 'request_id', 'observed_at', 'http_status', 'ok', 'read_error_count'}
