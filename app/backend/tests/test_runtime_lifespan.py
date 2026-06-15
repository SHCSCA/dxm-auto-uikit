import asyncio

from src import main as main_module


def test_app_lifespan_closes_visible_browser_sessions(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(main_module.login_flow, '_close_browser_session', lambda: calls.append('login-flow'))
    monkeypatch.setattr(main_module.agent_console_service, 'stop', lambda: calls.append('agent-console') or {'active': False})

    async def run_lifespan_once():
        async with main_module.app_lifespan(main_module.app):
            calls.append('running')

    asyncio.run(run_lifespan_once())

    assert calls == ['running', 'login-flow', 'agent-console']
