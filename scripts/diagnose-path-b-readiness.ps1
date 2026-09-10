# Read-only diagnostic wrapper. Never launches the app or grants SAVE authority.
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$DataDir = "",
    [ValidateRange(1, 7200)][int]$L2MaxAgeSeconds = 7200,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $repoRoot "app\backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
$diagnosticArgs = @(
    "-B", "-X", "utf8", (Join-Path $PSScriptRoot "path_b_readiness.py"),
    "--base-url", $BaseUrl, "--max-age-seconds", "$L2MaxAgeSeconds"
)
if ($DataDir) { $diagnosticArgs += @("--data-dir", $DataDir) }
if ($Json) { $diagnosticArgs += "--json" }
$previousConsoleEncoding = [Console]::OutputEncoding
$previousOutputEncoding = $OutputEncoding
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
    & $pythonPath @diagnosticArgs
    $diagnosticExitCode = $LASTEXITCODE
} finally {
    [Console]::OutputEncoding = $previousConsoleEncoding
    $OutputEncoding = $previousOutputEncoding
}
exit $diagnosticExitCode
