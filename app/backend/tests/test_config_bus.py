from dataclasses import FrozenInstanceError

import pytest

from src.core.config_bus import (
    ConfigurationBus, ConfigurationError, configuration_scope, env_bool, env_float, env_int, env_string,
)


def test_snapshot_is_immutable_and_import_style_resolution_never_creates_data(tmp_path):
    environment = {"DXM_DATA_DIR": str(tmp_path / "runtime"), "DXM_BACKEND_PORT": "8012"}
    bus = ConfigurationBus.from_environment(environment)
    configuration = bus.runtime()
    environment["DXM_BACKEND_PORT"] = "9999"
    assert configuration.server.backend_port == 8012
    assert bus.string("DXM_BACKEND_PORT") == "8012"
    assert not configuration.paths.data_dir.exists()
    with pytest.raises(TypeError):
        bus.environment["DXM_BACKEND_PORT"] = "9000"
    with pytest.raises(FrozenInstanceError):
        configuration.server.backend_port = 9000


@pytest.mark.parametrize("value", ["0", "65536", "1.0", "08000", " 8000", "false"])
def test_runtime_rejects_ambiguous_or_invalid_port(value):
    with pytest.raises(ConfigurationError, match="DXM_BACKEND_PORT"):
        ConfigurationBus.from_environment({"DXM_BACKEND_PORT": value}).runtime()


@pytest.mark.parametrize("value", ["https://remote.invalid", "http://user:pass@127.0.0.1:8000", "file://", "http://127.0.0.1?token=private"])
def test_runtime_endpoints_cannot_escape_loopback_or_embed_credentials(value):
    with pytest.raises(ConfigurationError, match="DXM_BACKEND_URL"):
        ConfigurationBus.from_environment({"DXM_BACKEND_URL": value}).runtime()


def test_nested_scope_is_frozen_and_restored_after_exception(monkeypatch):
    monkeypatch.setenv("DXM_TEST_SETTING", "process")
    with configuration_scope({"DXM_TEST_SETTING": "outer"}):
        monkeypatch.setenv("DXM_TEST_SETTING", "changed")
        assert env_string("DXM_TEST_SETTING") == "outer"
        with pytest.raises(RuntimeError):
            with configuration_scope({"DXM_TEST_SETTING": "inner"}):
                assert env_string("DXM_TEST_SETTING") == "inner"
                raise RuntimeError("scope aborted")
        assert env_string("DXM_TEST_SETTING") == "outer"
    assert env_string("DXM_TEST_SETTING") == "changed"


def test_typed_configuration_cannot_turn_malformed_values_into_authorization():
    with configuration_scope({"DXM_TEST_FLAG": "maybe", "DXM_TEST_NUMBER": "nan"}):
        with pytest.raises(ConfigurationError):
            env_bool("DXM_TEST_FLAG")
        with pytest.raises(ConfigurationError):
            env_float("DXM_TEST_NUMBER", 1.0, minimum=0, maximum=10)
        assert env_int("DXM_MISSING", 3, minimum=1, maximum=5) == 3
    assert "maybe" not in repr(ConfigurationBus.from_environment({"DXM_TEST_FLAG": "maybe"}))
