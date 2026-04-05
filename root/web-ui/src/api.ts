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
    calibre_id: string | null
    status: string
    error_message: string | null
    started_at: string
    completed_at: string | null
}

export interface EmailRow {
    id: number
    checked_at: string
    urls_found: number
    urls_new: number
    urls_duplicate: number
    urls_disabled_site: number
}

export interface NotificationRow {
    id: number
    download_event_id: number | null
    title: string
    body: string
    site: string | null
    sent_at: string
    provider: string | null
}

export interface RetryRow {
    id: number
    download_event_id: number | null
    url: string
    site: string
    attempt_number: number
    action: string
    delay_minutes: number
    error_message: string | null
    scheduled_at: string
    fired_at: string | null
}

export function getDownloads(page = 1, size = 25, search = '') {
    const params = new URLSearchParams({ page: String(page), page_size: String(size) })
    if (search) params.set('search', search)
    return apiFetch<{ items: DownloadRow[]; total: number }>(
        `/api/history/downloads?${params}`,
    )
}

export function getEmails(page = 1, size = 25) {
    const offset = (page - 1) * size
    return apiFetch<{ items: EmailRow[] }>(
        `/api/history/emails?limit=${size}&offset=${offset}`,
    )
}

export function getNotifications(page = 1, size = 25) {
    const offset = (page - 1) * size
    return apiFetch<{ items: NotificationRow[] }>(
        `/api/history/notifications?limit=${size}&offset=${offset}`,
    )
}

export function getRetries(page = 1, size = 25) {
    return apiFetch<{ items: RetryRow[]; total: number }>(
        `/api/history/retries?page=${page}&page_size=${size}`,
    )
}

// ── Controls ───────────────────────────────────────────────────
export interface AddUrlResult {
    accepted: boolean
    message: string
}

export function addUrls(urls: string[]) {
    return apiFetch<{ results: AddUrlResult[] }>('/api/controls/add-urls', {
        method: 'POST',
        body: JSON.stringify({ urls }),
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
