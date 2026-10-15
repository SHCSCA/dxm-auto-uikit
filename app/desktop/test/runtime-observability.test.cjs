const assert = require('node:assert/strict')
const test = require('node:test')
const path = require('node:path')
const { loadDesktopRuntimeConfig } = require('../src/runtime-config.cjs')
const { serializeDesktopLog, exceptionFields, redactText } = require('../src/runtime-observability.cjs')

test('desktop configuration freezes launch inputs without changing global environment', () => {
  const environment = { DXM_LOG_LEVEL: 'warning', DXM_BUILD_MANIFEST_FILE: path.resolve('manifest.json') }
  const config = loadDesktopRuntimeConfig(environment)
  environment.DXM_LOG_LEVEL = 'debug'
  assert.equal(config.logLevel, 'WARNING')
  assert.equal(config.environment.DXM_LOG_LEVEL, 'warning')
  assert.equal(Object.isFrozen(config), true)
  assert.equal(Object.isFrozen(config.environment), true)
  assert.equal(Object.isFrozen(config.portable), true)
})

test('desktop configuration rejects unknown log levels and relative portable authority', () => {
  assert.throws(() => loadDesktopRuntimeConfig({ DXM_LOG_LEVEL: 'quiet' }), /DXM_LOG_LEVEL/)
  assert.throws(() => loadDesktopRuntimeConfig({ PORTABLE_EXECUTABLE_FILE: 'relative.exe' }), /绝对路径/)
})

test('desktop diagnostics share backend schema and remove nested credentials', () => {
  const serialized = serializeDesktopLog('failed', { level: 'ERROR', fields: {
    password: 'private-password', nested: { api_key: 'private-api-key', raw_body: 'private-body' },
    diagnostic: 'Bearer private-bearer token=private-token https://unit.invalid/path?id=private-id',
  } })
  for (const value of ['private-password', 'private-api-key', 'private-body', 'private-bearer', 'private-token', 'private-id']) {
    assert.equal(serialized.includes(value), false)
  }
  const payload = JSON.parse(serialized)
  assert.equal(payload.schema, 'dxm.log.v1')
  assert.equal(payload.level, 'ERROR')
})

test('desktop exception serialization preserves original reason for caller semantics', () => {
  const reason = new Error('cookie=private-session')
  const serialized = serializeDesktopLog('unhandled_rejection', { fields: exceptionFields(reason) })
  assert.equal(serialized.includes('private-session'), false)
  assert.equal(reason.message, 'cookie=private-session')
  assert.equal(JSON.parse(serialized).fields.exception_type, 'Error')
})

test('quoted passwords and complete cookie headers are not partially retained', () => {
  const serialized = serializeDesktopLog('failed', { fields: {
    detail: 'password="private first second"\nCookie: first=private-one; second=private-two',
  } })
  assert.equal(serialized.includes('private'), false)
})

test('escaped quote backslash and multiline JSON secrets never retain a suffix', () => {
  for (const secret of ['prefix"private-tail', 'prefix\\private-tail', 'prefix\nprivate-tail',
    'prefix\\"private-tail', 'prefix\\\\"private-tail']) {
    const raw = JSON.stringify({ password: secret, safe: 'preserved' })
    assert.deepEqual(JSON.parse(redactText(raw)), { password: '[REDACTED]', safe: 'preserved' })
    for (const message of ['provider: ' + raw + ' completed', 'provider body=' + JSON.stringify(raw),
      'provider: ' + JSON.stringify({ nested: [{ api_key: secret }] })]) {
      assert.equal(redactText(message).includes('private-tail'), false)
    }
  }
})

test('unknown truncated or multiply escaped secret formats fail closed', () => {
  for (const message of ['password="prefix\\"private-tail',
    'body="{\\"password\\":\\"prefix\\\\\\"private-tail',
    '{"password":"prefix\\\\"private-tail"}', 'password="prefix\nprivate-tail']) {
    assert.equal(redactText(message).includes('private-tail'), false)
  }
})

test('redaction marker prefixes never authorize a secret suffix', () => {
  for (const message of ['password=[REDACTED]private-tail', 'password="[REDACTED]private-tail',
    "password='[REDACTED]private-tail", 'password="[REDACTED]private-tail"', 'passphrase=private-tail',
    'password=[REDACTED]private-tail {"status":"safe"} private-tail']) {
    assert.equal(redactText(message).includes('private-tail'), false)
  }
})

test('secret headers in JSON strings preserve structural boundaries and following safe fields', () => {
  for (const header of ['Cookie: first=private-tail', 'Set-Cookie: first=private-tail',
    'Authorization: Bearer private-tail', 'passphrase=private-tail']) {
    const raw = JSON.stringify({ message: header, status: 'preserved', nested: { safe: 3 } })
    const sanitized = redactText(raw)
    const parsed = JSON.parse(sanitized)
    assert.equal(sanitized.includes('private-tail'), false)
    assert.equal(parsed.message.endsWith('[REDACTED]'), true)
    assert.equal(parsed.status, 'preserved')
    assert.deepEqual(parsed.nested, { safe: 3 })
    const embedded = redactText('before ' + raw + ' after')
    assert.equal(embedded.startsWith('before '), true)
    assert.equal(embedded.endsWith(' after'), true)
    assert.deepEqual(JSON.parse(embedded.slice(7, -6)), parsed)
    assert.deepEqual(JSON.parse(JSON.parse(redactText(JSON.stringify(raw)))), parsed)
  }
})

test('nonsecret escaped JSON and surrounding context stay readable', () => {
  const safe = { path: 'C:\\runtime\\safe', note: 'a "quoted"\nline', status: 'saved' }
  assert.deepEqual(JSON.parse(redactText(JSON.stringify(safe))), safe)
  const sanitized = redactText('before ' + JSON.stringify({ password: 'private"tail', status: 'saved' }) + ' after')
  assert.equal(sanitized.startsWith('before '), true)
  assert.equal(sanitized.endsWith(' after'), true)
  assert.equal(JSON.parse(sanitized.slice(7, -6)).status, 'saved')
})
