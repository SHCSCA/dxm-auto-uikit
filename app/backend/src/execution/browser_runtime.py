from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any


def chrome_launch_options(headless: bool) -> dict[str, Any]:
    options: dict[str, Any] = {"headless": headless}
    executable_path = resolve_chrome_executable()
    if executable_path:
        options["executable_path"] = executable_path
    if platform.system() == "Windows":
        options["ignore_default_args"] = ["--no-sandbox"]
    else:
        options["args"] = ["--no-sandbox"]
    return options


def resolve_chrome_executable() -> str | None:
    env_path = os.getenv("DXM_CHROME_PATH")
    if env_path:
        return env_path

    for command in _chrome_commands():
        path = shutil.which(command)
        if path:
            return path

    for path in _known_chrome_paths():
        if path.exists():
            return str(path)
    return None


def _chrome_commands() -> tuple[str, ...]:
    system = platform.system()
    if system == "Windows":
        return ("chrome.exe", "msedge.exe")
    if system == "Darwin":
        return ("google-chrome", "chromium", "msedge")
    return ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium")


def _known_chrome_paths() -> tuple[Path, ...]:
    system = platform.system()
    if system == "Windows":
        local_app_data = Path(os.getenv("LOCALAPPDATA", ""))
        program_files = Path(os.getenv("PROGRAMFILES", "C:/Program Files"))
        program_files_x86 = Path(os.getenv("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        return (
            program_files / "Google/Chrome/Application/chrome.exe",
            program_files_x86 / "Google/Chrome/Application/chrome.exe",
            local_app_data / "Google/Chrome/Application/chrome.exe",
            program_files / "Microsoft/Edge/Application/msedge.exe",
            program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
        )
    if system == "Darwin":
        return (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        )
    return (
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    )
