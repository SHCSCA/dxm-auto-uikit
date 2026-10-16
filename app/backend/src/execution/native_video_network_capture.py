"""在唯一生成命令周围被动观察原生网络；不请求接口、不派发或补成功。"""

from copy import deepcopy
from datetime import datetime
import math
import uuid

from src.batch_edit.scope_contract import canonical_sha256
from src.execution.native_video_network_contract import (
    NativeVideoNetworkLimits, NativeVideoNetworkScope, capture_clock, private_wire_record, utc_time, validate_video_wire_observation,
)
from src.execution.native_video_wire import (
    ENDPOINTS, NativeVideoWireError, browser_timing, inputs_digest, raw_facts, read_finished_body,
    reject, reopen_body, request_values, require_request_scope, require_response_identity, response_values,
)
from src.services.structured_logging import get_logger, log_event, log_exception


_LOGGER = get_logger('native_video.network_capture')


class PassiveNativeVideoNetworkCapture:
    def __init__(self, page, scope: NativeVideoNetworkScope, *, command, scope_reader, clock=capture_clock):
        self.page, self.scope, self.command = page, scope, command
        self.scope_reader, self.clock = scope_reader, clock
        self.capture_id, self.frame = uuid.uuid4().hex, page.main_frame
        self.started = self.completed = self.last_stamp = None
        self.listeners, self.entries, self.requests, self.issues = [], [], {}, set()
        self.active = self.closed = self.closing = False
        self.document_invalid = self.draining = False
        self.event_count = self.body_read_count = 0
        self.limits = NativeVideoNetworkLimits.from_config_bus()

    def _issue(self, reason):
        if reason not in self.issues:
            self.issues.add(reason)
            log_event(_LOGGER, 'native_video_network_observation_incomplete', level='WARNING', reason_code=reason)

    def _scope(self):
        if not isinstance(self.scope, NativeVideoNetworkScope):
            reject('SCOPE_DRIFT')
        self.scope.require_live(self.command, self.page, self.frame, self.scope_reader, document_invalid=self.document_invalid)

    def _stamp(self):
        wall, monotonic = self.clock()
        if (not isinstance(wall, datetime) or wall.utcoffset() is None or wall.utcoffset().total_seconds() != 0
                or isinstance(monotonic, bool) or not isinstance(monotonic, (int, float))
                or not math.isfinite(monotonic) or monotonic < 0):
            reject('TIME_INVALID')
        if self.last_stamp and (wall < self.last_stamp[0] or monotonic < self.last_stamp[1]):
            reject('TIME_REGRESSION')
        if self.started and (max((wall - self.started[0]).total_seconds(), monotonic - self.started[1])
                             > self.limits.max_window_seconds):
            reject('WINDOW_EXPIRED')
        if wall > utc_time(self.command.deadline):
            reject('COMMAND_EXPIRED')
        self.last_stamp = (wall, monotonic)
        return wall.isoformat()

    def start(self):
        if self.active or self.closed:
            reject('WINDOW_REUSED')
        try:
            self._scope()
            self._stamp()
            self.started = self.last_stamp
            for event, callback in (('request', self._request), ('response', self._response),
                    ('requestfinished', self._finished), ('requestfailed', self._failed), ('framenavigated', self._navigated)):
                self.listeners.append((event, callback))
                self.page.on(event, callback)
            self.active = True
        except Exception as exc:
            self._failure(exc, 'START_FAILED')
            self.close()
            raise
        return self

    __enter__ = start

    def __exit__(self, exc_type, _exc, _traceback):
        if exc_type is not None:
            self._issue('NATIVE_VIDEO_WIRE_CALLER_FAILED')
        self.close()
        return False

    def _failure(self, exc, fallback):
        log_exception(_LOGGER, 'native_video_network_observation_failed', exc)
        self._issue(exc.reason_code if isinstance(exc, NativeVideoWireError) else 'NATIVE_VIDEO_WIRE_' + fallback)

    def _event(self, request):
        if not self.active or self.closing or request.url not in ENDPOINTS:
            return None
        self.event_count += 1
        if self.event_count > self.limits.max_events:
            reject('EVENT_LIMIT')
        self._scope()
        require_request_scope(request, page=self.page, frame=self.frame, url=request.url)
        return self._stamp()

    def _request(self, request):
        try:
            stamp = self._event(request)
            if stamp is None:
                return
            kind = ENDPOINTS[request.url]
            if id(request) in self.requests or (kind == 'generation' and self.entries):
                reject('DUPLICATE_GENERATION_OR_REQUEST')
            if (kind == 'progress' and (not self.entries or self.entries[0]['wire']['kind'] != 'generation'
                    or any(item['response'] is None for item in self.entries))):
                reject('PROGRESS_CAUSAL_ORDER_INVALID')
            headers = {key.lower(): value for key, value in request.headers.items()}
            if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/x-www-form-urlencoded':
                reject('REQUEST_FORMAT_INVALID')
            raw = request.post_data_buffer
            body = raw_facts(raw, maximum=self.limits.max_body_bytes)
            request_values(kind, raw)
            if kind == 'generation' and inputs_digest(raw) != self.scope.inputs_sha256:
                reject('INPUTS_DRIFT')
            item = {'request': request, 'response': None, 'finished': False, 'network_finished': False, 'wire': {
                'request_id': uuid.uuid4().hex, 'kind': kind, 'url': request.url, 'request_at': stamp,
                'response_headers_at': None, 'response_finished_at': None, 'body_observed_at': None, 'browser_timing': None,
                'request_body': body, 'response_body': None, 'http_status': None}}
            self.entries.append(item)
            self.requests[id(request)] = item
        except Exception as exc:
            self._failure(exc, 'REQUEST_FAILED')

    def _response(self, response):
        try:
            request = response.request
            stamp = self._event(request)
            if stamp is None:
                return
            item = self.requests.get(id(request))
            if item is None or item['request'] is not request or item['response'] is not None:
                reject('RESPONSE_UNBOUND_OR_DUPLICATE')
            require_response_identity(response, request)
            item['response'] = response
            item['wire'].update(response_headers_at=stamp, http_status=response.status)
        except Exception as exc:
            self._failure(exc, 'RESPONSE_FAILED')

    def _finished(self, request):
        try:
            stamp = self._event(request)
            if stamp is None:
                return
            item = self.requests.get(id(request))
            if (item is None or item['request'] is not request
                    or item['response'] is None or item['network_finished']):
                reject('FINISH_UNBOUND_OR_DUPLICATE')
            item['network_finished'] = True
            item['wire']['response_finished_at'] = stamp
            # 回调只登记完成；同步读体留在 owner 调用栈，避免回调绿线程悬挂。
            item['wire']['browser_timing'] = browser_timing(request.timing)
        except Exception as exc:
            self._failure(exc, 'BODY_OBSERVATION_FAILED')

    def _drain(self):
        if self.draining:
            return
        self.draining = True
        try:
            for index, item in enumerate(self.entries):
                if not item['network_finished']:
                    break
                if item['finished']:
                    continue
                self._scope()
                wire = item['wire']
                require_request_scope(item['request'], page=self.page, frame=self.frame, url=wire['url'])
                require_response_identity(item['response'], item['request'])
                if item['request'].response() is not item['response']:
                    reject('FINISH_UNBOUND_OR_DUPLICATE')
                self._scope()
                if index:
                    values = request_values('progress', reopen_body(wire['request_body'], maximum=self.limits.max_body_bytes))
                    parent, previous = self.entries[0]['semantic'], self.entries[index - 1]['semantic']
                    if parent['uuid'] is None or values['uuid'] != parent['uuid'] or index > 1 and (
                            previous['outer_code'] != 0 or previous['process_code'] != 0):
                        reject('UUID_CAUSAL_BINDING_INVALID')
                facts = read_finished_body(item['response'], maximum=self.limits.max_body_bytes)
                self.body_read_count += 1
                item['semantic'] = response_values(wire['kind'], reopen_body(facts, maximum=self.limits.max_body_bytes))
                self._scope()
                wire.update(response_body=facts, body_observed_at=self._stamp())
                item['finished'] = True
        finally:
            self.draining = False

    def _failed(self, request):
        try:
            if self._event(request) is not None:
                reject('REQUEST_FAILED')
        except Exception as exc:
            self._failure(exc, 'REQUEST_FAILED')

    def _navigated(self, frame):
        try:
            if self.active and (frame is self.frame or frame is self.page.main_frame):
                self.document_invalid = True
                reject('DOCUMENT_CHANGED')
        except Exception as exc:
            self._failure(exc, 'NAVIGATION_FAILED')

    def close(self):
        if self.closed or self.closing:
            return
        self.closing = True
        try:
            self._drain()
        except Exception as exc:
            self._failure(exc, 'BODY_OBSERVATION_FAILED')
        for event, callback in self.listeners:
            try:
                self.page.remove_listener(event, callback)
            except Exception as exc:
                self._failure(exc, 'LISTENER_CLEANUP_FAILED')
        self.listeners = []
        try:
            self._scope()
            self.completed = self._stamp()
        except Exception as exc:
            self._failure(exc, 'FINAL_SCOPE_FAILED')
        self.active, self.closed = False, True

    def private_facts(self):
        issues = set(self.issues)
        if not self.closed:
            issues.add('NATIVE_VIDEO_WIRE_WINDOW_OPEN')
        if not self.entries or any(not item['finished'] for item in self.entries):
            issues.add('NATIVE_VIDEO_WIRE_EXCHANGE_INCOMPLETE')
        record = private_wire_record(capture_id=self.capture_id, scope=self.scope,
            window={'started_at': self.started[0].isoformat() if self.started else None, 'completed_at': self.completed},
            exchanges=[item['wire'] for item in self.entries], issues=issues, wire_complete=self.closed and not issues)
        if record['wire_complete']:
            try:
                validate_video_wire_observation(record, expected_scope=self.scope, limits=self.limits)
            except Exception as exc:
                self._failure(exc, 'RECORD_INVALID')
                record.update(wire_complete=False, issues=sorted(self.issues))
                record['observation_sha256'] = canonical_sha256({key: value for key, value in record.items() if key != 'observation_sha256'})
        return deepcopy(record)

    def summary(self):
        record = self.private_facts()
        return {key: record[key] for key in ('schema', 'wire_complete', 'success_semantics', 'physical_completion_order', 'issues',
            'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed', 'observation_sha256')} | {
            'exchange_count': len(self.entries), 'body_read_count': self.body_read_count}
