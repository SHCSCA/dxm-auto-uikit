import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildTaskControlButtons,
  humanTaskControlStatus,
  isTaskControlActive,
} from '../src/taskControl.ts'

test('maps human labels for E4 statuses', () => {
  assert.equal(humanTaskControlStatus('pause_requested'), '暂停确认中')
  assert.equal(humanTaskControlStatus('stop_requested'), '停止确认中')
  assert.equal(humanTaskControlStatus('stopped'), '已停止')
  assert.equal(humanTaskControlStatus('paused'), '已暂停')
})

test('running enables pause and stop, not resume', () => {
  const buttons = Object.fromEntries(buildTaskControlButtons({ status: 'running' }).map((b) => [b.action, b]))
  assert.equal(buttons.start.enabled, false)
  assert.equal(buttons.pause.enabled, true)
  assert.equal(buttons.resume.enabled, false)
  assert.equal(buttons.stop.enabled, true)
  assert.equal(isTaskControlActive('running'), true)
})

test('pause_requested shows pending pause and blocks resume', () => {
  const buttons = Object.fromEntries(
    buildTaskControlButtons({
      status: 'pause_requested',
      workerControl: { request: 'pause', pending: true },
    }).map((b) => [b.action, b]),
  )
  assert.equal(buttons.pause.enabled, false)
  assert.equal(buttons.pause.pending, true)
  assert.match(buttons.pause.label, /暂停确认中/)
  assert.equal(buttons.resume.enabled, false)
  assert.equal(buttons.stop.enabled, true)
})

test('paused enables resume and stop only', () => {
  const buttons = Object.fromEntries(
    buildTaskControlButtons({
      status: 'paused',
      workerControl: { ack: 'paused', pending: false },
    }).map((b) => [b.action, b]),
  )
  assert.equal(buttons.pause.enabled, false)
  assert.equal(buttons.resume.enabled, true)
  assert.equal(buttons.resume.primary, true)
  assert.equal(buttons.stop.enabled, true)
  assert.equal(buttons.start.enabled, false)
})

test('stop_requested is pending and disables stop re-click', () => {
  const buttons = Object.fromEntries(
    buildTaskControlButtons({
      status: 'stop_requested',
      workerControl: { request: 'stop', pending: true },
    }).map((b) => [b.action, b]),
  )
  assert.equal(buttons.pause.enabled, false)
  assert.equal(buttons.resume.enabled, false)
  assert.equal(buttons.stop.enabled, false)
  assert.equal(buttons.stop.pending, true)
  assert.equal(isTaskControlActive('stop_requested'), true)
})

test('stopped disables all four keys', () => {
  const buttons = Object.fromEntries(
    buildTaskControlButtons({
      status: 'stopped',
      workerControl: { ack: 'stopped', pending: false },
    }).map((b) => [b.action, b]),
  )
  assert.equal(buttons.start.enabled, false)
  assert.equal(buttons.pause.enabled, false)
  assert.equal(buttons.resume.enabled, false)
  assert.equal(buttons.stop.enabled, false)
  assert.equal(isTaskControlActive('stopped'), false)
})
