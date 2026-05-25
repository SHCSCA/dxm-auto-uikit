param(
  [string]$Url = "http://127.0.0.1:5173",
  [string]$OutDir = "outputs/browser-checks",
  [int]$Port = 9230
)

$ErrorActionPreference = "Stop"

function Find-Chrome {
  $candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe"
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      return $candidate
    }
  }
  throw "Chrome or Edge was not found."
}

function Find-Node {
  $bundled = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
  if (Test-Path -LiteralPath $bundled) {
    return $bundled
  }
  $node = Get-Command node -ErrorAction SilentlyContinue
  if ($node) {
    return $node.Source
  }
  throw "Node.js was not found."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$absoluteOutDir = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $root $OutDir }
New-Item -ItemType Directory -Path $absoluteOutDir -Force | Out-Null

$chrome = Find-Chrome
$node = Find-Node
$userData = Join-Path $env:TEMP ("dxm-qa-chrome-" + [guid]::NewGuid().ToString("N"))
$scriptPath = Join-Path $env:TEMP ("dxm-qa-browser-check-" + [guid]::NewGuid().ToString("N") + ".mjs")
New-Item -ItemType Directory -Path $userData | Out-Null

$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
  $candidate = $Port + 1
  while ($candidate -lt ($Port + 50)) {
    if (!(Get-NetTCPConnection -LocalPort $candidate -ErrorAction SilentlyContinue)) {
      Write-Host "Port $Port is already in use; using $candidate instead."
      $Port = $candidate
      break
    }
    $candidate += 1
  }
  if ((Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue)) {
    throw "No available Chrome debugging port found near $Port."
  }
}

$chromeArgs = @(
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  "--user-data-dir=$userData",
  "--remote-debugging-port=$Port",
  "--window-size=1440,1100",
  "about:blank"
)

$proc = Start-Process -FilePath $chrome -ArgumentList $chromeArgs -PassThru -WindowStyle Hidden
try {
  $deadline = (Get-Date).AddSeconds(15)
  do {
    Start-Sleep -Milliseconds 300
    try {
      Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/list" -TimeoutSec 2 | Out-Null
      break
    } catch {
      if ((Get-Date) -ge $deadline) {
        throw "Chrome DevTools endpoint did not start."
      }
    }
  } while ($true)

  $nodeScript = @"
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
const port = $Port;
const targetUrl = '$Url';
const rootDir = '$($root.Replace("\", "/"))';
const outDir = '$($absoluteOutDir.Replace("\", "/"))';
const qaScriptPath = '$($PSCommandPath.Replace("\", "/"))';
const versionInfo = await (await fetch('http://127.0.0.1:' + port + '/json/version')).json();
if (typeof WebSocket !== 'function') {
  throw new Error('This QA check requires Node.js with global WebSocket support. Use Node 22+ or the bundled Codex Node runtime.');
}
fs.mkdirSync(outDir, { recursive: true });
const tabs = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
const tab = tabs.find(t => t.type === 'page') || tabs[0];
const ws = new WebSocket(tab.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const consoleEvents = [];
const consoleErrors = [];
const networkEvents = [];
ws.onmessage = event => {
  const msg = JSON.parse(event.data);
  if (msg.method === 'Runtime.consoleAPICalled') {
    const text = msg.params.args.map(a => a.value || a.description || '').join(' ');
    const entry = {
      type: msg.params.type,
      text,
      timestamp: msg.params.timestamp || Date.now(),
    };
    consoleEvents.push(entry);
    if (msg.params.type === 'error') {
      consoleErrors.push(text);
    }
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    const text = msg.params.exceptionDetails.text || 'exception';
    consoleEvents.push({ type: 'exception', text, timestamp: Date.now() });
    consoleErrors.push(text);
  }
  if (msg.method === 'Network.requestWillBeSent') {
    networkEvents.push({
      type: 'request',
      requestId: msg.params.requestId,
      url: msg.params.request.url,
      method: msg.params.request.method,
      timestamp: msg.params.timestamp,
    });
  }
  if (msg.method === 'Network.responseReceived') {
    networkEvents.push({
      type: 'response',
      requestId: msg.params.requestId,
      url: msg.params.response.url,
      status: msg.params.response.status,
      mimeType: msg.params.response.mimeType,
      timestamp: msg.params.timestamp,
    });
  }
  if (msg.method === 'Network.loadingFailed') {
    networkEvents.push({
      type: 'failed',
      requestId: msg.params.requestId,
      errorText: msg.params.errorText,
      timestamp: msg.params.timestamp,
    });
  }
  if (msg.id && pending.has(msg.id)) {
    const p = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
  }
};
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
function send(method, params = {}) {
  const msgId = ++id;
  ws.send(JSON.stringify({ id: msgId, method, params }));
  return new Promise((resolve, reject) => pending.set(msgId, { resolve, reject }));
}
async function evalValue(expr) {
  const res = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return res.result.value;
}
async function bodyText() {
  return await evalValue('document.body.innerText.replace(/\\\\s+/g, " ")');
}
async function clickText(label) {
  return await evalValue('(() => { const els = [...document.querySelectorAll("button,a,[role=\\"button\\"],nav *")]; const el = els.find(e => (e.innerText || e.textContent || "").trim() === ' + JSON.stringify(label) + '); if (el) { el.click(); return true; } return false; })()');
}
async function screenshot(name) {
  const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const path = outDir + '/' + name + '.png';
  fs.writeFileSync(path, Buffer.from(res.data, 'base64'));
  return path;
}
await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');
await send('Page.navigate', { url: targetUrl });
await new Promise(r => setTimeout(r, 1800));
const text = {
  tasks: '\u4efb\u52a1\u4e2d\u5fc3',
  console: '\u6267\u884c\u63a7\u5236\u53f0',
  hero: '\u534a\u6258\u7ba1\u4fdd\u5b58\u4ea4\u4ed8\u5de5\u4f5c\u53f0',
  appName: '\u5e97\u5c0f\u79d8\u534a\u6258\u7ba1\u6267\u884c\u5668',
  localWrite: '\u521b\u5efa\u6f14\u793a\u6279\u6b21\uff08\u5199\u5165\u672c\u5730\uff09',
  readonlyDiag: '\u67e5\u770b\u53ea\u8bfb\u8bca\u65ad',
  evidenceGap: '\u67e5\u770b\u8bc1\u636e\u7f3a\u53e3',
  forbiddenStart: '\u7981\u6b62\u542f\u52a8',
  readonly: '\u53ea\u8bfb\u8bca\u65ad',
  noSaveStart: '\u4e0d\u542f\u52a8\u4fdd\u5b58',
  noBrowser: '\u5c1a\u672a\u6253\u5f00\u771f\u5b9e\u8bca\u65ad\u6d4f\u89c8\u5668',
  noFakeEvidence: '\u4e0d\u628a\u5546\u54c1\u4fe1\u606f\u4f2a\u88c5\u6210\u6d4f\u89c8\u5668\u8bc1\u636e',
  oldSaveOnly: '\u53ea\u4fdd\u5b58\u4e0d\u53d1\u5e03',
  oldWaitSave: '\u7b49\u5f85\u4fdd\u5b58\u6838\u9a8c',
  oldVisibleBrowser: '\u6253\u5f00\u53ef\u89c1\u6d4f\u89c8\u5668',
  oldAutomation: '\u65c1\u89c2\u81ea\u52a8\u5316',
  fakePlaceholder: '\u8bca\u65ad\u5360\u4f4d',
};
const initialText = await bodyText();
await clickText(text.tasks);
await new Promise(r => setTimeout(r, 700));
const taskText = await bodyText();
const taskShot = await screenshot('qa-task-center');
await clickText(text.console);
await new Promise(r => setTimeout(r, 700));
const consoleText = await bodyText();
const consoleShot = await screenshot('qa-execution-console');
function sha256(path) {
  return crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
}
function runGit(args) {
  try {
    return execFileSync('git', args, { cwd: rootDir, encoding: 'utf8' }).trim();
  } catch {
    return null;
  }
}
const screenshotHashes = Object.fromEntries([taskShot, consoleShot].map(path => [path, sha256(path)]));
const consolePath = outDir + '/qa-console.jsonl';
fs.writeFileSync(
  consolePath,
  consoleEvents.map(event => JSON.stringify(event)).join('\n') + (consoleEvents.length ? '\n' : '')
);
const networkPath = outDir + '/qa-network.json';
fs.writeFileSync(networkPath, JSON.stringify(networkEvents, null, 2));
const allowedHostname = new URL(targetUrl).hostname;
const failedNetworkEvents = networkEvents.filter(event => event.type === 'failed');
const badNetworkResponses = networkEvents.filter(event => event.type === 'response' && (event.status < 200 || event.status >= 400));
const unexpectedNetworkMethods = networkEvents.filter(event => event.type === 'request' && event.method !== 'GET');
const unexpectedNetworkHosts = networkEvents.filter(event => {
  if (!event.url || !(event.type === 'request' || event.type === 'response')) return false;
  try {
    const parsed = new URL(event.url);
    return parsed.protocol.startsWith('http') && parsed.hostname !== allowedHostname;
  } catch {
    return true;
  }
});
const result = {
  checkedAt: new Date().toISOString(),
  url: targetUrl,
  ok: true,
  assertions: {
    initialLoaded: initialText.includes(text.hero) || initialText.includes(text.appName),
    localWriteCopy: taskText.includes(text.localWrite),
    taskRecoveryActions: taskText.includes(text.readonlyDiag) && taskText.includes(text.evidenceGap),
    taskStartBlockedCopy: taskText.includes(text.forbiddenStart),
    consoleReadonlyCopy: consoleText.includes(text.readonly) && consoleText.includes(text.noSaveStart),
    consoleNoFakeBrowser: consoleText.includes(text.noBrowser) && consoleText.includes(text.noFakeEvidence),
    consoleNoFakePlaceholder: !(consoleText + ' ' + taskText).includes(text.fakePlaceholder),
    noOldActionCopy: !(consoleText + ' ' + taskText).includes(text.oldSaveOnly)
      && !(consoleText + ' ' + taskText).includes(text.oldWaitSave)
      && !(consoleText + ' ' + taskText).includes(text.oldVisibleBrowser)
      && !(consoleText + ' ' + taskText).includes(text.oldAutomation)
      && !(consoleText + ' ' + taskText).includes('SAVE_ONLY'),
    noConsoleErrors: consoleErrors.length === 0,
    networkNoFailures: failedNetworkEvents.length === 0,
    networkHttpOk: badNetworkResponses.length === 0,
    networkGetOnly: unexpectedNetworkMethods.length === 0,
    networkLocalOnly: unexpectedNetworkHosts.length === 0,
    sidecarsWritten: fs.existsSync(consolePath) && fs.existsSync(networkPath),
  },
  consoleErrors,
  networkSummary: {
    eventCount: networkEvents.length,
    failedCount: failedNetworkEvents.length,
    badResponseCount: badNetworkResponses.length,
    unexpectedMethodCount: unexpectedNetworkMethods.length,
    unexpectedHostCount: unexpectedNetworkHosts.length,
    allowedHostname,
  },
  screenshots: [taskShot, consoleShot],
  screenshotHashes,
  sidecars: {
    console: consolePath,
    network: networkPath,
  },
  sidecarHashes: {
    [consolePath]: sha256(consolePath),
    [networkPath]: sha256(networkPath),
  },
  environment: {
    node: process.version,
    platform: process.platform,
    os: os.type() + ' ' + os.release(),
    browser: versionInfo.Browser || versionInfo['User-Agent'] || 'unknown',
    protocolVersion: versionInfo['Protocol-Version'] || null,
    chromeDebugPort: port,
    viewport: '1440x1100',
  },
  manifest: {
    command: 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\\\qa-browser-check.ps1',
    scriptPath: qaScriptPath,
    scriptSha256: sha256(qaScriptPath),
    gitHead: runGit(['rev-parse', 'HEAD']),
    gitStatusShort: runGit(['status', '--short']),
    backendLogPath: rootDir + '/data/backend.log',
    frontendLogPath: rootDir + '/data/frontend.log',
  },
};
result.ok = Object.values(result.assertions).every(Boolean);
const jsonPath = outDir + '/qa-browser-check.json';
fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));
const summaryPath = outDir + '/qa-browser-check.md';
const assertionLines = Object.entries(result.assertions).map(([key, value]) => '- ' + (value ? 'PASS' : 'FAIL') + ' ' + key);
const screenshotLines = result.screenshots.map(path => '- ' + path + ' sha256=' + result.screenshotHashes[path]);
const sidecarLines = Object.entries(result.sidecars).map(([key, path]) => '- ' + key + ': ' + path + ' sha256=' + result.sidecarHashes[path]);
const consoleLines = result.consoleErrors.length ? result.consoleErrors.map(error => '- ' + error) : ['- none'];
fs.writeFileSync(summaryPath, [
  '# Workbench Browser QA',
  '',
  '- Checked at: ' + result.checkedAt,
  '- URL: ' + result.url,
  '- Result: ' + (result.ok ? 'PASS' : 'FAIL'),
  '',
  '## Assertions',
  ...assertionLines,
  '',
  '## Screenshots',
  ...screenshotLines,
  '',
  '## Sidecars',
  ...sidecarLines,
  '',
  '## Console Errors',
  ...consoleLines,
  '',
].join('\n'));
console.log(JSON.stringify(result, null, 2));
ws.close();
if (!result.ok) process.exit(1);
"@
  [System.IO.File]::WriteAllText($scriptPath, $nodeScript, [System.Text.Encoding]::UTF8)
  & $node $scriptPath
} finally {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
    Start-Sleep -Milliseconds 800
  }
  if (Test-Path -LiteralPath $userData) {
    try {
      Remove-Item -LiteralPath $userData -Recurse -Force -ErrorAction Stop
    } catch {
      Write-Warning "Could not remove temp Chrome profile: $userData"
    }
  }
  if (Test-Path -LiteralPath $scriptPath) {
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
  }
}
