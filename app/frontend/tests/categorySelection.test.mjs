import assert from 'node:assert/strict'
import test from 'node:test'
import { isExecutableCategory, resolveCategorySelection } from '../src/categorySelection.ts'

function catalog(depth = 6) {
  const ids = Array.from({ length: depth }, (_, index) => String(index + 10))
  return new Map(ids.map((categoryId, index) => [categoryId, {
    categoryId,
    nameZh: `类目${index + 1}`,
    pcid: index ? ids[index - 1] : '0',
    nodePathId: ids.slice(0, index + 1).join('/'),
    isleaf: index === depth - 1,
    executableLeaf: index === depth - 1,
  }]))
}

test('six-level selection preserves every real ancestor and uses the catalog leaf', async () => {
  const records = catalog()
  const reads = []
  const chain = await resolveCategorySelection('15', async (id) => {
    reads.push(id)
    return records.get(id) ?? null
  })
  assert.deepEqual(chain.map((record) => record.categoryId), ['10', '11', '12', '13', '14', '15'])
  assert.deepEqual(reads, ['15', '14', '13', '12', '11', '10'])
})

test('third-level branches and catalog-conflict leaves cannot become a target', async () => {
  const records = catalog()
  await assert.rejects(resolveCategorySelection('12', async (id) => records.get(id)), /末级/)
  records.get('15').executableLeaf = false
  assert.equal(isExecutableCategory(records.get('15')), false)
  await assert.rejects(resolveCategorySelection('15', async (id) => records.get(id)), /末级/)
})

test('a leading virtual root is normalized without dropping real ancestor levels', async () => {
  const records = catalog()
  for (const record of records.values()) record.nodePathId = `0/${record.nodePathId}`
  const chain = await resolveCategorySelection('15', async (id) => records.get(id))
  assert.deepEqual(chain.map((record) => record.categoryId), ['10', '11', '12', '13', '14', '15'])
})

test('a search hit cannot supply leaf authority or replace missing directory identity', async () => {
  await assert.rejects(resolveCategorySelection('15', async () => null), /身份/)
  await assert.rejects(resolveCategorySelection('15', async () => ({ categoryId: '999', isleaf: true })), /身份/)
  assert.equal(isExecutableCategory({ categoryId: '15', isleaf: true }), false)
})

test('parent drift, cyclic ancestry and incomplete paths fail closed', async () => {
  for (const change of [
    (records) => { records.get('15').pcid = '10' },
    (records) => { records.get('10').pcid = '15' },
    (records) => { records.get('15').nodePathId = '15' },
    (records) => { records.delete('12') },
  ]) {
    const records = catalog()
    change(records)
    await assert.rejects(resolveCategorySelection('15', async (id) => records.get(id) ?? null))
  }
})
