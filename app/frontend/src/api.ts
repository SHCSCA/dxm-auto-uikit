import { frontendConfig } from './config/frontendConfig.ts'
import { recordFrontendError } from './diagnostics/frontendErrors.ts'

export const API_BASE = frontendConfig.apiBase

export class ApiRequestError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export class ApiConfigurationError extends Error {
  readonly reasonCode = 'FRONTEND_API_BASE_INVALID'
  constructor() {
    super(frontendConfig.apiConfigurationError || '工作台 API 地址配置无效，请改用本机地址。')
    this.name = 'ApiConfigurationError'
  }
}

const DXM_SESSION_BUSY_ATTEMPTS = frontendConfig.sessionBusy.attempts
const DXM_SESSION_BUSY_RETRY_DELAYS_MS = frontendConfig.sessionBusy.delaysMs

export function isDxmSessionBusyError(error: unknown) {
  const text = error instanceof Error ? error.message : String(error ?? '')
  return text.includes('DXM_SESSION_BUSY')
    || text.includes('上一条会话操作')
    || text.includes('会话忙')
    || text.includes('正在处理')
}

// 只重试只读会话忙响应；真实动作不得使用此重试器。
export async function withDxmSessionBusyRetry<T>(
  operation: () => Promise<T>,
  maxAttempts = DXM_SESSION_BUSY_ATTEMPTS,
): Promise<T> {
  let lastError: unknown
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (!isDxmSessionBusyError(error) || attempt === maxAttempts - 1) throw error
      await new Promise<void>((resolve) => setTimeout(resolve, DXM_SESSION_BUSY_RETRY_DELAYS_MS[attempt] ?? 1000))
    }
  }
  throw lastError instanceof Error ? lastError : new Error('店小秘只读请求失败，请稍后重试。')
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { signal })
}

export async function getJsonOrDefault<T>(path: string, fallback: T): Promise<T> {
  try {
    return await getJson<T>(path)
  } catch {
    return fallback
  }
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function deleteJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, {
    method: 'DELETE',
  })
}

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const method = init.method ?? 'GET'
  let status: number | undefined
  try {
    if (frontendConfig.apiConfigurationError) throw new ApiConfigurationError()
    const response = await fetch(`${API_BASE}${path}`, init)
    status = response.status
    if (!response.ok) throw await responseError(response, `${method} ${path} failed`)
    return await response.json()
  } catch (error) {
    const route = path.split('?')[0].replace(/\/\d+(?=\/|$)/g, '/:id')
    recordFrontendError(error, { component: 'api', action: `${method} ${route}`, status })
    throw error
  }
}

async function responseError(response: Response, fallback: string): Promise<ApiRequestError> {
  try {
    const payload = await response.clone().json()
    if (typeof payload?.detail === 'string') return new ApiRequestError(safeApiErrorMessage(payload.detail, response.status, fallback))
    if (typeof payload?.detail?.message === 'string') return new ApiRequestError(safeApiErrorMessage(payload.detail.message, response.status, fallback))
    if (typeof payload?.message === 'string') return new ApiRequestError(safeApiErrorMessage(payload.message, response.status, fallback))
  } catch {
    try {
      const text = await response.text()
      if (text.trim()) return new ApiRequestError(safeApiErrorMessage(text.trim(), response.status, fallback))
    } catch {
      // 非 JSON 响应继续使用下方安全文案。
    }
  }
  return new ApiRequestError(safeApiErrorMessage('', response.status, fallback))
}

function safeApiErrorMessage(raw: string, status: number, fallback: string): string {
  const message = operatorSafeApiMessage(String(raw ?? '').trim())
  const normalized = message.toLowerCase()
  const looksTechnical = (
    message.includes('Cannot switch to a different thread')
    || message.includes('Internal Server Error')
    || message.includes('Traceback')
    || normalized.includes('greenlet')
    || normalized.includes('playwright sync api')
    || normalized.includes('<html')
    || normalized.includes('<!doctype')
    || normalized.includes('stack trace')
  )
  if (looksTechnical || status >= 500) {
    const readOnlyPost = fallback.includes('/api/dxm-template-refs/sync')
    if (!readOnlyPost && (fallback.startsWith('POST ') || fallback.startsWith('PATCH ') || fallback.startsWith('DELETE '))) {
      return `${humanRequestFallback(fallback)}：本机服务处理失败，操作结果未确认。系统不会自动重试；请先刷新工作台状态，必要时到真实页面人工核对。`
    }
    return `${humanRequestFallback(fallback)}：本机服务处理失败。请刷新工作台或查看实时日志。`
  }
  if (message) return message
  return `${humanRequestFallback(fallback)}（${status}）`
}

function humanRequestFallback(fallback: string) {
  if (fallback.includes('/api/dxm-template-refs/sync')) return '店小秘类目字段与模板读取失败'
  if (fallback.startsWith('GET ')) return '数据读取失败'
  if (fallback.startsWith('PATCH ')) return '修改保存失败'
  if (fallback.startsWith('DELETE ')) return '归档失败'
  if (fallback.startsWith('POST ')) return '操作提交失败'
  return '操作失败'
}

function operatorSafeApiMessage(raw: string) {
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(raw)) return ''
  return raw
    .replace(/^[A-Z][A-Z0-9_]{2,}:\s*/, '')
    .replace(/\b(?:approval_)?token\b\s*[:=]?\s*[^\s,;，；]*/gi, '')
    .replace(/\b(?:reason_code|schema_version|policy_digest|scope_snapshot_digest|template_snapshot_digest|browser_session_id|session_id|runtime_identity|fingerprint|lease_id|nonce_hash|git_head|l2_evidence_fingerprint|mutation_scope_id)\b\s*[:=]?\s*[^\s,;，；]*/gi, '')
    .replace(/\b[0-9A-F]{64}\b/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
