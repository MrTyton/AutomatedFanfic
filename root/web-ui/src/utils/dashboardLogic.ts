import type {
    DownloadRow,
    RetryRow,
    WaitingDownload,
    TimePoint,
    SiteStats,
    StatusPoint,
    LogEntry,
    SystemVersionInfo,
} from '../api'
import { STATUS_COLORS } from '../statusColors.ts'

export interface ParsedUrlPreview {
    raw: string
    normalizedUrl: string
    site: string
    inferredTitle: string
    isValid: boolean
    isDisabledSite: boolean
    isDuplicateInFlight: boolean
}

export function parseAndValidateUrlLines(
    input: string,
    disabledSites: string[] = [],
    inFlightUrls: Set<string> = new Set()
): ParsedUrlPreview[] {
    const tokens = input
        .split(/[\r\n\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean)

    const disabledSet = new Set(disabledSites.map((s) => s.toLowerCase()))

    return tokens.map((raw) => {
        const withProto = raw.startsWith('http://') || raw.startsWith('https://') ? raw : `https://${raw}`
        let site = 'web'
        let isValid = false
        let normalizedUrl = raw

        try {
            const parsed = new URL(withProto)
            if (parsed.hostname && parsed.hostname.includes('.')) {
                isValid = true
                normalizedUrl = parsed.href
                const host = parsed.hostname.replace(/^www\./, '').replace(/^forums\./, '')
                site = host.split('.')[0]?.toLowerCase() || 'web'
            }
        } catch {
            isValid = false
        }

        const parts = raw.split('/').filter(Boolean)
        const lastPart = decodeURIComponent(parts[parts.length - 1] || 'Story').replace(/[-_]/g, ' ')
        const inferredTitle = /^\d+$/.test(lastPart)
            ? `Work #${lastPart}`
            : lastPart.charAt(0).toUpperCase() + lastPart.slice(1)

        return {
            raw,
            normalizedUrl,
            site,
            inferredTitle,
            isValid,
            isDisabledSite: isValid && disabledSet.has(site),
            isDuplicateInFlight: inFlightUrls.has(raw) || inFlightUrls.has(normalizedUrl),
        }
    })
}

export function filterRemainingInputAfterSubmit(
    rawUrls: string[],
    results: { accepted: boolean; message: string }[]
): string {
    const rejected: string[] = []
    for (let i = 0; i < rawUrls.length; i++) {
        if (!results[i]?.accepted) {
            rejected.push(rawUrls[i])
        }
    }
    return rejected.join('\n')
}

export interface AggregatedErrorRecord {
    title: string
    url: string
    site?: string
    calibre_id?: string
    status: string
    error: string
    occurrences: number
    attempt_number?: number
    lastTimestamp?: string
}

export function aggregateRecentErrors(
    waitingItems: WaitingDownload[],
    recentDownloads: {
        url: string
        site?: string
        title?: string | null
        calibre_id?: string | null
        status?: string
        error_message?: string | null
        completed_at?: string | null
        timestamp?: string | null
    }[],
    nowMs: number
): AggregatedErrorRecord[] {
    const cutoff24h = nowMs - 24 * 60 * 60 * 1000
    const isWithin24h = (iso?: string | null) => {
        if (!iso) return true
        const t = new Date(iso).getTime()
        return !isNaN(t) && t >= cutoff24h
    }

    const map = new Map<string, AggregatedErrorRecord>()

    for (const w of waitingItems) {
        if (!w.error_message) continue
        map.set(w.url, {
            title: w.title || w.url,
            url: w.url,
            site: w.site,
            calibre_id: w.calibre_id,
            status: 'waiting',
            error: w.error_message,
            occurrences: w.attempt_number && w.attempt_number > 0 ? w.attempt_number : 1,
            attempt_number: w.attempt_number,
            lastTimestamp: w.updated_at,
        })
    }

    for (const d of recentDownloads) {
        const ts = d.completed_at || d.timestamp
        if (!isWithin24h(ts)) continue
        if (d.status !== 'failed' && d.status !== 'abandoned' && !d.error_message) continue

        const existing = map.get(d.url)
        if (existing) {
            existing.occurrences += 1
            if (!existing.error && d.error_message) {
                existing.error = d.error_message
            }
        } else {
            map.set(d.url, {
                title: d.title || d.url,
                url: d.url,
                site: d.site,
                calibre_id: d.calibre_id || undefined,
                status: d.status || 'failed',
                error: d.error_message || 'Download failed without specific error message',
                occurrences: 1,
                lastTimestamp: ts || undefined,
            })
        }
    }

    return Array.from(map.values())
}

// ── Attempt Block Grouping Engine (De-interleaves concurrent worker logs) ──

export interface LogAttemptBlock {
    id: string
    kind: 'story_attempt' | 'system'
    url?: string
    title: string
    site?: string
    attemptNumber: number
    status: 'success' | 'failed' | 'processing' | 'system'
    isActive: boolean
    activeStage?: 'downloading' | 'queued' | 'waiting_retry' | 'processing'
    startedAt: string
    endedAt: string
    lines: LogEntry[]
    traceback?: string | null
}

const URL_EXTRACT_RE = /(https?:\/\/[^\s<>"')]+?)(?=[.,;:]?(?:\s|$))/
const SITE_PREFIX_RE = /^\(([\w.-]+)\)/
const RETRY_NUM_RE = /retry #(\d+)/i

export function parseLogTimestamp(ts?: string | null): number {
    if (!ts) return 0
    const trimmed = ts.trim()
    if (!trimmed) return 0

    // Match 12-hour or 24-hour timestamp: "YYYY-MM-DD hh:mm:ss [AM|PM]"
    const match = trimmed.match(
        /^(\d{4})-(\d{2})-(\d{2})[T\s]+(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?(?:\s*([ap]m))?$/i
    )
    if (match) {
        const year = parseInt(match[1], 10)
        const month = parseInt(match[2], 10) - 1
        const day = parseInt(match[3], 10)
        let hours = parseInt(match[4], 10)
        const minutes = parseInt(match[5], 10)
        const seconds = parseInt(match[6], 10)
        const ampm = match[7] ? match[7].toLowerCase() : null

        if (ampm === 'pm' && hours < 12) {
            hours += 12
        } else if (ampm === 'am' && hours === 12) {
            hours = 0
        }
        return new Date(year, month, day, hours, minutes, seconds).getTime()
    }

    const direct = new Date(trimmed).getTime()
    return isNaN(direct) ? 0 : direct
}

export function formatLogTimeShort(ts: string): string {
    if (!ts) return ''
    const trimmed = ts.trim()
    const m = trimmed.match(/(\d{1,2}:\d{2}:\d{2}(?:\s*[ap]m)?)/i)
    return m ? m[1].toUpperCase() : trimmed
}

export function formatBlockTimeRange(startedAt?: string | null, endedAt?: string | null): string {
    if (!startedAt && !endedAt) return ''
    if (startedAt && !endedAt) return formatLogTimeShort(startedAt)
    if (!startedAt && endedAt) return `Updated ${formatLogTimeShort(endedAt)}`

    const tStart = parseLogTimestamp(startedAt)
    const tEnd = parseLogTimestamp(endedAt)

    const shortStart = formatLogTimeShort(startedAt!)
    const shortEnd = formatLogTimeShort(endedAt!)

    if (shortStart === shortEnd) {
        return `Updated ${shortEnd}`
    }

    if (tStart > 0 && tEnd > 0) {
        const dStart = new Date(tStart)
        const dEnd = new Date(tEnd)
        if (
            dStart.getFullYear() !== dEnd.getFullYear() ||
            dStart.getMonth() !== dEnd.getMonth() ||
            dStart.getDate() !== dEnd.getDate()
        ) {
            const dateFmt = (d: Date) =>
                d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
            return `${dateFmt(dStart)} ${shortStart} → ${dateFmt(dEnd)} ${shortEnd}`
        }
    }

    return `${shortStart} → ${shortEnd}`
}

export function ensureExternalUrl(raw?: string | null): string {
    if (!raw) return '#'
    const trimmed = raw.trim()
    if (!trimmed) return '#'
    if (/^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(trimmed)) {
        return trimmed
    }
    return `https://${trimmed}`
}

export function normalizeStoryUrl(raw?: string | null): string {
    if (!raw) return ''
    const trimmed = raw.trim()
    if (!trimmed) return ''
    if (/^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(trimmed)) {
        return trimmed
    }
    return `https://${trimmed}`
}

export function buildCalibreBookUrl(
    serverUrl?: string | null,
    calibreId?: string | number | null
): string {
    if (!serverUrl || calibreId === undefined || calibreId === null) return ''
    const idStr = String(calibreId).replace(/^#/, '').trim()
    if (!idStr) return ''

    const trimmedUrl = serverUrl.trim()
    if (!trimmedUrl) return ''

    try {
        const parsed = new URL(trimmedUrl)
        let libraryId = ''
        const rawHash = parsed.hash.replace(/^#/, '').trim()

        if (rawHash) {
            if (rawHash.includes('&') || rawHash.includes('=')) {
                const searchParams = new URLSearchParams(rawHash)
                libraryId = searchParams.get('library_id') || ''
                if (!libraryId) {
                    const firstPart = rawHash.split('&')[0]
                    if (!firstPart.includes('=')) {
                        libraryId = firstPart.replace(/^\/+/, '')
                    }
                }
            } else {
                libraryId = rawHash.replace(/^\/+/, '')
            }
        }

        let pathname = parsed.pathname
        if (!pathname.endsWith('/')) {
            pathname += '/'
        }

        const params: string[] = [`book_id=${encodeURIComponent(idStr)}`]
        if (libraryId) {
            params.push(`library_id=${encodeURIComponent(libraryId)}`)
        }
        params.push('panel=book_details')

        return `${parsed.origin}${pathname}${parsed.search}#${params.join('&')}`
    } catch {
        // Fallback for non-standard or malformed URLs
        const hashIdx = trimmedUrl.indexOf('#')
        let base = hashIdx >= 0 ? trimmedUrl.slice(0, hashIdx) : trimmedUrl
        const rawHash = hashIdx >= 0 ? trimmedUrl.slice(hashIdx + 1).trim() : ''

        let libraryId = ''
        if (rawHash) {
            if (rawHash.includes('&') || rawHash.includes('=')) {
                const match = rawHash.match(/(?:^|&)library_id=([^&]+)/)
                if (match) {
                    libraryId = decodeURIComponent(match[1])
                } else {
                    const firstPart = rawHash.split('&')[0]
                    if (!firstPart.includes('=')) {
                        libraryId = firstPart.replace(/^\/+/, '')
                    }
                }
            } else {
                libraryId = rawHash.replace(/^\/+/, '')
            }
        }

        base = base.replace(/\/+$/, '') + '/'
        const params: string[] = [`book_id=${encodeURIComponent(idStr)}`]
        if (libraryId) {
            params.push(`library_id=${encodeURIComponent(libraryId)}`)
        }
        params.push('panel=book_details')

        return `${base}#${params.join('&')}`
    }
}

export function isStoryCandidateUrl(rawUrl?: string): boolean {
    if (!rawUrl) return false
    const trimmed = rawUrl.trim()
    if (!trimmed) return false
    try {
        const withProto = /^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`
        const parsed = new URL(withProto)
        const host = parsed.hostname.toLowerCase()
        if (
            !host.includes('.') ||
            host === 'github.com' ||
            host === 'api.github.com' ||
            host === 'localhost' ||
            host === '127.0.0.1' ||
            host.startsWith('192.168.') ||
            host.startsWith('10.') ||
            /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(host)
        ) {
            return false
        }
    } catch {
        return false
    }
    return true
}

function isValidStoryTitle(title?: string | null): boolean {
    if (!title || !title.trim()) return false
    const lower = title.toLowerCase()
    if (
        lower.includes('/tmp') ||
        lower.includes('\\tmp') ||
        lower.startsWith('/var/') ||
        lower.startsWith('c:\\') ||
        lower.startsWith('/tmp/') ||
        lower.includes('temp directory') ||
        lower.endsWith('.epub') ||
        lower.startsWith('http://') ||
        lower.startsWith('https://')
    ) {
        return false
    }
    return true
}

function extractTitleFromLogMessage(message: string): string | null {
    // Worker explicit title logs: "Extracted title: Foo" or "Extracted title from filename: Foo"
    const extractedMatch = message.match(/Extracted title(?: from filename)?: (.+)$/i)
    if (extractedMatch) {
        const title = extractedMatch[1].trim()
        if (isValidStoryTitle(title)) return title
    }

    // Apprise notification dispatched for 'Story Title'
    const dispatchedMatch = message.match(/Apprise notification dispatched for '([^']+)'/i)
    if (dispatchedMatch) {
        const title = dispatchedMatch[1].trim()
        if (isValidStoryTitle(title)) return title
    }

    // Apprise notification: "Apprise notification for '...': 'Story Title' ..."
    const appriseMatch = message.match(/Apprise notification for '[^']+': '([^']+)'/i)
    if (appriseMatch) {
        const title = appriseMatch[1].trim()
        if (isValidStoryTitle(title)) return title
    }

    // "Successfully processed Foo" or "Successfully processed 'Foo'"
    const procMatch =
        message.match(/Successfully processed '([^']+)'/i) || message.match(/Successfully processed (.+)$/i)
    if (procMatch) {
        const title = procMatch[1].trim()
        if (isValidStoryTitle(title)) return title
    }

    return null
}

export function isStartupMessage(msg: string): boolean {
    const trimmed = msg.trim()
    const lower = trimmed.toLowerCase()
    return (
        lower.startsWith('starting automatedfanfic') ||
        lower.startsWith('for issues and updates') ||
        lower.startsWith('using configuration file') ||
        lower.startsWith('python version:') ||
        lower.startsWith('os / platform:') ||
        lower.startsWith('calibre version:') ||
        lower.startsWith('fanficfare version:') ||
        lower.startsWith('apprise version:') ||
        lower.includes('configuration details') ||
        lower.startsWith('email account:') ||
        lower.startsWith('email server:') ||
        lower.startsWith('email mailbox:') ||
        lower.startsWith('email sleep time:') ||
        lower.startsWith('disabled sites:') ||
        lower.startsWith('calibre path:') ||
        lower.startsWith('calibre default ini:') ||
        lower.startsWith('calibre personal ini:') ||
        lower.startsWith('update method:') ||
        lower.startsWith('update only (email):') ||
        lower.startsWith('metadata preservation mode:') ||
        lower.startsWith('pushbullet notifications:') ||
        lower.startsWith('pushbullet device:') ||
        lower.startsWith('apprise notifications:') ||
        lower.startsWith('max workers:') ||
        lower.startsWith('process monitoring:') ||
        lower.startsWith('auto restart:') ||
        trimmed.startsWith('---') ||
        trimmed.startsWith('----------------') ||
        lower.startsWith('generating url parsers') ||
        (lower.startsWith('generated ') && lower.includes('url parsers')) ||
        (lower.startsWith('spawning ') && lower.includes('worker pool')) ||
        lower.startsWith('configuration loaded successfully') ||
        lower.startsWith('apprise enabled') ||
        lower.startsWith('webserver: starting') ||
        lower.startsWith('web dashboard enabled') ||
        lower.startsWith('historywriter: started') ||
        lower.startsWith('starting all processes') ||
        lower.startsWith('all processes started') ||
        lower.startsWith('processes running') ||
        lower.startsWith('supervisor: starting helper services') ||
        (lower.startsWith('worker ') && lower.includes('started')) ||
        lower.startsWith('webserver: history database connection established')
    )
}

export interface SystemLogCategory {
    category: 'startup' | 'shutdown' | 'email' | 'webserver' | 'supervisor' | 'coordinator' | 'general'
    title: string
}

export function categorizeSystemLog(entry: LogEntry, inStartupWindow: boolean): SystemLogCategory {
    const msg = entry.message.trim()
    const lower = msg.toLowerCase()

    // 1. Shutdown / Teardown
    if (
        lower.includes('received signal sigterm') ||
        lower.includes('received signal sigint') ||
        lower.includes('initiating graceful shutdown') ||
        lower.includes('coordinator received shutdown signal') ||
        lower.includes('supervisor: waiting for threads to stop') ||
        lower.includes('historywriter: stopped') ||
        lower.includes('history database connection closed') ||
        lower.includes('stopped gracefully') ||
        lower.includes('shutting down gracefully')
    ) {
        return { category: 'shutdown', title: 'System Shutdown & Teardown' }
    }

    // 2. Email Watcher & IMAP (IMAP errors, inbox checks, unread counts)
    if (
        lower.startsWith('emailwatcher:') ||
        lower.startsWith('urlingester:') ||
        lower.includes('imap idle') ||
        lower.includes('imap error') ||
        lower.includes('imap connection') ||
        lower.includes('unread fanfiction email') ||
        lower.includes('checking imap') ||
        lower.includes('found unread email')
    ) {
        return { category: 'email', title: 'Email Watcher & IMAP' }
    }

    // 3. Application Startup
    const isReboot = lower.startsWith('starting automatedfanfic')
    if (
        Boolean(entry.is_startup) ||
        isReboot ||
        (inStartupWindow && isStartupMessage(msg)) ||
        (!inStartupWindow && (
            lower.startsWith('for issues and updates') ||
            lower.startsWith('using configuration file') ||
            lower.startsWith('python version:') ||
            lower.startsWith('os / platform:') ||
            lower.startsWith('generating url parsers') ||
            lower.startsWith('spawning ') ||
            isStartupMessage(msg)
        ))
    ) {
        return { category: 'startup', title: 'Application Startup & Lifecycle' }
    }

    // 4. Web Server & Configuration Management
    if (
        lower.startsWith('webserver:') ||
        lower.startsWith('configstore:') ||
        lower.includes('configuration loaded') ||
        lower.includes('web dashboard enabled') ||
        lower.includes('saving configuration')
    ) {
        return { category: 'webserver', title: 'Web Server & Configuration' }
    }

    // 5. Supervisor & Worker Management
    if (
        lower.startsWith('supervisor:') ||
        lower.startsWith('processmanager:') ||
        lower.startsWith('scalemanager:') ||
        (lower.startsWith('worker ') && lower.includes('started'))
    ) {
        return { category: 'supervisor', title: 'Process Supervisor Lifecycle' }
    }

    // 6. Coordinator & Ingestion Queue
    if (
        lower.startsWith('coordinator:') ||
        lower.includes('to the ingestion queue') ||
        lower.includes('worker idle for site') ||
        lower.includes('assigned site ')
    ) {
        return { category: 'coordinator', title: 'Coordinator Activity' }
    }

    // 7. General System Activity
    return { category: 'general', title: 'System Activity' }
}

function extractEntrySite(entry: LogEntry): string {
    if (entry.thread_site) return entry.thread_site
    const m = entry.message.match(SITE_PREFIX_RE)
    return m ? m[1] : ''
}

function inferTitleFromUrl(url: string): string {
    const parts = url.split('/').filter(Boolean)
    const lastPart = decodeURIComponent(parts[parts.length - 1] || 'Story').replace(/[-_]/g, ' ')
    return /^\d+$/.test(lastPart)
        ? `Work #${lastPart}`
        : lastPart.charAt(0).toUpperCase() + lastPart.slice(1)
}

export function buildLogAttemptBlocks(
    entries: LogEntry[] = [],
    knownDownloads: {
        url: string
        title?: string | null
        site?: string
        status?: string
        error_message?: string | null
        started_at?: string | null
        completed_at?: string | null
    }[] = [],
    knownRetries: {
        url: string
        title?: string | null
        site?: string
        attempt_number?: number
        error_message?: string | null
    }[] = [],
    activeItems: { url: string; stage: 'downloading' | 'queued' | 'waiting_retry' }[] = []
): LogAttemptBlock[] {
    if (entries.length === 0) return []

    // Normalize to chronological order (oldest -> newest):
    // By API contract, GET /api/logs and /api/logs/startup return newest-first.
    // Determine whether incoming entries are newest-first so we can reverse them.
    const isNewestFirst = (() => {
        if (entries.length < 2) return false
        // 1. Check timestamps if they differ anywhere in the list
        for (let i = 0; i < entries.length - 1; i++) {
            const tA = parseLogTimestamp(entries[i].timestamp)
            const tB = parseLogTimestamp(entries[i + 1].timestamp)
            if (tA > 0 && tB > 0 && tA !== tB) {
                return tA > tB
            }
        }
        // 2. Check seq if timestamps are identical
        for (let i = 0; i < entries.length - 1; i++) {
            const aSeq = entries[i].seq
            const bSeq = entries[i + 1].seq
            if (aSeq !== undefined && bSeq !== undefined && aSeq !== bSeq) {
                return aSeq > bSeq
            }
        }
        // 3. Fallback: by contract, GET /api/logs returns newest first.
        return true
    })()

    const baseList = isNewestFirst ? [...entries].reverse() : [...entries]
    const chronological = baseList.sort((a, b) => {
        const tA = parseLogTimestamp(a.timestamp)
        const tB = parseLogTimestamp(b.timestamp)
        if (tA > 0 && tB > 0 && tA !== tB) {
            return tA - tB
        }
        if (a.seq !== undefined && b.seq !== undefined && a.seq !== b.seq) {
            return a.seq - b.seq
        }
        return 0
    })

    const titleByUrl = new Map<string, string>()
    const errorByUrl = new Map<string, string>()
    const siteByUrl = new Map<string, string>()
    const attemptByUrl = new Map<string, number>()
    const activeStageByUrl = new Map<string, 'downloading' | 'queued' | 'waiting_retry'>()

    for (const d of knownDownloads) {
        if (d.title) titleByUrl.set(d.url, d.title)
        if (d.error_message) errorByUrl.set(d.url, d.error_message)
        if (d.site) siteByUrl.set(d.url, d.site)
    }
    for (const r of knownRetries) {
        if (r.title && !titleByUrl.has(r.url)) titleByUrl.set(r.url, r.title)
        if (r.error_message && !errorByUrl.has(r.url)) errorByUrl.set(r.url, r.error_message)
        if (r.site && !siteByUrl.has(r.url)) siteByUrl.set(r.url, r.site)
        if (r.attempt_number) attemptByUrl.set(r.url, r.attempt_number)
    }
    for (const a of activeItems) {
        activeStageByUrl.set(a.url, a.stage)
    }

    const blocks: LogAttemptBlock[] = []
    const activeBlockByAttemptId = new Map<string, LogAttemptBlock>()
    const activeBlockBySite = new Map<string, LogAttemptBlock>()
    const activeBlockByUrl = new Map<string, LogAttemptBlock>()
    const activeBlockByWorkerId = new Map<string, LogAttemptBlock>()
    const attemptCounterByUrl = new Map<string, number>()
    let currentSystemBlock: LogAttemptBlock | null = null
    let activeStartupBlock: LogAttemptBlock | null = null
    let startupCompleteSeen = false

    for (const entry of chronological) {
        const site = extractEntrySite(entry)
        const urlMatch = entry.message.match(URL_EXTRACT_RE)
        const isSystemBanner = isStartupMessage(entry.message)
        const procMatch = !urlMatch ? entry.message.match(/processing\s+([^\s<>"')]+)/i) : null
        const rawCandidateUrl =
            entry.story_url ||
            (urlMatch ? urlMatch[1] : undefined) ||
            (procMatch && isStoryCandidateUrl(procMatch[1]) ? procMatch[1] : undefined)
        const candidateUrl = rawCandidateUrl ? normalizeStoryUrl(rawCandidateUrl) : undefined
        const url = isSystemBanner ? undefined : isStoryCandidateUrl(candidateUrl) ? candidateUrl : undefined
        const msgLower = entry.message.toLowerCase()

        // Determine if this line starts or belongs to a story attempt
        let targetBlock: LogAttemptBlock | undefined

        if (entry.attempt_id) {
            targetBlock = activeBlockByAttemptId.get(entry.attempt_id)
            if (!targetBlock) {
                const prevCount = url ? attemptCounterByUrl.get(url) || 0 : 0
                const nextAttempt = prevCount + 1
                if (url) attemptCounterByUrl.set(url, nextAttempt)

                const resolvedSite = site || (url ? siteByUrl.get(url) : '') || ''
                const candidateTitle =
                    entry.story_title && isValidStoryTitle(entry.story_title) ? entry.story_title : undefined
                const resolvedTitle =
                    candidateTitle || (url ? titleByUrl.get(url) || inferTitleFromUrl(url) : 'Unknown Story')

                targetBlock = {
                    id: entry.attempt_id,
                    kind: 'story_attempt',
                    url,
                    title: resolvedTitle,
                    site: resolvedSite || undefined,
                    attemptNumber: (url && attemptByUrl.get(url)) || nextAttempt,
                    status: 'processing',
                    isActive: true,
                    activeStage: 'processing',
                    startedAt: entry.timestamp,
                    endedAt: entry.timestamp,
                    lines: [],
                    traceback: (url && errorByUrl.get(url)) || null,
                }
                blocks.push(targetBlock)
                activeBlockByAttemptId.set(entry.attempt_id, targetBlock)
                if (url) activeBlockByUrl.set(url, targetBlock)
                if (resolvedSite) activeBlockBySite.set(resolvedSite, targetBlock)
                if (entry.worker_id) activeBlockByWorkerId.set(entry.worker_id, targetBlock)
            }
        } else if (url) {
            const existingForUrl = activeBlockByUrl.get(url)
            const isStartTrigger =
                msgLower.includes('processing ') ||
                (msgLower.includes('queued ') && !msgLower.includes('queued retry')) ||
                msgLower.includes('immediate retry') ||
                msgLower.includes('scratch redownload')

            const hasProcessingStarted =
                existingForUrl &&
                existingForUrl.lines.some((l) => l.message.toLowerCase().includes('processing '))

            if (existingForUrl && (!isStartTrigger || !hasProcessingStarted)) {
                targetBlock = existingForUrl
            } else {
                const prevCount = attemptCounterByUrl.get(url) || 0
                const nextAttempt = prevCount + 1
                attemptCounterByUrl.set(url, nextAttempt)

                const resolvedSite = site || siteByUrl.get(url) || ''
                const candidateTitle =
                    entry.story_title && isValidStoryTitle(entry.story_title) ? entry.story_title : undefined
                const resolvedTitle = candidateTitle || titleByUrl.get(url) || inferTitleFromUrl(url)

                targetBlock = {
                    id: `attempt-${url}-${nextAttempt}-${entry.timestamp}`,
                    kind: 'story_attempt',
                    url,
                    title: resolvedTitle,
                    site: resolvedSite || undefined,
                    attemptNumber: attemptByUrl.get(url) || nextAttempt,
                    status: 'processing',
                    isActive: true,
                    activeStage: 'processing',
                    startedAt: entry.timestamp,
                    endedAt: entry.timestamp,
                    lines: [],
                    traceback: errorByUrl.get(url) || null,
                }
                blocks.push(targetBlock)
                activeBlockByUrl.set(url, targetBlock)
                if (resolvedSite) {
                    activeBlockBySite.set(resolvedSite, targetBlock)
                }
                if (entry.worker_id) {
                    activeBlockByWorkerId.set(entry.worker_id, targetBlock)
                }
            }
        } else if (entry.worker_id && activeBlockByWorkerId.has(entry.worker_id)) {
            targetBlock = activeBlockByWorkerId.get(entry.worker_id)
        } else if (site && activeBlockBySite.has(site)) {
            targetBlock = activeBlockBySite.get(site)
        } else if (msgLower.includes('assigned site ')) {
            // e.g. "Coordinator: Assigned site archiveofourown to worker_0"
            const assignedMatch = entry.message.match(/assigned site ([\w.-]+)/i)
            const assignedSite = assignedMatch ? assignedMatch[1] : ''
            if (assignedSite && activeBlockBySite.has(assignedSite)) {
                targetBlock = activeBlockBySite.get(assignedSite)
            }
        }

        if (targetBlock) {
            activeStartupBlock = null
            currentSystemBlock = null
            targetBlock.lines.push(entry)
            targetBlock.endedAt = entry.timestamp

            if (!targetBlock.site && site) {
                targetBlock.site = site
                activeBlockBySite.set(site, targetBlock)
            }
            const resolvedEntryUrl = entry.story_url || url
            if (!targetBlock.url && resolvedEntryUrl) {
                targetBlock.url = normalizeStoryUrl(resolvedEntryUrl)
                activeBlockByUrl.set(targetBlock.url, targetBlock)
            }

            // Check if log message mentions explicit retry number
            const retryMatch = entry.message.match(RETRY_NUM_RE)
            if (retryMatch) {
                const rNum = parseInt(retryMatch[1], 10)
                if (!isNaN(rNum) && rNum > 1) {
                    targetBlock.attemptNumber = Math.max(targetBlock.attemptNumber, rNum - 1)
                }
            }

            // Update title if new valid title is discovered
            if (entry.story_title && isValidStoryTitle(entry.story_title)) {
                targetBlock.title = entry.story_title.trim()
            } else if (
                targetBlock.title.startsWith('Work #') ||
                targetBlock.title === 'Unknown Story' ||
                targetBlock.title === 'Story'
            ) {
                const parsedTitle = extractTitleFromLogMessage(entry.message)
                if (parsedTitle) {
                    targetBlock.title = parsedTitle
                }
            }

            // Update block status based on line severity and keywords
            const lvl = entry.level.toLowerCase()
            const isSuccess =
                msgLower.includes('successfully updated') ||
                msgLower.includes('successfully processed') ||
                msgLower.includes('notification dispatched') ||
                msgLower.includes('sent successfully to') ||
                msgLower.includes('completed -> book id') ||
                msgLower.includes('story is in calibre with story id') ||
                msgLower.includes('added book ids:')

            const isFailure =
                lvl === 'error' ||
                lvl === 'critical' ||
                msgLower.includes('failed to download') ||
                msgLower.includes('download failed') ||
                msgLower.includes('failed to process') ||
                msgLower.includes('failed to update') ||
                msgLower.includes('queued retry') ||
                msgLower.includes('moving to hail-mary') ||
                msgLower.includes('giving up on') ||
                msgLower.includes('retry exhausted')

            if (isFailure) {
                targetBlock.status = 'failed'
            } else if (isSuccess && targetBlock.status !== 'failed') {
                targetBlock.status = 'success'
            }

            // If this line closes out the attempt, release active site/url/worker pointers
            const isClosed =
                isSuccess ||
                msgLower.includes('queued retry') ||
                msgLower.includes('moving to hail-mary') ||
                msgLower.includes('giving up on') ||
                msgLower.includes('retry exhausted') ||
                msgLower.includes('finished site ') ||
                msgLower.includes('worker idle for site') ||
                msgLower.includes('signaling worker')

            if (isClosed) {
                if (targetBlock.url) activeBlockByUrl.delete(targetBlock.url)
                if (targetBlock.site) activeBlockBySite.delete(targetBlock.site)
                if (entry.worker_id) activeBlockByWorkerId.delete(entry.worker_id)
            }
        } else {
            const isRebootMarker = msgLower.startsWith('starting automatedfanfic')
            if (isRebootMarker) {
                activeStartupBlock = null
                currentSystemBlock = null
                startupCompleteSeen = false
            }

            const inStartupWindow = (activeStartupBlock !== null && !startupCompleteSeen)
            const sysCat = categorizeSystemLog(entry, inStartupWindow)

            let targetSystemBlock: LogAttemptBlock | null = null

            if (sysCat.category === 'startup') {
                const timeDiffSec = activeStartupBlock
                    ? Math.abs(parseLogTimestamp(entry.timestamp) - parseLogTimestamp(activeStartupBlock.endedAt)) / 1000
                    : 999999

                if (!activeStartupBlock || timeDiffSec > 120) {
                    activeStartupBlock = {
                        id: `startup-${entry.timestamp}-${blocks.length}`,
                        kind: 'system',
                        title: 'Application Startup & Lifecycle',
                        attemptNumber: 1,
                        status: 'system',
                        isActive: false,
                        startedAt: entry.timestamp,
                        endedAt: entry.timestamp,
                        lines: [entry],
                    }
                    blocks.push(activeStartupBlock)
                    startupCompleteSeen = false
                    currentSystemBlock = null
                } else {
                    activeStartupBlock.lines.push(entry)
                    activeStartupBlock.endedAt = entry.timestamp
                }
                targetSystemBlock = activeStartupBlock
            } else {
                activeStartupBlock = null

                const timeDiffSec = currentSystemBlock && currentSystemBlock.title === sysCat.title
                    ? Math.abs(parseLogTimestamp(entry.timestamp) - parseLogTimestamp(currentSystemBlock.endedAt)) / 1000
                    : 999999

                if (
                    !currentSystemBlock ||
                    currentSystemBlock.title !== sysCat.title ||
                    timeDiffSec > 180
                ) {
                    currentSystemBlock = {
                        id: `sys-${entry.timestamp}-${blocks.length}`,
                        kind: 'system',
                        title: sysCat.title,
                        attemptNumber: 1,
                        status: 'system',
                        isActive: false,
                        startedAt: entry.timestamp,
                        endedAt: entry.timestamp,
                        lines: [entry],
                    }
                    blocks.push(currentSystemBlock)
                } else {
                    currentSystemBlock.lines.push(entry)
                    currentSystemBlock.endedAt = entry.timestamp
                }
                targetSystemBlock = currentSystemBlock
            }

            if (targetSystemBlock) {
                const lvl = entry.level.toLowerCase()
                if (lvl === 'error' || lvl === 'critical') {
                    targetSystemBlock.status = 'failed'
                }
            }
        }
    }

    // Determine final isActive status for each block:
    // A block is active if its status is still 'processing' OR if it is the latest block for a URL currently in activeItems
    const latestBlockByUrl = new Map<string, LogAttemptBlock>()
    for (const b of blocks) {
        if (b.url) {
            const prev = latestBlockByUrl.get(b.url)
            const tPrev = prev ? parseLogTimestamp(prev.endedAt) : 0
            const tCurr = parseLogTimestamp(b.endedAt)
            if (!prev || tCurr >= tPrev) {
                latestBlockByUrl.set(b.url, b)
            }
        }
    }

    for (const b of blocks) {
        if (b.lines.length > 1) {
            b.lines.sort((a, b) => {
                const tA = parseLogTimestamp(a.timestamp)
                const tB = parseLogTimestamp(b.timestamp)
                if (tA > 0 && tB > 0 && tA !== tB) {
                    return tA - tB
                }
                if (a.seq !== undefined && b.seq !== undefined && a.seq !== b.seq) {
                    return a.seq - b.seq
                }
                return 0
            })
            b.startedAt = b.lines[0].timestamp
            b.endedAt = b.lines[b.lines.length - 1].timestamp
        }
        if (b.kind === 'system') {
            b.isActive = false
            b.activeStage = undefined
            continue
        }
        const inFlightStage = b.url ? activeStageByUrl.get(b.url) : undefined
        const isLatestForUrl = b.url ? latestBlockByUrl.get(b.url) === b : false
        if (inFlightStage && isLatestForUrl) {
            b.isActive = true
            b.activeStage = inFlightStage
        } else if (b.status === 'processing') {
            b.isActive = true
            b.activeStage = 'processing'
        } else {
            b.isActive = false
            b.activeStage = undefined
        }
    }

    // Filter out system blocks from before the current application startup.
    // Persistent log hydration is strictly intended for story events/processing.
    // Past system lifecycle logs (old shutdowns, past startups, prior health checks)
    // from earlier sessions must never be shown on the live attempts dashboard.
    let latestStartupTs = 0
    for (const entry of chronological) {
        if (entry.message.toLowerCase().startsWith('starting automatedfanfic')) {
            const t = parseLogTimestamp(entry.timestamp)
            if (t > latestStartupTs) {
                latestStartupTs = t
            }
        }
    }

    const visibleBlocks = latestStartupTs > 0
        ? blocks.filter((b) => b.kind !== 'system' || parseLogTimestamp(b.endedAt) >= latestStartupTs)
        : blocks

    // Sort active blocks first, then non-active blocks; within each group sort by latest update (endedAt descending)
    return visibleBlocks.sort((a, b) => {
        if (a.isActive !== b.isActive) {
            return a.isActive ? -1 : 1
        }
        const tA = parseLogTimestamp(a.endedAt)
        const tB = parseLogTimestamp(b.endedAt)
        if (tA > 0 && tB > 0 && tA !== tB) {
            return tB - tA
        }
        return 0
    })
}

export function getAttemptBlockForStory(
    url: string,
    entries: LogEntry[],
    knownDownloads: { url: string; title?: string | null; site?: string; status?: string; error_message?: string | null }[] = [],
    knownRetries: { url: string; title?: string | null; site?: string; attempt_number?: number; error_message?: string | null }[] = [],
    activeItems: { url: string; stage: 'downloading' | 'queued' | 'waiting_retry' }[] = []
): LogAttemptBlock | null {
    const allBlocks = buildLogAttemptBlocks(entries, knownDownloads, knownRetries, activeItems)
    return allBlocks.find((b) => b.url === url) || null
}

export function formatAttemptBlockAsText(block: LogAttemptBlock): string {
    const header = `=== ${block.title} (${block.site || 'system'}) — Attempt #${block.attemptNumber} [${block.status.toUpperCase()}] ===`
    const urlLine = block.url ? `URL: ${block.url}` : ''
    const windowLine = `Time: ${block.startedAt} -> ${block.endedAt}`
    const logLines = block.lines.map((l) => `${l.timestamp} [${l.level.toUpperCase()}] ${l.message}`).join('\n')
    const tracePart = block.traceback ? `\n--- Stack Trace / Diagnostic Output ---\n${block.traceback}` : ''
    return [header, urlLine, windowLine, '--- Execution Log ---', logLines, tracePart]
        .filter(Boolean)
        .join('\n')
}

export interface ErrorDiagnosis {
    category: string
    summary: string
    hint: string
    configTab?: string
    configLabel?: string
}

export function diagnoseErrorSignature(errorText?: string | null): ErrorDiagnosis | null {
    if (!errorText) return null
    const lower = errorText.toLowerCase()

    if (
        lower.includes('cloudflare') ||
        lower.includes('anubis') ||
        lower.includes('503') ||
        lower.includes('challenge') ||
        lower.includes('flaresolverr')
    ) {
        return {
            category: 'Anti-Bot / Cloudflare Challenge',
            summary: 'Source site presented an anti-bot challenge or solver timed out.',
            hint: 'Configure FlareSolverr proxy or update cf_clearance cookie settings in personal.ini, or allow automatic exponential backoff to retry.',
            configTab: 'personal.ini',
            configLabel: 'Open personal.ini',
        }
    }

    if (
        lower.includes('404') ||
        lower.includes('not found') ||
        lower.includes('removed') ||
        lower.includes('deleted')
    ) {
        return {
            category: 'Story Removed or Restricted (404)',
            summary: 'The story URL returned 404 Not Found or was restricted by the author.',
            hint: 'Further retries will likely fail unless the URL was temporarily unavailable. Consider cancelling scheduled retries.',
        }
    }

    if (
        lower.includes('adult') ||
        lower.includes('login') ||
        lower.includes('401') ||
        lower.includes('403') ||
        lower.includes('unauthorized')
    ) {
        return {
            category: 'Auth / Adult Content Gate',
            summary: 'Site requires adult confirmation or account login credentials.',
            hint: 'Verify is_adult:true and site username/password or cookiejar entries inside personal.ini.',
            configTab: 'personal.ini',
            configLabel: 'Open personal.ini',
        }
    }

    if (
        lower.includes('calibre') ||
        lower.includes('calibredb') ||
        lower.includes('database is locked') ||
        lower.includes('connection refused')
    ) {
        return {
            category: 'Calibre Library Target Error',
            summary: 'Worker could not write to Calibre library or Content Server.',
            hint: 'Verify that Calibre Content Server is reachable and no other process holds an exclusive lock.',
            configTab: 'calibre',
            configLabel: 'Test Calibre Config',
        }
    }

    return null
}

export interface PiiScrubOptions {
    redactStoryUrls?: boolean
    storyTitle?: string
}

export interface PiiScrubResult {
    text: string
    redactionCount: number
    detectedTypes: string[]
}

export function scrubPiiFromLogText(input: string, options?: PiiScrubOptions): PiiScrubResult {
    if (!input) {
        return { text: '', redactionCount: 0, detectedTypes: [] }
    }
    let text = input
    let redactionCount = 0
    const detectedTypes = new Set<string>()

    // 1. Email addresses
    text = text.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, () => {
        redactionCount++
        detectedTypes.add('email address')
        return '[REDACTED_EMAIL]'
    })

    // 2. Pushbullet tokens (o.xxxx) or Bearer tokens
    text = text.replace(/\bo\.[A-Za-z0-9]{12,}\b/g, () => {
        redactionCount++
        detectedTypes.add('Pushbullet token')
        return 'o.[REDACTED_TOKEN]'
    })
    text = text.replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*\b/gi, () => {
        redactionCount++
        detectedTypes.add('auth token')
        return 'Bearer [REDACTED_TOKEN]'
    })

    // 3. Key-value secrets (password, token, cf_clearance, cookie, api_key, secret)
    text = text.replace(
        /\b(password|passwd|secret|api_key|apikey|access_token|auth_token|cf_clearance|session_id|phpbb3_[a-z0-9_]+)\s*([=:])\s*([^\s,;'"&\])}]+)/gi,
        (_match, key: string, sep: string) => {
            redactionCount++
            detectedTypes.add('credential/cookie')
            return `${key}${sep}[REDACTED]`
        }
    )

    // 4. Local user filesystem paths (/Users/name/, /home/name/, C:\Users\name\)
    text = text.replace(/(\/Users\/|\/home\/)([^/\s:'"]+)/g, (_match, prefix: string, user: string) => {
        if (user === '[REDACTED_USER]' || user === 'app') return _match
        redactionCount++
        detectedTypes.add('local username path')
        return `${prefix}[REDACTED_USER]`
    })
    text = text.replace(/([A-Za-z]:\\Users\\)([^\\\s:'"]+)/g, (_match, prefix: string, user: string) => {
        if (user === '[REDACTED_USER]') return _match
        redactionCount++
        detectedTypes.add('local username path')
        return `${prefix}[REDACTED_USER]`
    })

    // 5. IPv4 addresses (excluding 127.0.0.1 and 0.0.0.0)
    text = text.replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, (ip) => {
        if (ip === '127.0.0.1' || ip === '0.0.0.0') return ip
        redactionCount++
        detectedTypes.add('IP address')
        return '[REDACTED_IP]'
    })

    // 6. Optional: Redact story URLs and story title
    if (options?.redactStoryUrls) {
        text = text.replace(/https?:\/\/[^\s<>"')`\]]+/gi, (url) => {
            if (url.includes('github.com')) return url
            redactionCount++
            detectedTypes.add('story URL')
            return '[REDACTED_STORY_URL]'
        })
    }
    if (options?.storyTitle && options.storyTitle.trim().length > 2) {
        const escaped = options.storyTitle.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const re = new RegExp(escaped, 'gi')
        if (re.test(text)) {
            text = text.replace(re, () => {
                redactionCount++
                detectedTypes.add('story title')
                return '[REDACTED_STORY_TITLE]'
            })
        }
    }

    return {
        text,
        redactionCount,
        detectedTypes: Array.from(detectedTypes),
    }
}

export interface GitHubIssueDraft {
    title: string
    body: string
    detectedPiiCount: number
    detectedPiiTypes: string[]
}

/**
 * Algorithmically extracts component and environment versions from log entries or text.
 */
export function extractSystemVersionsFromLogs(
    logs: (LogEntry | string)[]
): Partial<SystemVersionInfo> {
    const result: Partial<SystemVersionInfo> = {}
    for (const item of logs) {
        const msg = typeof item === 'string' ? item : item.message || ''

        const afMatch = msg.match(/Starting AutomatedFanfic v([0-9a-zA-Z.-]+)/i)
        if (afMatch && !result.automatedfanfic) {
            result.automatedfanfic = afMatch[1]
        }
        const pyMatch = msg.match(/Python version:\s*([^\n\r]+)/i)
        if (pyMatch && !result.python) {
            result.python = pyMatch[1].trim()
        }
        const osMatch = msg.match(/OS \/ Platform:\s*([^\n\r]+)/i)
        if (osMatch && !result.platform) {
            result.platform = osMatch[1].trim()
        }
        const calMatch = msg.match(/Calibre version:\s*([^\n\r]+)/i)
        if (calMatch && !result.calibre) {
            result.calibre = calMatch[1].trim()
        }
        const fffMatch = msg.match(/FanFicFare version:\s*([^\n\r]+)/i)
        if (fffMatch && !result.fanficfare) {
            result.fanficfare = fffMatch[1].trim()
        }
        const appMatch = msg.match(/Apprise version:\s*([^\n\r]+)/i)
        if (appMatch && !result.apprise) {
            result.apprise = appMatch[1].trim()
        }
    }
    return result
}

export function buildGitHubIssueDraft(options: {
    block?: LogAttemptBlock | null
    rawLogsText?: string
    startupLogs?: LogEntry[]
    systemVersions?: Partial<SystemVersionInfo> | null
    mode?: 'runtime' | 'startup'
    scrubPii?: boolean
    redactStoryUrls?: boolean
}): GitHubIssueDraft {
    const {
        block,
        rawLogsText,
        startupLogs = [],
        systemVersions = null,
        mode = 'runtime',
        scrubPii = false,
        redactStoryUrls = false,
    } = options

    let rawTitle = ''
    let rawBody = ''

    const startupLinesText =
        startupLogs.length > 0
            ? startupLogs
                  .map((l) => `${l.timestamp} [${l.level.toUpperCase()}] ${l.message}`)
                  .join('\n')
            : ''

    // Algorithmically merge detected versions across startup logs, block lines, raw text, and passed system info
    const detectedVersions: Partial<SystemVersionInfo> = {
        ...extractSystemVersionsFromLogs(startupLogs),
        ...extractSystemVersionsFromLogs(block?.lines || []),
        ...extractSystemVersionsFromLogs(rawLogsText ? rawLogsText.split('\n') : []),
        ...(systemVersions || {}),
    }

    const versionEntries: string[] = []
    if (detectedVersions.automatedfanfic) {
        versionEntries.push(`- **AutomatedFanfic**: \`v${detectedVersions.automatedfanfic.replace(/^v/i, '')}\``)
    }
    if (detectedVersions.python) {
        versionEntries.push(`- **Python**: \`${detectedVersions.python}\``)
    }
    if (detectedVersions.platform) {
        versionEntries.push(`- **Platform / OS**: \`${detectedVersions.platform}\``)
    }
    if (detectedVersions.fanficfare) {
        versionEntries.push(`- **FanFicFare**: \`${detectedVersions.fanficfare}\``)
    }
    if (detectedVersions.calibre) {
        versionEntries.push(`- **Calibre**: \`${detectedVersions.calibre}\``)
    }
    if (detectedVersions.apprise) {
        versionEntries.push(`- **Apprise**: \`${detectedVersions.apprise}\``)
    }

    const versionMarkdown =
        versionEntries.length > 0
            ? ['', '### Environment & Component Versions', ...versionEntries]
            : []

    if (block) {
        const siteLabel = block.site || 'system'
        const statusLabel = block.status === 'failed' ? 'Download failure' : `Log report (${block.status})`
        rawTitle = `[Bug] (${siteLabel}) ${statusLabel}: ${block.title}`

        const logLinesText = block.lines
            .map((l) => `${l.timestamp} [${l.level.toUpperCase()}] ${l.message}`)
            .join('\n')

        const sections: string[] = [
            '### Summary',
            '<!-- Briefly describe what went wrong or what behavior you expected -->',
            ...versionMarkdown,
            '',
            '### Attempt Diagnostic Context',
            `- **Worker / Site**: \`${siteLabel}\``,
            `- **Story / Task**: ${block.title}`,
            ...(block.url ? [`- **Story URL**: ${block.url}`] : []),
            `- **Attempt**: #${block.attemptNumber}${block.isActive ? ` (${block.activeStage || 'active'})` : ''}`,
            `- **Status**: \`${block.status.toUpperCase()}\``,
            `- **Time Window**: \`${block.startedAt}\` → \`${block.endedAt}\``,
            '',
            '### Execution Log Block',
            '```text',
            logLinesText || '(No log lines recorded)',
            '```',
        ]

        if (block.traceback) {
            sections.push(
                '',
                '### Exception / Stack Trace',
                '```python',
                block.traceback.trim(),
                '```'
            )
        }

        if (startupLinesText) {
            sections.push(
                '',
                '### Startup Log & Environment Context',
                '<details>',
                '<summary> Startup & Supervisor Initialization Logs</summary>',
                '',
                '```text',
                startupLinesText,
                '```',
                '</details>'
            )
        }

        rawBody = sections.join('\n')
    } else {
        rawTitle = `[Bug] AutomatedFanfic ${mode === 'startup' ? 'Startup' : 'Runtime'} Log Report`
        const trimmedLogs = (rawLogsText || '').trim() || '(No logs selected)'
        const sections: string[] = [
            '### Summary',
            '<!-- Briefly describe what went wrong or what behavior you expected -->',
            ...versionMarkdown,
            '',
            '### Environment & Log Context',
            `- **Log Buffer**: \`${mode.toUpperCase()}\``,
            `- **Captured At**: \`${new Date().toISOString().replace('T', ' ').slice(0, 19)}\``,
            '',
            '### Captured Logs',
            '```text',
            trimmedLogs,
            '```',
        ]

        if (startupLinesText && mode !== 'startup') {
            sections.push(
                '',
                '### Startup Log & Environment Context',
                '<details>',
                '<summary>Startup & Supervisor Initialization Logs</summary>',
                '',
                '```text',
                startupLinesText,
                '```',
                '</details>'
            )
        }

        rawBody = sections.join('\n')
    }

    const scrubOpts: PiiScrubOptions = {
        redactStoryUrls,
        storyTitle: redactStoryUrls && block?.title ? block.title : undefined,
    }
    const titleCheck = scrubPiiFromLogText(rawTitle, scrubOpts)
    const bodyCheck = scrubPiiFromLogText(rawBody, scrubOpts)
    const combinedTypes = Array.from(new Set([...titleCheck.detectedTypes, ...bodyCheck.detectedTypes]))
    const totalDetected = titleCheck.redactionCount + bodyCheck.redactionCount

    const shouldApplyScrub = scrubPii || redactStoryUrls

    return {
        title: shouldApplyScrub ? titleCheck.text : rawTitle,
        body: shouldApplyScrub ? bodyCheck.text : rawBody,
        detectedPiiCount: totalDetected,
        detectedPiiTypes: combinedTypes,
    }
}

export interface IniDiffLine {
    type: 'same' | 'add' | 'remove'
    lineNumber: number
    text: string
}

export function computeIniLineDiff(initialIni: string, currentIni: string): IniDiffLine[] {
    const oldLines = initialIni.split('\n')
    const newLines = currentIni.split('\n')
    const result: IniDiffLine[] = []
    const maxLen = Math.max(oldLines.length, newLines.length)

    for (let i = 0; i < maxLen; i++) {
        const oldL = oldLines[i]
        const newL = newLines[i]
        if (oldL === newL && oldL !== undefined) {
            result.push({ type: 'same', lineNumber: i + 1, text: newL })
        } else {
            if (oldL !== undefined && (newL === undefined || oldL !== newL)) {
                result.push({ type: 'remove', lineNumber: i + 1, text: oldL })
            }
            if (newL !== undefined && (oldL === undefined || oldL !== newL)) {
                result.push({ type: 'add', lineNumber: i + 1, text: newL })
            }
        }
    }
    return result
}

export function extractIniSections(iniContent: string): { name: string; line: number }[] {
    const lines = iniContent.split('\n')
    const sections: { name: string; line: number }[] = []
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].trim().match(/^\[([^\]]+)\]$/)
        if (m) {
            sections.push({ name: m[1], line: i + 1 })
        }
    }
    return sections
}

export function buildGitHubIssueUrl(options: {
    repo: string
    title: string
    body: string
    labels?: string[]
}): { url: string; isTruncated: boolean } {
    const cleanRepo = (options.repo || 'AutomatedFanfic/AutomatedFanfic')
        .trim()
        .replace(/^https?:\/\/github\.com\//i, '')
        .replace(/\/+$/, '')
    const repoPath = cleanRepo.includes('/') ? cleanRepo : 'AutomatedFanfic/AutomatedFanfic'

    const MAX_BODY_CHARS_FOR_URL = 5500
    let bodyForUrl = options.body
    let isTruncated = false

    if (bodyForUrl.length > MAX_BODY_CHARS_FOR_URL) {
        isTruncated = true
        bodyForUrl =
            bodyForUrl.slice(0, MAX_BODY_CHARS_FOR_URL) +
            '\n```\n\n> ⚠️ *[Log output truncated to fit GitHub URL length limit — paste full copied markdown from dashboard if needed]*'
    }

    const params = new URLSearchParams()
    params.set('title', options.title)
    params.set('body', bodyForUrl)
    if (options.labels && options.labels.length > 0) {
        params.set('labels', options.labels.join(','))
    }

    return {
        url: `https://github.com/${repoPath}/issues/new?${params.toString()}`,
        isTruncated,
    }
}

export function computeDirtySections(
    config: Record<string, unknown> | null,
    initialConfig: Record<string, unknown> | null,
    personalIni: string,
    initialPersonalIni: string
): Record<string, string[]> {
    const result: Record<string, string[]> = {}
    if (config && initialConfig) {
        for (const section of Object.keys(config)) {
            const cur = config[section]
            const init = initialConfig[section]
            if (typeof cur === 'object' && cur !== null && typeof init === 'object' && init !== null) {
                const curObj = cur as Record<string, unknown>
                const initObj = init as Record<string, unknown>
                const dirtyKeys: string[] = []
                for (const key of Object.keys(curObj)) {
                    if (JSON.stringify(curObj[key]) !== JSON.stringify(initObj[key])) {
                        dirtyKeys.push(key)
                    }
                }
                if (dirtyKeys.length > 0) {
                    result[section] = dirtyKeys
                }
            }
        }
    }
    if (personalIni !== initialPersonalIni) {
        result['personal.ini'] = ['content']
    }
    return result
}

export function getStatusColor(status: string): string {
    const key = status.toLowerCase()
    if (key === 'success') return STATUS_COLORS.success
    if (key === 'failed') return STATUS_COLORS.failed
    if (key === 'abandoned') return STATUS_COLORS.abandoned
    if (key === 'waiting') return STATUS_COLORS.waiting
    if (key === 'pending' || key === 'processing' || key === 'retry') return STATUS_COLORS.pending
    return STATUS_COLORS.accent
}

export function buildTimelineBuckets(
    downloads: DownloadRow[],
    period: '24h' | '7d' | '30d',
    nowMs = Date.now()
): TimePoint[] {
    if (period === '24h') {
        const buckets: TimePoint[] = []
        const currentHour = new Date(nowMs)
        currentHour.setMinutes(0, 0, 0)

        const hourMap = new Map<string, { total: number; success: number; failed: number }>()
        for (let i = 23; i >= 0; i--) {
            const slot = new Date(currentHour.getTime() - i * 3600 * 1000)
            const label = `${String(slot.getHours()).padStart(2, '0')}:00`
            hourMap.set(label, { total: 0, success: 0, failed: 0 })
        }

        const cutoff = nowMs - 24 * 3600 * 1000
        for (const d of downloads) {
            const t = new Date(d.started_at).getTime()
            if (isNaN(t) || t < cutoff) continue
            const dt = new Date(t)
            const label = `${String(dt.getHours()).padStart(2, '0')}:00`
            const bucket = hourMap.get(label)
            if (bucket) {
                bucket.total += 1
                if (d.status === 'success') bucket.success += 1
                else bucket.failed += 1
            }
        }

        for (const [date, counts] of hourMap.entries()) {
            buckets.push({ date, ...counts })
        }
        return buckets
    }

    const days = period === '7d' ? 7 : 30
    const dayMap = new Map<string, { total: number; success: number; failed: number }>()
    const end = new Date(nowMs)

    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(end)
        d.setDate(d.getDate() - i)
        const key = d.toISOString().slice(0, 10)
        dayMap.set(key, { total: 0, success: 0, failed: 0 })
    }

    const cutoff = nowMs - days * 24 * 3600 * 1000
    for (const d of downloads) {
        const t = new Date(d.started_at).getTime()
        if (isNaN(t) || t < cutoff) continue
        const key = new Date(t).toISOString().slice(0, 10)
        const bucket = dayMap.get(key)
        if (bucket) {
            bucket.total += 1
            if (d.status === 'success') bucket.success += 1
            else bucket.failed += 1
        }
    }

    return Array.from(dayMap.entries()).map(([date, counts]) => ({
        date,
        ...counts,
    }))
}

export function filterDownloadsByPeriod(
    downloads: DownloadRow[],
    period: '24h' | '7d' | '30d',
    nowMs = Date.now()
): DownloadRow[] {
    const msInPeriod =
        period === '24h' ? 24 * 3600 * 1000 : period === '7d' ? 7 * 24 * 3600 * 1000 : 30 * 24 * 3600 * 1000
    return downloads.filter((d) => {
        const t = new Date(d.started_at).getTime()
        return !isNaN(t) && nowMs - t <= msInPeriod
    })
}

export function filterRetriesByPeriod(
    retries: RetryRow[],
    period: '24h' | '7d' | '30d',
    nowMs = Date.now()
): RetryRow[] {
    const msInPeriod =
        period === '24h' ? 24 * 3600 * 1000 : period === '7d' ? 7 * 24 * 3600 * 1000 : 30 * 24 * 3600 * 1000
    return retries.filter((r) => {
        const t = new Date(r.scheduled_at).getTime()
        return !isNaN(t) && nowMs - t <= msInPeriod
    })
}

export function computeSiteBreakdown(downloads: DownloadRow[]): SiteStats[] {
    const siteMap: Record<string, { total: number; success: number; failed: number }> = {}
    for (const d of downloads) {
        if (!siteMap[d.site]) siteMap[d.site] = { total: 0, success: 0, failed: 0 }
        siteMap[d.site].total++
        if (d.status === 'success') siteMap[d.site].success++
        else siteMap[d.site].failed++
    }
    return Object.entries(siteMap).map(([site, counts]) => ({
        site,
        ...counts,
    }))
}

export function computeStatusBreakdown(downloads: DownloadRow[]): StatusPoint[] {
    const statusMap: Record<string, number> = {}
    for (const d of downloads) {
        statusMap[d.status] = (statusMap[d.status] || 0) + 1
    }
    return Object.entries(statusMap).map(([status, count]) => ({
        status,
        count,
    }))
}
