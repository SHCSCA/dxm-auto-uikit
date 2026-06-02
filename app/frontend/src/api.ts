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
    if (typeof payload?.detail === 'string') return payload.detail
    if (typeof payload?.message === 'string') return payload.message
  } catch {
    try {
      const text = await response.text()
      if (text.trim()) return text.trim()
    } catch {
      // Keep the caller-facing fallback below.
    }
  }
  return `${fallback} (${response.status})`
}
