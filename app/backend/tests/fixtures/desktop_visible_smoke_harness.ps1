$script:Launches = @()
$script:Owned = [pscustomobject]@{ Id = 4321; HasExited = $false; ExitCode = 0; Killed = $false }
$script:Other = [pscustomobject]@{ Id = 9999; Killed = $false }
$script:Owned | Add-Member ScriptMethod WaitForExit {
  param($Milliseconds)
  if ($script:Mode -eq 'timeout' -and !$this.Killed) { return $false }
  if ($script:Mode -eq 'cleanup-failure') { return $true }
  $this.HasExited = $true
  return $true
}
$script:Owned | Add-Member ScriptMethod Kill {
  if ($script:Mode -eq 'cleanup-failure') { throw 'test-cleanup-denied' }
  $this.Killed = $true
  $this.HasExited = $true
}

function Start-Process {
  param($FilePath, $WorkingDirectory, $ArgumentList, $WindowStyle, [switch]$PassThru)
  $script:Launches += [pscustomobject]@{
    filePath = $FilePath; workingDirectory = $WorkingDirectory
    arguments = @($ArgumentList); windowStyle = [string]$WindowStyle
  }
  if ($script:Mode -eq 'start-failure') { throw 'test-launch-denied' }
  if ($script:Mode -eq 'nonzero') { $script:Owned.ExitCode = 7 }
  if ($WindowStyle -eq 'Normal') {
    if ($script:Mode -ne 'missing') {
      $Result = @{ ok = $true; windowVisible = ($script:Mode -ne 'invisible'); backendPort = 8123; apiBase = 'http://127.0.0.1:8123' }
      [System.IO.File]::WriteAllText($VisiblePath, ($Result | ConvertTo-Json -Compress))
    }
  }
  return $script:Owned
}

function Write-HarnessResult {
  param($Verification, [string]$ErrorText)
  [pscustomobject]@{
    verification = $Verification; error = $ErrorText; launches = @($script:Launches)
    ownedKilled = $script:Owned.Killed; otherKilled = $script:Other.Killed
  } | ConvertTo-Json -Depth 8 -Compress
}
