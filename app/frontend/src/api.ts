const params = new URLSearchParams(window.location.search)
const runtimeBase = params.get('apiBase') || (window as any).__DXM_API_BASE__
export const API_BASE = runtimeBase || ''

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(await responseErrorMessage(response, `GET ${path} failed`))
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
  if (!response.ok) throw new Error(await responseErrorMessage(response, `POST ${path} failed`))
  return response.json()
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await responseErrorMessage(response, `PATCH ${path} failed`))
  return response.json()
}

async function responseErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.clone().json()
    if (typeof payload?.detail === 'string') return safeApiErrorMessage(payload.detail, response.status, fallback)
    if (typeof payload?.detail?.message === 'string') return safeApiErrorMessage(payload.detail.message, response.status, fallback)
    if (typeof payload?.message === 'string') return safeApiErrorMessage(payload.message, response.status, fallback)
  } catch {
    try {
      const text = await response.text()
      if (text.trim()) return safeApiErrorMessage(text.trim(), response.status, fallback)
    } catch {
      // Keep the caller-facing fallback below.
    }
  }
  return safeApiErrorMessage('', response.status, fallback)
}

function safeApiErrorMessage(raw: string, status: number, fallback: string): string {
  const message = String(raw ?? '').trim()
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
    return `${fallback} (${status})：本机服务处理失败。请刷新工作台或查看实时日志；系统没有执行保存或发布。`
  }
  if (message) return message
  return `${fallback} (${status})`
}
