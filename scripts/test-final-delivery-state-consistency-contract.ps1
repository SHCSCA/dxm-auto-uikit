param(
  [string]$SourceScript = (Join-Path $PSScriptRoot "final-delivery-check.ps1")
)

$ErrorActionPreference = "Stop"

$tokens = $null
$parseErrors = $null
$source = Get-Content -LiteralPath $SourceScript -Raw -Encoding UTF8
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
  $source,
  [ref]$tokens,
  [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
  throw "final-delivery-check.ps1 does not parse: $($parseErrors[0].Message)"
}

foreach ($removedToken in @(
  "two_stage_acceptance",
  "twoStageAcceptance",
  "ExpectedRealDxmTwoStageEndToEnd",
  "claim_task_id",
  "claimed_product_id"
)) {
  if ($source.Contains($removedToken)) {
    throw "removed acceptance token remains in final-delivery-check.ps1: $removedToken"
  }
}

foreach ($functionName in @(
  "Get-L3EvidenceReadiness",
  "Get-SingleSaveAcceptanceReadiness",
  "Get-StateConsistencyReadiness",
  "Get-RealDxmWriteReadiness",
  "Get-RealDxmWriteBlockedReason",
  "Get-RealDxmWriteDecision",
  "Test-FinalDeliveryOverallOk"
)) {
  $functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $functionName
  }, $true)
  if (!$functionAst) {
    throw "$functionName was not found"
  }
  Invoke-Expression $functionAst.Extent.Text
}

$malformedSafetyWorkspace = [pscustomobject]@{
  delivery_readiness = [pscustomobject]@{
    schema = "dxm_delivery_readiness.v1"
    ready = "true"
    task_completed = 1
    blocked_by_task_status = $false
    has_l3_evidence = "true"
    total_job_count = 1
    complete_job_count = 1
    blocked_by_state_consistency = $false
    blocked_by_single_save_acceptance = $false
    jobs = @([pscustomobject]@{
      job_id = 9
      ready = "true"
      has_save_result = "true"
      has_unpublished_proof = 1
      has_network_or_har_save_response = "true"
      has_save_evidence_file = 1
      has_unpublished_evidence_file = "true"
      missing = @()
    })
  }
  single_save_acceptance = [pscustomobject]@{
    schema = "wrong.v1"
    passed = "true"
    status = "passed"
    save_task_id = 8
    product_id = 9
    product_box_snapshot_error = "drifted"
    save_report_count = 0
    evidence_count = 1
    missing_codes = @("should-block")
    checks = [pscustomobject]@{}
  }
}
$malformedL3 = Get-L3EvidenceReadiness -WorkspaceSnapshot $malformedSafetyWorkspace
$malformedSingleSave = Get-SingleSaveAcceptanceReadiness -WorkspaceSnapshot $malformedSafetyWorkspace
if ($malformedL3.ready -ne $false -or $malformedSingleSave.ready -ne $false) {
  throw "string/integer booleans, wrong schema, and non-empty missing codes must fail closed"
}

$validSafetyWorkspace = [pscustomobject]@{
  delivery_readiness = [pscustomobject]@{
    schema = "dxm_delivery_readiness.v1"
    ready = $true
    task_completed = $true
    blocked_by_task_status = $false
    has_l3_evidence = $true
    total_job_count = 1
    complete_job_count = 1
    blocked_by_state_consistency = $false
    state_violation_codes = @()
    blocked_by_single_save_acceptance = $false
    single_save_missing_codes = @()
    jobs = @([pscustomobject]@{
      job_id = 9
      ready = $true
      has_save_result = $true
      has_unpublished_proof = $true
      has_network_or_har_save_response = $true
      has_save_evidence_file = $true
      has_unpublished_evidence_file = $true
      missing = @()
    })
  }
  single_save_acceptance = [pscustomobject]@{
    schema = "dxm_single_save_acceptance.v1"
    passed = $true
    status = "passed"
    user_message = "single save passed"
    save_task_id = 8
    product_id = 9
    product_box_snapshot_error = $null
    save_report_count = 1
    evidence_count = 2
    missing_codes = @()
    state_violation_codes = @()
    checks = [pscustomobject]@{
      save_task_mode_valid = $true
      save_task_completed = $true
      product_present = $true
      product_box_snapshot_valid = $true
      single_save_target_bound = $true
      manual_approval_consumed = $true
      save_success = $true
      unpublished_proof = $true
      save_evidence_integrity = $true
      unpublished_evidence_integrity = $true
      publish_guard_safe = $true
      state_consistent = $true
    }
  }
}
$validL3 = Get-L3EvidenceReadiness -WorkspaceSnapshot $validSafetyWorkspace
$validSingleSave = Get-SingleSaveAcceptanceReadiness -WorkspaceSnapshot $validSafetyWorkspace
if ($validL3.ready -ne $true -or $validSingleSave.ready -ne $true) {
  throw "strict valid delivery and single-save contracts must remain READY"
}

$invalidSnapshotWorkspace = $validSafetyWorkspace | ConvertTo-Json -Depth 12 | ConvertFrom-Json
$invalidSnapshotWorkspace.single_save_acceptance.product_box_snapshot_error = "snapshot drifted"
$invalidSnapshot = Get-SingleSaveAcceptanceReadiness -WorkspaceSnapshot $invalidSnapshotWorkspace
if ($invalidSnapshot.ready -ne $false -or $invalidSnapshot.missing -notcontains "single_save_acceptance.product_box_snapshot_error must be null") {
  throw "product-box snapshot errors must fail closed"
}

$invalidEvidenceCountWorkspace = $validSafetyWorkspace | ConvertTo-Json -Depth 12 | ConvertFrom-Json
$invalidEvidenceCountWorkspace.single_save_acceptance.evidence_count = 1
$invalidEvidenceCount = Get-SingleSaveAcceptanceReadiness -WorkspaceSnapshot $invalidEvidenceCountWorkspace
if ($invalidEvidenceCount.ready -ne $false) {
  throw "single-save acceptance requires separate save and unpublished evidence records"
}

function New-WorkspaceSnapshot {
  param([object]$StateConsistency)
  return [pscustomobject]@{ state_consistency = $StateConsistency }
}

$validState = [pscustomobject]@{
  schema = "dxm_state_consistency.v1"
  consistent = $true
  violation_codes = @()
  violations = @()
  audited_task_ids = @(41, 42)
}

$cases = @(
  [pscustomobject]@{ name = "valid"; workspace = (New-WorkspaceSnapshot $validState); expected = $true },
  [pscustomobject]@{ name = "missing state"; workspace = [pscustomobject]@{}; expected = $false },
  [pscustomobject]@{
    name = "wrong schema"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "wrong.v1"; consistent = $true; violation_codes = @(); violations = @(); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "string true"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = "true"; violation_codes = @(); violations = @(); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "integer true"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = 1; violation_codes = @(); violations = @(); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "violation details present"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = @(); violations = @(@{ code = "STATE_X" }); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "violation codes present"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = @("STATE_X"); violations = @(); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "audited task ids missing"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = @(); violations = @(); audited_task_ids = @()
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "violations null"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = @(); violations = $null; audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "violation codes null"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = $null; violations = @(); audited_task_ids = @(1)
    }))
    expected = $false
  },
  [pscustomobject]@{
    name = "audited task ids scalar"
    workspace = (New-WorkspaceSnapshot ([pscustomobject]@{
      schema = "dxm_state_consistency.v1"; consistent = $true; violation_codes = @(); violations = @(); audited_task_ids = 1
    }))
    expected = $false
  }
)

foreach ($case in $cases) {
  $actual = Get-StateConsistencyReadiness -WorkspaceSnapshot $case.workspace
  if ($actual.ready -isnot [bool]) {
    throw "$($case.name): ready must be Boolean"
  }
  if ($actual.ready -ne $case.expected) {
    throw "$($case.name): expected ready=$($case.expected), got $($actual.ready); missing=$($actual.missing -join '; ')"
  }
  $writeReadiness = Get-RealDxmWriteReadiness `
    -L2Gate ([pscustomobject]@{ status = "passed" }) `
    -L3Gate ([pscustomobject]@{ status = "passed" }) `
    -L3EvidenceReadiness ([pscustomobject]@{ ready = $true }) `
    -StateConsistencyReadiness $actual `
    -SingleSaveAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
  $expectedWriteReadiness = if ($case.expected) { "READY" } else { "BLOCKED" }
  if ($writeReadiness -ne $expectedWriteReadiness) {
    throw "$($case.name): expected write readiness $expectedWriteReadiness, got $writeReadiness"
  }
  $blockedReason = Get-RealDxmWriteBlockedReason `
    -L2Gate ([pscustomobject]@{ status = "passed" }) `
    -L3Gate ([pscustomobject]@{ status = "passed" }) `
    -L3EvidenceReadiness ([pscustomobject]@{ ready = $true }) `
    -StateConsistencyReadiness $actual `
    -SingleSaveAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
  if ($case.expected -and $blockedReason -ne "") {
    throw "$($case.name): valid state must not have a blocked reason"
  }
  if (!$case.expected -and $blockedReason -notmatch "State consistency is not passed") {
    throw "$($case.name): invalid state must have a state-consistency blocked reason"
  }
}

$blockedBySingleSave = Get-RealDxmWriteReadiness `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -SingleSaveAcceptanceReadiness ([pscustomobject]@{ ready = $false; missing = @("single-save acceptance not passed") })
if ($blockedBySingleSave -ne "BLOCKED") {
  throw "single-save acceptance missing: expected write readiness BLOCKED, got $blockedBySingleSave"
}

$singleSaveBlockedDecision = Get-RealDxmWriteDecision `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -SingleSaveAcceptanceReadiness ([pscustomobject]@{ ready = $false; missing = @("single-save acceptance not passed") })
if (
  $singleSaveBlockedDecision.readiness -ne "BLOCKED" -or
  $singleSaveBlockedDecision.controlledSingleSaveReady -ne $false -or
  $singleSaveBlockedDecision.realDxmMutationAllowed -ne $false -or
  $singleSaveBlockedDecision.realDxmMutationScope -ne "none" -or
  $singleSaveBlockedDecision.blockedReason -notmatch "Single-save acceptance is not passed"
) {
  throw "single-save acceptance missing: READY, controlled single-save, and mutation must all remain blocked"
}

$readyDecision = Get-RealDxmWriteDecision `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -SingleSaveAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
if (
  $readyDecision.readiness -ne "READY" -or
  $readyDecision.controlledSingleSaveReady -ne $true -or
  $readyDecision.realDxmMutationAllowed -ne $true -or
  $readyDecision.realDxmMutationScope -ne "controlled_single_save_only" -or
  $readyDecision.blockedReason -ne ""
) {
  throw "all write gates passed: expected READY controlled single-save decision"
}

$overallWithInvalidState = Test-FinalDeliveryOverallOk `
  -LocalWorkbenchOk $true `
  -GateEvidenceOk $true `
  -RealDxmWriteReadinessMatchesExpected $true `
  -SingleSaveAcceptanceMatchesExpected $true `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $false; missing = @("STATE_X") }) `
  -RequireCleanSourcePackage $false `
  -SourcePackageCheck "NOT_REQUIRED"
if ($overallWithInvalidState -ne $false) {
  throw "invalid state consistency must fail overall check even when expected BLOCKED matches"
}

$overallWithValidState = Test-FinalDeliveryOverallOk `
  -LocalWorkbenchOk $true `
  -GateEvidenceOk $true `
  -RealDxmWriteReadinessMatchesExpected $true `
  -SingleSaveAcceptanceMatchesExpected $true `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -RequireCleanSourcePackage $false `
  -SourcePackageCheck "NOT_REQUIRED"
if ($overallWithValidState -ne $true) {
  throw "valid state consistency should allow the otherwise-passing overall check"
}

$decisionCallCount = @($ast.FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq "Get-RealDxmWriteDecision"
}, $true)).Count
if ($decisionCallCount -ne 2) {
  throw "provisional and final paths must both use Get-RealDxmWriteDecision; found $decisionCallCount calls"
}

$overallCallCount = @($ast.FindAll({
  param($node)
  $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq "Test-FinalDeliveryOverallOk"
}, $true)).Count
if ($overallCallCount -ne 3) {
  throw "initial final decision and both post-report QA recalculations must use Test-FinalDeliveryOverallOk; found $overallCallCount calls"
}

Write-Output "state consistency contract: $($cases.Count)/$($cases.Count) passed"
