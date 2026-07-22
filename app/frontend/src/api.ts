const params = new URLSearchParams(window.location.search)
const runtimeBase = params.get('apiBase') || (window as any).__DXM_API_BASE__
export const API_BASE = runtimeBase || ''

export class ApiRequestError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw await responseError(response, `GET ${path} failed`)
  return response.json()
}

export async function getJsonOrDefault<T>(path: string, fallback: T): Promise<T> {
  try {
    return await getJson<T>(path)
  } catch {
    return fallback
  }
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await responseError(response, `POST ${path} failed`)
  return response.json()
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await responseError(response, `PATCH ${path} failed`)
  return response.json()
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
      // Keep the caller-facing fallback below.
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
    if (fallback.startsWith('POST ') || fallback.startsWith('PATCH ')) {
      return `${humanRequestFallback(fallback)}：本机服务处理失败，操作结果未确认。系统不会自动重试；请先刷新工作台状态，必要时到真实页面人工核对。`
    }
    return `${humanRequestFallback(fallback)}：本机服务处理失败。请刷新工作台或查看实时日志。`
  }
  if (message) return message
  return `${humanRequestFallback(fallback)}（${status}）`
}

function humanRequestFallback(fallback: string) {
  if (fallback.startsWith('GET ')) return '数据读取失败'
  if (fallback.startsWith('PATCH ')) return '修改保存失败'
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
