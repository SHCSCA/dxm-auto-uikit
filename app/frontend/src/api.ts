const runtimeBase = (window as any).__DXM_API_BASE__
export const API_BASE = runtimeBase || ''

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(`GET ${path} failed`)
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
  if (!response.ok) throw new Error(`POST ${path} failed`)
  return response.json()
}
