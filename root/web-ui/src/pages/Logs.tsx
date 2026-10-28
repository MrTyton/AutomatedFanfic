import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
    getLogs,
    getStartupLogs,
    clearLogs,
    getAttemptBlocksFromLogs,
    getHistoricalStoryDetails,
    type LogEntry,
    type HistoricalStoryDetails,
} from '../api'
import { formatAttemptBlockAsText, type LogAttemptBlock } from '../utils/dashboardLogic'
import AttemptBlockCard from '../components/AttemptBlockCard'
import GitHubIssueModal from '../components/GitHubIssueModal'
import {
    Search,
    Pause,
    Play,
    Copy,
    Check,
    Trash2,
    ArrowUpToLine,
    ArrowDownToLine,
    X,
    Layers,
    List,
    Activity,
    Clock,
    Bug,
    Database,
    AlertTriangle,
    ExternalLink,
} from 'lucide-react'

const LEVEL_COLORS: Record<string, string> = {
    debug: '#64748b',
    info: '#38bdf8',
    warning: '#f59e0b',
    error: '#ef4444',
    critical: '#f87171',
}

function ansiToCssColor(ansi?: string): string | undefined {
    if (!ansi) return undefined
    const m256 = ansi.match(/38;5;(\d+)/)
    if (m256) {
        const n = parseInt(m256[1], 10)
        const std = [
            '#555',
            '#f87171',
            '#4ade80',
            '#facc15',
            '#60a5fa',
            '#c084fc',
            '#22d3ee',
            '#e2e8f0',
            '#64748b',
            '#ef4444',
            '#22c55e',
            '#eab308',
            '#3b82f6',
            '#a855f7',
            '#06b6d4',
            '#f8fafc',
        ]
        if (n < 16) return std[n]
        if (n < 232) {
            const idx = n - 16
            const r = Math.floor(idx / 36) * 51
            const g = (Math.floor(idx / 6) % 6) * 51
            const b = (idx % 6) * 51
            return `rgb(${r},${g},${b})`
        }
        const gray = (n - 232) * 10 + 8
        return `rgb(${gray},${gray},${gray})`
    }
    const basic: Record<string, string> = {
        '31': '#f87171',
        '32': '#4ade80',
        '33': '#facc15',
        '34': '#60a5fa',
        '35': '#c084fc',
        '36': '#22d3ee',
        '91': '#ef4444',
        '92': '#22c55e',
        '93': '#eab308',
        '94': '#3b82f6',
        '95': '#a855f7',
        '96': '#06b6d4',
    }
    for (const [code, col] of Object.entries(basic)) {
        if (ansi.includes(`${code}m`)) return col
    }
    return undefined
}

const SITE_MSG_RE = /^\(([\w.-]+)\)/

function extractSite(entry: LogEntry): string {
    if (entry.thread_site) return entry.thread_site
    const m = entry.message.match(SITE_MSG_RE)
    return m ? m[1] : ''
}

const URL_SPLIT_RE = /(https?:\/\/[^\s<>"')]+)/g

function renderMessageWithLinks(message: string) {
    const parts = message.split(URL_SPLIT_RE)
    return parts.map((part, i) => {
        if (part.startsWith('http://') || part.startsWith('https://')) {
            return (
                <a
                    key={i}
                    href={part}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                        color: '#818cf8',
                        textDecoration: 'underline',
                        wordBreak: 'break-all',
                    }}
                >
                    {part}
                </a>
            )
        }
        return <span key={i}>{part}</span>
    })
}

const LEVEL_FILTERS: { label: string; value: string; levels: Set<string> | null }[] = [
    { label: 'Info', value: 'info', levels: new Set(['info']) },
    { label: 'Warn', value: 'warning', levels: new Set(['info', 'warning']) },
    { label: 'Errors', value: 'error', levels: new Set(['info', 'warning', 'error', 'critical']) },
    { label: 'Debug', value: 'debug', levels: null },
]

export default function Logs() {
    const [searchParams, setSearchParams] = useSearchParams()
    const [mode, setMode] = useState<'runtime' | 'startup'>('runtime')
    const [viewFormat, setViewFormat] = useState<'blocks' | 'stream'>(() =>
        searchParams.get('view') === 'stream' ? 'stream' : 'blocks'
    )
    const [entries, setEntries] = useState<LogEntry[]>([])
    const [levelFilter, setLevelFilter] = useState('error')
    const [siteFilter, setSiteFilter] = useState(() => searchParams.get('site') || '')
    const [search, setSearch] = useState(() => searchParams.get('search') || '')
    const [focusedBlockUrl, setFocusedBlockUrl] = useState(() => searchParams.get('block') || '')
    const [blockStatusFilter, setBlockStatusFilter] = useState<'all' | 'failed' | 'active'>('all')
    const [forceExpandedState, setForceExpandedState] = useState<boolean | null>(null)
    const [paused, setPaused] = useState(false)
    const [copied, setCopied] = useState(false)
    const [confirmClear, setConfirmClear] = useState(false)
    const [historicalFallback, setHistoricalFallback] = useState<HistoricalStoryDetails['story'] | null>(null)
    const [historicalLoading, setHistoricalLoading] = useState(false)
    const [copiedHistoricalTrace, setCopiedHistoricalTrace] = useState(false)
    const [issueModalTarget, setIssueModalTarget] = useState<{
        open: boolean
        block?: LogAttemptBlock | null
    }>({ open: false, block: null })
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const paramSite = searchParams.get('site')
        const paramSearch = searchParams.get('search')
        const paramView = searchParams.get('view')
        const paramBlock = searchParams.get('block')
        if (paramSite !== null) setSiteFilter(paramSite)
        if (paramSearch !== null) setSearch(paramSearch)
        if (paramView === 'stream' || paramView === 'blocks') setViewFormat(paramView)
        if (paramBlock !== null) {
            setFocusedBlockUrl(paramBlock)
            setViewFormat('blocks')
            setMode('runtime')
        }
    }, [searchParams])

    const loadLogs = useCallback(() => {
        const fn = mode === 'runtime' ? getLogs : getStartupLogs
        fn(500)
            .then((res) => setEntries(res.items))
            .catch(() => {})
    }, [mode])

    useEffect(() => {
        loadLogs()
    }, [loadLogs])

    useEffect(() => {
        if (paused || mode === 'startup') return
        const id = setInterval(loadLogs, 2500)
        return () => clearInterval(id)
    }, [paused, mode, loadLogs])

    const sites = useMemo(() => {
        const set = new Set<string>()
        if (siteFilter) set.add(siteFilter)
        for (const e of entries) {
            const s = extractSite(e)
            if (s) set.add(s)
        }
        return Array.from(set).sort()
    }, [entries, siteFilter])

    const allowedLevels = useMemo(
        () => LEVEL_FILTERS.find((f) => f.value === levelFilter)?.levels ?? null,
        [levelFilter]
    )

    const filtered = useMemo(() => {
        const q = search.toLowerCase()
        return entries.filter((e) => {
            const lvl = e.level.toLowerCase()
            if (allowedLevels && !allowedLevels.has(lvl)) return false
            if (siteFilter && extractSite(e) !== siteFilter) return false
            if (q && !e.message.toLowerCase().includes(q) && !lvl.includes(q)) return false
            return true
        })
    }, [entries, allowedLevels, siteFilter, search])

    // In raw stream view, chronological order reads top-to-bottom (oldest at top, most recent at bottom).
    const rawStreamLines = useMemo(() => [...filtered].reverse(), [filtered])

    // Build de-interleaved per-attempt blocks (already sorted: active first, then not active, each sorted by latest update)
    const filteredAttemptBlocks = useMemo(() => {
        const rawBlocks = getAttemptBlocksFromLogs(entries)
        const q = search.toLowerCase()

        return rawBlocks
            .map((block) => {
                const visibleLines = block.lines.filter((line) => {
                    const lvl = line.level.toLowerCase()
                    if (allowedLevels && !allowedLevels.has(lvl)) return false
                    return true
                })
                return {
                    ...block,
                    lines: visibleLines,
                }
            })
            .filter((block) => {
                if (block.lines.length === 0) return false
                if (siteFilter && block.site !== siteFilter) return false
                if (blockStatusFilter === 'failed' && block.status !== 'failed') return false
                if (blockStatusFilter === 'active' && !block.isActive) return false
                if (q) {
                    const matchesHeader =
                        block.title.toLowerCase().includes(q) ||
                        (block.url && block.url.toLowerCase().includes(q)) ||
                        (block.site && block.site.toLowerCase().includes(q)) ||
                        (block.traceback && block.traceback.toLowerCase().includes(q))
                    const matchesLine = block.lines.some(
                        (l) => l.message.toLowerCase().includes(q) || l.level.toLowerCase().includes(q)
                    )
                    if (!matchesHeader && !matchesLine) return false
                }
                return true
            })
    }, [entries, allowedLevels, siteFilter, blockStatusFilter, search])

    // Separate into Active/In-Flight blocks vs Completed/Historical blocks, each sorted by latest update (endedAt descending)
    const activeAttemptBlocks = useMemo(
        () => filteredAttemptBlocks.filter((b) => b.isActive),
        [filteredAttemptBlocks]
    )

    const inactiveAttemptBlocks = useMemo(
        () => filteredAttemptBlocks.filter((b) => !b.isActive),
        [filteredAttemptBlocks]
    )

    const hasLiveBlockForUrl = useMemo(
        () => (focusedBlockUrl ? filteredAttemptBlocks.some((b) => b.url === focusedBlockUrl) : false),
        [focusedBlockUrl, filteredAttemptBlocks]
    )

    useEffect(() => {
        if (!focusedBlockUrl || hasLiveBlockForUrl) {
            setHistoricalFallback(null)
            return
        }

        let cancelled = false
        setHistoricalLoading(true)
        getHistoricalStoryDetails(focusedBlockUrl)
            .then((res) => {
                if (cancelled) return
                if (res?.found && res.story) {
                    setHistoricalFallback(res.story)
                } else {
                    setHistoricalFallback(null)
                }
            })
            .catch(() => {
                if (!cancelled) setHistoricalFallback(null)
            })
            .finally(() => {
                if (!cancelled) setHistoricalLoading(false)
            })

        return () => {
            cancelled = true
        }
    }, [focusedBlockUrl, hasLiveBlockForUrl])

    // Scroll to focused block when navigated via ?block=<url>
    useEffect(() => {
        if (!focusedBlockUrl || viewFormat !== 'blocks') return
        const timer = setTimeout(() => {
            const container = containerRef.current
            if (!container) return
            const target = container.querySelector(
                `[data-block-url="${CSS.escape(focusedBlockUrl)}"]`
            ) as HTMLElement | null
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
            }
        }, 120)
        return () => clearTimeout(timer)
    }, [focusedBlockUrl, viewFormat, filteredAttemptBlocks.length])

    const isAtBottomRef = useRef(true)

    const handleScroll = () => {
        const container = containerRef.current
        if (!container) return
        const threshold = 60
        isAtBottomRef.current =
            container.scrollHeight - container.scrollTop - container.clientHeight <= threshold
    }

    // Auto-scroll to bottom in raw stream view as new logs arrive
    useEffect(() => {
        if (viewFormat !== 'stream' || paused) return
        if (isAtBottomRef.current) {
            const container = containerRef.current
            if (container) {
                container.scrollTop = container.scrollHeight
            }
        }
    }, [viewFormat, rawStreamLines.length, paused])

    // Initial scroll to bottom when switching to stream view
    useEffect(() => {
        if (viewFormat === 'stream') {
            const container = containerRef.current
            if (container) {
                container.scrollTop = container.scrollHeight
            }
        }
    }, [viewFormat])

    const handleCopy = () => {
        const text =
            viewFormat === 'blocks' && mode === 'runtime'
                ? filteredAttemptBlocks.map((b) => formatAttemptBlockAsText(b)).join('\n\n')
                : rawStreamLines.map((e) => `${e.timestamp} [${e.level.toUpperCase()}] ${e.message}`).join('\n')
        navigator.clipboard?.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    const handleScrollTop = () => {
        isAtBottomRef.current = false
        containerRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }

    const handleScrollBottom = () => {
        isAtBottomRef.current = true
        const container = containerRef.current
        if (container) {
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
        }
    }

    const clearActiveFilters = () => {
        setSiteFilter('')
        setSearch('')
        setFocusedBlockUrl('')
        setBlockStatusFilter('all')
        setSearchParams({})
    }

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
                        Logs
                    </h1>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        {viewFormat === 'blocks' && mode === 'runtime'
                            ? `Organized by Active (${activeAttemptBlocks.length}) then Completed (${inactiveAttemptBlocks.length}), sorted by latest update`
                            : `Live stream from Coordinator, UrlIngester, FFWaiter, and site workers (${filtered.length} of ${entries.length} lines shown)`}
                    </p>
                </div>

                <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', alignItems: 'center' }}>
                    {mode === 'runtime' && (
                        <div className="segmented-control" style={{ width: 'auto' }} role="group" aria-label="Log display format">
                            <button
                                type="button"
                                className={`segmented-btn ${viewFormat === 'blocks' ? 'active' : ''}`}
                                onClick={() => setViewFormat('blocks')}
                                title="Group interleaved worker logs into isolated per-attempt execution blocks"
                            >
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <Layers size={13} /> Attempt Blocks
                                </span>
                            </button>
                            <button
                                type="button"
                                className={`segmented-btn ${viewFormat === 'stream' ? 'active' : ''}`}
                                onClick={() => setViewFormat('stream')}
                                title="Show raw chronological log stream"
                            >
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <List size={13} /> Raw Stream
                                </span>
                            </button>
                        </div>
                    )}

                    <div className="segmented-control" style={{ width: 'auto' }}>
                        <button
                            type="button"
                            className={`segmented-btn ${mode === 'runtime' ? 'active' : ''}`}
                            onClick={() => setMode('runtime')}
                        >
                            Runtime
                        </button>
                        <button
                            type="button"
                            className={`segmented-btn ${mode === 'startup' ? 'active' : ''}`}
                            onClick={() => setMode('startup')}
                        >
                            Startup
                        </button>
                    </div>

                    {mode === 'runtime' && (
                        <button
                            type="button"
                            className={`btn-sm ${paused ? '' : 'secondary'}`}
                            onClick={() => setPaused((p) => !p)}
                        >
                            {paused ? <Play size={14} /> : <Pause size={14} />}
                            {paused ? 'Resume' : 'Pause'}
                        </button>
                    )}

                    <button type="button" className="secondary btn-sm" onClick={handleScrollTop} title="Scroll to top of log buffer">
                        <ArrowUpToLine size={14} /> Top
                    </button>
                    {viewFormat === 'stream' && (
                        <button type="button" className="secondary btn-sm" onClick={handleScrollBottom} title="Scroll to bottom (most recent) of log buffer">
                            <ArrowDownToLine size={14} /> Bottom
                        </button>
                    )}

                    <button type="button" className="secondary btn-sm" onClick={handleCopy}>
                        {copied ? <Check size={14} /> : <Copy size={14} />}
                        {copied ? 'Copied' : 'Copy'}
                    </button>

                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={() => {
                            const defaultBlock =
                                viewFormat === 'blocks' && mode === 'runtime'
                                    ? filteredAttemptBlocks.find((b) => b.status === 'failed') ||
                                      filteredAttemptBlocks[0] ||
                                      null
                                    : null
                            setIssueModalTarget({ open: true, block: defaultBlock })
                        }}
                        title="Create a GitHub issue with logs copied in and PII check"
                    >
                        <Bug size={14} /> Report Issue
                    </button>

                    {mode === 'runtime' && (
                        confirmClear ? (
                            <>
                                <button
                                    type="button"
                                    className="danger btn-sm"
                                    onClick={() => {
                                        clearLogs()
                                        loadLogs()
                                        setConfirmClear(false)
                                    }}
                                >
                                    Confirm Clear
                                </button>
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={() => setConfirmClear(false)}
                                >
                                    Cancel
                                </button>
                            </>
                        ) : (
                            <button
                                type="button"
                                className="danger btn-sm"
                                onClick={() => setConfirmClear(true)}
                            >
                                <Trash2 size={14} /> Clear
                            </button>
                        )
                    )}
                </div>
            </div>

            {/* Filter Bar */}
            <div
                style={{
                    display: 'flex',
                    gap: '0.6rem',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    marginBottom: '0.85rem',
                }}
            >
                <div className="segmented-control">
                    {LEVEL_FILTERS.map((f) => (
                        <button
                            key={f.value}
                            type="button"
                            className={`segmented-btn ${levelFilter === f.value ? 'active' : ''}`}
                            onClick={() => setLevelFilter(f.value)}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>

                <select
                    value={siteFilter}
                    onChange={(e) => setSiteFilter(e.target.value)}
                    style={{ flex: '1 1 160px', background: 'var(--surface)' }}
                    aria-label="Filter by worker site"
                >
                    <option value="">All Worker Sites</option>
                    {sites.map((s) => (
                        <option key={s} value={s}>
                            {s}
                        </option>
                    ))}
                </select>

                <div style={{ position: 'relative', flex: '2 1 220px' }}>
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
                        aria-label="Filter log messages"
                        placeholder="Filter log messages, URLs, or titles…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        style={{ paddingLeft: '2.35rem', background: 'var(--surface)' }}
                    />
                </div>

                {viewFormat === 'blocks' && mode === 'runtime' && (
                    <div className="segmented-control" role="group" aria-label="Filter attempt blocks by outcome">
                        {(
                            [
                                { label: 'All Blocks', value: 'all' },
                                { label: 'Failed Only', value: 'failed' },
                                { label: 'Active Only', value: 'active' },
                            ] as const
                        ).map((bf) => (
                            <button
                                key={bf.value}
                                type="button"
                                className={`segmented-btn ${blockStatusFilter === bf.value ? 'active' : ''}`}
                                onClick={() => setBlockStatusFilter(bf.value)}
                            >
                                {bf.label}
                            </button>
                        ))}
                    </div>
                )}

                {viewFormat === 'blocks' && mode === 'runtime' && (
                    <div style={{ display: 'inline-flex', gap: '0.35rem' }}>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => setForceExpandedState(true)}
                            style={{ padding: '0.2rem 0.55rem', minHeight: 28, fontSize: '0.74rem' }}
                            title="Expand all attempt blocks"
                        >
                            Expand All
                        </button>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => setForceExpandedState(false)}
                            style={{ padding: '0.2rem 0.55rem', minHeight: 28, fontSize: '0.74rem' }}
                            title="Collapse all attempt blocks to summary headers"
                        >
                            Collapse All
                        </button>
                    </div>
                )}

                {(siteFilter || search || focusedBlockUrl || blockStatusFilter !== 'all') && (
                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={clearActiveFilters}
                        title="Reset site, search, and block highlight"
                    >
                        <X size={14} /> Reset Filters
                    </button>
                )}
            </div>

            {/* Log Viewer Container */}
            <div
                ref={containerRef}
                onScroll={handleScroll}
                style={{
                    background: '#070a12',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-lg)',
                    padding: viewFormat === 'blocks' && mode === 'runtime' ? '0.85rem' : '0.65rem 0.75rem',
                    height: 'calc(100vh - 280px)',
                    minHeight: 340,
                    overflowY: 'auto',
                }}
            >
                {viewFormat === 'blocks' && mode === 'runtime' ? (
                    <div>
                        {/* Pinned Historical DB Fallback Card if navigating to a block whose console logs rolled over */}
                        {focusedBlockUrl && !hasLiveBlockForUrl && (
                            <div
                                style={{
                                    background: 'var(--surface)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    padding: '1rem',
                                    marginBottom: '1.25rem',
                                }}
                            >
                                {historicalLoading ? (
                                    <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                                        Checking persistent database for historical story records...
                                    </div>
                                ) : historicalFallback ? (
                                    <div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                            <div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                                    <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                                                        <Database size={11} /> Historical DB Record
                                                    </span>
                                                    {historicalFallback.download.site && (
                                                        <span style={{ fontSize: '0.72rem', fontWeight: 600, padding: '0.15rem 0.45rem', borderRadius: '4px', background: 'var(--surface-hover)', color: 'var(--text-secondary)' }}>
                                                            {historicalFallback.download.site}
                                                        </span>
                                                    )}
                                                    <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '0.15rem 0.45rem', borderRadius: '4px', background: historicalFallback.download.status === 'failed' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(34, 197, 94, 0.15)', color: historicalFallback.download.status === 'failed' ? 'var(--danger)' : 'var(--success)' }}>
                                                        {historicalFallback.download.status.toUpperCase()}
                                                    </span>
                                                    {historicalFallback.download.calibre_id && (
                                                        <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: 'var(--success)' }}>
                                                            #{historicalFallback.download.calibre_id}
                                                        </span>
                                                    )}
                                                </div>
                                                <h3 style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: '0.35rem', marginBottom: '0.2rem' }}>
                                                    {historicalFallback.download.title || focusedBlockUrl}
                                                </h3>
                                                <a href={focusedBlockUrl} target="_blank" rel="noopener noreferrer" style={{ fontSize: '0.78rem', color: 'var(--text-muted)', wordBreak: 'break-all', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                                                    <span>{focusedBlockUrl}</span>
                                                    <ExternalLink size={10} />
                                                </a>
                                            </div>
                                            <button
                                                type="button"
                                                className="secondary btn-sm"
                                                onClick={() => {
                                                    const next = new URLSearchParams(searchParams)
                                                    next.delete('block')
                                                    setSearchParams(next)
                                                    setFocusedBlockUrl('')
                                                }}
                                            >
                                                <X size={12} /> Clear Focus
                                            </button>
                                        </div>

                                        <div style={{ background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.25)', borderRadius: 'var(--radius-sm)', padding: '0.6rem 0.8rem', fontSize: '0.78rem', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.85rem' }}>
                                            <AlertTriangle size={15} style={{ flexShrink: 0 }} />
                                            <span>
                                                Live console logs from this previous session are no longer in memory (e.g., container restarted or logs rolled over). Displaying captured diagnostic record from the persistent history database.
                                            </span>
                                        </div>

                                        <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '0.85rem' }}>
                                            <span>Started: <strong style={{ color: 'var(--text-primary)' }}>{historicalFallback.download.started_at}</strong></span>
                                            {historicalFallback.download.completed_at && (
                                                <span>Completed: <strong style={{ color: 'var(--text-primary)' }}>{historicalFallback.download.completed_at}</strong></span>
                                            )}
                                            <span>Total Retries: <strong style={{ color: 'var(--text-primary)' }}>{historicalFallback.retries.length}</strong></span>
                                        </div>

                                        {historicalFallback.download.error_message && (
                                            <div style={{ marginTop: '0.5rem' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                                                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--danger)' }}>
                                                        Captured Error & Traceback:
                                                    </span>
                                                    <button
                                                        type="button"
                                                        className="secondary btn-xs"
                                                        onClick={() => {
                                                            if (historicalFallback?.download.error_message) {
                                                                navigator.clipboard?.writeText(historicalFallback.download.error_message)
                                                                setCopiedHistoricalTrace(true)
                                                                setTimeout(() => setCopiedHistoricalTrace(false), 2000)
                                                            }
                                                        }}
                                                    >
                                                        {copiedHistoricalTrace ? <Check size={11} color="var(--success)" /> : <Copy size={11} />}
                                                        <span style={{ marginLeft: '0.25rem' }}>{copiedHistoricalTrace ? 'Copied' : 'Copy Trace'}</span>
                                                    </button>
                                                </div>
                                                <pre style={{ margin: 0, padding: '0.65rem 0.75rem', background: '#030712', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 'var(--radius-sm)', color: '#fca5a5', fontSize: '0.76rem', lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 250, overflowY: 'auto' }}>
                                                    {historicalFallback.download.error_message}
                                                </pre>
                                            </div>
                                        )}
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
                                        <span>No active log blocks or historical database records found matching URL: <code>{focusedBlockUrl}</code></span>
                                        <button
                                            type="button"
                                            className="secondary btn-xs"
                                            onClick={() => {
                                                const next = new URLSearchParams(searchParams)
                                                next.delete('block')
                                                setSearchParams(next)
                                                setFocusedBlockUrl('')
                                            }}
                                        >
                                            <X size={12} /> Clear Focus
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Section 1: Active & Waiting Attempts */}
                        {activeAttemptBlocks.length > 0 && (
                            <div style={{ marginBottom: '1.25rem' }}>
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        gap: '0.5rem',
                                        marginBottom: '0.6rem',
                                        padding: '0 0.25rem',
                                    }}
                                >
                                    <span
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.45rem',
                                            fontSize: '0.76rem',
                                            fontWeight: 700,
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.05em',
                                            color: '#22d3ee',
                                        }}
                                    >
                                        <Activity size={14} /> Active & Waiting Attempts ({activeAttemptBlocks.length})
                                    </span>
                                    <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                                        Sorted by latest update
                                    </span>
                                </div>
                                {activeAttemptBlocks.map((block) => (
                                    <AttemptBlockCard
                                        key={block.id}
                                        block={block}
                                        defaultExpanded={true}
                                        forceExpanded={forceExpandedState}
                                        searchQuery={search}
                                        isHighlighted={!!focusedBlockUrl && block.url === focusedBlockUrl}
                                        onFilterSite={(s) => setSiteFilter(s === siteFilter ? '' : s)}
                                        onReportIssue={(b) => setIssueModalTarget({ open: true, block: b })}
                                    />
                                ))}
                            </div>
                        )}

                        {/* Section 2: Completed & Historical Attempts */}
                        {inactiveAttemptBlocks.length > 0 && (
                            <div>
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        gap: '0.5rem',
                                        marginBottom: '0.6rem',
                                        padding: '0 0.25rem',
                                    }}
                                >
                                    <span
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.45rem',
                                            fontSize: '0.76rem',
                                            fontWeight: 700,
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.05em',
                                            color: 'var(--text-muted)',
                                        }}
                                    >
                                        <Clock size={14} /> Completed & Past Attempts ({inactiveAttemptBlocks.length})
                                    </span>
                                    <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                                        Sorted by latest update
                                    </span>
                                </div>
                                {inactiveAttemptBlocks.map((block) => (
                                    <AttemptBlockCard
                                        key={block.id}
                                        block={block}
                                        defaultExpanded={true}
                                        forceExpanded={forceExpandedState}
                                        searchQuery={search}
                                        isHighlighted={!!focusedBlockUrl && block.url === focusedBlockUrl}
                                        onFilterSite={(s) => setSiteFilter(s === siteFilter ? '' : s)}
                                        onReportIssue={(b) => setIssueModalTarget({ open: true, block: b })}
                                    />
                                ))}
                            </div>
                        )}

                        {filteredAttemptBlocks.length === 0 && (
                            <div style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                                No attempt blocks match your active filters.
                            </div>
                        )}
                    </div>
                ) : (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                        {rawStreamLines.map((entry, idx) => {
                            const lvl = entry.level.toLowerCase()
                            const color = ansiToCssColor(entry.thread_color) || '#e2e8f0'
                            const isErr = lvl === 'error' || lvl === 'critical'
                            return (
                                <div
                                    key={`${entry.timestamp}-${idx}`}
                                    className={`log-entry-row ${isErr ? 'log-error' : ''}`}
                                >
                                    <div className="log-entry-meta">
                                        <span style={{ color: '#64748b', fontSize: '0.73rem' }}>
                                            {entry.timestamp}
                                        </span>
                                        <span
                                            style={{
                                                color: LEVEL_COLORS[lvl] || '#94a3b8',
                                                fontWeight: 700,
                                                fontSize: '0.73rem',
                                                minWidth: '4.8em',
                                            }}
                                        >
                                            [{entry.level.toUpperCase()}]
                                        </span>
                                    </div>
                                    <div
                                        className="log-entry-msg"
                                        style={{ color: isErr ? '#fca5a5' : color }}
                                    >
                                        {renderMessageWithLinks(entry.message)}
                                    </div>
                                </div>
                            )
                        })}
                        {rawStreamLines.length === 0 && (
                            <div style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                                No log lines match your active filters.
                            </div>
                        )}
                    </div>
                )}
            </div>

            {issueModalTarget.open && (
                <GitHubIssueModal
                    block={issueModalTarget.block}
                    rawLogsText={
                        viewFormat === 'blocks' && mode === 'runtime'
                            ? filteredAttemptBlocks.map((b) => formatAttemptBlockAsText(b)).join('\n\n')
                            : rawStreamLines.map((e) => `${e.timestamp} [${e.level.toUpperCase()}] ${e.message}`).join('\n')
                    }
                    mode={mode}
                    onClose={() => setIssueModalTarget({ open: false, block: null })}
                />
            )}
        </div>
    )
}
