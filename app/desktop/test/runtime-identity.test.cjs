const assert = require('node:assert/strict')
const fs = require('node:fs')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { EventEmitter } = require('node:events')
const test = require('node:test')

const {
  BUILD_MANIFEST_SCHEMA_VERSION,
  canonicalJson,
  fingerprintPayload,
  normalizeIdentityPath,
  createBuildManifest,
  parseBuildManifest,
  createDirectLaunchManifest,
  resolveLaunchManifest,
  resolvePortablePackageSha,
  createExpectedRuntimeIdentity,
  verifyRuntimeIdentity,
  buildBackendEnvironment,
  createBackendOwnership,
  setVerifiedBackendIdentity,
  canTerminateOwnedBackend,
  isCurrentOwnedBackendLive,
  clearOwnershipForChild,
  createBackendChildLifecycle,
  waitForOwnedBackendHealth,
} = require('../src/runtime-identity.cjs')

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
const GOLDEN_VECTOR = path.join(REPO_ROOT, 'app', 'backend', 'tests', 'fixtures', 'runtime_identity_golden_vector.json')
const GENERATOR = path.join(REPO_ROOT, 'app', 'desktop', 'scripts', 'generate-build-manifest.cjs')

function readGoldenVector() {
  return JSON.parse(fs.readFileSync(GOLDEN_VECTOR, 'utf8'))
}

function manifest(overrides = {}) {
  return createBuildManifest({
    gitHead: '1234567890abcdef1234567890abcdef12345678',
    gitDirty: false,
    buildId: 'desktop-build-01',
    packageVersion: '0.1.0',
    builtAt: '2026-07-13T03:00:00.000Z',
    ...overrides,
  })
}

function expectedIdentity(overrides = {}) {
  return createExpectedRuntimeIdentity({
    manifest: manifest(),
    instanceId: 'desktop-instance-01',
    packageSha256: null,
    backendPid: 4321,
    dataDir: path.resolve('C:/DXM/data'),
    workflowProfileDir: path.resolve('C:/DXM/data/browser_profiles/dxm_workflow'),
    resourceRoot: path.resolve('D:/Desktop/py/dxm-auto-uikit'),
    ...overrides,
  })
}

function actualIdentity(expected = expectedIdentity(), overrides = {}) {
  const fields = {
    ...expected,
    startedAt: '2026-07-13T03:04:05.678Z',
    ...overrides,
  }
  return { ...fields, fingerprint: fingerprintPayload(fields) }
}

test('canonical JSON and fingerprint match the shared Python golden vector', () => {
  const vector = readGoldenVector()

  assert.equal(canonicalJson(vector.identity), vector.canonicalJson)
  assert.equal(fingerprintPayload(vector.identity), vector.fingerprint)
})

test('identity paths match the shared lexical golden cases', () => {
  const vector = readGoldenVector()

  for (const pathCase of vector.pathCases) {
    assert.equal(normalizeIdentityPath(pathCase.input, pathCase.platform), pathCase.expected)
  }
  assert.throws(() => normalizeIdentityPath('relative/path', 'posix'), /absolute/i)
  assert.throws(() => normalizeIdentityPath('relative\\path', 'win32'), /absolute/i)
})

test('build manifest parser validates schema, version, timestamp, and fingerprint', () => {
  const original = manifest()
  assert.equal(original.schemaVersion, BUILD_MANIFEST_SCHEMA_VERSION)
  assert.deepEqual(parseBuildManifest(JSON.stringify(original), { expectedPackageVersion: '0.1.0' }), original)

  const tampered = { ...original, gitDirty: !original.gitDirty }
  assert.throws(() => parseBuildManifest(tampered), /fingerprint/i)
  assert.throws(() => parseBuildManifest({ ...original, schemaVersion: 'old' }), /schema/i)
  assert.throws(() => parseBuildManifest(original, { expectedPackageVersion: '9.9.9' }), /package version/i)
  const invalidTime = { ...original, builtAt: 'not-a-time' }
  delete invalidTime.fingerprint
  invalidTime.fingerprint = fingerprintPayload(invalidTime)
  assert.throws(() => parseBuildManifest(invalidTime), /builtAt/i)
  const offsetTime = { ...original, builtAt: '2026-07-13T11:00:00+08:00' }
  delete offsetTime.fingerprint
  offsetTime.fingerprint = fingerprintPayload(offsetTime)
  assert.throws(() => parseBuildManifest(offsetTime), /builtAt/i)
  const extraField = { ...original, futureField: 'must-not-drift-v1' }
  delete extraField.fingerprint
  extraField.fingerprint = fingerprintPayload(extraField)
  assert.throws(() => parseBuildManifest(extraField), /unknown/i)
})

test('packaged launch fails closed on missing manifest while direct launch uses one explicit source once', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dxm-launch-manifest-'))
  const resourcesPath = path.join(root, 'resources')
  fs.mkdirSync(path.join(resourcesPath, 'build-metadata'), { recursive: true })

  assert.throws(() => resolveLaunchManifest({ isPackaged: true, resourcesPath, packageVersion: '0.1.0' }), /manifest/i)

  const staleOutput = path.join(root, 'outputs', 'build-metadata', 'desktop-build-manifest.json')
  fs.mkdirSync(path.dirname(staleOutput), { recursive: true })
  fs.writeFileSync(staleOutput, JSON.stringify(manifest({ buildId: 'stale' })))
  let directCalls = 0
  const direct = resolveLaunchManifest({
    isPackaged: false,
    resourcesPath,
    packageVersion: '0.1.0',
    directManifestFactory: () => {
      directCalls += 1
      return manifest({ buildId: 'direct-live' })
    },
  })
  assert.equal(direct.buildId, 'direct-live')
  assert.equal(directCalls, 1)

  const packaged = manifest({ buildId: 'packaged' })
  fs.writeFileSync(path.join(resourcesPath, 'build-metadata', 'desktop-build-manifest.json'), JSON.stringify(packaged))
  assert.equal(resolveLaunchManifest({ isPackaged: true, resourcesPath, packageVersion: '0.1.0' }).buildId, 'packaged')
})

test('direct launch build identity derives from the launch instance and fails Git closed', () => {
  const direct = createDirectLaunchManifest({
    repoRoot: path.resolve('.'),
    packageVersion: '0.1.0',
    buildId: 'direct-desktop-instance-01',
    builtAt: '2026-07-13T03:00:00.000Z',
    runGit: () => { throw new Error('git unavailable') },
  })

  assert.equal(direct.buildId, 'direct-desktop-instance-01')
  assert.equal(direct.gitHead, 'unknown')
  assert.equal(direct.gitDirty, true)
})

test('portable SHA fails closed for partial packaged markers and hashes only a fully consistent outer file', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dxm-portable-sha-'))
  const portable = path.join(root, 'DXM-Agent-Console-Portable-0.1.0.exe')
  const inner = path.join(root, 'inner', 'DXM-Agent-Console.exe')
  fs.writeFileSync(portable, Buffer.from('portable-outer-exe', 'utf8'))

  assert.equal(await resolvePortablePackageSha({ isPackaged: false, portableExecutableFile: portable }), null)
  assert.equal(await resolvePortablePackageSha({ isPackaged: true }), null)
  await assert.rejects(() => resolvePortablePackageSha({ isPackaged: true, portableExecutableFile: portable }), /marker/i)
  await assert.rejects(() => resolvePortablePackageSha({ isPackaged: true, portableExecutableDir: root }), /marker/i)
  await assert.rejects(() => resolvePortablePackageSha({ isPackaged: true, portableExecutableAppFilename: 'DXM-Agent-Console.exe' }), /marker/i)
  await assert.rejects(() => resolvePortablePackageSha({
    isPackaged: true,
    portableExecutableFile: path.basename(portable),
    portableExecutableDir: root,
    portableExecutableAppFilename: 'DXM-Agent-Console.exe',
    innerExecutablePath: inner,
  }), /absolute/i)
  await assert.rejects(() => resolvePortablePackageSha({
    isPackaged: true,
    portableExecutableFile: portable,
    portableExecutableDir: path.join(root, 'other'),
    portableExecutableAppFilename: 'DXM-Agent-Console.exe',
    innerExecutablePath: inner,
  }), /directory/i)
  await assert.rejects(() => resolvePortablePackageSha({
    isPackaged: true,
    portableExecutableFile: portable,
    portableExecutableDir: root,
    portableExecutableAppFilename: 'nested\\app-name',
    innerExecutablePath: inner,
  }), /APP_FILENAME/i)
  await assert.rejects(() => resolvePortablePackageSha({
    isPackaged: true,
    portableExecutableFile: root,
    portableExecutableDir: path.dirname(root),
    portableExecutableAppFilename: 'DXM-Agent-Console.exe',
    innerExecutablePath: inner,
  }), /regular file/i)
  await assert.rejects(() => resolvePortablePackageSha({
    isPackaged: true,
    portableExecutableFile: inner,
    portableExecutableDir: path.dirname(inner),
    portableExecutableAppFilename: 'dxm-agent-desktop',
    innerExecutablePath: inner,
  }), /outer.*inner|inner.*outer/i)
  assert.equal(
    await resolvePortablePackageSha({
      isPackaged: true,
      portableExecutableFile: portable,
      portableExecutableDir: root,
      portableExecutableAppFilename: 'dxm-agent-desktop',
      innerExecutablePath: inner,
    }),
    '741DBCAF6F760C16372C3B119DFC3A6DC7612245DB6124D23840F566045396C4',
  )
})

test('full identity verification rejects every launch-known field mismatch and invalid self-proof', () => {
  const expected = expectedIdentity()
  const verified = verifyRuntimeIdentity(actualIdentity(expected), expected)
  assert.ok(Object.isFrozen(verified))

  for (const key of Object.keys(expected)) {
    const changed = typeof expected[key] === 'boolean'
      ? !expected[key]
      : typeof expected[key] === 'number'
        ? expected[key] + 1
        : expected[key] === null
          ? 'AA'.repeat(32)
          : `${expected[key]}-mismatch`
    assert.throws(() => verifyRuntimeIdentity(actualIdentity(expected, { [key]: changed }), expected), new RegExp(key, 'i'), key)
  }

  assert.throws(() => verifyRuntimeIdentity({ ...actualIdentity(expected), startedAt: 'not-a-time' }, expected), /startedAt/i)
  assert.throws(() => verifyRuntimeIdentity({ ...actualIdentity(expected), fingerprint: '00'.repeat(32) }, expected), /fingerprint/i)
  const extraField = { ...actualIdentity(expected), futureField: 'must-not-drift-v1' }
  delete extraField.fingerprint
  extraField.fingerprint = fingerprintPayload(extraField)
  assert.throws(() => verifyRuntimeIdentity(extraField, expected), /unknown/i)
})

test('backend environment clears stale identity inputs after spreading the parent environment', () => {
  const launchManifest = manifest()
  const env = buildBackendEnvironment(
    {
      KEEP_ME: 'yes',
      DXM_BUILD_MANIFEST_JSON: 'stale-json',
      DXM_BUILD_MANIFEST_FILE: 'stale-file',
      DXM_PACKAGE_SHA256: 'FF'.repeat(32),
      DXM_BACKEND_INSTANCE_ID: 'stale-instance',
      DXM_DATA_DIR: 'stale-data',
      DXM_RESOURCE_ROOT: 'stale-resource',
      DXM_WORKFLOW_PROFILE_DIR: 'stale-profile',
      PORTABLE_EXECUTABLE_FILE: 'stale-outer.exe',
      Dxm_Package_Sha256: 'EE'.repeat(32),
      dxm_build_manifest_json: 'mixed-case-stale-json',
    },
    {
      manifest: launchManifest,
      instanceId: 'fresh-instance',
      packageSha256: null,
      dataDir: path.resolve('C:/fresh/data'),
      resourceRoot: path.resolve('D:/fresh/resources'),
      workflowProfileDir: path.resolve('C:/fresh/data/profile'),
    },
  )

  assert.equal(env.KEEP_ME, 'yes')
  assert.equal(JSON.parse(env.DXM_BUILD_MANIFEST_JSON).fingerprint, launchManifest.fingerprint)
  assert.equal(env.DXM_BACKEND_INSTANCE_ID, 'fresh-instance')
  assert.equal(env.DXM_DATA_DIR, path.resolve('C:/fresh/data'))
  assert.equal(env.DXM_RESOURCE_ROOT, path.resolve('D:/fresh/resources'))
  assert.equal(env.DXM_WORKFLOW_PROFILE_DIR, path.resolve('C:/fresh/data/profile'))
  assert.equal('DXM_BUILD_MANIFEST_FILE' in env, false)
  assert.equal('DXM_PACKAGE_SHA256' in env, false)
  assert.equal('PORTABLE_EXECUTABLE_FILE' in env, false)
  assert.equal(Object.keys(env).some((key) => key.toUpperCase() === 'DXM_PACKAGE_SHA256' && key !== 'DXM_PACKAGE_SHA256'), false)
  assert.equal(Object.keys(env).some((key) => key.toUpperCase() === 'DXM_BUILD_MANIFEST_JSON' && key !== 'DXM_BUILD_MANIFEST_JSON'), false)
})

test('ownership permits exact pre-health cleanup and requires verified identity post-health', () => {
  const expected = expectedIdentity()
  const child = { pid: expected.backendPid, exitCode: null, signalCode: null, killed: true }
  const ownership = createBackendOwnership({ child, instanceId: expected.instanceId, expectedIdentity: expected })
  const runtimeInfo = {
    backendPid: expected.backendPid,
    backendInstanceId: expected.instanceId,
    runtimeIdentity: null,
  }

  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo }), true)
  assert.equal(canTerminateOwnedBackend({ currentOwnership: { ...ownership }, ownership, runtimeInfo }), false)
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo: { ...runtimeInfo, backendPid: 9999 } }), false)
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership: { ...ownership, child: { ...child } }, runtimeInfo }), false)

  const verified = verifyRuntimeIdentity(actualIdentity(expected), expected)
  setVerifiedBackendIdentity(ownership, verified)
  runtimeInfo.runtimeIdentity = verified
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo }), true)
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo: { ...runtimeInfo, runtimeIdentity: { ...verified, instanceId: 'stale' } } }), false)

  child.exitCode = 0
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo }), false)
  child.exitCode = null
  child.signalCode = 'SIGTERM'
  assert.equal(canTerminateOwnedBackend({ currentOwnership: ownership, ownership, runtimeInfo }), false)
})

test('exit or error events clear ownership only for the currently owned exact ChildProcess', () => {
  const expected = expectedIdentity()
  const child = { pid: expected.backendPid, exitCode: null, signalCode: null }
  const staleChild = { pid: expected.backendPid, exitCode: null, signalCode: null }
  const ownership = createBackendOwnership({ child, instanceId: expected.instanceId, expectedIdentity: expected })

  assert.equal(isCurrentOwnedBackendLive(ownership, ownership), true)
  assert.equal(isCurrentOwnedBackendLive({ ...ownership }, ownership), false)
  assert.equal(clearOwnershipForChild(ownership, staleChild, 'exit'), ownership)
  assert.equal(clearOwnershipForChild(ownership, child, 'error'), ownership)
  assert.equal(clearOwnershipForChild(ownership, child, 'exit'), null)
  assert.equal(clearOwnershipForChild(ownership, child, 'close'), null)

  child.exitCode = 1
  assert.equal(isCurrentOwnedBackendLive(ownership, ownership), false)
})

test('child exit clears ownership while close ends the log stream exactly once', () => {
  const expected = expectedIdentity()
  const child = { pid: expected.backendPid, exitCode: null, signalCode: null }
  const ownership = createBackendOwnership({ child, instanceId: expected.instanceId, expectedIdentity: expected })
  let currentOwnership = ownership
  let logEndCount = 0
  const lifecycle = createBackendChildLifecycle({
    ownership,
    getCurrentOwnership: () => currentOwnership,
    setCurrentOwnership: (value) => { currentOwnership = value },
    endLogStream: () => { logEndCount += 1 },
  })

  lifecycle.handle('exit')
  assert.equal(currentOwnership, null)
  assert.equal(logEndCount, 0)
  lifecycle.handle('close')
  lifecycle.handle('close')
  assert.equal(logEndCount, 1)
})

test('health waiter cannot verify a late response after timeout', async (t) => {
  const expected = expectedIdentity()
  const actual = actualIdentity(expected)
  const child = { pid: expected.backendPid, exitCode: null, signalCode: null }
  const ownership = createBackendOwnership({ child, instanceId: expected.instanceId, expectedIdentity: expected })
  let verifiedCount = 0
  const server = http.createServer((_request, response) => {
    setTimeout(() => {
      if (response.destroyed) return
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ status: 'ok', instanceId: actual.instanceId, runtimeIdentity: actual }))
    }, 80)
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise((resolve) => server.close(resolve)))
  const address = server.address()

  await assert.rejects(() => waitForOwnedBackendHealth({
    apiBase: `http://127.0.0.1:${address.port}`,
    timeoutMs: 20,
    requestTimeoutMs: 200,
    pollIntervalMs: 5,
    ownership,
    getCurrentOwnership: () => ownership,
    onVerified: () => { verifiedCount += 1 },
  }), /timed out/i)
  await new Promise((resolve) => setTimeout(resolve, 100))

  assert.equal(verifiedCount, 0)
  assert.equal(ownership.verifiedIdentity, null)
})

test('health waiter rejects immediately when the owned child exits between polls', async (t) => {
  const expected = expectedIdentity()
  const child = Object.assign(new EventEmitter(), { pid: expected.backendPid, exitCode: null, signalCode: null })
  const ownership = createBackendOwnership({ child, instanceId: expected.instanceId, expectedIdentity: expected })
  const server = http.createServer((_request, response) => {
    setTimeout(() => {
      if (!response.destroyed) response.end('{}')
    }, 150)
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise((resolve) => server.close(resolve)))
  const address = server.address()
  const startedAt = Date.now()
  const waiting = waitForOwnedBackendHealth({
    apiBase: `http://127.0.0.1:${address.port}`,
    timeoutMs: 500,
    requestTimeoutMs: 200,
    pollIntervalMs: 5,
    ownership,
    getCurrentOwnership: () => ownership,
  })
  setTimeout(() => {
    child.exitCode = 1
    child.emit('exit', 1, null)
  }, 10)

  await assert.rejects(() => waiting, /owned child exited/i)
  assert.ok(Date.now() - startedAt < 200)
})

test('prebuild generator writes a fingerprinted manifest without packaging Electron', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dxm-build-manifest-'))
  const output = path.join(root, 'desktop-build-manifest.json')
  const result = spawnSync(process.execPath, [GENERATOR], {
    cwd: path.dirname(GENERATOR),
    encoding: 'utf8',
    env: {
      ...process.env,
      DXM_BUILD_MANIFEST_OUTPUT: output,
      DXM_BUILD_GIT_HEAD: 'abcdef0123456789abcdef0123456789abcdef01',
      DXM_BUILD_GIT_DIRTY: 'true',
      DXM_BUILD_ID: 'test-build-id',
      DXM_BUILD_AT: '2026-07-13T03:00:00.000Z',
    },
  })

  assert.equal(result.status, 0, result.stderr || result.stdout)
  const generated = parseBuildManifest(fs.readFileSync(output, 'utf8'), { expectedPackageVersion: '0.1.0' })
  assert.equal(generated.buildId, 'test-build-id')
  assert.equal(generated.gitDirty, true)
  assert.equal(generated.packageVersion, '0.1.0')
})
