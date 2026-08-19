import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveSchemaChoiceOptions } from '../src/schemaValueEditor.ts'

test('empty schema choice collections use the ordinary type editor', () => {
  assert.equal(resolveSchemaChoiceOptions({ type: 'string', values: [] }), null)
  assert.equal(resolveSchemaChoiceOptions({ type: 'string', enum: [] }), null)
  assert.equal(
    resolveSchemaChoiceOptions({ type: 'string', values: [], enum: [] }),
    null,
  )
})

test('non-empty schema choices preserve value labels and enum fallback', () => {
  assert.deepEqual(
    resolveSchemaChoiceOptions({
      type: 'string',
      values: [{ id: 'ABS', name: 'Plastic', names: { zh: '塑料' } }],
    }),
    [{ value: 'ABS', label: '塑料 · ABS' }],
  )
  assert.deepEqual(
    resolveSchemaChoiceOptions({ type: 'string', enum: ['red', 2] }),
    [
      { value: 'red', label: 'red' },
      { value: '2', label: '2' },
    ],
  )
})
