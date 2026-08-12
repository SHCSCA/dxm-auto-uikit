import asyncio
import subprocess
import sys

from fastapi.testclient import TestClient

from src import main as main_module


def test_app_lifespan_closes_visible_browser_sessions(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        main_module.batch_execution_runtime,
        'shutdown',
        lambda: calls.append('batch-runtime') or {'ok': True},
    )
    monkeypatch.setattr(main_module.agent_console_service, 'stop', lambda: calls.append('agent-console') or {'active': False})
    monkeypatch.setattr(
        main_module.browser_agent_runtime,
        'shutdown',
        lambda: calls.append('browser-runtime') or {'ok': True},
    )

    async def run_lifespan_once():
        async with main_module.app_lifespan(main_module.app):
            calls.append('running')

    asyncio.run(run_lifespan_once())

    assert calls == ['running', 'batch-runtime', 'agent-console', 'browser-runtime']


def test_app_lifespan_records_truth_when_browser_agent_shutdown_is_incomplete(monkeypatch):
    logs: list[str] = []

    monkeypatch.setattr(main_module, '_append_backend_runtime_log', logs.append)
    monkeypatch.setattr(main_module.agent_console_service, 'stop', lambda: {'active': False})
    monkeypatch.setattr(
        main_module.browser_agent_runtime,
        'shutdown',
        lambda: {
            'ok': False,
            'status': 'stopping',
            'reasonCode': 'BROWSER_AGENT_STOPPING',
            'needsRestart': True,
        },
    )

    async def run_lifespan_once():
        async with main_module.app_lifespan(main_module.app):
            return None

    asyncio.run(run_lifespan_once())

    assert any(
        'Browser Agent cleanup incomplete' in line
        and 'status=stopping' in line
        and 'reason=BROWSER_AGENT_STOPPING' in line
        for line in logs
    )


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
