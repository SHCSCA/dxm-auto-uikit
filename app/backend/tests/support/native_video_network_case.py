"""合成命令与网络事件只证明观察层合同，不证明真实原生生成或生产权限。"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from urllib.parse import urlencode

from src.execution.browser_agent_protocol import BrowserAgentCommand, browser_agent_command_sha256
from src.execution.native_video_network_capture import PassiveNativeVideoNetworkCapture
from src.execution.native_video_network_contract import NativeVideoNetworkScope
from src.execution.native_video_wire import GENERATION_URL, PROGRESS_URL, inputs_digest


IMAGES = ['https://example.invalid/private-a.png', 'https://example.invalid/private-b.png']
GENERATION_BODY = urlencode({'imgs': ','.join(IMAGES), 'transition': '4', 'musicUrl': '', 'platform': 'smt'}).encode()
UUID = 'synthetic-native-uuid'
MEDIA = 'https://example.invalid/private-output.mp4'
PAGE_URL = 'https://www.dianxiaomi.com/web/smt/edit?id=8101'


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.monotonic = 100.0

    def __call__(self):
        return self.wall, self.monotonic

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.monotonic += seconds


class Page:
    def __init__(self):
        self.url = PAGE_URL
        self.main_frame = SimpleNamespace(page=self, url=self.url)
        self.listeners, self.registered, self.removed = {}, [], []
        self.registration_failure = self.cleanup_failure = None
        self.cleanup_effect = None
        self.request_serial = 0

    def on(self, event, callback):
        self.registered.append(event)
        self.listeners.setdefault(event, []).append(callback)
        if event == self.registration_failure:
            raise RuntimeError('synthetic listener registration unavailable')

    def remove_listener(self, event, callback):
        self.removed.append(event)
        if self.cleanup_effect:
            self.cleanup_effect(self, event)
        if event == self.cleanup_failure:
            raise RuntimeError('synthetic listener cleanup unavailable')
        self.listeners[event].remove(callback)

    def emit(self, event, value):
        if event == 'requestfinished':
            value.finished = True
        for callback in list(self.listeners.get(event, [])):
            callback(value)


class Request:
    def __init__(self, page, kind='generation', *, raw=None, response=None):
        self.url = GENERATION_URL if kind == 'generation' else PROGRESS_URL
        self.method, self.resource_type, self.frame = 'POST', 'xhr', page.main_frame
        self.redirected_from = self.redirected_to = None
        self.headers = {'content-type': 'application/x-www-form-urlencoded;charset=UTF-8'}
        self.post_data_buffer = (GENERATION_BODY if kind == 'generation' else urlencode({'uuid': UUID}).encode()) if raw is None else raw
        self.finished, self.response_reads = False, 0
        self.timing = {'startTime': 1000000 + page.request_serial * 100, 'requestStart': 0, 'responseEnd': 10}
        page.request_serial += 1
        self.response_value = Response(self, response or ({'code': 0, 'data': UUID} if kind == 'generation' else
            {'code': 0, 'data': {'processMsg': {'code': 1, 'data': MEDIA}}}))

    def response(self):
        self.response_reads += 1
        assert self.finished, '响应绑定只允许在完成事件中复核'
        return self.response_value


class Response:
    def __init__(self, request, data):
        self.request, self.url, self.status = request, request.url, 200
        self.raw = json.dumps(data, separators=(',', ':')).encode()
        self.headers = {'content-type': 'application/json;charset=UTF-8', 'content-length': str(len(self.raw))}
        self.reads, self.error = 0, None

    def body(self):
        self.reads += 1
        assert self.request.finished, '完成事件之前禁止读取原始响应'
        if self.error:
            raise self.error
        return self.raw

    def update(self, raw):
        self.raw = raw
        self.headers['content-length'] = str(len(raw))


def make_case():
    command = BrowserAgentCommand(command_id='synthetic-command', idempotency_key='synthetic-key',
        deadline='2026-10-16T01:00:00Z', expected_page='editor', runtime_id='synthetic-runtime',
        task_id=71, job_id=81, state='BATCH_VIDEO_SUBMIT', action='submit_editor_video',
        params={'synthetic_inputs_ref': 'A' * 64}, execution_mode='batch_draft_save', execution_payload_hash='B' * 64)
    scope = NativeVideoNetworkScope(task_id=71, job_id=81, product_id='8101', browser_session_id='synthetic-session',
        runtime_id=command.runtime_id, command_id=command.command_id, command_sha256=browser_agent_command_sha256(command),
        execution_payload_hash=command.execution_payload_hash, snapshot_sha256='C' * 64,
        scope_sha256='D' * 64, inputs_sha256=inputs_digest(GENERATION_BODY), source_page_url=PAGE_URL)
    page, clock = Page(), Clock()
    live = [scope]
    capture = PassiveNativeVideoNetworkCapture(page, scope, command=command, scope_reader=lambda: live[0], clock=clock)
    return SimpleNamespace(page=page, clock=clock, command=command, scope=scope, live=live, capture=capture)


def exchange(case, request):
    case.page.emit('request', request)
    case.clock.advance(0.01)
    case.page.emit('response', request.response_value)
    case.clock.advance(0.01)
    case.page.emit('requestfinished', request)
    return request


def complete(case, *, progress_code=1):
    case.capture.start()
    generation = exchange(case, Request(case.page))
    progress = exchange(case, Request(case.page, 'progress', response={'code': 0,
        'data': {'processMsg': {'code': progress_code, 'data': MEDIA}}}))
    case.capture.close()
    return generation, progress


def reseal(record):
    from src.batch_edit.scope_contract import canonical_sha256
    record['observation_sha256'] = canonical_sha256({key: value for key, value in record.items() if key != 'observation_sha256'})


def assert_no_authority(record):
    assert all(record[key] is False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))
    assert record['success_semantics'] == 'unreviewed'
    assert record['physical_completion_order'] == 'unproven'


def change_scope(case, **changes):
    case.live[0] = replace(case.scope, **changes)
