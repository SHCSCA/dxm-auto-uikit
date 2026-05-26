param(
  [string]$Url = "http://127.0.0.1:5173",
  [string]$OutDir = "outputs/browser-checks",
  [int]$Port = 9230,
  [switch]$ReportOnlyFinal,
  [switch]$AllowMissingPostFinalQa
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
const apiBase = new URL(targetUrl).searchParams.get('apiBase') || new URL(targetUrl).origin;
const rootDir = '$($root.Replace("\", "/"))';
const outDir = '$($absoluteOutDir.Replace("\", "/"))';
const qaScriptPath = '$($PSCommandPath.Replace("\", "/"))';
const reportOnlyFinal = $($ReportOnlyFinal.IsPresent.ToString().ToLowerInvariant());
const allowMissingPostFinalQa = $($AllowMissingPostFinalQa.IsPresent.ToString().ToLowerInvariant());
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
async function waitForBodyIncludes(fragments, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let text = await bodyText();
  while (Date.now() < deadline) {
    if (fragments.every(fragment => !fragment || text.includes(fragment))) {
      return text;
    }
    await new Promise(r => setTimeout(r, 200));
    text = await bodyText();
  }
  return text;
}
async function clickText(label) {
  return await evalValue('(() => { const els = [...document.querySelectorAll("button,a,[role=\\"button\\"],nav *")]; const el = els.find(e => (e.innerText || e.textContent || "").trim() === ' + JSON.stringify(label) + '); if (el) { el.click(); return true; } return false; })()');
}
async function clickSelector(selector) {
  return await evalValue('(() => { const el = document.querySelector(' + JSON.stringify(selector) + '); if (el) { el.click(); return true; } return false; })()');
}
function summarizeTask(task) {
  return task ? {
    id: task.id,
    mode: task.mode,
    status: task.status,
    totalJobs: task.total_jobs,
    completedJobs: task.completed_jobs,
    failedJobs: task.failed_jobs,
  } : null;
}
async function fetchJson(path) {
  const response = await fetch(apiBase + path);
  if (!response.ok) throw new Error('GET ' + path + ' failed with ' + response.status);
  return await response.json();
}
async function postJson(path, body) {
  const response = await fetch(apiBase + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const rawBody = await response.text();
  let parsedBody = null;
  try {
    parsedBody = JSON.parse(rawBody);
  } catch {
    parsedBody = rawBody;
  }
  if (!response.ok) {
    throw new Error('POST ' + path + ' failed with ' + response.status + ': ' + String(rawBody).slice(0, 240));
  }
  return parsedBody;
}
async function ensureRealMutationTask() {
  const existingStores = await fetchJson('/api/stores');
  const dangKangStore = Array.isArray(existingStores)
    ? existingStores.find(store => store?.name === 'Dang Kang')
    : null;
  const store = dangKangStore
    ? dangKangStore
    : await postJson('/api/stores/connect', { name: 'Dang Kang', platform: 'AliExpress' });
  let products = await fetchJson('/api/products');
  if (!Array.isArray(products)) products = [];
  if (!products.length) {
    products = await postJson('/api/products/import', { rows: [{
      title: 'QA guarded product',
      source: 'qa',
      category_name: 'QA_CATEGORY',
      price: 7.01,
      currency: 'USD',
      sku_count: 1,
      image_count: 1,
      image: 'qa-product.jpg',
    }] });
  }
  return await postJson('/api/tasks', {
    name: 'QA guarded real mutation task',
    store_id: store.id,
    mode: 'single_save',
    publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
    product_ids: products.map(item => item.id),
    claim_mark: 'QA_CLAIM',
    payload: {
      store_name: store.name,
      category_name: products[0]?.category_name ?? 'QA_CATEGORY',
      image: products[0]?.image ?? 'qa-product.jpg',
    },
  });
}
async function screenshot(name) {
  const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const path = outDir + '/' + name + '.png';
  fs.writeFileSync(path, Buffer.from(res.data, 'base64'));
  return path;
}
const realMutationTaskForBlockedChecks = reportOnlyFinal ? null : await ensureRealMutationTask();
await send('Page.enable');
await send('Runtime.enable');
await send('Network.enable');
await send('Page.navigate', { url: targetUrl });
await new Promise(r => setTimeout(r, 1800));
const text = {
  tasks: '\u4efb\u52a1\u4e2d\u5fc3',
  overview: '\u603b\u89c8',
  console: '\u6267\u884c\u63a7\u5236\u53f0',
  reports: '\u62a5\u544a\u4e2d\u5fc3',
  hero: '\u672c\u5730\u5b89\u5168\u8bca\u65ad\u5de5\u4f5c\u53f0',
  localWorkbenchDeliverable: '\u672c\u5730\u5de5\u4f5c\u53f0\u53ef\u4ea4\u4ed8',
  expectedSafetyBlocked: '\u771f\u5b9e\u5199\u5165\u9884\u671f BLOCKED',
  realWriteGateFailed: '\u771f\u5b9e\u5199\u5165\u95e8\u7981\u672a\u901a\u8fc7',
  appName: '\u5e97\u5c0f\u79d8\u534a\u6258\u7ba1\u6267\u884c\u5668',
  localWrite: '\u521b\u5efa\u6f14\u793a\u6279\u6b21\uff08\u5199\u5165\u672c\u5730\uff09',
  readonlyDiag: '\u67e5\u770b\u53ea\u8bfb\u8bca\u65ad',
  l2BlockHelp: '\u67e5\u770b L2 \u963b\u65ad\u8bf4\u660e',
  evidenceGap: '\u67e5\u770b\u8bc1\u636e\u7f3a\u53e3',
  forbiddenStart: '\u7981\u6b62\u542f\u52a8',
  readonly: '\u53ea\u8bfb\u8bca\u65ad',
  noSaveStart: '\u4e0d\u542f\u52a8\u4fdd\u5b58',
  noBrowser: '\u5c1a\u672a\u6253\u5f00\u771f\u5b9e\u8bca\u65ad\u6d4f\u89c8\u5668',
  noFakeEvidence: '\u4e0d\u628a\u5546\u54c1\u4fe1\u606f\u4f2a\u88c5\u6210\u6d4f\u89c8\u5668\u8bc1\u636e',
  finalCheck: '\u6700\u8fd1\u4ea4\u4ed8\u81ea\u68c0',
  expectedBlocked: '\u771f\u5b9e\u5199\u5165\u4fdd\u6301\u963b\u65ad',
  blockedExpectedState: '\u9884\u671f\u963b\u65ad',
  saveResultLocked: '\u4fdd\u5b58\u7ed3\u679c 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  unpublishedProofLocked: '\u672a\u53d1\u5e03\u8bc1\u660e 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  networkHarLocked: '\u7f51\u7edc/HAR 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  noRealWrite: '\u4e0d\u53ef\u6267\u884c\u771f\u5b9e\u5199\u5165',
  finalCheckCurrent: '\u81ea\u68c0\u8986\u76d6\u5f53\u524d\u4ee3\u7801',
  finalCheckStale: '\u81ea\u68c0\u672a\u8986\u76d6\u5f53\u524d\u4ee3\u7801',
  browserQaGit: '\u6d4f\u89c8\u5668 QA Git',
  screenshotHashes: '\u622a\u56fe\u54c8\u5e0c',
  localAcceptanceCommand: '\u672c\u5730\u9a8c\u6536\u547d\u4ee4',
  sourceAcceptanceCommand: '\u6e90\u7801\u5305\u9a8c\u6536\u547d\u4ee4',
  localWorkbenchLabel: '\u672c\u5730\u5de5\u4f5c\u53f0',
  browserQaLabel: '\u6d4f\u89c8\u5668 QA',
  finalReportCenterQa: '\u6700\u7ec8\u62a5\u544a\u4e2d\u5fc3 QA',
  sourcePackageLabel: '\u6e90\u7801\u5305\u9a8c\u6536',
  sourcePackageNotRequired: '\u6e90\u7801\u5305\u9a8c\u6536 NOT_REQUIRED',
  sourcePackageNotRequiredCopy: '\u9ed8\u8ba4\u672c\u5730\u9a8c\u6536\u4e0d\u8981\u6c42\u6e90\u7801\u5305 clean',
  demoBatchButton: '\u521b\u5efa\u6f14\u793a\u6279\u6b21\uff08\u5199\u5165\u672c\u5730\uff09',
  localDemoTask: '\u672c\u5730\u6f14\u793a\u6838\u9a8c\u6279\u6b21',
  localDemoStart: '\u542f\u52a8\u672c\u5730\u6f14\u793a\u4efb\u52a1',
  l2RunIdFlag: '--run-id',
  l2RunIdVar: '$runId',
  l2SameBinding: '\u540c\u4e00 run-id',
  fallbackCopy: 'fallback',
  oldSaveOnly: '\u53ea\u4fdd\u5b58\u4e0d\u53d1\u5e03',
  oldWaitSave: '\u7b49\u5f85\u4fdd\u5b58\u6838\u9a8c',
  oldVisibleBrowser: '\u6253\u5f00\u53ef\u89c1\u6d4f\u89c8\u5668',
  oldAutomation: '\u65c1\u89c2\u81ea\u52a8\u5316',
  fakePlaceholder: '\u8bca\u65ad\u5360\u4f4d',
};
if (reportOnlyFinal) {
  const clickedReports = await clickSelector('[data-section="reports"]') || await clickText(text.reports);
  await new Promise(r => setTimeout(r, 300));
  const finalCheckSummary = await fetchJson('/api/delivery/final-check');
  const expectedSourcePackage = finalCheckSummary?.source_package_check === 'NOT_REQUIRED'
    ? text.sourcePackageNotRequired
    : text.sourcePackageLabel + ' ' + String(finalCheckSummary?.source_package_check ?? '\u672a\u68c0\u67e5');
  const expectedBrowserQa = text.browserQaLabel + ' ' + (finalCheckSummary?.browser_qa_ok === true ? 'PASS' : 'FAIL');
  const expectedLocalWorkbench = text.localWorkbenchLabel + ' ' + String(finalCheckSummary?.local_workbench_check ?? '\u672a\u68c0\u67e5');
  const expectedPostFinalReportQa = text.finalReportCenterQa + ' ' + (finalCheckSummary?.post_final_report_qa_ok === true ? 'PASS' : 'FAIL');
  const expectedLockedEvidence = [text.saveResultLocked, text.unpublishedProofLocked, text.networkHarLocked];
  const requiredReportFragments = [
    text.finalCheck,
    expectedLocalWorkbench,
    expectedBrowserQa,
    expectedSourcePackage,
    ...(allowMissingPostFinalQa ? [] : ['qa-report-center-final.png']),
  ];
  const reportText = await waitForBodyIncludes(requiredReportFragments, 5000);
  const finalReportShot = await screenshot('qa-report-center-final');
  const finalReportCenterQaDomState = await evalValue('(() => { const el = document.querySelector("[data-testid=\\"final-report-center-qa\\"]"); return el ? el.getAttribute("data-state") : null; })()');
  const finalReportCenterScreenshotDomPath = await evalValue('(() => { const el = document.querySelector("[data-testid=\\"final-report-center-screenshot-path\\"]"); return el ? (el.innerText || el.textContent || "") : ""; })()');
  const reportCenterSectionVisible = await evalValue('Boolean(document.querySelector("[data-testid=\\"report-center-section\\"]"))');
  const finalReportBlockedStatusTone = await evalValue('(() => { const row = document.querySelector(".delivery-readiness-row"); return Boolean(row && row.className.includes("is-blocked") && (row.innerText || "").includes("BLOCKED")); })()');
  const lockedEvidenceRows = await evalValue('(() => [...document.querySelectorAll(".check-row[data-state=\\"locked\\"]")].map(el => ({ text: el.innerText || "", className: el.className || "" })))()');
  const finalReportCenterQaDiagnostics = {
    expectedPostFinalReportQa,
    hasExpectedPostFinalReportQa: reportText.includes(expectedPostFinalReportQa),
    expectedLockedEvidence,
    lockedEvidenceRows,
    hasExpectedLockedEvidenceRows: expectedLockedEvidence.every(fragment => reportText.includes(fragment)),
    lockedEvidenceRowsNotWarn: Array.isArray(lockedEvidenceRows) && lockedEvidenceRows.length >= 3 && lockedEvidenceRows.every(row => !String(row.className || '').includes('warn')),
    hasFinalReportScreenshotName: reportText.includes('qa-report-center-final.png'),
    finalReportCenterQaDomState,
    finalReportCenterScreenshotDomPath,
    reportCenterSectionVisible,
    apiPostFinalReportQaOk: finalCheckSummary?.post_final_report_qa_ok,
    apiFinalReportCenterScreenshotPath: finalCheckSummary?.final_report_center_screenshot_path,
    reportTextSample: reportText.slice(0, 1200),
  };
  const consolePath = outDir + '/qa-final-report-console.jsonl';
  fs.writeFileSync(
    consolePath,
    consoleEvents.map(event => JSON.stringify(event)).join('\n') + (consoleEvents.length ? '\n' : '')
  );
  const networkPath = outDir + '/qa-final-report-network.json';
  fs.writeFileSync(networkPath, JSON.stringify(networkEvents, null, 2));
  const allowedOrigins = new Set([new URL(targetUrl).origin, new URL(apiBase).origin]);
  const failedNetworkEvents = networkEvents.filter(event => event.type === 'failed');
  const badNetworkResponses = networkEvents.filter(event => event.type === 'response' && (event.status < 200 || event.status >= 400));
  const unexpectedNetworkMethods = networkEvents.filter(event => event.type === 'request' && event.method !== 'GET');
  const unexpectedNetworkHosts = networkEvents.filter(event => {
    if (!event.url || !(event.type === 'request' || event.type === 'response')) return false;
    try {
      const parsed = new URL(event.url);
      return parsed.protocol.startsWith('http') && !allowedOrigins.has(parsed.origin);
    } catch {
      return true;
    }
  });
  const finalResult = {
    checkedAt: new Date().toISOString(),
    url: targetUrl,
    mode: 'report_only_final',
    ok: true,
    assertions: {
      finalReportCenterOpened: clickedReports && reportCenterSectionVisible,
      finalReportCenterShowsFinalPassState: reportText.includes(expectedLocalWorkbench)
        && reportText.includes(expectedBrowserQa)
        && reportText.includes(expectedSourcePackage),
      finalReportCenterQaVisible: allowMissingPostFinalQa
        || (finalReportCenterQaDiagnostics.finalReportCenterQaDomState === 'PASS'
          && finalReportCenterQaDiagnostics.finalReportCenterScreenshotDomPath.includes('qa-report-center-final.png')
          && finalReportCenterQaDiagnostics.apiPostFinalReportQaOk === true
          && Boolean(finalReportCenterQaDiagnostics.apiFinalReportCenterScreenshotPath)),
      finalReportCenterQaTextVisible: allowMissingPostFinalQa || finalReportCenterQaDiagnostics.hasExpectedPostFinalReportQa,
      finalReportCenterShowsFreshnessState: reportText.includes(text.finalCheckCurrent)
        || reportText.includes(text.finalCheckStale),
      finalReportCenterShowsBlockedDxmState: reportText.includes(text.blockedExpectedState)
        && reportText.includes(text.noRealWrite)
        && finalReportBlockedStatusTone,
      finalReportExpectedLockedEvidenceRows: finalReportCenterQaDiagnostics.hasExpectedLockedEvidenceRows,
      finalReportLockedEvidenceRowsNotWarn: finalReportCenterQaDiagnostics.lockedEvidenceRowsNotWarn,
      finalReportApiIsFinal: finalCheckSummary?.local_workbench_check === 'PASS'
        && finalCheckSummary?.browser_qa_ok === true
        && finalCheckSummary?.real_dxm_write_readiness === 'BLOCKED',
      noConsoleErrors: consoleErrors.length === 0,
      networkNoFailures: failedNetworkEvents.length === 0,
      networkHttpOk: badNetworkResponses.length === 0,
      networkGetOnly: unexpectedNetworkMethods.length === 0,
      networkLocalOnly: unexpectedNetworkHosts.length === 0,
      screenshotsWritten: fs.existsSync(finalReportShot),
      sidecarsWritten: fs.existsSync(consolePath) && fs.existsSync(networkPath),
    },
    consoleErrors,
    finalReportCenterQaDiagnostics,
    networkSummary: {
      eventCount: networkEvents.length,
      failedCount: failedNetworkEvents.length,
      badResponseCount: badNetworkResponses.length,
      unexpectedMethodCount: unexpectedNetworkMethods.length,
      unexpectedHostCount: unexpectedNetworkHosts.length,
      allowedOrigins: [...allowedOrigins],
    },
    screenshots: [finalReportShot],
    screenshotHashes: { [finalReportShot]: sha256(finalReportShot) },
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
      command: 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\\\qa-browser-check.ps1 -ReportOnlyFinal',
      scriptPath: qaScriptPath,
      scriptSha256: sha256(qaScriptPath),
      gitHead: runGit(['rev-parse', 'HEAD']),
      gitStatusShort: runGit(['status', '--short']),
      backendLogPath: rootDir + '/data/backend.log',
      frontendLogPath: rootDir + '/data/frontend.log',
    },
  };
  finalResult.ok = Object.values(finalResult.assertions).every(Boolean);
  const finalJsonPath = outDir + '/qa-final-report-check.json';
  fs.writeFileSync(finalJsonPath, JSON.stringify(finalResult, null, 2));
  const finalSummaryPath = outDir + '/qa-final-report-check.md';
  const finalAssertionLines = Object.entries(finalResult.assertions).map(([key, value]) => '- ' + (value ? 'PASS' : 'FAIL') + ' ' + key);
  const finalScreenshotLines = finalResult.screenshots.map(path => '- ' + path + ' sha256=' + finalResult.screenshotHashes[path]);
  const finalSidecarLines = Object.entries(finalResult.sidecars).map(([key, path]) => '- ' + key + ': ' + path + ' sha256=' + finalResult.sidecarHashes[path]);
  const finalConsoleLines = finalResult.consoleErrors.length ? finalResult.consoleErrors.map(error => '- ' + error) : ['- none'];
  fs.writeFileSync(finalSummaryPath, [
    '# Final Report Center QA',
    '',
    '- Checked at: ' + finalResult.checkedAt,
    '- URL: ' + finalResult.url,
    '- Result: ' + (finalResult.ok ? 'PASS' : 'FAIL'),
    '',
    '## Assertions',
    ...finalAssertionLines,
    '',
    '## Screenshots',
    ...finalScreenshotLines,
    '',
    '## Sidecars',
    ...finalSidecarLines,
    '',
    '## Console Errors',
    ...finalConsoleLines,
    '',
  ].join('\n'));
  console.log(JSON.stringify(finalResult, null, 2));
  ws.close();
  if (!finalResult.ok) process.exit(1);
  process.exit(0);
}
const initialText = await bodyText();
const clickedTasks = await clickText(text.tasks);
await new Promise(r => setTimeout(r, 700));
const taskText = await bodyText();
const taskStartDisabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes("\u7981\u6b62\u542f\u52a8")); return Boolean(button && button.disabled); })()');
const taskShot = await screenshot('qa-task-center');
const clickedConsole = await clickText(text.console);
await new Promise(r => setTimeout(r, 700));
const consoleText = await bodyText();
const consoleStartDisabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes("L2 \u672a\u901a\u8fc7\uff0c\u7981\u6b62\u6253\u5f00\u8bca\u65ad\u6d4f\u89c8\u5668")); return Boolean(button && button.disabled); })()');
const consoleShot = await screenshot('qa-execution-console');
const clickedReports = await clickText(text.reports);
await new Promise(r => setTimeout(r, 700));
const reportText = await bodyText();
const finalCheckSummaryForReport = await fetchJson('/api/delivery/final-check');
const reportBlockedStatusTone = await evalValue('(() => { const row = document.querySelector(".delivery-readiness-row"); return Boolean(row && row.className.includes("is-blocked") && (row.innerText || "").includes("BLOCKED")); })()');
const reportAcceptanceCommands = await evalValue('(() => [...document.querySelectorAll(".delivery-check-card__commands code")].map(el => (el.innerText || el.textContent || "").trim()))()');
const l2CommandBlocks = await evalValue('(() => [...document.querySelectorAll(".l2-next-step-card__commands code")].map(el => (el.innerText || el.textContent || "").trim()))()');
const reportShot = await screenshot('qa-report-center');
await send('Emulation.setDeviceMetricsOverride', {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
});
await send('Emulation.setTouchEmulationEnabled', { enabled: true });
await send('Page.navigate', { url: targetUrl });
await new Promise(r => setTimeout(r, 1400));
const mobileInitialText = await bodyText();
const clickedMobileTasks = await clickText(text.tasks);
await new Promise(r => setTimeout(r, 700));
const mobileTaskText = await bodyText();
const mobileReflow = await evalValue('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1');
const mobileOverflow = await evalValue('(() => { const viewportWidth = document.documentElement.clientWidth; const candidates = [...document.querySelectorAll("button, a, code, .guard-chip, .status-pill, .module-head, .module-card")]; const bad = candidates.map(el => ({ el, rect: el.getBoundingClientRect() })).filter(({ rect }) => rect.width > 0 && (rect.left < -1 || rect.right > viewportWidth + 1)); return { ok: bad.length === 0, count: bad.length, samples: bad.slice(0, 5).map(({ el, rect }) => ({ tag: el.tagName, text: String(el.innerText || el.textContent || "").trim().slice(0, 80), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) })) }; })()');
const mobileShot = await screenshot('qa-mobile-task-center');
await send('Emulation.clearDeviceMetricsOverride');
await send('Emulation.setTouchEmulationEnabled', { enabled: false });
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
const consolePath = outDir + '/qa-console.jsonl';
fs.writeFileSync(
  consolePath,
  consoleEvents.map(event => JSON.stringify(event)).join('\n') + (consoleEvents.length ? '\n' : '')
);
const networkPath = outDir + '/qa-network.json';
fs.writeFileSync(networkPath, JSON.stringify(networkEvents, null, 2));
const allowedHostname = new URL(targetUrl).hostname;
const allowedOrigins = new Set([new URL(targetUrl).origin, new URL(apiBase).origin]);
const failedNetworkEvents = networkEvents.filter(event => event.type === 'failed');
const badNetworkResponses = networkEvents.filter(event => event.type === 'response' && (event.status < 200 || event.status >= 400));
const unexpectedNetworkMethods = networkEvents.filter(event => event.type === 'request' && event.method !== 'GET');
const unexpectedNetworkHosts = networkEvents.filter(event => {
  if (!event.url || !(event.type === 'request' || event.type === 'response')) return false;
  try {
    const parsed = new URL(event.url);
    return parsed.protocol.startsWith('http') && !allowedOrigins.has(parsed.origin);
  } catch {
    return true;
  }
});
const screenshotPaths = [taskShot, consoleShot, reportShot, mobileShot];
let blockedStartStatus = null;
let blockedAgentConsoleStatus = null;
let blockedActionChecks = [];
let beforeTaskStatus = null;
let afterTaskStatus = null;
async function postBlockedAction(name, path, body) {
  const response = await fetch(apiBase + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const rawBody = await response.text();
  let parsedBody = null;
  try {
    parsedBody = JSON.parse(rawBody);
  } catch {
    parsedBody = rawBody;
  }
  return {
    name,
    path,
    status: response.status,
    detail: parsedBody && typeof parsedBody === 'object' ? parsedBody.detail : String(rawBody).slice(0, 240),
  };
}
try {
  const realMutationTask = realMutationTaskForBlockedChecks;
  const taskId = realMutationTask?.id;
  beforeTaskStatus = summarizeTask(realMutationTask);
  if (taskId) {
    const directPayload = {
      action: 'note',
      note_text: 'QA_BLOCKED_ACTION_SHOULD_NOT_WRITE',
      product_query: 'QA_BLOCKED_PRODUCT',
      store_name: 'Dang Kang',
      task_id: taskId,
    };
    blockedActionChecks = [
      await postBlockedAction('task_start', '/api/tasks/' + taskId + '/start', {}),
      await postBlockedAction('agent_console_start', '/api/agent-console/start', { task_id: taskId, launch_browser: true }),
      await postBlockedAction('dxm_draft_box_action', '/api/dxm/draft-box/action', directPayload),
      await postBlockedAction('dxm_claim_product', '/api/dxm/workflow/claim-product', directPayload),
      await postBlockedAction('dxm_open_editor', '/api/dxm/workflow/open-editor', { ...directPayload, action: 'edit' }),
    ];
    blockedStartStatus = blockedActionChecks.find(item => item.name === 'task_start')?.status ?? null;
    blockedAgentConsoleStatus = blockedActionChecks.find(item => item.name === 'agent_console_start')?.status ?? null;
    const afterWorkspacePayload = await fetchJson('/api/delivery/workspace?task_id=' + taskId);
    const afterTask = Array.isArray(afterWorkspacePayload?.tasks)
      ? afterWorkspacePayload.tasks.find(task => task?.id === taskId)
      : afterWorkspacePayload?.current_task;
    afterTaskStatus = summarizeTask(afterTask);
  }
} catch {
  blockedStartStatus = 'error';
  blockedAgentConsoleStatus = 'error';
}
const blockedActionsPath = outDir + '/qa-blocked-actions.json';
fs.writeFileSync(blockedActionsPath, JSON.stringify({
  apiBase,
  beforeTaskStatus,
  afterTaskStatus,
  checks: blockedActionChecks,
}, null, 2));
const blockedActionsAllForbidden = blockedActionChecks.length === 5 && blockedActionChecks.every(item => item.status === 403);
const taskStateUnchanged = JSON.stringify(beforeTaskStatus) === JSON.stringify(afterTaskStatus);
const tasksBeforeDemo = await fetchJson('/api/tasks');
const maxTaskIdBeforeDemo = Array.isArray(tasksBeforeDemo) && tasksBeforeDemo.length
  ? Math.max(...tasksBeforeDemo.map(item => Number(item.id) || 0))
  : 0;
await evalValue('window.confirm = () => true');
const demoBatchCreated = await clickText(text.demoBatchButton);
await new Promise(r => setTimeout(r, 1200));
const demoText = await bodyText();
const demoStartButtonEnabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes("' + text.localDemoStart + '")); return Boolean(button && !button.disabled); })()');
const tasksAfterDemo = await fetchJson('/api/tasks');
const newTasks = Array.isArray(tasksAfterDemo)
  ? tasksAfterDemo.filter(item => item.id > maxTaskIdBeforeDemo)
  : [];
const demoCreatedTask = newTasks.find(item => item.id > maxTaskIdBeforeDemo && item.mode === 'dry_run' && item.status === 'draft' && String(item.name || '').includes(text.localDemoTask));
const hasLocalAcceptanceCommand = Array.isArray(reportAcceptanceCommands) && reportAcceptanceCommands.some(command => /scripts[\\/]+final-delivery-check\.bat$/.test(command));
const hasSourceAcceptanceCommand = Array.isArray(reportAcceptanceCommands) && reportAcceptanceCommands.some(command => /scripts[\\/]+final-delivery-check\.bat\s+-RequireCleanWorktree$/.test(command));
const hasRunIdSetup = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('$runId') && command.includes('Get-Date'));
const hasDataAcquisitionRunId = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('--target data_acquisition') && command.includes('--run-id $runId'));
const hasDraftBoxRunId = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('--target draft_box') && command.includes('--run-id $runId'));
const finalCheckRequiresNotRequiredCopy = finalCheckSummaryForReport?.source_package_check === 'NOT_REQUIRED';
const result = {
  checkedAt: new Date().toISOString(),
  url: targetUrl,
  ok: true,
  assertions: {
    initialLoaded: initialText.includes(text.hero) || initialText.includes(text.appName),
    navClicksWorked: clickedTasks && clickedConsole && clickedReports,
    localizedOverviewNav: initialText.includes(text.overview),
    firstScreenExpectedBlockedScope: initialText.includes(text.localWorkbenchDeliverable) && initialText.includes(text.expectedSafetyBlocked) && initialText.includes(text.realWriteGateFailed),
    localWriteCopy: taskText.includes(text.localWrite),
    taskRecoveryActions: (taskText.includes(text.readonlyDiag) || taskText.includes(text.l2BlockHelp)) && taskText.includes(text.evidenceGap),
    taskStartBlockedCopy: taskText.includes(text.forbiddenStart),
    taskStartButtonDisabled: taskStartDisabled,
    mobileLoaded: mobileInitialText.includes(text.hero) || mobileInitialText.includes(text.appName),
    mobileNavWorked: clickedMobileTasks && mobileTaskText.includes(text.localWrite),
    mobileNoHorizontalOverflow: mobileReflow === true && mobileOverflow.ok === true,
    consoleReadonlyCopy: consoleText.includes(text.readonly) && consoleText.includes(text.noSaveStart),
    consoleNoFakeBrowser: consoleText.includes(text.noBrowser) && consoleText.includes(text.noFakeEvidence),
    consoleStartButtonDisabled: consoleStartDisabled,
    consoleNoFakePlaceholder: !(consoleText + ' ' + taskText).includes(text.fakePlaceholder),
    reportDeliveryCheckVisible: reportText.includes(text.finalCheck) && reportText.includes(text.expectedBlocked),
    reportFreshnessVisible: (reportText.includes(text.finalCheckCurrent) || reportText.includes(text.finalCheckStale)) && reportText.includes(text.browserQaGit) && reportText.includes(text.screenshotHashes),
    reportBlockedStatusLanguage: reportText.includes(text.blockedExpectedState) && reportText.includes(text.noRealWrite) && reportBlockedStatusTone,
    reportDualAcceptanceCommands: reportText.includes(text.localAcceptanceCommand) && reportText.includes(text.sourceAcceptanceCommand) && hasLocalAcceptanceCommand && hasSourceAcceptanceCommand,
    reportL2RunBindingCopy: reportText.includes(text.l2SameBinding) && hasRunIdSetup && hasDataAcquisitionRunId && hasDraftBoxRunId,
    reportSourcePackageNotRequiredCopy: !finalCheckRequiresNotRequiredCopy || (reportText.includes(text.sourcePackageNotRequired) && reportText.includes(text.sourcePackageNotRequiredCopy)),
    demoBatchCanStartLocally: demoBatchCreated && Boolean(demoCreatedTask) && demoText.includes(text.localDemoTask) && demoStartButtonEnabled,
    noDeveloperFallbackCopy: !(initialText + ' ' + taskText + ' ' + consoleText + ' ' + reportText).includes(text.fallbackCopy),
    localStartPostBlocked: blockedStartStatus === 403,
    localAgentConsolePostBlocked: blockedAgentConsoleStatus === 403,
    localDirectDxmPostsBlocked: blockedActionsAllForbidden,
    blockedPostsDidNotMutateTask: taskStateUnchanged,
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
    screenshotsWritten: screenshotPaths.every(path => fs.existsSync(path)),
    sidecarsWritten: fs.existsSync(consolePath) && fs.existsSync(networkPath) && fs.existsSync(blockedActionsPath),
  },
  consoleErrors,
  networkSummary: {
    eventCount: networkEvents.length,
    failedCount: failedNetworkEvents.length,
    badResponseCount: badNetworkResponses.length,
    unexpectedMethodCount: unexpectedNetworkMethods.length,
    unexpectedHostCount: unexpectedNetworkHosts.length,
    allowedHostname,
    allowedOrigins: [...allowedOrigins],
    blockedStartStatus,
    blockedAgentConsoleStatus,
    mobileOverflow,
  },
  screenshots: screenshotPaths,
  screenshotHashes: Object.fromEntries(screenshotPaths.map(path => [path, sha256(path)])),
  sidecars: {
    console: consolePath,
    network: networkPath,
    blockedActions: blockedActionsPath,
  },
  sidecarHashes: {
    [consolePath]: sha256(consolePath),
    [networkPath]: sha256(networkPath),
    [blockedActionsPath]: sha256(blockedActionsPath),
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
  if ($LASTEXITCODE -ne 0) {
    throw "Browser QA node check failed with exit code $LASTEXITCODE."
  }
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
