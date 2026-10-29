// ── AutomatedFanfic Web API Client (Real FastAPI Endpoints) ──

import {
    buildLogAttemptBlocks,
    getAttemptBlockForStory,
    type LogAttemptBlock,
} from './utils/dashboardLogic'

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

export interface ExtractedEmailUrl {
    url: string
    site: string
    title: string
    status: 'new' | 'duplicate' | 'disabled_site'
}

export interface EmailRow {
    id: number
    checked_at: string
    urls_found: number
    urls_new: number
    urls_duplicate: number
    urls_disabled_site: number
    trigger: string
    extracted_urls?: ExtractedEmailUrl[]
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

export interface AddUrlResult {
    url?: string
    accepted: boolean
    message: string
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

export type ReloadBehavior = 'hot' | 'service_restart' | 'app_restart'

export interface ConfigResponse {
    config: Record<string, unknown>
    reload_map?: Record<string, Record<string, ReloadBehavior>>
}

export interface ConfigUpdateResult {
    applied: boolean
    error?: string
    results?: { hot: string[]; service_restart: string[]; app_restart: string[] }
    needs_service_restart?: boolean
    needs_app_restart?: boolean
}

export interface ConfigTestResult {
    ok: boolean
    message: string
    latency_ms: number
}

export interface IniFileResponse {
    content: string | null
    path: string | null
    error?: string | null
}

export interface IniUpdateResult {
    applied: boolean
    error?: string
}

export interface LogEntry {
    timestamp: string
    level: string
    message: string
    thread_color?: string
    thread_site?: string
    story_url?: string
    story_title?: string
    worker_id?: string
    attempt_id?: string
}

export interface SiteStats {
    site: string
    total: number
    success: number
    failed: number
    avg_duration_sec?: number
    top_error?: string | null
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

export interface ActiveDownload {
    url: string
    site?: string
    title?: string
    started_at?: string
}

export interface WaitingDownload {
    url: string
    updated_at?: string
    site?: string
    title?: string
    calibre_id?: string
    error_message?: string
    attempt_number?: number
    action?: string
    scheduled_at?: string
    delay_minutes?: number
}

export interface DaemonDetail {
    name: string
    status: 'running' | 'paused' | 'stopped'
    pid: number
    uptime_sec: number
    restarts: number
    role: string
}

export interface SiteWorkerEntry {
    site: string
    status: 'downloading' | 'queued' | 'backoff' | 'disabled' | 'idle'
    queued_count: number
    active_url?: string
    active_title?: string
    backoff_until?: string
    attempt_number?: number
    total_downloads?: number
    failed_downloads?: number
}

export interface DashboardSnapshot {
    timestamp: number
    active_downloads: { items: ActiveDownload[]; count: number }
    queued_downloads?: { items: ActiveDownload[]; count: number }
    queues: {
        ingress: number
        waiting: number
        sites: Record<string, number>
    }
    processes: Record<string, string>
    daemon_details?: Record<string, DaemonDetail>
    coordinator_paused?: boolean
    recent_downloads: unknown[]
    recent_activity: unknown[]
    waiting_downloads?: {
        items: WaitingDownload[]
        count: number
    }
    last_email_check?: EmailRow | null
    calibre_server_url?: string | null
    disabled_sites?: string[]
    dismissed_error_urls?: string[]
    max_normal_retries?: number
    latest_log_by_url?: Record<string, { timestamp: string; level: string; message: string }>
    site_worker_stats?: {
        active_threads: number
        max_threads: number
        notable_sites: SiteWorkerEntry[]
        catalog_sites: SiteWorkerEntry[]
    }
}

// ── Pure API Fetch Helper ───────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(path, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
    const contentType = res.headers.get('content-type') || ''
    if (!res.ok) {
        let errorMsg = `HTTP ${res.status}: ${res.statusText}`
        try {
            if (contentType.includes('application/json')) {
                const errBody = await res.json()
                if (errBody && typeof errBody === 'object' && 'detail' in errBody) {
                    errorMsg = String(errBody.detail)
                } else if (errBody && typeof errBody === 'object' && 'message' in errBody) {
                    errorMsg = String(errBody.message)
                }
            } else {
                const text = await res.text()
                if (text) errorMsg = text.slice(0, 200)
            }
        } catch {
            // Ignore body parse errors
        }
        throw new Error(errorMsg)
    }
    if (contentType.includes('application/json')) {
        return (await res.json()) as T
    }
    return {} as T
}

// ── Exported API Methods ───────────────────────────────────────

export function getDownloads(
    page = 1,
    size = 25,
    search = '',
    statusFilter = '',
    siteFilter = ''
) {
    const params = new URLSearchParams({ page: String(page), page_size: String(size) })
    if (search) params.set('search', search)
    if (statusFilter) params.set('status', statusFilter)
    if (siteFilter) params.set('site', siteFilter)
    return apiFetch<{ items: DownloadRow[]; total: number }>(`/api/history/downloads?${params}`)
}

export function getEmails(page = 1, size = 25) {
    const offset = (page - 1) * size
    return apiFetch<{ items: EmailRow[]; total: number }>(`/api/history/emails?limit=${size}&offset=${offset}`)
}

export function getHistorySites() {
    return apiFetch<{ sites: string[] }>('/api/history/sites')
}

export function getNotifications(
    page = 1,
    size = 25,
    search = '',
    siteFilter = ''
) {
    const offset = (page - 1) * size
    const params = new URLSearchParams({ limit: String(size), offset: String(offset) })
    if (search) params.set('search', search)
    if (siteFilter) params.set('site', siteFilter)
    return apiFetch<{ items: NotificationRow[]; total: number }>(`/api/history/notifications?${params}`)
}

export function getRetries(page = 1, size = 25, search = '', siteFilter = '') {
    const params = new URLSearchParams({ page: String(page), page_size: String(size) })
    if (search) params.set('search', search)
    if (siteFilter) params.set('site', siteFilter)
    return apiFetch<{ items: RetryRow[]; total: number }>(`/api/history/retries?${params}`)
}

export function addUrls(urls: string[], updateMethodOverride?: string) {
    return apiFetch<{ results: AddUrlResult[] }>(
        '/api/controls/add-urls',
        { method: 'POST', body: JSON.stringify({ urls, update_method: updateMethodOverride }) }
    )
}

export function restartDaemon(name: string) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/restart-daemon',
        { method: 'POST', body: JSON.stringify({ name }) }
    )
}

export function toggleCoordinatorPause() {
    return apiFetch<QueueActionResponse>(
        '/api/controls/toggle-coordinator',
        { method: 'POST' }
    )
}

export function toggleSiteDisabled(site: string) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/toggle-site',
        { method: 'POST', body: JSON.stringify({ site }) }
    )
}

export function retryNow(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/retry-now',
        { method: 'POST', body: JSON.stringify(payload) }
    )
}

export function retryAllWaiting() {
    return apiFetch<QueueActionResponse>(
        '/api/controls/retry-all',
        { method: 'POST' }
    )
}

export function cancelRetry(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/cancel-retry',
        { method: 'POST', body: JSON.stringify(payload) }
    )
}

export function cancelDownload(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/cancel',
        { method: 'POST', body: JSON.stringify(payload) }
    )
}

export function cancelAllInFlight() {
    return apiFetch<QueueActionResponse>(
        '/api/controls/cancel-all',
        { method: 'POST' }
    )
}

export function redownloadScratch(payload: QueueActionRequest) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/redownload-scratch',
        { method: 'POST', body: JSON.stringify(payload) }
    )
}

export function checkEmails() {
    return apiFetch<QueueActionResponse>(
        '/api/controls/check-emails',
        { method: 'POST' }
    )
}

export function clearLogs() {
    return Promise.resolve({ ok: true })
}

export function clearErrors(url?: string) {
    return apiFetch<QueueActionResponse>(
        '/api/controls/clear-errors',
        { method: 'POST', body: JSON.stringify({ url }) }
    )
}

export function getConfig() {
    return apiFetch<ConfigResponse>('/api/config')
}

export function getSecret(section: string, key: string) {
    return apiFetch<{ value: string }>(
        `/api/config/secret?section=${encodeURIComponent(section)}&key=${encodeURIComponent(key)}`
    )
}

export function updateConfigSection(section: string, values: Record<string, unknown>) {
    return apiFetch<ConfigUpdateResult>(
        `/api/config/${section}`,
        { method: 'PUT', body: JSON.stringify({ values }) }
    )
}

export function testConfigSection(section: string, values: Record<string, unknown>) {
    return apiFetch<ConfigTestResult>(
        `/api/config/${section}/test`,
        { method: 'POST', body: JSON.stringify({ values }) }
    )
}

export function getIniFile(iniType: 'personal' | 'defaults') {
    return apiFetch<IniFileResponse>(`/api/config/ini/${iniType}`)
}

export function updateIniFile(iniType: 'personal' | 'defaults', content: string) {
    return apiFetch<IniUpdateResult>(
        `/api/config/ini/${iniType}`,
        { method: 'PUT', body: JSON.stringify({ content }) }
    )
}

export function getLogs(limit = 500) {
    return apiFetch<{ items: LogEntry[]; count: number }>(`/api/logs?limit=${limit}`)
}

export function getStartupLogs(limit = 500) {
    return apiFetch<{ items: LogEntry[]; count: number }>(`/api/logs/startup?limit=${limit}`)
}

export interface SystemVersionInfo {
    automatedfanfic: string
    python: string
    python_implementation?: string
    platform: string
    os?: string
    arch?: string
    is_docker?: boolean
    calibre: string
    fanficfare: string
    apprise: string
}

export function getSystemVersion() {
    return apiFetch<SystemVersionInfo>('/api/version')
}

export function getAttemptBlocksFromLogs(
    entries?: LogEntry[],
    downloads?: DownloadRow[],
    retries?: RetryRow[],
    activeItems?: { url: string; stage: 'downloading' | 'queued' | 'waiting_retry' }[]
): LogAttemptBlock[] {
    return buildLogAttemptBlocks(
        entries || [],
        downloads || [],
        retries || [],
        activeItems || []
    )
}

export function getStoryAttemptBlock(
    url: string,
    fallback: {
        title?: string | null
        site?: string
        attemptNumber?: number
        error?: string | null
        timestamp?: string
    } = {},
    sourceLogs?: LogEntry[],
    downloads?: DownloadRow[],
    retries?: RetryRow[],
    activeItems?: { url: string; stage: 'downloading' | 'queued' | 'waiting_retry' }[]
): LogAttemptBlock {
    const existing = getAttemptBlockForStory(
        url,
        sourceLogs || [],
        downloads || [],
        retries || [],
        activeItems || []
    )
    if (existing) {
        return {
            ...existing,
            title: fallback.title || existing.title,
            site: fallback.site || existing.site,
            attemptNumber: fallback.attemptNumber || existing.attemptNumber,
            traceback: fallback.error || existing.traceback,
        }
    }

    const ts = fallback.timestamp || new Date().toISOString().replace('T', ' ').slice(0, 19)
    const siteTag = fallback.site ? `(${fallback.site}) ` : ''
    const firstLineMsg = fallback.error
        ? `${siteTag}Failed ${url}: ${fallback.error.split('\n')[0]}`
        : `${siteTag}Processed ${url}`
    const matchedActive = activeItems?.find(a => a.url === url)

    return {
        id: `synth-${url}-${ts}`,
        kind: 'story_attempt',
        url,
        title: fallback.title || url,
        site: fallback.site,
        attemptNumber: fallback.attemptNumber || 1,
        status: fallback.error ? 'failed' : 'success',
        isActive: !!matchedActive,
        activeStage: matchedActive?.stage,
        startedAt: ts,
        endedAt: ts,
        lines: [
            {
                timestamp: ts,
                level: 'info',
                message: `${siteTag}Processing ${url}`,
                thread_site: fallback.site,
                story_url: url,
            },
            {
                timestamp: ts,
                level: fallback.error ? 'error' : 'info',
                message: firstLineMsg,
                thread_site: fallback.site,
                story_url: url,
            },
        ],
        traceback: fallback.error || null,
    }
}

export function getStats(period: '24h' | '7d' | '30d' = '7d'): Promise<StatsResponse> {
    return apiFetch<StatsResponse>(`/api/stats?period=${period}`)
}

export interface HistoricalStoryDetails {
    found: boolean
    story: {
        download: DownloadRow & { behavior?: string }
        retries: RetryRow[]
        notifications: NotificationRow[]
    } | null
}

export async function getHistoricalStoryDetails(url: string): Promise<HistoricalStoryDetails | null> {
    try {
        return await apiFetch<HistoricalStoryDetails>(`/api/history/story?url=${encodeURIComponent(url)}`)
    } catch {
        return null
    }
}
