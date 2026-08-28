function finiteInteger(value, fallback) {
  return Number.isFinite(value) ? Math.round(value) : fallback
}

/**
 * Keep the native console and the visible DXM browser side-by-side when the
 * monitor has enough real work area.  On smaller displays we preserve a
 * normal console window and deliberately do not claim that two independent
 * desktop windows can be non-overlapping.
 */
function resolveDesktopWindowLayout(workArea) {
  const area = {
    x: finiteInteger(workArea?.x, 0),
    y: finiteInteger(workArea?.y, 0),
    width: finiteInteger(workArea?.width, 1920),
    height: finiteInteger(workArea?.height, 1080),
  }
  const margin = 12
  const gap = 16
  const usableWidth = Math.max(0, area.width - (margin * 2) - gap)
  const usableHeight = Math.max(720, area.height - (margin * 2))
  const consoleMinWidth = 960
  const browserMinWidth = 800
  const height = Math.min(900, usableHeight)

  if (usableWidth >= consoleMinWidth + browserMinWidth) {
    const consoleWidth = Math.max(consoleMinWidth, Math.min(1120, Math.round(usableWidth * 0.55)))
    const browserWidth = usableWidth - consoleWidth
    return {
      mode: 'side_by_side',
      console: { x: area.x + margin, y: area.y + margin, width: consoleWidth, height },
      browser: { x: area.x + margin + consoleWidth + gap, y: area.y + margin, width: browserWidth, height },
    }
  }

  const consoleWidth = Math.min(1280, Math.max(960, area.width - (margin * 2)))
  return {
    mode: 'single_surface',
    console: { x: area.x + Math.max(0, Math.floor((area.width - consoleWidth) / 2)), y: area.y + margin, width: consoleWidth, height },
    browser: null,
  }
}

function browserBoundsEnvironment(layout) {
  if (!layout?.browser) return null
  return JSON.stringify(layout.browser)
}

module.exports = { resolveDesktopWindowLayout, browserBoundsEnvironment }
