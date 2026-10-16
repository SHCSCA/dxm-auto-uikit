"""仅使用合成脚本与事件对象，避免读取真实会话或公开源码缓存。"""

from hashlib import sha256
from types import SimpleNamespace
from contextlib import contextmanager

from src.execution import native_video_script_capture as subject


SCRIPTS = {"synthetic-a.js": b"window.syntheticA = 17;", "synthetic-b.js": b"window.syntheticB = 23;"}
EDITOR_URL = "https://www.dianxiaomi.com/web/smt/edit?id=70001"


class ScriptPage:
    def __init__(self, url=EDITOR_URL):
        self.url, self.main_frame = url, SimpleNamespace(page=self, url=url)
        self.listeners, self.removals, self.registrations = {}, [], []
        self.registration_failure = self.removal_failure = None
        self.in_callback = False

    def on(self, event, handler):
        self.registrations.append(event)
        self.listeners.setdefault(event, []).append(handler)
        if event == self.registration_failure:
            raise RuntimeError("synthetic listener registration failed")

    def remove_listener(self, event, handler):
        self.removals.append(event)
        if event == self.removal_failure:
            raise RuntimeError("synthetic listener cleanup failed")
        self.listeners[event].remove(handler)

    def emit(self, event, request):
        if event == "requestfinished":
            request.finished = True
        previous, self.in_callback = self.in_callback, True
        try:
            for handler in list(self.listeners.get(event, [])):
                handler(request)
        finally:
            self.in_callback = previous


class ScriptRequest:
    def __init__(self, page, name):
        self.page = page
        self.url, self.method, self.resource_type = subject.PUBLIC_ASSET_BASE + name, "GET", "script"
        self.frame, self.redirected_from, self.redirected_to = page.main_frame, None, None
        self.finished, self.response_reads = False, 0
        self.response_value = ScriptResponse(self, SCRIPTS[name])

    def response(self):
        assert not self.page.in_callback, "事件回调只登记，禁止回调内响应 RPC"
        self.response_reads += 1
        assert self.finished, "只能在真实完成事件后读取响应"
        return self.response_value


class ScriptResponse:
    def __init__(self, request, body):
        self.request, self.status, self.raw, self.reads = request, 200, body, 0
        self.headers = {"content-type": "application/javascript", "content-length": str(len(body))}
        self.body_error = None

    def body(self):
        assert not self.request.page.in_callback, "事件回调只登记，禁止回调内 body RPC"
        self.reads += 1
        assert self.request.finished, "只能在真实完成事件后读取 body"
        if self.body_error:
            raise self.body_error
        return self.raw


def make_case(monkeypatch, *, page_url=EDITOR_URL):
    monkeypatch.setattr(subject, "REVIEWED_VIDEO_SCRIPTS", {
        name: (len(body), sha256(body).hexdigest().upper()) for name, body in SCRIPTS.items()})
    page = ScriptPage(page_url)
    return SimpleNamespace(page=page, capture=subject.PassiveNativeVideoScriptCapture(page, expected_page_url=EDITOR_URL),
        requests={name: ScriptRequest(page, name) for name in SCRIPTS})


def complete(case):
    for request in case.requests.values():
        case.page.emit("request", request)
        case.page.emit("requestfinished", request)


def assert_no_authority(result):
    assert result["executionAllowed"] is False
    assert result["capabilityCertified"] is False
    assert result["inputFreezeAllowed"] is False


def assert_incomplete(case, reason=None):
    result = case.capture.snapshot()
    assert result["reviewed_resources_match"] is False
    assert_no_authority(result)
    if reason:
        assert "NATIVE_VIDEO_STATIC_" + reason in result["issues"]
    return result


@contextmanager
def local_chromium_case(monkeypatch, *, script_count=1):
    from playwright.sync_api import Request, Response, sync_playwright

    origin = "http://127.0.0.1:19876/"
    scripts = {f'synthetic-local-{index}.js': (b'window.syntheticVideoCapture = 17;' if index == 0 else
        f'window.syntheticConcurrent{index} = {index};'.encode()) for index in range(script_count)}
    monkeypatch.setattr(subject, "PUBLIC_ASSET_BASE", origin + "assets/")
    monkeypatch.setattr(subject, "REVIEWED_VIDEO_SCRIPTS", {
        name: (len(body), sha256(body).hexdigest().upper()) for name, body in scripts.items()})
    finished, body_reads, response_reads, routed, pending_routes = [], [], [], [], []
    callback = {'active': False}
    original_body, original_response = Response.body, Request.response

    def read_response(request):
        assert not callback['active'], '事件回调不能执行响应 RPC'
        assert any(item is request for item in finished)
        response_reads.append(request)
        return original_response(request)

    def read_body(response):
        assert not callback['active'], '事件回调不能执行 body RPC'
        assert any(item is response.request for item in finished)
        body_reads.append(response.request)
        return original_body(response)
    monkeypatch.setattr(Request, 'response', read_response)
    monkeypatch.setattr(Response, "body", read_body)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            def route_local(route):
                routed.append(route.request.url)
                if route.request.url == origin + "index.html":
                    html = ''.join(f'<script async src="/assets/{name}"></script>' for name in scripts)
                    route.fulfill(status=200, content_type="text/html", body=html)
                elif route.request.url in {origin + 'assets/' + name for name in scripts}:
                    pending_routes.append(route)
                    # 全部并发请求先抵达才返回，避免把串行加载误当并发验证。
                    if len(pending_routes) == len(scripts):
                        for pending in pending_routes:
                            body = scripts[pending.request.url.rsplit('/', 1)[-1]]
                            pending.fulfill(status=200, headers={"Content-Type": "application/javascript",
                                "Content-Length": str(len(body))}, body=body)
                else:
                    route.abort()
            page.route("**/*", route_local)
            for event in ('request', 'requestfinished', 'requestfailed', 'framenavigated'):
                page.on(event, lambda *_args: callback.update(active=True))
            page.on("requestfinished", lambda request: finished.append(request))
            capture = subject.PassiveNativeVideoScriptCapture(page, expected_page_url=origin + "index.html").start()
            for event in ('request', 'requestfinished', 'requestfailed', 'framenavigated'):
                page.on(event, lambda *_args: callback.update(active=False))
            try:
                page.goto(origin + "index.html", wait_until="networkidle")
                reads_before_close = (len(response_reads), len(body_reads))
                queued_before_close = len(capture.finished_bodies)
            finally:
                capture.close()
            yield SimpleNamespace(page=page, capture=capture, body_reads=body_reads, response_reads=response_reads,
                reads_before_close=reads_before_close, queued_before_close=queued_before_close,
                routed=routed, origin=origin, scripts=scripts)
        finally:
            browser.close()
