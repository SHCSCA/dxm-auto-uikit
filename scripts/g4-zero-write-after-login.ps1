# G4 zero-write evidence after visible browser is logged into dianxiaomi.com
# Usage (PowerShell):  .\scripts\g4-zero-write-after-login.ps1
# Prerequisites: start-mvp running; user completed login in visible Chrome / 连接店小秘 UI.
# Safety: only reads + local plan preview/freeze; never save/publish on DXM.

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000"
$evidenceDir = Join-Path $PSScriptRoot "..\data\g4-zero-write"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $evidenceDir "g4-report-$stamp.json"

function Invoke-Json {
  param([string]$Method, [string]$Path, [object]$Body = $null, [int]$TimeoutSec = 180)
  $uri = "$base$Path"
  if ($null -eq $Body) {
    return Invoke-RestMethod -Uri $uri -Method $Method -TimeoutSec $TimeoutSec
  }
  $json = $Body | ConvertTo-Json -Depth 20 -Compress
  return Invoke-RestMethod -Uri $uri -Method $Method -ContentType "application/json" -Body $json -TimeoutSec $TimeoutSec
}

Write-Host "== G4 zero-write start =="
$login = Invoke-Json -Method POST -Path "/api/dxm/login/continue" -Body @{ confirm = $true } -TimeoutSec 240
if ($login.ok -ne $true) {
  throw "login/continue not ok: stage=$($login.stage) message=$($login.message)"
}
Write-Host "login ok stage=$($login.stage) url=$($login.page_url)"

$shops = Invoke-Json -Method GET -Path "/api/dxm/draft-reader/shops" -TimeoutSec 120
if ($shops.source -ne "api" -or -not $shops.session_bound) {
  throw "shops not authoritative: source=$($shops.source) bound=$($shops.session_bound)"
}
$shopId = [string]$shops.shops[0].id
$sessionRef = [string]$shops.session_ref
Write-Host "shops n=$(@($shops.shops).Count) shopId=$shopId session_ref_len=$($sessionRef.Length)"

$products = Invoke-Json -Method GET -Path "/api/dxm/draft-reader/products?shop_id=$shopId&page_no=1&page_size=20" -TimeoutSec 180
$items = @($products.items)
if ($items.Count -lt 3) { throw "need >=3 draft items, got $($items.Count)" }
$pick = $items | Select-Object -First 3
$productIds = @($pick | ForEach-Object { [string]$_.id })
$categoryIds = @($pick | ForEach-Object { [string]$_.category_id } | Select-Object -Unique)
Write-Host "picked products=$($productIds.Count) categories=$($categoryIds -join ',')"

# Prefer existing active local plan matching shop; else create a minimal Path A plan
$plans = @(Invoke-Json -Method GET -Path "/api/local-plan-templates" -TimeoutSec 60)
$plan = $plans | Where-Object {
  $_.is_active -ne $false -and [string]$_.shop_id -eq $shopId -and $_.path -eq "A"
} | Select-Object -First 1

if (-not $plan) {
  Write-Host "creating minimal local plan for G4..."
  $planBody = @{
    name = "G4_ZERO_WRITE_$stamp"
    version = "1"
    shop_id = $shopId
    category_ids = @($categoryIds)
    path = "A"
    fixed_values = @{}
    fill_rules = @{}
    dxm_template_refs = @()
    field_mappings = @{}
    validation_policy = @{ english_natural_language = $true }
    exception_policy = @{ on_unknown = "stop" }
    provenance = "G4_ZERO_WRITE_DO_NOT_EXECUTE"
  }
  $plan = Invoke-Json -Method POST -Path "/api/local-plan-templates" -Body $planBody -TimeoutSec 60
}
$planId = [int]$plan.id
Write-Host "plan_id=$planId"

$snapReq = @{
  local_plan_template_id = $planId
  shop_id = $shopId
  session_ref = $sessionRef
  product_ids = $productIds
  idempotency_key = "g4-zero-write-$stamp"
}

Write-Host "preview..."
$preview = Invoke-Json -Method POST -Path "/api/plan-snapshots/preview" -Body $snapReq -TimeoutSec 300
$previewHash = [string]$preview.snapshot_hash
$itemCount = @($preview.item_snapshots).Count
Write-Host "preview hash_len=$($previewHash.Length) items=$itemCount"

Write-Host "freeze..."
$freezeBody = $snapReq.Clone()
$freezeBody["expected_snapshot_hash"] = $previewHash
$frozen = Invoke-Json -Method POST -Path "/api/plan-snapshots" -Body $freezeBody -TimeoutSec 300
Write-Host "freeze id=$($frozen.id) hash_len=$(@($frozen.snapshot_hash).ToString().Length)"

$reportObj = [ordered]@{
  stamp = $stamp
  zero_write = $true
  login_stage = $login.stage
  page_url = $login.page_url
  shops_source = $shops.source
  shops_count = @($shops.shops).Count
  session_ref_len = $sessionRef.Length
  shop_id = $shopId
  product_ids_count = $productIds.Count
  category_ids = $categoryIds
  plan_id = $planId
  preview_item_snapshots = $itemCount
  preview_snapshot_hash_len = $previewHash.Length
  freeze_id = $frozen.id
  freeze_snapshot_hash_len = @($frozen.snapshot_hash).ToString().Length
  publish_attempted = $false
  save_attempted = $false
}
$reportObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8
Write-Host "REPORT=$report"
Write-Host "== G4 zero-write DONE (no DXM save/publish) =="
