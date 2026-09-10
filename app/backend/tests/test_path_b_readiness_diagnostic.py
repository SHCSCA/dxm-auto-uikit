from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def local_backend():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200 if self.path == '/health' else 404)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_isolated_wrapper(tmp_path, base_url, *, lock=False):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    for name in ('diagnose-path-b-readiness.ps1', 'path_b_readiness.py'):
        source = ROOT / 'scripts' / name
        if source.exists():
            shutil.copyfile(source, scripts / name)
    if lock:
        (tmp_path / 'data').mkdir()
        (tmp_path / 'data' / '.dxm-runtime.lock').write_bytes(b'\0{}')
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('DXM_PATH_B_CLOSED_LOOP', None)
    env.pop('DXM_DATA_DIR', None)
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         str(scripts / 'diagnose-path-b-readiness.ps1'), '-BaseUrl', base_url],
        cwd=tmp_path, env=env, capture_output=True, timeout=20,
    )
    return result.stdout.decode('utf-8', errors='replace')


def test_runtime_lease_file_is_not_a_replay_mode_flag(tmp_path, local_backend):
    output = run_isolated_wrapper(tmp_path, local_backend[0], lock=True)
    assert 'Closed-loop driver still active' not in output
    assert (tmp_path / 'data' / '.dxm-runtime.lock').read_bytes() == b'\0{}'


def test_diagnostic_calls_real_health_route(tmp_path, local_backend):
    run_isolated_wrapper(tmp_path, local_backend[0])
    assert local_backend[1] == ['/health']


def diagnostic_module():
    spec = importlib.util.spec_from_file_location('path_b_readiness', ROOT / 'scripts' / 'path_b_readiness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_and_environment_data_dirs_override_repo_data(tmp_path):
    diagnostic = diagnostic_module()
    assert diagnostic.resolve_data_dir(tmp_path, None, {'DXM_DATA_DIR': str(tmp_path / 'external')}) == tmp_path / 'external'
    assert diagnostic.resolve_data_dir(tmp_path, str(tmp_path / 'explicit'), {'DXM_DATA_DIR': str(tmp_path / 'external')}) == tmp_path / 'explicit'


def test_cookie_contents_are_never_read_or_treated_as_live_login(tmp_path, monkeypatch):
    diagnostic = diagnostic_module()
    session = tmp_path / 'sessions' / 'dianxiaomi_cookies.json'
    session.parent.mkdir()
    session.write_text('SYNTHETIC_SECRET_DO_NOT_PRINT', encoding='utf-8')

    def forbid_read(*_args, **_kwargs):
        raise AssertionError('Diagnostic must not open the cookie file')

    monkeypatch.setattr(Path, 'read_text', forbid_read)
    monkeypatch.setattr(Path, 'read_bytes', forbid_read)
    result = diagnostic.cookie_presence(tmp_path)
    assert result['status'] == 'info'
    assert 'SYNTHETIC_SECRET_DO_NOT_PRINT' not in json.dumps(result)


def test_scope_inspection_does_not_create_database_and_uses_current_tables(tmp_path):
    diagnostic = diagnostic_module()
    assert diagnostic.scope_counts(tmp_path)['status'] == 'blocked'
    assert list(tmp_path.iterdir()) == []
    db_file = tmp_path / 'sqlite' / 'dxm_auto_uikit.db'
    db_file.parent.mkdir()
    with sqlite3.connect(db_file) as connection:
        for name in ('real_dxm_write_scopes', 'real_dxm_path_b_discovery_attempts', 'real_dxm_path_b_discovery_receipts'):
            connection.execute(f'CREATE TABLE {name} (status TEXT)')
            connection.execute(f'INSERT INTO {name} VALUES (?)', ('prepared',))
    before = db_file.read_bytes()
    result = diagnostic.scope_counts(tmp_path)
    assert result['counts'] == {'scopes': 1, 'discoveryAttempts': 1, 'discoveryReceipts': 1}
    assert result['status'] == 'unknown'  # A row count never proves valid authority.
    assert db_file.read_bytes() == before


def test_only_loopback_http_without_credentials_or_redirects_is_allowed(local_backend):
    diagnostic = diagnostic_module()
    for value in ('https://example.com', 'http://127.0.0.1.evil.com', 'http://user:secret@127.0.0.1:8000', 'http://127.0.0.1:8000/path'):
        with pytest.raises(ValueError):
            diagnostic.validate_base_url(value)
    assert diagnostic.validate_base_url(local_backend[0]) == local_backend[0]


def test_missing_runtime_identity_never_means_ready(local_backend, tmp_path):
    diagnostic = diagnostic_module()
    result = diagnostic.backend_session(local_backend[0], ROOT, tmp_path)
    assert result['status'] == 'blocked'
    assert result['code'] == 'RUNTIME_IDENTITY_MISMATCH'
    assert local_backend[1] == ['/health']


def test_cli_never_creates_missing_runtime_or_claims_save_ready(tmp_path, local_backend):
    data_dir = tmp_path / 'missing-runtime'
    env = dict(os.environ, DXM_DATA_DIR=str(data_dir), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'scripts' / 'path_b_readiness.py'), '--base-url', local_backend[0], '--json'],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=20,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['dataDir'] == str(data_dir)
    assert report['productionReady'] is False
    assert not data_dir.exists()


@pytest.mark.parametrize('problem', ['none', 'missing_counter', 'stale', 'tampered_image', 'old_code', 'other_directory'])
def test_l2_diagnostic_uses_formal_checks_in_current_directory(tmp_path, monkeypatch, problem):
    from src.services import delivery_workspace
    from test_delivery_workspace import _write_l2_probe_result

    diagnostic = diagnostic_module()
    current = tmp_path / 'l2_readonly_probe'
    current.mkdir()
    source = tmp_path / 'other' if problem == 'other_directory' else current
    monkeypatch.setattr(delivery_workspace, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(delivery_workspace, 'L2_RUNTIME_PROBE_DIR', current)
    monkeypatch.setattr(delivery_workspace, 'L2_PROBE_DIR', source)
    json_path = _write_l2_probe_result(
        source,
        created_at=(datetime.now(timezone.utc) - timedelta(hours=3 if problem == 'stale' else 0)).isoformat(),
        git_head='f' * 40 if problem == 'old_code' else diagnostic.git_head(ROOT),
        script_sha256=hashlib.sha256((ROOT / 'tools' / 'probes' / 'l2_readonly_probe.py').read_bytes()).hexdigest(),
    )
    if problem == 'missing_counter':
        payload = json.loads(json_path.read_text(encoding='utf-8'))
        payload['network'].pop('write_request_count')
        json_path.write_text(json.dumps(payload), encoding='utf-8')
    if problem == 'tampered_image':
        (source / 'draft_box.png').write_bytes(b'tampered fixture')
    # Fresh file timestamps cannot repair old created_at evidence.
    os.utime(json_path, None)
    result = diagnostic.l2_evidence(tmp_path, 7200)
    assert result['status'] == ('pass' if problem == 'none' else 'blocked')
    if problem == 'none':
        assert result['code'] == 'L2_FILE_GATE_PASSED'


def test_windows_wrapper_preserves_chinese_without_utf8_environment(tmp_path, local_backend):
    env = dict(os.environ, DXM_DATA_DIR=str(tmp_path / 'missing'), PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONIOENCODING', None)
    env.pop('PYTHONUTF8', None)
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         str(ROOT / 'scripts' / 'diagnose-path-b-readiness.ps1'), '-BaseUrl', local_backend[0]],
        cwd=ROOT, env=env, capture_output=True, timeout=20,
    )
    assert result.returncode == 2
    assert '当前运行目录' in result.stdout.decode('utf-8')


def test_http_redirect_is_not_followed():
    diagnostic = diagnostic_module()
    requests = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/not-allowed')
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(Exception):
            diagnostic.local_json(f'http://127.0.0.1:{server.server_port}', '/health')
        assert requests == ['/health']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
