## Closed-loop Path B replay driver: real FastAPI + Dang Kang fixtures + website replay
##
## This script is the production-driver entry for the isolated Path B closed loop.
## It does NOT touch the user's real data/, sessions, cookies, draft box or any
## non-Dang Kang shop. The system scripts (FastAPI, snapshot compiler,
## V1TaskRunner, BrowserAgent pipeline, publish guard) stay production code.
## Only the dianxiaomi.com adapter is swapped for the website replay.
##
## Prerequisite:
##   - scripts/start-mvp.bat --check  (already passing)
##   - The user's data/, cookies, sessions are not modified by this script.
##
## Output:
##   - data/closed-loop-data/  (isolated SQLite + evidence dirs)
##   - TestClient-based runner walks the pre-save Path B actions through
##     real FastAPI and V1TaskRunner, asserts the closed-loop envelopes
##     contain the four pre-save mandatory capability receipts and stops at
##     the SAVE_ONLY mutation dispatch boundary.
##
## The test deliberately stops at SAVE_ONLY because the mutation scope/approval
## ledger is a real security boundary that must not be silently bypassed for
## an isolated closed-loop run.

[CmdletBinding()]
param(
    [string]$DataDir = (Join-Path $env:TEMP ("dxm-closed-loop-" + [guid]::NewGuid().ToString("N")))
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = $null
if ($PSCommandPath) {
    $scriptDir = Split-Path -Parent $PSCommandPath
} elseif ($MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $scriptDir = (Get-Location).Path
}
$RepoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$PythonExe = Join-Path $RepoRoot "app\backend\.venv\Scripts\python.exe"
$TestPath = Join-Path $RepoRoot "app\backend\tests\test_path_b_closed_loop.py"
$backendRoot = Join-Path $RepoRoot "app\backend"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found at $PythonExe"
    exit 2
}

if (-not (Test-Path $TestPath)) {
    Write-Error "Test file not found at $TestPath"
    exit 2
}

Write-Host "[closed-loop] repo root         : $RepoRoot"
Write-Host "[closed-loop] backend root     : $backendRoot"
Write-Host "[closed-loop] isolated data dir: $DataDir"
Write-Host "[closed-loop] python           : $PythonExe"

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$env:DXM_DATA_DIR = $DataDir
$env:DXM_PATH_B_CLOSED_LOOP = "1"

Push-Location $backendRoot
try {
    & $PythonExe -m pytest -q -ra --tb=short "tests\test_path_b_closed_loop.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Closed-loop Path B replay failed. See pytest output above."
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

Write-Host "[closed-loop] Path B pre-save closed loop PASSED"
Write-Host "[closed-loop] Isolated data dir kept for inspection: $DataDir"
Write-Host "[closed-loop] Note: real mutation scope/approval is intentionally NOT bypassed"
Write-Host "[closed-loop] Next step: provide real scope/approval or run shadow Discovery"
