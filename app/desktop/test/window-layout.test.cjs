const test = require('node:test')
const assert = require('node:assert/strict')

const { resolveDesktopWindowLayout, browserBoundsEnvironment } = require('../src/window-layout.cjs')

test('wide desktop places the console and visible DXM browser without overlap', () => {
  const layout = resolveDesktopWindowLayout({ x: 0, y: 0, width: 1920, height: 1080 })

  assert.equal(layout.mode, 'side_by_side')
  assert.ok(layout.console.x + layout.console.width < layout.browser.x)
  assert.ok(layout.console.width >= 960)
  assert.ok(layout.browser.width >= 800)
  assert.deepEqual(JSON.parse(browserBoundsEnvironment(layout)), layout.browser)
})

test('compact desktop preserves the console and does not falsely promise non-overlap', () => {
  const layout = resolveDesktopWindowLayout({ x: 0, y: 0, width: 1366, height: 768 })

  assert.equal(layout.mode, 'single_surface')
  assert.equal(layout.browser, null)
  assert.equal(browserBoundsEnvironment(layout), null)
})
