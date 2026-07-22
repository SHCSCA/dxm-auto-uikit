const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const repoRoot = path.resolve(__dirname, '..', '..', '..')
const backendRoot = path.join(repoRoot, 'app', 'backend')
const venvPython = path.join(backendRoot, '.venv', 'Scripts', 'python.exe')
const outputRoot = path.resolve(
  process.env.DXM_DESKTOP_PYTHON_RUNTIME_OUTPUT
    || path.join(repoRoot, 'outputs', 'desktop-python-runtime'),
)

const excludedLibRoots = new Set([
  '__pycache__',
  'ensurepip',
  'idlelib',
  'site-packages',
  'test',
  'tkinter',
  'turtledemo',
  'venv',
])

function fail(message) {
  throw new Error(`desktop Python runtime preparation failed: ${message}`)
}

function discoverBaseRuntime() {
  if (!fs.existsSync(venvPython)) fail(`backend venv Python is missing: ${venvPython}`)
  const probe = spawnSync(venvPython, [
    '-c',
    'import json,sys; print(json.dumps({"base_executable":sys._base_executable,"version":list(sys.version_info[:3])}))',
  ], {
    cwd: backendRoot,
    encoding: 'utf8',
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    timeout: 30000,
  })
  if (probe.status !== 0) fail(probe.stderr || probe.stdout || 'base runtime probe failed')
  let payload
  try {
    payload = JSON.parse(String(probe.stdout).trim())
  } catch (error) {
    fail(`base runtime probe returned invalid JSON: ${error.message}`)
  }
  const baseExecutable = path.resolve(String(payload.base_executable || ''))
  const version = Array.isArray(payload.version) ? payload.version.map(Number) : []
  if (!fs.existsSync(baseExecutable)) fail(`base executable is missing: ${baseExecutable}`)
  if (version.length !== 3 || version.some((part) => !Number.isInteger(part))) {
    fail('base runtime version is invalid')
  }
  return { baseExecutable, baseRoot: path.dirname(baseExecutable), version }
}

function shouldCopyLibraryPath(libraryRoot, sourcePath) {
  const relative = path.relative(libraryRoot, sourcePath)
  if (!relative) return true
  const parts = relative.split(path.sep)
  if (excludedLibRoots.has(parts[0].toLowerCase())) return false
  if (parts.some((part) => part.toLowerCase() === '__pycache__')) return false
  return !sourcePath.toLowerCase().endsWith('.pyc')
}

function copyRuntime({ baseRoot, version }) {
  fs.rmSync(outputRoot, { recursive: true, force: true })
  fs.mkdirSync(outputRoot, { recursive: true })

  const requiredRootFiles = new Set([
    'python.exe',
    'python3.dll',
    `python${version[0]}${version[1]}.dll`,
  ])
  const copiedRootFiles = new Set()
  for (const entry of fs.readdirSync(baseRoot, { withFileTypes: true })) {
    if (!entry.isFile()) continue
    const name = entry.name
    if (!/^(python(?:w)?\.exe|python\d*\.dll|vcruntime[^/\\]*\.dll|license[^/\\]*)$/i.test(name)) continue
    fs.copyFileSync(path.join(baseRoot, name), path.join(outputRoot, name))
    copiedRootFiles.add(name.toLowerCase())
  }
  for (const requiredName of requiredRootFiles) {
    if (!copiedRootFiles.has(requiredName.toLowerCase())) {
      fail(`required base runtime file is missing: ${path.join(baseRoot, requiredName)}`)
    }
  }

  const dllRoot = path.join(baseRoot, 'DLLs')
  const libraryRoot = path.join(baseRoot, 'Lib')
  if (!fs.existsSync(dllRoot) || !fs.existsSync(libraryRoot)) {
    fail(`base runtime DLLs or Lib directory is missing: ${baseRoot}`)
  }
  fs.cpSync(dllRoot, path.join(outputRoot, 'DLLs'), {
    recursive: true,
    filter: (sourcePath) => !sourcePath.toLowerCase().endsWith('.pyc')
      && !sourcePath.split(path.sep).some((part) => part.toLowerCase() === '__pycache__'),
  })
  fs.cpSync(libraryRoot, path.join(outputRoot, 'Lib'), {
    recursive: true,
    filter: (sourcePath) => shouldCopyLibraryPath(libraryRoot, sourcePath),
  })
}

function verifyRuntime() {
  const outputPython = path.join(outputRoot, 'python.exe')
  const cleanEnvironment = { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }
  for (const key of Object.keys(cleanEnvironment)) {
    if (['PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'].includes(key.toUpperCase())) {
      delete cleanEnvironment[key]
    }
  }
  const smoke = spawnSync(outputPython, [
    '-B',
    '-I',
    '-c',
    'import asyncio,ctypes,json,sqlite3,ssl,sys; print(sys.executable)',
  ], {
    cwd: outputRoot,
    encoding: 'utf8',
    env: cleanEnvironment,
    timeout: 30000,
  })
  if (smoke.status !== 0) fail(smoke.stderr || smoke.stdout || 'staged runtime smoke failed')
  const executable = path.resolve(String(smoke.stdout).trim())
  if (executable.toLowerCase() !== outputPython.toLowerCase()) {
    fail(`staged runtime escaped its package root: ${executable}`)
  }
}

const runtime = discoverBaseRuntime()
copyRuntime(runtime)
verifyRuntime()
console.log(`prepared self-contained Python ${runtime.version.join('.')} runtime: ${outputRoot}`)
