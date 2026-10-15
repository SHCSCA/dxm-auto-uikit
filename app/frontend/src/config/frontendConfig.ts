type RuntimeWindow = Window & { __DXM_API_BASE__?: unknown }

export function resolveApiConfiguration(search: string, injectedBase?: unknown) {
  const params = new URLSearchParams(search)
  const candidate = params.has('apiBase') ? params.get('apiBase') : injectedBase ?? ''
  const invalid = { apiBase: '', error: '工作台 API 地址配置无效：只允许当前页面同源或无凭据的本机 HTTP 地址。真实任务与配置请求已关闭。', reasonCode: 'FRONTEND_API_BASE_INVALID' }
  if (typeof candidate !== 'string') return invalid
  const raw = candidate.trim()
  if (!raw) return { apiBase: '', error: null, reasonCode: null }
  try {
    const url = new URL(raw)
    const authority = raw.split('/')[2] || ''
    if (!/^https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:\/|$)/i.test(raw)
      || !['http:', 'https:'].includes(url.protocol)
      || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || (url.port !== '' && Number(url.port) < 1)
      || authority.includes('@') || url.username || url.password || url.search || url.hash) return invalid
    return { apiBase: raw.replace(/\/+$/, ''), error: null, reasonCode: null }
  } catch {
    // 配置错误转成可见状态，避免在 React 错误边界挂载前终止初始化。
    return invalid
  }
}

const apiConfiguration = typeof window === 'undefined'
  ? resolveApiConfiguration('')
  : resolveApiConfiguration(window.location.search, (window as RuntimeWindow).__DXM_API_BASE__)

// 页面只消费此配置入口；运行时业务权限仍由后端冻结合同决定。
export const frontendConfig = Object.freeze({
  apiBase: apiConfiguration.apiBase,
  apiConfigurationError: apiConfiguration.error,
  apiConfigurationReasonCode: apiConfiguration.reasonCode,
  draftSelection: Object.freeze({ minimum: 3, maximum: 100, pageSizes: [20, 50, 100, 200] as const, defaultPageSize: 100 }),
  polling: Object.freeze({ workspaceMs: 1500, logsMs: 1500, runtimeMs: 5000, browserMs: 3500, approvalMs: 2000 }),
  sessionBusy: Object.freeze({ attempts: 4, delaysMs: [250, 500, 1000] as const }),
  diagnostics: Object.freeze({ maximumEntries: 100 }),
  storage: Object.freeze({ themeKey: 'dxm-workbench-theme' }),
  browser: Object.freeze({ homeUrl: 'https://www.dianxiaomi.com/', draftUrl: 'https://www.dianxiaomi.com/web/smt/smtProductList/draft', navigationSettleMs: 2500 }),
  development: Object.freeze({ host: '127.0.0.1', frontendPort: 5173, backendPort: 8000 }),
  product: Object.freeze({ path: 'B' as const, nativeGate: 'RUNTIME_NATIVE_GATE_REQUIRED' as const }),
})

export function developmentBackendTarget(environment: Record<string, string | undefined>) {
  return environment.DXM_BACKEND_URL || `http://${frontendConfig.development.host}:${environment.DXM_BACKEND_PORT || frontendConfig.development.backendPort}`
}
