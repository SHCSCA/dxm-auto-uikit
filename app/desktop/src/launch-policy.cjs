const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')

const { normalizeIdentityPath } = require('./runtime-identity.cjs')

const QA_DEADLINE_MIN_MS = 1000
const QA_DEADLINE_MAX_MS = 600000
const NORMAL_BACKEND_PORT = 8000
const QA_BACKEND_PORT_MAX = 8079
const DEFAULT_QA_PORT_DEADLINE_MS = 1500
const DEFAULT_LEGACY_SCAN_DEADLINE_MS = 2000
const DEFAULT_LEGACY_BODY_LIMIT = 64 * 1024
const QA_FLAG_NAMES = new Set([
  'qa-user-data-dir',
  'qa-capture',
  'qa-visible-smoke',
  'qa-credential-smoke',
  'qa-deadline-ms',
])

function identityPlatform(platform) {
  return platform === 'win32' ? 'win32' : 'posix'
}

function pathApiFor(platform) {
  return platform === 'win32' ? path.win32 : path.posix
}

function normalizeComparisonKey(value, platform) {
  const normalized = normalizeIdentityPath(value, identityPlatform(platform))
  return platform === 'win32' ? normalized.toLowerCase() : normalized
}

function resolveRealPath(fsModule, value) {
  const resolver = fsModule.realpathSync?.native || fsModule.realpathSync
  if (typeof resolver !== 'function') return value
  return resolver.call(fsModule.realpathSync, value)
}

function canonicalizeComparablePath(value, {
  platform = process.platform,
  fsModule = fs,
} = {}) {
  const pathApi = pathApiFor(platform)
  const normalized = normalizeIdentityPath(value, identityPlatform(platform))
  let cursor = normalized
  const missingParts = []

  while (!fsModule.existsSync(cursor)) {
    const parent = pathApi.dirname(cursor)
    if (parent === cursor) break
    missingParts.unshift(pathApi.basename(cursor))
    cursor = parent
  }

  if (fsModule.existsSync(cursor)) {
    cursor = resolveRealPath(fsModule, cursor)
  }
  const resolved = missingParts.length ? pathApi.join(cursor, ...missingParts) : cursor
  return normalizeIdentityPath(resolved, identityPlatform(platform))
}

function isSameOrDescendant(parentValue, candidateValue, platform) {
  const pathApi = pathApiFor(platform)
  const parentKey = normalizeComparisonKey(parentValue, platform)
  const candidateKey = normalizeComparisonKey(candidateValue, platform)
  if (parentKey === candidateKey) return true
  const relative = pathApi.relative(parentKey, candidateKey)
  return Boolean(relative)
    && relative !== '..'
    && !relative.startsWith(`..${pathApi.sep}`)
    && !pathApi.isAbsolute(relative)
}

function parseQaArguments(argv) {
  const values = new Map()
  for (const rawArg of argv) {
    const arg = String(rawArg)
    if (!arg.startsWith('--qa-')) continue
    const separator = arg.indexOf('=')
    const name = arg.slice(2, separator === -1 ? undefined : separator)
    if (!QA_FLAG_NAMES.has(name)) {
      throw new Error(`Unknown QA argument --${name}`)
    }
    if (values.has(name)) {
      throw new Error(`Duplicate QA argument --${name}`)
    }
    values.set(name, separator === -1 ? '' : arg.slice(separator + 1).trim())
  }
  return values
}

function requireAbsoluteQaPath(value, flagName, platform) {
  if (!value) throw new Error(`QA argument --${flagName} requires a non-empty absolute path`)
  const pathApi = pathApiFor(platform)
  if (!pathApi.isAbsolute(value)) {
    throw new Error(`QA argument --${flagName} requires an absolute path`)
  }
  return normalizeIdentityPath(value, identityPlatform(platform))
}

function classifyLaunchArguments({
  argv,
  normalUserDataDir,
  platform = process.platform,
  fsModule = fs,
}) {
  if (!Array.isArray(argv)) throw new TypeError('argv must be an array')
  const normalLexical = requireAbsoluteQaPath(normalUserDataDir, 'normal-user-data', platform)
  const qa = parseQaArguments(argv)
  if (qa.size === 0) {
    return Object.freeze({
      kind: 'normal',
      isIsolatedQa: false,
      normalUserDataDir: normalLexical,
      qaUserDataDir: null,
      smokeOutputs: Object.freeze({ capture: null, visible: null, credential: null }),
      deadlineMs: null,
    })
  }

  const smokeFlagNames = ['qa-capture', 'qa-visible-smoke', 'qa-credential-smoke']
  const presentSmokeFlags = smokeFlagNames.filter((name) => qa.has(name))
  if (!qa.has('qa-user-data-dir') || presentSmokeFlags.length === 0) {
    throw new Error('Isolated QA requires --qa-user-data-dir and at least one known smoke output')
  }
  if (qa.has('qa-capture') && qa.has('qa-visible-smoke')) {
    throw new Error('Isolated QA cannot combine --qa-capture with --qa-visible-smoke')
  }

  const qaUserDataDir = requireAbsoluteQaPath(qa.get('qa-user-data-dir'), 'qa-user-data-dir', platform)
  const normalCanonical = canonicalizeComparablePath(normalLexical, { platform, fsModule })
  const qaCanonical = canonicalizeComparablePath(qaUserDataDir, { platform, fsModule })
  if (isSameOrDescendant(normalCanonical, qaCanonical, platform)
    || isSameOrDescendant(qaCanonical, normalCanonical, platform)) {
    throw new Error('QA userData must be filesystem-disjoint from normal userData')
  }

  const smokeOutputs = {
    capture: null,
    visible: null,
    credential: null,
  }
  const outputFields = [
    ['qa-capture', 'capture'],
    ['qa-visible-smoke', 'visible'],
    ['qa-credential-smoke', 'credential'],
  ]
  for (const [flagName, fieldName] of outputFields) {
    if (!qa.has(flagName)) continue
    const outputPath = requireAbsoluteQaPath(qa.get(flagName), flagName, platform)
    const canonicalOutput = canonicalizeComparablePath(outputPath, { platform, fsModule })
    if (isSameOrDescendant(normalCanonical, canonicalOutput, platform)) {
      throw new Error(`QA output --${flagName} must remain outside normal userData`)
    }
    smokeOutputs[fieldName] = outputPath
  }

  let deadlineMs = null
  if (qa.has('qa-deadline-ms')) {
    const rawDeadline = qa.get('qa-deadline-ms')
    if (!/^\d+$/.test(rawDeadline)) {
      throw new Error('--qa-deadline-ms must be a bounded positive integer')
    }
    deadlineMs = Number(rawDeadline)
    if (!Number.isSafeInteger(deadlineMs)
      || deadlineMs < QA_DEADLINE_MIN_MS
      || deadlineMs > QA_DEADLINE_MAX_MS) {
      throw new Error(`--qa-deadline-ms must be between ${QA_DEADLINE_MIN_MS} and ${QA_DEADLINE_MAX_MS}`)
    }
  }

  return Object.freeze({
    kind: 'isolated-qa',
    isIsolatedQa: true,
    normalUserDataDir: normalLexical,
    qaUserDataDir,
    smokeOutputs: Object.freeze(smokeOutputs),
    deadlineMs,
  })
}

function resolveSelectedDataDir({ isIsolatedQa, isPackaged, repoRoot, userDataDir }) {
  if (isIsolatedQa || isPackaged) return path.join(userDataDir, 'data')
  return path.join(repoRoot, 'data')
}

async function selectBackendPort({
    isIsolatedQa,
    isPackaged = false,
    isPortFree,
    deadlineMs = DEFAULT_QA_PORT_DEADLINE_MS,
    setTimer = setTimeout,
    clearTimer = clearTimeout,
  }) {
    if (!isIsolatedQa && !isPackaged) return 8000
  if (typeof isPortFree !== 'function') throw new TypeError('isolated QA requires an isPortFree function')
  if (!Number.isFinite(deadlineMs) || deadlineMs <= 0) throw new TypeError('QA port deadlineMs must be positive')
  const controller = new AbortController()
  const freePorts = []
  let acceptingResults = true
  let deadlineTimer = null
  const probes = []
  for (let port = 8000; port <= 8079; port += 1) {
    probes.push(Promise.resolve()
      .then(() => isPortFree(port, { signal: controller.signal }))
      .then((isFree) => {
        if (acceptingResults && isFree === true) freePorts.push(port)
      })
      .catch(() => {}))
  }
  const allProbes = Promise.allSettled(probes)
  const deadline = new Promise((resolve) => {
    deadlineTimer = setTimer(() => {
      acceptingResults = false
      controller.abort()
      resolve('deadline')
    }, deadlineMs)
  })
  const outcome = await Promise.race([allProbes.then(() => 'complete'), deadline])
  if (outcome === 'complete') {
    acceptingResults = false
    clearTimer(deadlineTimer)
    controller.abort()
  }
  if (freePorts.length > 0) return Math.min(...freePorts)
  if (outcome === 'deadline') {
    throw createConflictError(
      'DXM_QA_PORT_UNAVAILABLE',
      'No free loopback port was proven in QA range 8000..8079 before the total deadline',
    )
  }
  throw createConflictError(
    'DXM_QA_PORT_UNAVAILABLE',
    'No free loopback port in bounded QA range 8000..8079',
  )
}

function createTcpOccupancyProbe({ netModule = net } = {}) {
  return function probeTcpOccupancy({ host = '127.0.0.1', port, signal }) {
    return new Promise((resolve) => {
      let settled = false
      let socket = null
      const finish = (value) => {
        if (settled) return
        settled = true
        signal?.removeEventListener?.('abort', onAbort)
        socket?.destroy()
        resolve(value)
      }
      const onAbort = () => finish(null)
      if (signal?.aborted) {
        finish(null)
        return
      }
      signal?.addEventListener?.('abort', onAbort, { once: true })
      try {
        socket = netModule.createConnection({ host, port })
        socket.once('connect', () => finish(true))
        socket.once('error', (error) => {
          finish(error?.code === 'ECONNREFUSED' ? false : null)
        })
      } catch {
        finish(null)
      }
    })
  }
}

function createHttpRuntimeProbe({ httpModule = http } = {}) {
  return function probeHttpRuntime({
    host = '127.0.0.1',
    port,
    pathname,
    signal,
    maxBodyBytes,
  }) {
    return new Promise((resolve, reject) => {
      let settled = false
      let request = null
      const finish = (error, result = null) => {
        if (settled) return
        settled = true
        signal?.removeEventListener?.('abort', onAbort)
        if (error) reject(error)
        else resolve(result)
      }
      const onAbort = () => {
        request?.destroy()
        const error = new Error('runtime probe aborted')
        error.code = 'ABORT_ERR'
        finish(error)
      }
      if (signal?.aborted) {
        onAbort()
        return
      }
      signal?.addEventListener?.('abort', onAbort, { once: true })
      try {
        request = httpModule.get({ host, port, path: pathname }, (response) => {
          const chunks = []
          let size = 0
          response.on('data', (chunk) => {
            if (settled) return
            const bytes = Buffer.from(chunk)
            size += bytes.length
            if (size > maxBodyBytes) {
              response.destroy()
              const error = new Error(`runtime probe body exceeded ${maxBodyBytes} bytes`)
              error.code = 'DXM_RUNTIME_PROBE_BODY_LIMIT'
              finish(error)
              return
            }
            chunks.push(bytes)
          })
          response.once('error', (error) => finish(error))
          response.once('end', () => finish(null, {
            statusCode: response.statusCode || 0,
            body: Buffer.concat(chunks).toString('utf8'),
          }))
        })
        request.once('error', (error) => finish(error))
      } catch (error) {
        finish(error)
      }
    })
  }
}

function extractRuntimeFact(response, pathname) {
  if (!response || response.statusCode < 200 || response.statusCode >= 300) return null
  let payload
  try {
    payload = JSON.parse(String(response.body || ''))
  } catch {
    return null
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null

  if (pathname === '/health') {
    const identity = payload.runtimeIdentity
    if (!identity || typeof identity !== 'object') return null
    return {
      dataDir: identity.dataDir,
      pid: identity.backendPid ?? null,
      instanceId: identity.instanceId ?? payload.instanceId ?? null,
      source: '/health.runtimeIdentity.dataDir',
    }
  }

  const identity = payload.runtimeIdentity || payload.backend?.runtimeIdentity
  const dataDir = payload.paths?.data_dir ?? identity?.dataDir
  if (!dataDir) return null
  return {
    dataDir,
    pid: payload.backend?.pid ?? identity?.backendPid ?? null,
    instanceId: payload.backend?.instanceId ?? identity?.instanceId ?? null,
    source: payload.paths?.data_dir ? '/api/runtime/status.paths.data_dir' : '/api/runtime/status.runtimeIdentity.dataDir',
  }
}

function createConflictError(code, message, details = {}) {
  const error = new Error(message)
  error.code = code
  Object.assign(error, details)
  return error
}

async function inspectLegacyRuntimePorts({
  dataDir,
  ports = Array.from({ length: 80 }, (_, index) => NORMAL_BACKEND_PORT + index),
  deadlineMs = DEFAULT_LEGACY_SCAN_DEADLINE_MS,
  maxBodyBytes = DEFAULT_LEGACY_BODY_LIMIT,
  platform = process.platform,
  fsModule = fs,
  tcpProbe = createTcpOccupancyProbe(),
  httpProbe = createHttpRuntimeProbe(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  requireFixedPortFree = true,
}) {
  if (!Array.isArray(ports) || ports.length === 0) throw new TypeError('ports must be a non-empty array')
  if (!Number.isFinite(deadlineMs) || deadlineMs <= 0) throw new TypeError('deadlineMs must be positive')
  if (!Number.isInteger(maxBodyBytes) || maxBodyBytes <= 0) throw new TypeError('maxBodyBytes must be positive')

  const expectedDataKey = normalizeComparisonKey(
    canonicalizeComparablePath(dataDir, { platform, fsModule }),
    platform,
  )
  const controller = new AbortController()
  const records = new Map(ports.map((port) => [port, {
    port,
    tcp: 'pending',
    runtimeFacts: [],
  }]))
  let acceptingResults = true
  let deadlineReached = false
  let deadlineTimer = null

  const probeTasks = ports.map(async (port) => {
    const record = records.get(port)
    let occupied = null
    try {
      occupied = await tcpProbe({ host: '127.0.0.1', port, signal: controller.signal })
    } catch {
      occupied = null
    }
    if (!acceptingResults) return
    record.tcp = occupied === true ? 'occupied' : occupied === false ? 'free' : 'unknown'
    if (occupied !== true) return

    await Promise.allSettled(['/health', '/api/runtime/status'].map(async (pathname) => {
      let response
      try {
        response = await httpProbe({
          host: '127.0.0.1',
          port,
          pathname,
          signal: controller.signal,
          maxBodyBytes,
        })
      } catch {
        return
      }
      if (!acceptingResults) return
      if (Buffer.byteLength(String(response?.body || ''), 'utf8') > maxBodyBytes) return
      const fact = extractRuntimeFact(response, pathname)
      if (!fact?.dataDir) return
      try {
        const factKey = normalizeComparisonKey(
          canonicalizeComparablePath(fact.dataDir, { platform, fsModule }),
          platform,
        )
        record.runtimeFacts.push({ ...fact, sameData: factKey === expectedDataKey })
      } catch {
        // An invalid identity path is not runtime ownership evidence.
      }
    }))
  })

  const allProbes = Promise.allSettled(probeTasks)
  const deadline = new Promise((resolve) => {
    deadlineTimer = setTimer(() => {
      deadlineReached = true
      acceptingResults = false
      controller.abort()
      resolve('deadline')
    }, deadlineMs)
  })
  const outcome = await Promise.race([allProbes.then(() => 'complete'), deadline])
  if (outcome === 'complete') {
    acceptingResults = false
    clearTimer(deadlineTimer)
    controller.abort()
  }

  const snapshot = [...records.values()].map((record) => Object.freeze({
    port: record.port,
    tcp: record.tcp,
    runtimeFacts: Object.freeze(record.runtimeFacts.map((fact) => Object.freeze({ ...fact }))),
  }))
  const sameDataRuntimes = snapshot.flatMap((record) => record.runtimeFacts
    .filter((fact) => fact.sameData)
    .map((fact) => Object.freeze({ port: record.port, ...fact })))

  if (sameDataRuntimes.length > 0) {
    const owner = sameDataRuntimes[0]
    const ownerText = [
      `port=${owner.port}`,
      owner.pid === null ? null : `pid=${owner.pid}`,
      owner.instanceId ? `instance=${owner.instanceId}` : null,
    ].filter(Boolean).join(' ')
    throw createConflictError(
      'DXM_SAME_DATA_RUNTIME',
      `A DXM runtime already owns the same data directory (${ownerText}); stop it explicitly. Do not adopt or kill it.`,
      { conflict: owner },
    )
  }

  const fixedPort = snapshot.find((record) => record.port === NORMAL_BACKEND_PORT)
  if (requireFixedPortFree && fixedPort?.tcp === 'occupied') {
    throw createConflictError(
      'DXM_PORT_8000_OCCUPIED',
      'Loopback port 8000 is occupied. Stop the owning application explicitly; do not adopt or kill it.',
      { conflict: fixedPort },
    )
  }
  if (requireFixedPortFree && fixedPort && fixedPort.tcp !== 'free') {
    throw createConflictError(
      'DXM_PORT_8000_UNCERTAIN',
      'Loopback port 8000 could not be proven free before the shared diagnostic deadline.',
      { conflict: fixedPort },
    )
  }

  return Object.freeze({
    ok: true,
    deadlineReached,
    port8000: fixedPort?.tcp || 'not-scanned',
    occupiedPorts: Object.freeze(snapshot.filter((record) => record.tcp === 'occupied').map((record) => record.port)),
    sameDataRuntimes: Object.freeze([]),
    records: Object.freeze(snapshot),
  })
}

module.exports = {
  QA_DEADLINE_MIN_MS,
  QA_DEADLINE_MAX_MS,
  NORMAL_BACKEND_PORT,
  QA_BACKEND_PORT_MAX,
  DEFAULT_QA_PORT_DEADLINE_MS,
  canonicalizeComparablePath,
  classifyLaunchArguments,
  resolveSelectedDataDir,
  selectBackendPort,
  createTcpOccupancyProbe,
  createHttpRuntimeProbe,
  inspectLegacyRuntimePorts,
}
