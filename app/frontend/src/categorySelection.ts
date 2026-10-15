import type { DxmCategoryRecord } from './types'

export function isLeafCategory(record: DxmCategoryRecord) {
  return record.isleaf === 1 || record.isleaf === '1' || record.isleaf === true
}

export function isExecutableCategory(record: DxmCategoryRecord) {
  return isLeafCategory(record) && record.executableLeaf === true
}

export function categoryLabel(record: DxmCategoryRecord) {
  return record.nameZh ? displayCategoryName(record.nameZh)
    : record.nameEn ? `中文名称待读取（${record.nameEn}）` : `类目 ${record.categoryId}`
}

export function categoryPathLabel(record: DxmCategoryRecord) {
  return (record.nodePath || categoryLabel(record)).split(/\s*(?:>|\/)\s*/)
    .map(displayCategoryName).filter(Boolean).join(' / ')
}

function displayCategoryName(value: string) {
  const normalized = value.trim()
  const bilingual = normalized.match(/^[^\u3400-\u9fff]+[（(]([\s\S]*[\u3400-\u9fff][\s\S]*)[）)]$/)
  return bilingual?.[1]?.trim() || normalized
}

function pathIds(value: string | undefined) {
  const ids = (value || '').split('/').filter(Boolean)
  return ids[0] === '0' ? ids.slice(1) : ids
}

export async function resolveCategorySelection(
  categoryId: string,
  readById: (id: string) => Promise<DxmCategoryRecord | null>,
): Promise<DxmCategoryRecord[]> {
  const visited = new Set<string>()
  const chain: DxmCategoryRecord[] = []
  let nextId = categoryId
  while (nextId && nextId !== '0') {
    if (!/^[1-9][0-9]*$/.test(nextId) || visited.has(nextId)) throw new Error('类目祖先链无效或存在循环。')
    visited.add(nextId)
    const record = await readById(nextId)
    if (!record || record.categoryId !== nextId) throw new Error('类目身份无法由当前目录核实。')
    chain.unshift(record)
    const declaredPath = pathIds(record.nodePathId)
    if (declaredPath.length && declaredPath[declaredPath.length - 1] !== record.categoryId) {
      throw new Error('类目路径与节点身份不一致。')
    }
    const declaredParent = declaredPath.length > 1 ? declaredPath[declaredPath.length - 2] : ''
    if (record.pcid && record.pcid !== '0' && declaredParent && record.pcid !== declaredParent) {
      throw new Error('类目路径与父节点冲突。')
    }
    if (record.pcid === undefined && !declaredPath.length) throw new Error('类目缺少可核实的祖先链。')
    nextId = record.pcid || declaredParent
  }
  const leaf = chain[chain.length - 1]
  if (!leaf || !isExecutableCategory(leaf)) throw new Error('请选择目录已确认的可执行末级类目。')
  chain.forEach((record, index) => {
    if (leaf.catalogSha256 && record.catalogSha256 !== leaf.catalogSha256) throw new Error('类目目录版本在读取期间发生变化。')
    const path = pathIds(record.nodePathId)
    if (path.length && path.join('/') !== chain.slice(0, index + 1).map((node) => node.categoryId).join('/')) {
      throw new Error('类目祖先链与目录路径不一致。')
    }
    if (index < chain.length - 1 && isLeafCategory(record)) throw new Error('类目祖先错误地标记为末级节点。')
  })
  return chain
}
