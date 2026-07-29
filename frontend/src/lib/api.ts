const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

export function useMockApi(): boolean {
  return !API_BASE
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) {
    throw new Error('VITE_API_BASE is empty; use mock data instead of apiFetch')
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${text || res.statusText}`)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return (await res.json()) as T
}

export function getApiBase(): string {
  return API_BASE
}

export function isRemoteMode(): boolean {
  return Boolean(API_BASE)
}
