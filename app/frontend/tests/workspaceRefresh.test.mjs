import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

// Exercise the actual hooks without starting Electron or changing production APIs.
const source = ts.createSourceFile('App.tsx', readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const app = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'App')
function evaluateHook(statement, context) {
  return runInNewContext(ts.transpileModule(statement.getText(source), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText, context)
}

test('a pending delivery check cannot withhold templates or workspace readiness', async () => {
  const declaration = app.body.statements.find((node) => ts.isVariableStatement(node)
    && node.declarationList.declarations.some((item) => item.name.getText(source) === 'refreshWorkspace'))
  const refs = [{ id: 'reference-from-api' }]
  const state = {}
  const context = {
    useCallback: (callback) => callback,
    selectedTaskId: null,
    workspaceRefreshGenerationRef: { current: 0 },
    getJson: async (path) => {
      if (path === '/api/delivery/final-check') return new Promise(() => {})
      if (path === '/api/dxm-template-refs') return refs
      return path === '/api/delivery/workspace' ? null : []
    },
    composeWorkspace: (bundle) => bundle,
    pickTaskIdForOperatorPath: () => null,
    syncSelectedTaskIdUrl: () => {},
  }
  for (const setter of declaration.getText(source).matchAll(/\b(set[A-Z]\w*)\(/g)) {
    context[setter[1]] = (value) => { state[setter[1]] = value }
  }
  evaluateHook(declaration, context)
  const result = await Promise.race([
    runInNewContext('refreshWorkspace()', context).then(() => 'loaded'),
    new Promise((resolve) => setImmediate(() => resolve('blocked'))),
  ])
  assert.equal(result, 'loaded')
  assert.equal(state.setDxmTemplateRefs, refs)
  assert.equal(state.setWorkspaceNotice, null)
})

test('workspace polling waits for a slow refresh and stops scheduling on unmount', async () => {
  const effect = app.body.statements.find((node) => ts.isExpressionStatement(node)
    && node.getText(source).startsWith('useEffect(')
    && node.getText(source).includes('if (!workspaceHasRunningTask'))
  const timers = []
  let finishRefresh
  let cleanup
  const context = {
    workspaceHasRunningTask: true,
    workspaceHasRunningBatch: false,
    agentConsole: null,
    refreshWorkspace: () => new Promise((resolve) => { finishRefresh = resolve }),
    useEffect: (callback) => { cleanup = callback() },
    window: {
      setTimeout: (callback) => timers.push(callback),
      clearTimeout: () => {},
      setInterval: () => assert.fail('overlapping interval refreshes can starve the latest-generation guard'),
    },
  }
  evaluateHook(effect, context)
  const polling = timers[0]()
  assert.equal(timers.length, 1)
  finishRefresh()
  await polling
  assert.equal(timers.length, 2)
  const lastPolling = timers[1]()
  cleanup()
  finishRefresh()
  await lastPolling
  assert.equal(timers.length, 2)
})
