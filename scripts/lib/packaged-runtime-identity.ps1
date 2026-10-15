function ConvertTo-IdentityJsonString {
  param([string]$Value)
  $Buffer = [System.Text.StringBuilder]::new('"')
  foreach ($Character in $Value.ToCharArray()) {
    switch ([int]$Character) {
      34 { [void]$Buffer.Append('\"') }
      92 { [void]$Buffer.Append('\\') }
      8 { [void]$Buffer.Append('\b') }
      9 { [void]$Buffer.Append('\t') }
      10 { [void]$Buffer.Append('\n') }
      12 { [void]$Buffer.Append('\f') }
      13 { [void]$Buffer.Append('\r') }
      default {
        if ([int]$Character -lt 32) {
          [void]$Buffer.Append(('\u{0:x4}' -f [int]$Character))
        } else {
          [void]$Buffer.Append($Character)
        }
      }
    }
  }
  [void]$Buffer.Append('"')
  return $Buffer.ToString()
}

function ConvertTo-IdentityCanonicalJson {
  param([object]$Payload)
  $Values = @{}
  if ($Payload -is [System.Collections.IDictionary]) {
    foreach ($Key in $Payload.Keys) { $Values[[string]$Key] = $Payload[$Key] }
  } else {
    foreach ($Property in $Payload.PSObject.Properties) { $Values[$Property.Name] = $Property.Value }
  }
  [string[]]$Names = @($Values.Keys)
  [Array]::Sort($Names, [System.StringComparer]::Ordinal)
  $Pairs = foreach ($Name in $Names) {
    $Value = $Values[$Name]
    if ($null -eq $Value) { $JsonValue = 'null' }
    elseif ($Value -is [string]) { $JsonValue = ConvertTo-IdentityJsonString -Value $Value }
    elseif ($Value -is [bool]) { $JsonValue = $Value.ToString().ToLowerInvariant() }
    elseif ($Value -is [int] -or $Value -is [long]) {
      $JsonValue = $Value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    } else { throw "Identity JSON field must be scalar: $Name" }
    (ConvertTo-IdentityJsonString -Value $Name) + ':' + $JsonValue
  }
  return '{' + ($Pairs -join ',') + '}'
}

function Get-PackagedIdentityFingerprint {
  param([object]$Payload)
  $Unsigned = [ordered]@{}
  foreach ($Property in $Payload.PSObject.Properties) {
    if ($Property.Name -cne 'fingerprint') { $Unsigned[$Property.Name] = $Property.Value }
  }
  $Sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes((ConvertTo-IdentityCanonicalJson -Payload $Unsigned))
    return [BitConverter]::ToString($Sha.ComputeHash($Bytes)).Replace('-', '')
  } finally { $Sha.Dispose() }
}

function Assert-IdentityFieldSet {
  param([object]$Payload, [string[]]$Names, [string]$Label)
  if ($null -eq $Payload -or $Payload -isnot [PSCustomObject]) { throw "$Label must be an object" }
  $ActualNames = @($Payload.PSObject.Properties.Name)
  if ($ActualNames.Count -ne $Names.Count -or @($ActualNames | Where-Object { $Names -cnotcontains $_ }).Count) {
    throw "$Label fields mismatch"
  }
}

function ConvertFrom-IdentityTimestamp {
  param([object]$Value, [string]$Label)
  $Parsed = [DateTimeOffset]::MinValue
  $Style = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
  if ($Value -isnot [string] -or ![DateTimeOffset]::TryParseExact(
      $Value, "yyyy-MM-dd'T'HH:mm:ss.fff'Z'", [System.Globalization.CultureInfo]::InvariantCulture, $Style, [ref]$Parsed)) {
    throw "$Label must use canonical UTC milliseconds"
  }
  return $Parsed
}

function Read-PackagedBuildManifest {
  param([string]$Path, [string]$ExpectedPackageVersion)
  $Manifest = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
  Assert-IdentityFieldSet -Payload $Manifest -Label 'Packaged build manifest' -Names @(
    'schemaVersion', 'gitHead', 'gitDirty', 'buildId', 'packageVersion', 'builtAt', 'fingerprint')
  if ($Manifest.schemaVersion -cne 'dxm.desktop.build.v1' -or $Manifest.gitDirty -isnot [bool]) {
    throw 'Packaged build manifest schema or gitDirty is invalid'
  }
  foreach ($Name in @('gitHead', 'buildId', 'packageVersion')) {
    $Value = $Manifest.$Name
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value) -or $Value -cne $Value.Trim()) {
      throw "Packaged build manifest field is invalid: $Name"
    }
  }
  $null = ConvertFrom-IdentityTimestamp -Value $Manifest.builtAt -Label 'Packaged build manifest builtAt'
  if ($Manifest.packageVersion -cne $ExpectedPackageVersion) { throw 'Packaged build manifest packageVersion mismatch' }
  if ($Manifest.fingerprint -isnot [string] -or $Manifest.fingerprint.ToUpperInvariant() -cne (Get-PackagedIdentityFingerprint -Payload $Manifest)) {
    throw 'Packaged build manifest fingerprint mismatch'
  }
  return $Manifest
}

function Set-PackagedProbeBuildIdentity {
  param([object]$Environment, [object]$Manifest, [string]$InstanceId, [string]$WorkflowProfileDir)
  # 清除调用者身份，独立探针只能声明包内构建事实和本次新进程。
  $IdentityKeys = @('DXM_BUILD_MANIFEST_JSON', 'DXM_PACKAGE_SHA256', 'DXM_BACKEND_INSTANCE_ID', 'DXM_WORKFLOW_PROFILE_DIR')
  foreach ($Key in @($Environment.Keys)) {
    if ($IdentityKeys -contains ([string]$Key).ToUpperInvariant()) { $Environment.Remove([string]$Key) }
  }
  $Environment['DXM_BUILD_MANIFEST_JSON'] = ConvertTo-IdentityCanonicalJson -Payload $Manifest
  $Environment['DXM_BACKEND_INSTANCE_ID'] = $InstanceId
  $Environment['DXM_WORKFLOW_PROFILE_DIR'] = $WorkflowProfileDir
}

function Assert-PackagedProbeRuntimeIdentity {
  param(
    [object]$Identity, [object]$Manifest, [string]$InstanceId, [int]$BackendProcessId,
    [string]$DataDir, [string]$WorkflowProfileDir, [string]$ResourceRoot, [DateTimeOffset]$NotBefore
  )
  Assert-IdentityFieldSet -Payload $Identity -Label 'Packaged runtime identity' -Names @(
    'schemaVersion', 'instanceId', 'gitHead', 'gitDirty', 'buildId', 'packageVersion', 'packageSha256',
    'backendPid', 'browserAgentPid', 'browserExecutionModel', 'dataDir', 'workflowProfileDir', 'resourceRoot', 'startedAt', 'fingerprint')
  $Expected = [ordered]@{
    schemaVersion = 'dxm.runtime.identity.v1'; instanceId = $InstanceId
    gitHead = $Manifest.gitHead; buildId = $Manifest.buildId; packageVersion = $Manifest.packageVersion
    browserExecutionModel = 'in_process_thread'; dataDir = $DataDir
    workflowProfileDir = $WorkflowProfileDir; resourceRoot = $ResourceRoot
  }
  foreach ($Name in $Expected.Keys) {
    if ($Identity.$Name -isnot [string] -or $Identity.$Name -cne $Expected[$Name]) {
      throw "Packaged runtime identity mismatch: $Name"
    }
  }
  if ($Identity.gitDirty -isnot [bool] -or $Identity.gitDirty -ne $Manifest.gitDirty) {
    throw 'Packaged runtime identity mismatch: gitDirty'
  }
  foreach ($Name in @('backendPid', 'browserAgentPid')) {
    $Value = $Identity.$Name
    if (($Value -isnot [int] -and $Value -isnot [long]) -or $Value -ne $BackendProcessId -or $BackendProcessId -le 0) {
      throw "Packaged runtime identity mismatch: $Name"
    }
  }
  if ($null -ne $Identity.packageSha256) { throw 'Packaged probe cannot inherit packageSha256' }
  $StartedAt = ConvertFrom-IdentityTimestamp -Value $Identity.startedAt -Label 'Packaged runtime identity startedAt'
  if ($StartedAt -lt $NotBefore.AddMilliseconds(-1) -or $StartedAt -gt [DateTimeOffset]::UtcNow) {
    throw 'Packaged runtime identity startedAt is outside this probe lifetime'
  }
  if ($Identity.fingerprint -isnot [string] -or $Identity.fingerprint -cne (Get-PackagedIdentityFingerprint -Payload $Identity)) {
    throw 'Packaged runtime identity fingerprint mismatch'
  }
}
