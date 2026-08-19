const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
  QA_DEADLINE_MIN_MS,
  QA_DEADLINE_MAX_MS,
  classifyLaunchArguments,
  resolveSelectedDataDir,
  selectBackendPort,
  inspectLegacyRuntimePorts,
} = require('../src/launch-policy.cjs')
const {
  createRuntimeStarter,
  focusExistingWindow,
} = require('../src/runtime-start.cjs')

function makeWorkspace(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dxm-launch-policy-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const normalUserDataDir = path.join(root, 'normal-user-data')
  fs.mkdirSync(normalUserDataDir, { recursive: true })
  return { root, normalUserDataDir }
}

function validQaArgs(root, overrides = []) {
  return [
    '--disable-gpu',
    `--qa-user-data-dir=${path.join(root, 'qa-user-data')}`,
    `--qa-capture=${path.join(root, 'outputs', 'capture.png')}`,
    ...overrides,
  ]
}

test('ordinary launch ignores unrelated Chromium flags and has no QA side effects', (t) => {
  const { normalUserDataDir } = makeWorkspace(t)

  const policy = classifyLaunchArguments({
    argv: ['electron', '.', '--disable-gpu', '--no-sandbox'],
    normalUserDataDir,
  })

  assert.equal(policy.kind, 'normal')
  assert.equal(policy.isIsolatedQa, false)
  assert.equal(policy.qaUserDataDir, null)
  assert.deepEqual(policy.smokeOutputs, {
    capture: null,
    visible: null,
    credential: null,
  })
})

test('valid isolated QA accepts absolute disjoint paths without creating them', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const qaUserDataDir = path.join(root, 'qa-user-data')
  const capturePath = path.join(root, 'outputs', 'capture.png')

  const policy = classifyLaunchArguments({
    argv: validQaArgs(root),
    normalUserDataDir,
  })

  assert.equal(policy.kind, 'isolated-qa')
  assert.equal(policy.isIsolatedQa, true)
  assert.equal(policy.qaUserDataDir, qaUserDataDir)
  assert.equal(policy.smokeOutputs.capture, capturePath)
  assert.equal(policy.deadlineMs, null)
  assert.equal(fs.existsSync(qaUserDataDir), false)
  assert.equal(fs.existsSync(path.dirname(capturePath)), false)
})

test('QA requires absolute non-empty user-data and output paths', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const absoluteQa = path.join(root, 'qa-user-data')
  const absoluteOutput = path.join(root, 'outputs', 'capture.png')
  const invalidSets = [
    [`--qa-user-data-dir=`, `--qa-capture=${absoluteOutput}`],
    ['--qa-user-data-dir=relative', `--qa-capture=${absoluteOutput}`],
    [`--qa-user-data-dir=${absoluteQa}`, '--qa-capture='],
    [`--qa-user-data-dir=${absoluteQa}`, '--qa-capture=relative.png'],
    [`--qa-capture=${absoluteOutput}`],
    [`--qa-user-data-dir=${absoluteQa}`],
  ]

  for (const argv of invalidSets) {
    assert.throws(
      () => classifyLaunchArguments({ argv, normalUserDataDir }),
      /QA|absolute|non-empty|requires/i,
      argv.join(' '),
    )
  }
})

test('QA rejects duplicate and unknown qa flags while allowing unrelated flags', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const args = validQaArgs(root)

  assert.throws(
    () => classifyLaunchArguments({
      argv: [...args, `--qa-visible-smoke=${path.join(root, 'outputs', 'visible.json')}`, '--qa-magic=1'],
      normalUserDataDir,
    }),
    /unknown QA argument.*qa-magic/i,
  )
  assert.throws(
    () => classifyLaunchArguments({ argv: [...args, args[1]], normalUserDataDir }),
    /duplicate QA argument.*qa-user-data-dir/i,
  )
  assert.equal(
    classifyLaunchArguments({ argv: [...args, '--inspect=0'], normalUserDataDir }).isIsolatedQa,
    true,
  )
})

test('capture and visible smoke are mutually exclusive while credential may accompany either', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const qaUserDataDir = path.join(root, 'qa-user-data')
  const capture = path.join(root, 'outputs', 'capture.png')
  const visible = path.join(root, 'outputs', 'visible.json')
  const credential = path.join(root, 'outputs', 'credential.json')

  assert.throws(() => classifyLaunchArguments({
    argv: [
      `--qa-user-data-dir=${qaUserDataDir}`,
      `--qa-capture=${capture}`,
      `--qa-visible-smoke=${visible}`,
    ],
    normalUserDataDir,
  }), /capture.*visible|visible.*capture/i)

  for (const primarySmoke of [
    `--qa-capture=${capture}`,
    `--qa-visible-smoke=${visible}`,
  ]) {
    const policy = classifyLaunchArguments({
      argv: [
        `--qa-user-data-dir=${qaUserDataDir}`,
        primarySmoke,
        `--qa-credential-smoke=${credential}`,
      ],
      normalUserDataDir,
    })
    assert.equal(policy.isIsolatedQa, true)
    assert.equal(policy.smokeOutputs.credential, credential)
  }
})

test('QA user-data rejects normal path equality, ancestors, and descendants', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const output = path.join(root, 'outputs', 'capture.png')
  const overlapping = [
    normalUserDataDir,
    path.dirname(normalUserDataDir),
    path.join(normalUserDataDir, 'qa-child'),
  ]

  for (const qaUserDataDir of overlapping) {
    assert.throws(
      () => classifyLaunchArguments({
        argv: [`--qa-user-data-dir=${qaUserDataDir}`, `--qa-capture=${output}`],
        normalUserDataDir,
      }),
      /disjoint/i,
      qaUserDataDir,
    )
  }
})

test('QA output paths must remain outside the normal user-data tree', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)

  assert.throws(
    () => classifyLaunchArguments({
      argv: [
        `--qa-user-data-dir=${path.join(root, 'qa-user-data')}`,
        `--qa-visible-smoke=${path.join(normalUserDataDir, 'qa', 'visible.json')}`,
      ],
      normalUserDataDir,
    }),
    /output.*normal userData/i,
  )
})

test('QA canonical comparison rejects junction aliases and alias descendants where supported', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const junction = path.join(root, 'normal-user-data-alias')
  try {
    fs.symlinkSync(normalUserDataDir, junction, process.platform === 'win32' ? 'junction' : 'dir')
  } catch (error) {
    t.skip(`directory link unavailable: ${error.message}`)
    return
  }

  assert.throws(
    () => classifyLaunchArguments({
      argv: [
        `--qa-user-data-dir=${path.join(junction, 'qa-child')}`,
        `--qa-capture=${path.join(root, 'outputs', 'capture.png')}`,
      ],
      normalUserDataDir,
    }),
    /disjoint/i,
  )
  assert.throws(
    () => classifyLaunchArguments({
      argv: [
        `--qa-user-data-dir=${path.join(root, 'qa-user-data')}`,
        `--qa-credential-smoke=${path.join(junction, 'qa-output.json')}`,
      ],
      normalUserDataDir,
    }),
    /output.*normal userData/i,
  )
})

test('QA deadline is bounded and never grants QA identity by itself', (t) => {
  const { root, normalUserDataDir } = makeWorkspace(t)
  const valid = validQaArgs(root)

  for (const value of ['', '0', '-1', '1.5', 'abc', String(QA_DEADLINE_MIN_MS - 1), String(QA_DEADLINE_MAX_MS + 1)]) {
    assert.throws(
      () => classifyLaunchArguments({ argv: [...valid, `--qa-deadline-ms=${value}`], normalUserDataDir }),
      /qa-deadline-ms/i,
      value,
    )
  }
  assert.throws(
    () => classifyLaunchArguments({ argv: [`--qa-deadline-ms=${QA_DEADLINE_MIN_MS}`], normalUserDataDir }),
    /requires.*qa-user-data-dir.*smoke/i,
  )

  const policy = classifyLaunchArguments({
    argv: [...valid, `--qa-deadline-ms=${QA_DEADLINE_MAX_MS}`],
    normalUserDataDir,
  })
  assert.equal(policy.deadlineMs, QA_DEADLINE_MAX_MS)
})

test('selected QA data always lives below QA userData while normal dev keeps repo data', (t) => {
  const { root } = makeWorkspace(t)
  const repoRoot = path.join(root, 'repo')
  const userDataDir = path.join(root, 'user-data')

  assert.equal(
    resolveSelectedDataDir({ isIsolatedQa: true, isPackaged: false, repoRoot, userDataDir }),
    path.join(userDataDir, 'data'),
  )
  assert.equal(
    resolveSelectedDataDir({ isIsolatedQa: true, isPackaged: true, repoRoot, userDataDir }),
    path.join(userDataDir, 'data'),
  )
  assert.equal(
    resolveSelectedDataDir({ isIsolatedQa: false, isPackaged: false, repoRoot, userDataDir }),
    path.join(repoRoot, 'data'),
  )
  assert.equal(
    resolveSelectedDataDir({ isIsolatedQa: false, isPackaged: true, repoRoot, userDataDir }),
    path.join(userDataDir, 'data'),
  )
})

test('packaged launch skips occupied 8000 and uses the next free loopback port', async () => {
  const packagedPort = await selectBackendPort({
    isIsolatedQa: false,
    isPackaged: true,
    isPortFree: async (port) => port === 8003,
  })
  assert.equal(packagedPort, 8003)

  const packagedDefault = await selectBackendPort({
    isIsolatedQa: false,
    isPackaged: true,
    isPortFree: async () => true,
  })
  assert.equal(packagedDefault, 8000)
})

test('normal launch is fixed to port 8000 and isolated QA alone may select 8000..8079', async () => {
  let checks = 0
  const normalPort = await selectBackendPort({
    isIsolatedQa: false,
    isPortFree: async () => {
      checks += 1
      return true
    },
  })
  assert.equal(normalPort, 8000)
  assert.equal(checks, 0)

  const qaPort = await selectBackendPort({
    isIsolatedQa: true,
    isPortFree: async (port) => {
      checks += 1
      return port === 8002
    },
  })
  assert.equal(qaPort, 8002)
  assert.equal(checks, 80)

  await assert.rejects(
    selectBackendPort({ isIsolatedQa: true, isPortFree: async () => false }),
    /no free loopback port.*8000.*8079/i,
  )
})

test('isolated QA port selection has one total deadline and ignores late lower-port results', async () => {
  let releaseLate
  let aborted = false
  const latePort = new Promise((resolve) => { releaseLate = resolve })
  const startedAt = Date.now()

  const selected = await selectBackendPort({
    isIsolatedQa: true,
    deadlineMs: 35,
    isPortFree: async (port, { signal }) => {
      if (port === 8000) {
        signal.addEventListener('abort', () => { aborted = true }, { once: true })
        return latePort
      }
      return port === 8001
    },
  })

  assert.equal(selected, 8001)
  assert.equal(aborted, true)
  assert.ok(Date.now() - startedAt < 250)
  releaseLate(true)
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(selected, 8001)
})

test('isolated QA port selection fails within its total deadline when all facts are unresolved', async () => {
  const startedAt = Date.now()
  const abortedPorts = []

  await assert.rejects(
    selectBackendPort({
      isIsolatedQa: true,
      deadlineMs: 30,
      isPortFree: async (port, { signal }) => new Promise((resolve) => {
        signal.addEventListener('abort', () => {
          abortedPorts.push(port)
          resolve(false)
        }, { once: true })
      }),
    }),
    /no free loopback port.*total deadline/i,
  )
  assert.equal(abortedPorts.length, 80)
  assert.ok(Date.now() - startedAt < 250)
})

test('legacy diagnostics reject same canonical data on fixed or shifted ports with owner facts', async (t) => {
  const { root } = makeWorkspace(t)
  const dataDir = path.join(root, 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  const tcpProbe = async ({ port }) => port === 8001
  const httpProbe = async ({ port, pathname }) => {
    if (port === 8001 && pathname === '/health') {
      return {
        statusCode: 200,
        body: JSON.stringify({
          status: 'ok',
          runtimeIdentity: { dataDir, backendPid: 321, instanceId: 'legacy-shifted' },
        }),
      }
    }
    return { statusCode: 404, body: '{}' }
  }

  await assert.rejects(
    inspectLegacyRuntimePorts({ dataDir, ports: [8000, 8001], tcpProbe, httpProbe, deadlineMs: 200 }),
    (error) => {
      assert.equal(error.code, 'DXM_SAME_DATA_RUNTIME')
      assert.match(error.message, /8001/)
      assert.match(error.message, /321/)
      assert.match(error.message, /legacy-shifted/)
      return true
    },
  )
})

test('legacy paths.data_dir is recognized as same-data evidence', async (t) => {
  const { root } = makeWorkspace(t)
  const dataDir = path.join(root, 'data')
  fs.mkdirSync(dataDir, { recursive: true })

  await assert.rejects(
    inspectLegacyRuntimePorts({
      dataDir,
      ports: [8000, 8004],
      tcpProbe: async ({ port }) => port === 8004,
      httpProbe: async ({ pathname }) => pathname === '/api/runtime/status'
        ? { statusCode: 200, body: JSON.stringify({ paths: { data_dir: dataDir }, backend: { pid: 88, instanceId: 'old' } }) }
        : { statusCode: 404, body: '{}' },
      deadlineMs: 200,
    }),
    (error) => error.code === 'DXM_SAME_DATA_RUNTIME' && /8004/.test(error.message),
  )
})

test('an unrelated or malformed occupant on port 8000 is rejected without adoption', async (t) => {
  const { root } = makeWorkspace(t)
  const dataDir = path.join(root, 'data')

  await assert.rejects(
    inspectLegacyRuntimePorts({
      dataDir,
      ports: [8000],
      tcpProbe: async () => true,
      httpProbe: async () => ({ statusCode: 200, body: '{malformed' }),
      deadlineMs: 200,
    }),
    (error) => error.code === 'DXM_PORT_8000_OCCUPIED' && /do not adopt or kill/i.test(error.message),
  )
})

test('a different-data shifted runtime does not block normal fixed-port startup', async (t) => {
  const { root } = makeWorkspace(t)
  const dataDir = path.join(root, 'data')
  const result = await inspectLegacyRuntimePorts({
    dataDir,
    ports: [8000, 8001],
    tcpProbe: async ({ port }) => port === 8001,
    httpProbe: async ({ pathname }) => ({
      statusCode: 200,
      body: pathname === '/health'
        ? JSON.stringify({ status: 'ok', runtimeIdentity: { dataDir: path.join(root, 'other-data') } })
        : '{}',
    }),
    deadlineMs: 200,
  })

  assert.equal(result.ok, true)
  assert.equal(result.port8000, 'free')
  assert.deepEqual(result.occupiedPorts, [8001])
})

test('all 80 legacy probes share one deadline, cancel pending work, and ignore late identity', async (t) => {
  const { root } = makeWorkspace(t)
  const dataDir = path.join(root, 'data')
  const started = []
  const aborted = []
  let releaseLate
  const late = new Promise((resolve) => { releaseLate = resolve })

  const result = await inspectLegacyRuntimePorts({
    dataDir,
    tcpProbe: async ({ port, signal }) => {
      started.push(port)
      if (port === 8000) return false
      if (port === 8001) return true
      signal.addEventListener('abort', () => aborted.push(port), { once: true })
      return new Promise(() => {})
    },
    httpProbe: async ({ port, pathname, signal, maxBodyBytes }) => {
      assert.equal(maxBodyBytes, 4096)
      signal.addEventListener('abort', () => aborted.push(`${port}:${pathname}`), { once: true })
      return late
    },
    deadlineMs: 35,
    maxBodyBytes: 4096,
  })

  assert.equal(started.length, 80)
  assert.equal(result.ok, true)
  assert.equal(result.deadlineReached, true)
  assert.equal(result.port8000, 'free')
  assert.ok(aborted.length >= 79)
  releaseLate({
    statusCode: 200,
    body: JSON.stringify({ runtimeIdentity: { dataDir } }),
  })
  await new Promise((resolve) => setTimeout(resolve, 15))
  assert.deepEqual(result.sameDataRuntimes, [])
})

test('an unresolved port 8000 TCP fact fails closed at the shared deadline', async (t) => {
  const { root } = makeWorkspace(t)

  await assert.rejects(
    inspectLegacyRuntimePorts({
      dataDir: path.join(root, 'data'),
      ports: [8000],
      tcpProbe: async () => new Promise(() => {}),
      httpProbe: async () => ({ statusCode: 200, body: '{}' }),
      deadlineMs: 25,
    }),
    (error) => error.code === 'DXM_PORT_8000_UNCERTAIN',
  )
})

test('runtime starter caches exactly one promise including rejection', async () => {
  let calls = 0
  const expected = { apiBase: 'http://127.0.0.1:8000' }
  const startRuntimeOnce = createRuntimeStarter(async () => {
    calls += 1
    return expected
  })

  const first = startRuntimeOnce()
  const second = startRuntimeOnce()
  assert.strictEqual(first, second)
  assert.strictEqual(await first, expected)
  assert.equal(calls, 1)

  const failure = new Error('startup failed')
  let failedCalls = 0
  const startFailedOnce = createRuntimeStarter(async () => {
    failedCalls += 1
    throw failure
  })
  const rejected = startFailedOnce()
  await assert.rejects(rejected, failure)
  assert.strictEqual(startFailedOnce(), rejected)
  assert.equal(failedCalls, 1)
})

test('second-instance focusing restores, shows, and focuses only the current window', () => {
  const calls = []
  const window = {
    isDestroyed: () => false,
    isMinimized: () => true,
    restore: () => calls.push('restore'),
    show: () => calls.push('show'),
    focus: () => calls.push('focus'),
  }

  assert.equal(focusExistingWindow(() => window), true)
  assert.deepEqual(calls, ['restore', 'show', 'focus'])
  assert.equal(focusExistingWindow(() => null), false)
})
