import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
LIBRARY = ROOT / "scripts/lib/desktop-visible-smoke.ps1"
PROCESS_LIBRARY = ROOT / "scripts/lib/desktop-smoke-process.ps1"
HARNESS = Path(__file__).with_name("fixtures") / "desktop_visible_smoke_harness.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="需要 PowerShell 验证默认隐藏与显式可见授权合同")


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _invoke(tmp_path, body, mode="good"):
    script = (
        "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        f". {_quote(PROCESS_LIBRARY)}; . {_quote(LIBRARY)}; "
        f"$VisiblePath={_quote(tmp_path / 'visible result.json')}; "
        f"$ExePath={_quote(tmp_path / 'app.exe')}; $UserDataDir={_quote(tmp_path / 'qa user data')}; "
        f"$script:Mode={_quote(mode)}; . {_quote(HARNESS)}; " + body
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )


def _verification(tmp_path):
    return json.loads((tmp_path / "visible result.json.verification.json").read_bytes())


def test_default_never_launches_and_keeps_stale_visible_result_non_passing(tmp_path):
    previous = b'{"ok":true,"windowVisible":true}'
    result_path = tmp_path / "visible result.json"
    result_path.write_bytes(previous)
    result = _invoke(tmp_path, """
      $Verification=Invoke-VisibleDesktopSmoke -ExePath $ExePath -VisibleSmokePath $VisiblePath -UserDataDir $UserDataDir;
      Write-HarnessResult -Verification $Verification;
      exit $Verification.exitCode
    """)
    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["launches"] == []
    assert payload["verification"]["status"] == "PENDING_PERMISSION"
    assert payload["verification"]["ok"] is False
    assert payload["verification"]["reasonCode"] == "VISIBLE_WINDOW_PERMISSION_REQUIRED"
    assert _verification(tmp_path)["status"] == "PENDING_PERMISSION"
    assert result_path.read_bytes() == previous
    diagnostic = json.loads(result.stderr.strip())
    assert diagnostic["schema"] == "dxm.log.v1"
    assert diagnostic["event"] == "visible_smoke_pending_permission"


def test_authorized_run_only_launches_the_owned_process_and_validates_real_result(tmp_path):
    result = _invoke(tmp_path, """
      $Verification=Invoke-VisibleDesktopSmoke -ExePath $ExePath -VisibleSmokePath $VisiblePath -UserDataDir $UserDataDir -AllowVisibleWindow;
      Write-HarnessResult -Verification $Verification
    """)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verification"]["status"] == "PASSED"
    assert payload["verification"]["processId"] == 4321
    assert len(payload["launches"]) == 1
    launch = payload["launches"][0]
    assert launch["windowStyle"] == "Normal"
    assert launch["filePath"] == str(tmp_path / "app.exe")
    assert launch["arguments"] == [
        f'"--qa-visible-smoke={tmp_path / "visible result.json"}"',
        f'"--qa-user-data-dir={tmp_path / "qa user data"}"',
    ]
    assert payload["otherKilled"] is False
    assert _verification(tmp_path)["ok"] is True


@pytest.mark.parametrize("mode,reason", [
    ("timeout", "VISIBLE_SMOKE_TIMEOUT"),
    ("nonzero", "VISIBLE_SMOKE_PROCESS_FAILED"),
    ("missing", "VISIBLE_SMOKE_RESULT_MISSING"),
    ("invisible", "VISIBLE_SMOKE_WINDOW_NOT_VISIBLE"),
    ("start-failure", "test-launch-denied"),
    ("cleanup-failure", "test-cleanup-denied"),
])
def test_authorized_failures_clean_only_owned_process_and_propagate(tmp_path, mode, reason):
    result = _invoke(tmp_path, """
      try {
        Invoke-VisibleDesktopSmoke -ExePath $ExePath -VisibleSmokePath $VisiblePath -UserDataDir $UserDataDir -WaitSeconds 1 -AllowVisibleWindow | Out-Null;
        throw 'test-must-not-pass'
      } catch {
        Write-HarnessResult -ErrorText $_.Exception.Message;
        exit 1
      }
    """, mode=mode)
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert reason in payload["error"]
    assert payload["otherKilled"] is False
    if mode == "timeout":
        assert payload["ownedKilled"] is True
    assert _verification(tmp_path)["status"] == "FAILED"
    assert _verification(tmp_path)["ok"] is False
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{"schema"')]
    assert any(item["event"] == "visible_smoke_failed" and item["level"] == "ERROR" for item in records)
    if mode == "invisible":
        assert json.loads((tmp_path / "visible result.json").read_bytes())["windowVisible"] is False


def test_post_result_validation_failure_is_not_hidden_by_process_exit(tmp_path):
    result = _invoke(tmp_path, """
      try {
        Invoke-VisibleDesktopSmoke -ExePath $ExePath -VisibleSmokePath $VisiblePath -UserDataDir $UserDataDir -AllowVisibleWindow -VerifyLog {throw 'test-log-invalid'} | Out-Null;
        throw 'test-must-not-pass'
      } catch { Write-HarnessResult -ErrorText $_.Exception.Message; exit 1 }
    """)
    assert result.returncode == 1
    assert "test-log-invalid" in json.loads(result.stdout)["error"]
    assert _verification(tmp_path)["status"] == "FAILED"


def test_initial_status_write_failure_is_logged_and_cannot_launch(tmp_path):
    (tmp_path / "visible result.json.verification.json").mkdir()
    result = _invoke(tmp_path, """
      try {
        Initialize-VisibleDesktopSmoke -Path $VisiblePath | Out-Null;
        throw 'test-must-not-pass'
      } catch { Write-HarnessResult -ErrorText $_.Exception.Message; exit 1 }
    """)
    assert result.returncode == 1
    assert json.loads(result.stdout)["launches"] == []
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith('{"schema"')]
    assert any(item["event"] == "visible_smoke_record_failed" for item in records)


@pytest.mark.parametrize("allowed", [False, True])
def test_final_delivery_forwards_permission_only_when_explicit(tmp_path, allowed):
    final_script = ROOT / "scripts/final-delivery-check.ps1"
    result = _invoke(tmp_path, f"""
      $Tokens=$null; $ParseErrors=$null;
      $Ast=[System.Management.Automation.Language.Parser]::ParseFile({_quote(final_script)},[ref]$Tokens,[ref]$ParseErrors);
      if ($ParseErrors.Count) {{ throw $ParseErrors[0] }};
      $Permission=$Ast.ParamBlock.Parameters | Where-Object {{$_.Name.VariablePath.UserPath -eq 'AllowVisibleWindow'}};
      if (!$Permission -or $null -ne $Permission.DefaultValue) {{ throw 'permission-must-be-explicit-switch' }};
      $Forward=$Ast.EndBlock.Statements | Where-Object {{$_ -is [System.Management.Automation.Language.IfStatementAst] -and $_.Extent.Text.StartsWith('if ($AllowVisibleWindow)')}};
      if (@($Forward).Count -ne 1) {{ throw 'permission-forwarding-must-be-unique' }};
      $AllowVisibleWindow=${str(allowed).lower()}; $packagedDesktopSmokeArgs=@('base');
      . ([scriptblock]::Create($Forward.Extent.Text));
      ConvertTo-Json -InputObject @($packagedDesktopSmokeArgs) -Compress
    """)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == (["base", "-AllowVisibleWindow"] if allowed else ["base"])


def test_final_delivery_windows_powershell_help_parses_without_launch(tmp_path):
    result = subprocess.run(
        [SHELL, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts/final-delivery-check.ps1"), "-Help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "-AllowVisibleWindow" in result.stdout
    assert "PENDING_PERMISSION" in result.stdout


def test_default_verifier_finishes_hidden_capture_and_portable_then_exits_pending(tmp_path):
    verifier = ROOT / "scripts/verify-desktop-package.ps1"
    result = _invoke(tmp_path, f"""
      $Source=[System.IO.File]::ReadAllText({_quote(verifier)});
      $Tail=$Source.Substring($Source.IndexOf('Assert-PackagedRuntimeClean -ExePath $ExePath'));
      function Assert-PackagedRuntimeClean {{}}; function Assert-PackagedBackendResourceStatus {{}};
      function Assert-CredentialSmoke {{}}; function Assert-DesktopSmokeLog {{}};
      function Assert-PortableTempSpace {{}}; function Get-DesktopSmokeLog {{ return 'test.log' }};
      function Wait-ForFile {{ return $true }};
      $WaitSeconds=1; $AllowVisibleWindow=$false; $CheckPortable=$true;
      $CapturePath=$ExePath; $PortableExePath=$ExePath; $PortableCapturePath=$ExePath;
      $CredentialSmokePath=$ExePath; $VisibleSmokePath=$VisiblePath;
      $SmokeUserDataDir=$UserDataDir; $VisibleSmokeUserDataDir=$UserDataDir; $PortableSmokeUserDataDir=$UserDataDir;
      [System.IO.File]::WriteAllText($ExePath,'test-only');
      try {{ . ([scriptblock]::Create($Tail)) }} finally {{
        Write-Host ('HARNESS:'+((@($script:Launches)) | ConvertTo-Json -Depth 5 -Compress))
      }}
    """)
    assert result.returncode == 3, result.stderr
    evidence = next(line.removeprefix("HARNESS:") for line in result.stdout.splitlines() if line.startswith("HARNESS:"))
    launches = json.loads(evidence)
    assert len(launches) == 2
    assert all(item["windowStyle"] == "Hidden" for item in launches)
    assert all("qa-visible-smoke" not in " ".join(item["arguments"]) for item in launches)
    assert "Packaged smoke passed." in result.stdout
    assert "Portable smoke passed." in result.stdout
    assert "PENDING_PERMISSION" in result.stderr
    assert _verification(tmp_path)["ok"] is False
