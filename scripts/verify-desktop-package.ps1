param(
  [int]$WaitSeconds = 25
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$ExePath = Join-Path $RepoRoot 'outputs\desktop-build\win-unpacked\DXM Agent Console.exe'
$LogPath = Join-Path $env:APPDATA 'DXM Agent Console\data\desktop-main.log'
$LegacyLogPath = Join-Path $env:APPDATA 'dxm-agent-desktop\data\desktop-main.log'

Write-Host 'DXM Agent Console packaged smoke'
Write-Host "Exe: $ExePath"

if (!(Test-Path $ExePath)) {
  throw "Packaged exe is missing: $ExePath"
}

foreach ($Path in @($LogPath, $LegacyLogPath)) {
  if (Test-Path $Path) {
    Remove-Item -LiteralPath $Path -Force
  }
}

$Process = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -PassThru
Start-Sleep -Seconds $WaitSeconds

$LogCandidates = @($LogPath, $LegacyLogPath)
$ExistingLog = $LogCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$ExistingLog) {
  throw "desktop-main.log was not created. Checked: $($LogCandidates -join ', ')"
}

$LogText = Get-Content -LiteralPath $ExistingLog -Raw -Encoding UTF8
if ($LogText -notmatch 'Starting backend') {
  throw "Packaged smoke failed: desktop-main.log does not contain Starting backend. Log: $ExistingLog"
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
