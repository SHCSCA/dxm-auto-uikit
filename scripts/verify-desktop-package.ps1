param(
  [int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$ExePath = Join-Path $RepoRoot 'outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe'
$LogPath = Join-Path $env:APPDATA 'DXM Agent Console\data\desktop-main.log'
$LegacyLogPath = Join-Path $env:APPDATA 'dxm-agent-desktop\data\desktop-main.log'
$CapturePath = Join-Path $env:TEMP 'dxm-agent-console-packaged-smoke.png'

Write-Host 'DXM Agent Console packaged smoke'
Write-Host "Exe: $ExePath"

if (!(Test-Path $ExePath)) {
  throw "Packaged exe is missing: $ExePath"
}

$RequiredResources = @(
  'resources\app\backend\.venv\Scripts\python.exe',
  'resources\tools\probes\l2_readonly_probe_runner.py',
  'resources\tools\probes\l2_readonly_probe.py',
  'resources\config\l2_readonly_allowlist.json'
)
foreach ($RelativePath in $RequiredResources) {
  $ResourcePath = Join-Path (Split-Path $ExePath) $RelativePath
  if (!(Test-Path $ResourcePath)) {
    throw "Packaged resource is missing: $RelativePath"
  }
}

foreach ($Path in @($LogPath, $LegacyLogPath)) {
  if (Test-Path $Path) {
    Remove-Item -LiteralPath $Path -Force
  }
}

if (Test-Path $CapturePath) {
  Remove-Item -LiteralPath $CapturePath -Force
}

function Wait-ForFile {
  param(
    [string]$Path,
    [int]$TimeoutSeconds
  )
  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $Deadline) {
    if (Test-Path -LiteralPath $Path) {
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Get-DesktopSmokeLog {
  $LogCandidates = @($LogPath, $LegacyLogPath)
  $ExistingLog = $LogCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (!$ExistingLog) {
    throw "desktop-main.log was not created. Checked: $($LogCandidates -join ', ')"
  }
  return $ExistingLog
}

function Assert-DesktopSmokeLog {
  param(
    [string]$ExistingLog,
    [string]$ExpectedPythonRoot,
    [string]$Label
  )
  $LogText = Get-Content -LiteralPath $ExistingLog -Raw -Encoding UTF8
  if ($LogText -notmatch 'Starting backend') {
    throw "$Label failed: desktop-main.log does not contain Starting backend. Log: $ExistingLog"
  }
  $BundledPythonRelative = 'resources\app\backend\.venv\Scripts\python.exe'
  if ($ExpectedPythonRoot) {
    $BundledPythonPath = Join-Path $ExpectedPythonRoot $BundledPythonRelative
    if ($LogText -notmatch [regex]::Escape($BundledPythonPath)) {
      throw "$Label backend did not start with bundled Python: $BundledPythonPath. Log: $ExistingLog"
    }
  } elseif ($LogText -notmatch [regex]::Escape($BundledPythonRelative)) {
    throw "$Label backend did not start with bundled Python resource path: $BundledPythonRelative. Log: $ExistingLog"
  }
  if ($LogText -notmatch 'Loaded frontend') {
    throw "$Label failed: desktop-main.log does not contain Loaded frontend. Log: $ExistingLog"
  }
}

$Process = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -ArgumentList "--qa-capture=$CapturePath" -PassThru
if (!$Process.WaitForExit($WaitSeconds * 1000)) {
  try {
    Stop-Process -Id $Process.Id -Force
  } catch {}
  throw "Packaged smoke timed out after $WaitSeconds seconds"
}
if ($Process.ExitCode -ne 0) {
  throw "Packaged smoke failed: exit code $($Process.ExitCode)"
}
if (!(Test-Path $CapturePath)) {
  throw "Packaged smoke failed: QA capture was not created: $CapturePath"
}

$ExistingLog = Get-DesktopSmokeLog
Assert-DesktopSmokeLog -ExistingLog $ExistingLog -ExpectedPythonRoot (Split-Path $ExePath) -Label 'Packaged smoke'

try {
  if (!$Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
  }
} catch {}

Get-Process | Where-Object { $_.Path -like '*desktop-build*DXM-Agent-Console.exe' } | ForEach-Object {
  try {
    taskkill /PID $_.Id /T /F | Out-Null
  } catch {}
}

Write-Host "Packaged smoke passed. Log: $ExistingLog"
Write-Host "QA capture: $CapturePath"
