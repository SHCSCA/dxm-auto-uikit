import { getJson, withDxmSessionBusyRetry } from './api.ts'
import type { DxmDraftShopsResponse } from './types.ts'

type ShopReaderEffects = {
  commit: (snapshot: DxmDraftShopsResponse | null) => void
  loading: (value: boolean) => void
  error: (message: string | null) => void
}

export function createDxmShopReader(effects: ShopReaderEffects) {
  let generation = 0
  let snapshot: DxmDraftShopsResponse | null = null
  let pending: Promise<DxmDraftShopsResponse | null> | null = null

  function invalidate() {
    generation += 1
    snapshot = null
    pending = null
    effects.commit(null)
    effects.loading(false)
    effects.error(null)
  }

  function refresh(force = false): Promise<DxmDraftShopsResponse | null> {
    if (!force && snapshot) return Promise.resolve(snapshot)
    if (pending) return pending
    const owner = generation
    const refreshPromise = (async () => {
      effects.loading(true)
      effects.error(null)
      try {
        const response = await withDxmSessionBusyRetry(() => (
          // 旧会话在只读退避期间失效后，也不能再次读取新会话。
          owner === generation ? getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops') : Promise.resolve(null)
        ))
        // 状态和返回值同时隔离，调用方不能借旧结果进入店铺页面。
        if (owner !== generation || !response) return null
        snapshot = response
        effects.commit(response)
        return response
      } catch (error) {
        // API 总线已记录异常；旧错误不得覆盖新会话的状态。
        if (owner === generation) effects.error(error instanceof Error ? error.message : '店铺列表读取失败，请稍后重试。')
        return null
      } finally {
        if (owner === generation) {
          pending = null
          effects.loading(false)
        }
      }
    })()
    pending = refreshPromise
    return refreshPromise
  }

  return { invalidate, refresh }
}
