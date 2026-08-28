const fs = require('node:fs')
const path = require('node:path')

const DEV_PACKAGE_NAMES = new Set([
  '_pytest',
  'pip',
  'pytest',
  'setuptools',
  'wheel',
])

function removePath(targetPath) {
  if (!fs.existsSync(targetPath)) return
  fs.rmSync(targetPath, { recursive: true, force: true })
}

function pruneTree(rootPath) {
  if (!fs.existsSync(rootPath)) return
  for (const entry of fs.readdirSync(rootPath, { withFileTypes: true })) {
    const entryPath = path.join(rootPath, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === '__pycache__') {
        removePath(entryPath)
        continue
      }
      pruneTree(entryPath)
      continue
    }
    if (entry.isFile() && entry.name.endsWith('.pyc')) {
      removePath(entryPath)
    }
  }
}

function pruneSitePackages(sitePackagesPath) {
  if (!fs.existsSync(sitePackagesPath)) return
  for (const entry of fs.readdirSync(sitePackagesPath, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const baseName = entry.name.replace(/-.+$/, '')
    if (DEV_PACKAGE_NAMES.has(baseName) || DEV_PACKAGE_NAMES.has(entry.name)) {
      removePath(path.join(sitePackagesPath, entry.name))
    }
  }
}

function prunePackagedRuntime(context) {
  const appOutDir = context.appOutDir
  const backendPath = path.join(appOutDir, 'resources', 'app', 'backend')
  const venvPath = path.join(backendPath, '.venv')
  const sitePackagesPath = path.join(venvPath, 'Lib', 'site-packages')

  pruneSitePackages(sitePackagesPath)
  pruneTree(backendPath)
  console.log(`pruned packaged backend runtime: ${backendPath}`)
}

module.exports = prunePackagedRuntime
