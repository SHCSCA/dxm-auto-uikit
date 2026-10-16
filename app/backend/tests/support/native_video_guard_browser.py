"""本机 HTTP/WS 合成服务器；未知请求一律失败，不连接外部网络。"""

import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


@contextmanager
def local_video_server():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.respond()

        def do_GET(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            hits.append((self.command, self.path, body))
            if self.path == '/ws':
                key = self.headers.get('Sec-WebSocket-Key', '')
                accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.send_response(101)
                self.send_header('Upgrade', 'websocket')
                self.send_header('Connection', 'Upgrade')
                self.send_header('Sec-WebSocket-Accept', accept)
                self.end_headers()
                # 发送固定消息证明未激活时确实完成握手并保持原生传输。
                self.wfile.write(b'\x81\x02ok')
                self.wfile.flush()
                self.connection.settimeout(2)
                try:
                    self.connection.recv(256)
                except TimeoutError:
                    pass
                return
            status = int(self.path.rsplit('/', 1)[1]) if self.path.startswith('/redirect/') else 200
            payload = b'<html><body>local synthetic fixture</body></html>' if self.path == '/' else b'ok'
            self.send_response(status)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Content-Type', 'text/html')
            if 300 <= status < 400:
                self.send_header('Location', '/second-hop')
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
