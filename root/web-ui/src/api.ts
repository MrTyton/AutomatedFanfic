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
    title?: string | null
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

export interface QueueActionRequest {
    url: string
    site?: string | null
    title?: string | null
    calibre_id?: string | null
}

export interface QueueActionResponse {
    ok: boolean
    message: string
}

export function retryNow(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>('/api/controls/retry-now', {
        method: 'POST',
        body: JSON.stringify(payload),
    })
}

export function cancelRetry(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>('/api/controls/cancel-retry', {
        method: 'POST',
        body: JSON.stringify(payload),
    })
}

export function redownloadScratch(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>('/api/controls/redownload-scratch', {
        method: 'POST',
        body: JSON.stringify(payload),
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

// ── INI files ──────────────────────────────────────────────────
export interface IniFileResponse {
    content: string | null
    path: string | null
    error?: string | null
}

export interface IniUpdateResult {
    applied: boolean
    error?: string
}

export function getIniFile(iniType: 'personal' | 'defaults') {
    return apiFetch<IniFileResponse>(`/api/config/ini/${iniType}`)
}

export function updateIniFile(iniType: 'personal' | 'defaults', content: string) {
    return apiFetch<IniUpdateResult>(`/api/config/ini/${iniType}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
    })
}

// ── Logs ───────────────────────────────────────────────────────
export interface LogEntry {
    timestamp: string
    level: string
    message: string
    thread_color?: string
}

export function getLogs(limit = 500) {
    return apiFetch<{ items: LogEntry[]; count: number }>(
        `/api/logs?limit=${limit}`,
    )
}

// ── Stats ──────────────────────────────────────────────────────
export interface SiteStats {
    site: string
    total: number
    success: number
    failed: number
}

export interface TimePoint {
    date: string
    total: number
    success: number
    failed: number
}

export interface HourPoint {
    hour: number
    count: number
}

export interface WeekdayPoint {
    day_of_week: number
    count: number
}

export interface MonthDayPoint {
    day_of_month: number
    count: number
}

export interface RetryPoint {
    attempt_number: number
    count: number
}

export interface StatusPoint {
    status: string
    count: number
}

export interface StatsResponse {
    period: string
    total_downloads: number
    total_success: number
    total_failed: number
    period_downloads: number
    period_success: number
    period_failed: number
    downloads_with_retries: number
    total_retries: number
    avg_retries_to_success: number
    downloads_by_site: SiteStats[]
    downloads_over_time: TimePoint[]
    hourly_distribution: HourPoint[]
    weekly_distribution: WeekdayPoint[]
    monthly_distribution: MonthDayPoint[]
    retry_distribution: RetryPoint[]
    status_breakdown: StatusPoint[]
    error?: string
}

export function getStats(period: '24h' | '7d' | '30d' = '24h') {
    return apiFetch<StatsResponse>(`/api/stats?period=${period}`)
}
