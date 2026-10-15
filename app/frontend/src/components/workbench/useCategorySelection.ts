import { useCallback, useEffect, useRef, useState } from 'react'
import { getJson, withDxmSessionBusyRetry } from '../../api'
import { resolveCategorySelection, isLeafCategory } from '../../categorySelection'
import { recordFrontendError } from '../../diagnostics/frontendErrors'
import type { DxmCategoryRecord } from '../../types'

export function useCategorySelection(
  onAdd: (record: DxmCategoryRecord) => void,
  onPending: () => void,
  enabled = true,
  scopeKey = '',
) {
  const [levels, setLevels] = useState<DxmCategoryRecord[][]>([[]])
  const [selection, setSelection] = useState<DxmCategoryRecord[]>([])
  const [results, setResults] = useState<DxmCategoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sequence = useRef(0)

  const readById = (id: string) => withDxmSessionBusyRetry(
    () => getJson<DxmCategoryRecord | null>(`/api/dxm/category/get?category_id=${encodeURIComponent(id)}`),
  )

  const loadChildren = useCallback(async (level: number, parentId: string, request: number) => {
    const params = new URLSearchParams(parentId ? { pcid: parentId } : {})
    const records = await withDxmSessionBusyRetry(
      () => getJson<DxmCategoryRecord[]>(`/api/dxm/category/children?${params.toString()}`),
    )
    if (sequence.current !== request) return
    setLevels((current) => [...current.slice(0, level), records])
    if (!records.length) setError('当前层没有可核实的子类目；空列表不会被当作末级证明。')
  }, [])

  const reset = useCallback(async () => {
    const request = ++sequence.current
    setSelection([])
    setLevels([[]])
    setResults([])
    setError(null)
    if (!enabled) { setLoading(false); return }
    setLoading(true)
    try {
      await loadChildren(0, '', request)
    } catch (caught) {
      recordFrontendError(caught, { component: 'category_picker', action: 'load_roots' })
      if (sequence.current === request) setError(categoryError(caught))
    } finally {
      if (sequence.current === request) setLoading(false)
    }
  }, [enabled, loadChildren])

  useEffect(() => {
    void reset()
    return () => { sequence.current += 1 }
  }, [reset, scopeKey])

  async function select(record: DxmCategoryRecord, level?: number) {
    const request = ++sequence.current
    onPending()
    setLoading(true)
    setError(null)
    setResults([])
    try {
      if (level !== undefined && !isLeafCategory(record)) {
        setSelection((current) => [...current.slice(0, level), record])
        setLevels((current) => current.slice(0, level + 1))
        await loadChildren(level + 1, record.categoryId, request)
        return
      }
      const chain = await resolveCategorySelection(record.categoryId, readById)
      if (sequence.current !== request) return
      const leaf = chain[chain.length - 1]
      setSelection(chain)
      setLevels((current) => chain.map((node, index) => {
        const candidates = level === undefined ? [] : current[index] ?? []
        return candidates.some((candidate) => candidate.categoryId === node.categoryId) ? candidates : [...candidates, node]
      }))
      onAdd({ ...leaf, nodePath: chain.map((node) => node.nameZh || node.nameEn || node.categoryId).join(' / '), nodePathId: chain.map((node) => node.categoryId).join('/') })
    } catch (caught) {
      recordFrontendError(caught, { component: 'category_picker', action: 'select_leaf' })
      if (sequence.current === request) setError(categoryError(caught))
    } finally {
      if (sequence.current === request) setLoading(false)
    }
  }

  async function search(keyword: string) {
    if (!keyword.trim()) return
    const request = ++sequence.current
    setLoading(true)
    setError(null)
    try {
      const records = await withDxmSessionBusyRetry(
        () => getJson<DxmCategoryRecord[]>(`/api/dxm/category/search?keyword=${encodeURIComponent(keyword.trim())}`),
      )
      if (sequence.current === request) setResults(records)
    } catch (caught) {
      recordFrontendError(caught, { component: 'category_picker', action: 'search' })
      if (sequence.current === request) setError(categoryError(caught))
    } finally {
      if (sequence.current === request) setLoading(false)
    }
  }

  return { levels, selection, results, loading, error, reset, select, search }
}

function categoryError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : '类目读取失败。'
  return /fetch|network|failed/i.test(message) ? '本机类目服务不可用，请确认服务已连接后重试。' : message
}
