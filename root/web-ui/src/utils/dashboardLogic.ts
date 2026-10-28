import type {
    DownloadRow,
    RetryRow,
    WaitingDownload,
    TimePoint,
    SiteStats,
    StatusPoint,
    LogEntry,
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

function isStoryCandidateUrl(rawUrl?: string): boolean {
    if (!rawUrl) return false
    try {
        const parsed = new URL(rawUrl)
        const host = parsed.hostname.toLowerCase()
        if (
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

function isStartupMessage(msg: string): boolean {
    return (
        msg.startsWith('Starting all processes') ||
        msg.startsWith('All processes started') ||
        msg.startsWith('Processes running') ||
        msg.startsWith('FanFicFare version:') ||
        msg.startsWith('Calibre version:') ||
        msg.startsWith('WebServer:') ||
        msg.startsWith('Configuration loaded') ||
        msg.startsWith('Supervisor: Starting helper services') ||
        msg.startsWith('Apprise enabled') ||
        msg.startsWith('HistoryWriter: started') ||
        (msg.startsWith('Worker ') && msg.includes('started')) ||
        msg.startsWith('Spawning ') ||
        msg.startsWith('Calibre Path:') ||
        msg.startsWith('For issues and updates')
    )
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
    entries: LogEntry[],
    knownDownloads: { url: string; title?: string | null; site?: string; status?: string; error_message?: string | null }[] = [],
    knownRetries: { url: string; title?: string | null; site?: string; attempt_number?: number; error_message?: string | null }[] = [],
    activeItems: { url: string; stage: 'downloading' | 'queued' | 'waiting_retry' }[] = []
): LogAttemptBlock[] {
    if (entries.length === 0) return []

    // Sort oldest -> newest so we trace each attempt's lifecycle in execution order
    const chronological = [...entries].sort((a, b) => a.timestamp.localeCompare(b.timestamp))

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

    for (const entry of chronological) {
        const site = extractEntrySite(entry)
        const urlMatch = entry.message.match(URL_EXTRACT_RE)
        const isSystemBanner = isStartupMessage(entry.message)
        const candidateUrl = entry.story_url || (urlMatch ? urlMatch[1] : undefined)
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

            if (existingForUrl && (!isStartTrigger || existingForUrl.lines.length <= 1)) {
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
            currentSystemBlock = null
            targetBlock.lines.push(entry)
            targetBlock.endedAt = entry.timestamp

            if (!targetBlock.site && site) {
                targetBlock.site = site
                activeBlockBySite.set(site, targetBlock)
            }
            const resolvedEntryUrl = entry.story_url || url
            if (!targetBlock.url && resolvedEntryUrl) {
                targetBlock.url = resolvedEntryUrl
                activeBlockByUrl.set(resolvedEntryUrl, targetBlock)
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
            // System / Supervisor / IMAP IDLE event block
            const isStartup = isStartupMessage(entry.message)
            const targetTitle = isStartup
                ? 'Application Startup & Lifecycle'
                : entry.message.startsWith('UrlIngester:')
                  ? 'IMAP Inbox Watcher Check'
                  : entry.message.startsWith('Supervisor:') || entry.message.startsWith('ProcessManager:')
                    ? 'Process Supervisor Lifecycle'
                    : 'System & Coordinator Activity'

            const timeDiffSec = currentSystemBlock
                ? (() => {
                      const d1 = new Date(entry.timestamp.replace(' ', 'T')).getTime()
                      const d2 = new Date(currentSystemBlock.endedAt.replace(' ', 'T')).getTime()
                      return isNaN(d1) || isNaN(d2) ? 0 : Math.abs(d1 - d2) / 1000
                  })()
                : 999999

            if (
                !currentSystemBlock ||
                currentSystemBlock.title !== targetTitle ||
                timeDiffSec > 300 ||
                currentSystemBlock.lines.length >= 100
            ) {
                currentSystemBlock = {
                    id: `sys-${entry.timestamp}-${blocks.length}`,
                    kind: 'system',
                    title: targetTitle,
                    attemptNumber: 1,
                    status: entry.level.toLowerCase() === 'error' ? 'failed' : 'system',
                    isActive: false,
                    startedAt: entry.timestamp,
                    endedAt: entry.timestamp,
                    lines: [entry],
                }
                blocks.push(currentSystemBlock)
            } else {
                currentSystemBlock.lines.push(entry)
                currentSystemBlock.endedAt = entry.timestamp
                if (entry.level.toLowerCase() === 'error') {
                    currentSystemBlock.status = 'failed'
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
            if (!prev || b.endedAt.localeCompare(prev.endedAt) >= 0) {
                latestBlockByUrl.set(b.url, b)
            }
        }
    }

    for (const b of blocks) {
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

    // Sort active blocks first, then non-active blocks; within each group sort by latest update (endedAt descending)
    return blocks.sort((a, b) => {
        if (a.isActive !== b.isActive) {
            return a.isActive ? -1 : 1
        }
        return b.endedAt.localeCompare(a.endedAt)
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

export function buildGitHubIssueDraft(options: {
    block?: LogAttemptBlock | null
    rawLogsText?: string
    startupLogs?: LogEntry[]
    mode?: 'runtime' | 'startup'
    scrubPii?: boolean
    redactStoryUrls?: boolean
}): GitHubIssueDraft {
    const {
        block,
        rawLogsText,
        startupLogs = [],
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
