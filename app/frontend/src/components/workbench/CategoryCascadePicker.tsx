import { useState } from 'react'
import { categoryLabel, categoryPathLabel, isExecutableCategory } from '../../categorySelection'
import type { DxmCategoryRecord } from '../../types'
import { useCategorySelection } from './useCategorySelection'

export { categoryLabel, categoryPathLabel } from '../../categorySelection'

type CategoryCascadePickerProps = {
  selectedCategories: DxmCategoryRecord[]
  disabled?: boolean
  ready?: boolean
  scopeKey?: string
  onAdd: (record: DxmCategoryRecord) => void
  onRemove: (categoryId: string) => void
  onPending?: () => void
}

const noPending = () => undefined

export function CategoryCascadePicker({
  selectedCategories,
  disabled = false,
  ready = true,
  scopeKey = '',
  onAdd,
  onRemove,
  onPending = noPending,
}: CategoryCascadePickerProps) {
  const [keyword, setKeyword] = useState('')
  const state = useCategorySelection(onAdd, onPending, ready, scopeKey)

  return (
    <div className="category-cascade-picker">
      <div className="category-cascade-picker__selects" aria-label="适用类目逐级选择">
        {state.levels.map((records, level) => (
          <select
            key={level}
            aria-label={`第 ${level + 1} 级类目`}
            value={state.selection[level]?.categoryId ?? ''}
            disabled={disabled || state.loading || records.length === 0}
            onChange={(event) => {
              const record = records.find((candidate) => candidate.categoryId === event.target.value)
              if (record) void state.select(record, level)
            }}
          >
            <option value="">{level === 0 ? '一级类目' : `${level + 1} 级类目`}</option>
            {records.map((record) => (
              <option key={record.categoryId} value={record.categoryId}>{categoryLabel(record)}</option>
            ))}
          </select>
        ))}
      </div>
      <div className="category-cascade-picker__search">
        <input
          value={keyword}
          disabled={disabled || state.loading}
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              void state.search(keyword)
            }
          }}
          placeholder="按中文名称搜索类目"
        />
        <button className="button button--quiet" type="button" disabled={disabled || state.loading || !keyword.trim()} onClick={() => { void state.search(keyword) }}>
          {state.loading ? '读取中…' : '搜索'}
        </button>
      </div>
      <small className="category-cascade-picker__hint">
        {state.loading ? '正在核实当前目录的节点与祖先链…' : '按真实目录逐级展开；只有目录确认的可执行末级节点才能加入方案。'}
      </small>
      <button className="button button--quiet" type="button" disabled={disabled || state.loading} onClick={() => { onPending(); void state.reset() }}>重新展开目录</button>
      {state.error && (
        <div className="category-cascade-picker__error" role="alert">
          <span>{state.error}</span>
          <button className="button button--quiet" type="button" disabled={disabled || state.loading} onClick={() => { onPending(); void state.reset() }}>重试</button>
        </div>
      )}
      {state.results.length > 0 && (
        <ul className="category-cascade-picker__results">
          {state.results.map((record) => (
            <li key={record.categoryId}>
              <button type="button" disabled={disabled || state.loading || !isExecutableCategory(record)} onClick={() => { void state.select(record) }}>
                <strong>{categoryLabel(record)}</strong>
                <span>{categoryPathLabel(record)}{!isExecutableCategory(record) ? ' · 非可执行末级类目' : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="category-cascade-picker__selected" aria-label="已选适用类目">
        {selectedCategories.map((record) => (
          <span key={record.categoryId} className="category-chip">
            <span><strong>{categoryLabel(record)}</strong><small>{categoryPathLabel(record)}</small></span>
            <button type="button" disabled={disabled || state.loading} aria-label={`移除${categoryLabel(record)}`} onClick={() => onRemove(record.categoryId)}>×</button>
          </span>
        ))}
        {!selectedCategories.length && <small>尚未选择适用类目</small>}
      </div>
    </div>
  )
}
