const path = require('node:path')

const LOG_LEVELS = new Set(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])

function snapshotEnvironment(environment = process.env) {
  return Object.freeze({ ...environment })
}

function optionalPath(value, key, absolute = false) {
  if (value === undefined || value === '') return null
  if (typeof value !== 'string' || !value.trim() || value.includes('\0')) {
    throw new Error(`${key} 必须为有效路径`)
  }
  if (absolute && !path.isAbsolute(value)) throw new Error(`${key} 必须使用绝对路径`)
  return path.resolve(value)
}

function loadDesktopRuntimeConfig(environment = process.env) {
  const snapshot = snapshotEnvironment(environment)
  const logLevel = String(snapshot.DXM_LOG_LEVEL || 'INFO').toUpperCase()
  if (!LOG_LEVELS.has(logLevel)) throw new Error('DXM_LOG_LEVEL 不是受支持的日志等级')
  return Object.freeze({
    environment: snapshot,
    logLevel,
    buildManifestFile: optionalPath(snapshot.DXM_BUILD_MANIFEST_FILE, 'DXM_BUILD_MANIFEST_FILE'),
    portable: Object.freeze({
      executableFile: optionalPath(snapshot.PORTABLE_EXECUTABLE_FILE, 'PORTABLE_EXECUTABLE_FILE', true),
      executableDir: optionalPath(snapshot.PORTABLE_EXECUTABLE_DIR, 'PORTABLE_EXECUTABLE_DIR', true),
      appFilename: snapshot.PORTABLE_EXECUTABLE_APP_FILENAME,
    }),
  })
}

module.exports = { loadDesktopRuntimeConfig, snapshotEnvironment }
