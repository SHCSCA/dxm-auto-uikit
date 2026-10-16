"""复读原生视频请求与响应的私有原字节；状态候选不表示业务成功。"""

import base64
import hashlib
import json
import math
import re
from urllib.parse import parse_qsl, urlsplit

from src.batch_edit.scope_contract import canonical_sha256


GENERATION_URL = 'https://www.dianxiaomi.com/api/picToVideo/transToVideo.json'
PROGRESS_URL = 'https://www.dianxiaomi.com/api/checkProcess.json'
ENDPOINTS = {GENERATION_URL: 'generation', PROGRESS_URL: 'progress'}


class NativeVideoWireError(ValueError):
    def __init__(self, reason):
        self.reason_code = 'NATIVE_VIDEO_WIRE_' + reason
        super().__init__(self.reason_code)


def reject(reason):
    raise NativeVideoWireError(reason)


def opaque_text(value, *, maximum=1024):
    return (isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def url_text(value):
    if not opaque_text(value, maximum=8192):
        return False
    parts = urlsplit(value)
    return (parts.scheme in {'http', 'https'} and bool(parts.netloc)
            and parts.username is None and parts.password is None and not parts.fragment)


def raw_facts(raw, *, maximum):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= maximum:
        reject('BODY_SIZE_INVALID')
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest().upper(),
            'base64': base64.b64encode(raw).decode('ascii')}


def reopen_body(facts, *, maximum):
    if (not isinstance(facts, dict) or set(facts) != {'size', 'sha256', 'base64'}
            or type(facts.get('size')) is not int or not 0 < facts['size'] <= maximum
            or not isinstance(facts.get('base64'), str) or len(facts['base64']) > (maximum + 2) // 3 * 4):
        reject('BODY_RECORD_INVALID')
    try:
        raw = base64.b64decode(facts['base64'], validate=True)
    except (ValueError, TypeError):
        reject('BODY_RECORD_INVALID')
    if raw_facts(raw, maximum=maximum) != facts:
        reject('BODY_RECORD_DRIFT')
    return raw


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject('DUPLICATE_KEY')
        result[key] = value
    return result


def request_values(kind, raw):
    try:
        pairs = parse_qsl(raw.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=8)
        values = _unique(pairs)
    except NativeVideoWireError:
        raise
    except (UnicodeError, ValueError):
        reject('FORM_INVALID')
    if kind == 'progress':
        if set(values) != {'uuid'} or not opaque_text(values['uuid'], maximum=256):
            reject('PROGRESS_REQUEST_INVALID')
        return values
    if kind != 'generation' or set(values) != {'imgs', 'transition', 'musicUrl', 'platform'}:
        reject('GENERATION_REQUEST_INVALID')
    images = values['imgs'].split(',')
    if (not 2 <= len(images) <= 8 or len(set(images)) != len(images) or not all(map(url_text, images))
            or re.fullmatch('[0-6]', values['transition']) is None or values['platform'] != 'smt'
            or values['musicUrl'] and not url_text(values['musicUrl'])):
        reject('GENERATION_INPUT_INVALID')
    return {'images': images, 'transition': int(values['transition']), 'music_url': values['musicUrl'], 'platform': 'smt'}


def response_values(kind, raw):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=lambda _value: reject('JSON_INVALID'))
    except NativeVideoWireError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        reject('JSON_INVALID')
    if not isinstance(value, dict) or type(value.get('code')) is not int:
        reject('RESPONSE_SCHEMA_UNREVIEWED')
    result = {'outer_code': value['code'], 'uuid': None, 'process_code': None, 'media': None}
    if value['code'] != 0:
        return result
    if kind == 'generation':
        data = value.get('data')
        native_uuid = data.get('uuid') if isinstance(data, dict) else data
        if not opaque_text(native_uuid, maximum=256):
            reject('GENERATION_UUID_UNREVIEWED')
        result['uuid'] = native_uuid
    else:
        data = value.get('data')
        process = data.get('processMsg') if isinstance(data, dict) else None
        if not isinstance(process, dict) or type(process.get('code')) is not int:
            reject('PROGRESS_SCHEMA_UNREVIEWED')
        result['process_code'] = process['code']
        if process.get('data') not in (None, ''):
            if not opaque_text(process['data'], maximum=8192):
                reject('MEDIA_SCHEMA_UNREVIEWED')
            result['media'] = process['data']
    return result


def inputs_digest(raw):
    return canonical_sha256(request_values('generation', raw))


def require_request_scope(request, *, page, frame, url):
    if (request.url != url or url not in ENDPOINTS or request.method != 'POST'
            or request.resource_type not in {'xhr', 'fetch'} or request.frame is not frame
            or request.frame.page is not page or request.redirected_from is not None or request.redirected_to is not None):
        reject('REQUEST_SCOPE_INVALID')


def require_response_identity(response, request):
    if response.request is not request or response.url != request.url or type(response.status) is not int or response.status != 200:
        reject('HTTP_RESPONSE_INVALID')


def browser_timing(value):
    """只用实际资源起点和完成偏移；不把缺失的传输阶段 requestStart 补零。"""
    keys = ('startTime', 'responseEnd')
    if not isinstance(value, dict) or any(type(value.get(key)) not in {int, float}
            or not math.isfinite(value[key]) for key in keys):
        reject('BROWSER_TIMING_UNPROVEN')
    if value['startTime'] <= 0 or value['responseEnd'] < 0:
        reject('BROWSER_TIMING_UNPROVEN')
    return {key: value[key] for key in keys}


def read_finished_body(response, *, maximum):
    headers = {key.lower(): value for key, value in response.headers.items()}
    length = headers.get('content-length')
    if (not isinstance(length, str) or re.fullmatch('[1-9][0-9]{0,6}', length) is None
            or int(length) > maximum or headers.get('content-encoding', 'identity').lower() != 'identity'
            or headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
        reject('RESPONSE_BOUNDS_UNPROVEN')
    raw = response.body()
    facts = raw_facts(raw, maximum=maximum)
    if facts['size'] != int(length):
        reject('BODY_LENGTH_DRIFT')
    return facts
