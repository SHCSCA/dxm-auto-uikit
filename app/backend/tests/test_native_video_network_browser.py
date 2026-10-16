"""离线 Chromium 只运行合成按钮；全部请求均本地 fulfill，不访问 DXM 服务。"""

import json

from playwright.sync_api import Response, sync_playwright

from src.execution.native_video_network_capture import PassiveNativeVideoNetworkCapture
from src.execution.native_video_network_contract import validate_video_wire_observation
from src.execution.native_video_wire import GENERATION_URL, PROGRESS_URL
from tests.support.native_video_network_case import GENERATION_BODY, MEDIA, PAGE_URL, UUID, make_case


def test_actual_playwright_objects_are_bound_and_body_is_read_after_actual_finished_only(monkeypatch):
    case = make_case()
    routed, finished, read_bodies = [], [], []
    original_body = Response.body

    def body_after_finished(response):
        assert any(request is response.request for request in finished)
        read_bodies.append(response.request)
        return original_body(response)

    monkeypatch.setattr(Response, 'body', body_after_finished)
    html = f'''<button id="generate">SyntheticGeneration</button><script>
      document.querySelector('#generate').onclick=async()=>{{
        const generation=await fetch({json.dumps(GENERATION_URL)},{{method:'POST',
          headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:{json.dumps(GENERATION_BODY.decode())}}}).then(r=>r.json());
        window.syntheticProgress=await fetch({json.dumps(PROGRESS_URL)},{{method:'POST',
          headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'uuid='+encodeURIComponent(generation.data)}}).then(r=>r.json());
      }};
    </script>'''
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()

            def offline_only(route):
                routed.append(route.request.url)
                if route.request.url == PAGE_URL:
                    route.fulfill(status=200, content_type='text/html', body=html)
                elif route.request.url in {GENERATION_URL, PROGRESS_URL}:
                    data = {'code': 0, 'data': UUID} if route.request.url == GENERATION_URL else {
                        'code': 0, 'data': {'processMsg': {'code': 1, 'data': MEDIA}}}
                    raw = json.dumps(data, separators=(',', ':')).encode()
                    route.fulfill(status=200, headers={'Content-Type': 'application/json', 'Content-Length': str(len(raw))}, body=raw)
                else:
                    route.abort()

            context.route('**/*', offline_only)
            page = context.new_page()
            page.goto(PAGE_URL, wait_until='networkidle')
            page.on('requestfinished', lambda request: finished.append(request))
            capture = PassiveNativeVideoNetworkCapture(page, case.scope, command=case.command,
                scope_reader=lambda: case.scope, clock=case.clock).start()
            try:
                page.get_by_role('button', name='SyntheticGeneration', exact=True).click()
                page.wait_for_function('window.syntheticProgress !== undefined')
                page.wait_for_load_state('networkidle')
            finally:
                capture.close()
            record = capture.private_facts()
            assert record['wire_complete'] is True, [{key: item['request'].timing[key]
                for key in ('startTime', 'requestStart', 'responseEnd')} for item in capture.entries]
            assert len(read_bodies) == 2
            assert routed == [PAGE_URL, GENERATION_URL, PROGRESS_URL]
            assert all(type(request).__name__ == 'Request' for request in read_bodies)
            derived = validate_video_wire_observation(record, expected_scope=case.scope, limits=capture.limits)
            assert derived['media_candidate'] == MEDIA
            assert derived['business_success_proven'] is derived['placement_proven'] is False
            assert capture.summary()['inputFreezeAllowed'] is False
        finally:
            browser.close()
