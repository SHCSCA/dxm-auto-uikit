# G4 zero-write evidence (read + local plan preview/freeze only; never DXM save/publish)
#
# Usage:
#   cd D:\Desktop\py\dxm-auto-uikit
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\g4-zero-write-after-login.ps1
#
# Optional (only if you want the script to pre-fill the official login form; prefer typing in the browser):
#   -Username "your_account" -Password "your_password"
#
# Prerequisites:
#   1) scripts\start-mvp.bat is running (8000 + 5173)
#   2) You finish login in the *visible Playwright Chrome* until URL is https://www.dianxiaomi.com/web/home
#
# Note: live-status "logged_in=true" is NOT enough. draft-reader needs the Playwright page on dianxiaomi.com.

[CmdletBinding()]
param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$Username = "",
  [string]$Password = "",
  [int]$MaxLoginAttempts = 8
)

$ErrorActionPreference = "Stop"
try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$evidenceDir = Join-Path $PSScriptRoot "..\data\g4-zero-write"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $evidenceDir "g4-report-$stamp.json"

function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host ">>> $msg" -ForegroundColor Cyan
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
  Write-Step "打开真实可见浏览器并进入店小秘（login/start）"
  # Empty strings are allowed by API; page open still happens. Prefer typing password in the browser.
  $body = @{ username = $User; password = $Pass }
  try {
    $start = Invoke-Json -Method POST -Path "/api/dxm/login/start" -Body $body -TimeoutSec 120
  } catch {
    Write-Host "login/start 调用异常（可能仍打开了窗口）: $($_.Exception.Message)" -ForegroundColor Yellow
    return $null
  }
  Write-Host ("stage={0} page_url={1} browser_visible={2}" -f $start.stage, $start.page_url, $start.browser_visible)
  if ($start.message) { Write-Host ("message={0}" -f $start.message) }
  if ($start.next_action) { Write-Host ("next={0}" -f $start.next_action) }
  return $start
}

function Navigate-Home {
  Write-Step "导航到店小秘首页 /web/home"
  try {
    $n = Invoke-Json -Method POST -Path "/api/dxm/navigate" -Body @{ target = "home" } -TimeoutSec 120
    Write-Host ("nav ok={0} url={1}" -f $n.ok, $n.page_url)
    return $n
  } catch {
    Write-Host "navigate 失败: $($_.Exception.Message)" -ForegroundColor Yellow
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
    return $null
  }
}

function Continue-Login {
  Write-Step "检测登录态 login/continue"
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
Write-Host " G4 真机零写（只读 + 本地方案 preview/freeze）" -ForegroundColor Green
Write-Host " 禁止：店小秘保存 / 发布 / 提交 Cookie 到 Git" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if (-not (Test-BackendHealth)) {
  throw "后端未就绪: $BaseUrl/health 。请先运行 scripts\start-mvp.bat"
}
Write-Host "backend health OK"

$live = Get-LiveStatusSafe
if ($live) {
  Write-Host ("live-status logged_in={0} url={1}" -f $live.logged_in, $live.final_url) -ForegroundColor DarkGray
  Write-Host "说明: live-status 用 Cookie 探针，不能单独当作 Playwright 会话已就绪。" -ForegroundColor DarkGray
}

# 1) Ensure Playwright browser is open on DXM
Open-LoginBrowser -User $Username -Pass $Password | Out-Null
Navigate-Home | Out-Null

Write-Host ""
Write-Host "请在「真实可见的 Playwright Chrome」窗口中完成登录：" -ForegroundColor Yellow
Write-Host "  1. 地址栏应是 https://www.dianxiaomi.com/web/home （不是 about:blank）" -ForegroundColor Yellow
Write-Host "  2. 页面应是店小秘后台首页（不要停在欢迎登录页）" -ForegroundColor Yellow
Write-Host "  3. 若只有 Cookie 探针显示已登录但窗口是空白，请在窗口内手动打开店小秘并登录" -ForegroundColor Yellow
Write-Host "  4. 也可在 http://127.0.0.1:5173 使用「连接店小秘」完成同一套可见浏览器登录" -ForegroundColor Yellow
Write-Host ""

$loginOk = $false
$login = $null
$shops = $null
for ($i = 1; $i -le $MaxLoginAttempts; $i++) {
  Write-Host ("---- 登录检测轮次 {0}/{1} ----" -f $i, $MaxLoginAttempts) -ForegroundColor Magenta
  if ($i -gt 1) {
    $null = Read-Host "在可见浏览器完成登录后，按 Enter 继续检测"
  }

  Navigate-Home | Out-Null
  $login = Continue-Login
  if ($login.ok -eq $true) {
    Write-Host "login/continue 成功" -ForegroundColor Green
    $loginOk = $true
  } else {
    Write-Host "login/continue 仍失败（常见原因：页面还在 about:blank，或未完成验证码）" -ForegroundColor Yellow
  }

  $shopTry = Try-Shops
  if ($shopTry.ok) {
    $shops = $shopTry.shops
    if ($shops.source -eq "api" -and $shops.session_bound) {
      Write-Host "draft-reader/shops 成功" -ForegroundColor Green
      $loginOk = $true
      break
    }
    Write-Host ("shops 回包不可用 source={0} bound={1}" -f $shops.source, $shops.session_bound) -ForegroundColor Yellow
  } else {
    $code = $null
    if ($shopTry.detail -and $shopTry.detail.detail) { $code = $shopTry.detail.detail.reason_code }
    Write-Host ("shops 失败: {0} reason={1}" -f $shopTry.error, $code) -ForegroundColor Yellow
    if ($code -eq "BROWSER_SESSION_UNAVAILABLE" -or $code -eq "DXM_PAGE_REQUIRED") {
      Write-Host "  → Playwright 会话未挂到店小秘站点。请先 login/start 打开窗口并登录，不要只依赖 live-status。" -ForegroundColor Yellow
      if ($i -eq 1) { Open-LoginBrowser -User $Username -Pass $Password | Out-Null }
    }
  }
}

if (-not $shops -or $shops.source -ne "api" -or -not $shops.session_bound) {
  $hint = @(
    "未能建立可用的 Playwright 会话，无法继续 G4。",
    "请按顺序：",
    "  1) 确认 start-mvp 运行中",
    "  2) 重新运行本脚本",
    "  3) 在弹出的真实 Chrome 中登录到 /web/home",
    "  4) 回到终端按 Enter 再检测",
    "不要依赖 live-status 的 logged_in=true（那是 Cookie 探针，不是 draft-reader 会话）。"
  ) -join [Environment]::NewLine
  throw $hint
}

$shopId = [string]$shops.shops[0].id
$sessionRef = [string]$shops.session_ref
Write-Host ("shops n={0} shopId={1} session_ref_len={2}" -f @($shops.shops).Count, $shopId, $sessionRef.Length)

Write-Step "读取采集箱草稿 pageList(draft)"
$products = Invoke-Json -Method GET -Path "/api/dxm/draft-reader/products?shop_id=$shopId&page_no=1&page_size=20" -TimeoutSec 180
$items = @($products.items)
if ($items.Count -lt 3) { throw "need >=3 draft items, got $($items.Count)" }
$pick = $items | Select-Object -First 3
$productIds = @($pick | ForEach-Object { [string]$_.id })
$categoryIds = @($pick | ForEach-Object { [string]$_.category_id } | Where-Object { $_ } | Select-Object -Unique)
if (@($categoryIds).Count -lt 1) { throw "picked products missing category_id" }
Write-Host ("picked products={0} categories={1}" -f $productIds.Count, ($categoryIds -join ","))

Write-Step "准备本地方案 local_plan_template"
$plansRaw = Invoke-Json -Method GET -Path "/api/local-plan-templates" -TimeoutSec 60
$plans = @($plansRaw)
if ($plans.Count -eq 1 -and $plans[0].plans) { $plans = @($plans[0].plans) }
$plan = $plans | Where-Object {
  $_.is_active -ne $false -and [string]$_.shop_id -eq $shopId -and [string]$_.path -eq "A"
} | Select-Object -First 1

if (-not $plan) {
  Write-Host "创建最小 Path A 本地方案（G4 验证用）..."
  $planBody = @{
    name                 = "G4_ZERO_WRITE_$stamp"
    version              = "1"
    shop_id              = $shopId
    category_ids         = @($categoryIds)
    path                 = "A"
    fixed_values         = @{}
    fill_rules           = @{}
    dxm_template_refs    = @()
    field_mappings       = @{}
    validation_policy    = @{ english_natural_language = $true }
    exception_policy     = @{ on_unknown = "stop" }
    provenance           = "G4_ZERO_WRITE_DO_NOT_EXECUTE"
  }
  $plan = Invoke-Json -Method POST -Path "/api/local-plan-templates" -Body $planBody -TimeoutSec 60
}
$planId = [int]$plan.id
Write-Host "plan_id=$planId"

$snapReq = @{
  local_plan_template_id = $planId
  shop_id                = $shopId
  session_ref            = $sessionRef
  product_ids            = $productIds
  idempotency_key        = "g4-zero-write-$stamp"
}

Write-Step "preview plan-snapshot（只读编译，不写 DXM）"
try {
  $preview = Invoke-Json -Method POST -Path "/api/plan-snapshots/preview" -Body $snapReq -TimeoutSec 300
} catch {
  $msg = $_.Exception.Message
  if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
  throw "preview failed: $msg"
}
$previewHash = [string]$preview.snapshot_hash
$itemCount = @($preview.item_snapshots).Count
Write-Host ("preview hash_len={0} item_snapshots={1}" -f $previewHash.Length, $itemCount)

Write-Step "freeze plan-snapshot（本地冻结，不保存/不发布店小秘商品）"
$freezeBody = @{
  local_plan_template_id = $planId
  shop_id                = $shopId
  session_ref            = $sessionRef
  product_ids            = $productIds
  expected_snapshot_hash = $previewHash
  idempotency_key        = "g4-zero-write-$stamp"
}
try {
  $frozen = Invoke-Json -Method POST -Path "/api/plan-snapshots" -Body $freezeBody -TimeoutSec 300
} catch {
  $msg = $_.Exception.Message
  if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
  throw "freeze failed: $msg"
}
Write-Host ("freeze id={0} hash_len={1}" -f $frozen.id, ([string]$frozen.snapshot_hash).Length)

$reportObj = [ordered]@{
  stamp                      = $stamp
  zero_write                 = $true
  login_stage                = $(if ($login) { $login.stage } else { "shops_only" })
  page_url                   = $(if ($login) { $login.page_url } else { $null })
  shops_source               = $shops.source
  shops_count                = @($shops.shops).Count
  session_ref_len            = $sessionRef.Length
  shop_id                    = $shopId
  product_ids_count          = $productIds.Count
  category_ids               = @($categoryIds)
  plan_id                    = $planId
  preview_item_snapshots     = $itemCount
  preview_snapshot_hash_len  = $previewHash.Length
  freeze_id                  = $frozen.id
  freeze_snapshot_hash_len   = ([string]$frozen.snapshot_hash).Length
  publish_attempted          = $false
  save_attempted             = $false
}
$reportObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " G4 零写完成（未调用店小秘保存/发布）" -ForegroundColor Green
Write-Host " 报告: $report" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "请勿把 data/sessions、Cookie 或含密码日志提交到 Git。" -ForegroundColor Yellow
