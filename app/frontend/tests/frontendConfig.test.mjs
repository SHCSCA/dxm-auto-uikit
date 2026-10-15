import assert from 'node:assert/strict'
import test from 'node:test'
import { spawnSync } from 'node:child_process'
import { resolveApiConfiguration } from '../src/config/frontendConfig.ts'

test('API configuration accepts same-origin and credential-free loopback URLs only', () => {
  for (const apiBase of ['', 'http://localhost:8000', 'https://127.0.0.1:8443/', 'http://[::1]:8000']) {
    const result = resolveApiConfiguration(`?apiBase=${encodeURIComponent(apiBase)}`)
    assert.equal(result.error, null)
    assert.equal(result.apiBase, apiBase.replace(/\/+$/, ''))
  }
  assert.equal(resolveApiConfiguration('?apiBase=', 'https://remote.invalid').apiBase, '')
  for (const apiBase of [
    'https://remote.invalid', '//127.0.0.1:8000', '/api', 'file:///tmp/local',
    'http://user:secret@127.0.0.1:8000', 'http://@localhost:8000',
    'http://127.0.0.1:8000?token=secret', 'http://localhost:8000/#secret',
    'http://127.0.0.1.remote.invalid', 'http://localhost:99999', 'http://127.1:8000', 'http://localhost:0',
  ]) {
    const result = resolveApiConfiguration(`?apiBase=${encodeURIComponent(apiBase)}`)
    assert.equal(result.reasonCode, 'FRONTEND_API_BASE_INVALID')
    assert.equal(result.apiBase, '')
    assert.doesNotMatch(result.error, /secret|remote\.invalid/)
  }
  assert.equal(resolveApiConfiguration('', {}).reasonCode, 'FRONTEND_API_BASE_INVALID')
})

test('invalid runtime configuration rejects a write before fetch is called', () => {
  const source = `
    globalThis.window = { location: { search: '?apiBase=https%3A%2F%2Fremote.invalid' } };
    let calls = 0;
    globalThis.fetch = async () => { calls++; throw new Error('fetch must stay closed'); };
    console.error = () => {};
    const { postJson } = await import('./src/api.ts');
    try { await postJson('/api/tasks/1/approve-and-start', {}); process.exitCode = 2; }
    catch (error) { if (error.reasonCode !== 'FRONTEND_API_BASE_INVALID' || calls !== 0) process.exitCode = 3; }
  `
  const result = spawnSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e', source], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
})
