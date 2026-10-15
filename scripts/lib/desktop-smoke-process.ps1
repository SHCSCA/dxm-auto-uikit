function Stop-DesktopSmokeProcess {
  param([object]$Process, [string]$Label)
  if ($null -eq $Process) { return }
  $OwnedProcessId = 0
  try {
    $OwnedProcessId = $Process.Id
    # 只清理本次持有的进程对象，不按名称或安装路径枚举其他实例。
    if (!$Process.HasExited) {
      $Process.Kill()
      if (!$Process.WaitForExit(5000)) { throw 'Owned process did not exit after cleanup' }
    }
  } catch {
    $Record = [ordered]@{
      schema = 'dxm.log.v1'; timestamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'")
      level = 'ERROR'; component = 'desktop-package-verifier'; event = 'process_cleanup_failed'
      fields = @{ label = $Label; pid = $OwnedProcessId; exception_type = $_.Exception.GetType().Name; exception_message = $_.Exception.Message }
    }
    [Console]::Error.WriteLine(($Record | ConvertTo-Json -Depth 4 -Compress))
    throw
  }
}
