import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
    DashboardSnapshot,
    AddUrlResult,
    addUrls,
    retryNow,
    retryAllWaiting,
    cancelRetry,
    cancelDownload,
    cancelAllInFlight,
    redownloadScratch,
    checkEmails,
    clearErrors,
    getStoryAttemptBlock,
    toggleSiteDisabled,
} from '../api'
import { statusBadgeClass, getSiteBadgeInfo } from '../statusColors'
import AttemptBlockCard from '../components/AttemptBlockCard'
import {
    parseAndValidateUrlLines,
    filterRemainingInputAfterSubmit,
    aggregateRecentErrors,
    ensureExternalUrl,
    AggregatedErrorRecord,
} from '../utils/dashboardLogic'
import {
    Download,
    RefreshCw,
    XCircle,
    AlertTriangle,
    Clock,
    CheckCircle2,
    Activity,
    Layers,
    ExternalLink,
    BookOpen,
    Globe,
    Mail,
    RotateCcw,
    ClipboardPaste,
    Copy,
    Check,
    Terminal,
    Trash2,
    X,
    Search,
} from 'lucide-react'

interface Props {
    data: DashboardSnapshot | null
}

interface RecentDownloadItem {
    url: string
    site?: string
    title?: string
    status?: string
    calibre_id?: string
    completed_at?: string
    timestamp?: string
    error_message?: string
}

interface InFlightItem {
    url: string
    site?: string
    title?: string
    calibre_id?: string
    stage: 'processing' | 'queued' | 'waiting'
    started_at?: string
    updated_at?: string
    scheduled_at?: string
    attempt_number?: number
    action?: string
    delay_minutes?: number
    error_message?: string
}

function SiteBadge({ site }: { site?: string }) {
    const info = getSiteBadgeInfo(site)
    return (
        <span className="site-badge" style={{ color: 'var(--text)' }}>
            <span className="site-dot" style={{ background: info.color }} />
            <span>{info.name}</span>
        </span>
    )
}

function StoryUrlLink({ url }: { url: string }) {
    return (
        <a
            href={ensureExternalUrl(url)}
            target="_blank"
            rel="noopener noreferrer"
            className="story-url-link"
            title={`Open ${url} in new tab`}
        >
            <span>{url}</span>
            <ExternalLink size={11} style={{ flexShrink: 0 }} />
        </a>
    )
}

function CalibreIdBadge({
    calibreId,
    serverUrl,
}: {
    calibreId?: string | null
    serverUrl?: string | null
}) {
    if (!calibreId) {
        return <span style={{ color: 'var(--text-faint)' }}>—</span>
    }
    if (serverUrl) {
        const base = serverUrl.replace(/\/$/, '')
        const href = base.includes('#') ? `${base}&book_id=${calibreId}` : `${base}/#book_id=${calibreId}`
        return (
            <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="tabular-nums"
                style={{
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--success)',
                    fontWeight: 600,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                }}
                title={`Open Calibre Book #${calibreId} in Content Server`}
            >
                <span>#{calibreId}</span>
                <ExternalLink size={11} />
            </a>
        )
    }
    return (
        <span
            className="tabular-nums"
            style={{
                fontFamily: 'var(--font-mono)',
                color: 'var(--success)',
                fontWeight: 600,
            }}
        >
            #{calibreId}
        </span>
    )
}

function formatRelativeAndDate(iso: string | undefined | null, now: number): string {
    if (!iso) return '—'
    const d = new Date(iso)
    const ms = d.getTime()
    if (isNaN(ms)) return iso

    const diffSec = Math.max(0, Math.floor((now - ms) / 1000))
    let rel = ''
    if (diffSec < 60) rel = `${diffSec}s ago`
    else if (diffSec < 3600) rel = `${Math.floor(diffSec / 60)}m ago`
    else if (diffSec < 86400) rel = `${Math.floor(diffSec / 3600)}h ago`
    else rel = `${Math.floor(diffSec / 86400)}d ago`

    const shortDate = d.toLocaleString([], {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    })
    return `${rel} · ${shortDate}`
}

function formatElapsed(iso: string | undefined, now: number): string {
    if (!iso) return 'active'
    const start = new Date(iso).getTime()
    if (isNaN(start)) return 'active'
    const diff = Math.max(0, Math.floor((now - start) / 1000))
    if (diff < 60) return `${diff}s`
    const m = Math.floor(diff / 60)
    const s = diff % 60
    return `${m}m ${s}s`
}

function formatCountdown(scheduledIso: string | undefined, now: number): string {
    if (!scheduledIso) return 'Scheduled backoff'
    const target = new Date(scheduledIso).getTime()
    if (isNaN(target)) return 'Scheduled backoff'
    const remSec = Math.max(0, Math.ceil((target - now) / 1000))
    const timeStr = new Date(target).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    if (remSec <= 0) return `Firing now (${timeStr})`
    if (remSec < 60) return `In ${remSec}s (${timeStr})`
    const m = Math.floor(remSec / 60)
    const s = remSec % 60
    if (m < 60) return `In ${m}m ${String(s).padStart(2, '0')}s (${timeStr})`
    const h = Math.floor(m / 60)
    const remM = m % 60
    return `In ${h}h ${remM}m (${timeStr})`
}

function summarizeError(err?: string | null): string {
    if (!err) return ''
    const firstLine = err.split('\n')[0].trim()
    return firstLine.length > 120 ? firstLine.slice(0, 117) + '…' : firstLine
}

export default function Dashboard({ data }: Props) {
    const navigate = useNavigate()
    const [urlInput, setUrlInput] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [checkingEmail, setCheckingEmail] = useState(false)
    const [feedback, setFeedback] = useState<{
        text: string
        ok: boolean
        details?: AddUrlResult[]
    } | null>(null)
    const [actionNotice, setActionNotice] = useState<string | null>(null)
    const [now, setNow] = useState(() => Date.now())
    const [selectedError, setSelectedError] = useState<AggregatedErrorRecord | null>(null)
    const [showAllErrorsModal, setShowAllErrorsModal] = useState(false)
    const [copiedTrace, setCopiedTrace] = useState(false)
    const [confirmScratchUrl, setConfirmScratchUrl] = useState<string | null>(null)
    const [confirmCancelAll, setConfirmCancelAll] = useState(false)
    const [updateMethodOverride, setUpdateMethodOverride] = useState<string>('')
    const [expandAllPreviews, setExpandAllPreviews] = useState(false)
    const [showWorkerPoolModal, setShowWorkerPoolModal] = useState(false)
    const [workerSearch, setWorkerSearch] = useState('')
    const [localDismissedUrls, setLocalDismissedUrls] = useState<Set<string>>(() => {
        try {
            const stored = localStorage.getItem('aff_dismissed_error_urls')
            return stored ? new Set(JSON.parse(stored)) : new Set()
        } catch {
            return new Set()
        }
    })

    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(id)
    }, [])

    const activeItems = data?.active_downloads?.items || []
    const queuedItems = data?.queued_downloads?.items || []
    const waitingItems = data?.waiting_downloads?.items || []
    const disabledSites = data?.disabled_sites || []

    const inFlightUrlSet = useMemo(() => {
        const s = new Set<string>()
        for (const a of activeItems) s.add(a.url)
        for (const q of queuedItems) s.add(q.url)
        for (const w of waitingItems) s.add(w.url)
        return s
    }, [activeItems, queuedItems, waitingItems])

    const parsedPreviews = useMemo(
        () => parseAndValidateUrlLines(urlInput, disabledSites, inFlightUrlSet),
        [urlInput, disabledSites, inFlightUrlSet]
    )

    if (!data) {
        return (
            <div className="card">
                <h2>Loading dashboard…</h2>
            </div>
        )
    }

    const showBriefNotice = (msg: string) => {
        setActionNotice(msg)
        setTimeout(() => {
            setActionNotice((prev) => (prev === msg ? null : prev))
        }, 3500)
    }

    const removePreviewUrl = (rawToRemove: string) => {
        const remaining = urlInput
            .split(/[\r\n]+/)
            .filter((line) => line.trim() !== rawToRemove)
            .join('\n')
        setUrlInput(remaining)
    }

    const removeWarningUrls = () => {
        const warningRaws = new Set(
            parsedPreviews
                .filter((p) => !p.isValid || p.isDisabledSite || p.isDuplicateInFlight)
                .map((p) => p.raw)
        )
        const remaining = urlInput
            .split(/[\r\n]+/)
            .filter((line) => !warningRaws.has(line.trim()))
            .join('\n')
        setUrlInput(remaining)
    }

    const submitUrls = async () => {
        const urls = urlInput
            .split(/[\r\n\s,]+/)
            .map((s) => s.trim())
            .filter(Boolean)
        if (urls.length === 0 || submitting) return

        setSubmitting(true)
        setFeedback(null)
        try {
            const res = await addUrls(urls, updateMethodOverride || undefined)
            const acceptedCount = res.results.filter((r) => r.accepted).length
            const rejectedList = res.results.filter((r) => !r.accepted)
            const remainingText = filterRemainingInputAfterSubmit(urls, res.results)

            setUrlInput(remainingText)

            if (urls.length === 1) {
                setFeedback({
                    text: res.results[0]?.message || 'Processed URL',
                    ok: acceptedCount > 0,
                })
            } else {
                setFeedback({
                    text:
                        rejectedList.length === 0
                            ? `Added all ${acceptedCount} story URLs to download queue`
                            : `Added ${acceptedCount} of ${urls.length} URLs (${rejectedList.length} rejected — kept in input above so you can review)`,
                    ok: acceptedCount > 0 && rejectedList.length === 0,
                    details: rejectedList.length > 0 ? rejectedList : undefined,
                })
            }
        } catch (err: unknown) {
            setFeedback({
                text: err instanceof Error ? err.message : 'Failed to enqueue URLs',
                ok: false,
            })
        } finally {
            setSubmitting(false)
        }
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        await submitUrls()
    }

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault()
            submitUrls()
        }
    }

    const handlePasteClipboard = async () => {
        try {
            const clip = await navigator.clipboard.readText()
            if (clip && clip.trim()) {
                setUrlInput((prev) => (prev.trim() ? `${prev.trim()}\n${clip.trim()}` : clip.trim()))
            }
        } catch {
            // Clipboard permission denied or unsupported
        }
    }

    const handleCheckEmails = async () => {
        setCheckingEmail(true)
        setFeedback(null)
        try {
            const res = await checkEmails()
            setFeedback({ text: res.message, ok: res.ok })
        } catch (err: unknown) {
            setFeedback({
                text: err instanceof Error ? err.message : 'Failed to check email inbox',
                ok: false,
            })
        } finally {
            setCheckingEmail(false)
        }
    }

    const handleCopyTraceback = (text: string) => {
        navigator.clipboard?.writeText(text)
        setCopiedTrace(true)
        setTimeout(() => setCopiedTrace(false), 2000)
    }

    const handleJumpToLogs = (site?: string, url?: string) => {
        const params = new URLSearchParams()
        params.set('view', 'blocks')
        if (url) {
            params.set('block', url)
        } else if (site) {
            params.set('site', getSiteBadgeInfo(site).key)
        }
        navigate(`/logs?${params.toString()}`)
    }

    const inFlight: InFlightItem[] = [
        ...activeItems.map((a) => ({
            url: a.url,
            site: a.site,
            title: a.title,
            stage: 'processing' as const,
            started_at: a.started_at,
        })),
        ...queuedItems.map((q) => ({
            url: q.url,
            site: q.site,
            title: q.title,
            stage: 'queued' as const,
            started_at: q.started_at,
        })),
        ...waitingItems.map((w) => ({
            url: w.url,
            site: w.site,
            title: w.title,
            calibre_id: w.calibre_id,
            stage: 'waiting' as const,
            updated_at: w.updated_at,
            scheduled_at: w.scheduled_at,
            attempt_number: w.attempt_number,
            action: w.action,
            delay_minutes: w.delay_minutes,
            error_message: w.error_message,
        })),
    ]

    const recentDownloads = (data.recent_downloads || []) as RecentDownloadItem[]
    const cutoff24h = now - 24 * 60 * 60 * 1000

    const isWithin24h = (iso?: string | null) => {
        if (!iso) return true
        const t = new Date(iso).getTime()
        return !isNaN(t) && t >= cutoff24h
    }

    const recentSuccessCount = recentDownloads.filter(
        (d) => d.status === 'success' && isWithin24h(d.completed_at || d.timestamp)
    ).length

    const dismissedErrorUrls = useMemo(() => {
        const combined = new Set(data.dismissed_error_urls || [])
        for (const u of localDismissedUrls) {
            combined.add(u)
        }
        return combined
    }, [data.dismissed_error_urls, localDismissedUrls])

    const uniqueErrors = aggregateRecentErrors(waitingItems, recentDownloads, now).filter(
        (e) => !dismissedErrorUrls.has(e.url)
    )
    const totalErrorOccurrences = uniqueErrors.reduce((sum, e) => sum + e.occurrences, 0)

    const handleClearAllErrors = () => {
        const toDismiss = new Set(localDismissedUrls)
        for (const e of uniqueErrors) {
            toDismiss.add(e.url)
        }
        setLocalDismissedUrls(toDismiss)
        try {
            localStorage.setItem('aff_dismissed_error_urls', JSON.stringify(Array.from(toDismiss)))
        } catch {
            // ignore
        }
        clearErrors()
        showBriefNotice('Cleared 24h error alerts')
    }

    const handleDismissSingleError = (url: string) => {
        const toDismiss = new Set(localDismissedUrls)
        toDismiss.add(url)
        setLocalDismissedUrls(toDismiss)
        try {
            localStorage.setItem('aff_dismissed_error_urls', JSON.stringify(Array.from(toDismiss)))
        } catch {
            // ignore
        }
        clearErrors(url)
    }

    const siteQueues = data.queues?.sites || {}
    const siteQueueEntries = Object.entries(siteQueues).filter(([, c]) => c > 0)
    const lastEmail = data.last_email_check
    const maxNormalRetries = data.max_normal_retries ?? 11
    const latestLogByUrl = data.latest_log_by_url || {}
    const activeThreads = data.site_worker_stats?.active_threads ?? activeItems.length
    const maxThreads = data.site_worker_stats?.max_threads ?? 16
    const notableSites = data.site_worker_stats?.notable_sites || []
    const catalogSites = data.site_worker_stats?.catalog_sites || []
    const warningPreviewCount = parsedPreviews.filter(
        (p) => !p.isValid || p.isDisabledSite || p.isDuplicateInFlight
    ).length

    const nextScheduledWaiting = waitingItems.find((w) => w.scheduled_at)

    return (
        <div>
            {/* Clean Page Header */}
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    marginBottom: '1rem',
                }}
            >
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                        Dashboard
                    </h1>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        Add story URLs, monitor IMAP inbox ingestion, and manage your Calibre download pipeline
                    </p>
                </div>

                {actionNotice && (
                    <div
                        className="badge badge-info"
                        style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}
                    >
                        <CheckCircle2 size={14} />
                        {actionNotice}
                    </div>
                )}
            </div>

            {/* Multi-line URL Ingestion & Email Check Card */}
            <div className="card">
                <div className="card-header" style={{ marginBottom: '0.65rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <h2>
                            <Download size={17} style={{ color: 'var(--accent)' }} />
                            Ingest Story URLs
                        </h2>
                        {lastEmail && (
                            <span
                                className="tabular-nums"
                                onClick={() => navigate('/history?tab=emails')}
                                style={{
                                    fontSize: '0.75rem',
                                    color: 'var(--text-muted)',
                                    cursor: 'pointer',
                                    textDecoration: 'underline',
                                    textDecorationColor: 'var(--border)',
                                }}
                                title={
                                    lastEmail.extracted_urls && lastEmail.extracted_urls.length > 0
                                        ? `Latest extracted: ${lastEmail.extracted_urls.map((u) => `${u.title} (${u.status})`).join(', ')} — Click to view Email Check History`
                                        : 'Click to view Email Check History'
                                }
                            >
                                Inbox checked {formatRelativeAndDate(lastEmail.checked_at, now)} ({lastEmail.trigger.toUpperCase()} · {lastEmail.urls_found} found, {lastEmail.urls_new} new)
                            </span>
                        )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="hide-on-mobile" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            One URL per line · <kbd style={{ fontFamily: 'var(--font-mono)' }}>Ctrl+Enter</kbd> to submit
                        </span>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={handlePasteClipboard}
                            title="Paste URLs from clipboard"
                        >
                            <ClipboardPaste size={13} /> Paste
                        </button>
                    </div>
                </div>

                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <textarea
                        rows={3}
                        aria-label="Story URLs to download"
                        placeholder={
                            'https://archiveofourown.org/works/54918203\nhttps://www.royalroad.com/fiction/82194/chronicles-of-ember\nhttps://forums.spacebattles.com/threads/1148920'
                        }
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.84rem',
                            lineHeight: 1.5,
                            resize: 'vertical',
                            minHeight: '78px',
                        }}
                    />

                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                            gap: '0.65rem',
                        }}
                    >
                        {parsedPreviews.length > 0 && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                <span
                                    style={{
                                        fontSize: '0.75rem',
                                        color: 'var(--text-muted)',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.3rem',
                                    }}
                                >
                                    <Globe size={13} style={{ color: 'var(--accent)' }} /> Parsed ({parsedPreviews.length}):
                                </span>
                                {(expandAllPreviews ? parsedPreviews : parsedPreviews.slice(0, 6)).map((p, idx) => {
                                    const badge = getSiteBadgeInfo(p.site)
                                    const hasWarning = !p.isValid || p.isDisabledSite || p.isDuplicateInFlight
                                    return (
                                        <span
                                            key={`${p.raw}-${idx}`}
                                            style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '0.35rem',
                                                padding: '0.18rem 0.5rem',
                                                borderRadius: 'var(--radius-sm)',
                                                background: 'var(--surface2)',
                                                border: `1px solid ${hasWarning ? 'rgba(245, 158, 11, 0.45)' : 'var(--border)'}`,
                                                fontSize: '0.74rem',
                                            }}
                                        >
                                            {p.isValid ? (
                                                <>
                                                    <span className="site-dot" style={{ background: badge.color }} />
                                                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>
                                                        {badge.name}
                                                    </span>
                                                    <span style={{ color: 'var(--text-muted)' }}>
                                                        {p.inferredTitle}
                                                    </span>
                                                </>
                                            ) : (
                                                <span style={{ color: 'var(--error)', fontWeight: 600 }}>
                                                    Invalid URL: {p.raw.slice(0, 24)}
                                                </span>
                                            )}
                                            {p.isDisabledSite && (
                                                <span style={{ color: 'var(--warning)', fontWeight: 600 }}>
                                                    (Disabled site)
                                                </span>
                                            )}
                                            {p.isDuplicateInFlight && (
                                                <span style={{ color: 'var(--info)', fontWeight: 600 }}>
                                                    (In queue)
                                                </span>
                                            )}
                                            <button
                                                type="button"
                                                onClick={() => removePreviewUrl(p.raw)}
                                                aria-label={`Remove ${p.raw}`}
                                                style={{
                                                    background: 'transparent',
                                                    border: 'none',
                                                    padding: '0 2px',
                                                    minHeight: 'auto',
                                                    color: 'var(--text-muted)',
                                                }}
                                            >
                                                <X size={12} />
                                            </button>
                                        </span>
                                    )
                                })}
                                {parsedPreviews.length > 6 && (
                                    <button
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => setExpandAllPreviews((prev) => !prev)}
                                        style={{ padding: '0.12rem 0.45rem', minHeight: 22, fontSize: '0.72rem' }}
                                    >
                                        {expandAllPreviews ? 'Show fewer' : `+${parsedPreviews.length - 6} more`}
                                    </button>
                                )}
                                {warningPreviewCount > 0 && (
                                    <button
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={removeWarningUrls}
                                        style={{
                                            padding: '0.12rem 0.5rem',
                                            minHeight: 22,
                                            fontSize: '0.72rem',
                                            borderColor: 'rgba(245, 158, 11, 0.4)',
                                            color: 'var(--warning)',
                                        }}
                                        title="Remove invalid, disabled-site, or duplicate in-flight URLs from the input box"
                                    >
                                        Remove Warnings ({warningPreviewCount})
                                    </button>
                                )}
                            </div>
                        )}

                        <div className="ingest-actions-row" style={{ marginLeft: 'auto', display: 'flex', gap: '0.55rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <select
                                aria-label="Update mode override"
                                value={updateMethodOverride}
                                onChange={(e) => setUpdateMethodOverride(e.target.value)}
                                style={{
                                    width: 'auto',
                                    minWidth: 165,
                                    background: 'var(--surface2)',
                                    fontSize: '0.79rem',
                                    padding: '0.4rem 0.65rem',
                                }}
                                title="Optional per-submission FanFicFare update mode override"
                            >
                                <option value="">Mode: Default (Config)</option>
                                <option value="update">Mode: Update (New Ch.)</option>
                                <option value="update_always">Mode: Update Always</option>
                                <option value="force">Mode: Force Overwrite</option>
                            </select>

                            <button
                                type="button"
                                className="secondary"
                                disabled={checkingEmail || submitting}
                                onClick={handleCheckEmails}
                            >
                                <Mail size={15} />
                                {checkingEmail ? 'Checking…' : 'Check Emails'}
                            </button>

                            <button type="submit" disabled={submitting || !urlInput.trim()}>
                                <Download size={15} />
                                {submitting
                                    ? 'Adding…'
                                    : parsedPreviews.length > 1
                                      ? `Download (${parsedPreviews.length})`
                                      : 'Download Stories'}
                            </button>
                        </div>
                    </div>
                </form>

                {feedback && (
                    <div
                        style={{
                            marginTop: '0.75rem',
                            paddingTop: '0.65rem',
                            borderTop: '1px solid var(--border)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.35rem',
                            fontSize: '0.82rem',
                            color: feedback.ok ? 'var(--success)' : 'var(--warning)',
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                            {feedback.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                            <span>{feedback.text}</span>
                        </div>
                        {feedback.details && feedback.details.length > 0 && (
                            <div
                                style={{
                                    paddingLeft: '1.4rem',
                                    fontSize: '0.76rem',
                                    color: '#fca5a5',
                                    fontFamily: 'var(--font-mono)',
                                }}
                            >
                                {feedback.details.map((d, i) => (
                                    <div key={i}>• {d.message}</div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Summary Row (4 Balanced KPI Cards) */}
            <div className="grid grid-4" style={{ marginBottom: '1rem' }}>
                <div className="stat-card">
                    <div className="stat-header">
                        <span>Downloading</span>
                        <Activity
                            size={15}
                            style={{ color: activeItems.length > 0 ? 'var(--warning)' : 'var(--text-muted)' }}
                        />
                    </div>
                    <div
                        className="stat-value"
                        style={{ color: activeItems.length > 0 ? 'var(--warning)' : 'var(--text)' }}
                    >
                        {activeItems.length}
                    </div>
                    <div className="stat-footer">
                        <span>{queuedItems.length} in ingress queue</span>
                        {siteQueueEntries.length > 0 && (
                            <>
                                <span>·</span>
                                <span>
                                    {siteQueueEntries.map(([s, c]) => `${getSiteBadgeInfo(s).name}: ${c}`).join(', ')}
                                </span>
                            </>
                        )}
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-header">
                        <span>Waiting Retries</span>
                        <Clock
                            size={15}
                            style={{ color: waitingItems.length > 0 ? 'var(--info)' : 'var(--text-muted)' }}
                        />
                    </div>
                    <div
                        className="stat-value"
                        style={{ color: waitingItems.length > 0 ? 'var(--info)' : 'var(--text)' }}
                    >
                        {waitingItems.length}
                    </div>
                    <div className="stat-footer">
                        <span>
                            {nextScheduledWaiting
                                ? `Next ${formatCountdown(nextScheduledWaiting.scheduled_at, now)}`
                                : 'No retries waiting'}
                        </span>
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-header">
                        <span>Completed (24h)</span>
                        <CheckCircle2 size={15} style={{ color: 'var(--success)' }} />
                    </div>
                    <div className="stat-value" style={{ color: 'var(--success)' }}>
                        {recentSuccessCount}
                    </div>
                    <div className="stat-footer">
                        <span>Synced to Calibre library</span>
                    </div>
                </div>

                <div
                    className="stat-card"
                    style={{
                        borderColor: uniqueErrors.length > 0 ? 'rgba(239, 68, 68, 0.35)' : undefined,
                    }}
                >
                    <div className="stat-header">
                        <span>Errors (24h)</span>
                        <AlertTriangle
                            size={15}
                            style={{ color: uniqueErrors.length > 0 ? 'var(--error)' : 'var(--text-muted)' }}
                        />
                    </div>
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '0.35rem',
                            flexWrap: 'wrap',
                        }}
                    >
                        <div
                            className="stat-value"
                            style={{ color: uniqueErrors.length > 0 ? 'var(--error)' : 'var(--text)' }}
                        >
                            {uniqueErrors.length}
                        </div>
                        {uniqueErrors.length > 0 && (
                            <div style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={() => setShowAllErrorsModal(true)}
                                    style={{ padding: '0.18rem 0.5rem', minHeight: 26, fontSize: '0.72rem' }}
                                    title="Inspect error attempt blocks and stack traces"
                                >
                                    Inspect ({totalErrorOccurrences}) →
                                </button>
                                <button
                                    type="button"
                                    className="danger btn-sm"
                                    onClick={() => {
                                        handleClearAllErrors()
                                    }}
                                    style={{ padding: '0.18rem 0.45rem', minHeight: 26, fontSize: '0.72rem' }}
                                    title="Clear 24h error alerts"
                                >
                                    Clear
                                </button>
                            </div>
                        )}
                    </div>
                    <div className="stat-footer">
                        <span
                            style={{
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                display: 'block',
                            }}
                            title={
                                uniqueErrors.length > 0
                                    ? `Latest: ${uniqueErrors[0].title} — ${summarizeError(uniqueErrors[0].error)}`
                                    : undefined
                            }
                        >
                            {uniqueErrors.length > 0
                                ? `Latest: ${uniqueErrors[0].title} (${totalErrorOccurrences} failed attempts)`
                                : 'Zero active error alerts'}
                        </span>
                    </div>
                </div>
            </div>

            {/* Active & Waiting Queue */}
            <div style={{ marginBottom: '1.5rem' }}>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: '0.65rem',
                        marginBottom: '0.65rem',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
                        <h2
                            style={{
                                fontSize: '1.02rem',
                                fontWeight: 600,
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}
                        >
                            <Layers size={17} style={{ color: 'var(--accent)' }} />
                            Active & Waiting Downloads ({inFlight.length})
                        </h2>

                        {/* Scalable Dynamic Site Worker Strip (Only shows active/backoff/disabled sites + 128-adapter modal trigger) */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                            {notableSites.slice(0, 6).map((sw) => {
                                const info = getSiteBadgeInfo(sw.site)
                                const statusColor =
                                    sw.status === 'downloading'
                                        ? 'var(--warning)'
                                        : sw.status === 'queued'
                                          ? 'var(--accent)'
                                          : sw.status === 'backoff'
                                            ? 'var(--info)'
                                            : 'var(--error)'
                                const label =
                                    sw.status === 'downloading'
                                        ? 'downloading'
                                        : sw.status === 'queued'
                                          ? `${sw.queued_count} queued`
                                          : sw.status === 'backoff'
                                            ? `retry #${sw.attempt_number || 1}`
                                            : 'disabled'
                                return (
                                    <button
                                        key={sw.site}
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => navigate(`/history?site=${encodeURIComponent(sw.site)}`)}
                                        style={{
                                            padding: '0.14rem 0.5rem',
                                            minHeight: 24,
                                            fontSize: '0.72rem',
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.35rem',
                                        }}
                                        title={`${info.name} worker (${label}) — Click to view site history`}
                                    >
                                        <span className="site-dot" style={{ background: info.color }} />
                                        <span style={{ fontWeight: 600 }}>{info.name}</span>
                                        <span style={{ color: statusColor, fontFamily: 'var(--font-mono)', fontSize: '0.69rem' }}>
                                            {label}
                                        </span>
                                    </button>
                                )
                            })}
                            <button
                                type="button"
                                className="secondary btn-sm"
                                onClick={() => setShowWorkerPoolModal(true)}
                                style={{
                                    padding: '0.14rem 0.55rem',
                                    minHeight: 24,
                                    fontSize: '0.72rem',
                                    fontFamily: 'var(--font-mono)',
                                }}
                                title={`Worker pool concurrency is bounded by system CPU threads (${activeThreads} active of ${maxThreads} system threads, ${notableSites.length} active/backoff/disabled site lanes)`}
                            >
                                <Globe size={12} /> Worker Pool ({activeThreads} / {maxThreads} threads)
                            </button>
                        </div>
                    </div>

                    {inFlight.length > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                            {waitingItems.length > 0 && (
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={async () => {
                                        const res = await retryAllWaiting()
                                        showBriefNotice(res.message)
                                    }}
                                >
                                    <RefreshCw size={13} /> Retry All Waiting ({waitingItems.length})
                                </button>
                            )}
                            {confirmCancelAll ? (
                                <>
                                    <button
                                        type="button"
                                        className="danger btn-sm"
                                        onClick={async () => {
                                            const res = await cancelAllInFlight()
                                            setConfirmCancelAll(false)
                                            showBriefNotice(res.message)
                                        }}
                                    >
                                        Confirm Cancel All ({inFlight.length})
                                    </button>
                                    <button
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => setConfirmCancelAll(false)}
                                    >
                                        Keep
                                    </button>
                                </>
                            ) : (
                                <button
                                    type="button"
                                    className="danger btn-sm"
                                    onClick={() => setConfirmCancelAll(true)}
                                >
                                    <XCircle size={13} /> Cancel All ({inFlight.length})
                                </button>
                            )}
                        </div>
                    )}
                </div>

                {inFlight.length === 0 ? (
                    <div
                        style={{
                            padding: '0.9rem 1.15rem',
                            borderRadius: 'var(--radius-md)',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.65rem',
                        }}
                    >
                        <CheckCircle2 size={18} style={{ color: 'var(--success)' }} />
                        <span style={{ fontSize: '0.86rem', color: 'var(--text-muted)' }}>
                            No downloads currently in progress or waiting to retry.
                        </span>
                    </div>
                ) : (
                    <>
                        <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                            <table>
                                <thead>
                                    <tr>
                                        <th>Story</th>
                                        <th>Site</th>
                                        <th>Stage / Attempt</th>
                                        <th>Backoff / Progress</th>
                                        <th style={{ textAlign: 'right' }}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {inFlight.map((item) => {
                                        const isConfirmingScratch = confirmScratchUrl === `inflight:${item.url}`
                                        return (
                                            <tr key={`${item.stage}-${item.url}`}>
                                                <td>
                                                    <div style={{ fontWeight: 600 }}>
                                                        <a
                                                            href={ensureExternalUrl(item.url)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            style={{ color: 'var(--text)' }}
                                                        >
                                                            {item.title || 'Fetching story metadata…'}
                                                        </a>
                                                    </div>
                                                    <StoryUrlLink url={item.url} />
                                                </td>
                                                <td>
                                                    <SiteBadge site={item.site} />
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', alignItems: 'flex-start' }}>
                                                        <span className={statusBadgeClass(item.stage)}>
                                                            {item.stage === 'waiting'
                                                                ? item.action === 'hail_mary'
                                                                    ? `Hail-Mary #${item.attempt_number || maxNormalRetries}`
                                                                    : `Retry #${item.attempt_number || 1} / ${maxNormalRetries}`
                                                                : item.stage}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td>
                                                    {item.stage === 'processing' && (
                                                        <div
                                                            style={{
                                                                display: 'flex',
                                                                flexDirection: 'column',
                                                                gap: '0.35rem',
                                                            }}
                                                        >
                                                            <div
                                                                style={{
                                                                    display: 'flex',
                                                                    justifyContent: 'space-between',
                                                                    fontSize: '0.75rem',
                                                                    maxWidth: 180,
                                                                }}
                                                            >
                                                                <span style={{ color: 'var(--warning)' }}>
                                                                    Downloading…
                                                                </span>
                                                                <span
                                                                    className="tabular-nums"
                                                                    style={{
                                                                        color: 'var(--text-muted)',
                                                                        fontFamily: 'var(--font-mono)',
                                                                    }}
                                                                >
                                                                    {formatElapsed(item.started_at, now)}
                                                                </span>
                                                            </div>
                                                            <div className="indeterminate-bar" />
                                                            {latestLogByUrl[item.url]?.message && (
                                                                <div
                                                                    style={{
                                                                        fontSize: '0.71rem',
                                                                        fontFamily: 'var(--font-mono)',
                                                                        color: 'var(--text-muted)',
                                                                        maxWidth: 310,
                                                                        whiteSpace: 'nowrap',
                                                                        overflow: 'hidden',
                                                                        textOverflow: 'ellipsis',
                                                                    }}
                                                                    title={latestLogByUrl[item.url].message}
                                                                >
                                                                    {latestLogByUrl[item.url].message}
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                    {item.stage === 'queued' && (
                                                        <span
                                                            style={{
                                                                fontSize: '0.8rem',
                                                                color: 'var(--text-muted)',
                                                            }}
                                                        >
                                                            Queued — waiting for {getSiteBadgeInfo(item.site).name} worker
                                                        </span>
                                                    )}
                                                    {item.stage === 'waiting' && (
                                                        <div style={{ maxWidth: 360, display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                                                            <div
                                                                style={{
                                                                    display: 'flex',
                                                                    alignItems: 'center',
                                                                    gap: '0.4rem',
                                                                    flexWrap: 'nowrap',
                                                                }}
                                                            >
                                                                <span
                                                                    className="tabular-nums"
                                                                    style={{
                                                                        fontSize: '0.77rem',
                                                                        fontFamily: 'var(--font-mono)',
                                                                        color: 'var(--info)',
                                                                        fontWeight: 600,
                                                                        whiteSpace: 'nowrap',
                                                                    }}
                                                                >
                                                                    {formatCountdown(item.scheduled_at, now)}
                                                                </span>
                                                                {item.error_message && (
                                                                    <div style={{ display: 'inline-flex', gap: '0.25rem', flexShrink: 0 }}>
                                                                        <button
                                                                            type="button"
                                                                            className="secondary btn-sm"
                                                                            style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                                            onClick={() => handleJumpToLogs(item.site, item.url)}
                                                                            title="Jump directly to this attempt's block in the Logs page"
                                                                        >
                                                                            <Terminal size={10} /> Log Block
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            className="secondary btn-sm"
                                                                            style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                                            onClick={() =>
                                                                                setSelectedError({
                                                                                    title: item.title || item.url,
                                                                                    url: item.url,
                                                                                    site: item.site,
                                                                                    calibre_id: item.calibre_id,
                                                                                    status: 'waiting',
                                                                                    error: item.error_message!,
                                                                                    occurrences: item.attempt_number || 1,
                                                                                    attempt_number: item.attempt_number,
                                                                                })
                                                                            }
                                                                            title="Inspect attempt execution block and stack trace"
                                                                        >
                                                                            <AlertTriangle size={10} /> Trace
                                                                        </button>
                                                                    </div>
                                                                )}
                                                            </div>
                                                            {item.error_message && (
                                                                <div
                                                                    onClick={() =>
                                                                        setSelectedError({
                                                                            title: item.title || item.url,
                                                                            url: item.url,
                                                                            site: item.site,
                                                                            calibre_id: item.calibre_id,
                                                                            status: 'waiting',
                                                                            error: item.error_message!,
                                                                            occurrences: item.attempt_number || 1,
                                                                            attempt_number: item.attempt_number,
                                                                        })
                                                                    }
                                                                    title={`${summarizeError(item.error_message)} — Click to view stack trace`}
                                                                    style={{
                                                                        fontSize: '0.73rem',
                                                                        color: '#fca5a5',
                                                                        whiteSpace: 'nowrap',
                                                                        overflow: 'hidden',
                                                                        textOverflow: 'ellipsis',
                                                                        maxWidth: 340,
                                                                        cursor: 'pointer',
                                                                    }}
                                                                >
                                                                    {summarizeError(item.error_message)}
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </td>
                                                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                                    <div
                                                        style={{
                                                            display: 'inline-flex',
                                                            gap: '0.35rem',
                                                            flexWrap: 'nowrap',
                                                            justifyContent: 'flex-end',
                                                        }}
                                                    >
                                                        {item.stage === 'waiting' ? (
                                                            <>
                                                                <button
                                                                    type="button"
                                                                    className="btn-sm"
                                                                    onClick={() => {
                                                                        retryNow({
                                                                            url: item.url,
                                                                            site: item.site,
                                                                            title: item.title,
                                                                            calibre_id: item.calibre_id,
                                                                        })
                                                                        showBriefNotice(
                                                                            `Retrying ${item.title || item.url}`
                                                                        )
                                                                    }}
                                                                    title="Fire the scheduled retry immediately"
                                                                >
                                                                    <RefreshCw size={13} /> Retry Now
                                                                </button>
                                                                {isConfirmingScratch ? (
                                                                    <>
                                                                        <button
                                                                            type="button"
                                                                            className="danger btn-sm"
                                                                            onClick={() => {
                                                                                setConfirmScratchUrl(null)
                                                                                redownloadScratch({
                                                                                    url: item.url,
                                                                                    site: item.site,
                                                                                    title: item.title,
                                                                                    calibre_id: item.calibre_id,
                                                                                })
                                                                                showBriefNotice(
                                                                                    `Queued full overwrite from Ch. 1 for ${item.title || item.url}`
                                                                                )
                                                                            }}
                                                                        >
                                                                            Confirm Ch.1 Overwrite
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            className="secondary btn-sm"
                                                                            onClick={() => setConfirmScratchUrl(null)}
                                                                        >
                                                                            Cancel
                                                                        </button>
                                                                    </>
                                                                ) : (
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        onClick={() =>
                                                                            setConfirmScratchUrl(`inflight:${item.url}`)
                                                                        }
                                                                        title="Re-download all chapters from Chapter 1 and overwrite existing EPUB in Calibre"
                                                                    >
                                                                        <RotateCcw size={13} /> From Scratch
                                                                    </button>
                                                                )}
                                                                <button
                                                                    type="button"
                                                                    className="danger btn-sm"
                                                                    onClick={() =>
                                                                        cancelRetry({
                                                                            url: item.url,
                                                                            site: item.site,
                                                                            title: item.title,
                                                                        })
                                                                    }
                                                                >
                                                                    <XCircle size={13} /> Cancel
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                className="danger btn-sm"
                                                                onClick={() =>
                                                                    cancelDownload({
                                                                        url: item.url,
                                                                        site: item.site,
                                                                        title: item.title,
                                                                    })
                                                                }
                                                            >
                                                                <XCircle size={13} /> Cancel
                                                            </button>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {/* Mobile Card List */}
                        <div className="mobile-card-list">
                            {inFlight.map((item) => (
                                <div key={`mob-${item.stage}-${item.url}`} className="mobile-data-card">
                                    <div className="mobile-data-card-header">
                                        <div style={{ minWidth: 0, flex: 1 }}>
                                            <div style={{ fontWeight: 600 }}>
                                                <a
                                                    href={ensureExternalUrl(item.url)}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{ color: 'var(--text)' }}
                                                >
                                                    {item.title || 'Fetching story metadata…'}
                                                </a>
                                            </div>
                                            <StoryUrlLink url={item.url} />
                                        </div>
                                        <span className={statusBadgeClass(item.stage)}>
                                            {item.stage === 'waiting'
                                                ? item.action === 'hail_mary'
                                                    ? `Hail-Mary #${item.attempt_number || maxNormalRetries}`
                                                    : `Retry #${item.attempt_number || 1} / ${maxNormalRetries}`
                                                : item.stage}
                                        </span>
                                    </div>

                                    {item.stage === 'waiting' && (
                                        <div
                                            className="tabular-nums"
                                            style={{
                                                fontSize: '0.76rem',
                                                fontFamily: 'var(--font-mono)',
                                                color: 'var(--info)',
                                            }}
                                        >
                                            {formatCountdown(item.scheduled_at, now)}
                                        </div>
                                    )}

                                    {item.error_message && (
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'space-between',
                                                gap: '0.4rem',
                                                padding: '0.28rem 0.5rem',
                                                borderRadius: 'var(--radius-sm)',
                                                background: 'rgba(239, 68, 68, 0.08)',
                                                border: '1px solid rgba(239, 68, 68, 0.22)',
                                            }}
                                        >
                                            <span
                                                style={{
                                                    fontSize: '0.74rem',
                                                    color: '#fca5a5',
                                                    whiteSpace: 'nowrap',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    flex: 1,
                                                    minWidth: 0,
                                                }}
                                            >
                                                {summarizeError(item.error_message)}
                                            </span>
                                            <div style={{ display: 'inline-flex', gap: '0.25rem', flexShrink: 0 }}>
                                                <button
                                                    type="button"
                                                    className="secondary btn-sm"
                                                    style={{ padding: '0.12rem 0.42rem', minHeight: 22, fontSize: '0.7rem' }}
                                                    onClick={() => handleJumpToLogs(item.site, item.url)}
                                                >
                                                    <Terminal size={11} /> Log Block
                                                </button>
                                                <button
                                                    type="button"
                                                    className="secondary btn-sm"
                                                    style={{ padding: '0.12rem 0.42rem', minHeight: 22, fontSize: '0.7rem' }}
                                                    onClick={() =>
                                                        setSelectedError({
                                                            title: item.title || item.url,
                                                            url: item.url,
                                                            site: item.site,
                                                            calibre_id: item.calibre_id,
                                                            status: 'waiting',
                                                            error: item.error_message!,
                                                            occurrences: item.attempt_number || 1,
                                                            attempt_number: item.attempt_number,
                                                        })
                                                    }
                                                >
                                                    <AlertTriangle size={11} /> Trace
                                                </button>
                                            </div>
                                        </div>
                                    )}

                                    <div
                                        style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                        }}
                                    >
                                        <SiteBadge site={item.site} />
                                        {item.stage === 'processing' && <div className="indeterminate-bar" />}
                                    </div>

                                    <div className="mobile-data-card-actions">
                                        {item.stage === 'waiting' ? (
                                            <>
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        retryNow({
                                                            url: item.url,
                                                            site: item.site,
                                                            title: item.title,
                                                            calibre_id: item.calibre_id,
                                                        })
                                                    }
                                                >
                                                    <RefreshCw size={14} /> Retry Now
                                                </button>
                                                {confirmScratchUrl === `mob-inflight:${item.url}` ? (
                                                    <>
                                                        <button
                                                            type="button"
                                                            className="danger"
                                                            onClick={() => {
                                                                setConfirmScratchUrl(null)
                                                                redownloadScratch({
                                                                    url: item.url,
                                                                    site: item.site,
                                                                    title: item.title,
                                                                    calibre_id: item.calibre_id,
                                                                })
                                                            }}
                                                        >
                                                            Confirm Overwrite
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="secondary"
                                                            onClick={() => setConfirmScratchUrl(null)}
                                                        >
                                                            Cancel
                                                        </button>
                                                    </>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        className="secondary"
                                                        onClick={() => setConfirmScratchUrl(`mob-inflight:${item.url}`)}
                                                    >
                                                        <RotateCcw size={14} /> From Scratch
                                                    </button>
                                                )}
                                                <button
                                                    type="button"
                                                    className="danger"
                                                    onClick={() =>
                                                        cancelRetry({
                                                            url: item.url,
                                                            site: item.site,
                                                            title: item.title,
                                                        })
                                                    }
                                                >
                                                    <XCircle size={14} /> Cancel
                                                </button>
                                            </>
                                        ) : (
                                            <button
                                                type="button"
                                                className="danger"
                                                onClick={() =>
                                                    cancelDownload({
                                                        url: item.url,
                                                        site: item.site,
                                                        title: item.title,
                                                    })
                                                }
                                            >
                                                <XCircle size={14} /> Cancel Download
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </>
                )}
            </div>

            {/* Recent Story Outcomes */}
            <div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '0.65rem',
                    }}
                >
                    <h2
                        style={{
                            fontSize: '1.02rem',
                            fontWeight: 600,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}
                    >
                        <BookOpen size={17} style={{ color: 'var(--accent)' }} />
                        Recent Story Outcomes
                    </h2>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        Latest {recentDownloads.length} stories
                    </span>
                </div>

                <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                    <table>
                        <thead>
                            <tr>
                                <th>Story</th>
                                <th>Site</th>
                                <th>Status</th>
                                <th>Calibre ID</th>
                                <th>Completed</th>
                                <th style={{ textAlign: 'right' }}>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {recentDownloads.map((dl, idx) => {
                                const isConfirmingScratch = confirmScratchUrl === `recent:${dl.url}-${idx}`
                                return (
                                    <tr key={`${dl.url}-${idx}`}>
                                        <td style={{ maxWidth: 320 }}>
                                            <div style={{ fontWeight: 600 }}>
                                                <a
                                                    href={ensureExternalUrl(dl.url)}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{ color: 'var(--text)' }}
                                                >
                                                    {dl.title || 'Untitled Story'}
                                                </a>
                                            </div>
                                            <StoryUrlLink url={dl.url} />
                                        </td>
                                        <td>
                                            <SiteBadge site={dl.site} />
                                        </td>
                                        <td style={{ maxWidth: 250 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'nowrap' }}>
                                                <span className={statusBadgeClass(dl.status)}>
                                                    {dl.status || 'unknown'}
                                                </span>
                                                {dl.error_message && (
                                                    <div style={{ display: 'inline-flex', gap: '0.25rem', flexShrink: 0 }}>
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                            onClick={() => handleJumpToLogs(dl.site, dl.url)}
                                                            title="Jump directly to this attempt's block in the Logs page"
                                                        >
                                                            <Terminal size={10} /> Log Block
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                            onClick={() =>
                                                                setSelectedError({
                                                                    title: dl.title || dl.url,
                                                                    url: dl.url,
                                                                    site: dl.site,
                                                                    calibre_id: dl.calibre_id,
                                                                    status: dl.status || 'failed',
                                                                    error: dl.error_message!,
                                                                    occurrences: 1,
                                                                })
                                                            }
                                                            title="Inspect attempt execution block and stack trace"
                                                        >
                                                            <AlertTriangle size={10} /> Trace
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                            {dl.error_message && (
                                                <div
                                                    onClick={() =>
                                                        setSelectedError({
                                                            title: dl.title || dl.url,
                                                            url: dl.url,
                                                            site: dl.site,
                                                            calibre_id: dl.calibre_id,
                                                            status: dl.status || 'failed',
                                                            error: dl.error_message!,
                                                            occurrences: 1,
                                                        })
                                                    }
                                                    title={`${summarizeError(dl.error_message)} — Click to view stack trace`}
                                                    style={{
                                                        marginTop: '0.2rem',
                                                        fontSize: '0.72rem',
                                                        color: '#fca5a5',
                                                        whiteSpace: 'nowrap',
                                                        overflow: 'hidden',
                                                        textOverflow: 'ellipsis',
                                                        maxWidth: 235,
                                                        cursor: 'pointer',
                                                    }}
                                                >
                                                    {summarizeError(dl.error_message)}
                                                </div>
                                            )}
                                        </td>
                                        <td>
                                            <CalibreIdBadge
                                                calibreId={dl.calibre_id}
                                                serverUrl={data.calibre_server_url}
                                            />
                                        </td>
                                        <td
                                            className="tabular-nums"
                                            style={{
                                                fontSize: '0.77rem',
                                                color: 'var(--text-muted)',
                                                fontFamily: 'var(--font-mono)',
                                                whiteSpace: 'nowrap',
                                            }}
                                            title={dl.completed_at || dl.timestamp || ''}
                                        >
                                            {formatRelativeAndDate(dl.completed_at || dl.timestamp, now)}
                                        </td>
                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                            <div
                                                style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.4rem',
                                                    justifyContent: 'flex-end',
                                                }}
                                            >
                                                {inFlightUrlSet.has(dl.url) ? (
                                                    <span
                                                        className="badge badge-info"
                                                        title="This story is currently active or waiting in the retry queue"
                                                    >
                                                        In Queue
                                                    </span>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        className="secondary btn-sm"
                                                        onClick={() => {
                                                            addUrls([dl.url])
                                                            showBriefNotice(
                                                                `Queued ${!dl.calibre_id && dl.status !== 'success' ? 'retry' : 'chapter update'} for ${dl.title || dl.url}`
                                                            )
                                                        }}
                                                        title={
                                                            !dl.calibre_id && dl.status !== 'success'
                                                                ? 'Retry downloading this story'
                                                                : 'Fetch only new chapters and append to existing EPUB in Calibre'
                                                        }
                                                    >
                                                        <RefreshCw size={12} />{' '}
                                                        {!dl.calibre_id && dl.status !== 'success' ? 'Retry' : 'Update'}
                                                    </button>
                                                )}
                                                {isConfirmingScratch ? (
                                                    <>
                                                        <button
                                                            type="button"
                                                            className="danger btn-sm"
                                                            onClick={() => {
                                                                setConfirmScratchUrl(null)
                                                                redownloadScratch({
                                                                    url: dl.url,
                                                                    site: dl.site,
                                                                    title: dl.title,
                                                                    calibre_id: dl.calibre_id,
                                                                })
                                                                showBriefNotice(
                                                                    `Queued full redownload from Ch. 1 for ${dl.title || dl.url}`
                                                                )
                                                            }}
                                                        >
                                                            Confirm Overwrite
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            onClick={() => setConfirmScratchUrl(null)}
                                                        >
                                                            Cancel
                                                        </button>
                                                    </>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        className="secondary btn-sm"
                                                        onClick={() =>
                                                            setConfirmScratchUrl(`recent:${dl.url}-${idx}`)
                                                        }
                                                        title="Re-download all chapters from Chapter 1 and rebuild the EPUB from scratch"
                                                    >
                                                        <RotateCcw size={12} /> From Scratch
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>

                {/* Mobile Cards for Recent Outcomes */}
                <div className="mobile-card-list">
                    {recentDownloads.map((dl, idx) => (
                        <div key={`mob-dl-${dl.url}-${idx}`} className="mobile-data-card">
                            <div className="mobile-data-card-header">
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ fontWeight: 600 }}>
                                        <a
                                            href={ensureExternalUrl(dl.url)}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            style={{ color: 'var(--text)' }}
                                        >
                                            {dl.title || 'Untitled Story'}
                                        </a>
                                    </div>
                                    <StoryUrlLink url={dl.url} />
                                </div>
                                <span className={statusBadgeClass(dl.status)}>{dl.status}</span>
                            </div>

                            {dl.error_message && (
                                <div
                                    style={{
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: 'var(--radius-sm)',
                                        background: 'rgba(239, 68, 68, 0.08)',
                                        border: '1px solid rgba(239, 68, 68, 0.22)',
                                        color: '#fca5a5',
                                        fontSize: '0.74rem',
                                        whiteSpace: 'nowrap',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                    }}
                                    title={dl.error_message}
                                >
                                    {summarizeError(dl.error_message)}
                                </div>
                            )}

                            <div
                                style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    fontSize: '0.76rem',
                                }}
                            >
                                <SiteBadge site={dl.site} />
                                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                                    {dl.calibre_id ? `#${dl.calibre_id}` : 'No ID'} ·{' '}
                                    {formatRelativeAndDate(dl.completed_at || dl.timestamp, now)}
                                </span>
                            </div>
                            <div className="mobile-data-card-actions">
                                {inFlightUrlSet.has(dl.url) ? (
                                    <span className="badge badge-info" style={{ alignSelf: 'center' }}>
                                        In Queue
                                    </span>
                                ) : (
                                    <button
                                        type="button"
                                        className="secondary"
                                        onClick={() => {
                                            addUrls([dl.url])
                                            showBriefNotice(`Queued ${!dl.calibre_id && dl.status !== 'success' ? 'retry' : 'update'} for ${dl.title || dl.url}`)
                                        }}
                                    >
                                        <RefreshCw size={14} /> {!dl.calibre_id && dl.status !== 'success' ? 'Retry' : 'Update'}
                                    </button>
                                )}
                                {confirmScratchUrl === `mob-recent:${dl.url}-${idx}` ? (
                                    <>
                                        <button
                                            type="button"
                                            className="danger"
                                            onClick={() => {
                                                setConfirmScratchUrl(null)
                                                redownloadScratch({
                                                    url: dl.url,
                                                    site: dl.site,
                                                    title: dl.title,
                                                    calibre_id: dl.calibre_id,
                                                })
                                                showBriefNotice(
                                                    `Queued fresh redownload for ${dl.title || dl.url}`
                                                )
                                            }}
                                        >
                                            Confirm Overwrite
                                        </button>
                                        <button
                                            type="button"
                                            className="secondary"
                                            onClick={() => setConfirmScratchUrl(null)}
                                        >
                                            Cancel
                                        </button>
                                    </>
                                ) : (
                                    <button
                                        type="button"
                                        className="secondary"
                                        onClick={() => setConfirmScratchUrl(`mob-recent:${dl.url}-${idx}`)}
                                    >
                                        <RotateCcw size={14} /> From Scratch
                                    </button>
                                )}
                                {dl.error_message && (
                                    <button
                                        type="button"
                                        className="danger"
                                        onClick={() =>
                                            setSelectedError({
                                                title: dl.title || dl.url,
                                                url: dl.url,
                                                site: dl.site,
                                                calibre_id: dl.calibre_id,
                                                status: dl.status || 'failed',
                                                error: dl.error_message!,
                                                occurrences: 1,
                                            })
                                        }
                                    >
                                        <AlertTriangle size={14} /> Trace
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* All Recent Errors & Alerts Modal */}
            {showAllErrorsModal && (
                <div className="modal-overlay" onClick={() => setShowAllErrorsModal(false)}>
                    <div
                        className="modal-card"
                        style={{ maxWidth: 780 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <h3>Recent Errors & Alerts ({uniqueErrors.length})</h3>
                            <button
                                type="button"
                                className="modal-close-btn"
                                aria-label="Close modal"
                                onClick={() => setShowAllErrorsModal(false)}
                            >
                                ✕
                            </button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {uniqueErrors.map((errItem) => (
                                <div
                                    key={errItem.url}
                                    style={{
                                        padding: '1rem',
                                        borderRadius: 'var(--radius-md)',
                                        background: 'var(--surface2)',
                                        border: '1px solid rgba(239, 68, 68, 0.3)',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '0.65rem',
                                    }}
                                >
                                    <div
                                        style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'flex-start',
                                            gap: '0.75rem',
                                            flexWrap: 'wrap',
                                        }}
                                    >
                                        <div style={{ minWidth: 0, flex: 1 }}>
                                            <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                                                <a
                                                    href={ensureExternalUrl(errItem.url)}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{ color: 'var(--text)' }}
                                                >
                                                    {errItem.title}
                                                </a>
                                            </div>
                                            <StoryUrlLink url={errItem.url} />
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center' }}>
                                            <SiteBadge site={errItem.site} />
                                            <span className={statusBadgeClass(errItem.status)}>
                                                {errItem.status}
                                                {errItem.occurrences > 1 ? ` (×${errItem.occurrences})` : ''}
                                            </span>
                                        </div>
                                    </div>

                                    <AttemptBlockCard
                                        block={getStoryAttemptBlock(errItem.url, {
                                            title: errItem.title,
                                            site: errItem.site,
                                            attemptNumber: errItem.attempt_number || errItem.occurrences,
                                            error: errItem.error,
                                        })}
                                        defaultExpanded={true}
                                    />

                                    <div
                                        style={{
                                            display: 'flex',
                                            justifyContent: 'flex-end',
                                            gap: '0.45rem',
                                            flexWrap: 'wrap',
                                        }}
                                    >
                                        <button
                                            type="button"
                                            className="secondary btn-sm"
                                            onClick={() => {
                                                handleDismissSingleError(errItem.url)
                                                if (uniqueErrors.length <= 1) {
                                                    setShowAllErrorsModal(false)
                                                }
                                            }}
                                            title="Dismiss this error alert"
                                        >
                                            <Trash2 size={13} /> Dismiss
                                        </button>
                                        <button
                                            type="button"
                                            className="secondary btn-sm"
                                            onClick={() => handleCopyTraceback(errItem.error)}
                                        >
                                            {copiedTrace ? <Check size={13} /> : <Copy size={13} />}
                                            {copiedTrace ? 'Copied!' : 'Copy Traceback'}
                                        </button>
                                        <button
                                            type="button"
                                            className="secondary btn-sm"
                                            onClick={() => {
                                                setShowAllErrorsModal(false)
                                                handleJumpToLogs(errItem.site, errItem.url)
                                            }}
                                        >
                                            <Terminal size={13} /> View Log Block
                                        </button>
                                        <button
                                            type="button"
                                            className="secondary btn-sm"
                                            onClick={() => {
                                                redownloadScratch({
                                                    url: errItem.url,
                                                    site: errItem.site,
                                                    title: errItem.title,
                                                    calibre_id: errItem.calibre_id,
                                                })
                                                showBriefNotice(
                                                    `Queued full redownload from scratch for ${errItem.title}`
                                                )
                                                setShowAllErrorsModal(false)
                                            }}
                                        >
                                            <RotateCcw size={13} /> From Scratch
                                        </button>
                                        <button
                                            type="button"
                                            className="btn-sm"
                                            onClick={() => {
                                                addUrls([errItem.url])
                                                showBriefNotice(`Queued update for ${errItem.title}`)
                                                setShowAllErrorsModal(false)
                                            }}
                                        >
                                            <RefreshCw size={13} /> Retry Update
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="modal-footer">
                            <button
                                type="button"
                                className="danger"
                                onClick={() => {
                                    handleClearAllErrors()
                                    setShowAllErrorsModal(false)
                                }}
                            >
                                <Trash2 size={14} /> Clear All Errors
                            </button>
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => setShowAllErrorsModal(false)}
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Single Diagnostic Error Modal */}
            {selectedError && (
                <div className="modal-overlay" onClick={() => setSelectedError(null)}>
                    <div
                        className="modal-card"
                        style={{ maxWidth: 780 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <h3>Attempt Execution Block & Stack Trace — {selectedError.title}</h3>
                            <button
                                type="button"
                                className="modal-close-btn"
                                aria-label="Close modal"
                                onClick={() => setSelectedError(null)}
                            >
                                ✕
                            </button>
                        </div>
                        <div className="modal-body">
                            <AttemptBlockCard
                                block={getStoryAttemptBlock(selectedError.url, {
                                    title: selectedError.title,
                                    site: selectedError.site,
                                    attemptNumber: selectedError.attempt_number || selectedError.occurrences,
                                    error: selectedError.error,
                                })}
                                defaultExpanded={true}
                            />
                        </div>
                        <div className="modal-footer">
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => handleCopyTraceback(selectedError.error)}
                            >
                                {copiedTrace ? <Check size={14} /> : <Copy size={14} />}
                                {copiedTrace ? 'Copied!' : 'Copy Traceback'}
                            </button>
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => {
                                    const s = selectedError.site
                                    const u = selectedError.url
                                    setSelectedError(null)
                                    handleJumpToLogs(s, u)
                                }}
                            >
                                <Terminal size={14} /> View in Logs
                            </button>
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => {
                                    redownloadScratch({
                                        url: selectedError.url,
                                        site: selectedError.site,
                                        title: selectedError.title,
                                        calibre_id: selectedError.calibre_id,
                                    })
                                    setSelectedError(null)
                                }}
                            >
                                <RotateCcw size={14} /> From Scratch
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    addUrls([selectedError.url])
                                    setSelectedError(null)
                                }}
                            >
                                <RefreshCw size={14} /> Retry Update
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Worker Thread Pool & Dynamic Site Queues Modal */}
            {showWorkerPoolModal && (
                <div className="modal-overlay" onClick={() => setShowWorkerPoolModal(false)}>
                    <div
                        className="modal-card"
                        style={{ maxWidth: 740, width: '100%' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <div>
                                <h3 style={{ margin: 0, fontSize: '1.02rem' }}>
                                    Worker Thread Pool ({activeThreads} / {maxThreads} System Threads Active)
                                </h3>
                                <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                                    Pool concurrency is bounded by system CPU threads ({maxThreads} max). Dynamic per-site lanes serialize same-site downloads and release their thread when idle.
                                </div>
                            </div>
                            <button
                                type="button"
                                className="secondary btn-sm"
                                onClick={() => setShowWorkerPoolModal(false)}
                            >
                                <X size={14} /> Close
                            </button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                            <div
                                style={{
                                    padding: '0.65rem 0.85rem',
                                    borderRadius: 'var(--radius-sm)',
                                    background: 'var(--surface2)',
                                    border: '1px solid var(--border)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.45rem',
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        alignItems: 'center',
                                        flexWrap: 'wrap',
                                        gap: '0.5rem',
                                        fontSize: '0.78rem',
                                    }}
                                >
                                    <span style={{ fontWeight: 600 }}>
                                        Thread Pool Utilization:{' '}
                                        <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                                            {activeThreads} / {maxThreads} threads
                                        </span>
                                    </span>
                                    <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                                        {notableSites.filter((s) => s.status === 'downloading' || s.status === 'queued').length} active site queues ·{' '}
                                        {notableSites.filter((s) => s.status === 'backoff').length} in backoff ·{' '}
                                        {notableSites.filter((s) => s.status === 'disabled').length} disabled
                                    </span>
                                </div>
                                <div
                                    style={{
                                        height: 6,
                                        borderRadius: 999,
                                        background: 'var(--bg)',
                                        overflow: 'hidden',
                                    }}
                                >
                                    <div
                                        style={{
                                            width: `${Math.min(100, Math.round((activeThreads / Math.max(1, maxThreads)) * 100))}%`,
                                            height: '100%',
                                            background: 'var(--accent)',
                                            transition: 'width 0.25s ease',
                                        }}
                                    />
                                </div>
                            </div>

                            <div style={{ position: 'relative' }}>
                                <Search
                                    size={15}
                                    style={{
                                        position: 'absolute',
                                        left: '0.8rem',
                                        top: '50%',
                                        transform: 'translateY(-50%)',
                                        color: 'var(--text-muted)',
                                    }}
                                />
                                <input
                                    type="text"
                                    placeholder="Search site queue or domain (e.g. archiveofourown, fanfiction, royalroad, spacebattles)…"
                                    value={workerSearch}
                                    onChange={(e) => setWorkerSearch(e.target.value)}
                                    style={{ paddingLeft: '2.35rem', background: 'var(--surface2)' }}
                                />
                            </div>

                            <div
                                style={{
                                    maxHeight: 380,
                                    overflowY: 'auto',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.45rem',
                                }}
                            >
                                {catalogSites
                                    .filter((sw) => {
                                        if (!workerSearch.trim()) return true
                                        const q = workerSearch.toLowerCase()
                                        const info = getSiteBadgeInfo(sw.site)
                                        return sw.site.toLowerCase().includes(q) || info.name.toLowerCase().includes(q)
                                    })
                                    .map((sw) => {
                                        const info = getSiteBadgeInfo(sw.site)
                                        const isDisabled = sw.status === 'disabled'
                                        return (
                                            <div
                                                key={sw.site}
                                                style={{
                                                    padding: '0.6rem 0.8rem',
                                                    borderRadius: 'var(--radius-sm)',
                                                    background: 'var(--surface2)',
                                                    border: '1px solid var(--border)',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'space-between',
                                                    gap: '0.75rem',
                                                    flexWrap: 'wrap',
                                                }}
                                            >
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
                                                    <span className="site-dot" style={{ background: info.color }} />
                                                    <span style={{ fontWeight: 700, fontSize: '0.84rem' }}>{info.name}</span>
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                                        ({sw.site})
                                                    </span>
                                                    <span
                                                        className={
                                                            sw.status === 'downloading'
                                                                ? 'badge badge-warning'
                                                                : sw.status === 'queued'
                                                                  ? 'badge badge-info'
                                                                  : sw.status === 'backoff'
                                                                    ? 'badge badge-info'
                                                                    : sw.status === 'disabled'
                                                                      ? 'badge badge-error'
                                                                      : 'badge'
                                                        }
                                                    >
                                                        {sw.status === 'backoff'
                                                            ? `backoff (retry #${sw.attempt_number || 1})`
                                                            : sw.status}
                                                    </span>
                                                    <span
                                                        className="tabular-nums"
                                                        style={{ fontSize: '0.73rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}
                                                    >
                                                        {sw.total_downloads || 0} total · {sw.failed_downloads || 0} failed
                                                    </span>
                                                </div>

                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                                    <button
                                                        type="button"
                                                        className="secondary btn-sm"
                                                        onClick={() => {
                                                            setShowWorkerPoolModal(false)
                                                            navigate(`/history?site=${encodeURIComponent(sw.site)}`)
                                                        }}
                                                        style={{ padding: '0.15rem 0.5rem', minHeight: 24, fontSize: '0.72rem' }}
                                                    >
                                                        History
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className={isDisabled ? 'btn-sm' : 'danger btn-sm'}
                                                        onClick={async () => {
                                                            const res = await toggleSiteDisabled(sw.site)
                                                            showBriefNotice(res.message)
                                                        }}
                                                        style={{ padding: '0.15rem 0.5rem', minHeight: 24, fontSize: '0.72rem' }}
                                                    >
                                                        {isDisabled ? 'Enable Site' : 'Disable Site'}
                                                    </button>
                                                </div>
                                            </div>
                                        )
                                    })}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
