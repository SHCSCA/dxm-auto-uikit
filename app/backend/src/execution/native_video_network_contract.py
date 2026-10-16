"""原生生成与轮询的来源合同；完整线缆观察不授予业务成功或投放权。"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
import math
import time
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.scope_contract import canonical_sha256
from src.core.config_bus import get_config_bus
from src.execution.browser_agent_protocol import BrowserAgentCommand, browser_agent_command_sha256
from src.execution.native_video_wire import (
    GENERATION_URL, PROGRESS_URL, browser_timing, inputs_digest, opaque_text, reopen_body,
    request_values, response_values, reject,
)
from src.services.structured_logging import get_logger, log_exception


def capture_clock():
    return datetime.now(timezone.utc), time.monotonic()


@dataclass(frozen=True)
class NativeVideoNetworkLimits:
    max_body_bytes: int
    max_events: int
    max_window_seconds: float

    def __post_init__(self):
        if (type(self.max_body_bytes) is not int or not 128 <= self.max_body_bytes <= 1048576
                or type(self.max_events) is not int or not 3 <= self.max_events <= 2048
                or isinstance(self.max_window_seconds, bool) or not isinstance(self.max_window_seconds, (int, float))
                or not math.isfinite(self.max_window_seconds) or not 1 <= self.max_window_seconds <= 900):
            reject('LIMITS_INVALID')

    @classmethod
    def from_config_bus(cls):
        try:
            bus = get_config_bus()
            return cls(bus.integer('DXM_VIDEO_NETWORK_MAX_BODY_BYTES', 65536, minimum=128, maximum=1048576),
                bus.integer('DXM_VIDEO_NETWORK_MAX_EVENTS', 512, minimum=3, maximum=2048),
                bus.number('DXM_VIDEO_NETWORK_MAX_WINDOW_SECONDS', 300, minimum=1, maximum=900))
        except Exception as exc:
            log_exception(get_logger('native_video.network_capture'), 'native_video_network_configuration_failed', exc)
            raise


@dataclass(frozen=True)
class NativeVideoNetworkScope:
    task_id: int
    job_id: int
    product_id: str
    browser_session_id: str
    runtime_id: str
    command_id: str
    command_sha256: str
    execution_payload_hash: str
    snapshot_sha256: str
    scope_sha256: str
    inputs_sha256: str
    source_page_url: str

    def validate(self):
        if any(type(value) is not int or value <= 0 for value in (self.task_id, self.job_id)):
            reject('SCOPE_INVALID')
        if (not isinstance(self.product_id, str) or re.fullmatch('[1-9][0-9]*', self.product_id) is None
                or any(not opaque_text(value, maximum=256) for value in
                    (self.browser_session_id, self.runtime_id, self.command_id))):
            reject('SCOPE_INVALID')
        if any(not isinstance(value, str) or re.fullmatch('[0-9a-fA-F]{64}', value) is None for value in
                (self.command_sha256, self.execution_payload_hash, self.snapshot_sha256, self.scope_sha256, self.inputs_sha256)):
            reject('SCOPE_INVALID')
        page = urlsplit(self.source_page_url)
        if (page.scheme != 'https' or page.netloc != 'www.dianxiaomi.com' or page.path != '/web/smt/edit'
                or page.fragment or parse_qs(page.query, keep_blank_values=True) != {'id': [self.product_id]}):
            reject('PAGE_INVALID')
        return asdict(self)

    def require_command(self, command):
        self.validate()
        if (not isinstance(command, BrowserAgentCommand)
                or (command.state, command.action) != ('BATCH_VIDEO_SUBMIT', 'submit_editor_video')
                or command.execution_mode != 'batch_draft_save' or command.expected_page != 'editor'
                or type(command.task_id) is not int or type(command.job_id) is not int
                or (command.task_id, command.job_id, command.command_id, command.runtime_id, command.execution_payload_hash)
                    != (self.task_id, self.job_id, self.command_id, self.runtime_id, self.execution_payload_hash)
                or browser_agent_command_sha256(command) != self.command_sha256):
            reject('COMMAND_DRIFT')

    def require_live(self, command, page, frame, scope_reader, *, document_invalid):
        if not callable(scope_reader) or scope_reader() != self:
            reject('SCOPE_DRIFT')
        self.require_command(command)
        if str(page.url) != self.source_page_url or page.main_frame is not frame:
            reject('PAGE_DRIFT')
        if document_invalid:
            reject('DOCUMENT_CHANGED')


def utc_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        reject('TIME_INVALID')
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        reject('TIME_INVALID')
    return parsed


def private_wire_record(*, capture_id, scope, window, exchanges, issues, wire_complete):
    """统一私有证据容器；构造字典不提供 Worker 来源或任何成功权威。"""
    record = {'schema': 'dxm.native_video_network_observation.v1', 'capture_id': capture_id,
        'scope': scope.validate(), 'window': window, 'exchanges': exchanges, 'issues': sorted(issues),
        'wire_complete': wire_complete, 'success_semantics': 'unreviewed', 'physical_completion_order': 'unproven',
        'executionAllowed': False, 'capabilityCertified': False, 'inputFreezeAllowed': False}
    return {**record, 'observation_sha256': canonical_sha256(record)}


def validate_video_wire_observation(record, *, expected_scope, limits):
    """复读私有原字节和因果链；生产权威还必须由 Worker 原文件及持久索引绑定。"""
    keys = {'schema', 'capture_id', 'scope', 'window', 'exchanges', 'issues', 'wire_complete',
            'success_semantics', 'physical_completion_order', 'executionAllowed', 'capabilityCertified', 'inputFreezeAllowed', 'observation_sha256'}
    if (not isinstance(expected_scope, NativeVideoNetworkScope) or not isinstance(limits, NativeVideoNetworkLimits)
            or not isinstance(record, dict) or set(record) != keys
            or record.get('schema') != 'dxm.native_video_network_observation.v1'
            or record.get('scope') != expected_scope.validate() or not opaque_text(record.get('capture_id'), maximum=64)
            or record.get('wire_complete') is not True or record.get('issues') != []
            or record.get('success_semantics') != 'unreviewed'
            or record.get('physical_completion_order') != 'unproven'
            or any(record.get(key) is not False for key in ('executionAllowed', 'capabilityCertified', 'inputFreezeAllowed'))
            or canonical_sha256({key: value for key, value in record.items() if key != 'observation_sha256'}) != record['observation_sha256']):
        reject('OBSERVATION_INVALID')
    window = record['window']
    if not isinstance(window, dict) or set(window) != {'started_at', 'completed_at'}:
        reject('WINDOW_INVALID')
    started, completed = utc_time(window['started_at']), utc_time(window['completed_at'])
    if not 0 <= (completed - started).total_seconds() <= limits.max_window_seconds:
        reject('WINDOW_INVALID')
    exchanges = record['exchanges']
    if not isinstance(exchanges, list) or not exchanges or len(exchanges) * 3 > limits.max_events:
        reject('EXCHANGES_INVALID')
    ids, generation, previous_headers, terminal = set(), None, started, False
    previous_browser_start, first_browser_start = None, None
    last_progress, media = None, None
    for index, exchange in enumerate(exchanges):
        required = {'request_id', 'kind', 'url', 'request_at', 'response_headers_at', 'response_finished_at', 'body_observed_at', 'browser_timing',
                    'request_body', 'response_body', 'http_status'}
        kind = 'generation' if index == 0 else 'progress'
        if (not isinstance(exchange, dict) or set(exchange) != required or exchange['kind'] != kind
                or exchange['url'] != (GENERATION_URL if index == 0 else PROGRESS_URL)
                or not opaque_text(exchange['request_id'], maximum=64) or exchange['request_id'] in ids
                or type(exchange['http_status']) is not int or exchange['http_status'] != 200):
            reject('EXCHANGE_INVALID')
        ids.add(exchange['request_id'])
        request_at, headers_at, finished_at = (utc_time(exchange[key]) for key in
            ('request_at', 'response_headers_at', 'response_finished_at'))
        body_at = utc_time(exchange['body_observed_at'])
        if not previous_headers <= request_at <= headers_at <= finished_at <= body_at <= completed:
            reject('CAUSAL_ORDER_INVALID')
        previous_headers = headers_at
        timing = browser_timing(exchange['browser_timing'])
        if set(exchange['browser_timing']) != set(timing) or (previous_browser_start is not None
                and previous_browser_start > timing['startTime']):
            reject('BROWSER_CAUSAL_ORDER_INVALID')
        first_browser_start = timing['startTime'] if first_browser_start is None else first_browser_start
        previous_browser_start = timing['startTime']
        if timing['startTime'] + timing['responseEnd'] - first_browser_start > limits.max_window_seconds * 1000:
            reject('BROWSER_WINDOW_EXPIRED')
        request_raw = reopen_body(exchange['request_body'], maximum=limits.max_body_bytes)
        values = request_values(kind, request_raw)
        response = response_values(kind, reopen_body(exchange['response_body'], maximum=limits.max_body_bytes))
        if index == 0:
            if inputs_digest(request_raw) != expected_scope.inputs_sha256:
                reject('INPUTS_DRIFT')
            generation = response
        else:
            if generation['uuid'] is None or values['uuid'] != generation['uuid'] or terminal:
                reject('UUID_CAUSAL_BINDING_INVALID')
            last_progress = response
            media = response['media'] if response['media'] is not None else media
            terminal = response['outer_code'] != 0 or response['process_code'] != 0
    return {'generation': generation, 'last_progress': last_progress, 'media_candidate': media,
            'business_success_proven': False, 'placement_proven': False, 'physical_completion_order': 'unproven'}


def require_reviewed_video_success(record, *, expected_scope, limits):
    """成功内层码尚无审阅合同，不能把终态、媒体候选或按钮升级为成功。"""
    validate_video_wire_observation(record, expected_scope=expected_scope, limits=limits)
    reject('SUCCESS_SEMANTICS_UNREVIEWED')
