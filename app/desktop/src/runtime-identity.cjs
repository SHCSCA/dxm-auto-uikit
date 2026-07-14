const crypto = require('node:crypto')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const RUNTIME_IDENTITY_SCHEMA_VERSION = 'dxm.runtime.identity.v1'
const BUILD_MANIFEST_SCHEMA_VERSION = 'dxm.desktop.build.v1'
const BROWSER_EXECUTION_MODEL = 'in_process_thread'
const SHA256_RE = /^[0-9a-fA-F]{64}$/
const IDENTITY_ENV_KEYS = [
  'DXM_BUILD_MANIFEST_JSON',
  'DXM_BUILD_MANIFEST_FILE',
  'DXM_PACKAGE_SHA256',
  'DXM_BACKEND_INSTANCE_ID',
  'DXM_DATA_DIR',
  'DXM_RESOURCE_ROOT',
  'DXM_WORKFLOW_PROFILE_DIR',
  'DXM_GIT_HEAD',
  'DXM_GIT_DIRTY',
  'DXM_BUILD_ID',
  'DXM_PACKAGE_VERSION',
  'DXM_BUILD_GIT_HEAD',
  'DXM_BUILD_GIT_DIRTY',
  'DXM_BUILD_AT',
  'PORTABLE_EXECUTABLE_FILE',
  'PORTABLE_EXECUTABLE_DIR',
  'PORTABLE_EXECUTABLE_APP_FILENAME',
]

function canonicalJson(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') {
    return JSON.stringify(value)
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('canonical JSON does not support non-finite numbers')
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`
  }
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => {
      if (value[key] === undefined) throw new TypeError(`canonical JSON does not support undefined at ${key}`)
      return `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    }).join(',')}}`
  }
  throw new TypeError(`canonical JSON does not support ${typeof value}`)
}

function fingerprintPayload(payload) {
  return crypto.createHash('sha256').update(canonicalJson(payload), 'utf8').digest('hex').toUpperCase()
}

function normalizeIdentityPath(value, platform = process.platform) {
  const text = String(value)
  if (platform === 'win32') {
    const windowsText = text.replaceAll('/', '\\')
    if (!path.win32.isAbsolute(windowsText)) throw new Error('identity path must be absolute')
    let normalized = path.win32.normalize(windowsText)
    if (/^[a-zA-Z]:/.test(normalized)) normalized = `${normalized[0].toUpperCase()}${normalized.slice(1)}`
    const isDriveRoot = /^[A-Z]:\\$/.test(normalized)
    const isUncShareRoot = /^\\\\[^\\]+\\[^\\]+\\?$/.test(normalized)
    if (!isDriveRoot && !isUncShareRoot) normalized = normalized.replace(/\\+$/, '')
    return normalized
  }
  if (platform === 'posix') {
    if (!path.posix.isAbsolute(text)) throw new Error('identity path must be absolute')
    const normalized = path.posix.normalize(text)
    return normalized === '/' ? normalized : normalized.replace(/\/+$/, '')
  }
  throw new Error(`unsupported identity path platform: ${platform}`)
}

function normalizeSha256(value, fieldName, { optional = false } = {}) {
  if (value === null || value === undefined || String(value).trim() === '') {
    if (optional) return null
    throw new Error(`${fieldName} is required`)
  }
  const normalized = String(value).trim().toUpperCase()
  if (!SHA256_RE.test(normalized)) throw new Error(`${fieldName} must be a 64-character SHA-256 hex digest`)
  return normalized
}

function validateTimestamp(value, fieldName) {
  if (typeof value !== 'string' || !value.trim() || !Number.isFinite(Date.parse(value))) {
    throw new Error(`${fieldName} must be an ISO-8601 timestamp`)
  }
  const normalized = value.trim()
  if (new Date(normalized).toISOString() !== normalized) {
    throw new Error(`${fieldName} must use canonical UTC milliseconds`)
  }
  return normalized
}

function createBuildManifest({ gitHead, gitDirty, buildId, packageVersion, builtAt }) {
  if (!String(gitHead || '').trim()) throw new Error('build manifest gitHead is required')
  if (typeof gitDirty !== 'boolean') throw new Error('build manifest gitDirty must be boolean')
  if (!String(buildId || '').trim()) throw new Error('build manifest buildId is required')
  if (!String(packageVersion || '').trim()) throw new Error('build manifest packageVersion is required')
  const unsigned = {
    schemaVersion: BUILD_MANIFEST_SCHEMA_VERSION,
    gitHead: String(gitHead).trim(),
    gitDirty,
    buildId: String(buildId).trim(),
    packageVersion: String(packageVersion).trim(),
    builtAt: validateTimestamp(builtAt, 'build manifest builtAt'),
  }
  return { ...unsigned, fingerprint: fingerprintPayload(unsigned) }
}

function parseBuildManifest(raw, { expectedPackageVersion = null } = {}) {
  let payload
  try {
    payload = typeof raw === 'string' || Buffer.isBuffer(raw) ? JSON.parse(String(raw)) : { ...raw }
  } catch (error) {
    throw new Error(`build manifest JSON is invalid: ${error.message}`)
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('build manifest must be an object')
  const fields = ['schemaVersion', 'gitHead', 'gitDirty', 'buildId', 'packageVersion', 'builtAt', 'fingerprint']
  const missing = fields.filter((field) => !(field in payload))
  if (missing.length) throw new Error(`build manifest missing fields: ${missing.join(', ')}`)
  const unknown = Object.keys(payload).filter((field) => !fields.includes(field))
  if (unknown.length) throw new Error(`build manifest unknown fields: ${unknown.join(', ')}`)
  if (payload.schemaVersion !== BUILD_MANIFEST_SCHEMA_VERSION) throw new Error('build manifest schemaVersion mismatch')
  const normalized = createBuildManifest(payload)
  const actualFingerprint = normalizeSha256(payload.fingerprint, 'build manifest fingerprint')
  if (actualFingerprint !== normalized.fingerprint) throw new Error('build manifest fingerprint mismatch')
  if (expectedPackageVersion && normalized.packageVersion !== expectedPackageVersion) {
    throw new Error(`build manifest package version mismatch: expected ${expectedPackageVersion}, got ${normalized.packageVersion}`)
  }
  return { ...normalized, fingerprint: actualFingerprint }
}

function readGitBuildState(repoRoot, run = execFileSync) {
  try {
    const gitHead = String(run('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8', windowsHide: true })).trim()
    const status = String(run('git', ['status', '--porcelain', '--untracked-files=normal'], { cwd: repoRoot, encoding: 'utf8', windowsHide: true }))
    if (!gitHead) throw new Error('empty git HEAD')
    return { gitHead, gitDirty: Boolean(status.trim()) }
  } catch {
    return { gitHead: 'unknown', gitDirty: true }
  }
}

function createDirectLaunchManifest({ repoRoot, packageVersion, buildId = null, builtAt = null, runGit = execFileSync }) {
  const git = readGitBuildState(repoRoot, runGit)
  return createBuildManifest({
    ...git,
    buildId: buildId || `direct-${crypto.randomUUID()}`,
    packageVersion,
    builtAt: builtAt || new Date().toISOString(),
  })
}

function resolveLaunchManifest({
  isPackaged,
  resourcesPath,
  packageVersion,
  explicitManifestFile = null,
  directManifestFactory = null,
}) {
  let manifestPath = null
  if (isPackaged) {
    manifestPath = path.join(resourcesPath, 'build-metadata', 'desktop-build-manifest.json')
    if (!fs.existsSync(manifestPath)) throw new Error(`Packaged build manifest is missing: ${manifestPath}`)
  } else if (explicitManifestFile) {
    manifestPath = path.resolve(explicitManifestFile)
    if (!fs.existsSync(manifestPath)) throw new Error(`Explicit build manifest is missing: ${manifestPath}`)
  }
  if (manifestPath) {
    const stat = fs.statSync(manifestPath)
    if (!stat.isFile()) throw new Error(`Build manifest is not a regular file: ${manifestPath}`)
    return parseBuildManifest(fs.readFileSync(manifestPath, 'utf8'), { expectedPackageVersion: packageVersion })
  }
  if (typeof directManifestFactory !== 'function') throw new Error('Direct launch metadata factory is required')
  return parseBuildManifest(directManifestFactory(), { expectedPackageVersion: packageVersion })
}

function normalizePathKey(value) {
  const normalized = path.resolve(value)
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized
}

function normalizeWindowsAppFilename(value, fieldName) {
  const filename = String(value || '').trim()
  if (!filename || filename === '.' || filename === '..' || path.win32.basename(filename) !== filename) {
    throw new Error(`${fieldName} must be a non-empty Windows basename`)
  }
  return path.win32.normalize(filename).toLowerCase()
}

async function hashRegularFile(filePath) {
  const stat = await fs.promises.stat(filePath)
  if (!stat.isFile()) return null
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256')
    const stream = fs.createReadStream(filePath)
    stream.on('error', reject)
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex').toUpperCase()))
  })
}

async function resolvePortablePackageSha({
  isPackaged,
  portableExecutableFile,
  portableExecutableDir,
  portableExecutableAppFilename,
  expectedPortableAppFilename,
  innerExecutablePath,
}) {
  if (!isPackaged) return null
  const markers = [portableExecutableFile, portableExecutableDir, portableExecutableAppFilename]
  const presentMarkers = markers.filter((value) => Boolean(value)).length
  if (presentMarkers === 0) return null
  if (presentMarkers !== markers.length) throw new Error('Packaged portable executable markers are incomplete')
  if (!path.isAbsolute(portableExecutableFile) || !path.isAbsolute(portableExecutableDir)) {
    throw new Error('Packaged portable executable markers must use absolute paths')
  }
  if (!innerExecutablePath || !path.isAbsolute(innerExecutablePath)) {
    throw new Error('Packaged portable inner executable path must be absolute')
  }
  if (normalizePathKey(path.dirname(portableExecutableFile)) !== normalizePathKey(portableExecutableDir)) {
    throw new Error('PORTABLE_EXECUTABLE_FILE directory does not match PORTABLE_EXECUTABLE_DIR')
  }
  const markerName = normalizeWindowsAppFilename(
    portableExecutableAppFilename,
    'PORTABLE_EXECUTABLE_APP_FILENAME',
  )
  const expectedMarkerName = normalizeWindowsAppFilename(
    expectedPortableAppFilename,
    'expected portable APP_FILENAME',
  )
  if (markerName !== expectedMarkerName) {
    throw new Error('PORTABLE_EXECUTABLE_APP_FILENAME mismatch')
  }
  if (normalizePathKey(portableExecutableFile) === normalizePathKey(innerExecutablePath)) {
    throw new Error('Portable outer executable must differ from the inner process executable')
  }
  try {
    const digest = await hashRegularFile(portableExecutableFile)
    if (!digest) throw new Error('PORTABLE_EXECUTABLE_FILE is not a regular file')
    return digest
  } catch (error) {
    if (/regular file/i.test(error.message)) throw error
    throw new Error(`PORTABLE_EXECUTABLE_FILE cannot be hashed as a regular file: ${error.message}`)
  }
}

function createExpectedRuntimeIdentity({
  manifest,
  instanceId,
  packageSha256,
  backendPid,
  dataDir,
  workflowProfileDir,
  resourceRoot,
}) {
  const parsedManifest = parseBuildManifest(manifest)
  const pid = Number(backendPid)
  if (!Number.isInteger(pid) || pid <= 0) throw new Error('backendPid must be a positive integer')
  if (!String(instanceId || '').trim()) throw new Error('instanceId is required')
  return Object.freeze({
    schemaVersion: RUNTIME_IDENTITY_SCHEMA_VERSION,
    instanceId: String(instanceId).trim(),
    gitHead: parsedManifest.gitHead,
    gitDirty: parsedManifest.gitDirty,
    buildId: parsedManifest.buildId,
    packageVersion: parsedManifest.packageVersion,
    packageSha256: normalizeSha256(packageSha256, 'packageSha256', { optional: true }),
    backendPid: pid,
    browserAgentPid: pid,
    browserExecutionModel: BROWSER_EXECUTION_MODEL,
    dataDir: normalizeIdentityPath(dataDir),
    workflowProfileDir: normalizeIdentityPath(workflowProfileDir),
    resourceRoot: normalizeIdentityPath(resourceRoot),
  })
}

function verifyRuntimeIdentity(actual, expected) {
  if (!actual || typeof actual !== 'object' || Array.isArray(actual)) throw new Error('runtime identity must be an object')
  const required = [...Object.keys(expected), 'startedAt', 'fingerprint']
  const missing = required.filter((field) => !(field in actual))
  if (missing.length) throw new Error(`runtime identity missing fields: ${missing.join(', ')}`)
  const unknown = Object.keys(actual).filter((field) => !required.includes(field))
  if (unknown.length) throw new Error(`runtime identity unknown fields: ${unknown.join(', ')}`)
  for (const [key, value] of Object.entries(expected)) {
    if (actual[key] !== value) throw new Error(`runtime identity ${key} mismatch`)
  }
  const startedAt = validateTimestamp(actual.startedAt, 'runtime identity startedAt')
  if (new Date(startedAt).toISOString() !== startedAt) throw new Error('runtime identity startedAt must use canonical UTC milliseconds')
  if (actual.browserAgentPid !== actual.backendPid || actual.browserExecutionModel !== BROWSER_EXECUTION_MODEL) {
    throw new Error('runtime identity Browser Agent process model mismatch')
  }
  normalizeSha256(actual.packageSha256, 'runtime identity packageSha256', { optional: true })
  const unsigned = {}
  for (const key of required) {
    if (key !== 'fingerprint') unsigned[key] = actual[key]
  }
  const actualFingerprint = normalizeSha256(actual.fingerprint, 'runtime identity fingerprint')
  if (fingerprintPayload(unsigned) !== actualFingerprint) throw new Error('runtime identity fingerprint mismatch')
  return Object.freeze({ ...unsigned, fingerprint: actualFingerprint })
}

function buildBackendEnvironment(baseEnvironment, {
  manifest,
  instanceId,
  packageSha256,
  dataDir,
  resourceRoot,
  workflowProfileDir,
}) {
  const env = { ...baseEnvironment }
  const identityKeySet = new Set(IDENTITY_ENV_KEYS)
  for (const key of Object.keys(env)) {
    if (identityKeySet.has(key.toUpperCase())) delete env[key]
  }
  const parsedManifest = parseBuildManifest(manifest)
  env.DXM_BUILD_MANIFEST_JSON = JSON.stringify(parsedManifest)
  env.DXM_BACKEND_INSTANCE_ID = String(instanceId)
  env.DXM_DATA_DIR = normalizeIdentityPath(dataDir)
  env.DXM_RESOURCE_ROOT = normalizeIdentityPath(resourceRoot)
  env.DXM_WORKFLOW_PROFILE_DIR = normalizeIdentityPath(workflowProfileDir)
  const normalizedPackageSha = normalizeSha256(packageSha256, 'packageSha256', { optional: true })
  if (normalizedPackageSha) env.DXM_PACKAGE_SHA256 = normalizedPackageSha
  return env
}

function createBackendOwnership({ child, instanceId, expectedIdentity }) {
  if (!child || !Number.isInteger(child.pid) || child.pid <= 0) throw new Error('spawned backend child has no valid pid')
  if (child.pid !== expectedIdentity.backendPid) throw new Error('spawned backend pid does not match expected identity')
  if (String(instanceId) !== expectedIdentity.instanceId) throw new Error('backend ownership instanceId mismatch')
  return {
    child,
    pid: child.pid,
    instanceId: String(instanceId),
    expectedIdentity,
    verifiedIdentity: null,
  }
}

function setVerifiedBackendIdentity(ownership, verifiedIdentity) {
  if (!ownership || !verifiedIdentity) throw new Error('ownership and verified identity are required')
  if (verifiedIdentity.instanceId !== ownership.instanceId || verifiedIdentity.backendPid !== ownership.pid) {
    throw new Error('verified identity does not belong to the owned backend')
  }
  ownership.verifiedIdentity = Object.freeze({ ...verifiedIdentity })
  return ownership.verifiedIdentity
}

function canTerminateOwnedBackend({ currentOwnership, ownership, runtimeInfo }) {
  if (!isCurrentOwnedBackendLive(currentOwnership, ownership)) return false
  const child = ownership.child
  if (!ownership.expectedIdentity
    || ownership.expectedIdentity.instanceId !== ownership.instanceId
    || ownership.expectedIdentity.backendPid !== ownership.pid) return false
  if (!runtimeInfo
    || runtimeInfo.backendInstanceId !== ownership.instanceId
    || runtimeInfo.backendPid !== ownership.pid) return false
  if (ownership.verifiedIdentity) {
    if (!runtimeInfo.runtimeIdentity) return false
    if (canonicalJson(runtimeInfo.runtimeIdentity) !== canonicalJson(ownership.verifiedIdentity)) return false
  }
  return true
}

function terminateExactOwnedBackend({ currentOwnership, ownership, runtimeInfo }) {
  if (!canTerminateOwnedBackend({ currentOwnership, ownership, runtimeInfo })) return false
  return ownership.child.kill() === true
}

function isCurrentOwnedBackendLive(currentOwnership, ownership) {
  if (!ownership || currentOwnership !== ownership || !ownership.child) return false
  const child = ownership.child
  return child.pid === ownership.pid && child.exitCode === null && child.signalCode === null
}

function clearOwnershipForChild(currentOwnership, eventChild, eventName) {
  if (!currentOwnership || currentOwnership.child !== eventChild) return currentOwnership
  return eventName === 'exit' || eventName === 'close' ? null : currentOwnership
}

function createBackendChildLifecycle({
  ownership,
  getCurrentOwnership,
  setCurrentOwnership,
  endLogStream,
}) {
  let logStreamEnded = false
  return {
    handle(eventName) {
      if (eventName === 'exit' || eventName === 'close') {
        const current = getCurrentOwnership()
        const next = clearOwnershipForChild(current, ownership.child, eventName)
        if (next !== current) setCurrentOwnership(next)
      }
      if (eventName === 'close' && !logStreamEnded) {
        logStreamEnded = true
        endLogStream()
      }
    },
  }
}

function waitForOwnedBackendHealth({
  apiBase,
  timeoutMs = 45000,
  requestTimeoutMs = 1500,
  pollIntervalMs = 500,
  ownership,
  getCurrentOwnership,
  onVerified = () => {},
  log = () => {},
  httpModule = http,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) {
  return new Promise((resolve, reject) => {
    let settled = false
    let retryTimer = null
    let deadlineTimer = null
    let activeRequest = null
    const ownedChild = ownership?.child || null
    const ownedChildExited = () => {
      finish(new Error(`Backend owned child exited before health verification: ${apiBase}/health`))
    }

    const finish = (error, identity = null) => {
      if (settled) return
      settled = true
      if (retryTimer) clearTimer(retryTimer)
      if (deadlineTimer) clearTimer(deadlineTimer)
      const request = activeRequest
      activeRequest = null
      if (request && !request.destroyed) request.destroy()
      ownedChild?.off?.('exit', ownedChildExited)
      ownedChild?.off?.('close', ownedChildExited)
      if (error) reject(error)
      else resolve(identity)
    }

    const scheduleRetry = () => {
      if (settled || retryTimer) return
      if (!isCurrentOwnedBackendLive(getCurrentOwnership(), ownership)) {
        finish(new Error(`Backend owned child exited before health verification: ${apiBase}/health`))
        return
      }
      retryTimer = setTimer(() => {
        retryTimer = null
        poll()
      }, pollIntervalMs)
    }

    const poll = () => {
      if (settled) return
      if (!isCurrentOwnedBackendLive(getCurrentOwnership(), ownership)) {
        finish(new Error(`Backend owned child exited before health verification: ${apiBase}/health`))
        return
      }
      let request = null
      let attemptFinished = false
      const finishAttemptForRetry = () => {
        if (settled || attemptFinished) return
        attemptFinished = true
        if (activeRequest === request) activeRequest = null
        scheduleRetry()
      }
      try {
        request = httpModule.get(`${apiBase}/health`, (response) => {
          if (settled || attemptFinished) {
            response.resume?.()
            return
          }
          const chunks = []
          response.on('data', (chunk) => {
            if (!settled && !attemptFinished) chunks.push(chunk)
          })
          response.on('error', finishAttemptForRetry)
          response.on('end', () => {
            if (settled || attemptFinished) return
            attemptFinished = true
            if (activeRequest === request) activeRequest = null
            let payload
            try {
              payload = JSON.parse(Buffer.concat(chunks).toString('utf8'))
            } catch (error) {
              log(`Backend health response was not ready: ${error.message}`)
              scheduleRetry()
              return
            }
            const healthy = response.statusCode
              && response.statusCode >= 200
              && response.statusCode < 300
              && payload.status === 'ok'
            if (!healthy) {
              scheduleRetry()
              return
            }
            if (!isCurrentOwnedBackendLive(getCurrentOwnership(), ownership)) {
              finish(new Error(`Backend health response arrived after the owned child exited at ${apiBase}/health`))
              return
            }
            let verifiedIdentity
            try {
              verifiedIdentity = verifyRuntimeIdentity(payload.runtimeIdentity, ownership.expectedIdentity)
            } catch (error) {
              finish(new Error(`Backend health check reached a mismatched backend at ${apiBase}/health: ${error.message}`))
              return
            }
            if (payload.instanceId !== verifiedIdentity.instanceId) {
              finish(new Error(`Backend health legacy instanceId mismatched verified identity at ${apiBase}/health`))
              return
            }
            if (!isCurrentOwnedBackendLive(getCurrentOwnership(), ownership)) {
              finish(new Error(`Backend ownership changed before identity verification completed at ${apiBase}/health`))
              return
            }
            const storedIdentity = setVerifiedBackendIdentity(ownership, verifiedIdentity)
            onVerified(storedIdentity)
            finish(null, storedIdentity)
          })
        })
        activeRequest = request
        request.on('error', finishAttemptForRetry)
        request.setTimeout(requestTimeoutMs, () => {
          if (settled || attemptFinished) return
          request.destroy()
          finishAttemptForRetry()
        })
      } catch (error) {
        log(`Backend health request could not start: ${error.message}`)
        finishAttemptForRetry()
      }
    }

    deadlineTimer = setTimer(() => {
      finish(new Error(`Backend health check timed out: ${apiBase}/health`))
    }, timeoutMs)
    ownedChild?.once?.('exit', ownedChildExited)
    ownedChild?.once?.('close', ownedChildExited)
    poll()
  })
}

module.exports = {
  RUNTIME_IDENTITY_SCHEMA_VERSION,
  BUILD_MANIFEST_SCHEMA_VERSION,
  BROWSER_EXECUTION_MODEL,
  canonicalJson,
  fingerprintPayload,
  normalizeIdentityPath,
  createBuildManifest,
  parseBuildManifest,
  readGitBuildState,
  createDirectLaunchManifest,
  resolveLaunchManifest,
  resolvePortablePackageSha,
  createExpectedRuntimeIdentity,
  verifyRuntimeIdentity,
  buildBackendEnvironment,
  createBackendOwnership,
  setVerifiedBackendIdentity,
  canTerminateOwnedBackend,
  terminateExactOwnedBackend,
  isCurrentOwnedBackendLive,
  clearOwnershipForChild,
  createBackendChildLifecycle,
  waitForOwnedBackendHealth,
}
