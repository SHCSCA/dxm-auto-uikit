import { createContext, useContext, type ReactNode } from 'react'
import { getJson } from './api'
import type { DxmDraftShop, DxmDraftShopsResponse } from './types'

export type DxmShopContextValue = {
  shops: DxmDraftShop[]
  snapshot: DxmDraftShopsResponse | null
  selectedShopId: string
  loading: boolean
  error: string | null
  setSelectedShopId: (shopId: string) => void
  /**
   * A single, session-bound reader refresh shared by the sidebar, draft box
   * and template pages.  `force` is reserved for an explicit operator retry;
   * normal page mounting must reuse the verified snapshot rather than create
   * a competing browser-session request.
   */
  refresh: (force?: boolean) => Promise<DxmDraftShopsResponse | null>
}

// Keep pages and the browser contract harness renderable when they are used
// outside the full desktop App.  The real App always supplies the provider;
// the fallback remains a real read instead of silently turning a standalone
// screen into a false "no shops" state.
const DxmShopContext = createContext<DxmShopContextValue>({
  shops: [],
  snapshot: null,
  selectedShopId: '',
  loading: false,
  error: null,
  setSelectedShopId: () => undefined,
  refresh: async () => getJson<DxmDraftShopsResponse>('/api/dxm/draft-reader/shops'),
})

export function DxmShopProvider({
  value,
  children,
}: {
  value: DxmShopContextValue
  children: ReactNode
}) {
  return <DxmShopContext.Provider value={value}>{children}</DxmShopContext.Provider>
}

export function useDxmShop() {
  return useContext(DxmShopContext)
}
