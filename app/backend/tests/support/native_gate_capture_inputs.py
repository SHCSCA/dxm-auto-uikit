from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.execution.native_gate_capture import NativeGateCaptureScope, NativeGateCaptureStamp
from src.execution.native_gate_evidence import NATIVE_GATE_URL
from src.execution.native_gate_observer import PassiveNativeGateCapture


class SyntheticClock:
    def __init__(self):
        self.seconds = 0.0
        self.wall_shift = 0.0

    def __call__(self):
        return NativeGateCaptureStamp(datetime(2026, 10, 16, tzinfo=timezone.utc)
            + timedelta(seconds=self.seconds + self.wall_shift), self.seconds)


class SyntheticPage:
    def __init__(self, url):
        self.url = url
        self.main_frame = SimpleNamespace(page=self)
        self.listeners, self.removal_attempts = {}, []
        self.registration_failure = self.removal_failure = None

    def on(self, name, callback):
        self.listeners.setdefault(name, []).append(callback)
        if name == self.registration_failure:
            raise RuntimeError("private-registration-value")

    def remove_listener(self, name, callback):
        self.removal_attempts.append(name)
        if name == self.removal_failure:
            raise RuntimeError("private-removal-value")
        self.listeners[name].remove(callback)

    def emit(self, name, event):
        for callback in list(self.listeners.get(name, [])):
            callback(event)

    def __getattr__(self, name):
        raise AssertionError("不允许调用页面读写或网络 API：" + name)


class SyntheticRequest:
    def __init__(self, page, body=b'{"synthetic_request":"private-native-token"}'):
        self.url, self.method, self.resource_type = NATIVE_GATE_URL, "POST", "xhr"
        self.frame, self.raw, self.read_count = page.main_frame, body, 0
        self.headers = {"content-type": "application/json", "content-length": str(len(body))}
        self.error = None

    @property
    def post_data_buffer(self):
        self.read_count += 1
        if self.error:
            raise self.error
        return self.raw


class SyntheticResponse:
    def __init__(self, request, body=b'{ "synthetic_unknown": "private-response-value", "n": 1 }'):
        self.request, self.raw, self.read_count = request, body, 0
        self.url, self.status = request.url, 200
        self.headers = {"content-type": "application/json", "content-length": str(len(body))}
        self.error = None

    def body(self):
        self.read_count += 1
        if self.error:
            raise self.error
        return self.raw


def capture_case():
    scope = NativeGateCaptureScope(11, 12, "70001", "synthetic-handshake", "synthetic-first-save",
        "synthetic-session", "a" * 64, "b" * 64, "c" * 64,
        "https://www.dianxiaomi.com/web/smt/edit?id=70001")
    page, clock, current = SyntheticPage(scope.source_page_url), SyntheticClock(), [scope]
    capture = PassiveNativeGateCapture(page, scope, scope_reader=lambda: current[0], clock=clock)
    request = SyntheticRequest(page)
    return {"scope": scope, "page": page, "clock": clock, "current": current,
            "capture": capture, "request": request, "response": SyntheticResponse(request)}


def emit_pair(case):
    case["clock"].seconds += 1
    case["page"].emit("request", case["request"])
    case["clock"].seconds += 1
    case["page"].emit("response", case["response"])
    case["page"].emit("requestfinished", case["request"])
