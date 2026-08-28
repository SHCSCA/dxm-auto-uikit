import assert from 'node:assert/strict'
import test from 'node:test'

import { canContinueDxmLogin, dxmLoginContinueDisabledReason } from '../src/dxmLoginUi.ts'

test('captcha handoff remains actionable when the global busy flag is stale', () => {
  assert.equal(canContinueDxmLogin({
    status: 'waiting_captcha',
    browserVisible: true,
    busy: true,
  }), true)
  assert.equal(dxmLoginContinueDisabledReason({
    status: 'waiting_captcha',
    browserVisible: true,
    busy: true,
  }), '')
})

test('login continuation stays blocked without a visible handoff or while its request is pending', () => {
  assert.equal(canContinueDxmLogin({
    status: 'waiting_captcha',
    browserVisible: false,
    busy: false,
  }), false)
  assert.equal(canContinueDxmLogin({
    status: 'waiting_captcha',
    browserVisible: true,
    busy: false,
    requestPending: true,
  }), false)
  assert.match(dxmLoginContinueDisabledReason({
    status: 'waiting_captcha',
    browserVisible: true,
    busy: false,
    requestPending: true,
  }), /正在检测/)
})

test('non-login runtime states cannot invoke login continuation', () => {
  assert.equal(canContinueDxmLogin({
    status: 'logged_in',
    browserVisible: true,
    busy: true,
  }), false)
  assert.equal(canContinueDxmLogin({
    status: 'idle',
    browserVisible: true,
    busy: false,
  }), false)
})
