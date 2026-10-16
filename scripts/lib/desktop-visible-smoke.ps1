function Write-VisibleSmokeDiagnostic {
  param([string]$Event, [string]$Level, [hashtable]$Fields)
  $Record = [ordered]@{
    schema = 'dxm.log.v1'; timestamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'")
    level = $Level; component = 'desktop-visible-smoke'; event = $Event; fields = $Fields
  }
  [Console]::Error.WriteLine(($Record | ConvertTo-Json -Depth 4 -Compress))
}

function Write-VisibleSmokeVerification {
  param([string]$Path, [string]$Status, [string]$ReasonCode, [int]$ExitCode, [int]$OwnedProcessId = 0)
  $Record = [pscustomobject][ordered]@{
    schema = 'dxm.desktop_visible_smoke.v1'; checkedAt = [DateTimeOffset]::UtcNow.ToString('o')
    status = $Status; ok = ($Status -eq 'PASSED'); reasonCode = $ReasonCode
    exitCode = $ExitCode; processId = $OwnedProcessId
  }
  $VerificationPath = "$Path.verification.json"
  try {
    $ParentPath = Split-Path -Parent $VerificationPath
    if ($ParentPath) { [System.IO.Directory]::CreateDirectory($ParentPath) | Out-Null }
    [System.IO.File]::WriteAllText($VerificationPath, ($Record | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
  } catch {
    Write-VisibleSmokeDiagnostic -Event 'visible_smoke_record_failed' -Level 'ERROR' -Fields @{ exception_type = $_.Exception.GetType().Name }
    throw
  }
  return $Record
}

function Initialize-VisibleDesktopSmoke {
  param([string]$Path, [switch]$AllowVisibleWindow)
  # 独立状态文件不得覆盖 Electron 对真实可见性的观察结果。
  if (!$AllowVisibleWindow) {
    return Write-VisibleSmokeVerification -Path $Path -Status 'PENDING_PERMISSION' -ReasonCode 'VISIBLE_WINDOW_PERMISSION_REQUIRED' -ExitCode 3
  }
  return Write-VisibleSmokeVerification -Path $Path -Status 'NOT_RUN' -ReasonCode 'VISIBLE_SMOKE_NOT_STARTED' -ExitCode 3
}

function Assert-VisibleSmoke {
  param([string]$Path)
  if (!(Test-Path -LiteralPath $Path)) { throw 'VISIBLE_SMOKE_RESULT_MISSING' }
  $Result = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($Result.ok -ne $true -or $Result.windowVisible -ne $true) {
    throw 'VISIBLE_SMOKE_WINDOW_NOT_VISIBLE'
  }
  if (-not $Result.backendPort -or -not ([string]$Result.apiBase).StartsWith('http://127.0.0.1:')) {
    throw 'VISIBLE_SMOKE_RUNTIME_DETAILS_INVALID'
  }
}

function Invoke-VisibleDesktopSmoke {
  param(
    [string]$ExePath, [string]$VisibleSmokePath, [string]$UserDataDir,
    [ValidateRange(1, 3600)][int]$WaitSeconds = 25, [switch]$AllowVisibleWindow,
    [scriptblock]$VerifyRuntime = {}, [scriptblock]$VerifyLog = {}
  )
  $VisibleProcess = $null
  try {
    $Verification = Initialize-VisibleDesktopSmoke -Path $VisibleSmokePath -AllowVisibleWindow:$AllowVisibleWindow
    if (!$AllowVisibleWindow) {
      Write-VisibleSmokeDiagnostic -Event 'visible_smoke_pending_permission' -Level 'WARNING' -Fields @{ reason_code = $Verification.reasonCode }
      return $Verification
    }
    # 只允许显式授权的分支显示本次进程，结束后仅清理所持有的进程对象。
    if (Test-Path -LiteralPath $VisibleSmokePath) { Remove-Item -LiteralPath $VisibleSmokePath -Force }
    try {
      $VisibleProcess = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -ArgumentList @(('"--qa-visible-smoke={0}"' -f $VisibleSmokePath), ('"--qa-user-data-dir={0}"' -f $UserDataDir)) -WindowStyle Normal -PassThru
      if (!$VisibleProcess.WaitForExit($WaitSeconds * 1000)) { throw 'VISIBLE_SMOKE_TIMEOUT' }
      if ($VisibleProcess.ExitCode -ne 0) { throw "VISIBLE_SMOKE_PROCESS_FAILED: $($VisibleProcess.ExitCode)" }
      Assert-VisibleSmoke -Path $VisibleSmokePath
      & $VerifyLog
      & $VerifyRuntime
    } finally {
      Stop-DesktopSmokeProcess -Process $VisibleProcess -Label 'visible-smoke-complete'
    }
    return Write-VisibleSmokeVerification -Path $VisibleSmokePath -Status 'PASSED' -ReasonCode 'VISIBLE_SMOKE_VERIFIED' -ExitCode 0 -OwnedProcessId $VisibleProcess.Id
  } catch {
    $Failure = $_
    Write-VisibleSmokeDiagnostic -Event 'visible_smoke_failed' -Level 'ERROR' -Fields @{ exception_type = $Failure.Exception.GetType().Name; pid = $(if ($VisibleProcess) { $VisibleProcess.Id } else { 0 }) }
    try {
      Write-VisibleSmokeVerification -Path $VisibleSmokePath -Status 'FAILED' -ReasonCode 'VISIBLE_SMOKE_FAILED' -ExitCode 1 | Out-Null
    } catch {
      Write-VisibleSmokeDiagnostic -Event 'visible_smoke_record_failed' -Level 'ERROR' -Fields @{ exception_type = $_.Exception.GetType().Name }
    }
    throw $Failure
  }
}
