import assert from 'node:assert/strict'
import test from 'node:test'

import {
  normalizeSchemaValueForDefinition,
  resolveSchemaChoiceOptions,
} from '../src/schemaValueEditor.ts'

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

test('DXM wire option aliases render Chinese labels and preserve real ids', () => {
  assert.deepEqual(
    resolveSchemaChoiceOptions({
      type: 'array',
      items: {
        type: 'string',
        values: [
          { valueId: 1983471271, nameZh: '普货' },
          { value_id: '1983471275', label: '纯电' },
        ],
      },
    }),
    [
      { value: '1983471271', label: '普货 · 1983471271' },
      { value: '1983471275', label: '纯电 · 1983471275' },
    ],
  )
})

test('template values normalize DXM option objects and Chinese labels to stable ids', () => {
  const definition = {
    type: 'array',
    items: {
      type: 'string',
      values: [
        { valueId: 11, nameZh: '无' },
        { valueId: 12, nameZh: '乙醛' },
      ],
    },
  }
  assert.deepEqual(
    normalizeSchemaValueForDefinition(definition, [
      { valueId: 11, nameZh: '无' },
      '乙醛',
      '12',
    ]),
    ['11', '12', '12'],
  )
})

test('template values preserve structured SKU and regional objects', () => {
  const value = [{ skuCode: 'A', skuPrice: 10 }]
  assert.deepEqual(
    normalizeSchemaValueForDefinition({ type: 'array', items: { type: 'object' } }, value),
    value,
  )
  assert.equal(
    normalizeSchemaValueForDefinition({ type: 'number' }, '1.25'),
    1.25,
  )
})
