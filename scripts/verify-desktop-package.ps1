param(
  [int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$ExePath = Join-Path $RepoRoot 'outputs\desktop-build\win-unpacked\DXM Agent Console.exe'
$PortableExePath = Join-Path $RepoRoot 'outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe'
$LogPath = Join-Path $env:APPDATA 'DXM Agent Console\data\desktop-main.log'
$LegacyLogPath = Join-Path $env:APPDATA 'dxm-agent-desktop\data\desktop-main.log'
$CapturePath = Join-Path $env:TEMP 'dxm-agent-console-packaged-smoke.png'

Write-Host 'DXM Agent Console packaged smoke'
Write-Host "Exe: $ExePath"
Write-Host "Portable exe: $PortableExePath"

if (!(Test-Path $ExePath)) {
  throw "Packaged exe is missing: $ExePath"
}
if (!(Test-Path $PortableExePath)) {
  throw "Portable exe is missing: $PortableExePath"
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

$LogCandidates = @($LogPath, $LegacyLogPath)
$ExistingLog = $LogCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$ExistingLog) {
  throw "desktop-main.log was not created. Checked: $($LogCandidates -join ', ')"
}

$LogText = Get-Content -LiteralPath $ExistingLog -Raw -Encoding UTF8
if ($LogText -notmatch 'Starting backend') {
  throw "Packaged smoke failed: desktop-main.log does not contain Starting backend. Log: $ExistingLog"
}
$BundledPythonRelative = 'resources\app\backend\.venv\Scripts\python.exe'
$BundledPythonPath = Join-Path (Split-Path $ExePath) $BundledPythonRelative
if ($LogText -notmatch [regex]::Escape($BundledPythonPath)) {
  throw "Packaged backend did not start with bundled Python: $BundledPythonPath. Log: $ExistingLog"
}
if ($LogText -notmatch 'Loaded frontend') {
  throw "Packaged smoke failed: desktop-main.log does not contain Loaded frontend. Log: $ExistingLog"
}

try {
  if (!$Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
  }
} catch {}

Get-Process | Where-Object { $_.Path -like '*desktop-build*DXM Agent Console.exe' } | ForEach-Object {
  try {
    taskkill /PID $_.Id /T /F | Out-Null
  } catch {}
}

Write-Host "Packaged smoke passed. Log: $ExistingLog"
Write-Host "QA capture: $CapturePath"
