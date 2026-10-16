"""仅访问本机隔离服务，验证生产 Schema fetch 原语不会携带 POST 跟随重定向。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.sync_api import Error, sync_playwright

from src.execution.dxm_login_flow import DxmLoginFlow


@pytest.mark.parametrize('status', [307, 308])
@pytest.mark.parametrize('strict', [True, False])
def test_actual_chromium_schema_post_rejects_redirect_before_second_hop(status, strict):
    scripts = []
    class CapturedPage:
        def evaluate(self, script):
            scripts.append(script)
            return {'ok': False, 'reason': 'isolated_fetch_primitive_capture'}
    DxmLoginFlow.__new__(DxmLoginFlow)._capture_current_editor_category_schema(CapturedPage(),
        {'category_id': '17', 'category_schema_hash': 'A'*64}, phase='isolated_redirect_contract', reject_redirects=strict)
    script = scripts[0]
    # 仅抽取生产 fetch 原语；不改写其选项，也不访问任何店小秘站点。
    post = script[script.index('const post = async'):script.index('const asList =')]
    assert ("redirect: 'error'" in post) is strict
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
            self.wfile.write(b'<!doctype html><title>isolated redirect contract</title>')
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            requests.append((self.path, body))
            if self.path == '/api/smtCategory/attributeList.json':
                self.send_response(status); self.send_header('Location', '/second-hop'); self.end_headers()
            else:
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'code': 0, 'data': []}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                invoke = 'async () => {' + post + " return await post('/api/smtCategory/attributeList.json', {categoryId:'17'}); }"
                if strict:
                    with pytest.raises(Error, match='fetch'):
                        page.evaluate(invoke)
                    assert requests == [('/api/smtCategory/attributeList.json', b'categoryId=17')]
                else:
                    assert page.evaluate(invoke) == []
                    assert requests == [('/api/smtCategory/attributeList.json', b'categoryId=17'), ('/second-hop', b'categoryId=17')]
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
