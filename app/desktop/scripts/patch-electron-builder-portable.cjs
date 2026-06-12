const fs = require('node:fs')
const path = require('node:path')

const templatePath = path.join(
  __dirname,
  '..',
  'node_modules',
  'app-builder-lib',
  'templates',
  'nsis',
  'portable.nsi'
)

const original = 'ExecWait "$INSTDIR\\${APP_EXECUTABLE_FILENAME} $R0" $0'
const singleQuotedAttempt = 'ExecWait \'"$INSTDIR\\${APP_EXECUTABLE_FILENAME}" $R0\' $0'
const fixed = 'ExecWait `"$INSTDIR\\${APP_EXECUTABLE_FILENAME}" $R0` $0'

if (!fs.existsSync(templatePath)) {
  throw new Error(`electron-builder portable template is missing: ${templatePath}`)
}

const source = fs.readFileSync(templatePath, 'utf8')
if (source.includes(fixed)) {
  console.log('electron-builder portable template already patched')
  process.exit(0)
}

const patchTarget = source.includes(original) ? original : singleQuotedAttempt
if (!source.includes(patchTarget)) {
  throw new Error('electron-builder portable template no longer matches expected ExecWait line')
}

fs.writeFileSync(templatePath, source.replace(patchTarget, fixed), 'utf8')
console.log('patched electron-builder portable template ExecWait quoting')
