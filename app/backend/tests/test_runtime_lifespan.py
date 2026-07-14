import asyncio
import subprocess
import sys

from fastapi.testclient import TestClient

from src import main as main_module


def test_app_lifespan_closes_visible_browser_sessions(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(main_module.login_flow, '_close_browser_session', lambda: calls.append('login-flow'))
    monkeypatch.setattr(main_module.agent_console_service, 'stop', lambda: calls.append('agent-console') or {'active': False})

    async def run_lifespan_once():
        async with main_module.app_lifespan(main_module.app):
            calls.append('running')

    asyncio.run(run_lifespan_once())

    assert calls == ['running', 'agent-console', 'login-flow']


def test_repeated_testclient_lifespan_never_releases_process_bootstrap_lease(monkeypatch):
    state = main_module.runtime_bootstrap_state
    lease = state.lease
    monkeypatch.setattr(main_module, '_recover_orphaned_runtime_tasks', lambda: {'recovered': [], 'cancelled': []})
    monkeypatch.setattr(main_module.agent_console_service, 'stop', lambda: {'active': False})
    monkeypatch.setattr(main_module.browser_agent_runtime, 'shutdown', lambda: None)

    assert lease.released is False
    for _ in range(2):
        with TestClient(main_module.app) as client:
            response = client.get('/health')
            assert response.status_code == 200
            assert response.json()['runtimeIdentity'] == state.runtime_identity.as_dict()
        assert lease.released is False
        assert main_module.runtime_bootstrap_state is state

    contender = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                "from src.services.runtime_lease import RuntimeDataLease, RuntimeLeaseConflictError; "
                f"data_dir={str(state.data_dir)!r}; "
                "\ntry:\n RuntimeDataLease.acquire(data_dir)\nexcept RuntimeLeaseConflictError:\n print('conflict')\nelse:\n raise SystemExit('lease unexpectedly released')"
            ),
        ],
        cwd=main_module.REPO_ROOT / 'app' / 'backend',
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert contender.returncode == 0, contender.stderr
    assert contender.stdout.strip() == 'conflict'
