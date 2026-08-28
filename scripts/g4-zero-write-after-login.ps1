# G4 zero-write evidence (read + local plan preview/freeze only; never DXM save/publish)
#
# Usage (from repo root recommended):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\g4-zero-write-after-login.ps1
#
# Optional prefill (prefer typing password in the visible browser):
#   -Username "account" -Password "password"
#
# Prerequisites:
#   1) start-mvp.bat running (ports 8000 + 5173)
#   2) Finish login in the VISIBLE Playwright Chrome until URL is:
#        https://www.dianxiaomi.com/web/home
#
# Note: live-status logged_in=true is NOT enough for draft-reader.

[CmdletBinding()]
param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$Username = "",
  [string]$Password = "",
  [int]$MaxLoginAttempts = 8
)

$ErrorActionPreference = "Stop"

$evidenceDir = Join-Path $PSScriptRoot "..\data\g4-zero-write"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $evidenceDir ("g4-report-{0}.json" -f $stamp)

function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host (">>> {0}" -f $msg) -ForegroundColor Cyan
}

function Invoke-Json {
  param(
    [string]$Method,
    [string]$Path,
    [object]$Body = $null,
    [int]$TimeoutSec = 180
  )
  $uri = "$BaseUrl$Path"
  if ($null -eq $Body) {
    return Invoke-RestMethod -Uri $uri -Method $Method -TimeoutSec $TimeoutSec
  }
  $json = $Body | ConvertTo-Json -Depth 30 -Compress
  return Invoke-RestMethod -Uri $uri -Method $Method -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec $TimeoutSec
}

function Test-BackendHealth {
  try {
    Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 5 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Get-LiveStatusSafe {
  try {
    return Invoke-Json -Method GET -Path "/api/dxm/live-status" -TimeoutSec 30
  } catch {
    return $null
  }
}

function Open-LoginBrowser {
  param([string]$User, [string]$Pass)
  Write-Step "Open visible browser via login/start"
  $body = @{ username = $User; password = $Pass }
  try {
    $start = Invoke-Json -Method POST -Path "/api/dxm/login/start" -Body $body -TimeoutSec 120
  } catch {
    Write-Host ("login/start error (window may still open): {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    return $null
  }
  Write-Host ("stage={0} page_url={1} browser_visible={2}" -f $start.stage, $start.page_url, $start.browser_visible)
  if ($start.message) { Write-Host ("message={0}" -f $start.message) }
  if ($start.next_action) { Write-Host ("next={0}" -f $start.next_action) }
  return $start
}

function Navigate-Home {
  Write-Step "Navigate to DXM home /web/home"
  try {
    $n = Invoke-Json -Method POST -Path "/api/dxm/navigate" -Body @{ target = "home" } -TimeoutSec 120
    Write-Host ("nav ok={0} url={1}" -f $n.ok, $n.page_url)
    return $n
  } catch {
    Write-Host ("navigate failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
    return $null
  }
}

function Continue-Login {
  Write-Step "Detect login via login/continue"
  $c = Invoke-Json -Method POST -Path "/api/dxm/login/continue" -Body @{ confirm = $true } -TimeoutSec 180
  Write-Host ("ok={0} stage={1} page_url={2}" -f $c.ok, $c.stage, $c.page_url)
  if ($c.message) { Write-Host ("message={0}" -f $c.message) }
  if ($c.next_action) { Write-Host ("next={0}" -f $c.next_action) }
  return $c
}

function Try-Shops {
  try {
    $shops = Invoke-Json -Method GET -Path "/api/dxm/draft-reader/shops" -TimeoutSec 90
    return @{ ok = $true; shops = $shops }
  } catch {
    $detail = $null
    if ($_.ErrorDetails.Message) {
      try { $detail = $_.ErrorDetails.Message | ConvertFrom-Json } catch { $detail = $_.ErrorDetails.Message }
    }
    return @{ ok = $false; error = $_.Exception.Message; detail = $detail }
  }
}

Write-Host "========================================" -ForegroundColor Green
Write-Host " G4 zero-write (read + local plan freeze)" -ForegroundColor Green
Write-Host " Forbidden: DXM save / publish / commit cookies" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if (-not (Test-BackendHealth)) {
  throw "Backend not ready at $BaseUrl/health. Run scripts\start-mvp.bat first."
}
Write-Host "backend health OK"

$live = Get-LiveStatusSafe
if ($live) {
  Write-Host ("live-status logged_in={0} url={1}" -f $live.logged_in, $live.final_url) -ForegroundColor DarkGray
  Write-Host "Note: live-status is a cookie probe; draft-reader needs Playwright page on dianxiaomi.com." -ForegroundColor DarkGray
}

Open-LoginBrowser -User $Username -Pass $Password | Out-Null
Navigate-Home | Out-Null

Write-Host ""
Write-Host "Complete login in the VISIBLE Playwright Chrome window:" -ForegroundColor Yellow
Write-Host "  1) URL must be https://www.dianxiaomi.com/web/home (not about:blank)" -ForegroundColor Yellow
Write-Host "  2) Page must be DXM backend home (not welcome-login only)" -ForegroundColor Yellow
Write-Host "  3) You can also use http://127.0.0.1:5173 Connect DXM UI" -ForegroundColor Yellow
Write-Host ""

$login = $null
$shops = $null
for ($i = 1; $i -le $MaxLoginAttempts; $i++) {
  Write-Host ("---- login attempt {0}/{1} ----" -f $i, $MaxLoginAttempts) -ForegroundColor Magenta
  if ($i -gt 1) {
    $null = Read-Host "After login is done in the visible browser, press Enter"
  }

  Navigate-Home | Out-Null
  $login = Continue-Login
  if ($login.ok -eq $true) {
    Write-Host "login/continue OK" -ForegroundColor Green
  } else {
    Write-Host "login/continue still failed (often about:blank or captcha not done)" -ForegroundColor Yellow
  }

  $shopTry = Try-Shops
  if ($shopTry.ok) {
    $shops = $shopTry.shops
    if ($shops.source -eq "api" -and $shops.session_bound) {
      Write-Host "draft-reader/shops OK" -ForegroundColor Green
      break
    }
    Write-Host ("shops payload not authoritative source={0} bound={1}" -f $shops.source, $shops.session_bound) -ForegroundColor Yellow
  } else {
    $code = $null
    if ($shopTry.detail -and $shopTry.detail.detail) { $code = $shopTry.detail.detail.reason_code }
    Write-Host ("shops failed: {0} reason={1}" -f $shopTry.error, $code) -ForegroundColor Yellow
    if ($code -eq "BROWSER_SESSION_UNAVAILABLE" -or $code -eq "DXM_PAGE_REQUIRED") {
      Write-Host "  -> Playwright session is not on DXM. Open login/start window and login there." -ForegroundColor Yellow
      if ($i -eq 1) { Open-LoginBrowser -User $Username -Pass $Password | Out-Null }
    }
  }
}

if (-not $shops -or $shops.source -ne "api" -or -not $shops.session_bound) {
  $hint = @(
    "Could not establish a usable Playwright session for G4.",
    "Do this in order:",
    "  1) Ensure start-mvp is running",
    "  2) Re-run this script",
    "  3) In the visible Chrome, login until /web/home",
    "  4) Press Enter in the terminal to re-check",
    "Do NOT rely on live-status logged_in=true (cookie probe only)."
  ) -join [Environment]::NewLine
  throw $hint
}

$shopId = [string]$shops.shops[0].id
$sessionRef = [string]$shops.session_ref
Write-Host ("shops n={0} shopId={1} session_ref_len={2}" -f @($shops.shops).Count, $shopId, $sessionRef.Length)

Write-Step "Read draft products pageList(draft)"
$products = Invoke-Json -Method GET -Path ("/api/dxm/draft-reader/products?shop_id={0}&page_no=1&page_size=20" -f $shopId) -TimeoutSec 180
$items = @($products.items)
if ($items.Count -lt 3) { throw ("need >=3 draft items, got {0}" -f $items.Count) }
$pick = $items | Select-Object -First 3
$productIds = @($pick | ForEach-Object { [string]$_.id })
$categoryIds = @($pick | ForEach-Object { [string]$_.category_id } | Where-Object { $_ } | Select-Object -Unique)
if (@($categoryIds).Count -lt 1) { throw "picked products missing category_id" }
Write-Host ("picked products={0} categories={1}" -f $productIds.Count, ($categoryIds -join ","))

Write-Step "Prepare local_plan_template"
$plansRaw = Invoke-Json -Method GET -Path "/api/local-plan-templates" -TimeoutSec 60
$plans = @($plansRaw)
if ($plans.Count -eq 1 -and $null -ne $plans[0].plans) { $plans = @($plans[0].plans) }
$plan = $plans | Where-Object {
  $_.is_active -ne $false -and [string]$_.shop_id -eq $shopId -and [string]$_.path -eq "A"
} | Select-Object -First 1

if (-not $plan) {
  Write-Host "Creating minimal Path A local plan for G4..."
  $planBody = @{
    name              = ("G4_ZERO_WRITE_{0}" -f $stamp)
    version           = "1"
    shop_id           = $shopId
    category_ids      = @($categoryIds)
    path              = "A"
    fixed_values      = @{}
    fill_rules        = @{}
    dxm_template_refs = @()
    field_mappings    = @{}
    validation_policy = @{ english_natural_language = $true }
    exception_policy  = @{ on_unknown = "stop" }
    provenance        = "G4_ZERO_WRITE_DO_NOT_EXECUTE"
  }
  $plan = Invoke-Json -Method POST -Path "/api/local-plan-templates" -Body $planBody -TimeoutSec 60
}
$planId = [int]$plan.id
Write-Host ("plan_id={0}" -f $planId)

$snapReq = @{
  local_plan_template_id = $planId
  shop_id                = $shopId
  session_ref            = $sessionRef
  product_ids            = $productIds
  idempotency_key        = ("g4-zero-write-{0}" -f $stamp)
}

Write-Step "preview plan-snapshot (local compile, no DXM write)"
try {
  $preview = Invoke-Json -Method POST -Path "/api/plan-snapshots/preview" -Body $snapReq -TimeoutSec 300
} catch {
  $msg = $_.Exception.Message
  if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
  throw ("preview failed: {0}" -f $msg)
}
$previewHash = [string]$preview.snapshot_hash
$itemCount = @($preview.item_snapshots).Count
Write-Host ("preview hash_len={0} item_snapshots={1}" -f $previewHash.Length, $itemCount)

Write-Step "freeze plan-snapshot (local freeze only; no DXM save/publish)"
$freezeBody = @{
  local_plan_template_id = $planId
  shop_id                = $shopId
  session_ref            = $sessionRef
  product_ids            = $productIds
  expected_snapshot_hash = $previewHash
  idempotency_key        = ("g4-zero-write-{0}" -f $stamp)
}
try {
  $frozen = Invoke-Json -Method POST -Path "/api/plan-snapshots" -Body $freezeBody -TimeoutSec 300
} catch {
  $msg = $_.Exception.Message
  if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
  throw ("freeze failed: {0}" -f $msg)
}
Write-Host ("freeze id={0} hash_len={1}" -f $frozen.id, ([string]$frozen.snapshot_hash).Length)

$reportObj = [ordered]@{
  stamp                     = $stamp
  zero_write                = $true
  login_stage               = $(if ($login) { $login.stage } else { "shops_only" })
  page_url                  = $(if ($login) { $login.page_url } else { $null })
  shops_source              = $shops.source
  shops_count               = @($shops.shops).Count
  session_ref_len           = $sessionRef.Length
  shop_id                   = $shopId
  product_ids_count         = $productIds.Count
  category_ids              = @($categoryIds)
  plan_id                   = $planId
  preview_item_snapshots    = $itemCount
  preview_snapshot_hash_len = $previewHash.Length
  freeze_id                 = $frozen.id
  freeze_snapshot_hash_len  = ([string]$frozen.snapshot_hash).Length
  publish_attempted         = $false
  save_attempted            = $false
}
$reportObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " G4 zero-write DONE (no DXM save/publish)" -ForegroundColor Green
Write-Host (" report: {0}" -f $report) -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Do not commit data/sessions or cookies to Git." -ForegroundColor Yellow