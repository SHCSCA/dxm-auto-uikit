import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
LIBRARY = REPO_ROOT / "scripts" / "lib" / "desktop-smoke-log.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="需要 PowerShell 验证桌面 smoke 日志合同")


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def read_log(tmp_path, lines):
    path = tmp_path / "desktop-main.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    command = ("$ErrorActionPreference='Stop'; . " + literal(LIBRARY)
        + "; Read-DesktopSmokeLogText -Path " + literal(path))
    return subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)


def record(message, **overrides):
    return json.dumps({"schema": "dxm.log.v1", "component": "desktop", "fields": {"message": message}, **overrides})


def test_jsonl_decodes_windows_paths_before_exact_bundled_python_assertion(tmp_path):
    python = r"G:\package\resources\app\backend\python-runtime\python.exe"
    result = read_log(tmp_path, [record("Starting backend: " + python + " -m src.desktop_server"),
        record(r"Loaded frontend G:\package\resources\app\frontend\dist\index.html")])
    assert result.returncode == 0, result.stderr
    assert python in result.stdout
    assert "Starting backend" in result.stdout and "Loaded frontend" in result.stdout
    assert python.replace("\\", "\\\\") not in result.stdout


def test_plain_text_legacy_and_mixed_records_keep_the_original_message(tmp_path):
    legacy = r"[2026-10-15] Starting backend: G:\legacy\python.exe"
    result = read_log(tmp_path, [legacy, record("Loaded frontend legacy-compatible")])
    assert result.returncode == 0, result.stderr
    assert legacy in result.stdout
    assert "Loaded frontend legacy-compatible" in result.stdout


@pytest.mark.parametrize("line", ['{"schema":', record("Starting backend", schema="other.v1"),
    record("Starting backend", component="unexpected"),
    json.dumps({"schema": "dxm.log.v1", "component": "desktop", "fields": {"fake": "Starting backend"}})])
def test_malformed_or_unrelated_json_cannot_supply_smoke_success_markers(tmp_path, line):
    result = read_log(tmp_path, [line])
    assert result.returncode != 0
    assert "Starting backend" not in result.stdout


def test_verifier_keeps_all_original_backend_path_and_frontend_assertions():
    source = (REPO_ROOT / "scripts" / "verify-desktop-package.ps1").read_text(encoding="utf-8-sig")
    assert "$LogText = Read-DesktopSmokeLogText -Path $ExistingLog" in source
    for required in ("Starting backend", "Loaded frontend", "[regex]::Escape($BundledPythonPath)",
                     "[regex]::Escape($BundledPythonRelative)"):
        assert required in source
