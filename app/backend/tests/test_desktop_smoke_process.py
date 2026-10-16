import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
LIBRARY = REPO_ROOT / "scripts" / "lib" / "desktop-smoke-process.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="需要 PowerShell 验证本次 smoke 进程清理合同")


def invoke(body):
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); . '"
        + str(LIBRARY).replace("'", "''") + "'; " + body)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)


def test_cleanup_only_calls_the_owned_process_object():
    result = invoke("""
      $Owned=[PSCustomObject]@{Id=4321;HasExited=$false;Killed=$false};
      $Other=[PSCustomObject]@{Id=4322;HasExited=$false;Killed=$false};
      foreach($Process in @($Owned,$Other)){
        $Process|Add-Member ScriptMethod Kill {$this.Killed=$true;$this.HasExited=$true};
        $Process|Add-Member ScriptMethod WaitForExit {$true};
      };
      Stop-DesktopSmokeProcess -Process $Owned -Label 'owned-contract';
      [PSCustomObject]@{ownedKilled=$Owned.Killed;otherKilled=$Other.Killed}|ConvertTo-Json -Compress
    """)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ownedKilled": True, "otherKilled": False}


@pytest.mark.parametrize("method", ["throw 'cleanup-denied'", "$this.HasExited=$true"])
def test_cleanup_failure_logs_the_owned_pid_and_propagates(method):
    result = invoke("""
      $Owned=[PSCustomObject]@{Id=4321;HasExited=$false};
      $Owned|Add-Member ScriptMethod Kill {""" + method + """};
      $Owned|Add-Member ScriptMethod WaitForExit {$false};
      Stop-DesktopSmokeProcess -Process $Owned -Label 'owned-failure'
    """)
    assert result.returncode != 0
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{"schema"')]
    assert len(records) == 1, result.stderr
    assert records[0]["schema"] == "dxm.log.v1"
    assert records[0]["level"] == "ERROR"
    assert records[0]["event"] == "process_cleanup_failed"
    assert records[0]["fields"]["pid"] == 4321
    assert records[0]["fields"]["label"] == "owned-failure"


def test_verifier_hides_default_helpers_and_delegates_only_explicit_visible_launch():
    source = (REPO_ROOT / "scripts" / "verify-desktop-package.ps1").read_text(encoding="utf-8-sig")
    visible = (REPO_ROOT / "scripts" / "lib" / "desktop-visible-smoke.ps1").read_text(encoding="utf-8-sig")
    launches = [line for line in source.splitlines() if "Start-Process " in line]
    assert len(launches) == 2
    assert all("-WindowStyle Hidden" in line for line in launches)
    assert "-WindowStyle Normal" in visible
    assert "if (!$AllowVisibleWindow)" in visible
    assert "Invoke-VisibleDesktopSmoke" in source
    assert "-AllowVisibleWindow:$AllowVisibleWindow" in source
    for combined in (source, visible):
        assert "Get-Process" not in combined and "taskkill" not in combined and "Stop-Process " not in combined
    for owned in ("$Process", "$PortableProcess"):
        assert "Stop-DesktopSmokeProcess -Process " + owned in source
    assert "Stop-DesktopSmokeProcess -Process $VisibleProcess" in visible
