import runpy
import os
from pathlib import Path


def test_rotate_local_and_show(tmp_path, monkeypatch):
    tf = tmp_path / 'tokenfile'
    monkeypatch.setenv('MCP_AUTH_FILE', str(tf))
    # load the script as a module dict
    mod = runpy.run_path('scripts/mcp_token.py')
    # rotate-local should write a token and return 0
    rc = mod['rotate_local']()
    assert rc == 0
    assert tf.exists()
    token = tf.read_text().strip()
    assert token

    # read_token should return the same
    got = mod['read_token']()
    assert got == token

    # show via main(['', 'show']) prints token; call main and ensure exit code 0
    rc = mod['main'](['', 'show'])
    assert rc == 0


def test_rotate_remote(tmp_path, monkeypatch):
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    tf = tmp_path / 'tokenfile'
    tf.write_text('current-token')
    monkeypatch.setenv('MCP_AUTH_FILE', str(tf))
    mod = runpy.run_path('scripts/mcp_token.py')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/v1/token/rotate':
                self.send_response(404); self.end_headers(); return
            auth = self.headers.get('Authorization', '')
            if auth != 'Bearer current-token':
                self.send_response(401); self.end_headers(); return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"token": "new-from-server"}')

    server = HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_port
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        rc = mod['rotate_remote'](f'http://127.0.0.1:{port}')
        assert rc == 0
    finally:
        server.shutdown()
        th.join(timeout=1)
