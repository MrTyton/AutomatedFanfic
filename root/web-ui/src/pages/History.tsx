import { useEffect, useState, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
    getDownloads,
    getRetries,
    getEmails,
    getNotifications,
    getHistorySites,
    addUrls,
    retryNow,
    cancelRetry,
    redownloadScratch,
    getStoryAttemptBlock,
    DashboardSnapshot,
    DownloadRow,
    RetryRow,
    EmailRow,
    NotificationRow,
} from '../api'
import { statusBadgeClass, getSiteBadgeInfo } from '../statusColors'
import AttemptBlockCard from '../components/AttemptBlockCard'
import { ensureExternalUrl } from '../utils/dashboardLogic'
import {
    Search,
    RefreshCw,
    Download,
    RotateCcw,
    Bell,
    Mail,
    AlertTriangle,
    ChevronLeft,
    ChevronRight,
    ExternalLink,
    Copy,
    Check,
    Terminal,
    XCircle,
} from 'lucide-react'

type Tab = 'downloads' | 'retries' | 'emails' | 'notifications'
type StatusFilter = '' | 'success' | 'failed' | 'abandoned'

function SiteBadge({ site }: { site?: string | null }) {
    if (!site) return <span style={{ color: 'var(--text-faint)' }}>—</span>
    const info = getSiteBadgeInfo(site)
    return (
        <span className="site-badge" style={{ color: 'var(--text)' }}>
            <span className="site-dot" style={{ background: info.color }} />
            <span>{info.name}</span>
        </span>
    )
}

function formatDateTime(iso: string | null): string {
    if (!iso) return '—'
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString([], {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    })
}

function formatDuration(startedAt: string | null, completedAt: string | null): string {
    if (!startedAt || !completedAt) return '—'
    const s = new Date(startedAt).getTime()
    const e = new Date(completedAt).getTime()
    if (isNaN(s) || isNaN(e)) return '—'
    const secs = Math.max(1, Math.round((e - s) / 1000))
    if (secs < 60) return `${secs}s`
    const mins = Math.floor(secs / 60)
    const rem = secs % 60
    return `${mins}m ${rem}s`
}

function summarizeError(err?: string | null): string {
    if (!err) return ''
    const firstLine = err.split('\n')[0].trim()
    return firstLine.length > 110 ? firstLine.slice(0, 107) + '…' : firstLine
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

interface InspectedErrorItem {
    title: string
    url: string
    site?: string
    calibre_id?: string | null
    error_message: string
}

interface HistoryProps {
    data?: DashboardSnapshot | null
}

export default function History({ data }: HistoryProps = {}) {
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()

    const initialTab = (searchParams.get('tab') as Tab) || 'downloads'
    const [tab, setTab] = useState<Tab>(
        ['downloads', 'retries', 'emails', 'notifications'].includes(initialTab) ? initialTab : 'downloads'
    )
    const [page, setPage] = useState(1)
    const [search, setSearch] = useState(() => searchParams.get('search') || '')
    const [statusFilter, setStatusFilter] = useState<StatusFilter>(
        () => (searchParams.get('status') as StatusFilter) || ''
    )
    const [siteFilter, setSiteFilter] = useState(() => searchParams.get('site') || '')
    const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set())

    useEffect(() => {
        const pTab = searchParams.get('tab') as Tab | null
        const pStatus = searchParams.get('status') as StatusFilter | null
        const pSite = searchParams.get('site')
        const pSearch = searchParams.get('search')
        if (pTab && ['downloads', 'retries', 'emails', 'notifications'].includes(pTab)) {
            setTab(pTab)
        }
        if (pStatus !== null) setStatusFilter(pStatus)
        if (pSite !== null) setSiteFilter(pSite)
        if (pSearch !== null) setSearch(pSearch)
    }, [searchParams])

    const [downloads, setDownloads] = useState<{ items: DownloadRow[]; total: number }>({
        items: [],
        total: 0,
    })
    const [retries, setRetries] = useState<{ items: RetryRow[]; total: number }>({
        items: [],
        total: 0,
    })
    const [emails, setEmails] = useState<{ items: EmailRow[]; total: number }>({
        items: [],
        total: 0,
    })
    const [notifications, setNotifications] = useState<{ items: NotificationRow[]; total: number }>({
        items: [],
        total: 0,
    })
    const [loading, setLoading] = useState(true)
    const [requeuedKey, setRequeuedKey] = useState<string | null>(null)
    const [confirmScratchKey, setConfirmScratchKey] = useState<string | null>(null)
    const [inspectedError, setInspectedError] = useState<InspectedErrorItem | null>(null)
    const [copiedTrace, setCopiedTrace] = useState(false)
    const [bulkNotice, setBulkNotice] = useState<string | null>(null)

    const inFlightUrlSet = useMemo(() => {
        const set = new Set<string>()
        if (data) {
            for (const a of data.active_downloads?.items || []) set.add(a.url)
            for (const q of data.queued_downloads?.items || []) set.add(q.url)
            for (const w of data.waiting_downloads?.items || []) set.add(w.url)
        }
        return set
    }, [data, requeuedKey])

    const maxNormalRetries = useMemo(() => {
        return data?.max_normal_retries ?? 11
    }, [data])

    const pageSize = 25

    useEffect(() => {
        setPage(1)
        setSelectedUrls(new Set())
    }, [tab, search, statusFilter, siteFilter])

    const [availableSites, setAvailableSites] = useState<string[]>([])
    const [tabCounts, setTabCounts] = useState<{
        downloads: number
        retries: number
        emails: number
        notifications: number
    }>({
        downloads: 0,
        retries: 0,
        emails: 0,
        notifications: 0,
    })

    useEffect(() => {
        getHistorySites()
            .then((res) => {
                if (res?.sites) setAvailableSites(res.sites)
            })
            .catch(() => {})
    }, [])

    const updateUrlParams = (changes: {
        tab?: Tab
        site?: string
        status?: StatusFilter
        search?: string
    }) => {
        const next = new URLSearchParams()
        const t = changes.tab !== undefined ? changes.tab : tab
        const s = changes.site !== undefined ? changes.site : siteFilter
        const st = changes.status !== undefined ? changes.status : statusFilter
        const q = changes.search !== undefined ? changes.search : search

        if (t !== 'downloads') next.set('tab', t)
        if (s) next.set('site', s)
        if (st) next.set('status', st)
        if (q) next.set('search', q)
        setSearchParams(next, { replace: true })
    }

    const loadCurrentTab = () => {
        setLoading(true)
        const p =
            tab === 'downloads'
                ? getDownloads(page, pageSize, search, statusFilter, siteFilter).then((r) => {
                      setDownloads(r)
                      setTabCounts((c) => ({ ...c, downloads: r.total }))
                  })
                : tab === 'retries'
                  ? getRetries(page, pageSize, search, siteFilter).then((r) => {
                        setRetries(r)
                        setTabCounts((c) => ({ ...c, retries: r.total }))
                    })
                  : tab === 'emails'
                    ? getEmails(page, pageSize).then((r) => {
                          const tot = r.total ?? r.items.length
                          setEmails({ items: r.items, total: tot })
                          setTabCounts((c) => ({ ...c, emails: tot }))
                      })
                    : getNotifications(page, pageSize, search, siteFilter).then((r) => {
                          const tot = r.total ?? r.items.length
                          setNotifications({ items: r.items, total: tot })
                          setTabCounts((c) => ({ ...c, notifications: tot }))
                      })

        p.catch(() => {}).finally(() => setLoading(false))
    }

    useEffect(() => {
        loadCurrentTab()
    }, [tab, page, search, statusFilter, siteFilter])

    // Pre-load total counts for other tabs on initial mount without overriding items
    useEffect(() => {
        getDownloads(1, 1).then((r) => setTabCounts((c) => ({ ...c, downloads: r.total }))).catch(() => {})
        getRetries(1, 1).then((r) => setTabCounts((c) => ({ ...c, retries: r.total }))).catch(() => {})
        getEmails(1, 1).then((r) => setTabCounts((c) => ({ ...c, emails: r.total ?? r.items.length }))).catch(() => {})
        getNotifications(1, 1).then((r) => setTabCounts((c) => ({ ...c, notifications: r.total ?? r.items.length }))).catch(() => {})
    }, [])

    const handleUpdate = async (url: string) => {
        await addUrls([url])
        setRequeuedKey(`update:${url}`)
        setTimeout(() => setRequeuedKey(null), 2000)
    }

    const toggleSelectUrl = (url: string) => {
        setSelectedUrls((prev) => {
            const next = new Set(prev)
            if (next.has(url)) next.delete(url)
            else next.add(url)
            return next
        })
    }

    const handleBulkUpdate = async () => {
        const urls = Array.from(selectedUrls)
        if (urls.length === 0) return
        await addUrls(urls)
        setSelectedUrls(new Set())
        setBulkNotice(`Queued ${urls.length} selected stor${urls.length === 1 ? 'y' : 'ies'} for update/retry`)
        setTimeout(() => setBulkNotice(null), 3000)
    }

    const handleBulkScratch = async () => {
        const urls = Array.from(selectedUrls)
        if (urls.length === 0) return
        for (const url of urls) {
            const row = downloads.items.find((d) => d.url === url)
            await redownloadScratch({
                url,
                site: row?.site,
                title: row?.title,
                calibre_id: row?.calibre_id,
            })
        }
        setSelectedUrls(new Set())
        setBulkNotice(`Queued ${urls.length} selected stor${urls.length === 1 ? 'y' : 'ies'} for Ch. 1 overwrite`)
        setTimeout(() => setBulkNotice(null), 3000)
    }

    const handleScratch = async (payload: {
        url: string
        site?: string
        title?: string | null
        calibre_id?: string | null
    }) => {
        setConfirmScratchKey(null)
        await redownloadScratch({
            url: payload.url,
            site: payload.site,
            title: payload.title,
            calibre_id: payload.calibre_id,
        })
        setRequeuedKey(`scratch:${payload.url}`)
        setTimeout(() => setRequeuedKey(null), 2000)
    }

    const handleRetryNow = async (r: RetryRow) => {
        await retryNow({
            url: r.url,
            site: r.site,
            title: r.title,
        })
        setRequeuedKey(`retry:${r.id}`)
        loadCurrentTab()
        setTimeout(() => setRequeuedKey(null), 2000)
    }

    const handleCancelRetry = async (r: RetryRow) => {
        await cancelRetry({
            url: r.url,
            site: r.site,
            title: r.title,
        })
        loadCurrentTab()
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

    const totalRecords =
        tab === 'downloads'
            ? downloads.total
            : tab === 'retries'
              ? retries.total
              : tab === 'emails'
                ? emails.total
                : notifications.total
    const totalPages = Math.max(1, Math.ceil(totalRecords / pageSize))

    const displaySiteOptions = useMemo(() => {
        const set = new Set(availableSites)
        if (siteFilter) set.add(siteFilter)
        return Array.from(set).sort()
    }, [availableSites, siteFilter])

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    marginBottom: '1rem',
                }}
            >
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                        History
                    </h1>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        Complete log of story downloads, scheduled retries, email checks, and notifications
                    </p>
                </div>
            </div>

            {/* Category Navigation + Segmented Status Filter */}
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.65rem',
                    marginBottom: '0.85rem',
                }}
            >
                <div className="history-tabs-grid">
                    <button
                        type="button"
                        className={tab === 'downloads' ? '' : 'secondary'}
                        onClick={() => {
                            setTab('downloads')
                            updateUrlParams({ tab: 'downloads' })
                        }}
                    >
                        <Download size={15} /> Downloads ({tabCounts.downloads || downloads.total})
                    </button>
                    <button
                        type="button"
                        className={tab === 'retries' ? '' : 'secondary'}
                        onClick={() => {
                            setTab('retries')
                            updateUrlParams({ tab: 'retries' })
                        }}
                    >
                        <RotateCcw size={15} /> Retries ({tabCounts.retries || retries.total})
                    </button>
                    <button
                        type="button"
                        className={tab === 'emails' ? '' : 'secondary'}
                        onClick={() => {
                            setTab('emails')
                            updateUrlParams({ tab: 'emails' })
                        }}
                    >
                        <Mail size={15} /> Email Checks ({tabCounts.emails || emails.total})
                    </button>
                    <button
                        type="button"
                        className={tab === 'notifications' ? '' : 'secondary'}
                        onClick={() => {
                            setTab('notifications')
                            updateUrlParams({ tab: 'notifications' })
                        }}
                    >
                        <Bell size={15} /> Notifications ({tabCounts.notifications || notifications.total})
                    </button>
                </div>

                {tab === 'downloads' && (
                    <div className="segmented-control">
                        {(
                            [
                                { label: 'All', value: '' },
                                { label: 'Success', value: 'success' },
                                { label: 'Failed', value: 'failed' },
                                { label: 'Abandoned', value: 'abandoned' },
                            ] as { label: string; value: StatusFilter }[]
                        ).map((opt) => (
                            <button
                                key={opt.label}
                                type="button"
                                className={`segmented-btn ${statusFilter === opt.value ? 'active' : ''}`}
                                onClick={() => {
                                    setStatusFilter(opt.value)
                                    updateUrlParams({ status: opt.value })
                                }}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {/* Search & Site Filter Row (for Downloads, Retries, and Notifications) */}
            {(tab === 'downloads' || tab === 'retries' || tab === 'notifications') && (
                <div
                    style={{
                        display: 'flex',
                        gap: '0.65rem',
                        flexWrap: 'wrap',
                        alignItems: 'center',
                        marginBottom: '1rem',
                    }}
                >
                    <div style={{ position: 'relative', flex: '1 1 240px' }}>
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
                            aria-label="Search history records"
                            placeholder={
                                tab === 'downloads'
                                    ? 'Search story title, URL, error, or Calibre ID…'
                                    : tab === 'retries'
                                      ? 'Search retry story title, URL, or error reason…'
                                      : 'Search notifications by title, body, or provider…'
                            }
                            value={search}
                            onChange={(e) => {
                                setSearch(e.target.value)
                                updateUrlParams({ search: e.target.value })
                            }}
                            style={{ paddingLeft: '2.35rem', background: 'var(--surface)' }}
                        />
                    </div>
                    <select
                        value={siteFilter}
                        onChange={(e) => {
                            setSiteFilter(e.target.value)
                            updateUrlParams({ site: e.target.value })
                        }}
                        style={{ flex: '1 1 160px', background: 'var(--surface)' }}
                        aria-label="Filter by source site"
                    >
                        <option value="">All Sites</option>
                        {displaySiteOptions.map((s) => (
                            <option key={s} value={s}>
                                {getSiteBadgeInfo(s).name}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            {loading ? (
                <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                    Loading records…
                </div>
            ) : (
                <>
                    {/* 1. DOWNLOADS TAB */}
                    {tab === 'downloads' && (
                        <>
                            {/* Bulk Selection Bar */}
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    flexWrap: 'wrap',
                                    gap: '0.5rem',
                                    marginBottom: '0.65rem',
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <button
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => {
                                            const failedUrls = downloads.items
                                                .filter((d) => d.status === 'failed' || d.status === 'abandoned')
                                                .map((d) => d.url)
                                            setSelectedUrls(new Set(failedUrls))
                                        }}
                                        style={{ padding: '0.18rem 0.55rem', minHeight: 26, fontSize: '0.74rem' }}
                                    >
                                        Select Failed on Page
                                    </button>
                                    {selectedUrls.size > 0 && (
                                        <>
                                            <button
                                                type="button"
                                                className="btn-sm"
                                                onClick={handleBulkUpdate}
                                                style={{ padding: '0.18rem 0.65rem', minHeight: 26, fontSize: '0.74rem' }}
                                            >
                                                <RefreshCw size={12} /> Retry / Update Selected ({selectedUrls.size})
                                            </button>
                                            <button
                                                type="button"
                                                className="secondary btn-sm"
                                                onClick={handleBulkScratch}
                                                style={{ padding: '0.18rem 0.65rem', minHeight: 26, fontSize: '0.74rem' }}
                                            >
                                                <RotateCcw size={12} /> From Scratch Selected ({selectedUrls.size})
                                            </button>
                                            <button
                                                type="button"
                                                className="secondary btn-sm"
                                                onClick={() => setSelectedUrls(new Set())}
                                                style={{ padding: '0.18rem 0.5rem', minHeight: 26, fontSize: '0.74rem' }}
                                            >
                                                Clear Selection
                                            </button>
                                        </>
                                    )}
                                </div>
                                {bulkNotice && (
                                    <span className="badge badge-info" style={{ fontSize: '0.76rem' }}>
                                        {bulkNotice}
                                    </span>
                                )}
                                {(siteFilter || statusFilter || search) && (
                                    <button
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => {
                                            setSiteFilter('')
                                            setStatusFilter('')
                                            setSearch('')
                                            setSearchParams(tab === 'downloads' ? {} : { tab }, { replace: true })
                                        }}
                                        style={{ padding: '0.18rem 0.55rem', minHeight: 26, fontSize: '0.74rem' }}
                                    >
                                        Clear Active Filters
                                    </button>
                                )}
                            </div>

                            <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                <table>
                                    <thead>
                                        <tr>
                                            <th style={{ width: 32 }}>
                                                <input
                                                    type="checkbox"
                                                    aria-label="Select all stories on page"
                                                    checked={
                                                        downloads.items.length > 0 &&
                                                        downloads.items.every((d) => selectedUrls.has(d.url))
                                                    }
                                                    onChange={(e) => {
                                                        if (e.target.checked) {
                                                            setSelectedUrls(new Set(downloads.items.map((d) => d.url)))
                                                        } else {
                                                            setSelectedUrls(new Set())
                                                        }
                                                    }}
                                                    style={{ width: 15, height: 15, margin: 0 }}
                                                />
                                            </th>
                                            <th>Story / Source URL</th>
                                            <th>Site</th>
                                            <th>Status</th>
                                            <th>Calibre ID</th>
                                            <th>Started</th>
                                            <th>Duration</th>
                                            <th style={{ textAlign: 'right' }}>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {downloads.items.map((r, idx) => {
                                            const rowKey = `${r.url}-${r.started_at}-${idx}`
                                            const isConfirmingScratch = confirmScratchKey === rowKey
                                            const isRowInFlight = inFlightUrlSet.has(r.url)
                                            const actionLabel = !r.calibre_id && r.status !== 'success' ? 'Retry' : 'Update'
                                            return (
                                                <tr key={rowKey}>
                                                    <td>
                                                        <input
                                                            type="checkbox"
                                                            aria-label={`Select ${r.title || r.url}`}
                                                            checked={selectedUrls.has(r.url)}
                                                            onChange={() => toggleSelectUrl(r.url)}
                                                            style={{ width: 15, height: 15, margin: 0 }}
                                                        />
                                                    </td>
                                                    <td>
                                                        <div style={{ fontWeight: 600 }}>
                                                            <a
                                                                href={ensureExternalUrl(r.url)}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                style={{ color: 'var(--text)' }}
                                                            >
                                                                {r.title || 'Untitled Story'}
                                                            </a>
                                                        </div>
                                                        <StoryUrlLink url={r.url} />
                                                    </td>
                                                    <td>
                                                        <SiteBadge site={r.site} />
                                                    </td>
                                                    <td style={{ maxWidth: 250 }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'nowrap' }}>
                                                            <span className={statusBadgeClass(r.status)}>
                                                                {r.status}
                                                            </span>
                                                            {r.error_message && (
                                                                <div style={{ display: 'inline-flex', gap: '0.25rem', flexShrink: 0 }}>
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                                        onClick={() => handleJumpToLogs(r.site, r.url)}
                                                                        title="Jump directly to this attempt's block in the Logs page"
                                                                    >
                                                                        <Terminal size={10} /> Log Block
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        style={{ padding: '0.1rem 0.38rem', minHeight: 20, fontSize: '0.69rem' }}
                                                                        onClick={() =>
                                                                            setInspectedError({
                                                                                title: r.title || r.url,
                                                                                url: r.url,
                                                                                site: r.site,
                                                                                calibre_id: r.calibre_id,
                                                                                error_message: r.error_message!,
                                                                            })
                                                                        }
                                                                        title="Inspect attempt execution block and stack trace"
                                                                    >
                                                                        <AlertTriangle size={10} /> Trace
                                                                    </button>
                                                                </div>
                                                            )}
                                                        </div>
                                                        {r.error_message && (
                                                            <div
                                                                onClick={() =>
                                                                    setInspectedError({
                                                                        title: r.title || r.url,
                                                                        url: r.url,
                                                                        site: r.site,
                                                                        calibre_id: r.calibre_id,
                                                                        error_message: r.error_message!,
                                                                    })
                                                                }
                                                                title={`${summarizeError(r.error_message)} — Click to view stack trace`}
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
                                                                {summarizeError(r.error_message)}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td>
                                                        {r.calibre_id ? (
                                                            <span
                                                                className="tabular-nums"
                                                                style={{
                                                                    fontFamily: 'var(--font-mono)',
                                                                    color: 'var(--success)',
                                                                    fontWeight: 600,
                                                                }}
                                                            >
                                                                #{r.calibre_id}
                                                            </span>
                                                        ) : (
                                                            <span style={{ color: 'var(--text-faint)' }}>
                                                                —
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.78rem',
                                                            color: 'var(--text-muted)',
                                                            whiteSpace: 'nowrap',
                                                        }}
                                                    >
                                                        {formatDateTime(r.started_at)}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.78rem',
                                                            color: 'var(--text-muted)',
                                                        }}
                                                    >
                                                        {formatDuration(r.started_at, r.completed_at)}
                                                    </td>
                                                    <td style={{ textAlign: 'right' }}>
                                                        <div
                                                            style={{
                                                                display: 'inline-flex',
                                                                gap: '0.4rem',
                                                                justifyContent: 'flex-end',
                                                            }}
                                                        >
                                                            {isRowInFlight ? (
                                                                <span
                                                                    className="badge badge-info"
                                                                    title="Already queued or waiting retry"
                                                                >
                                                                    In Queue
                                                                </span>
                                                            ) : (
                                                                <button
                                                                    type="button"
                                                                    className="secondary btn-sm"
                                                                    onClick={() => handleUpdate(r.url)}
                                                                    title={
                                                                        actionLabel === 'Retry'
                                                                            ? 'Retry downloading this story'
                                                                            : 'Fetch only new chapters and append to existing EPUB'
                                                                    }
                                                                >
                                                                    <RefreshCw size={12} />
                                                                    {requeuedKey === `update:${r.url}`
                                                                        ? 'Queued!'
                                                                        : actionLabel}
                                                                </button>
                                                            )}
                                                            {isConfirmingScratch ? (
                                                                <>
                                                                    <button
                                                                        type="button"
                                                                        className="danger btn-sm"
                                                                        onClick={() => handleScratch(r)}
                                                                    >
                                                                        Confirm Overwrite
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        onClick={() => setConfirmScratchKey(null)}
                                                                    >
                                                                        Cancel
                                                                    </button>
                                                                </>
                                                            ) : (
                                                                <button
                                                                    type="button"
                                                                    className="secondary btn-sm"
                                                                    onClick={() => setConfirmScratchKey(rowKey)}
                                                                    title="Re-download all chapters from Chapter 1 and overwrite existing EPUB"
                                                                >
                                                                    <RotateCcw size={12} />
                                                                    {requeuedKey === `scratch:${r.url}`
                                                                        ? 'Queued!'
                                                                        : 'From Scratch'}
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

                            <div className="mobile-card-list">
                                {downloads.items.map((r, idx) => (
                                    <div
                                        key={`mob-${r.url}-${r.started_at}-${idx}`}
                                        className="mobile-data-card"
                                    >
                                        <div className="mobile-data-card-header">
                                            <div style={{ minWidth: 0, flex: 1 }}>
                                                <div style={{ fontWeight: 600 }}>
                                                    <a
                                                        href={r.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        style={{ color: 'var(--text)' }}
                                                    >
                                                        {r.title || 'Untitled Story'}
                                                    </a>
                                                </div>
                                                <StoryUrlLink url={r.url} />
                                            </div>
                                            <span className={statusBadgeClass(r.status)}>
                                                {r.status}
                                            </span>
                                        </div>
                                        {r.error_message && (
                                            <div
                                                style={{
                                                    padding: '0.4rem 0.6rem',
                                                    borderRadius: 'var(--radius-sm)',
                                                    background: 'rgba(239, 68, 68, 0.1)',
                                                    border: '1px solid rgba(239, 68, 68, 0.25)',
                                                    color: '#fca5a5',
                                                    fontSize: '0.76rem',
                                                }}
                                            >
                                                {summarizeError(r.error_message)}
                                            </div>
                                        )}
                                        <div
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                fontSize: '0.75rem',
                                                gap: '0.5rem',
                                            }}
                                        >
                                            <SiteBadge site={r.site} />
                                            <span
                                                style={{
                                                    color: 'var(--text-muted)',
                                                    fontFamily: 'var(--font-mono)',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    whiteSpace: 'nowrap',
                                                }}
                                            >
                                                {r.calibre_id ? `#${r.calibre_id}` : '—'} ·{' '}
                                                {formatDateTime(r.started_at)} ({formatDuration(r.started_at, r.completed_at)})
                                            </span>
                                        </div>
                                        <div className="mobile-data-card-actions">
                                            {inFlightUrlSet.has(r.url) ? (
                                                <span className="badge badge-info" style={{ alignSelf: 'center' }}>
                                                    In Queue
                                                </span>
                                            ) : (
                                                <button
                                                    type="button"
                                                    className="secondary"
                                                    onClick={() => handleUpdate(r.url)}
                                                >
                                                    <RefreshCw size={14} />{' '}
                                                    {!r.calibre_id && r.status !== 'success' ? 'Retry' : 'Update'}
                                                </button>
                                            )}
                                            {confirmScratchKey === `mob-${r.url}-${idx}` ? (
                                                <>
                                                    <button
                                                        type="button"
                                                        className="danger"
                                                        onClick={() => handleScratch(r)}
                                                    >
                                                        Confirm Overwrite
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className="secondary"
                                                        onClick={() => setConfirmScratchKey(null)}
                                                    >
                                                        Cancel
                                                    </button>
                                                </>
                                            ) : (
                                                <button
                                                    type="button"
                                                    className="secondary"
                                                    onClick={() => setConfirmScratchKey(`mob-${r.url}-${idx}`)}
                                                >
                                                    <RotateCcw size={14} /> From Scratch
                                                </button>
                                            )}
                                            {r.error_message && (
                                                <button
                                                    type="button"
                                                    className="danger"
                                                    onClick={() =>
                                                        setInspectedError({
                                                            title: r.title || r.url,
                                                            url: r.url,
                                                            site: r.site,
                                                            calibre_id: r.calibre_id,
                                                            error_message: r.error_message!,
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
                        </>
                    )}

                    {/* 2. RETRIES TAB */}
                    {tab === 'retries' && (
                        <>
                            <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Story / URL</th>
                                            <th>Site</th>
                                            <th>Attempt</th>
                                            <th>Action</th>
                                            <th>Delay</th>
                                            <th>Scheduled / Status</th>
                                            <th>Error Reason</th>
                                            <th style={{ textAlign: 'right' }}>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {retries.items.map((r) => {
                                            const isPending = !r.fired_at
                                            return (
                                                <tr key={r.id}>
                                                    <td>
                                                        <div style={{ fontWeight: 600 }}>
                                                            <a
                                                                href={ensureExternalUrl(r.url)}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                style={{ color: 'var(--text)' }}
                                                            >
                                                                {r.title || 'Story Retry'}
                                                            </a>
                                                        </div>
                                                        <StoryUrlLink url={r.url} />
                                                    </td>
                                                    <td>
                                                        <SiteBadge site={r.site} />
                                                    </td>
                                                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                                                        #{r.attempt_number} / {maxNormalRetries}
                                                    </td>
                                                    <td>
                                                        <span className={statusBadgeClass(r.action)}>
                                                            {r.action}
                                                        </span>
                                                    </td>
                                                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                                                        {r.delay_minutes}m
                                                    </td>
                                                    <td
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.77rem',
                                                            color: 'var(--text-muted)',
                                                        }}
                                                    >
                                                        <div>{formatDateTime(r.scheduled_at)}</div>
                                                        <span
                                                            style={{
                                                                fontSize: '0.7rem',
                                                                color: isPending ? 'var(--info)' : 'var(--text-faint)',
                                                            }}
                                                        >
                                                            {isPending ? 'Pending backoff' : `Fired ${formatDateTime(r.fired_at)}`}
                                                        </span>
                                                    </td>
                                                    <td style={{ color: '#fca5a5', fontSize: '0.75rem', maxWidth: 230 }}>
                                                        <div
                                                            onClick={() =>
                                                                r.error_message &&
                                                                setInspectedError({
                                                                    title: r.title || r.url,
                                                                    url: r.url,
                                                                    site: r.site,
                                                                    error_message: r.error_message,
                                                                })
                                                            }
                                                            title={r.error_message || undefined}
                                                            style={{
                                                                whiteSpace: 'nowrap',
                                                                overflow: 'hidden',
                                                                textOverflow: 'ellipsis',
                                                                maxWidth: 220,
                                                                cursor: r.error_message ? 'pointer' : 'default',
                                                            }}
                                                        >
                                                            {summarizeError(r.error_message) || '—'}
                                                        </div>
                                                    </td>
                                                    <td style={{ textAlign: 'right' }}>
                                                        <div
                                                            style={{
                                                                display: 'inline-flex',
                                                                gap: '0.35rem',
                                                                justifyContent: 'flex-end',
                                                            }}
                                                        >
                                                            {r.error_message && (
                                                                <>
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        onClick={() => handleJumpToLogs(r.site, r.url)}
                                                                        title="Jump to this attempt block in Logs"
                                                                    >
                                                                        <Terminal size={12} /> Log Block
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        onClick={() =>
                                                                            setInspectedError({
                                                                                title: r.title || r.url,
                                                                                url: r.url,
                                                                                site: r.site,
                                                                                error_message: r.error_message!,
                                                                            })
                                                                        }
                                                                    >
                                                                        Trace
                                                                    </button>
                                                                </>
                                                            )}
                                                            <button
                                                                type="button"
                                                                className="btn-sm"
                                                                onClick={() => handleRetryNow(r)}
                                                            >
                                                                <RefreshCw size={12} />{' '}
                                                                {requeuedKey === `retry:${r.id}` ? 'Queued!' : 'Retry Now'}
                                                            </button>
                                                            {isPending && (
                                                                <button
                                                                    type="button"
                                                                    className="danger btn-sm"
                                                                    onClick={() => handleCancelRetry(r)}
                                                                >
                                                                    <XCircle size={12} /> Cancel
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

                            <div className="mobile-card-list">
                                {retries.items.map((r) => {
                                    const isPending = !r.fired_at
                                    return (
                                        <div key={`mob-retry-${r.id}`} className="mobile-data-card">
                                            <div className="mobile-data-card-header">
                                                <div style={{ minWidth: 0, flex: 1 }}>
                                                    <div style={{ fontWeight: 600 }}>
                                                        <a
                                                            href={ensureExternalUrl(r.url)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            style={{ color: 'var(--text)' }}
                                                        >
                                                            {r.title || 'Story Retry'}
                                                        </a>
                                                    </div>
                                                    <StoryUrlLink url={r.url} />
                                                </div>
                                                <span className={statusBadgeClass(r.action)}>
                                                    {r.action} #{r.attempt_number}
                                                </span>
                                            </div>
                                            {r.error_message && (
                                                <div style={{ fontSize: '0.76rem', color: '#fca5a5' }}>
                                                    {summarizeError(r.error_message)}
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
                                                <SiteBadge site={r.site} />
                                                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                                                    Delay: {r.delay_minutes}m · {formatDateTime(r.scheduled_at)}
                                                </span>
                                            </div>
                                            <div className="mobile-data-card-actions">
                                                <button type="button" onClick={() => handleRetryNow(r)}>
                                                    <RefreshCw size={14} /> Retry Now
                                                </button>
                                                {r.error_message && (
                                                    <button
                                                        type="button"
                                                        className="secondary"
                                                        onClick={() =>
                                                            setInspectedError({
                                                                title: r.title || r.url,
                                                                url: r.url,
                                                                site: r.site,
                                                                error_message: r.error_message!,
                                                            })
                                                        }
                                                    >
                                                        <AlertTriangle size={14} /> Trace
                                                    </button>
                                                )}
                                                {isPending && (
                                                    <button
                                                        type="button"
                                                        className="danger"
                                                        onClick={() => handleCancelRetry(r)}
                                                    >
                                                        <XCircle size={14} /> Cancel
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </>
                    )}

                    {/* 3. EMAIL CHECKS TAB */}
                    {tab === 'emails' && (
                        <>
                            <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Checked At</th>
                                            <th>Trigger</th>
                                            <th>URLs Found</th>
                                            <th>New Queued</th>
                                            <th>Duplicates</th>
                                            <th>Disabled Sites</th>
                                            <th>Extracted Story URLs</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {emails.items.map((e) => (
                                            <tr key={e.id}>
                                                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                                                    {formatDateTime(e.checked_at)}
                                                </td>
                                                <td>
                                                    <span className="badge badge-info">{e.trigger}</span>
                                                </td>
                                                <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                                                    {e.urls_found}
                                                </td>
                                                <td
                                                    style={{
                                                        fontFamily: 'var(--font-mono)',
                                                        color: 'var(--success)',
                                                        fontWeight: 600,
                                                    }}
                                                >
                                                    {e.urls_new}
                                                </td>
                                                <td style={{ fontFamily: 'var(--font-mono)' }}>
                                                    {e.urls_duplicate}
                                                </td>
                                                <td style={{ fontFamily: 'var(--font-mono)' }}>
                                                    {e.urls_disabled_site}
                                                </td>
                                                <td>
                                                    {e.extracted_urls && e.extracted_urls.length > 0 ? (
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                                            {e.extracted_urls.map((u, i) => (
                                                                <div
                                                                    key={`${u.url}-${i}`}
                                                                    style={{
                                                                        display: 'flex',
                                                                        alignItems: 'center',
                                                                        gap: '0.4rem',
                                                                        flexWrap: 'wrap',
                                                                        fontSize: '0.76rem',
                                                                    }}
                                                                >
                                                                    <SiteBadge site={u.site} />
                                                                    <a
                                                                        href={ensureExternalUrl(u.url)}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                        style={{ fontWeight: 600, color: 'var(--text)' }}
                                                                    >
                                                                        {u.title || u.url}
                                                                    </a>
                                                                    <span
                                                                        className={
                                                                            u.status === 'new'
                                                                                ? 'badge badge-success'
                                                                                : u.status === 'duplicate'
                                                                                  ? 'badge badge-info'
                                                                                  : 'badge badge-warning'
                                                                        }
                                                                    >
                                                                        {u.status}
                                                                    </span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <span style={{ color: 'var(--text-faint)', fontSize: '0.76rem' }}>
                                                            No matching fanfiction URLs in unread messages
                                                        </span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            <div className="mobile-card-list">
                                {emails.items.map((e) => (
                                    <div key={`mob-email-${e.id}`} className="mobile-data-card">
                                        <div className="mobile-data-card-header">
                                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.84rem' }}>
                                                {formatDateTime(e.checked_at)}
                                            </span>
                                            <span className="badge badge-info">{e.trigger}</span>
                                        </div>
                                        <div
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                fontSize: '0.78rem',
                                                color: 'var(--text-muted)',
                                            }}
                                        >
                                            <span>Found: <strong>{e.urls_found}</strong></span>
                                            <span style={{ color: 'var(--success)' }}>New: <strong>{e.urls_new}</strong></span>
                                            <span>Dupes: <strong>{e.urls_duplicate}</strong></span>
                                        </div>
                                        {e.extracted_urls && e.extracted_urls.length > 0 && (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', marginTop: '0.25rem' }}>
                                                {e.extracted_urls.map((u, i) => (
                                                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap', fontSize: '0.74rem' }}>
                                                        <SiteBadge site={u.site} />
                                                        <a href={ensureExternalUrl(u.url)} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text)', fontWeight: 600 }}>
                                                            {u.title || u.url}
                                                        </a>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {/* 4. NOTIFICATIONS TAB */}
                    {tab === 'notifications' && (
                        <>
                            <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Title</th>
                                            <th>Message</th>
                                            <th>Site</th>
                                            <th>Provider</th>
                                            <th>Sent At</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {notifications.items.map((n) => (
                                            <tr key={n.id}>
                                                <td style={{ fontWeight: 600 }}>{n.title}</td>
                                                <td style={{ color: 'var(--text-muted)' }}>{n.body}</td>
                                                <td>
                                                    <SiteBadge site={n.site} />
                                                </td>
                                                <td>
                                                    <span className="badge badge-info">
                                                        {n.provider || 'apprise'}
                                                    </span>
                                                </td>
                                                <td
                                                    style={{
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '0.78rem',
                                                        color: 'var(--text-muted)',
                                                    }}
                                                >
                                                    {formatDateTime(n.sent_at)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            <div className="mobile-card-list">
                                {notifications.items.map((n) => (
                                    <div key={`mob-notif-${n.id}`} className="mobile-data-card">
                                        <div className="mobile-data-card-header">
                                            <div style={{ fontWeight: 600 }}>{n.title}</div>
                                            <span className="badge badge-info">{n.provider || 'apprise'}</span>
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                            {n.body}
                                        </div>
                                        <div
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                fontSize: '0.75rem',
                                            }}
                                        >
                                            <SiteBadge site={n.site} />
                                            <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                                                {formatDateTime(n.sent_at)}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}

                    {/* Pagination Footer */}
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginTop: '1rem',
                            flexWrap: 'wrap',
                            gap: '0.75rem',
                        }}
                    >
                        <span className="tabular-nums" style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                            Page <strong>{page}</strong> of <strong>{totalPages}</strong> ({totalRecords}{' '}
                            records)
                        </span>
                        <div style={{ display: 'flex', gap: '0.45rem' }}>
                            <button
                                type="button"
                                className="secondary btn-sm"
                                disabled={page <= 1}
                                onClick={() => setPage((p) => p - 1)}
                            >
                                <ChevronLeft size={14} /> Previous
                            </button>
                            <button
                                type="button"
                                className="secondary btn-sm"
                                disabled={page >= totalPages}
                                onClick={() => setPage((p) => p + 1)}
                            >
                                Next <ChevronRight size={14} />
                            </button>
                        </div>
                    </div>
                </>
            )}

            {inspectedError && (
                <div className="modal-overlay" onClick={() => setInspectedError(null)}>
                    <div
                        className="modal-card"
                        style={{ maxWidth: 780 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <h3>Attempt Execution Block & Stack Trace — {inspectedError.title || inspectedError.url}</h3>
                            <button
                                type="button"
                                className="modal-close-btn"
                                aria-label="Close modal"
                                onClick={() => setInspectedError(null)}
                            >
                                ✕
                            </button>
                        </div>
                        <div className="modal-body">
                            <AttemptBlockCard
                                block={getStoryAttemptBlock(inspectedError.url, {
                                    title: inspectedError.title,
                                    site: inspectedError.site || undefined,
                                    error: inspectedError.error_message,
                                })}
                                defaultExpanded={true}
                            />
                        </div>
                        <div className="modal-footer">
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => handleCopyTraceback(inspectedError.error_message)}
                            >
                                {copiedTrace ? <Check size={14} /> : <Copy size={14} />}
                                {copiedTrace ? 'Copied!' : 'Copy Traceback'}
                            </button>
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => {
                                    const s = inspectedError.site
                                    const u = inspectedError.url
                                    setInspectedError(null)
                                    handleJumpToLogs(s, u)
                                }}
                            >
                                <Terminal size={14} /> View in Logs
                            </button>
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => {
                                    handleScratch(inspectedError)
                                    setInspectedError(null)
                                }}
                            >
                                <RotateCcw size={14} /> From Scratch
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    handleUpdate(inspectedError.url)
                                    setInspectedError(null)
                                }}
                            >
                                <RefreshCw size={14} /> Update Story
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
