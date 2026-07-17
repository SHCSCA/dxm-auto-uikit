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

foreach ($functionName in @(
  "Get-L3EvidenceReadiness",
  "Get-TwoStageAcceptanceReadiness",
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
    blocked_by_two_stage_acceptance = $false
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
  two_stage_acceptance = [pscustomobject]@{
    schema = "wrong.v1"
    passed = "true"
    status = "passed"
    claim_task_id = 7
    save_task_id = 8
    claimed_product_id = 9
    missing_codes = @("should-block")
    checks = [pscustomobject]@{}
  }
}
$malformedL3 = Get-L3EvidenceReadiness -WorkspaceSnapshot $malformedSafetyWorkspace
$malformedTwoStage = Get-TwoStageAcceptanceReadiness -WorkspaceSnapshot $malformedSafetyWorkspace
if ($malformedL3.ready -ne $false -or $malformedTwoStage.ready -ne $false) {
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
    blocked_by_two_stage_acceptance = $false
    two_stage_missing_codes = @()
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
  two_stage_acceptance = [pscustomobject]@{
    schema = "dxm_two_stage_acceptance.v1"
    passed = $true
    status = "passed"
    claim_task_id = 7
    save_task_id = 8
    claimed_product_id = 9
    missing_codes = @()
    state_violation_codes = @()
    checks = [pscustomobject]@{
      claim_task_present = $true
      claim_completed = $true
      save_task_completed = $true
      claimed_product_present = $true
      claim_provenance_valid = $true
      single_save_claim_snapshot_valid = $true
      claim_product_matches = $true
      draft_box_verified = $true
      single_save_linked_to_claim = $true
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
$validTwoStage = Get-TwoStageAcceptanceReadiness -WorkspaceSnapshot $validSafetyWorkspace
if ($validL3.ready -ne $true -or $validTwoStage.ready -ne $true) {
  throw "strict valid delivery and two-stage contracts must remain READY"
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
    -TwoStageAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
  $expectedWriteReadiness = if ($case.expected) { "READY" } else { "BLOCKED" }
  if ($writeReadiness -ne $expectedWriteReadiness) {
    throw "$($case.name): expected write readiness $expectedWriteReadiness, got $writeReadiness"
  }
  $blockedReason = Get-RealDxmWriteBlockedReason `
    -L2Gate ([pscustomobject]@{ status = "passed" }) `
    -L3Gate ([pscustomobject]@{ status = "passed" }) `
    -L3EvidenceReadiness ([pscustomobject]@{ ready = $true }) `
    -StateConsistencyReadiness $actual `
    -TwoStageAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
  if ($case.expected -and $blockedReason -ne "") {
    throw "$($case.name): valid state must not have a blocked reason"
  }
  if (!$case.expected -and $blockedReason -notmatch "State consistency is not passed") {
    throw "$($case.name): invalid state must have a state-consistency blocked reason"
  }
}

$blockedByTwoStage = Get-RealDxmWriteReadiness `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -TwoStageAcceptanceReadiness ([pscustomobject]@{ ready = $false; missing = @("two-stage acceptance not passed") })
if ($blockedByTwoStage -ne "BLOCKED") {
  throw "two-stage acceptance missing: expected write readiness BLOCKED, got $blockedByTwoStage"
}

$twoStageBlockedDecision = Get-RealDxmWriteDecision `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -TwoStageAcceptanceReadiness ([pscustomobject]@{ ready = $false; missing = @("two-stage acceptance not passed") })
if (
  $twoStageBlockedDecision.readiness -ne "BLOCKED" -or
  $twoStageBlockedDecision.controlledSingleSaveReady -ne $false -or
  $twoStageBlockedDecision.realDxmMutationAllowed -ne $false -or
  $twoStageBlockedDecision.realDxmMutationScope -ne "none" -or
  $twoStageBlockedDecision.blockedReason -notmatch "Two-stage acceptance is not passed"
) {
  throw "two-stage acceptance missing: READY, controlled single-save, and mutation must all remain blocked"
}

$readyDecision = Get-RealDxmWriteDecision `
  -L2Gate ([pscustomobject]@{ status = "passed" }) `
  -L3Gate ([pscustomobject]@{ status = "passed" }) `
  -L3EvidenceReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -StateConsistencyReadiness ([pscustomobject]@{ ready = $true; missing = @() }) `
  -TwoStageAcceptanceReadiness ([pscustomobject]@{ ready = $true; missing = @() })
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
  -TwoStageAcceptanceMatchesExpected $true `
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
  -TwoStageAcceptanceMatchesExpected $true `
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
