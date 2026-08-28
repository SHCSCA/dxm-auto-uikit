import { useCallback, useEffect, useRef, useState } from 'react'

import { getJson, withDxmSessionBusyRetry } from '../../api'
import type { DxmCategoryRecord } from '../../types'

type CategoryCascadePickerProps = {
  selectedCategories: DxmCategoryRecord[]
  disabled?: boolean
  onAdd: (record: DxmCategoryRecord) => void
  onRemove: (categoryId: string) => void
}

export function CategoryCascadePicker({
  selectedCategories,
  disabled = false,
  onAdd,
  onRemove,
}: CategoryCascadePickerProps) {
  const [levels, setLevels] = useState<DxmCategoryRecord[][]>([[], [], []])
  const [selection, setSelection] = useState<(DxmCategoryRecord | null)[]>([null, null, null])
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<DxmCategoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestSequence = useRef(0)

  const loadChildren = useCallback(async (level: number, pcid: string) => {
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setLoading(true)
    try {
      const params = new URLSearchParams(pcid ? { pcid } : {})
      const records = await withDxmSessionBusyRetry(
        () => getJson<DxmCategoryRecord[]>(`/api/dxm/category/children?${params.toString()}`),
      )
      if (sequence !== requestSequence.current) return
      setLevels((current) => {
        const next = current.map((items) => [...items])
        next[level] = records.length || !next[level].length ? records : next[level]
        return next
      })
      setError(null)
    } catch (caught) {
      if (sequence !== requestSequence.current) return
      setError(humanCategoryError(caught))
    } finally {
      if (sequence === requestSequence.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadChildren(0, '')
  }, [loadChildren])

  function pickLevel(level: number, record: DxmCategoryRecord) {
    setSelection((current) => {
      const next = [...current]
      next[level] = record
      for (let index = level + 1; index < next.length; index += 1) next[index] = null
      return next
    })
    setResults([])
    setError(null)
    if (level === 2 || isLeafCategory(record)) {
      onAdd(record)
      return
    }
    void loadChildren(level + 1, record.categoryId)
  }

  async function searchCategories() {
    const keyword = search.trim()
    if (!keyword) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ keyword })
      const records = await withDxmSessionBusyRetry(
        () => getJson<DxmCategoryRecord[]>(`/api/dxm/category/search?${params.toString()}`),
      )
      setResults(records)
      setLevels((current) => mergeCategorySearchLevels(current, records))
      setError(null)
    } catch (caught) {
      setResults([])
      setError(humanCategoryError(caught))
    } finally {
      setLoading(false)
    }
  }

  function addSearchResult(record: DxmCategoryRecord) {
    if (!isLeafCategory(record) && !record.nodePathId) {
      setError('搜索结果缺少末级类目路径，请使用三级联动继续选择。')
      return
    }
    onAdd(record)
    setResults([])
    setSearch('')
    setError(null)
  }

  return (
    <div className="category-cascade-picker">
      <div className="category-cascade-picker__selects" aria-label="适用类目三级联动">
        {[0, 1, 2].map((level) => (
          <select
            key={level}
            value={selection[level]?.categoryId ?? ''}
            disabled={disabled || loading || (level > 0 && !selection[level - 1])}
            onChange={(event) => {
              const record = levels[level].find((item) => item.categoryId === event.target.value)
              if (record) pickLevel(level, record)
            }}
          >
            <option value="">{level === 0 ? '一级类目' : `${level + 1} 级类目`}</option>
            {levels[level].map((record) => (
              <option key={record.categoryId} value={record.categoryId}>{categoryLabel(record)}</option>
            ))}
          </select>
        ))}
      </div>

      <div className="category-cascade-picker__search">
        <input
          value={search}
          disabled={disabled || loading}
          onChange={(event) => setSearch(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              void searchCategories()
            }
          }}
          placeholder="按中文名称搜索类目"
        />
        <button
          className="button button--quiet"
          type="button"
          disabled={disabled || loading || !search.trim()}
          onClick={() => { void searchCategories() }}
        >
          {loading ? '读取中…' : '搜索'}
        </button>
      </div>

      <small className="category-cascade-picker__hint">
        {loading
          ? '正在读取店小秘类目树…'
          : selection[1]
            ? '请选择三级末级类目；选中后会加入下方适用范围。'
            : selection[0]
              ? '请选择二级类目，再继续选择三级类目。'
              : '从一级类目开始逐级选择；也可以搜索后直接加入末级类目。'}
      </small>

      {error && (
        <div className="category-cascade-picker__error" role="alert">
          <span>{error}</span>
          <button className="button button--quiet" type="button" disabled={loading} onClick={() => { void loadChildren(0, '') }}>
            重试
          </button>
        </div>
      )}

      {results.length > 0 && (
        <ul className="category-cascade-picker__results">
          {results.map((record) => (
            <li key={record.categoryId}>
              <button type="button" onClick={() => addSearchResult(record)}>
                <strong>{categoryLabel(record)}</strong>
                <span>{categoryPathLabel(record)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="category-cascade-picker__selected" aria-label="已选适用类目">
        {selectedCategories.map((record) => (
          <span key={record.categoryId} className="category-chip">
            <span><strong>{categoryLabel(record)}</strong><small>{categoryPathLabel(record)}</small></span>
            <button type="button" aria-label={`移除${categoryLabel(record)}`} onClick={() => onRemove(record.categoryId)}>×</button>
          </span>
        ))}
        {!selectedCategories.length && <small>尚未选择适用类目</small>}
      </div>
    </div>
  )
}

export function categoryLabel(record: DxmCategoryRecord) {
  if (record.nameZh) return displayCategoryName(record.nameZh)
  if (record.nameEn) return `中文名称待读取（${record.nameEn}）`
  return '中文类目名称待读取'
}

export function categoryPathLabel(record: DxmCategoryRecord) {
  const rawPath = record.nodePath || categoryLabel(record)
  return rawPath
    .split(/\s*(?:>|\/)\s*/)
    .map((segment) => displayCategoryName(segment))
    .filter(Boolean)
    .join(' / ')
}

function displayCategoryName(value: string) {
  const normalized = value.trim()
  const chinese = normalized.match(/[\u3400-\u9fff][\u3400-\u9fff\s·（）()\-]*/)?.[0]?.trim()
  if (chinese) return chinese.replace(/[()（）]/g, '').trim()
  return normalized
}

function isLeafCategory(record: DxmCategoryRecord) {
  return record.isleaf === 1 || record.isleaf === '1' || record.isleaf === true
}

function mergeCategorySearchLevels(current: DxmCategoryRecord[][], records: DxmCategoryRecord[]) {
  const next = current.map((level) => [...level])
  for (const result of records) {
    const allIds = (result.nodePathId || '').split('/').map((value) => value.trim()).filter(Boolean)
    const names = (result.nodePath || '').split(/\s*(?:>|\/)\s*/).map((value) => value.trim()).filter(Boolean)
    if (!allIds.length || allIds[allIds.length - 1] !== result.categoryId) allIds.push(result.categoryId)
    if (!names.length) names.push(categoryLabel(result))
    const ids = allIds.slice(-3)
    const offset = Math.max(0, 3 - ids.length)
    ids.forEach((id, index) => {
      const level = offset + index
      if (level > 2) return
      const nameIndex = Math.max(0, names.length - ids.length + index)
      if (next[level].some((item) => item.categoryId === id)) return
      next[level].push({
        categoryId: id,
        nameZh: displayCategoryName(names[nameIndex] || ''),
        nameEn: index === ids.length - 1 ? result.nameEn : undefined,
        nodePath: names.slice(Math.max(0, nameIndex - index), nameIndex + 1).join(' / '),
        nodePathId: ids.slice(0, index + 1).join('/'),
        pcid: index > 0 ? ids[index - 1] : undefined,
        isleaf: index === ids.length - 1 ? result.isleaf : false,
        level: level + 1,
      })
    })
  }
  return next
}

function humanCategoryError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '类目读取失败'
  if (/登录|会话|浏览器|店小秘/.test(message)) return message
  if (/fetch|network|failed/i.test(message)) return '本机类目服务不可用，请确认工作台服务已连接后重试。'
  if (/409|忙/.test(message)) return '店小秘会话正在处理上一项只读请求，请稍后重试。'
  return `类目读取失败：${message}`
}
