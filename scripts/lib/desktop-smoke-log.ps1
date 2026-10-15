function Read-DesktopSmokeLogText {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $Messages = [System.Collections.Generic.List[string]]::new()
  foreach ($Line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
    if ([string]::IsNullOrWhiteSpace($Line)) { continue }
    if (!$Line.TrimStart().StartsWith('{')) {
      $Messages.Add($Line)
      continue
    }
    try {
      $Record = $Line | ConvertFrom-Json -ErrorAction Stop
    } catch {
      throw "Desktop smoke JSONL record is invalid: $Path"
    }
    if ($Record.schema -ne 'dxm.log.v1' -or $Record.component -ne 'desktop') {
      throw "Desktop smoke JSONL schema or component is invalid: $Path"
    }
    if ($Record.fields.message -isnot [string]) {
      throw "Desktop smoke JSONL message is missing: $Path"
    }
    # 先解码 JSON 字符串，再复用原有路径与启动事实断言，避免反斜杠转义造成误判。
    $Messages.Add($Record.fields.message)
  }
  return $Messages -join "`n"
}
