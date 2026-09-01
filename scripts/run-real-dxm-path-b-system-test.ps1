# Real DXM Path B system-flow driver.
#
# This script is intentionally fail-closed and uses public HTTP endpoints only.
# It never controls the browser, dispatches a write directly, or reads local
# persistence.  Every real phase is explicit and permanently counted in one
# global v2 attempt journal in the Git-external evidence directory.  That
# journal spans the predecessor Discovery scope and the fresh Formal scope.
#
# External input contracts:
#   Prepare: DXM_REAL_SAVE_SCOPE_FILE is a Git-external output path.
#   Execute phases: DXM_REAL_SAVE_SCOPE_FILE contains one scope object.
#   -ApprovalFile            -> one matching real_dxm_write_approval.v1 object.
#   -PrepareRequestFile      -> one hash-only prepare request containing plan
#     selection plus exact per-product SAVE1/SAVE2 fieldHashBindings.
#   -ShadowRequestFile       -> one real_dxm_path_b_shadow_request.v1 object:
#     { schemaVersion, localPlanTemplateId, shopId, sessionRef,
#       orderedProductIds[3], idempotencyKey, optional targetCategoryId,
#       optional targetCategoryName, optional targetCategoryMatch }
#   -AttemptJournalFile      -> optional global real_dxm_path_b_attempts.v2
#     path; defaults to a stable file under EvidenceDirectory.
#   -DiscoveryKey            -> one-use opaque key for Discovery and its
#     read-only recovery query; the journal stores only its SHA-256.
#   -DiscoveryReceiptFile    -> Discovery output / Formal input.  It is never
#     overwritten and contains the public persisted receipt projection.
#
# Required order:
#   Prepare(discovery scope) -> Shadow -> Discovery ->
#   Prepare(fresh Formal scope, with journal/key/receipt) -> Formal.
# The second Prepare sends the sealed predecessor hashes to the public scope
# derivation endpoint; Formal never reuses the Discovery task/snapshot/scope or
# ApprovalFile.

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("Prepare", "Shadow", "Discovery", "Formal")]
  [string]$Phase,

  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$ScopeFile = $env:DXM_REAL_SAVE_SCOPE_FILE,
  [string]$ApprovalFile = "",
  [string]$PrepareRequestFile = "",
  [string]$ShadowRequestFile = "",
  [string]$EvidenceDirectory = "",
  [string]$AttemptJournalFile = "",
  [string]$DiscoveryKey = "",
  [string]$DiscoveryReceiptFile = "",
  [int]$PollIntervalSeconds = 2,
  [int]$PollTimeoutSeconds = 1800,
  [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$script:Trace = [System.Collections.Generic.List[object]]::new()
$script:DiscoveryPostSent = $false
$script:DiscoveryNotAcceptedProven = $false
$script:FormalPostSent = $false
$script:FormalNotAcceptedProven = $false
$script:FormalCompleted = $false

function Resolve-ExternalFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
  )

  if ([string]::IsNullOrWhiteSpace($Path)) {
    throw "$Label is required and must be an external file."
  }
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label does not exist."
  }
  $fullPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
  $rootPrefix = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
  if ($fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Label must be outside the Git worktree."
  }
  return $fullPath
}

function Resolve-ExternalOutputFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
  )

  if ([string]::IsNullOrWhiteSpace($Path)) {
    throw "$Label is required and must be a Git-external output path."
  }
  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $normalizedRoot = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd("\", "/")
  $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
  if ($fullPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Label must be outside the Git worktree."
  }
  $parent = Split-Path -Parent $fullPath
  if ([string]::IsNullOrWhiteSpace($parent)) { throw "$Label parent directory is invalid." }
  [System.IO.Directory]::CreateDirectory($parent) | Out-Null
  if (Test-Path -LiteralPath $fullPath -PathType Container) {
    throw "$Label must be a file path, not a directory."
  }
  return $fullPath
}

function Resolve-ExternalDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
  )

  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $normalizedRoot = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd("\", "/")
  $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
  if ($fullPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "EvidenceDirectory must be outside the Git worktree."
  }
  [System.IO.Directory]::CreateDirectory($fullPath) | Out-Null
  return $fullPath
}

function Resolve-LoopbackBaseUrl {
  param([Parameter(Mandatory = $true)][string]$Value)

  try { $uri = [Uri]$Value } catch { throw "BaseUrl must be an absolute loopback HTTP(S) URL." }
  if (
    -not $uri.IsAbsoluteUri -or
    $uri.Scheme -notin @("http", "https") -or
    -not $uri.IsLoopback -or
    -not [string]::IsNullOrEmpty($uri.UserInfo) -or
    -not [string]::IsNullOrEmpty($uri.Query) -or
    -not [string]::IsNullOrEmpty($uri.Fragment) -or
    $uri.AbsolutePath -notin @("", "/")
  ) {
    throw "BaseUrl must be an origin-only loopback HTTP(S) URL."
  }
  return $uri.GetLeftPart([System.UriPartial]::Authority)
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)

  try {
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($text)) { throw "empty" }
    return $text | ConvertFrom-Json
  } catch {
    throw "$Label must contain one valid UTF-8 JSON object."
  }
}

function Test-Property {
  param([object]$Value, [string]$Name)
  return $null -ne $Value -and $null -ne $Value.PSObject.Properties[$Name]
}

function Assert-AllowedProperties {
  param(
    [Parameter(Mandatory = $true)][object]$Value,
    [Parameter(Mandatory = $true)][string[]]$Allowed,
    [Parameter(Mandatory = $true)][string]$Label
  )

  $allowedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  foreach ($name in $Allowed) { $allowedSet.Add($name) | Out-Null }
  foreach ($property in $Value.PSObject.Properties) {
    if (-not $allowedSet.Contains([string]$property.Name)) {
      throw "$Label contains unexpected property $($property.Name)."
    }
  }
}

function Assert-NoWildcards {
  param([object]$Value, [string]$Label = "input")

  if ($null -eq $Value) { return }
  if ($Value -is [string]) {
    $folded = $Value.Trim().ToLowerInvariant()
    if ($Value.Contains("*") -or $Value.Contains("?") -or $Value.Contains("%") -or $folded -in @("all", "any", "all_fields", "any_field", "all_products", "any_product")) {
      throw "$Label contains a forbidden wildcard."
    }
    return
  }
  if ($Value -is [System.Collections.IDictionary]) {
    foreach ($key in $Value.Keys) { Assert-NoWildcards -Value $Value[$key] -Label "$Label.$key" }
    return
  }
  if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [System.Management.Automation.PSCustomObject])) {
    $index = 0
    foreach ($item in $Value) {
      Assert-NoWildcards -Value $item -Label "$Label[$index]"
      $index += 1
    }
    return
  }
  foreach ($property in $Value.PSObject.Properties) {
    Assert-NoWildcards -Value $property.Value -Label "$Label.$($property.Name)"
  }
}

function Assert-ScopeContract {
  param([Parameter(Mandatory = $true)][object]$Scope)

  $required = @(
    "schema", "stage", "path", "issuedAt", "expiresAt", "nonce", "account",
    "shop", "snapshot", "git", "worktree", "runtime", "l2",
    "orderedProducts", "publishAllowed", "maxPhysicalRequestsPerSave", "scopeSha256"
  )
  foreach ($name in $required) {
    if (-not (Test-Property -Value $Scope -Name $name)) { throw "Scope is missing required field $name." }
  }
  if ($Scope.schema -ne "real_dxm_write_scope.v1" -or $Scope.stage -ne "execute" -or $Scope.path -ne "B") {
    throw "Scope schema, stage, and path must be real_dxm_write_scope.v1 / execute / B."
  }
  if ($Scope.publishAllowed -ne $false -or [int]$Scope.maxPhysicalRequestsPerSave -ne 1) {
    throw "Scope must bind publishAllowed=false and maxPhysicalRequestsPerSave=1."
  }
  if ([string]$Scope.scopeSha256 -cnotmatch "^[0-9A-F]{64}$") {
    throw "Scope scopeSha256 must be uppercase SHA-256."
  }
  try {
    $issuedAt = [DateTimeOffset]::Parse([string]$Scope.issuedAt, [Globalization.CultureInfo]::InvariantCulture)
    $expiresAt = [DateTimeOffset]::Parse([string]$Scope.expiresAt, [Globalization.CultureInfo]::InvariantCulture)
  } catch {
    throw "Scope validity timestamps are invalid."
  }
  $now = [DateTimeOffset]::UtcNow
  if ($issuedAt -ge $expiresAt -or $now -lt $issuedAt -or $now -ge $expiresAt) {
    throw "Scope is not currently inside its validity window."
  }
  if ([string]::IsNullOrWhiteSpace([string]$Scope.nonce) -or ([string]$Scope.nonce).Length -lt 16) {
    throw "Scope nonce is invalid."
  }
  $products = @($Scope.orderedProducts)
  if ($products.Count -ne 3) { throw "The system-flow scope must bind exactly three ordered products." }
  $seenProductIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  for ($index = 0; $index -lt 3; $index++) {
    $product = $products[$index]
    if ([int]$product.ordinal -ne ($index + 1) -or [int64]$product.productId -le 0) {
      throw "Scope product ordering is invalid."
    }
    if (-not $seenProductIds.Add([string]$product.productId)) { throw "Scope product IDs must be unique." }
    $saves = @($product.saves)
    if ($saves.Count -ne 2 -or $saves[0].stage -ne "SAVE1" -or $saves[1].stage -ne "SAVE2") {
      throw "Every product must bind SAVE1 then SAVE2."
    }
    if ([int]$saves[0].maxPhysicalRequests -ne 1 -or [int]$saves[1].maxPhysicalRequests -ne 1) {
      throw "Each SAVE stage must permit exactly one physical request."
    }
  }
  Assert-NoWildcards -Value $Scope -Label "scope"
}

function Assert-ApprovalContract {
  param([Parameter(Mandatory = $true)][object]$Approval, [Parameter(Mandatory = $true)][object]$Scope)

  if ($Approval.schema -ne "real_dxm_write_approval.v1" -or $Approval.stage -ne "execute" -or $Approval.decision -ne "APPROVE") {
    throw "ApprovalFile schema, stage, and decision are invalid."
  }
  if ([string]$Approval.scopeSha256 -cne [string]$Scope.scopeSha256 -or [string]$Approval.nonce -cne [string]$Scope.nonce) {
    throw "ApprovalFile does not match the exact scope hash and nonce."
  }
  if ([string]$Approval.expiresAt -cne [string]$Scope.expiresAt -or [string]::IsNullOrWhiteSpace([string]$Approval.approvedBy)) {
    throw "ApprovalFile expiry or approver binding is invalid."
  }
  if ([string]$Approval.approvalSha256 -cnotmatch "^[0-9A-F]{64}$") {
    throw "ApprovalFile approvalSha256 must be uppercase SHA-256."
  }
  Assert-NoWildcards -Value $Approval -Label "approval"
}

function Get-HttpReasonCode {
  param([System.Management.Automation.ErrorRecord]$Record)

  if ($Record.ErrorDetails -and $Record.ErrorDetails.Message) {
    try {
      $parsed = $Record.ErrorDetails.Message | ConvertFrom-Json
      if ($parsed.detail.detail_code) { return [string]$parsed.detail.detail_code }
      if ($parsed.detail.detailCode) { return [string]$parsed.detail.detailCode }
      if ($parsed.detail.reason_code) { return [string]$parsed.detail.reason_code }
      if ($parsed.detail.reasonCode) { return [string]$parsed.detail.reasonCode }
      if ($parsed.reason_code) { return [string]$parsed.reason_code }
      if ($parsed.reasonCode) { return [string]$parsed.reasonCode }
      if ([string]$parsed.detail -ceq "Discovery attempt not found") {
        return "DISCOVERY_ATTEMPT_NOT_FOUND"
      }
    } catch { }
  }
  return "HTTP_REJECTED"
}

function Get-HttpStatusCode {
  param([System.Management.Automation.ErrorRecord]$Record)

  try {
    if ($null -ne $Record.Exception.Response -and $null -ne $Record.Exception.Response.StatusCode) {
      return [int]$Record.Exception.Response.StatusCode
    }
  } catch { }
  return 0
}

function Add-Trace {
  param([string]$Method, [string]$Path, [string]$Status, [string]$ReasonCode = "OK")
  $safePath = ($Path -split "\?", 2)[0]
  $safePath = $safePath -replace "/api/tasks/[0-9]+", "/api/tasks/{id}"
  $safePath = $safePath -replace "/api/plan-snapshots/[0-9]+", "/api/plan-snapshots/{id}"
  $safePath = $safePath -replace "/api/local-plan-templates/[0-9]+", "/api/local-plan-templates/{id}"
  $script:Trace.Add([ordered]@{
    at = [DateTimeOffset]::UtcNow.ToString("o")
    method = $Method
    path = $safePath
    status = $Status
    reasonCode = $ReasonCode
  })
}

function Invoke-PublicJson {
  param(
    [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
    [Parameter(Mandatory = $true)][string]$Path,
    [object]$Body = $null,
    [int]$TimeoutSec = 180
  )

  $uri = $BaseUrl.TrimEnd("/") + $Path
  try {
    if ($null -eq $Body) {
      $response = Invoke-RestMethod -Uri $uri -Method $Method -TimeoutSec $TimeoutSec
    } else {
      $json = $Body | ConvertTo-Json -Depth 100 -Compress
      $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
      $response = Invoke-RestMethod -Uri $uri -Method $Method -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec $TimeoutSec
    }
    Add-Trace -Method $Method -Path $Path -Status "ok"
    return $response
  } catch {
    $reason = Get-HttpReasonCode -Record $_
    $statusCode = Get-HttpStatusCode -Record $_
    Add-Trace -Method $Method -Path $Path -Status "blocked" -ReasonCode $reason
    $failure = [System.InvalidOperationException]::new($reason)
    $failure.Data["HttpStatusCode"] = $statusCode
    $failure.Data["HttpNotAcceptedProven"] = (
      $Method -eq "POST" -and
      $statusCode -ge 400 -and
      $statusCode -lt 500 -and
      $reason -cne "HTTP_REJECTED"
    )
    throw $failure
  }
}

function Update-AttemptJournal {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$PhaseName,
    [Parameter(Mandatory = $true)][ValidateSet("start", "complete", "blocked")][string]$Action,
    [Parameter(Mandatory = $true)][object]$Binding,
    [string]$ReasonCode = "",
    [System.Collections.IDictionary]$Details = $null
  )

  $creating = -not (Test-Path -LiteralPath $Path)
  if ($creating) {
    if ($Action -ne "start" -or $PhaseName -ne "Shadow") {
      throw "Only the first Shadow start may create the global attempt journal."
    }
    try {
      $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
      throw "Attempt journal creation raced with another process."
    }
  } else {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
  }
  try {
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 1024, $true)
    $existingText = $reader.ReadToEnd()
    $reader.Dispose()
    if ($creating) {
      if (-not [string]::IsNullOrEmpty($existingText)) {
        throw "New attempt journal was not empty."
      }
      $journal = [pscustomobject]@{
        schemaVersion = "real_dxm_path_b_attempts.v2"
        unknownObserved = $false
        createdAt = [DateTimeOffset]::UtcNow.ToString("o")
        phases = [pscustomobject]@{}
      }
    } else {
      if ([string]::IsNullOrWhiteSpace($existingText)) {
        throw "Existing attempt journal is empty or incomplete."
      }
      $journal = $existingText | ConvertFrom-Json
      if (
        $journal.schemaVersion -ne "real_dxm_path_b_attempts.v2" -or
        -not (Test-Property -Value $journal -Name "unknownObserved") -or
        -not (Test-Property -Value $journal -Name "phases")
      ) {
        throw "Attempt journal is not the global v2 contract."
      }
    }

    $existing = $journal.phases.PSObject.Properties[$PhaseName]
    if ($Action -eq "start") {
      if ($journal.unknownObserved -eq $true) {
        throw "UNKNOWN was already observed; no further real phase is allowed."
      }
      if ($null -ne $existing) { throw "$PhaseName has already consumed its one allowed attempt." }
      $journal.phases | Add-Member -NotePropertyName $PhaseName -NotePropertyValue ([ordered]@{
        status = "started"
        startedAt = [DateTimeOffset]::UtcNow.ToString("o")
        binding = $Binding
      })
    } else {
      if ($null -eq $existing) { throw "$PhaseName attempt was not started." }
      $entry = $existing.Value
      if ($entry.status -ne "started") { throw "$PhaseName attempt is already terminal." }
      if ((Get-JsonSha256 -Value $entry.binding) -cne (Get-JsonSha256 -Value $Binding)) {
        throw "$PhaseName terminal update does not match its started binding."
      }
      $entry.status = $Action
      $entry | Add-Member -Force -NotePropertyName endedAt -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString("o"))
      if (-not [string]::IsNullOrWhiteSpace($ReasonCode)) {
        $entry | Add-Member -Force -NotePropertyName reasonCode -NotePropertyValue $ReasonCode
        if ($ReasonCode -match "UNKNOWN") { $journal.unknownObserved = $true }
      }
      if ($null -ne $Details) {
        foreach ($key in $Details.Keys) {
          $entry | Add-Member -Force -NotePropertyName ([string]$key) -NotePropertyValue $Details[$key]
        }
      }
    }

    $journal | Add-Member -Force -NotePropertyName updatedAt -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString("o"))
    $rendered = $journal | ConvertTo-Json -Depth 20
    $stream.Position = 0
    $stream.SetLength(0)
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 1024, $true)
    $writer.Write($rendered)
    $writer.Flush()
    $writer.Dispose()
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
}

function Read-AttemptJournal {
  param([Parameter(Mandatory = $true)][string]$Path)

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  try {
    $journal = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  } catch {
    throw "Attempt journal is unreadable."
  }
  if (
    $journal.schemaVersion -ne "real_dxm_path_b_attempts.v2" -or
    -not (Test-Property -Value $journal -Name "unknownObserved") -or
    -not (Test-Property -Value $journal -Name "phases")
  ) {
    throw "Attempt journal is not the global v2 contract."
  }
  return $journal
}

function Record-FormalPrepareJournalBinding {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][object]$Scope,
    [Parameter(Mandatory = $true)][string]$ReaderSessionRef,
    [Parameter(Mandatory = $true)][string]$PredecessorScopeSha256,
    [Parameter(Mandatory = $true)][string]$DiscoveryReceiptSha256
  )

  $binding = New-ScopeJournalBinding -Scope $Scope -ReaderSessionRef $ReaderSessionRef
  $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
  try {
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 1024, $true)
    $existingText = $reader.ReadToEnd()
    $reader.Dispose()
    if ([string]::IsNullOrWhiteSpace($existingText)) {
      throw "Existing attempt journal is empty or incomplete."
    }
    try { $journal = $existingText | ConvertFrom-Json } catch { throw "Attempt journal is unreadable." }
    if (
      $journal.schemaVersion -ne "real_dxm_path_b_attempts.v2" -or
      $journal.unknownObserved -eq $true -or
      $journal.phases.Shadow.status -ne "complete" -or
      $journal.phases.Discovery.status -ne "complete" -or
      $null -ne $journal.phases.PSObject.Properties["Formal"] -or
      [string]$journal.phases.Discovery.binding.scopeSha256 -cne $PredecessorScopeSha256 -or
      [string]$journal.phases.Discovery.discoveryReceiptSha256 -cne $DiscoveryReceiptSha256 -or
      [string]$binding.readerSessionRefSha256 -cne [string]$journal.phases.Discovery.binding.readerSessionRefSha256 -or
      [string]$binding.browserSessionIdSha256 -cne [string]$journal.phases.Discovery.binding.browserSessionIdSha256 -or
      [string]$binding.l2EvidenceFingerprint -cne [string]$journal.phases.Discovery.binding.l2EvidenceFingerprint
    ) {
      throw "Formal Prepare journal continuity is invalid."
    }
    $formalPrepare = [ordered]@{
      status = "prepared"
      preparedAt = [DateTimeOffset]::UtcNow.ToString("o")
      predecessorScopeSha256 = $PredecessorScopeSha256
      discoveryReceiptSha256 = $DiscoveryReceiptSha256
      binding = $binding
    }
    $existing = $journal.PSObject.Properties["formalPrepare"]
    if ($null -ne $existing) {
      $existingValue = $existing.Value
      $existingComparable = [ordered]@{
        status = $existingValue.status
        predecessorScopeSha256 = $existingValue.predecessorScopeSha256
        discoveryReceiptSha256 = $existingValue.discoveryReceiptSha256
        binding = $existingValue.binding
      }
      $candidateComparable = [ordered]@{
        status = $formalPrepare.status
        predecessorScopeSha256 = $formalPrepare.predecessorScopeSha256
        discoveryReceiptSha256 = $formalPrepare.discoveryReceiptSha256
        binding = $formalPrepare.binding
      }
      if ((Get-JsonSha256 -Value $existingComparable) -cne (Get-JsonSha256 -Value $candidateComparable)) {
        throw "Another Formal Prepare binding already exists."
      }
      return $existingValue
    }
    $journal | Add-Member -NotePropertyName formalPrepare -NotePropertyValue $formalPrepare
    $journal | Add-Member -Force -NotePropertyName updatedAt -NotePropertyValue ([DateTimeOffset]::UtcNow.ToString("o"))
    $rendered = $journal | ConvertTo-Json -Depth 30
    $stream.Position = 0
    $stream.SetLength(0)
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 1024, $true)
    $writer.Write($rendered)
    $writer.Flush()
    $writer.Dispose()
    $stream.Flush($true)
    return $formalPrepare
  } finally {
    $stream.Dispose()
  }
}

function Assert-PhasePrerequisites {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$PhaseName,
    [Parameter(Mandatory = $true)][object]$Binding
  )

  $journal = Read-AttemptJournal -Path $Path
  if ($PhaseName -eq "Shadow") {
    if ($null -eq $journal) { return $null }
    if ($journal.unknownObserved -eq $true) { throw "UNKNOWN was already observed." }
    if ($null -ne $journal.phases.PSObject.Properties["Shadow"]) {
      throw "Shadow has already consumed its one allowed attempt."
    }
    if (
      $null -ne $journal.phases.PSObject.Properties["Discovery"] -or
      $null -ne $journal.phases.PSObject.Properties["Formal"]
    ) {
      throw "Shadow cannot start after a later real phase exists."
    }
    return $journal
  }
  if ($null -eq $journal -or $journal.phases.Shadow.status -ne "complete") {
    throw "$PhaseName requires Shadow status=complete."
  }
  if ($journal.unknownObserved -eq $true) { throw "UNKNOWN was already observed." }
  if ($PhaseName -eq "Discovery") {
    if (
      [string]$journal.phases.Shadow.binding.scopeSha256 -cne [string]$Binding.scopeSha256 -or
      [string]$journal.phases.Shadow.binding.readerSessionRefSha256 -cne [string]$Binding.readerSessionRefSha256 -or
      [string]$journal.phases.Shadow.binding.browserSessionIdSha256 -cne [string]$Binding.browserSessionIdSha256 -or
      [string]$journal.phases.Shadow.binding.l2EvidenceFingerprint -cne [string]$Binding.l2EvidenceFingerprint
    ) {
      throw "Discovery must use the exact Shadow scope."
    }
    if ($null -ne $journal.phases.PSObject.Properties["Discovery"]) {
      throw "Discovery has already consumed its one allowed attempt."
    }
    if ($null -ne $journal.phases.PSObject.Properties["Formal"]) {
      throw "Discovery cannot start after Formal exists."
    }
  } elseif ($PhaseName -eq "Formal") {
    if ($journal.phases.Discovery.status -ne "complete") {
      throw "Formal requires Discovery status=complete."
    }
    if ($null -ne $journal.phases.PSObject.Properties["Formal"]) {
      throw "Formal has already consumed its one allowed attempt."
    }
    if ([string]$journal.phases.Discovery.binding.scopeSha256 -ceq [string]$Binding.scopeSha256) {
      throw "Formal must use a fresh scope, not the Discovery scope."
    }
    $formalPrepareProperty = $journal.PSObject.Properties["formalPrepare"]
    if ($null -eq $formalPrepareProperty) {
      throw "Formal requires its journaled post-Discovery Prepare binding."
    }
    $formalPrepare = $formalPrepareProperty.Value
    $preparedBinding = $formalPrepare.binding
    if (
      $formalPrepare.status -ne "prepared" -or
      [string]$formalPrepare.predecessorScopeSha256 -cne [string]$journal.phases.Discovery.binding.scopeSha256 -or
      [string]$formalPrepare.discoveryReceiptSha256 -cne [string]$journal.phases.Discovery.discoveryReceiptSha256 -or
      [string]$preparedBinding.scopeSha256 -cne [string]$Binding.scopeSha256 -or
      [string]$preparedBinding.taskRefSha256 -cne [string]$Binding.taskRefSha256 -or
      [string]$preparedBinding.snapshotRefSha256 -cne [string]$Binding.snapshotRefSha256 -or
      [string]$preparedBinding.snapshotSha256 -cne [string]$Binding.snapshotSha256 -or
      [string]$preparedBinding.nonceSha256 -cne [string]$Binding.nonceSha256 -or
      [string]$preparedBinding.issuedAt -cne [string]$Binding.issuedAt -or
      [string]$preparedBinding.accountIdentitySha256 -cne [string]$Binding.accountIdentitySha256 -or
      [string]$preparedBinding.shopIdentitySha256 -cne [string]$Binding.shopIdentitySha256 -or
      [string]$preparedBinding.gitIdentitySha256 -cne [string]$Binding.gitIdentitySha256 -or
      [string]$preparedBinding.worktreeIdentitySha256 -cne [string]$Binding.worktreeIdentitySha256 -or
      [string]$preparedBinding.runtimeIdentitySha256 -cne [string]$Binding.runtimeIdentitySha256 -or
      [string]$preparedBinding.browserSessionIdSha256 -cne [string]$Binding.browserSessionIdSha256 -or
      [string]$preparedBinding.readerSessionRefSha256 -cne [string]$Binding.readerSessionRefSha256 -or
      [string]$preparedBinding.l2EvidenceFingerprint -cne [string]$Binding.l2EvidenceFingerprint -or
      [string]$preparedBinding.orderedProductIdsSha256 -cne [string]$Binding.orderedProductIdsSha256
    ) {
      throw "Formal scope, session, or L2 evidence drifted after its journaled Prepare."
    }
  }
  return $journal
}

function Get-TextSha256 {
  param([Parameter(Mandatory = $true)][string]$Label, [Parameter(Mandatory = $true)][string]$Value)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes("${Label}:$Value")
  $digest = [System.Security.Cryptography.SHA256]::Create()
  try {
    return ([System.BitConverter]::ToString($digest.ComputeHash($bytes))).Replace("-", "")
  } finally {
    $digest.Dispose()
  }
}

function Get-RawTextSha256 {
  param([Parameter(Mandatory = $true)][string]$Value)

  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
  $digest = [System.Security.Cryptography.SHA256]::Create()
  try {
    return ([System.BitConverter]::ToString($digest.ComputeHash($bytes))).Replace("-", "")
  } finally {
    $digest.Dispose()
  }
}

function Get-JsonSha256 {
  param([Parameter(Mandatory = $true)][object]$Value)

  return Get-RawTextSha256 -Value ($Value | ConvertTo-Json -Depth 100 -Compress)
}

function New-ScopeJournalBinding {
  param(
    [Parameter(Mandatory = $true)][object]$Scope,
    [object]$Approval = $null,
    [string]$ReaderSessionRef = ""
  )

  $orderedProductIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  return [ordered]@{
    scopeSha256 = [string]$Scope.scopeSha256
    taskRefSha256 = Get-TextSha256 -Label "task" -Value ([string]$Scope.snapshot.taskId)
    snapshotRefSha256 = Get-TextSha256 -Label "snapshot" -Value ([string]$Scope.snapshot.snapshotId)
    snapshotSha256 = [string]$Scope.snapshot.snapshotSha256
    nonceSha256 = Get-TextSha256 -Label "nonce" -Value ([string]$Scope.nonce)
    approvalSha256 = $(if ($null -ne $Approval) { [string]$Approval.approvalSha256 } else { $null })
    issuedAt = [string]$Scope.issuedAt
    accountIdentitySha256 = Get-JsonSha256 -Value $Scope.account
    shopIdentitySha256 = Get-JsonSha256 -Value $Scope.shop
    gitIdentitySha256 = Get-JsonSha256 -Value $Scope.git
    worktreeIdentitySha256 = Get-JsonSha256 -Value $Scope.worktree
    runtimeIdentitySha256 = Get-JsonSha256 -Value $Scope.runtime
    browserSessionIdSha256 = Get-TextSha256 -Label "browserSessionId" -Value ([string]$Scope.runtime.browserSessionId)
    readerSessionRefSha256 = $(if (-not [string]::IsNullOrWhiteSpace($ReaderSessionRef)) { Get-TextSha256 -Label "readerSessionRef" -Value $ReaderSessionRef } else { $null })
    l2EvidenceFingerprint = [string]$Scope.l2.evidenceFingerprint
    orderedProductIdsSha256 = Get-RawTextSha256 -Value ($orderedProductIds -join "`n")
  }
}

function Write-ExternalJson {
  param([string]$Path, [object]$Value)
  $json = $Value | ConvertTo-Json -Depth 100
  [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

function Export-PublicAcceptance {
  param([int]$TaskId, [string]$OutputPath)

  $export = Invoke-PublicJson -Method GET -Path "/api/tasks/$TaskId/acceptance-export" -TimeoutSec 120
  Write-ExternalJson -Path $OutputPath -Value $export
  return $export
}

function Assert-ZeroTaskAcceptance {
  param(
    [Parameter(Mandatory = $true)][object]$Export,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if (
    $Export.schemaVersion -ne "real_dxm_path_b_acceptance_export.v1" -or
    -not (Test-Property -Value $Export -Name "saveReceipts") -or
    -not (Test-Property -Value $Export -Name "mutationLedger") -or
    -not (Test-Property -Value $Export -Name "publish") -or
    @($Export.saveReceipts).Count -ne 0 -or
    @($Export.mutationLedger).Count -ne 0 -or
    $Export.publish.allowed -ne $false -or
    $Export.publish.requestCount -ne 0 -or
    $null -ne $Export.publish.published
  ) {
    throw "${Label}_ZERO_WRITE_EVIDENCE_FAILED"
  }
}

function Assert-ShadowRequest {
  param([object]$Request, [object]$Scope)

  if ($Request.schemaVersion -ne "real_dxm_path_b_shadow_request.v1") {
    throw "Shadow request schemaVersion is invalid."
  }
  $ids = @($Request.orderedProductIds | ForEach-Object { [string]$_ })
  $scopeIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  if ($ids.Count -ne 3 -or ($ids -join ",") -cne ($scopeIds -join ",")) {
    throw "Shadow request product order must exactly match the scope."
  }
  if ([string]$Request.shopId -cne [string]$Scope.shop.shopId -or [int]$Request.localPlanTemplateId -le 0) {
    throw "Shadow request shop or local plan binding is invalid."
  }
  if ([string]$Request.sessionRef -cnotmatch "^[0-9a-f]{16}$" -or [string]$Request.idempotencyKey -cnotmatch "^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$") {
    throw "Shadow request session_ref or idempotency key is invalid."
  }
  Assert-NoWildcards -Value $Request -Label "shadowRequest"
}

function New-PlanRequestBody {
  param([object]$Request, [bool]$IncludeFreezeFields, [string]$SnapshotHash = "")

  $body = [ordered]@{
    local_plan_template_id = [int]$Request.localPlanTemplateId
    shop_id = [string]$Request.shopId
    session_ref = [string]$Request.sessionRef
    product_ids = @($Request.orderedProductIds | ForEach-Object { [string]$_ })
  }
  if (Test-Property -Value $Request -Name "targetCategoryId") { $body.target_category_id = [string]$Request.targetCategoryId }
  if (Test-Property -Value $Request -Name "targetCategoryName") { $body.target_category_name = [string]$Request.targetCategoryName }
  if (Test-Property -Value $Request -Name "targetCategoryMatch") { $body.target_category_match = [string]$Request.targetCategoryMatch }
  if ($IncludeFreezeFields) {
    $body.expected_snapshot_hash = $SnapshotHash
    $body.idempotency_key = [string]$Request.idempotencyKey
  }
  return $body
}

function Assert-PrepareRequest {
  param([Parameter(Mandatory = $true)][object]$Request)

  if ($Request.schemaVersion -ne "real_dxm_path_b_prepare_request.v1") {
    throw "Prepare request schemaVersion is invalid."
  }
  Assert-AllowedProperties -Value $Request -Allowed @(
    "schemaVersion", "localPlanTemplateId", "shopId", "sessionRef",
    "idempotencyKey", "prepareKey", "validForSeconds", "orderedProducts",
    "targetCategoryId", "targetCategoryName", "targetCategoryMatch"
  ) -Label "prepareRequest"
  if (
    [int]$Request.localPlanTemplateId -le 0 -or
    [string]::IsNullOrWhiteSpace([string]$Request.shopId) -or
    [string]$Request.sessionRef -cnotmatch "^[0-9a-f]{16}$" -or
    [string]$Request.idempotencyKey -cnotmatch "^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$" -or
    [string]$Request.prepareKey -cnotmatch "^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$" -or
    [int]$Request.validForSeconds -lt 60 -or
    [int]$Request.validForSeconds -gt 600
  ) {
    throw "Prepare request plan, session, idempotency, or validity binding is invalid."
  }
  $products = @($Request.orderedProducts)
  if ($products.Count -ne 3) { throw "Prepare requires exactly three ordered products." }
  $seenProducts = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  foreach ($product in $products) {
    Assert-AllowedProperties -Value $product -Allowed @(
      "productId", "fieldHashBindings"
    ) -Label "prepareRequest.orderedProducts[]"
    if ([int64]$product.productId -le 0 -or -not $seenProducts.Add([string]$product.productId)) {
      throw "Prepare product IDs must be positive and unique."
    }
    $stageCounts = @{ SAVE1 = 0; SAVE2 = 0 }
    $seenFields = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($binding in @($product.fieldHashBindings)) {
      Assert-AllowedProperties -Value $binding -Allowed @(
        "field", "saveStage", "preimageSha256", "expectedSha256"
      ) -Label "prepareRequest.fieldHashBindings[]"
      $field = [string]$binding.field
      if (
        [string]::IsNullOrWhiteSpace($field) -or
        $field -cne $field.Trim() -or
        -not $seenFields.Add($field) -or
        [string]$binding.saveStage -notin @("SAVE1", "SAVE2") -or
        [string]$binding.preimageSha256 -cnotmatch "^[0-9A-F]{64}$" -or
        [string]$binding.expectedSha256 -cnotmatch "^[0-9A-F]{64}$"
      ) {
        throw "Prepare field hash binding is invalid or duplicated."
      }
      $stageCounts[[string]$binding.saveStage] += 1
    }
    if ($stageCounts.SAVE1 -lt 1 -or $stageCounts.SAVE2 -lt 1) {
      throw "Prepare requires explicit SAVE1 and SAVE2 field hashes for every product."
    }
  }
  Assert-NoWildcards -Value $Request -Label "prepareRequest"
}

function New-PreparePlanRequestBody {
  param([Parameter(Mandatory = $true)][object]$Request, [bool]$Freeze, [string]$SnapshotHash = "")

  $body = [ordered]@{
    local_plan_template_id = [int]$Request.localPlanTemplateId
    shop_id = [string]$Request.shopId
    session_ref = [string]$Request.sessionRef
    product_ids = @($Request.orderedProducts | ForEach-Object { [string]$_.productId })
  }
  if (Test-Property -Value $Request -Name "targetCategoryId") { $body.target_category_id = [string]$Request.targetCategoryId }
  if (Test-Property -Value $Request -Name "targetCategoryName") { $body.target_category_name = [string]$Request.targetCategoryName }
  if (Test-Property -Value $Request -Name "targetCategoryMatch") { $body.target_category_match = [string]$Request.targetCategoryMatch }
  if ($Freeze) {
    $body.expected_snapshot_hash = $SnapshotHash
    $body.idempotency_key = [string]$Request.idempotencyKey
  }
  return $body
}

function Invoke-PreparePhase {
  param(
    [Parameter(Mandatory = $true)][object]$Request,
    [Parameter(Mandatory = $true)][string]$ScopeOutputPath,
    [string]$PredecessorScopeSha256 = "",
    [string]$DiscoveryReceiptSha256 = "",
    [object]$PredecessorBinding = $null,
    [string]$DiscoveryEndedAt = "",
    [string]$ReaderSessionRef = ""
  )

  $formalLineage = -not [string]::IsNullOrWhiteSpace($PredecessorScopeSha256)
  if (
    $formalLineage -ne (-not [string]::IsNullOrWhiteSpace($DiscoveryReceiptSha256)) -or
    ($formalLineage -and (
      $PredecessorScopeSha256 -cnotmatch "^[0-9A-F]{64}$" -or
      $DiscoveryReceiptSha256 -cnotmatch "^[0-9A-F]{64}$" -or
      $PredecessorScopeSha256 -ceq $DiscoveryReceiptSha256
    ))
  ) {
    throw "PREPARE_FORMAL_LINEAGE_INVALID"
  }

  $shops = Invoke-PublicJson -Method GET -Path "/api/dxm/draft-reader/shops" -TimeoutSec 120
  if ($shops.source -ne "api" -or $shops.session_bound -ne $true -or [string]$shops.session_ref -cne [string]$Request.sessionRef) {
    throw "PREPARE_READER_SESSION_NOT_BOUND"
  }
  $matchingShops = @($shops.shops | Where-Object { [string]$_.id -ceq [string]$Request.shopId })
  if ($matchingShops.Count -ne 1) { throw "PREPARE_SHOP_NOT_FOUND" }

  $requiredIds = @($Request.orderedProducts | ForEach-Object { [string]$_.productId })
  $visibleIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  $pageNo = 1
  do {
    $productsPath = "/api/dxm/draft-reader/products?shop_id=$([uri]::EscapeDataString([string]$Request.shopId))&page_no=$pageNo&page_size=200"
    $productPage = Invoke-PublicJson -Method GET -Path $productsPath -TimeoutSec 180
    if (
      $productPage.source -ne "api" -or
      $productPage.session_bound -ne $true -or
      [string]::IsNullOrWhiteSpace([string]$productPage.session_ref) -or
      [string]$productPage.session_ref -cne [string]$Request.sessionRef
    ) {
      throw "PREPARE_PRODUCT_READER_NOT_SESSION_BOUND"
    }
    foreach ($item in @($productPage.items)) { $visibleIds.Add([string]$item.id) | Out-Null }
    $missing = @($requiredIds | Where-Object { -not $visibleIds.Contains($_) })
    $hasNext = $productPage.pagination.has_next -eq $true
    $pageNo += 1
  } while ($missing.Count -gt 0 -and $hasNext)
  if ($missing.Count -gt 0) { throw "PREPARE_PRODUCT_NOT_IN_FRESH_READER" }

  $plan = Invoke-PublicJson -Method GET -Path "/api/local-plan-templates/$([int]$Request.localPlanTemplateId)" -TimeoutSec 60
  if ($plan.path -ne "B" -or [string]$plan.shop_id -cne [string]$Request.shopId) {
    throw "PREPARE_PLAN_BINDING_DRIFT"
  }

  $previewBody = New-PreparePlanRequestBody -Request $Request -Freeze $false
  $preview = Invoke-PublicJson -Method POST -Path "/api/plan-snapshots/preview?projection=scope_prepare" -Body $previewBody -TimeoutSec 300
  if (
    $preview.schemaVersion -ne "real_dxm_path_b_scope_prepare_projection.v1" -or
    $preview.path -ne "B" -or
    $preview.publishAllowed -ne $false -or
    (@($preview.orderedProductIds | ForEach-Object { [string]$_ }) -join ",") -cne ($requiredIds -join ",")
  ) {
    throw "PREPARE_PREVIEW_SCOPE_DRIFT"
  }

  $previewByProduct = @{}
  foreach ($item in @($preview.orderedProducts)) { $previewByProduct[[string]$item.productId] = $item }
  foreach ($product in @($Request.orderedProducts)) {
    $projected = $previewByProduct[[string]$product.productId]
    if ($null -eq $projected) { throw "PREPARE_FIELD_HASH_PRODUCT_MISSING" }
    $hashByField = @{}
    foreach ($field in @($projected.fieldHashes)) { $hashByField[[string]$field.field] = $field }
    foreach ($binding in @($product.fieldHashBindings)) {
      $fieldHash = $hashByField[[string]$binding.field]
      if (
        $null -eq $fieldHash -or
        [string]$fieldHash.saveStage -cne [string]$binding.saveStage
      ) {
        throw "PREPARE_FIELD_STAGE_AUTHORITY_DRIFT"
      }
      if (
        $fieldHash.preimageAvailable -ne $true -or
        [string]$fieldHash.preimageSha256 -cne [string]$binding.preimageSha256 -or
        [string]$fieldHash.expectedSha256 -cne [string]$binding.expectedSha256
      ) {
        throw "PREPARE_FIELD_HASH_BINDING_DRIFT"
      }
    }
  }

  $freezeBody = New-PreparePlanRequestBody -Request $Request -Freeze $true -SnapshotHash ([string]$preview.snapshotSha256)
  $frozen = Invoke-PublicJson -Method POST -Path "/api/plan-snapshots?projection=scope_prepare" -Body $freezeBody -TimeoutSec 300
  if (
    [int]$frozen.snapshotId -le 0 -or
    [int]$frozen.taskId -le 0 -or
    [string]$frozen.snapshotSha256 -cne [string]$preview.snapshotSha256
  ) {
    throw "PREPARE_FREEZE_BINDING_DRIFT"
  }
  $taskProjection = Invoke-PublicJson -Method GET -Path "/api/tasks/$([int]$frozen.taskId)/scope-prepare" -TimeoutSec 120
  if (
    $taskProjection.taskStatus -ne "draft" -or
    [int]$taskProjection.snapshotId -ne [int]$frozen.snapshotId -or
    [string]$taskProjection.snapshotSha256 -cne [string]$frozen.snapshotSha256
  ) {
    throw "PREPARE_TASK_BINDING_DRIFT"
  }
  $beforeScopeAcceptance = Invoke-PublicJson -Method GET -Path "/api/tasks/$([int]$frozen.taskId)/acceptance-export" -TimeoutSec 120
  Assert-ZeroTaskAcceptance -Export $beforeScopeAcceptance -Label "PREPARE_BEFORE_SCOPE"

  $deriveBody = [ordered]@{
    schemaVersion = "real_dxm_path_b_scope_prepare.v1"
    taskId = [int]$frozen.taskId
    prepareKey = [string]$Request.prepareKey
    validForSeconds = [int]$Request.validForSeconds
    orderedProducts = @($Request.orderedProducts)
    predecessorScopeSha256 = $null
    discoveryReceiptSha256 = $null
  }
  if ($formalLineage) {
    $deriveBody.predecessorScopeSha256 = $PredecessorScopeSha256
    $deriveBody.discoveryReceiptSha256 = $DiscoveryReceiptSha256
  }
  $prepared = Invoke-PublicJson -Method POST -Path "/api/real-dxm/path-b/scopes/derive-and-prepare" -Body $deriveBody -TimeoutSec 300
  if (
    $prepared.ok -ne $true -or
    $prepared.status -ne "SCOPE_PREPARED" -or
    $prepared.counterEvidence.source -ne "prepare_route_contract_declaration" -or
    $prepared.counterEvidence.measured -ne $false -or
    $prepared.counterEvidence.requiredIndependentCheck -ne "task_acceptance_export_before_after" -or
    $prepared.counters.physicalSave -ne 0 -or
    $prepared.counters.browserMutation -ne 0 -or
    $prepared.counters.publishRequest -ne 0
  ) {
    throw "PREPARE_SCOPE_NOT_ZERO_REAL_WRITE"
  }
  if ($formalLineage -and (
    [string]$prepared.purpose -cne "formal" -or
    [string]$prepared.predecessorScopeSha256 -cne $PredecessorScopeSha256 -or
    [string]$prepared.discoveryReceiptSha256 -cne $DiscoveryReceiptSha256 -or
    [string]$prepared.scope.scopeSha256 -ceq $PredecessorScopeSha256
  )) {
    throw "PREPARE_FORMAL_LINEAGE_NOT_PERSISTED"
  }
  if (-not $formalLineage -and (
    [string]$prepared.purpose -cne "discovery" -or
    -not [string]::IsNullOrEmpty([string]$prepared.predecessorScopeSha256) -or
    -not [string]::IsNullOrEmpty([string]$prepared.discoveryReceiptSha256)
  )) {
    throw "PREPARE_DISCOVERY_PURPOSE_OR_LINEAGE_INVALID"
  }
  $afterScopeAcceptance = Invoke-PublicJson -Method GET -Path "/api/tasks/$([int]$frozen.taskId)/acceptance-export" -TimeoutSec 120
  Assert-ZeroTaskAcceptance -Export $afterScopeAcceptance -Label "PREPARE_AFTER_SCOPE"
  Assert-ScopeContract -Scope $prepared.scope
  if ($formalLineage) {
    if ($null -eq $PredecessorBinding -or [string]::IsNullOrWhiteSpace($DiscoveryEndedAt)) {
      throw "PREPARE_FORMAL_JOURNAL_BINDING_MISSING"
    }
    Assert-FreshFormalPreparedScope -FormalScope $prepared.scope -PredecessorBinding $PredecessorBinding -DiscoveryEndedAt $DiscoveryEndedAt -ReaderSessionRef $ReaderSessionRef
  }
  if (Test-Path -LiteralPath $ScopeOutputPath -PathType Leaf) {
    $existingScope = Read-JsonFile -Path $ScopeOutputPath -Label "existing ScopeFile"
    Assert-ScopeContract -Scope $existingScope
    $existingCanonical = $existingScope | ConvertTo-Json -Depth 100 -Compress
    $preparedCanonical = $prepared.scope | ConvertTo-Json -Depth 100 -Compress
    if ($existingCanonical -cne $preparedCanonical) {
      throw "PREPARE_SCOPE_OUTPUT_CONFLICT"
    }
  } else {
    Write-ExternalJson -Path $ScopeOutputPath -Value $prepared.scope
  }
  return $prepared
}

function Invoke-ShadowPhase {
  param([object]$Scope, [object]$Request, [string]$ExportPath)

  $shops = Invoke-PublicJson -Method GET -Path "/api/dxm/draft-reader/shops" -TimeoutSec 120
  if ($shops.source -ne "api" -or $shops.session_bound -ne $true -or [string]$shops.session_ref -cne [string]$Request.sessionRef) {
    throw "SHADOW_READER_SESSION_NOT_BOUND"
  }
  $matchingShops = @($shops.shops | Where-Object { [string]$_.id -ceq [string]$Scope.shop.shopId })
  if ($matchingShops.Count -ne 1 -or [string]$matchingShops[0].name -cne [string]$Scope.shop.shopName) {
    throw "SHADOW_SHOP_IDENTITY_DRIFT"
  }

  $requiredIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  $visibleIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  $pageNo = 1
  do {
    $productsPath = "/api/dxm/draft-reader/products?shop_id=$([uri]::EscapeDataString([string]$Scope.shop.shopId))&page_no=$pageNo&page_size=200"
    $productPage = Invoke-PublicJson -Method GET -Path $productsPath -TimeoutSec 180
    if (
      $productPage.source -ne "api" -or
      $productPage.session_bound -ne $true -or
      [string]::IsNullOrWhiteSpace([string]$productPage.session_ref) -or
      [string]$productPage.session_ref -cne [string]$Request.sessionRef
    ) {
      throw "SHADOW_PRODUCT_READER_NOT_SESSION_BOUND"
    }
    foreach ($item in @($productPage.items)) { $visibleIds.Add([string]$item.id) | Out-Null }
    $missing = @($requiredIds | Where-Object { -not $visibleIds.Contains($_) })
    $hasNext = $productPage.pagination.has_next -eq $true
    $pageNo += 1
  } while ($missing.Count -gt 0 -and $hasNext)
  if ($missing.Count -gt 0) { throw "SHADOW_PRODUCT_NOT_IN_FRESH_READER" }

  $plan = Invoke-PublicJson -Method GET -Path "/api/local-plan-templates/$([int]$Request.localPlanTemplateId)" -TimeoutSec 60
  if ($plan.path -ne "B" -or [string]$plan.shop_id -cne [string]$Scope.shop.shopId) {
    throw "SHADOW_PLAN_BINDING_DRIFT"
  }

  $previewBody = New-PlanRequestBody -Request $Request -IncludeFreezeFields $false
  $preview = Invoke-PublicJson -Method POST -Path "/api/plan-snapshots/preview?projection=scope_prepare" -Body $previewBody -TimeoutSec 300
  $previewIds = @($preview.orderedProductIds | ForEach-Object { [string]$_ })
  $scopeIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  if ($preview.path -ne "B" -or $preview.publishAllowed -ne $false -or ($previewIds -join ",") -cne ($scopeIds -join ",")) {
    throw "SHADOW_PREVIEW_SCOPE_DRIFT"
  }
  if ([string]$preview.snapshotSha256 -cne [string]$Scope.snapshot.snapshotSha256) {
    throw "SHADOW_PREVIEW_HASH_DRIFT"
  }

  $freezeBody = New-PlanRequestBody -Request $Request -IncludeFreezeFields $true -SnapshotHash ([string]$preview.snapshotSha256)
  $frozen = Invoke-PublicJson -Method POST -Path "/api/plan-snapshots?projection=scope_prepare" -Body $freezeBody -TimeoutSec 300
  if ([int]$frozen.snapshotId -ne [int]$Scope.snapshot.snapshotId -or [int]$frozen.taskId -ne [int]$Scope.snapshot.taskId) {
    throw "SHADOW_FROZEN_TASK_BINDING_DRIFT"
  }

  $task = Invoke-PublicJson -Method GET -Path "/api/tasks/$([int]$frozen.taskId)/scope-prepare" -TimeoutSec 60
  $taskIds = @($task.orderedProductIds | ForEach-Object { [string]$_ })
  if ([int]$task.taskId -ne [int]$Scope.snapshot.taskId -or $task.taskStatus -ne "draft" -or $task.path -ne "B" -or ($taskIds -join ",") -cne ($scopeIds -join ",")) {
    throw "SHADOW_TASK_CONTRACT_DRIFT"
  }

  $export = Export-PublicAcceptance -TaskId ([int]$Scope.snapshot.taskId) -OutputPath $ExportPath
  if (
    $export.schemaVersion -ne "real_dxm_path_b_acceptance_export.v1" -or
    -not (Test-Property -Value $export -Name "saveReceipts") -or
    -not (Test-Property -Value $export -Name "mutationLedger") -or
    -not (Test-Property -Value $export -Name "publish") -or
    @($export.saveReceipts).Count -ne 0 -or
    @($export.mutationLedger).Count -ne 0 -or
    $export.publish.allowed -ne $false -or
    $export.publish.requestCount -ne 0 -or
    $null -ne $export.publish.published
  ) {
    throw "SHADOW_ZERO_WRITE_EVIDENCE_FAILED"
  }
}

function Test-TaskUnknown {
  param([object]$Task)

  if (
    [string]$Task.status -in @("unknown", "needs_manual_review") -or
    [string]$Task.error_code -eq "UNKNOWN" -or
    [string]$Task.current_step_code -match "^UNKNOWN(?:_|$)" -or
    [string]$Task.execution_state -eq "unknown" -or
    $Task.needs_manual_review -eq $true
  ) { return $true }
  foreach ($job in @($Task.jobs)) {
    if (
      [string]$job.status -in @("unknown", "needs_manual_review") -or
      [string]$job.error_code -eq "UNKNOWN" -or
      [string]$job.current_step_code -match "^UNKNOWN(?:_|$)" -or
      [string]$job.execution_state -eq "unknown" -or
      $job.needs_manual_review -eq $true
    ) { return $true }
  }
  return $false
}

function Assert-DiscoveryKey {
  param([Parameter(Mandatory = $true)][string]$Value)

  if ($Value -cnotmatch "^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$") {
    throw "DiscoveryKey is invalid."
  }
  Assert-NoWildcards -Value $Value -Label "DiscoveryKey"
}

function Get-DiscoveryRecovery {
  param([Parameter(Mandatory = $true)][string]$DiscoveryKeySha256)

  if ($DiscoveryKeySha256 -cnotmatch "^[0-9A-F]{64}$") {
    throw "Discovery key SHA-256 is invalid."
  }
  return Invoke-PublicJson -Method GET -Path "/api/real-dxm/path-b/discovery/by-key-sha256/$DiscoveryKeySha256" -TimeoutSec 120
}

function Assert-DiscoveryRecoveryEnvelope {
  param(
    [Parameter(Mandatory = $true)][object]$Recovery,
    [Parameter(Mandatory = $true)][object]$Scope,
    [Parameter(Mandatory = $true)][string]$DiscoveryKeySha256,
    [switch]$RequireSealed
  )

  $allowedStatuses = @("ARMED", "RUNNING", "DISCOVERY_SEALED", "UNKNOWN", "BLOCKED")
  if (
    $Recovery.ok -ne $true -or
    [string]$Recovery.status -notin $allowedStatuses -or
    [int]$Recovery.taskId -ne [int]$Scope.snapshot.taskId -or
    [string]$Recovery.discoveryKeySha256 -cne $DiscoveryKeySha256 -or
    [string]$Recovery.scopeSha256 -cne [string]$Scope.scopeSha256
  ) {
    throw "DISCOVERY_RECOVERY_BINDING_INVALID"
  }
  if ([string]$Recovery.status -eq "UNKNOWN") { throw "DISCOVERY_UNKNOWN_OBSERVED" }
  if ([string]$Recovery.status -eq "BLOCKED") { throw "DISCOVERY_TERMINAL_BLOCKED" }
  if (-not $RequireSealed -and [string]$Recovery.status -ne "DISCOVERY_SEALED") {
    return $null
  }
  if ([string]$Recovery.status -ne "DISCOVERY_SEALED" -or -not (Test-Property -Value $Recovery -Name "receipt")) {
    throw "DISCOVERY_RECEIPT_NOT_SEALED"
  }

  $receipt = $Recovery.receipt
  $firstProductId = [int64]$Scope.orderedProducts[0].productId
  $scopeProductIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  $receiptProductIds = @($receipt.ordered_product_ids | ForEach-Object { [string]$_ })
  if (
    $receipt.schema_version -ne "dxm.real-dxm-path-b.save1-discovery-receipt.v1" -or
    [int]$receipt.task_id -ne [int]$Scope.snapshot.taskId -or
    [int]$receipt.job_id -le 0 -or
    [int64]$receipt.product_id -ne $firstProductId -or
    [int]$receipt.snapshot_id -ne [int]$Scope.snapshot.snapshotId -or
    [string]$receipt.snapshot_sha256 -cne [string]$Scope.snapshot.snapshotSha256 -or
    [string]$receipt.scope_sha256 -cne [string]$Scope.scopeSha256 -or
    [string]$receipt.account_ref_hash -cne [string]$Scope.account.accountContextHash -or
    [int64]$receipt.shop_id -ne [int64]$Scope.shop.shopId -or
    [string]$receipt.shop_name -cne [string]$Scope.shop.shopName -or
    [string]$receipt.git_head -cne [string]$Scope.git.head -or
    -not (Test-Property -Value $receipt -Name "worktree") -or
    -not (Test-Property -Value $receipt -Name "runtime") -or
    (Get-JsonSha256 -Value $receipt.worktree) -cne (Get-JsonSha256 -Value $Scope.worktree) -or
    (Get-JsonSha256 -Value $receipt.runtime) -cne (Get-JsonSha256 -Value $Scope.runtime) -or
    ($receiptProductIds -join ",") -cne ($scopeProductIds -join ",") -or
    [string]$receipt.discovery_key_sha256 -cne $DiscoveryKeySha256 -or
    [int]$receipt.physical_mutation_count -ne 1 -or
    [int]$receipt.save1_count -ne 1 -or
    [int]$receipt.save2_count -ne 0 -or
    [int]$receipt.other_product_mutation_count -ne 0 -or
    [int]$receipt.publish_request_count -ne 0 -or
    $receipt.published -ne $false -or
    [int]$receipt.unknown_count -ne 0 -or
    [string]$receipt.first_save_intent_handshake_sha256 -cnotmatch "^[0-9A-F]{64}$" -or
    [string]$receipt.unpublished_action_result_sha256 -cnotmatch "^[0-9A-F]{64}$" -or
    [string]$receipt.field_readbacks_sha256 -cnotmatch "^[0-9A-F]{64}$" -or
    [string]$receipt.unpublished_readback_sha256 -cnotmatch "^[0-9A-F]{64}$" -or
    [string]$receipt.discovery_receipt_sha256 -cnotmatch "^[0-9A-F]{64}$" -or
    [string]$Recovery.discoveryReceiptSha256 -cne [string]$receipt.discovery_receipt_sha256
  ) {
    throw "DISCOVERY_RECEIPT_BINDING_INVALID"
  }
  if ([string]$receipt.first_save_intent_handshake_sha256 -ceq [string]$receipt.unpublished_action_result_sha256) {
    throw "DISCOVERY_RECEIPT_PROOFS_REUSED"
  }
  $expectedSave1Fields = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  foreach ($field in @($Scope.orderedProducts[0].allowedFields)) {
    if ([string]$field.saveStage -ceq "SAVE1") {
      $expectedSave1Fields.Add([string]$field.field) | Out-Null
    }
  }
  $observedSave1Fields = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
  foreach ($readback in @($receipt.field_readbacks)) {
    if (
      $readback.readback_proven -ne $true -or
      [string]::IsNullOrWhiteSpace([string]$readback.field_key) -or
      -not (Test-Property -Value $readback -Name "after_value") -or
      -not $observedSave1Fields.Add([string]$readback.field_key)
    ) {
      throw "DISCOVERY_RECEIPT_FIELD_READBACK_INVALID"
    }
  }
  if (
    $expectedSave1Fields.Count -lt 1 -or
    $expectedSave1Fields.Count -ne $observedSave1Fields.Count -or
    @($expectedSave1Fields | Where-Object { -not $observedSave1Fields.Contains($_) }).Count -ne 0
  ) {
    throw "DISCOVERY_RECEIPT_FIELD_READBACK_COVERAGE_INVALID"
  }
  return $receipt
}

function New-DiscoveryReceiptScopeProjection {
  param([Parameter(Mandatory = $true)][object]$Receipt)

  $products = @()
  $ordinal = 0
  foreach ($productId in @($Receipt.ordered_product_ids)) {
    $ordinal += 1
    $allowedFields = @()
    if ($ordinal -eq 1) {
      $allowedFields = @(
        $Receipt.field_readbacks | ForEach-Object {
          [pscustomobject]@{
            field = [string]$_.field_key
            saveStage = "SAVE1"
          }
        }
      )
    }
    $products += [pscustomobject]@{
      ordinal = $ordinal
      productId = [int64]$productId
      allowedFields = $allowedFields
    }
  }
  return [pscustomobject]@{
    scopeSha256 = [string]$Receipt.scope_sha256
    account = [pscustomobject]@{
      accountContextHash = [string]$Receipt.account_ref_hash
    }
    shop = [pscustomobject]@{
      shopId = [int64]$Receipt.shop_id
      shopName = [string]$Receipt.shop_name
    }
    snapshot = [pscustomobject]@{
      taskId = [int]$Receipt.task_id
      snapshotId = [int]$Receipt.snapshot_id
      snapshotSha256 = [string]$Receipt.snapshot_sha256
    }
    git = [pscustomobject]@{ head = [string]$Receipt.git_head }
    worktree = $Receipt.worktree
    runtime = $Receipt.runtime
    orderedProducts = $products
  }
}

function Assert-FormalSave1ReadbackContinuity {
  param(
    [Parameter(Mandatory = $true)][string]$ReceiptPath,
    [Parameter(Mandatory = $true)][string]$ScopePath,
    [Parameter(Mandatory = $true)][string]$PythonExecutable
  )

  # Python is used only as an offline canonical-JSON verifier.  It mirrors the
  # backend's sorted-key, compact, UTF-8 JSON hashing without importing the app
  # or touching its persistence/runtime.
  $canonicalVerifier = @'
import hashlib
import json
import re
import sys

HEX64 = re.compile(r"^[0-9A-F]{64}$")

def reject():
    print("FORMAL_SAVE1_READBACK_CONTINUITY_INVALID", file=sys.stderr)
    raise SystemExit(4)

def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)

def canonical_sha256(value):
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest().upper()

try:
    receipt = load_json(sys.argv[1])
    scope = load_json(sys.argv[2])
    products = scope.get("orderedProducts")
    first_products = [
        item
        for item in products
        if isinstance(item, dict) and item.get("ordinal") == 1
    ] if isinstance(products, list) else []
    if len(first_products) != 1:
        reject()

    formal_save1 = {}
    allowed_fields = first_products[0].get("allowedFields")
    if not isinstance(allowed_fields, list):
        reject()
    for item in allowed_fields:
        if not isinstance(item, dict) or item.get("saveStage") != "SAVE1":
            continue
        field = item.get("field")
        preimage = item.get("preimageSha256")
        if (
            not isinstance(field, str)
            or not field.strip()
            or field in formal_save1
            or not isinstance(preimage, str)
            or HEX64.fullmatch(preimage) is None
        ):
            reject()
        formal_save1[field] = preimage
    if not formal_save1:
        reject()

    discovery_after = {}
    readbacks = receipt.get("field_readbacks")
    if not isinstance(readbacks, list) or not readbacks:
        reject()
    for item in readbacks:
        if (
            not isinstance(item, dict)
            or item.get("readback_proven") is not True
            or "after_value" not in item
            or not isinstance(item.get("field_key"), str)
            or not item["field_key"].strip()
            or item["field_key"] in discovery_after
        ):
            reject()
        discovery_after[item["field_key"]] = canonical_sha256(item["after_value"])
    if discovery_after != formal_save1:
        reject()
except SystemExit:
    raise
except Exception:
    reject()

print(f"FORMAL_SAVE1_READBACK_CONTINUITY_OK count={len(formal_save1)}")
'@

  $verifierOutput = @(& $PythonExecutable -c $canonicalVerifier $ReceiptPath $ScopePath 2>&1)
  if (
    $LASTEXITCODE -ne 0 -or
    $verifierOutput.Count -ne 1 -or
    [string]$verifierOutput[0] -cnotmatch "^FORMAL_SAVE1_READBACK_CONTINUITY_OK count=[1-9][0-9]*$"
  ) {
    throw "FORMAL_SAVE1_READBACK_CONTINUITY_INVALID"
  }
}

function Write-NewExternalJson {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][object]$Value,
    [Parameter(Mandatory = $true)][string]$ConflictCode
  )

  $json = ($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine
  try {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  } catch [System.IO.IOException] {
    throw $ConflictCode
  }
  try {
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false), 1024, $true)
    $writer.Write($json)
    $writer.Flush()
    $writer.Dispose()
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
}

function Stop-TaskAndConfirm {
  param([Parameter(Mandatory = $true)][int]$TaskId)

  $terminal = @("completed", "partial_success", "failed", "needs_manual_review", "cancelled", "stopped")
  try {
    $current = Invoke-PublicJson -Method GET -Path "/api/tasks/$TaskId" -TimeoutSec 60
    if ([string]$current.status -in $terminal) { return }
  } catch { }

  try {
    Invoke-PublicJson -Method POST -Path "/api/tasks/$TaskId/stop" -TimeoutSec 60 | Out-Null
  } catch {
    throw "TASK_STOP_REQUEST_FAILED"
  }
  $stopDeadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Min(120, $PollTimeoutSeconds))
  while ([DateTimeOffset]::UtcNow -lt $stopDeadline) {
    try {
      $current = Invoke-PublicJson -Method GET -Path "/api/tasks/$TaskId" -TimeoutSec 60
      if ([string]$current.status -in $terminal) { return }
    } catch { }
    Start-Sleep -Seconds $PollIntervalSeconds
  }
  throw "TASK_STOP_NOT_CONFIRMED"
}

function Invoke-DiscoveryPhase {
  param(
    [Parameter(Mandatory = $true)][object]$Scope,
    [Parameter(Mandatory = $true)][object]$Approval,
    [Parameter(Mandatory = $true)][string]$DiscoveryKeyValue,
    [Parameter(Mandatory = $true)][string]$ReceiptPath,
    [Parameter(Mandatory = $true)][string]$ExportPath
  )

  Assert-DiscoveryKey -Value $DiscoveryKeyValue
  $keySha256 = Get-RawTextSha256 -Value $DiscoveryKeyValue
  $taskId = [int]$Scope.snapshot.taskId
  $targetProductId = [int64]$Scope.orderedProducts[0].productId
  $startBody = [ordered]@{
    schemaVersion = "real_dxm_path_b_save1_discovery_start.v1"
    taskId = $taskId
    targetProductId = $targetProductId
    discoveryKey = $DiscoveryKeyValue
    approvedBy = [string]$Approval.approvedBy
    confirmation = "CONFIRM_DXM_SAVE_ONLY"
    realDxmWriteScope = $Scope
    realDxmWriteApproval = $Approval
  }

  $startReturned = $false
  $recovery = $null
  try {
    $script:DiscoveryPostSent = $true
    $started = Invoke-PublicJson -Method POST -Path "/api/real-dxm/path-b/discovery/approve-and-start" -Body $startBody -TimeoutSec 180
    $startReturned = $true
    if (
      $started.ok -ne $true -or
      [int]$started.taskId -ne $taskId -or
      $started.authorizationConsumed -ne $true -or
      [string]$started.status -ne "running" -or
      [string]$started.discoveryKeySha256 -cne $keySha256 -or
      [string]$started.scopeSha256 -cne [string]$Scope.scopeSha256
    ) {
      throw "DISCOVERY_ATOMIC_START_RESPONSE_INVALID"
    }
  } catch {
    $startFailure = $_
    if ($startFailure.Exception.Data["HttpNotAcceptedProven"] -eq $true) {
      $script:DiscoveryNotAcceptedProven = $true
      throw $startFailure
    }
    $recoveryFailure = $null
    try {
      $recovery = Get-DiscoveryRecovery -DiscoveryKeySha256 $keySha256
      Assert-DiscoveryRecoveryEnvelope -Recovery $recovery -Scope $Scope -DiscoveryKeySha256 $keySha256 | Out-Null
    } catch {
      $recoveryFailure = $_
    }
    if ($null -ne $recoveryFailure) {
      if ($recoveryFailure.Exception.Message -ceq "DISCOVERY_ATTEMPT_NOT_FOUND") {
        $script:DiscoveryNotAcceptedProven = $true
        throw $startFailure
      }
      throw "DISCOVERY_START_OUTCOME_UNKNOWN"
    }
    # A recovery row can prove that the POST was accepted, but it cannot turn
    # a transport error or malformed POST response back into a trusted start.
    # Only explicit proof of non-acceptance may avoid journal UNKNOWN.
    throw "DISCOVERY_START_OUTCOME_UNKNOWN"
  }

  $receipt = $null
  if ($null -ne $recovery -and [string]$recovery.status -eq "DISCOVERY_SEALED") {
    $receipt = Assert-DiscoveryRecoveryEnvelope -Recovery $recovery -Scope $Scope -DiscoveryKeySha256 $keySha256 -RequireSealed
  } else {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($PollTimeoutSeconds)
    $terminal = @("completed", "partial_success", "failed", "needs_manual_review", "cancelled", "stopped")
    $task = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
      $task = Invoke-PublicJson -Method GET -Path "/api/tasks/$taskId" -TimeoutSec 60
      if (Test-TaskUnknown -Task $task) {
        try { Stop-TaskAndConfirm -TaskId $taskId } catch { }
        try { Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null } catch { }
        throw "DISCOVERY_UNKNOWN_OBSERVED"
      }
      if ([string]$task.status -in $terminal) { break }
      Start-Sleep -Seconds $PollIntervalSeconds
    }
    if ($null -eq $task -or [string]$task.status -notin $terminal) {
      Stop-TaskAndConfirm -TaskId $taskId
      $recovery = Get-DiscoveryRecovery -DiscoveryKeySha256 $keySha256
      if ([string]$recovery.status -ne "DISCOVERY_SEALED") {
        Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
        throw "DISCOVERY_POLL_OUTCOME_UNKNOWN"
      }
    } elseif ([string]$task.status -ne "stopped") {
      Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
      throw "DISCOVERY_DID_NOT_SEAL_STOP"
    }
    $recovery = Get-DiscoveryRecovery -DiscoveryKeySha256 $keySha256
    $receipt = Assert-DiscoveryRecoveryEnvelope -Recovery $recovery -Scope $Scope -DiscoveryKeySha256 $keySha256 -RequireSealed
  }

  $export = Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath
  if (
    $export.schemaVersion -ne "real_dxm_path_b_acceptance_export.v1" -or
    $export.publish.allowed -ne $false -or
    [int]$export.publish.requestCount -ne 0 -or
    @($export.saveReceipts).Count -ne 0
  ) {
    throw "DISCOVERY_PUBLIC_EXPORT_NOT_ISOLATED"
  }
  Write-NewExternalJson -Path $ReceiptPath -Value $receipt -ConflictCode "DISCOVERY_RECEIPT_FILE_ALREADY_EXISTS"
  $receiptFile = Get-Item -LiteralPath $ReceiptPath
  return [ordered]@{
    discoveryKeySha256 = $keySha256
    discoveryReceiptSha256 = [string]$receipt.discovery_receipt_sha256
    receiptFileSha256 = (Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToUpperInvariant()
    receiptFileSize = [int64]$receiptFile.Length
    startResponseObserved = $startReturned
  }
}

function Assert-FormalLineage {
  param(
    [Parameter(Mandatory = $true)][object]$Journal,
    [Parameter(Mandatory = $true)][object]$FormalScope,
    [Parameter(Mandatory = $true)][object]$FormalApproval,
    [Parameter(Mandatory = $true)][object]$DiscoveryReceipt,
    [Parameter(Mandatory = $true)][string]$DiscoveryKeySha256,
    [Parameter(Mandatory = $true)][string]$ReaderSessionRefSha256
  )

  $discovery = $Journal.phases.Discovery
  $predecessor = $discovery.binding
  if ($ReaderSessionRefSha256 -cnotmatch "^[0-9A-F]{64}$") {
    throw "FORMAL_READER_SESSION_BINDING_INVALID"
  }
  $formal = New-ScopeJournalBinding -Scope $FormalScope -Approval $FormalApproval
  $formal.readerSessionRefSha256 = $ReaderSessionRefSha256
  if (
    [string]$DiscoveryReceipt.schema_version -cne "dxm.real-dxm-path-b.save1-discovery-receipt.v1" -or
    [string]$DiscoveryReceipt.discovery_receipt_sha256 -cne [string]$discovery.discoveryReceiptSha256 -or
    [string]$DiscoveryReceipt.discovery_key_sha256 -cne $DiscoveryKeySha256 -or
    [string]$DiscoveryReceipt.scope_sha256 -cne [string]$predecessor.scopeSha256 -or
    [string]$formal.scopeSha256 -ceq [string]$predecessor.scopeSha256 -or
    [string]$formal.taskRefSha256 -ceq [string]$predecessor.taskRefSha256 -or
    [string]$formal.snapshotRefSha256 -ceq [string]$predecessor.snapshotRefSha256 -or
    [string]$formal.snapshotSha256 -ceq [string]$predecessor.snapshotSha256 -or
    [string]$formal.nonceSha256 -ceq [string]$predecessor.nonceSha256 -or
    [string]$formal.approvalSha256 -ceq [string]$predecessor.approvalSha256 -or
    [string]$formal.accountIdentitySha256 -cne [string]$predecessor.accountIdentitySha256 -or
    [string]$formal.shopIdentitySha256 -cne [string]$predecessor.shopIdentitySha256 -or
    [string]$formal.gitIdentitySha256 -cne [string]$predecessor.gitIdentitySha256 -or
    [string]$formal.worktreeIdentitySha256 -cne [string]$predecessor.worktreeIdentitySha256 -or
    [string]$formal.runtimeIdentitySha256 -cne [string]$predecessor.runtimeIdentitySha256 -or
    [string]$formal.browserSessionIdSha256 -cne [string]$predecessor.browserSessionIdSha256 -or
    [string]$formal.readerSessionRefSha256 -cne [string]$predecessor.readerSessionRefSha256 -or
    [string]$formal.l2EvidenceFingerprint -cne [string]$predecessor.l2EvidenceFingerprint -or
    [string]$formal.orderedProductIdsSha256 -cne [string]$predecessor.orderedProductIdsSha256
  ) {
    throw "FORMAL_FRESH_SCOPE_LINEAGE_INVALID"
  }
  try {
    $formalIssuedAt = [DateTimeOffset]::Parse([string]$FormalScope.issuedAt, [Globalization.CultureInfo]::InvariantCulture)
    $formalApprovedAt = [DateTimeOffset]::Parse([string]$FormalApproval.approvedAt, [Globalization.CultureInfo]::InvariantCulture)
    $discoveryEndedAt = [DateTimeOffset]::Parse([string]$discovery.endedAt, [Globalization.CultureInfo]::InvariantCulture)
  } catch {
    throw "FORMAL_LINEAGE_TIME_INVALID"
  }
  if ($formalIssuedAt -le $discoveryEndedAt -or $formalApprovedAt -le $discoveryEndedAt) {
    throw "FORMAL_SCOPE_OR_APPROVAL_NOT_FRESH"
  }
  return $formal
}

function Assert-FreshFormalPreparedScope {
  param(
    [Parameter(Mandatory = $true)][object]$FormalScope,
    [Parameter(Mandatory = $true)][object]$PredecessorBinding,
    [Parameter(Mandatory = $true)][string]$DiscoveryEndedAt,
    [Parameter(Mandatory = $true)][string]$ReaderSessionRef
  )

  $formal = New-ScopeJournalBinding -Scope $FormalScope -ReaderSessionRef $ReaderSessionRef
  if (
    [string]$formal.scopeSha256 -ceq [string]$PredecessorBinding.scopeSha256 -or
    [string]$formal.taskRefSha256 -ceq [string]$PredecessorBinding.taskRefSha256 -or
    [string]$formal.snapshotRefSha256 -ceq [string]$PredecessorBinding.snapshotRefSha256 -or
    [string]$formal.snapshotSha256 -ceq [string]$PredecessorBinding.snapshotSha256 -or
    [string]$formal.nonceSha256 -ceq [string]$PredecessorBinding.nonceSha256 -or
    [string]$formal.accountIdentitySha256 -cne [string]$PredecessorBinding.accountIdentitySha256 -or
    [string]$formal.shopIdentitySha256 -cne [string]$PredecessorBinding.shopIdentitySha256 -or
    [string]$formal.gitIdentitySha256 -cne [string]$PredecessorBinding.gitIdentitySha256 -or
    [string]$formal.worktreeIdentitySha256 -cne [string]$PredecessorBinding.worktreeIdentitySha256 -or
    [string]$formal.runtimeIdentitySha256 -cne [string]$PredecessorBinding.runtimeIdentitySha256 -or
    [string]$formal.browserSessionIdSha256 -cne [string]$PredecessorBinding.browserSessionIdSha256 -or
    [string]$formal.readerSessionRefSha256 -cne [string]$PredecessorBinding.readerSessionRefSha256 -or
    [string]$formal.l2EvidenceFingerprint -cne [string]$PredecessorBinding.l2EvidenceFingerprint -or
    [string]$formal.orderedProductIdsSha256 -cne [string]$PredecessorBinding.orderedProductIdsSha256
  ) {
    throw "PREPARE_FORMAL_SCOPE_NOT_FRESH"
  }
  try {
    $issuedAt = [DateTimeOffset]::Parse([string]$FormalScope.issuedAt, [Globalization.CultureInfo]::InvariantCulture)
    $sealedAt = [DateTimeOffset]::Parse($DiscoveryEndedAt, [Globalization.CultureInfo]::InvariantCulture)
  } catch {
    throw "PREPARE_FORMAL_LINEAGE_TIME_INVALID"
  }
  if ($issuedAt -le $sealedAt) { throw "PREPARE_FORMAL_SCOPE_NOT_POST_DISCOVERY" }
}

function Get-FormalPrepareLineage {
  param(
    [Parameter(Mandatory = $true)][string]$JournalPath,
    [Parameter(Mandatory = $true)][string]$ReceiptPath,
    [Parameter(Mandatory = $true)][string]$DiscoveryKeyValue
  )

  Assert-DiscoveryKey -Value $DiscoveryKeyValue
  $journal = Read-AttemptJournal -Path $JournalPath
  if (
    $null -eq $journal -or
    $journal.unknownObserved -eq $true -or
    $journal.phases.Shadow.status -ne "complete" -or
    $journal.phases.Discovery.status -ne "complete" -or
    $null -ne $journal.phases.PSObject.Properties["Formal"]
  ) {
    throw "FORMAL_PREPARE_JOURNAL_NOT_ELIGIBLE"
  }
  $keySha256 = Get-RawTextSha256 -Value $DiscoveryKeyValue
  if ([string]$journal.phases.Discovery.discoveryKeySha256 -cne $keySha256) {
    throw "FORMAL_PREPARE_DISCOVERY_KEY_INVALID"
  }
  $receipt = Read-JsonFile -Path $ReceiptPath -Label "DiscoveryReceiptFile"
  $receiptFileHash = (Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToUpperInvariant()
  $receiptFileSize = (Get-Item -LiteralPath $ReceiptPath).Length
  if (
    $receiptFileHash -cne [string]$journal.phases.Discovery.receiptFileSha256 -or
    [int64]$receiptFileSize -ne [int64]$journal.phases.Discovery.receiptFileSize -or
    [string]$receipt.discovery_key_sha256 -cne $keySha256 -or
    [string]$receipt.scope_sha256 -cne [string]$journal.phases.Discovery.binding.scopeSha256 -or
    [string]$receipt.discovery_receipt_sha256 -cne [string]$journal.phases.Discovery.discoveryReceiptSha256
  ) {
    throw "FORMAL_PREPARE_DISCOVERY_RECEIPT_INVALID"
  }
  $predecessorProjection = New-DiscoveryReceiptScopeProjection -Receipt $receipt
  $liveRecovery = Get-DiscoveryRecovery -DiscoveryKeySha256 $keySha256
  $liveReceipt = Assert-DiscoveryRecoveryEnvelope -Recovery $liveRecovery -Scope $predecessorProjection -DiscoveryKeySha256 $keySha256 -RequireSealed
  if (
    [string]$liveReceipt.discovery_receipt_sha256 -cne [string]$receipt.discovery_receipt_sha256 -or
    [string]$liveReceipt.first_save_intent_handshake_sha256 -cne [string]$receipt.first_save_intent_handshake_sha256 -or
    [string]$liveReceipt.unpublished_action_result_sha256 -cne [string]$receipt.unpublished_action_result_sha256
  ) {
    throw "FORMAL_PREPARE_DISCOVERY_PERSISTENCE_DRIFT"
  }
  return [ordered]@{
    predecessorScopeSha256 = [string]$receipt.scope_sha256
    discoveryReceiptSha256 = [string]$receipt.discovery_receipt_sha256
    predecessorBinding = $journal.phases.Discovery.binding
    discoveryEndedAt = [string]$journal.phases.Discovery.endedAt
    readerSessionRefSha256 = [string]$journal.phases.Discovery.binding.readerSessionRefSha256
  }
}

function Invoke-FormalPhase {
  param(
    [object]$Scope,
    [object]$Approval,
    [string]$ExportPath,
    [string]$RecordPath,
    [string]$PredecessorScopeSha256,
    [string]$DiscoveryReceiptSha256
  )

  if (
    $PredecessorScopeSha256 -cnotmatch "^[0-9A-F]{64}$" -or
    $DiscoveryReceiptSha256 -cnotmatch "^[0-9A-F]{64}$" -or
    $PredecessorScopeSha256 -ceq [string]$Scope.scopeSha256
  ) {
    throw "FORMAL_LINEAGE_INPUT_INVALID"
  }

  $taskId = [int]$Scope.snapshot.taskId
  $taskProjection = Invoke-PublicJson -Method GET -Path "/api/tasks/$taskId/scope-prepare" -TimeoutSec 120
  $scopeIds = @($Scope.orderedProducts | ForEach-Object { [string]$_.productId })
  $taskIds = @($taskProjection.orderedProductIds | ForEach-Object { [string]$_ })
  if (
    [int]$taskProjection.taskId -ne $taskId -or
    $taskProjection.taskStatus -ne "draft" -or
    $taskProjection.path -ne "B" -or
    [int]$taskProjection.snapshotId -ne [int]$Scope.snapshot.snapshotId -or
    [string]$taskProjection.snapshotSha256 -cne [string]$Scope.snapshot.snapshotSha256 -or
    ($taskIds -join ",") -cne ($scopeIds -join ",")
  ) {
    throw "FORMAL_FRESH_TASK_BINDING_DRIFT"
  }
  $beforeStart = Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath
  Assert-ZeroTaskAcceptance -Export $beforeStart -Label "FORMAL_BEFORE_START"

  $terminal = @("completed", "partial_success", "failed", "needs_manual_review", "cancelled", "stopped")
  $acceptedPostStates = @("running", "pause_requested", "paused", "stop_requested") + $terminal
  try {
  $startBody = [ordered]@{
    approved_by = [string]$Approval.approvedBy
    confirmation = "CONFIRM_DXM_SAVE_ONLY"
    real_dxm_write_scope = $Scope
    real_dxm_write_approval = $Approval
    predecessor_scope_sha256 = $PredecessorScopeSha256
    discovery_receipt_sha256 = $DiscoveryReceiptSha256
  }
  try {
    $script:FormalPostSent = $true
    $started = Invoke-PublicJson -Method POST -Path "/api/tasks/$taskId/approve-and-start" -Body $startBody -TimeoutSec 180
    if (
      $started.ok -ne $true -or
      [int]$started.taskId -ne $taskId -or
      $started.authorizationConsumed -ne $true -or
      $started.status -ne "running"
    ) {
      throw "FORMAL_ATOMIC_START_RESPONSE_INVALID"
    }
  } catch {
    $startFailure = $_
    if ($startFailure.Exception.Data["HttpNotAcceptedProven"] -eq $true) {
      $script:FormalNotAcceptedProven = $true
      throw $startFailure
    }

    $formalRecoveryFailure = $null
    try {
      $recoveredTask = Invoke-PublicJson -Method GET -Path "/api/tasks/$taskId" -TimeoutSec 60
      if (Test-TaskUnknown -Task $recoveredTask) {
        throw "FORMAL_UNKNOWN_OBSERVED"
      }
      if ([string]$recoveredTask.status -eq "draft") {
        $recoveryProjection = Invoke-PublicJson -Method GET -Path "/api/tasks/$taskId/scope-prepare" -TimeoutSec 120
        $recoveryIds = @($recoveryProjection.orderedProductIds | ForEach-Object { [string]$_ })
        if (
          [int]$recoveryProjection.taskId -ne $taskId -or
          $recoveryProjection.taskStatus -ne "draft" -or
          $recoveryProjection.path -ne "B" -or
          [int]$recoveryProjection.snapshotId -ne [int]$Scope.snapshot.snapshotId -or
          [string]$recoveryProjection.snapshotSha256 -cne [string]$Scope.snapshot.snapshotSha256 -or
          ($recoveryIds -join ",") -cne ($scopeIds -join ",")
        ) {
          throw "FORMAL_START_RECOVERY_DRAFT_BINDING_INVALID"
        }
        $recoveryExport = Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath
        Assert-ZeroTaskAcceptance -Export $recoveryExport -Label "FORMAL_START_RECOVERY"
        $script:FormalNotAcceptedProven = $true
      } elseif ([string]$recoveredTask.status -notin $acceptedPostStates) {
        throw "FORMAL_START_RECOVERY_STATE_INVALID"
      }
    } catch {
      $formalRecoveryFailure = $_
    }
    if ($script:FormalNotAcceptedProven) {
      throw $startFailure
    }
    if ($null -ne $formalRecoveryFailure) {
      throw "FORMAL_START_OUTCOME_UNKNOWN"
    }
    # Non-draft recovery proves acceptance, not a clean response.  The
    # one-shot contract therefore seals UNKNOWN instead of continuing.
    throw "FORMAL_START_OUTCOME_UNKNOWN"
  }

  $deadline = [DateTimeOffset]::UtcNow.AddSeconds($PollTimeoutSeconds)
  $task = $null
  while ([DateTimeOffset]::UtcNow -lt $deadline) {
    $task = Invoke-PublicJson -Method GET -Path "/api/tasks/$taskId" -TimeoutSec 60
    if (Test-TaskUnknown -Task $task) {
      Stop-TaskAndConfirm -TaskId $taskId
      Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
      throw "FORMAL_UNKNOWN_OBSERVED"
    }
    if ([string]$task.status -in $terminal) { break }
    Start-Sleep -Seconds $PollIntervalSeconds
  }

  if ($null -eq $task -or [string]$task.status -notin $terminal) {
    Stop-TaskAndConfirm -TaskId $taskId
    Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
    throw "FORMAL_POLL_TIMEOUT"
  }
  if ([string]$task.status -ne "completed") {
    Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
    throw "FORMAL_TASK_NOT_COMPLETED"
  }

  Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null
  & $PythonPath "${PSScriptRoot}\report\generate_v1_acceptance_record.py" --input $ExportPath --output $RecordPath
  if ($LASTEXITCODE -ne 0) { throw "FORMAL_ACCEPTANCE_NON_READY" }
  $script:FormalCompleted = $true
  } catch {
    $failure = $_
    $stopFailure = $null
    if ($script:FormalPostSent -and -not $script:FormalNotAcceptedProven) {
      try { Stop-TaskAndConfirm -TaskId $taskId } catch { $stopFailure = $_ }
      try { Export-PublicAcceptance -TaskId $taskId -OutputPath $ExportPath | Out-Null } catch { }
    }
    if ($null -ne $stopFailure -and $failure.Exception.Message -notmatch "UNKNOWN") { throw $stopFailure }
    throw $failure
  }
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BaseUrl = Resolve-LoopbackBaseUrl -Value $BaseUrl
if ($PollIntervalSeconds -lt 1 -or $PollTimeoutSeconds -lt 1) { throw "Polling values must be positive." }
try {
  Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/health") -Method GET -TimeoutSec 10 | Out-Null
} catch {
  throw "Backend health check failed before the one-shot phase was consumed."
}

if ($Phase -eq "Prepare") {
  $scopePath = Resolve-ExternalOutputFile -Path $ScopeFile -Label "DXM_REAL_SAVE_SCOPE_FILE" -RepositoryRoot $repoRoot
  $preparePath = Resolve-ExternalFile -Path $PrepareRequestFile -Label "PrepareRequestFile" -RepositoryRoot $repoRoot
  $prepareRequest = Read-JsonFile -Path $preparePath -Label "PrepareRequestFile"
  Assert-PrepareRequest -Request $prepareRequest
  if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
    $EvidenceDirectory = Join-Path (Split-Path -Parent $scopePath) "dxm-path-b-system-evidence"
  }
  $evidenceRoot = Resolve-ExternalDirectory -Path $EvidenceDirectory -RepositoryRoot $repoRoot
  if ([string]::IsNullOrWhiteSpace($AttemptJournalFile)) {
    $AttemptJournalFile = Join-Path $evidenceRoot "real-dxm-path-b-attempt-journal-v2.json"
  }
  $prepareJournalPath = Resolve-ExternalOutputFile -Path $AttemptJournalFile -Label "AttemptJournalFile" -RepositoryRoot $repoRoot
  $preparePredecessorScopeSha256 = ""
  $prepareDiscoveryReceiptSha256 = ""
  $preparePredecessorBinding = $null
  $prepareDiscoveryEndedAt = ""
  $prepareReaderSessionRefSha256 = ""
  $formalPrepareRequested = (
    -not [string]::IsNullOrWhiteSpace($DiscoveryReceiptFile) -or
    -not [string]::IsNullOrWhiteSpace($DiscoveryKey)
  )
  if ($formalPrepareRequested) {
    if (
      [string]::IsNullOrWhiteSpace($DiscoveryReceiptFile) -or
      [string]::IsNullOrWhiteSpace($DiscoveryKey)
    ) {
      throw "FORMAL_PREPARE_RECEIPT_AND_KEY_REQUIRED"
    }
    $prepareReceiptPath = Resolve-ExternalFile -Path $DiscoveryReceiptFile -Label "DiscoveryReceiptFile" -RepositoryRoot $repoRoot
    $prepareLineage = Get-FormalPrepareLineage -JournalPath $prepareJournalPath -ReceiptPath $prepareReceiptPath -DiscoveryKeyValue $DiscoveryKey
    $preparePredecessorScopeSha256 = [string]$prepareLineage.predecessorScopeSha256
    $prepareDiscoveryReceiptSha256 = [string]$prepareLineage.discoveryReceiptSha256
    $preparePredecessorBinding = $prepareLineage.predecessorBinding
    $prepareDiscoveryEndedAt = [string]$prepareLineage.discoveryEndedAt
    $prepareReaderSessionRefSha256 = Get-TextSha256 -Label "readerSessionRef" -Value ([string]$prepareRequest.sessionRef)
    if (
      [string]::IsNullOrWhiteSpace([string]$prepareLineage.readerSessionRefSha256) -or
      $prepareReaderSessionRefSha256 -cne [string]$prepareLineage.readerSessionRefSha256
    ) {
      throw "FORMAL_PREPARE_READER_SESSION_DRIFT"
    }
  } else {
    $existingJournal = Read-AttemptJournal -Path $prepareJournalPath
    if ($null -ne $existingJournal -and $existingJournal.phases.Discovery.status -eq "complete") {
      throw "FORMAL_PREPARE_LINEAGE_INPUT_REQUIRED"
    }
  }
  $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")
  $tracePath = Join-Path $evidenceRoot "path-b-prepare-$stamp-trace.json"
  $prepareCompleted = $false
  $prepareBlockedCode = "UNEXPECTED_BLOCKER"
  $prepared = $null
  try {
    $prepared = Invoke-PreparePhase -Request $prepareRequest -ScopeOutputPath $scopePath -PredecessorScopeSha256 $preparePredecessorScopeSha256 -DiscoveryReceiptSha256 $prepareDiscoveryReceiptSha256 -PredecessorBinding $preparePredecessorBinding -DiscoveryEndedAt $prepareDiscoveryEndedAt -ReaderSessionRef ([string]$prepareRequest.sessionRef)
    if ($formalPrepareRequested) {
      Record-FormalPrepareJournalBinding -Path $prepareJournalPath -Scope $prepared.scope -ReaderSessionRef ([string]$prepareRequest.sessionRef) -PredecessorScopeSha256 $preparePredecessorScopeSha256 -DiscoveryReceiptSha256 $prepareDiscoveryReceiptSha256 | Out-Null
    }
    $prepareCompleted = $true
  } catch {
    if ($_.Exception.Message -match "^[A-Z0-9_]+$") { $prepareBlockedCode = $_.Exception.Message }
    throw
  } finally {
    Write-ExternalJson -Path $tracePath -Value ([ordered]@{
      schemaVersion = "real_dxm_path_b_system_trace.v1"
      phase = "Prepare"
      scopeSha256 = $(if ($null -ne $prepared) { [string]$prepared.scopeSha256 } else { $null })
      purpose = $(if ($formalPrepareRequested) { "formal" } else { "discovery" })
      predecessorScopeSha256 = $(if ($formalPrepareRequested) { $preparePredecessorScopeSha256 } else { $null })
      discoveryReceiptSha256 = $(if ($formalPrepareRequested) { $prepareDiscoveryReceiptSha256 } else { $null })
      attemptJournalFileSha256 = $(if (Test-Path -LiteralPath $prepareJournalPath -PathType Leaf) { (Get-FileHash -LiteralPath $prepareJournalPath -Algorithm SHA256).Hash.ToUpperInvariant() } else { $null })
      completed = $prepareCompleted
      blockers = $(if ($prepareCompleted) { @() } else { @($prepareBlockedCode) })
      calls = @($script:Trace)
      mutationAuthorizationCalls = @($script:Trace | Where-Object { $_.path -like "*/approve-and-start" }).Count
      publicPublishEndpointCalls = @($script:Trace | Where-Object { $_.path -match "(?i)/[^/?]*publish[^/?]*" }).Count
      publicPublishEndpointCallsEvidence = "driver_http_trace_only"
    })
  }
  $scopePrefix = ([string]$prepared.scopeSha256).Substring(0, 12)
  Write-Host "phase=Prepare status=completed scope=$scopePrefix"
  Write-Host "scopeFile=$scopePath"
  Write-Host "trace=$tracePath"
  return
}

$scopePath = Resolve-ExternalFile -Path $ScopeFile -Label "DXM_REAL_SAVE_SCOPE_FILE" -RepositoryRoot $repoRoot
$scope = Read-JsonFile -Path $scopePath -Label "DXM_REAL_SAVE_SCOPE_FILE"
Assert-ScopeContract -Scope $scope

if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
  $EvidenceDirectory = Join-Path (Split-Path -Parent $scopePath) "dxm-path-b-system-evidence"
}
$evidenceRoot = Resolve-ExternalDirectory -Path $EvidenceDirectory -RepositoryRoot $repoRoot
if ($Phase -eq "Formal") {
  if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $repoRoot "app\backend\.venv\Scripts\python.exe"
  }
  if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "PythonPath does not exist." }
}
$approval = $null
if ($Phase -in @("Discovery", "Formal")) {
  $approvalPath = Resolve-ExternalFile -Path $ApprovalFile -Label "ApprovalFile" -RepositoryRoot $repoRoot
  $approval = Read-JsonFile -Path $approvalPath -Label "ApprovalFile"
  Assert-ApprovalContract -Approval $approval -Scope $scope
}

$shadowRequest = $null
if ($Phase -eq "Shadow") {
  $shadowPath = Resolve-ExternalFile -Path $ShadowRequestFile -Label "ShadowRequestFile" -RepositoryRoot $repoRoot
  $shadowRequest = Read-JsonFile -Path $shadowPath -Label "ShadowRequestFile"
  Assert-ShadowRequest -Request $shadowRequest -Scope $scope
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")
$safeScopePrefix = ([string]$scope.scopeSha256).Substring(0, 12)
if ([string]::IsNullOrWhiteSpace($AttemptJournalFile)) {
  $AttemptJournalFile = Join-Path $evidenceRoot "real-dxm-path-b-attempt-journal-v2.json"
}
$journalPath = Resolve-ExternalOutputFile -Path $AttemptJournalFile -Label "AttemptJournalFile" -RepositoryRoot $repoRoot
$discoveryReceiptPath = $null
if ($Phase -in @("Discovery", "Formal")) {
  Assert-DiscoveryKey -Value $DiscoveryKey
  if ([string]::IsNullOrWhiteSpace($DiscoveryReceiptFile)) {
    if ($Phase -eq "Formal") {
      throw "DiscoveryReceiptFile is required for Formal."
    }
    $DiscoveryReceiptFile = Join-Path $evidenceRoot "path-b-discovery-$safeScopePrefix-receipt.json"
  }
  if ($Phase -eq "Discovery") {
    $discoveryReceiptPath = Resolve-ExternalOutputFile -Path $DiscoveryReceiptFile -Label "DiscoveryReceiptFile" -RepositoryRoot $repoRoot
    if (Test-Path -LiteralPath $discoveryReceiptPath) {
      throw "DISCOVERY_RECEIPT_FILE_ALREADY_EXISTS"
    }
  } else {
    $discoveryReceiptPath = Resolve-ExternalFile -Path $DiscoveryReceiptFile -Label "DiscoveryReceiptFile" -RepositoryRoot $repoRoot
  }
}

$artifactPrefix = "path-b-$($Phase.ToLowerInvariant())-$safeScopePrefix-$stamp"
$tracePath = Join-Path $evidenceRoot "$artifactPrefix-trace.json"
$exportPath = Join-Path $evidenceRoot "$artifactPrefix-acceptance-export.json"
$recordPath = Join-Path $evidenceRoot "$artifactPrefix-acceptance-record.json"

$binding = $(
  if ($Phase -eq "Shadow") {
    New-ScopeJournalBinding -Scope $scope -ReaderSessionRef ([string]$shadowRequest.sessionRef)
  } else {
    New-ScopeJournalBinding -Scope $scope -Approval $approval
  }
)
if ($Phase -in @("Discovery", "Formal")) {
  $bindingJournal = Read-AttemptJournal -Path $journalPath
  if ($null -eq $bindingJournal) {
    throw "$($Phase.ToUpperInvariant())_ATTEMPT_JOURNAL_MISSING"
  }
  if ($Phase -eq "Discovery") {
    $boundReaderSessionSha256 = [string]$bindingJournal.phases.Shadow.binding.readerSessionRefSha256
  } else {
    $formalPrepareProperty = $bindingJournal.PSObject.Properties["formalPrepare"]
    $boundReaderSessionSha256 = $(
      if ($null -ne $formalPrepareProperty) {
        [string]$formalPrepareProperty.Value.binding.readerSessionRefSha256
      } else {
        ""
      }
    )
  }
  if ($boundReaderSessionSha256 -cnotmatch "^[0-9A-F]{64}$") {
    throw "$($Phase.ToUpperInvariant())_READER_SESSION_BINDING_MISSING"
  }
  $binding.readerSessionRefSha256 = $boundReaderSessionSha256
}
$journal = Assert-PhasePrerequisites -Path $journalPath -PhaseName $Phase -Binding $binding
$discoveryReceipt = $null
$discoveryKeySha256 = $null
$predecessorScopeSha256 = $null
$discoveryReceiptSha256 = $null
if ($Phase -eq "Formal") {
  $discoveryKeySha256 = Get-RawTextSha256 -Value $DiscoveryKey
  if ([string]$journal.phases.Discovery.discoveryKeySha256 -cne $discoveryKeySha256) {
    throw "FORMAL_DISCOVERY_KEY_LINEAGE_INVALID"
  }
  $discoveryReceipt = Read-JsonFile -Path $discoveryReceiptPath -Label "DiscoveryReceiptFile"
  $receiptFileHash = (Get-FileHash -LiteralPath $discoveryReceiptPath -Algorithm SHA256).Hash.ToUpperInvariant()
  $receiptFileSize = (Get-Item -LiteralPath $discoveryReceiptPath).Length
  if (
    $receiptFileHash -cne [string]$journal.phases.Discovery.receiptFileSha256 -or
    [int64]$receiptFileSize -ne [int64]$journal.phases.Discovery.receiptFileSize
  ) {
    throw "FORMAL_DISCOVERY_RECEIPT_FILE_DRIFT"
  }
  $binding = Assert-FormalLineage -Journal $journal -FormalScope $scope -FormalApproval $approval -DiscoveryReceipt $discoveryReceipt -DiscoveryKeySha256 $discoveryKeySha256 -ReaderSessionRefSha256 ([string]$journal.formalPrepare.binding.readerSessionRefSha256)
  $predecessorScopeSha256 = [string]$discoveryReceipt.scope_sha256
  $discoveryReceiptSha256 = [string]$discoveryReceipt.discovery_receipt_sha256
  $predecessorProjection = New-DiscoveryReceiptScopeProjection -Receipt $discoveryReceipt
  $liveRecovery = Get-DiscoveryRecovery -DiscoveryKeySha256 $discoveryKeySha256
  $liveReceipt = Assert-DiscoveryRecoveryEnvelope -Recovery $liveRecovery -Scope $predecessorProjection -DiscoveryKeySha256 $discoveryKeySha256 -RequireSealed
  if (
    [string]$liveReceipt.discovery_receipt_sha256 -cne $discoveryReceiptSha256 -or
    [string]$liveReceipt.first_save_intent_handshake_sha256 -cne [string]$discoveryReceipt.first_save_intent_handshake_sha256 -or
    [string]$liveReceipt.unpublished_action_result_sha256 -cne [string]$discoveryReceipt.unpublished_action_result_sha256
  ) {
    throw "FORMAL_DISCOVERY_RECEIPT_PERSISTENCE_DRIFT"
  }
  Assert-FormalSave1ReadbackContinuity -ReceiptPath $discoveryReceiptPath -ScopePath $scopePath -PythonExecutable $PythonPath
}

Update-AttemptJournal -Path $journalPath -PhaseName $Phase -Action "start" -Binding $binding
$phaseCompleted = $false
$blockedCode = "UNEXPECTED_BLOCKER"
$phaseDetails = [ordered]@{}
try {
  switch ($Phase) {
    "Shadow" {
      Invoke-ShadowPhase -Scope $scope -Request $shadowRequest -ExportPath $exportPath
    }
    "Discovery" {
      $phaseDetails = Invoke-DiscoveryPhase -Scope $scope -Approval $approval -DiscoveryKeyValue $DiscoveryKey -ReceiptPath $discoveryReceiptPath -ExportPath $exportPath
    }
    "Formal" {
      Invoke-FormalPhase -Scope $scope -Approval $approval -ExportPath $exportPath -RecordPath $recordPath -PredecessorScopeSha256 $predecessorScopeSha256 -DiscoveryReceiptSha256 $discoveryReceiptSha256
      $phaseDetails = [ordered]@{
        predecessorScopeSha256 = $predecessorScopeSha256
        discoveryReceiptSha256 = $discoveryReceiptSha256
      }
    }
  }
  $phaseCompleted = $true
  Update-AttemptJournal -Path $journalPath -PhaseName $Phase -Action "complete" -Binding $binding -Details $phaseDetails
} catch {
  if ($_.Exception.Message -match "^[A-Z0-9_]+$") { $blockedCode = $_.Exception.Message }
  if ($_.Exception.Message -match "(?i)UNKNOWN" -and $blockedCode -notmatch "UNKNOWN") {
    $blockedCode = "$($Phase.ToUpperInvariant())_OUTCOME_UNKNOWN"
  }
  if ($Phase -eq "Discovery" -and $script:DiscoveryPostSent -and -not $script:DiscoveryNotAcceptedProven) {
    $blockedCode = "DISCOVERY_POST_SENT_OUTCOME_UNKNOWN"
  }
  if ($Phase -eq "Formal" -and $script:FormalPostSent -and -not $script:FormalNotAcceptedProven) {
    $blockedCode = "FORMAL_POST_SENT_OUTCOME_UNKNOWN"
  }
  Update-AttemptJournal -Path $journalPath -PhaseName $Phase -Action "blocked" -Binding $binding -ReasonCode $blockedCode
  throw
} finally {
  $publicPublishEndpointCalls = @(
    $script:Trace | Where-Object { $_.path -match "(?i)/[^/?]*publish[^/?]*" }
  ).Count
  Write-ExternalJson -Path $tracePath -Value ([ordered]@{
    schemaVersion = "real_dxm_path_b_system_trace.v1"
    phase = $Phase
    scopeSha256 = [string]$scope.scopeSha256
    attemptJournalSchemaVersion = "real_dxm_path_b_attempts.v2"
    attemptJournalFileSha256 = $(if (Test-Path -LiteralPath $journalPath -PathType Leaf) { (Get-FileHash -LiteralPath $journalPath -Algorithm SHA256).Hash.ToUpperInvariant() } else { $null })
    attemptJournalFileSize = $(if (Test-Path -LiteralPath $journalPath -PathType Leaf) { [int64](Get-Item -LiteralPath $journalPath).Length } else { $null })
    predecessorScopeSha256 = $predecessorScopeSha256
    discoveryReceiptSha256 = $discoveryReceiptSha256
    taskRefSha256 = Get-TextSha256 -Label "task" -Value ([string]$scope.snapshot.taskId)
    completed = $phaseCompleted
    blockers = $(if ($phaseCompleted) { @() } else { @($blockedCode) })
    calls = @($script:Trace)
    mutationAuthorizationCalls = @($script:Trace | Where-Object { $_.path -like "*/approve-and-start" }).Count
    publicPublishEndpointCalls = $publicPublishEndpointCalls
    publicPublishEndpointCallsEvidence = "driver_http_trace_only"
  })
}

Write-Host "phase=$Phase status=completed scope=$safeScopePrefix taskRef=$((Get-TextSha256 -Label 'task' -Value ([string]$scope.snapshot.taskId)).Substring(0, 12))"
Write-Host "attemptJournal=$journalPath"
Write-Host "trace=$tracePath"
if ($Phase -eq "Discovery") { Write-Host "discoveryReceipt=$discoveryReceiptPath" }
if (Test-Path -LiteralPath $exportPath) { Write-Host "acceptanceExport=$exportPath" }
if (Test-Path -LiteralPath $recordPath) { Write-Host "acceptanceRecord=$recordPath" }
