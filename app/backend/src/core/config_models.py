from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    data_dir: Path
    launcher_log: Path
    runtime_control_command: Path

    @property
    def sqlite_dir(self) -> Path:
        return self.data_dir / "sqlite"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidences"

    @property
    def screenshot_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def session_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def ai_dir(self) -> Path:
        return self.data_dir / "ai"


@dataclass(frozen=True, slots=True)
class ServerConfiguration:
    backend_port: int
    frontend_port: int
    backend_url: str
    frontend_url: str | None


@dataclass(frozen=True, slots=True)
class LoggingConfiguration:
    level: str


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    paths: RuntimePaths
    server: ServerConfiguration
    logging: LoggingConfiguration
