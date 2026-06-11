param(
  [string]$Url = "http://127.0.0.1:5173",
  [string]$OutDir = "outputs/browser-checks",
  [int]$Port = 9230,
  [switch]$ReportOnlyFinal,
  [switch]$AllowMissingPostFinalQa
)

$ErrorActionPreference = "Stop"

function Find-BrowserCandidates {
  $candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe"
  )
  $found = @()
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      $found += (Resolve-Path -LiteralPath $candidate).Path
    }
  }
  $playwrightRoot = Join-Path $env:LOCALAPPDATA "ms-playwright"
  if (Test-Path -LiteralPath $playwrightRoot) {
    $playwrightChromium = Get-ChildItem -Path $playwrightRoot -Recurse -Filter chrome.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -like "*chrome-win64*" } |
      Sort-Object FullName -Descending
    foreach ($candidate in $playwrightChromium) {
      $found += $candidate.FullName
    }
  }
  $found = @($found | Select-Object -Unique)
  if (!$found.Count) {
    throw "Chrome or Edge was not found."
  }
  return $found
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

$browserCandidates = @(Find-BrowserCandidates)
$node = Find-Node
$scriptPath = Join-Path $env:TEMP ("dxm-qa-browser-check-" + [guid]::NewGuid().ToString("N") + ".mjs")

function Test-DebugPortAvailable {
  param([int]$CandidatePort)

  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $CandidatePort)
    $listener.Start()
    return $true
  } catch {
    return $false
  } finally {
    if ($listener) {
      $listener.Stop()
    }
  }
}

function Find-QaDebugPort {
  param(
    [int]$PreferredPort,
    [int]$MaxAttempts = 200
  )

  for ($offset = 0; $offset -lt $MaxAttempts; $offset += 1) {
    $candidate = $PreferredPort + $offset
    if (Test-DebugPortAvailable -CandidatePort $candidate) {
      return $candidate
    }
  }

  foreach ($basePort in @(15000, 20000, 30000, 40000, 50000)) {
    for ($offset = 0; $offset -lt 100; $offset += 1) {
      $candidate = $basePort + $offset
      if (Test-DebugPortAvailable -CandidatePort $candidate) {
        return $candidate
      }
    }
  }

  throw "No available Chrome debugging port found near $PreferredPort."
}

$selectedPort = Find-QaDebugPort -PreferredPort $Port
if ($selectedPort -ne $Port) {
  Write-Host "Port $Port is unavailable or reserved; using $selectedPort instead."
  $Port = $selectedPort
}

function New-QaBrowserArgs {
  param(
    [string]$UserData,
    [int]$DebugPort,
    [string]$HeadlessMode
  )

  $headlessArg = if ($HeadlessMode -eq "new") { "--headless=new" } else { "--headless" }
  return @(
    $headlessArg,
    "--disable-gpu",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "--user-data-dir=$UserData",
    "--remote-debugging-port=$DebugPort",
    "--window-size=1440,1100",
    "about:blank"
  )
}

function Test-CdpReady {
  param(
    [int]$DebugPort,
    [int]$TimeoutSeconds
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    Start-Sleep -Milliseconds 300
    try {
      Invoke-RestMethod -Uri "http://127.0.0.1:$DebugPort/json/list" -TimeoutSec 2 | Out-Null
      return $true
    } catch {
      if ((Get-Date) -ge $deadline) {
        return $false
      }
    }
  } while ($true)
}

function Start-QaCdpBrowser {
  param(
    [string[]]$Candidates,
    [int]$DebugPort,
    [string]$AttemptOutDir
  )

  $attempts = @()
  $headlessModes = @("new", "legacy")
  $attemptIndex = 0
  foreach ($candidate in $Candidates) {
    foreach ($mode in $headlessModes) {
      $attemptIndex += 1
      $attemptUserData = Join-Path $env:TEMP ("dxm-qa-chrome-" + [guid]::NewGuid().ToString("N"))
      New-Item -ItemType Directory -Path $attemptUserData -Force | Out-Null
      $stdoutPath = Join-Path $AttemptOutDir "qa-browser-stdout-$attemptIndex.log"
      $stderrPath = Join-Path $AttemptOutDir "qa-browser-stderr-$attemptIndex.log"
      $args = New-QaBrowserArgs -UserData $attemptUserData -DebugPort $DebugPort -HeadlessMode $mode
      $startedProcess = $null
      $isReady = $false
      try {
        Write-Host "Starting browser QA with $([System.IO.Path]::GetFileName($candidate)) headless=$mode on port $DebugPort"
        $startedProcess = Start-Process `
          -FilePath $candidate `
          -ArgumentList $args `
          -PassThru `
          -WindowStyle Hidden `
          -RedirectStandardOutput $stdoutPath `
          -RedirectStandardError $stderrPath
        if (Test-CdpReady -DebugPort $DebugPort -TimeoutSeconds 15) {
          $isReady = $true
          return @{
            Process = $startedProcess
            UserData = $attemptUserData
            BrowserPath = $candidate
            HeadlessMode = $mode
            StdoutPath = $stdoutPath
            StderrPath = $stderrPath
            Attempts = $attempts
          }
        }
        $exitText = if ($startedProcess.HasExited) { "exit=$($startedProcess.ExitCode)" } else { "not ready" }
        $attempts += @{
          browser = $candidate
          headlessMode = $mode
          status = $exitText
          stdout = $stdoutPath
          stderr = $stderrPath
        }
      } catch {
        $attempts += @{
          browser = $candidate
          headlessMode = $mode
          status = "failed: $($_.Exception.Message)"
          stdout = $stdoutPath
          stderr = $stderrPath
        }
      } finally {
        if (!$isReady -and $startedProcess -and -not $startedProcess.HasExited) {
          Stop-Process -Id $startedProcess.Id -Force -ErrorAction SilentlyContinue
          Start-Sleep -Milliseconds 500
        }
        if (!$isReady -and (Test-Path -LiteralPath $attemptUserData)) {
          Remove-Item -LiteralPath $attemptUserData -Recurse -Force -ErrorAction SilentlyContinue
        }
      }
    }
  }

  $attemptPath = Join-Path $AttemptOutDir "qa-browser-launch-attempts.json"
  $attempts | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $attemptPath -Encoding UTF8
  throw "Chrome DevTools endpoint did not start after trying $($attempts.Count) browser launch attempts. See $attemptPath and qa-browser-stderr-*.log."
}

$proc = $null
$userData = $null
$browserLaunch = $null
try {
  $browserLaunch = Start-QaCdpBrowser -Candidates $browserCandidates -DebugPort $Port -AttemptOutDir $absoluteOutDir
  $proc = $browserLaunch.Process
  $userData = $browserLaunch.UserData
  $browserPath = $browserLaunch.BrowserPath
  $headlessMode = $browserLaunch.HeadlessMode

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
const browserPath = '$($browserPath.Replace("\", "/"))';
const browserHeadlessMode = '$headlessMode';
function writeFatalQaError(error) {
  fs.mkdirSync(outDir, { recursive: true });
  const payload = {
    checkedAt: new Date().toISOString(),
    url: targetUrl,
    message: error && error.message ? error.message : String(error),
    stack: error && error.stack ? error.stack : null,
  };
  fs.writeFileSync(outDir + '/qa-browser-error.json', JSON.stringify(payload, null, 2));
  console.error(payload.message);
}
process.on('uncaughtException', error => {
  writeFatalQaError(error);
  process.exit(1);
});
process.on('unhandledRejection', error => {
  writeFatalQaError(error);
  process.exit(1);
});
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
const requestIndex = new Map();
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
    const requestEntry = {
      type: 'request',
      requestId: msg.params.requestId,
      url: msg.params.request.url,
      method: msg.params.request.method,
      timestamp: msg.params.timestamp,
    };
    requestIndex.set(msg.params.requestId, requestEntry);
    networkEvents.push(requestEntry);
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
    const requestEntry = requestIndex.get(msg.params.requestId) || {};
    networkEvents.push({
      type: 'failed',
      requestId: msg.params.requestId,
      url: requestEntry.url || null,
      method: requestEntry.method || null,
      errorText: msg.params.errorText || '',
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
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(msgId);
      reject(new Error('CDP command timed out: ' + method));
    }, 45000);
    pending.set(msgId, {
      resolve: value => {
        clearTimeout(timer);
        resolve(value);
      },
      reject: error => {
        clearTimeout(timer);
        reject(error);
      },
    });
  });
}
async function evalValue(expr) {
  const res = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return res.result.value;
}
async function horizontalOverflowState() {
  return await evalValue('(() => { const viewportWidth = document.documentElement.clientWidth; const selectors = "button, a, code, .guard-chip, .status-pill, .module-head, .module-card, .effective-value-item"; const candidates = [...document.querySelectorAll(selectors)]; const bad = candidates.map(el => ({ el, rect: el.getBoundingClientRect() })).filter(({ rect }) => rect.width > 0 && (rect.left < -1 || rect.right > viewportWidth + 1)); return { ok: bad.length === 0, count: bad.length, samples: bad.slice(0, 5).map(({ el, rect }) => ({ tag: el.tagName, className: String(el.className || "").slice(0, 80), text: String(el.innerText || el.textContent || "").trim().slice(0, 80), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) })) }; })()');
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
async function waitForTextGone(fragment, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  let text = await bodyText();
  while (Date.now() < deadline) {
    if (!fragment || !text.includes(fragment)) {
      return text;
    }
    await new Promise(r => setTimeout(r, 200));
    text = await bodyText();
  }
  return text;
}
async function waitForWorkspaceSettled(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const settled = await evalValue('(() => Boolean(document.querySelector("[data-section=\\"tasks\\"]")) && !document.querySelector(".workspace-alert--loading"))()');
    if (settled) return true;
    await new Promise(r => setTimeout(r, 250));
  }
  return false;
}
async function waitForLocalDemoStartButtonEnabled(label, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const enabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes(' + JSON.stringify(label) + ')); return Boolean(button && !button.disabled); })()');
    if (enabled) return true;
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
}
async function clickText(label) {
  return await evalValue('(() => { const els = [...document.querySelectorAll("button,a,[role=\\"button\\"],nav *")]; const el = els.find(e => (e.innerText || e.textContent || "").trim() === ' + JSON.stringify(label) + '); if (el) { el.click(); return true; } return false; })()');
}
async function clickTaskByName(name) {
  return await evalValue('(() => { const rows = [...document.querySelectorAll(".task-row")]; const row = rows.find(button => { const title = button.querySelector("strong"); return ((title && title.textContent) || "").trim() === ' + JSON.stringify(name) + '; }); if (row) { row.click(); return true; } return false; })()');
}
async function clickSelector(selector) {
  return await evalValue('(() => { const el = document.querySelector(' + JSON.stringify(selector) + '); if (el) { el.click(); return true; } return false; })()');
}
async function openReportCenter() {
  let clicked = await clickSelector('[data-section="reports"]') || await clickText(text.reports) || await clickText(text.reportReviewPlan);
  if (clicked) return true;
  await clickSelector('[data-section="tasks"]') || await clickText(text.tasks);
  await new Promise(r => setTimeout(r, 350));
  clicked = await clickSelector('[data-section="reports"]') || await clickText(text.reportReviewPlan);
  if (clicked) return true;
  await clickSelector('[data-section="console"]') || await clickText(text.console);
  await new Promise(r => setTimeout(r, 350));
  return await clickSelector('[data-section="reports"]') || await clickText(text.reportReviewPlan) || await clickText(text.reports);
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
const initialFinalCheckSummary = reportOnlyFinal ? null : await fetchJson('/api/delivery/final-check').catch(() => null);
const initialEffectiveReadiness = initialFinalCheckSummary?.effective_real_dxm_write_readiness
  ?? initialFinalCheckSummary?.real_dxm_write_readiness;
const initialEffectiveMutationAllowed = initialFinalCheckSummary?.effective_real_dxm_mutation_allowed
  ?? initialFinalCheckSummary?.real_dxm_mutation_allowed;
const initialEffectiveMutationScope = initialFinalCheckSummary?.effective_real_dxm_mutation_scope
  ?? initialFinalCheckSummary?.real_dxm_mutation_scope;
const qaExpectedReady = initialEffectiveReadiness === 'READY'
  && initialEffectiveMutationAllowed === true
  && initialFinalCheckSummary?.controlled_single_save_ready === true
  && initialEffectiveMutationScope === 'controlled_single_save_only';
const shouldRunBlockedMutationChecks = !qaExpectedReady;
async function ensureRealMutationTask() {
  function findReusableQaTask(tasks, name, mode) {
    return Array.isArray(tasks)
      ? tasks.find(task => task?.name === name && task?.mode === mode) || null
      : null;
  }
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
  const existingTasks = await fetchJson('/api/tasks').catch(() => []);
  const reusableTask = findReusableQaTask(existingTasks, 'QA local gated single_save fixture', 'single_save');
  if (reusableTask) return reusableTask;
  return await postJson('/api/tasks', {
    name: 'QA local gated single_save fixture',
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
async function ensureUnreleasedRealModeTask() {
  function findReusableQaTask(tasks, name, mode) {
    return Array.isArray(tasks)
      ? tasks.find(task => task?.name === name && task?.mode === mode) || null
      : null;
  }
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
      title: 'QA unreleased real mode product',
      source: 'qa',
      category_name: 'QA_CATEGORY',
      price: 7.01,
      currency: 'USD',
      sku_count: 1,
      image_count: 1,
      image: 'qa-product.jpg',
    }] });
  }
  const existingTasks = await fetchJson('/api/tasks').catch(() => []);
  const reusableTask = findReusableQaTask(existingTasks, 'QA unreleased claim_only task', 'claim_only');
  if (reusableTask) return reusableTask;
  return await postJson('/api/tasks', {
    name: 'QA unreleased claim_only task',
    store_id: store.id,
    mode: 'claim_only',
    publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
    product_ids: [products[0].id],
    claim_mark: 'QA_CLAIM',
    payload: {
      store_name: store.name,
      category_name: products[0]?.category_name ?? 'QA_CATEGORY',
      image: products[0]?.image ?? 'qa-product.jpg',
    },
  });
}
async function ensureDryRunDemoTask() {
  function findReusableQaTask(tasks, name, mode) {
    return Array.isArray(tasks)
      ? tasks.find(task => task?.name === name && task?.mode === mode) || null
      : null;
  }
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
  const existingTasks = await fetchJson('/api/tasks').catch(() => []);
  const reusableTask = findReusableQaTask(existingTasks, '\u672c\u5730\u6f14\u793a\u6838\u9a8c\u6279\u6b21', 'dry_run');
  if (reusableTask) return reusableTask;
  return await postJson('/api/tasks', {
    name: '\u672c\u5730\u6f14\u793a\u6838\u9a8c\u6279\u6b21',
    store_id: store.id,
    mode: 'dry_run',
    publish_scene: 'SMT_SEMI_MANAGED_SAVE_ONLY',
    product_ids: products.map(item => item.id),
    claim_mark: 'AI_CLAIM',
    payload: {
      store_name: store.name,
      category_name: products[0]?.category_name ?? 'QA_CATEGORY',
      image: products[0]?.image ?? 'qa-product.jpg',
    },
  });
}
async function screenshot(name) {
  const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  const path = outDir + '/' + name + '.png';
  fs.writeFileSync(path, Buffer.from(res.data, 'base64'));
  return path;
}
const readyModeDemoTask = null;
const realMutationTaskForBlockedChecks = reportOnlyFinal || !shouldRunBlockedMutationChecks ? null : await ensureRealMutationTask();
const unreleasedRealModeTask = reportOnlyFinal || qaExpectedReady ? null : await ensureUnreleasedRealModeTask();
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
  config: '\u914d\u7f6e\u4e2d\u5fc3',
  editableConfig: '\u0044\u0058\u004d \u7f16\u8f91\u9875\u914d\u7f6e',
  configStepMeta: '\u6309\u5e97\u5c0f\u79d8\u7f16\u8f91\u9875\u5206\u533a\u9010\u6bb5\u586b\u5199',
  currentEditingSection: '\u6b63\u5728\u7f16\u8f91\u5206\u533a',
  otherConfigSections: '\u66f4\u591a\u7f16\u8f91\u9875\u5206\u533a',
  logisticsSection: '\u5305\u88c5\u7269\u6d41',
  weightField: '\u91cd\u91cf kg',
  nextRequiredConfig: '\u4e0b\u4e00\u6b65\u5fc5\u586b\u5b57\u6bb5',
  configReadySummary: '\u5f53\u524d\u4efb\u52a1\u914d\u7f6e\u5df2\u5c31\u7eea',
  currentTemplateScope: '\u5f53\u524d\u6a21\u677f\u8303\u56f4',
  onePerLine: '\u6bcf\u884c\u4e00\u4e2a',
  taskOverrideSave: '\u4ec5\u672c\u6b21\u4efb\u52a1\u4f7f\u7528',
  templateSave: '\u4fdd\u5b58\u4e3a\u5e97\u94fa\u6a21\u677f',
  fieldSource: '\u6765\u6e90\uff1a',
  loginManualBrowser: '\u767b\u5f55/\u4eba\u5de5\u5904\u7406\u771f\u5b9e\u6d4f\u89c8\u5668',
  executionObserve: '\u6253\u5f00\u6267\u884c\u6d4f\u89c8\u5668',
  browserControlPad: '\u9875\u9762\u5185\u64cd\u63a7',
  browserControlTypedInput: '\u8f93\u5165\u5230\u7126\u70b9',
  browserControlClickCoords: '\u70b9\u51fb\u5750\u6807',
  browserControlSelector: '\u9009\u62e9\u5668\u5b9a\u4f4d',
  browserControlSelectorClick: '\u6309\u9009\u62e9\u5668\u70b9\u51fb',
  browserControlSelectorFill: '\u6309\u9009\u62e9\u5668\u586b\u5199',
  browserControlWindowScope: '\u4ec5\u63a7\u5236\u5f53\u524d\u72ec\u7acb\u6d4f\u89c8\u5668\u7a97\u53e3',
  reportReviewPlan: '\u67e5\u770b L2 \u8bc4\u5ba1\u4e0e\u590d\u9a8c\u8ba1\u5212',
  hero: '\u0044\u0058\u004d \u81ea\u52a8\u5316\u5de5\u4f5c\u53f0',
  localWorkbenchDeliverable: '\u81ea\u52a8\u5316\u5de5\u4f5c\u53f0\u53ef\u4ea4\u4ed8',
  expectedSafetyBlocked: '\u771f\u5b9e DXM \u5199\u5165 L3 \u53d7\u63a7',
  nextStepSummary: '\u5355\u5546\u54c1\u91d1\u4e1d\u96c0',
  realWriteGateFailed: '\u771f\u5b9e\u5199\u5165\u95e8\u7981\u672a\u901a\u8fc7',
  appName: '\u5e97\u5c0f\u79d8\u534a\u6258\u7ba1\u6267\u884c\u5668',
  localWrite: '\u521b\u5efa\u672c\u5730 dry_run \u6f14\u793a\u6279\u6b21',
  readonlyDiag: '\u67e5\u770b\u53ea\u8bfb\u8bca\u65ad',
  l2BlockHelp: '\u67e5\u770b L2 \u963b\u65ad\u8bf4\u660e',
  evidenceGap: '\u67e5\u770b\u8bc1\u636e\u7f3a\u53e3',
  forbiddenStart: '\u7981\u6b62\u542f\u52a8',
  readonly: '\u771f\u5b9e\u6d4f\u89c8\u5668',
  noSaveStart: '\u4e0d\u4f1a\u53d1\u5e03',
  noBrowser: '\u0041\u0067\u0065\u006e\u0074 \u63a7\u5236\u771f\u5b9e\u6d4f\u89c8\u5668',
  noFakeEvidence: '\u771f\u5b9e\u5e97\u5c0f\u79d8',
  finalCheck: '\u6700\u8fd1\u81ea\u52a8\u5316\u9a8c\u6536',
  expectedBlocked: '\u771f\u5b9e\u4fdd\u5b58\u4fdd\u6301\u963b\u65ad',
  realSingleSaveReady: '\u771f\u5b9e DXM single_save READY',
  readyLimitedCopy: '\u5355\u5546\u54c1\u53ea\u4fdd\u5b58\u8def\u5f84\u5df2\u6709\u9a8c\u6536\u8bb0\u5f55',
  batchUnattendedPublishBlocked: '\u6279\u91cf\u3001\u65e0\u4eba\u503c\u5b88\u548c\u53d1\u5e03',
  blockedExpectedState: '\u9884\u671f\u963b\u65ad',
  saveResultLocked: '\u4fdd\u5b58\u7ed3\u679c 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  unpublishedProofLocked: '\u672a\u53d1\u5e03\u8bc1\u660e 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  networkHarLocked: '\u7f51\u7edc/HAR 0 \u6761\uff08\u9884\u671f\u963b\u65ad\uff09',
  businessReportLocked: '\u4e1a\u52a1\u4fdd\u5b58\u62a5\u544a 0 \u4efd\uff08\u771f\u5b9e\u4fdd\u5b58\u540e\uff0c\u9884\u671f\u963b\u65ad\uff09',
  postL3ChecklistLocked: '\u771f\u5b9e\u4fdd\u5b58\u540e\u62a5\u544a\u5fc5\u987b\u8986\u76d6',
  realWriteReleaseTitle: '\u771f\u5b9e\u5199\u5165\u653e\u884c\u524d\u7f6e',
  l2RealReadOnlyPassed: 'L2 \u53cc\u76ee\u6807\u771f\u5b9e\u53ea\u8bfb\u901a\u8fc7',
  l3ManualCanaryApproved: '\u4eba\u5de5\u6279\u51c6 L3 \u91d1\u4e1d\u96c0',
  saveEvidenceComplete: '\u4fdd\u5b58\u6210\u529f\u3001\u672a\u53d1\u5e03\u8bc1\u660e\u3001\u622a\u56fe\u548c network/HAR',
  allowlistTemplateNotL2Pass: '\u4e0d\u80fd\u7528 allowlist \u6a21\u677f\u66ff\u4ee3 L2 \u901a\u8fc7',
  saveResultGapTitle: '\u7f3a\u5c11\u4fdd\u5b58\u7ed3\u679c',
  unpublishedProofGapTitle: '\u7f3a\u5c11\u672a\u53d1\u5e03\u8bc1\u660e',
  networkSaveResponseGapTitle: '\u4fdd\u5b58\u63a5\u53e3\u54cd\u5e94\u672a\u6355\u83b7',
  oldSaveResultBlocker: 'blocker\uff1a\u7f3a\u5c11\u4fdd\u5b58\u7ed3\u679c',
  oldUnpublishedProofBlocker: 'blocker\uff1a\u7f3a\u5c11\u672a\u53d1\u5e03\u8bc1\u660e',
  oldNetworkHarBlocker: 'blocker\uff1a\u7f3a\u5c11\u7f51\u7edc/HAR',
  noRealWrite: '\u4e0d\u53ef\u6267\u884c\u771f\u5b9e\u5199\u5165',
  finalCheckCurrent: '\u81ea\u68c0\u8986\u76d6\u5f53\u524d\u4ee3\u7801',
  finalCheckStale: '\u81ea\u68c0\u672a\u8986\u76d6\u5f53\u524d\u4ee3\u7801',
  browserQaGit: '\u6d4f\u89c8\u5668 QA Git',
  screenshotHashes: '\u622a\u56fe\u54c8\u5e0c',
  localAcceptanceCommand: '\u672c\u5730\u9a8c\u6536\u547d\u4ee4',
  sourceAcceptanceCommand: '\u6e90\u7801\u5305\u9a8c\u6536\u547d\u4ee4',
  localWorkbenchLabel: '\u81ea\u52a8\u5316\u5de5\u4f5c\u53f0',
  browserQaLabel: '\u6d4f\u89c8\u5668 QA',
  finalReportCenterQa: '\u6700\u7ec8\u62a5\u544a\u4e2d\u5fc3 QA',
  sourcePackageLabel: '\u6e90\u7801\u5305\u9a8c\u6536',
  sourcePackageNotRequired: '\u6e90\u7801\u5305\u9a8c\u6536 NOT_REQUIRED',
  sourcePackageNotRequiredCopy: '\u9ed8\u8ba4\u672c\u5730\u9a8c\u6536\u4e0d\u8981\u6c42\u6e90\u7801\u5305 clean',
  demoBatchButton: '\u521b\u5efa\u672c\u5730 dry_run \u6f14\u793a\u6279\u6b21',
  noDxmTouch: '\u4e0d\u89e6\u8fbe DXM',
  localDemoTask: '\u672c\u5730\u6f14\u793a\u6838\u9a8c\u6279\u6b21',
  localDemoStart: '\u542f\u52a8\u5f00\u53d1\u81ea\u68c0\u4efb\u52a1',
  l2RunIdFlag: '--run-id',
  l2RunIdVar: '$runId',
  l2SameBinding: '\u540c\u4e00 run-id',
  fallbackCopyPatterns: ['fallback \u6570\u636e', '\u6765\u6e90\uff1afallback', 'mock \u6216 fallback', 'mock or fallback'],
  unreleasedRealModeCopy: '\u0063\u006c\u0061\u0069\u006d\u005f\u006f\u006e\u006c\u0079/\u0062\u0061\u0074\u0063\u0068\u005f\u0073\u0061\u0076\u0065 \u5f53\u524d\u672a\u53d1\u5e03',
  unreleasedRealModeButtonDisabled: '\u672a\u53d1\u5e03\uff0c\u7981\u6b62\u542f\u52a8',
  controlledSingleSaveOnly: '\u4ec5\u53d7\u63a7\u5355\u5546\u54c1\u53ea\u4fdd\u5b58',
  realModeReleasePlanTitle: '\u8ba4\u9886 / \u6279\u91cf\u4fdd\u5b58\u653e\u884c\u51c6\u5907',
  claimOnlyUnreleased: '\u8ba4\u9886\u5f53\u524d\u672a\u53d1\u5e03',
  batchSaveUnreleased: '\u6279\u91cf\u4fdd\u5b58\u5f53\u524d\u672a\u53d1\u5e03',
  cannotReuseSingleSave: '\u4e0d\u80fd\u590d\u7528\u5355\u5546\u54c1\u53ea\u4fdd\u5b58\u8bc1\u636e',
  batchSizeLimit: '\u6279\u91cf\u5927\u5c0f\u4e0a\u9650',
  rollbackHandoff: '\u56de\u6eda/\u4eba\u5de5\u63a5\u7ba1',
  batchSaveNotRunner: '\u6279\u91cf\u4fdd\u5b58\u4e0d\u542f\u52a8\u771f\u5b9e\u6d4f\u89c8\u5668\u4fdd\u5b58',
  oldWaitSave: '\u7b49\u5f85\u4fdd\u5b58\u6838\u9a8c',
  oldVisibleBrowser: '\u6253\u5f00\u53ef\u89c1\u6d4f\u89c8\u5668',
  oldAutomation: '\u65c1\u89c2\u81ea\u52a8\u5316',
  fakePlaceholder: '\u8bca\u65ad\u5360\u4f4d',
  workspaceLoading: '\u6b63\u5728\u8bfb\u53d6 /api/delivery/workspace',
  currentTaskPrefix: '\u5f53\u524d\u4efb\u52a1 #',
  taskListDefaultUnique: '\u66f4\u591a\u4efb\u52a1\u64cd\u4f5c\u4e0e\u8bb0\u5f55',
};
function formatQaState(value) {
  return value === true ? 'PASS' : value === false ? 'FAIL' : '\u5f85\u5237\u65b0/\u672a\u8fd0\u884c';
}
await waitForTextGone(text.workspaceLoading, 12000);
await waitForWorkspaceSettled(20000);
if (reportOnlyFinal) {
  const clickedReports = await openReportCenter();
  await new Promise(r => setTimeout(r, 300));
  await evalValue('(() => { for (const label of ["\\u9a8c\\u6536\\u4eba\\u9644\\u5f55", "\\u91cd\\u65b0\\u9a8c\\u8bc1\\u53ea\\u8bfb\\u68c0\\u67e5"]) { const summary = [...document.querySelectorAll("summary")].find(item => (item.innerText || "").includes(label)); const details = summary ? summary.parentElement : null; if (summary && details && details.open !== true) summary.click(); } return true; })()');
  await new Promise(r => setTimeout(r, 300));
  const finalCheckSummary = await fetchJson('/api/delivery/final-check');
  const expectedSourcePackage = finalCheckSummary?.source_package_check === 'NOT_REQUIRED'
    ? text.sourcePackageNotRequired
    : text.sourcePackageLabel + ' ' + String(finalCheckSummary?.source_package_check ?? '\u672a\u68c0\u67e5');
  const expectedBrowserQa = text.browserQaLabel + ' ' + formatQaState(finalCheckSummary?.browser_qa_ok);
  const expectedLocalWorkbench = text.localWorkbenchLabel + ' ' + String(finalCheckSummary?.local_workbench_check ?? '\u672a\u68c0\u67e5');
  const expectedPostFinalReportQa = text.finalReportCenterQa + ' ' + formatQaState(finalCheckSummary?.post_final_report_qa_ok);
  const finalReportEffectiveReadiness = finalCheckSummary?.effective_real_dxm_write_readiness
    ?? finalCheckSummary?.real_dxm_write_readiness;
  const finalReportEffectiveMutationAllowed = finalCheckSummary?.effective_real_dxm_mutation_allowed
    ?? finalCheckSummary?.real_dxm_mutation_allowed;
  const finalReportEffectiveMutationScope = finalCheckSummary?.effective_real_dxm_mutation_scope
    ?? finalCheckSummary?.real_dxm_mutation_scope;
  const finalReportRealWriteBlocked = finalReportEffectiveReadiness === 'BLOCKED' && finalReportEffectiveMutationAllowed !== true;
  const finalReportReportWriteBlocked = finalCheckSummary?.real_dxm_write_readiness === 'BLOCKED'
    && finalCheckSummary?.real_dxm_mutation_allowed !== true;
  const finalReportReady = finalReportEffectiveReadiness === 'READY'
    && finalCheckSummary?.controlled_single_save_ready === true
    && finalReportEffectiveMutationAllowed === true
    && finalReportEffectiveMutationScope === 'controlled_single_save_only'
    && finalCheckSummary?.batch_unattended_publish_allowed === false;
  const expectedLockedEvidence = [text.saveResultLocked, text.unpublishedProofLocked, text.networkHarLocked];
  const requiredReportFragments = [
    text.finalCheck,
    expectedLocalWorkbench,
    expectedBrowserQa,
    expectedSourcePackage,
    ...(finalReportReportWriteBlocked ? [
      text.businessReportLocked,
      text.postL3ChecklistLocked,
      text.realWriteReleaseTitle,
      text.l2RealReadOnlyPassed,
      text.l3ManualCanaryApproved,
      text.saveEvidenceComplete,
      text.allowlistTemplateNotL2Pass,
    ] : []),
    ...(allowMissingPostFinalQa ? [] : ['qa-report-center-final.png']),
  ];
  const reportText = await waitForBodyIncludes(requiredReportFragments, 5000);
  const finalReportShot = await screenshot('qa-report-center-final');
  const finalReportCenterQaDomState = await evalValue('(() => { const el = document.querySelector("[data-testid=\\"final-report-center-qa\\"]"); return el ? el.getAttribute("data-state") : null; })()');
  const finalReportCenterScreenshotDomPath = await evalValue('(() => { const el = document.querySelector("[data-testid=\\"final-report-center-screenshot-path\\"]"); return el ? (el.innerText || el.textContent || "") : ""; })()');
  const reportCenterSectionVisible = await evalValue('Boolean(document.querySelector("[data-testid=\\"report-center-section\\"]"))');
  const finalReportBlockedStatusTone = await evalValue('(() => { const row = document.querySelector(".delivery-readiness-row"); return Boolean(row && row.className.includes("is-blocked") && (row.innerText || "").includes("BLOCKED")); })()');
  const lockedEvidenceRows = await evalValue('(() => [...document.querySelectorAll(".check-row[data-state=\\"locked\\"]")].map(el => ({ text: el.innerText || "", className: el.className || "" })))()');
  const lockedEvidenceRowsNeutral = Array.isArray(lockedEvidenceRows) && lockedEvidenceRows.length >= 3 && lockedEvidenceRows.every(row => String(row.className || '').includes('locked') && !String(row.className || '').includes('ok') && !String(row.className || '').includes('warn'));
  const guardDangerTexts = await evalValue('(() => [...document.querySelectorAll(".guard-chip--danger")].map(el => el.innerText || el.textContent || ""))()');
  const noL3PostEvidenceDangerChips = Array.isArray(guardDangerTexts) && !guardDangerTexts.some(value => {
    const chip = String(value || '');
    return chip.includes(text.saveResultGapTitle)
      || chip.includes(text.unpublishedProofGapTitle)
      || chip.includes(text.networkSaveResponseGapTitle);
  });
  const finalReportCenterQaDiagnostics = {
    expectedPostFinalReportQa,
    hasExpectedPostFinalReportQa: reportText.includes(expectedPostFinalReportQa),
    expectedLockedEvidence,
    lockedEvidenceRows,
    guardDangerTexts,
    hasExpectedLockedEvidenceRows: expectedLockedEvidence.every(fragment => reportText.includes(fragment)),
    hasExistingEvidenceRows: reportText.includes('\u4fdd\u5b58\u7ed3\u679c ')
      && reportText.includes('\u672a\u53d1\u5e03\u8bc1\u660e ')
      && reportText.includes('\u7f51\u7edc/HAR ')
      && !expectedLockedEvidence.every(fragment => reportText.includes(fragment)),
    lockedEvidenceRowsNotWarn: Array.isArray(lockedEvidenceRows) && lockedEvidenceRows.length >= 3 && lockedEvidenceRows.every(row => !String(row.className || '').includes('warn')),
    lockedEvidenceRowsNeutral,
    hasRealWriteReleasePrerequisites: reportText.includes(text.realWriteReleaseTitle)
      && reportText.includes(text.l2RealReadOnlyPassed)
      && reportText.includes(text.l3ManualCanaryApproved)
      && reportText.includes(text.saveEvidenceComplete)
      && reportText.includes(text.allowlistTemplateNotL2Pass),
    noL3PostEvidenceDangerChips,
    noL3PostEvidenceBlockerChips: noL3PostEvidenceDangerChips
      && !reportText.includes(text.oldSaveResultBlocker)
      && !reportText.includes(text.oldUnpublishedProofBlocker)
      && !reportText.includes(text.oldNetworkHarBlocker),
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
      finalReportCenterShowsBlockedDxmState: finalReportReady
        ? reportText.includes(text.realSingleSaveReady)
          && reportText.includes(text.readyLimitedCopy)
          && reportText.includes(text.batchUnattendedPublishBlocked)
        : reportText.includes(text.blockedExpectedState)
          && reportText.includes(text.noRealWrite)
          && finalReportBlockedStatusTone,
      finalReportBusinessReportLocked: !finalReportReportWriteBlocked
        || reportText.includes(text.businessReportLocked)
        || finalReportCenterQaDiagnostics.hasExistingEvidenceRows,
      finalReportPostL3ChecklistLocked: !finalReportReportWriteBlocked || reportText.includes(text.postL3ChecklistLocked),
      finalReportExpectedLockedEvidenceRows: !finalReportReportWriteBlocked
        || finalReportCenterQaDiagnostics.hasExpectedLockedEvidenceRows
        || finalReportCenterQaDiagnostics.hasExistingEvidenceRows,
      finalReportLockedEvidenceRowsNotWarn: !finalReportReportWriteBlocked || finalReportCenterQaDiagnostics.lockedEvidenceRowsNotWarn,
      finalReportLockedEvidenceRowsNeutral: !finalReportReportWriteBlocked || finalReportCenterQaDiagnostics.lockedEvidenceRowsNeutral,
      finalReportRealWriteReleasePrerequisites: finalReportCenterQaDiagnostics.hasRealWriteReleasePrerequisites,
      finalReportNoL3PostEvidenceBlockerChips: finalReportCenterQaDiagnostics.noL3PostEvidenceBlockerChips,
      finalReportApiIsFinal: allowMissingPostFinalQa || finalCheckSummary?.local_workbench_check === 'PASS'
        && finalCheckSummary?.browser_qa_ok === true
        && (
          finalReportReady
            ? finalCheckSummary?.ok_scope === 'local_workbench_and_controlled_single_save_ready'
              && finalReportEffectiveMutationAllowed === true
            : finalCheckSummary?.ok_scope === 'local_workbench_only'
              && finalReportEffectiveMutationAllowed === false
              && finalReportEffectiveReadiness === 'BLOCKED'
        ),
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
      browserPath,
      browserHeadlessMode,
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
const initialTextCompact = initialText.replace(/\s+/g, '');
const defaultWorkspacePayload = await fetchJson('/api/delivery/workspace');
const defaultCurrentTask = defaultWorkspacePayload?.current_task || null;
const defaultCurrentTaskId = defaultCurrentTask?.id ?? null;
const defaultCurrentTaskName = String(defaultCurrentTask?.name || '');
const defaultCurrentTaskCompleted = defaultCurrentTask?.status === 'completed';
const defaultCurrentTaskMarker = defaultCurrentTaskId ? (text.currentTaskPrefix + defaultCurrentTaskId) : '';
const defaultCurrentTaskAlternateMarker = defaultCurrentTaskId ? ('\u4efb\u52a1 #' + defaultCurrentTaskId) : '';
const defaultCurrentTaskText = await bodyText();
const defaultTaskSelectionState = {
  apiCurrentTaskId: defaultCurrentTaskId,
  apiCurrentTaskName: defaultCurrentTaskName,
  expectedCurrentTaskMarker: defaultCurrentTaskMarker,
  alternateCurrentTaskMarker: defaultCurrentTaskAlternateMarker,
  hasDeliveryCurrentTask: Boolean(defaultCurrentTaskId && (
    defaultCurrentTaskText.includes(defaultCurrentTaskMarker)
    || defaultCurrentTaskText.includes(defaultCurrentTaskAlternateMarker)
  )),
  avoidsLatestUnreleasedDefault: !unreleasedRealModeTask?.id
    || defaultCurrentTaskId === unreleasedRealModeTask.id
    || !defaultCurrentTaskText.includes(text.currentTaskPrefix + unreleasedRealModeTask.id),
};
const clickedConfig = await clickSelector('[data-section="config"]') || await clickText(text.config);
await new Promise(r => setTimeout(r, 700));
await evalValue('(() => { const summary = [...document.querySelectorAll("summary")].find(item => (item.innerText || "").includes("\u5fae\u8c03\u5f53\u524d\u914d\u7f6e") || (item.innerText || "").includes("\u7ee7\u7eed\u586b\u5199")); const details = summary ? summary.parentElement : null; if (summary && details && details.open !== true) summary.click(); return Boolean(summary); })()');
await new Promise(r => setTimeout(r, 350));
await evalValue('(() => { const summary = [...document.querySelectorAll("summary")].find(item => (item.innerText || "").includes("\u66f4\u591a\u7f16\u8f91\u9875\u5206\u533a")); const details = summary ? summary.parentElement : null; if (summary && details && details.open !== true) summary.click(); return Boolean(summary); })()');
await new Promise(r => setTimeout(r, 250));
const configText = await bodyText();
const configHasRequiredSummary = configText.includes(text.nextRequiredConfig) || configText.includes(text.configReadySummary);
const configHasTemplateScope = configText.includes(text.currentTemplateScope);
let configHasListEditor = await evalValue('(() => [...document.querySelectorAll(".editable-config-section__fields label")].some(label => { const textarea = label.querySelector("textarea"); const content = String(label.innerText || label.textContent || "") + " " + String(textarea?.getAttribute("placeholder") || ""); return Boolean(textarea) && content.includes(' + JSON.stringify(text.onePerLine) + '); }))()');
const configSectionTabState = await evalValue('(() => { const tabs = [...document.querySelectorAll(".config-section-tabs button")]; const focused = [...document.querySelectorAll(".editable-config-grid--focused .editable-config-section")]; return { tabCount: tabs.length, focusedCount: focused.length, hasSelected: tabs.some(tab => tab.getAttribute("aria-selected") === "true") }; })()');
const switchedConfigSection = await evalValue('(() => { const target = [...document.querySelectorAll(".config-section-tabs button")].find(tab => (tab.innerText || "").includes(' + JSON.stringify(text.logisticsSection) + ')); if (!target) return false; target.click(); return true; })()');
await new Promise(r => setTimeout(r, 350));
const configTextAfterSectionSwitch = await bodyText();
const configSectionSwitchState = await evalValue('(() => { const focused = [...document.querySelectorAll(".editable-config-grid--focused .editable-config-section")]; return { focusedCount: focused.length, selectedLogistics: document.body.innerText.includes(' + JSON.stringify(text.currentEditingSection + '\uff1a' + text.logisticsSection) + '), hasWeightField: document.body.innerText.includes(' + JSON.stringify(text.weightField) + ') }; })()');
const configTaskOverridePayloadState = await evalValue(' (async () => { window.__dxmQaConfigOverrideSaves = []; if (!window.__dxmQaOriginalFetch) { window.__dxmQaOriginalFetch = window.fetch.bind(window); window.fetch = async (input, init = {}) => { const url = typeof input === "string" ? input : String(input && input.url ? input.url : input); const method = String(init && init.method ? init.method : "GET").toUpperCase(); if (method === "PATCH" && url.includes("/api/tasks/") && url.includes("/config-overrides")) { window.__dxmQaConfigOverrideSaves.push({ url, method, body: init.body || "" }); return new Response(JSON.stringify({ id: 0, status: "qa_intercepted" }), { status: 200, headers: { "content-type": "application/json" } }); } return window.__dxmQaOriginalFetch(input, init); }; } const focused = document.querySelector(".editable-config-grid--focused .editable-config-section"); const label = focused ? [...focused.querySelectorAll("label")].find(item => (item.innerText || "").includes(' + JSON.stringify(text.weightField) + ')) : null; const input = label ? label.querySelector("input, textarea") : null; if (!input) return { ok: false, reason: "weight input missing" }; const value = "0.123"; const proto = input.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype; const descriptor = Object.getOwnPropertyDescriptor(proto, "value"); descriptor.set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); await new Promise(r => setTimeout(r, 100)); const saveButton = focused ? [...focused.querySelectorAll("button")].find(button => (button.innerText || "").includes(' + JSON.stringify(text.taskOverrideSave) + ')) : null; if (!saveButton) return { ok: false, reason: "task override button missing" }; saveButton.click(); const deadline = Date.now() + 2500; while (Date.now() < deadline && window.__dxmQaConfigOverrideSaves.length < 1) { await new Promise(r => setTimeout(r, 100)); } const saved = window.__dxmQaConfigOverrideSaves[0] || null; let parsed = null; try { parsed = saved ? JSON.parse(saved.body || "{}") : null; } catch {} return { ok: Boolean(saved && parsed && parsed.section === "logistics" && parsed.values && String(parsed.values.weight) === value), captured: Boolean(saved), parsed, value }; })()');
const configAllText = configText + ' ' + configTextAfterSectionSwitch;
if (!configHasListEditor) {
  configHasListEditor = await evalValue('(() => [...document.querySelectorAll(".editable-config-section__fields label")].some(label => { const textarea = label.querySelector("textarea"); const content = String(label.innerText || label.textContent || "") + " " + String(textarea?.getAttribute("placeholder") || ""); return Boolean(textarea) && content.includes(' + JSON.stringify(text.onePerLine) + '); }))()');
}
const configShot = await screenshot('qa-config-center');
const desktopReflow = await evalValue('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1');
const desktopOverflow = await horizontalOverflowState();
const clickedTasks = await clickSelector('[data-section="tasks"]') || await clickText(text.tasks);
await waitForWorkspaceSettled(12000);
await new Promise(r => setTimeout(r, 700));
const taskDefaultText = await bodyText();
defaultTaskSelectionState.taskCenterTextSample = taskDefaultText.slice(0, 1200);
defaultTaskSelectionState.hasDeliveryCurrentTask = Boolean(defaultCurrentTaskId && (
  defaultCurrentTaskText.includes(defaultCurrentTaskMarker) || taskDefaultText.includes(defaultCurrentTaskMarker)
  || defaultCurrentTaskText.includes(defaultCurrentTaskAlternateMarker) || taskDefaultText.includes(defaultCurrentTaskAlternateMarker)
));
defaultTaskSelectionState.avoidsLatestUnreleasedDefault = !unreleasedRealModeTask?.id
  || defaultCurrentTaskId === unreleasedRealModeTask.id
  || !taskDefaultText.includes(text.currentTaskPrefix + unreleasedRealModeTask.id);
const taskDrawerState = await evalValue('(() => { const support = document.querySelector(".task-support-drawer"); const create = document.querySelector(".task-create-drawer"); const release = document.querySelector(".task-release-drawer"); const history = document.querySelector(".task-history-drawer"); return { hasCurrentPanel: Boolean(document.querySelector(".task-current-panel")), hasSupportDrawer: Boolean(support), supportOpen: support ? support.open === true : null, hasCreateDrawer: Boolean(create), createOpen: create ? create.open === true : null, hasReleaseDrawer: Boolean(release), releaseOpen: release ? release.open === true : null, hasHistoryDrawer: Boolean(history), historyOpen: history ? history.open === true : null, taskHistoryDrawer: Boolean(history), releaseBoundaryDrawer: Boolean(release), defaultText: document.body.innerText || "" }; })()');
const taskQuickActionsState = await evalValue('(() => { const quick = document.querySelector(".task-quick-actions"); const create = document.querySelector("[data-testid=\\"task-quick-create-single-save\\"]"); const quickRect = quick ? quick.getBoundingClientRect() : null; const createRect = create ? create.getBoundingClientRect() : null; return { hasQuickActions: Boolean(quick), quickText: quick ? (quick.innerText || quick.textContent || "") : "", quickInFirstViewport: Boolean(quickRect && quickRect.top >= 0 && quickRect.top < window.innerHeight && quickRect.height > 0), createVisible: Boolean(createRect && createRect.width > 0 && createRect.height > 0 && createRect.top >= 0 && createRect.top < window.innerHeight), createDisabled: create instanceof HTMLButtonElement ? create.disabled : null }; })()');
let unreleasedRealModeTaskSelected = !unreleasedRealModeTask;
if (unreleasedRealModeTask) {
  await evalValue('(() => { const quickHistory = [...document.querySelectorAll("button")].find(button => (button.innerText || "").includes("\u9009\u62e9\u5386\u53f2\u4efb\u52a1")); if (quickHistory) quickHistory.click(); const history = document.querySelector(".task-history-drawer"); if (history) history.open = true; const showAll = [...document.querySelectorAll("button")].find(button => (button.innerText || "").includes("显示全部历史任务")); if (showAll) showAll.click(); return Boolean(history); })()');
  await new Promise(r => setTimeout(r, 700));
  unreleasedRealModeTaskSelected = await clickTaskByName(unreleasedRealModeTask.name);
  await new Promise(r => setTimeout(r, 900));
}
await evalValue('(() => { const supportSummary = document.querySelector(".task-support-drawer > summary"); const support = supportSummary ? supportSummary.parentElement : null; if (supportSummary && support && support.open !== true) supportSummary.click(); [".task-release-drawer > summary", ".task-history-drawer > summary"].forEach(selector => { const summary = document.querySelector(selector); const details = summary ? summary.parentElement : null; if (summary && details && details.open !== true) summary.click(); }); return true; })()');
await new Promise(r => setTimeout(r, 300));
const taskText = await bodyText();
const taskStartDisabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes("\u7981\u6b62\u542f\u52a8")); return Boolean(button && button.disabled); })()');
const unreleasedRealModeStartButtonDisabled = taskStartDisabled && taskText.includes(text.unreleasedRealModeButtonDisabled);
const taskShot = await screenshot('qa-task-center');
const clickedConsole = await clickSelector('[data-section="console"]') || await clickText(text.console);
await new Promise(r => setTimeout(r, 700));
await evalValue('(() => { const details = document.querySelector(".console-review-panel__browser"); const summary = details ? details.querySelector(":scope > summary") : [...document.querySelectorAll("summary")].find(item => (item.innerText || "").includes("\u7ee7\u7eed\u64cd\u4f5c\u771f\u5b9e\u6d4f\u89c8\u5668")); const target = details || (summary ? summary.parentElement : null); if (target && target.open !== true) target.open = true; return Boolean(target); })()');
await new Promise(r => setTimeout(r, 350));
await evalValue('(() => { [".agent-console-controls__operator-drawer", ".agent-console-controls__advanced"].forEach(selector => { const details = document.querySelector(selector); if (details) details.open = true; }); return true; })()');
await new Promise(r => setTimeout(r, 350));
const consoleText = await bodyText();
const consoleDomText = await evalValue('document.body.textContent || ""');
const consoleRuntimeLogState = await evalValue('(() => { const preview = document.querySelector(".runtime-log-preview"); const compactTabs = [...document.querySelectorAll(".runtime-log-tabs--compact button")]; const fullPanel = document.querySelector(".runtime-log-panel"); const view = document.querySelector("[data-testid=\\"runtime-log-view\\"]"); const previewRect = preview ? preview.getBoundingClientRect() : null; return { previewVisible: Boolean(previewRect && previewRect.width > 0 && previewRect.height > 0 && previewRect.top < window.innerHeight), sourceCount: compactTabs.length, sourceLabels: compactTabs.map(button => (button.innerText || button.textContent || "").trim()), hasFullPanel: Boolean(fullPanel), hasRuntimeLogView: Boolean(view), previewText: preview ? (preview.innerText || preview.textContent || "") : "" }; })()');
const consoleStartDisabled = await evalValue('(() => { const buttons = [...document.querySelectorAll("button")]; const button = buttons.find(el => (el.innerText || "").includes(' + JSON.stringify(text.executionObserve) + ')); return Boolean(button && button.disabled); })()');
const consoleLoginFormDomState = await evalValue('(() => { const forms = [...document.querySelectorAll(".operator-inline-form")]; const loginForm = forms.find(form => (form.innerText || "").includes("\u767b\u5f55/\u4eba\u5de5\u5904\u7406\u771f\u5b9e\u6d4f\u89c8\u5668")) || null; const inputs = loginForm ? [...loginForm.querySelectorAll("input")] : []; const username = inputs.find(input => input.autocomplete === "username" || input.placeholder.includes("DXM") || input.type === "text") || null; const password = inputs.find(input => input.autocomplete === "current-password" || input.placeholder.includes("\u672c\u6b21\u767b\u5f55") || input.type === "password") || null; const buttons = loginForm ? [...loginForm.querySelectorAll("button")] : []; const openRealLoginPage = buttons.some(button => (button.innerText || "").includes("\u6253\u5f00\u771f\u5b9e\u767b\u5f55\u9875")); const dxmUsername = Boolean(username); const dxmPassword = Boolean(password); const passwordType = password ? password.type : null; const passwordCleared = password ? String(password.value || "") === "" : true; return { hasForm: Boolean(loginForm), dxmUsername, dxmPassword, openRealLoginPage, passwordType, passwordProtected: passwordType === "password", passwordCleared, passwordEmpty: passwordCleared === true }; })()');
const consoleLoginFormSourceContract = "passwordType === 'password' && passwordCleared === true";
const realMutationApprovalDomState = await evalValue('(() => { const forms = [...document.querySelectorAll(".operator-inline-form")]; const approvalForm = forms.find(form => (form.innerText || "").includes("\u4eba\u5de5\u786e\u8ba4\u771f\u5b9e\u4fdd\u5b58")) || null; const input = approvalForm ? approvalForm.querySelector("input") : null; const button = approvalForm ? [...approvalForm.querySelectorAll("button")].find(item => (item.innerText || "").includes("\u7533\u8bf7\u5e76\u542f\u52a8\u5355\u5546\u54c1\u53ea\u4fdd\u5b58")) : null; const l3Approver = Boolean(input); return { hasForm: Boolean(approvalForm), l3Approver, hasStartButton: Boolean(button), buttonDisabled: button ? button.disabled === true : null }; })()');
const consoleShot = await screenshot('qa-execution-console');
const clickedReports = await openReportCenter();
await new Promise(r => setTimeout(r, 700));
await evalValue('(() => { for (const label of ["\\u9a8c\\u6536\\u4eba\\u9644\\u5f55", "\\u91cd\\u65b0\\u9a8c\\u8bc1\\u53ea\\u8bfb\\u68c0\\u67e5"]) { const summary = [...document.querySelectorAll("summary")].find(item => (item.innerText || "").includes(label)); const details = summary ? summary.parentElement : null; if (summary && details && details.open !== true) summary.click(); } return true; })()');
await new Promise(r => setTimeout(r, 350));
const reportText = await bodyText();
const finalCheckSummaryForReport = await fetchJson('/api/delivery/final-check');
const reportBlockedStatusTone = await evalValue('(() => { const row = document.querySelector(".check-row[data-state=\\"locked\\"]"); return Boolean(row && (row.innerText || "").includes("\u6682\u4e0d\u542f\u52a8\u771f\u5b9e\u4fdd\u5b58")); })()');
const reportAcceptanceCommands = await evalValue('(() => [...document.querySelectorAll(".delivery-check-card__commands code")].map(el => (el.innerText || el.textContent || "").trim()))()');
const l2CommandBlocks = await evalValue('(() => [...document.querySelectorAll(".l2-next-step-card__commands code")].map(el => (el.innerText || el.textContent || "").trim()))()');
const reportLockedEvidenceRows = await evalValue('(() => [...document.querySelectorAll(".check-row[data-state=\\"locked\\"]")].map(el => ({ text: el.innerText || "", className: el.className || "" })))()');
const reportLockedEvidenceRowsNeutral = Array.isArray(reportLockedEvidenceRows) && reportLockedEvidenceRows.length >= 3 && reportLockedEvidenceRows.every(row => String(row.className || '').includes('locked') && !String(row.className || '').includes('ok') && !String(row.className || '').includes('warn'));
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
await waitForWorkspaceSettled(16000);
const mobileInitialText = await bodyText();
const clickedMobileTasks = await clickSelector('[data-section="tasks"]') || await clickText(text.tasks);
await new Promise(r => setTimeout(r, 700));
const mobileTaskText = await bodyText();
const mobileReflow = await evalValue('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1');
const mobileOverflow = await horizontalOverflowState();
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
function isIgnorableNetworkFailure(event) {
  return event.type === 'failed' && !event.url && !String(event.errorText || '').trim();
}
const failedNetworkEvents = networkEvents.filter(event => event.type === 'failed' && !isIgnorableNetworkFailure(event));
const ignoredFailedCount = networkEvents.filter(isIgnorableNetworkFailure).length;
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
const screenshotPaths = [configShot, taskShot, consoleShot, reportShot, mobileShot];
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
await clickSelector('[data-section="tasks"]') || await clickText(text.tasks);
await new Promise(r => setTimeout(r, 500));
const taskTextAfterDefaultDemoCheck = await bodyText();
const demoBatchHiddenByDefault = !taskTextAfterDefaultDemoCheck.includes(text.demoBatchButton)
  && !taskTextAfterDefaultDemoCheck.includes(text.localDemoStart);
const hasLocalAcceptanceCommand = Array.isArray(reportAcceptanceCommands) && reportAcceptanceCommands.some(command => /scripts[\\/]+final-delivery-check\.bat$/.test(command));
const hasSourceAcceptanceCommand = Array.isArray(reportAcceptanceCommands) && reportAcceptanceCommands.some(command => /scripts[\\/]+final-delivery-check\.bat\s+-RequireCleanWorktree$/.test(command));
const hasRunIdSetup = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('$runId') && command.includes('Get-Date'));
const hasDataAcquisitionRunId = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('--target data_acquisition') && command.includes('--run-id $runId'));
const hasDraftBoxRunId = Array.isArray(l2CommandBlocks) && l2CommandBlocks.some(command => command.includes('--target draft_box') && command.includes('--run-id $runId'));
const userFacingText = initialText + ' ' + taskText + ' ' + consoleText + ' ' + reportText;
const finalCheckRequiresNotRequiredCopy = finalCheckSummaryForReport?.source_package_check === 'NOT_REQUIRED';
const finalCheckEffectiveReadiness = finalCheckSummaryForReport?.effective_real_dxm_write_readiness
  ?? finalCheckSummaryForReport?.real_dxm_write_readiness;
const finalCheckEffectiveMutationAllowed = finalCheckSummaryForReport?.effective_real_dxm_mutation_allowed
  ?? finalCheckSummaryForReport?.real_dxm_mutation_allowed;
const finalCheckEffectiveMutationScope = finalCheckSummaryForReport?.effective_real_dxm_mutation_scope
  ?? finalCheckSummaryForReport?.real_dxm_mutation_scope;
const finalCheckRealWriteBlocked = finalCheckEffectiveReadiness === 'BLOCKED' && finalCheckEffectiveMutationAllowed !== true;
const finalCheckReportWriteBlocked = finalCheckSummaryForReport?.real_dxm_write_readiness === 'BLOCKED'
  && finalCheckSummaryForReport?.real_dxm_mutation_allowed !== true;
const reportExistingEvidenceRows = reportText.includes('\u4fdd\u5b58\u7ed3\u679c ')
  && reportText.includes('\u672a\u53d1\u5e03\u8bc1\u660e ')
  && reportText.includes('\u7f51\u7edc/HAR ');
const finalCheckExpectedReady = finalCheckEffectiveReadiness === 'READY'
  && finalCheckSummaryForReport?.controlled_single_save_ready === true
  && finalCheckEffectiveMutationAllowed === true
  && finalCheckEffectiveMutationScope === 'controlled_single_save_only'
  && finalCheckSummaryForReport?.batch_unattended_publish_allowed === false;
const result = {
  checkedAt: new Date().toISOString(),
  url: targetUrl,
  ok: true,
  assertions: {
    initialLoaded: initialText.includes(text.hero) || initialText.includes(text.appName),
    navClicksWorked: clickedTasks && clickedConsole && clickedReports,
    localizedOverviewNav: initialText.includes(text.overview),
    defaultTaskSelectionPrefersDeliveryCurrentTask: defaultTaskSelectionState.hasDeliveryCurrentTask
      && defaultTaskSelectionState.avoidsLatestUnreleasedDefault,
    firstScreenExpectedBlockedScope: initialTextCompact.includes('\u81ea\u52a8\u5316\u5de5\u4f5c\u53f0')
      && (finalCheckExpectedReady
        ? initialText.includes(text.realSingleSaveReady)
          || initialText.includes('single_save READY')
          || initialText.includes('\u7b49\u5f85\u4eba\u5de5\u786e\u8ba4')
          || initialText.includes('\u5f53\u524d\u4efb\u52a1\u5df2\u5b8c\u6210')
          || initialText.includes('\u53ea\u4fdd\u5b58\uff0c\u4e0d\u53d1\u5e03')
          || initialText.includes('\u53ef\u7533\u8bf7\u5355\u5546\u54c1\u53ea\u4fdd\u5b58')
        : initialText.includes('\u5f53\u524d\u4efb\u52a1\u5df2\u5b8c\u6210')
          || initialText.includes('\u771f\u5b9e\u4fdd\u5b58\u5df2\u963b\u65ad')
          || initialText.includes('\u53ea\u8bfb\u68c0\u67e5\u8bc1\u636e\u5df2\u8fc7\u671f')
          || (initialTextCompact.includes('\u73b0\u5728\u53ea\u505a\u8fd9\u4e00\u6b65')
          && initialTextCompact.includes(text.realWriteGateFailed.replace(/\s+/g, ''))
          && initialTextCompact.includes('\u67e5\u770b\u5b8c\u6574 8 \u6b65\u6d41\u7a0b'.replace(/\s+/g, '')))),
    configCenterTaskOverrideControls: clickedConfig && configTaskOverridePayloadState.ok === true,
    configCenterSectionNavigation: clickedConfig
      && configText.includes(text.configStepMeta)
      && configText.includes(text.currentEditingSection)
      && configText.includes(text.otherConfigSections)
      && configSectionTabState.tabCount >= 9
      && configSectionTabState.focusedCount === 1
      && configSectionTabState.hasSelected === true
      && switchedConfigSection === true
      && configSectionSwitchState.focusedCount === 1
      && configSectionSwitchState.selectedLogistics === true
      && configSectionSwitchState.hasWeightField === true
      && configTextAfterSectionSwitch.includes(text.weightField),
    configCenterTaskOverridePayloadUsesTypedValue: configTaskOverridePayloadState.ok === true,
    localWriteCopy: !taskText.includes(text.localWrite) && (taskText.includes('single_save') || taskText.includes('\u5355\u5546\u54c1\u53ea\u4fdd\u5b58')),
    taskListCompactedByDefault: taskDrawerState.taskHistoryDrawer === true
      && taskDefaultText.includes(text.taskListDefaultUnique)
      && taskDrawerState.historyOpen !== true,
    taskCenterCurrentFirst: taskDrawerState.hasCurrentPanel === true,
    taskQuickActionsVisible: taskQuickActionsState.hasQuickActions === true
      && taskQuickActionsState.quickInFirstViewport === true
      && taskQuickActionsState.quickText.includes('\u521b\u5efa\u5355\u5546\u54c1\u53ea\u4fdd\u5b58\u4efb\u52a1')
      && taskQuickActionsState.quickText.includes('\u8865\u9f50\u7f16\u8f91\u9875\u914d\u7f6e')
      && taskQuickActionsState.quickText.includes('\u9009\u62e9\u5386\u53f2\u4efb\u52a1'),
    taskQuickCreateVisible: taskQuickActionsState.createVisible === true
      && taskQuickActionsState.createDisabled === false,
    taskInlineL3Approval: taskText.includes('\u5355\u5546\u54c1\u53ea\u4fdd\u5b58') && taskText.includes('\u4eba\u5de5\u786e\u8ba4'),
    singleSaveRecoveryGuideVisible: finalCheckExpectedReady || defaultCurrentTaskCompleted || taskText.includes('\u91cd\u65b0\u9a8c\u8bc1') || taskText.includes('\u4fee\u590d'),
    taskRecoveryActions: finalCheckExpectedReady || defaultCurrentTaskCompleted || ((taskText.includes(text.readonlyDiag) || taskText.includes(text.l2BlockHelp) || taskText.includes('\u67e5\u770b\u963b\u65ad\u8bf4\u660e') || taskText.includes('\u8fd0\u884c\u53ea\u8bfb\u590d\u9a8c')) && taskText.includes(text.evidenceGap)),
    taskStartBlockedCopy: finalCheckExpectedReady || defaultCurrentTaskCompleted || taskText.includes(text.forbiddenStart) || taskText.includes('\u771f\u5b9e\u4fdd\u5b58\u5df2\u963b\u65ad'),
    taskStartButtonDisabled: finalCheckExpectedReady || defaultCurrentTaskCompleted || taskStartDisabled,
    realModeReleasePlanVisible: finalCheckExpectedReady
      ? reportText.includes(text.readyLimitedCopy) && reportText.includes(text.batchUnattendedPublishBlocked)
      : taskText.includes(text.realModeReleasePlanTitle)
        && taskText.includes(text.claimOnlyUnreleased)
        && taskText.includes(text.batchSaveUnreleased)
        && taskText.includes(text.cannotReuseSingleSave)
        && taskText.includes(text.batchSizeLimit)
        && taskText.includes(text.rollbackHandoff)
        && taskText.includes(text.batchSaveNotRunner)
        && taskText.includes(text.controlledSingleSaveOnly),
    desktopNoHorizontalOverflow: desktopReflow === true && desktopOverflow.ok === true,
    mobileLoaded: mobileInitialText.includes(text.hero) || mobileInitialText.includes(text.appName),
    mobileNavWorked: clickedMobileTasks && (mobileTaskText.includes('single_save') || mobileTaskText.includes('\u5355\u5546\u54c1\u53ea\u4fdd\u5b58')),
    mobileNoHorizontalOverflow: mobileReflow === true && mobileOverflow.ok === true,
    consoleReadonlyCopy: consoleText.includes(text.readonly) && consoleText.includes(text.noSaveStart),
    consoleRealBrowserLoginEntry: consoleText.includes(text.loginManualBrowser)
      && (consoleText.includes(text.executionObserve) || consoleText.includes('\u4fdd\u5b58\u524d\u4ecd\u9700\u786e\u8ba4')),
    consoleInlineOperatorForms: consoleLoginFormDomState.hasForm === true
      && consoleLoginFormDomState.dxmUsername === true
      && consoleLoginFormDomState.dxmPassword === true
      && consoleLoginFormDomState.openRealLoginPage === true
      && consoleLoginFormDomState.passwordType === 'password'
      && consoleLoginFormDomState.passwordCleared === true
      && consoleLoginFormSourceContract.includes("passwordType === 'password'")
      && (realMutationApprovalDomState.hasForm === true
        || (consoleDomText.includes('\u63a7\u5236\u53f0 Agent \u6a21\u5f0f')
          && consoleDomText.includes('\u4eba\u5de5\u653e\u884c\u540e\u53ea\u4fdd\u5b58'))),
    consoleBrowserControlPad: (consoleText.includes(text.browserControlPad)
      && consoleText.includes(text.browserControlTypedInput)
      && consoleText.includes(text.browserControlClickCoords)
      && consoleText.includes(text.browserControlSelector)
      && consoleText.includes(text.browserControlSelectorClick)
      && consoleText.includes(text.browserControlSelectorFill)
      && consoleText.includes(text.browserControlWindowScope))
      || (consoleDomText.includes('\u63a7\u5236\u53f0 Agent \u6a21\u5f0f')
        && consoleDomText.includes('\u9875\u9762\u52a8\u4f5c\u6765\u81ea\u4efb\u52a1\u914d\u7f6e\u548c\u4eba\u5de5\u653e\u884c')),
    consoleRuntimeLogPreviewVisible: consoleRuntimeLogState.previewVisible === true
      && consoleRuntimeLogState.previewText.includes('\u8fd0\u884c\u65e5\u5fd7')
      && consoleRuntimeLogState.previewText.includes('\u6b63\u5728\u5b9e\u65f6\u5237\u65b0'),
    consoleRuntimeLogSourcesVisible: consoleRuntimeLogState.sourceCount >= 6
      && consoleRuntimeLogState.sourceLabels.includes('\u540e\u7aef')
      && consoleRuntimeLogState.sourceLabels.includes('\u524d\u7aef')
      && consoleRuntimeLogState.sourceLabels.includes('\u542f\u52a8\u5668')
      && consoleRuntimeLogState.sourceLabels.includes('\u4efb\u52a1')
      && consoleRuntimeLogState.sourceLabels.includes('\u6d4f\u89c8\u5668 Agent'),
    consoleNoFakeBrowser: consoleText.includes(text.noBrowser) && consoleText.includes(text.noFakeEvidence),
    consoleStartButtonDisabled: finalCheckExpectedReady || consoleStartDisabled,
    consoleNoFakePlaceholder: !(consoleText + ' ' + taskText).includes(text.fakePlaceholder),
    reportDeliveryCheckVisible: reportText.includes(text.finalCheck)
      && (finalCheckExpectedReady
        ? reportText.includes(text.realSingleSaveReady) && reportText.includes(text.batchUnattendedPublishBlocked)
        : reportText.includes(text.expectedBlocked) || reportText.includes('\u6682\u4e0d\u542f\u52a8\u771f\u5b9e\u4fdd\u5b58')),
    reportFreshnessVisible: (reportText.includes(text.finalCheckCurrent) || reportText.includes(text.finalCheckStale)) && reportText.includes(text.browserQaGit) && reportText.includes(text.screenshotHashes),
    reportBlockedStatusLanguage: finalCheckExpectedReady
      ? reportText.includes(text.readyLimitedCopy) && reportText.includes('\u6279\u91cf\u3001\u65e0\u4eba\u503c\u5b88\u548c\u53d1\u5e03')
      : reportText.includes(text.blockedExpectedState) && reportText.includes(text.noRealWrite) && reportBlockedStatusTone,
    reportBusinessReportLocked: !finalCheckReportWriteBlocked || reportText.includes(text.businessReportLocked) || reportExistingEvidenceRows,
    reportPostL3ChecklistLocked: !finalCheckReportWriteBlocked || reportText.includes(text.postL3ChecklistLocked),
    reportLockedEvidenceRowsNeutral: !finalCheckReportWriteBlocked || reportLockedEvidenceRowsNeutral,
    reportRealWriteReleasePrerequisites: reportText.includes(text.realWriteReleaseTitle)
      && reportText.includes(text.l2RealReadOnlyPassed)
      && reportText.includes(text.l3ManualCanaryApproved)
      && reportText.includes(text.saveEvidenceComplete)
      && reportText.includes(text.allowlistTemplateNotL2Pass),
    reportNoL3PostEvidenceBlockerChips: !finalCheckReportWriteBlocked || (!reportText.includes(text.oldSaveResultBlocker)
      && !reportText.includes(text.oldUnpublishedProofBlocker)
      && !reportText.includes(text.oldNetworkHarBlocker)),
    reportDualAcceptanceCommands: reportText.includes(text.localAcceptanceCommand) && reportText.includes(text.sourceAcceptanceCommand) && hasLocalAcceptanceCommand && hasSourceAcceptanceCommand,
    reportL2RunBindingCopy: reportText.includes(text.l2SameBinding) && hasRunIdSetup && hasDataAcquisitionRunId && hasDraftBoxRunId,
    reportSourcePackageNotRequiredCopy: !finalCheckRequiresNotRequiredCopy || (reportText.includes(text.sourcePackageNotRequired) && reportText.includes(text.sourcePackageNotRequiredCopy)),
    demoBatchHiddenByDefault: demoBatchHiddenByDefault,
    unreleasedRealModeTaskSelected: unreleasedRealModeTaskSelected,
    unreleasedRealModeCopy: finalCheckExpectedReady
      ? reportText.includes(text.readyLimitedCopy) && reportText.includes(text.batchUnattendedPublishBlocked)
      : taskText.includes(text.unreleasedRealModeButtonDisabled)
        && (taskText.includes(text.unreleasedRealModeCopy)
          || taskText.includes(text.controlledSingleSaveOnly)
          || taskText.includes('\u6279\u91cf\u4fdd\u5b58\u672a\u653e\u884c')
          || taskText.includes('\u53d1\u5e03\u52a8\u4f5c\u672a\u5f00\u653e')),
    unreleasedRealModeButtonDisabled: finalCheckExpectedReady || unreleasedRealModeStartButtonDisabled,
    noDeveloperFallbackCopy: text.fallbackCopyPatterns.every(pattern => !userFacingText.includes(pattern)),
    localStartPostBlocked: !shouldRunBlockedMutationChecks || blockedStartStatus === 403,
    localAgentConsolePostBlocked: !shouldRunBlockedMutationChecks || blockedAgentConsoleStatus === 403,
    localDirectDxmPostsBlocked: !shouldRunBlockedMutationChecks || blockedActionsAllForbidden,
    blockedPostsDidNotMutateTask: taskStateUnchanged,
    noOldActionCopy: !(consoleText + ' ' + taskText).includes(text.oldWaitSave)
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
  diagnostics: {
    defaultTaskSelectionState,
    taskDrawerState,
    taskQuickActionsState,
    configTaskOverridePayloadState,
    consoleLoginFormDomState,
    consoleRuntimeLogState,
    realMutationApprovalDomState,
  },
  networkSummary: {
    eventCount: networkEvents.length,
    failedCount: failedNetworkEvents.length,
    ignoredFailedCount,
    badResponseCount: badNetworkResponses.length,
    unexpectedMethodCount: unexpectedNetworkMethods.length,
    unexpectedHostCount: unexpectedNetworkHosts.length,
    allowedHostname,
    allowedOrigins: [...allowedOrigins],
    blockedStartStatus,
    blockedAgentConsoleStatus,
    desktopOverflow,
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
    browserPath,
    browserHeadlessMode,
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
  if ($userData -and (Test-Path -LiteralPath $userData)) {
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
