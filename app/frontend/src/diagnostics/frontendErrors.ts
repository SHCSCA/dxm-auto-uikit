import { frontendConfig } from '../config/frontendConfig.ts'

export type FrontendErrorContext = {
  component: string
  action: string
  status?: number
}

export type FrontendErrorEntry = FrontendErrorContext & {
  schema: 'dxm.frontend_error.v1'
  recorded_at: string
  level: 'error'
  error_name: string
}

const entries: FrontendErrorEntry[] = []

export function recordFrontendError(error: unknown, context: FrontendErrorContext) {
  if (error instanceof Error && error.name === 'AbortError') return
  const entry: FrontendErrorEntry = {
    schema: 'dxm.frontend_error.v1',
    recorded_at: new Date().toISOString(),
    level: 'error',
    ...context,
    error_name: error instanceof Error && /^[A-Za-z][A-Za-z0-9.]{0,63}$/.test(error.name) ? error.name : 'UnknownError',
  }
  // 不记录错误原文、请求体、查询参数或堆栈，避免业务字段与凭据进入日志。
  entries.push(entry)
  if (entries.length > frontendConfig.diagnostics.maximumEntries) entries.shift()
  console.error(JSON.stringify(entry))
}

export function frontendErrorEntries(): readonly FrontendErrorEntry[] {
  return entries.map((entry) => ({ ...entry }))
}

export function installFrontendErrorHandlers() {
  const handleError = (event: ErrorEvent) => {
    recordFrontendError(event.error, { component: 'window', action: 'unhandled_error' })
  }
  const handleRejection = (event: PromiseRejectionEvent) => {
    recordFrontendError(event.reason, { component: 'window', action: 'unhandled_rejection' })
  }
  window.addEventListener('error', handleError)
  window.addEventListener('unhandledrejection', handleRejection)
  return () => {
    window.removeEventListener('error', handleError)
    window.removeEventListener('unhandledrejection', handleRejection)
  }
}
