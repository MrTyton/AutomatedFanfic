const BASE = ''  // Vite proxy in dev, same origin in prod

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ── History ────────────────────────────────────────────────────
export interface DownloadRow {
  url: string
  site: string
  title: string | null
  status: string
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export function getDownloads(page = 1, size = 25) {
  return apiFetch<{ items: DownloadRow[]; total: number }>(
    `/api/history/downloads?page=${page}&page_size=${size}`,
  )
}

export function getEmails(page = 1, size = 25) {
  return apiFetch<{ items: unknown[]; total: number }>(
    `/api/history/emails?page=${page}&page_size=${size}`,
  )
}

export function getNotifications(page = 1, size = 25) {
  return apiFetch<{ items: unknown[]; total: number }>(
    `/api/history/notifications?page=${page}&page_size=${size}`,
  )
}

// ── Controls ───────────────────────────────────────────────────
export interface AddUrlResponse {
  accepted: boolean
  message: string
}

export function addUrl(url: string) {
  return apiFetch<AddUrlResponse>('/api/controls/add-url', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
}

// ── Config ─────────────────────────────────────────────────────
export interface ConfigResponse {
  config: Record<string, unknown>
  reload_map?: Record<string, unknown>
}

export function getConfig() {
  return apiFetch<ConfigResponse>('/api/config')
}

export interface ConfigUpdateResult {
  applied: boolean
  error?: string
  results?: { hot: string[]; service_restart: string[]; app_restart: string[] }
  needs_service_restart?: boolean
  needs_app_restart?: boolean
}

export function updateConfigSection(section: string, values: Record<string, unknown>) {
  return apiFetch<ConfigUpdateResult>(`/api/config/${section}`, {
    method: 'PUT',
    body: JSON.stringify({ values }),
  })
}

export function getReloadMap() {
  return apiFetch<Record<string, string>>('/api/config/reload-map')
}
