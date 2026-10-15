from types import SimpleNamespace

import pytest

from src.core.config_bus import env_string
from src.execution.browser_agent_worker import execute_browser_agent_action


def test_one_action_keeps_its_configuration_snapshot(monkeypatch):
    monkeypatch.setenv("DXM_BOUNDARY_TEST", "before")
    observed = []

    def check_login_state():
        observed.append(env_string("DXM_BOUNDARY_TEST"))
        monkeypatch.setenv("DXM_BOUNDARY_TEST", "after")
        observed.append(env_string("DXM_BOUNDARY_TEST"))
        return {"ok": True}

    result = execute_browser_agent_action(SimpleNamespace(check_login_state=check_login_state), "check_login_state")
    assert result == {"ok": True}
    assert observed == ["before", "before"]
    assert env_string("DXM_BOUNDARY_TEST") == "after"


def test_action_failure_is_recorded_and_propagated_once(caplog):
    calls = []
    failure = RuntimeError("动作无法完成")

    def check_login_state():
        calls.append("attempt")
        raise failure

    with pytest.raises(RuntimeError) as caught:
        execute_browser_agent_action(SimpleNamespace(check_login_state=check_login_state), "check_login_state")
    assert caught.value is failure
    assert calls == ["attempt"]
    assert "browser_action_failed" in caplog.text


def test_unbound_target_is_rejected_before_adapter_dispatch(caplog):
    calls = []
    adapter = SimpleNamespace(save_only=lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match="frozen exact target_identity"):
        execute_browser_agent_action(adapter, "save_only", {})
    assert calls == []
    assert "browser_action_failed" in caplog.text
