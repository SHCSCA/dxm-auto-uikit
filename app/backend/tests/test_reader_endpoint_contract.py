"""合成响应验证真实 Reader 方法与白名单；不访问浏览器或源站。"""

import copy
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution import dxm_login_flow as flow_module, reader_http_observation
from src.services import structured_logging
from src.services.dxm_draft_reader import DxmDraftReaderError
from tests.support.manual_login_case import make_case


ENDPOINT = 'https://www.dianxiaomi.com/api/userIn.json'


class Response:
    def __init__(self, payload=None, *, status=200):
        self.status, self.ok = status, 200 <= status < 300
        self.payload = payload if payload is not None else {'code': 0, 'data': {'userId': 'synthetic-reader-user'}}
        self.body_calls, self.before_body = 0, None
        self.headers = {'content-type': 'application/json; charset=utf-8'}

    def body(self):
        self.body_calls += 1
        assert self.ok, 'HTTP 失败不得读取正文'
        if self.before_body:
            self.before_body()
        return json.dumps(self.payload).encode('utf-8')

    def json(self):
        pytest.fail('有完整字节正文时不能调用第二次 JSON 读取')


@pytest.fixture
def case(monkeypatch, tmp_path):
    current = make_case(monkeypatch, tmp_path)
    current.response, current.calls, current.before_response = Response(), [], None

    def get(url, *, timeout):
        current.calls.append(('GET', url, timeout, threading.get_ident()))
        if current.before_response:
            current.before_response()
        return current.response

    current.flow._context.request = SimpleNamespace(get=get)
    monkeypatch.setattr(current.flow, '_draft_reader_session', lambda: (
        current.flow._page, current.flow._context, current.flow.browser_session_id()))
    return current


def read(case):
    return case.flow._read_authenticated_user_info(case.flow._context, case.flow.browser_session_id())


def test_authenticated_reader_uses_exact_approved_endpoint_once_on_same_owner(case):
    payload, account_ref = read(case)
    assert payload == case.response.payload and len(account_ref) == 32
    assert case.calls == [('GET', ENDPOINT, 15_000, threading.get_ident())]
    assert case.response.body_calls == 1


@pytest.mark.parametrize('method,url,form', [
    ('GET', 'https://www.dianxiaomi.com/api/userInfo.json', None),
    ('POST', ENDPOINT, None), ('HEAD', ENDPOINT, None),
    ('GET', 'https://dianxiaomi.com/api/userIn.json', None),
    ('GET', 'https://other.dianxiaomi.com/api/userIn.json', None),
    ('GET', 'http://www.dianxiaomi.com/api/userIn.json', None),
    ('GET', ENDPOINT + '?probe=1', None), ('GET', ENDPOINT + '#fragment', None),
    ('GET', ENDPOINT.replace('userIn', 'userin'), None),
    ('GET', ENDPOINT, {}),
])
def test_endpoint_method_host_path_and_query_drift_are_rejected_without_alias(method, url, form):
    with pytest.raises(DxmDraftReaderError) as caught:
        DxmLoginFlow._assert_draft_reader_allowlisted(method, url, form=form)
    assert caught.value.reason_code == 'READ_ALLOWLIST_VIOLATION'


def test_only_exact_approved_get_without_form_is_allowlisted():
    DxmLoginFlow._assert_draft_reader_allowlisted('GET', ENDPOINT, form=None)


def test_http_404_is_observed_without_body_or_fallback_request(case, caplog):
    case.response = Response({'private': 'PRIVATE_RESPONSE_BODY'}, status=404)
    with pytest.raises(DxmDraftReaderError) as caught:
        read(case)
    assert caught.value.reason_code == 'DXM_READ_HTTP_FAILED' and case.response.body_calls == 0
    assert case.calls == [('GET', ENDPOINT, 15_000, threading.get_ident())]
    events = [item for item in caplog.records if item.getMessage() == 'reader_http_failure_observed']
    assert len(events) == 1
    fields = events[0].event_fields
    assert fields['operation'] == 'authenticated_user_info' and fields['http_status'] == 404 and fields['ok'] is False
    assert 'PRIVATE_RESPONSE_BODY' not in caplog.text and ENDPOINT not in caplog.text


@pytest.mark.parametrize('payload', [
    {'code': False, 'data': {'userId': 'synthetic-reader-user'}},
    {'code': 1, 'data': {'userId': 'synthetic-reader-user'}},
    {'code': 0.0, 'data': {'userId': 'synthetic-reader-user'}},
    {'code': 'success', 'data': {'userId': 'synthetic-reader-user'}},
    {'code': 0, 'data': []}, {'code': 0, 'data': {'shopMap': {}}},
    {'code': 0, 'data': {'userId': False}}, {'code': 0, 'data': {'userId': '  '}},
])
def test_http_200_never_relaxes_business_code_or_stable_identity(case, payload):
    case.response = Response(copy.deepcopy(payload))
    with pytest.raises(DxmDraftReaderError) as caught:
        read(case)
    assert caught.value.reason_code == 'AUTH_ACCOUNT_UNPROVEN'
    assert len(case.calls) == case.response.body_calls == 1


@pytest.mark.parametrize('phase', ['response', 'body'])
def test_same_owner_session_generation_drift_discards_result_without_retry(case, phase):
    def drift():
        assert case.flow._browser_session_thread_id == threading.get_ident()
        case.flow._clear_browser_context_generation()
        case.flow._bind_browser_context_generation(case.flow._context)

    if phase == 'response':
        case.before_response = drift
    else:
        case.response.before_body = drift
    with pytest.raises(DxmDraftReaderError) as caught:
        read(case)
    assert caught.value.reason_code == 'BROWSER_SESSION_MISMATCH'
    assert len(case.calls) == 1 and case.response.body_calls == (phase == 'body')


@pytest.mark.parametrize('outcome', ['success', 'http', 'schema', 'unexpected'])
def test_visible_reader_status_all_paths_have_fresh_utc_and_unknown_failure_is_private(case, monkeypatch, caplog, outcome):
    if outcome == 'http':
        case.response = Response(status=404)
    elif outcome == 'schema':
        case.response = Response({'code': 0, 'data': {}})
    elif outcome == 'unexpected':
        def fail():
            raise RuntimeError('PRIVATE_EXCEPTION https://private.invalid/?Cookie=PRIVATE_TOKEN')
        monkeypatch.setattr(case.flow, '_draft_reader_session', fail)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    result = case.flow._visible_reader_session_status()
    after = datetime.now(timezone.utc)
    checked = datetime.fromisoformat(result['checked_at'].replace('Z', '+00:00'))
    assert checked.utcoffset() == timezone.utc.utcoffset(None) and before <= checked <= after
    assert result['reader_ready'] is (outcome == 'success')
    expected_reason = {'success': 'LOGIN_READER_READY', 'http': 'DXM_READ_HTTP_FAILED',
        'schema': 'AUTH_ACCOUNT_UNPROVEN', 'unexpected': 'BROWSER_SESSION_UNAVAILABLE'}[outcome]
    assert result['reason_code'] == expected_reason
    if outcome != 'success':
        assert not result.get('account_ref') and not result.get('browser_session_id')
    if outcome == 'unexpected':
        assert any(item.levelname in {'WARNING', 'ERROR'} for item in caplog.records)
        assert all(token not in caplog.text + json.dumps(result) for token in ('PRIVATE_', 'private.invalid', 'Cookie='))


@pytest.mark.parametrize('outcome', ['http', 'unexpected', 'network'])
def test_broken_log_outlets_never_mask_original_reader_failure(case, monkeypatch, outcome):
    def broken_log(*_args, **_kwargs):
        raise OSError('PRIVATE_LOG_SINK_FAILURE')

    # 兼容旧导入别名与新统一出口；全部日志失败也不能改变 Reader 失败合同。
    monkeypatch.setattr(structured_logging, 'log_event', broken_log)
    monkeypatch.setattr(flow_module, 'log_event', broken_log, raising=False)
    monkeypatch.setattr(reader_http_observation, 'log_event', broken_log)
    monkeypatch.setattr(reader_http_observation._FALLBACK, 'warning', broken_log)
    if outcome == 'network':
        def failed_get(*_args, **_kwargs):
            raise OSError('PRIVATE_NETWORK_FAILURE')
        case.flow._context.request.get = failed_get
        with pytest.raises(DxmDraftReaderError) as caught:
            read(case)
        assert caught.value.reason_code == 'DXM_SHOP_READ_FAILED'
        assert case.response.body_calls == 0
        return
    if outcome == 'http':
        case.response = Response(status=404)
    else:
        def failed_session():
            raise RuntimeError('PRIVATE_SESSION_FAILURE')
        monkeypatch.setattr(case.flow, '_draft_reader_session', failed_session)
    result = case.flow._visible_reader_session_status()
    assert result['reader_ready'] is False and result['checked_at']
    assert result['reason_code'] == ('DXM_READ_HTTP_FAILED' if outcome == 'http' else 'BROWSER_SESSION_UNAVAILABLE')
    assert 'PRIVATE_' not in json.dumps(result)
