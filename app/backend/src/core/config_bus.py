from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlparse

from src.core.config_models import (
    LoggingConfiguration, RuntimeConfiguration, RuntimePaths, ServerConfiguration,
)


class ConfigurationError(ValueError):
    reason_code = "RUNTIME_CONFIGURATION_INVALID"


_SCOPED_BUS: ContextVar[ConfigurationBus | None] = ContextVar("dxm_configuration_bus", default=None)


@dataclass(frozen=True, slots=True)
class ConfigurationBus:
    environment: Mapping[str, str] = field(repr=False)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> ConfigurationBus:
        return cls(MappingProxyType(dict(os.environ if environ is None else environ)))

    def string(self, name: str, default: str | None = None) -> str | None:
        return self.environment.get(name, default)

    def integer(self, name: str, default: int, *, minimum: int, maximum: int) -> int:
        raw = self.string(name)
        if raw is None or raw == "":
            return default
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", raw):
            raise ConfigurationError(f"{name} 必须使用规范整数格式")
        value = int(raw)
        if not minimum <= value <= maximum:
            raise ConfigurationError(f"{name} 必须在 {minimum} 至 {maximum} 之间")
        return value

    def boolean(self, name: str, default: bool = False) -> bool:
        raw = self.string(name)
        if raw is None or raw == "":
            return default
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(f"{name} 必须为明确的布尔值")

    def number(self, name: str, default: float, *, minimum: float, maximum: float) -> float:
        raw = self.string(name)
        if raw is None or raw == "":
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{name} 必须为有限数值") from exc
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ConfigurationError(f"{name} 必须在 {minimum} 至 {maximum} 之间")
        return value

    def runtime(self, base_dir: Path | None = None) -> RuntimeConfiguration:
        backend_root = base_dir or Path(__file__).resolve().parents[2]
        data_dir = Path(self.string("DXM_DATA_DIR") or backend_root.parent.parent / "data").expanduser().resolve()
        desktop = self.string("DXM_RUNTIME_OWNER") == "electron_desktop" or self.string("DXM_DESKTOP") == "1"
        log_name = "desktop-main.log" if desktop else "start-mvp.log"
        paths = RuntimePaths(
            data_dir=data_dir,
            launcher_log=Path(self.string("DXM_LAUNCHER_LOG_FILE") or data_dir / log_name),
            runtime_control_command=Path(self.string("DXM_RUNTIME_CONTROL_COMMAND_FILE") or data_dir / "runtime-control-command.json"),
        )
        backend_port = self.integer("DXM_BACKEND_PORT", 8000, minimum=1, maximum=65535)
        frontend_port = self.integer("DXM_FRONTEND_PORT", 5173, minimum=1, maximum=65535)
        server = ServerConfiguration(
            backend_port=backend_port,
            frontend_port=frontend_port,
            backend_url=_loopback_url(self.string("DXM_BACKEND_URL") or f"http://127.0.0.1:{backend_port}", "DXM_BACKEND_URL"),
            frontend_url=_loopback_url(self.string("DXM_FRONTEND_URL"), "DXM_FRONTEND_URL"),
        )
        level = (self.string("DXM_LOG_LEVEL") or "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("DXM_LOG_LEVEL 不是受支持的日志等级")
        return RuntimeConfiguration(paths, server, LoggingConfiguration(level))


def _loopback_url(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{name} 不是有效的本机地址") from exc
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)):
        raise ConfigurationError(f"{name} 必须是无凭据的 loopback HTTP 地址")
    return value.rstrip("/")


def get_config_bus() -> ConfigurationBus:
    # 显式作用域内固定快照；未进入作用域时保留现有进程环境更新的兼容语义。
    return _SCOPED_BUS.get() or ConfigurationBus.from_environment()


@contextmanager
def configuration_scope(environ: Mapping[str, str] | None = None) -> Iterator[ConfigurationBus]:
    bus = ConfigurationBus.from_environment(environ)
    token = _SCOPED_BUS.set(bus)
    try:
        yield bus
    finally:
        _SCOPED_BUS.reset(token)


def env_string(name: str, default: str | None = None) -> str | None:
    return get_config_bus().string(name, default)


def env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    return get_config_bus().integer(name, default, minimum=minimum, maximum=maximum)


def env_bool(name: str, default: bool = False) -> bool:
    return get_config_bus().boolean(name, default)


def env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    return get_config_bus().number(name, default, minimum=minimum, maximum=maximum)
