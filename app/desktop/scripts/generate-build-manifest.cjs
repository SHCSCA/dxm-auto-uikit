const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const { createBuildManifest, readGitBuildState } = require('../src/runtime-identity.cjs')

const desktopDir = path.resolve(__dirname, '..')
const repoRoot = path.resolve(desktopDir, '..', '..')
const packageJson = JSON.parse(fs.readFileSync(path.join(desktopDir, 'package.json'), 'utf8'))
const outputPath = path.resolve(
  process.env.DXM_BUILD_MANIFEST_OUTPUT
  || path.join(repoRoot, 'outputs', 'build-metadata', 'desktop-build-manifest.json'),
)

function parseDirty(value) {
  if (value === undefined) return null
  if (value === 'true') return true
  if (value === 'false') return false
  throw new Error('DXM_BUILD_GIT_DIRTY must be true or false')
}

const probed = readGitBuildState(repoRoot)
const envDirty = parseDirty(process.env.DXM_BUILD_GIT_DIRTY)
const manifest = createBuildManifest({
  gitHead: process.env.DXM_BUILD_GIT_HEAD || probed.gitHead,
  gitDirty: envDirty === null ? probed.gitDirty : envDirty,
  buildId: process.env.DXM_BUILD_ID || `desktop-${crypto.randomUUID()}`,
  packageVersion: packageJson.version,
  builtAt: process.env.DXM_BUILD_AT || new Date().toISOString(),
})

fs.mkdirSync(path.dirname(outputPath), { recursive: true })
fs.writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
process.stdout.write(`desktop build manifest written: ${outputPath}\n`)
