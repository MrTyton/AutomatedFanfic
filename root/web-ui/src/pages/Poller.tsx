import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
    Activity,
    AlertTriangle,
    Calendar,
    CheckCircle2,
    Clock,
    ExternalLink,
    Info,
    Radar,
    RefreshCw,
    Settings,
} from 'lucide-react'
import {
    fetchPollerStatus,
    triggerPollerSync,
    type PollEventItem,
    type PollerStatusResponse,
    type PollerTier,
    type PollerTierConfigMap,
    type PollerUpNextItem,
    type SitePollerStatus,
} from '../api'
import { getSiteBadgeInfo } from '../statusColors'
import { ensureExternalUrl } from '../utils/dashboardLogic'

const AUTO_REFRESH_MS = 15_000

const TIER_STYLES: Record<
    PollerTier,
    { label: string; color: string; bg: string; border: string }
> = {
    hot: {
        label: 'Hot',
        color: '#f87171',
        bg: 'rgba(239, 68, 68, 0.14)',
        border: 'rgba(239, 68, 68, 0.28)',
    },
    warm: {
        label: 'Warm',
        color: '#fbbf24',
        bg: 'rgba(245, 158, 11, 0.14)',
        border: 'rgba(245, 158, 11, 0.28)',
    },
    cool: {
        label: 'Cool',
        color: '#67e8f9',
        bg: 'rgba(6, 182, 212, 0.14)',
        border: 'rgba(6, 182, 212, 0.28)',
    },
    dormant: {
        label: 'Dormant',
        color: '#94a3b8',
        bg: 'rgba(148, 163, 184, 0.12)',
        border: 'rgba(148, 163, 184, 0.26)',
    },
}

const OUTCOME_STYLES: Record<
    string,
    { label: string; color: string; bg: string; border: string }
> = {
    unchanged: {
        label: 'Unchanged',
        color: '#94a3b8',
        bg: 'rgba(148, 163, 184, 0.12)',
        border: 'rgba(148, 163, 184, 0.26)',
    },
    update_found: {
        label: 'Update Found',
        color: '#34d399',
        bg: 'rgba(16, 185, 129, 0.14)',
        border: 'rgba(16, 185, 129, 0.3)',
    },
    completed: {
        label: 'Completed',
        color: '#a5b4fc',
        bg: 'rgba(99, 102, 241, 0.14)',
        border: 'rgba(99, 102, 241, 0.3)',
    },
    deleted: {
        label: 'Deleted',
        color: '#fbbf24',
        bg: 'rgba(245, 158, 11, 0.14)',
        border: 'rgba(245, 158, 11, 0.3)',
    },
    error: {
        label: 'Error',
        color: '#f87171',
        bg: 'rgba(239, 68, 68, 0.14)',
        border: 'rgba(239, 68, 68, 0.3)',
    },
}

function SiteBadge({ site }: { site: string }) {
    const info = getSiteBadgeInfo(site)
    return (
        <span className="site-badge" style={{ color: 'var(--text)' }}>
            <span className="site-dot" style={{ background: info.color }} />
            <span>{info.name}</span>
        </span>
    )
}

const DEFAULT_TIER_CONFIG: PollerTierConfigMap = {
    hot: { max_age_days: 14, interval_days: 1.5 },
    warm: { max_age_days: 90, interval_days: 7 },
    cool: { max_age_days: 365, interval_days: 21 },
    dormant: { max_age_days: null, interval_days: 60 },
}

function formatDays(days: number): string {
    const rounded = Math.round(days * 10) / 10
    return Number.isInteger(rounded) ? `${rounded}d` : `${rounded.toFixed(1)}d`
}

function TierBadge({ tier }: { tier: PollerTier }) {
    const style = TIER_STYLES[tier] ?? TIER_STYLES.dormant
    return (
        <span
            className="badge"
            style={{
                background: style.bg,
                color: style.color,
                border: `1px solid ${style.border}`,
            }}
        >
            {style.label}
        </span>
    )
}

function CadenceBadge({ cadenceDays }: { cadenceDays?: number | null }) {
    if (cadenceDays == null || !Number.isFinite(cadenceDays) || cadenceDays <= 0) {
        return null
    }
    return (
        <span
            className="badge badge-info"
            title="Detected from this story's regular update history"
            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}
        >
            ~{formatDays(cadenceDays)} schedule
        </span>
    )
}

function OutcomeBadge({ outcome }: { outcome: string }) {
    const normalized = outcome.toLowerCase()
    const style = OUTCOME_STYLES[normalized] ?? {
        label: outcome,
        color: '#a5b4fc',
        bg: 'rgba(99, 102, 241, 0.14)',
        border: 'rgba(99, 102, 241, 0.28)',
    }
    return (
        <span
            className="badge"
            style={{
                background: style.bg,
                color: style.color,
                border: `1px solid ${style.border}`,
            }}
        >
            {style.label}
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

function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '—'
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString([], {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    })
}

function formatDateOnly(iso: string | null | undefined): string {
    if (!iso) return '—'
    // Preserve YYYY-MM-DD dates cleanly without timezone shift
    if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
        const [year, month, day] = iso.split('-').map(Number)
        const d = new Date(year, month - 1, day)
        if (!isNaN(d.getTime())) {
            return d.toLocaleDateString([], {
                year: 'numeric',
                month: 'short',
                day: '2-digit',
            })
        }
    }
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleDateString([], {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
    })
}

function formatRelativeTime(iso: string | null | undefined, nowMs: number): string {
    if (!iso) return 'Never'
    const d = new Date(iso)
    const ms = d.getTime()
    if (isNaN(ms)) return iso

    const diffSec = Math.round((ms - nowMs) / 1000)
    const absSec = Math.abs(diffSec)

    const shortDate = d.toLocaleString([], {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    })

    if (absSec < 60) {
        return diffSec <= 0 ? `just now · ${shortDate}` : `in ${absSec}s · ${shortDate}`
    }
    const mins = Math.floor(absSec / 60)
    if (mins < 60) {
        return diffSec <= 0 ? `${mins}m ago · ${shortDate}` : `in ${mins}m · ${shortDate}`
    }
    const hours = Math.floor(mins / 60)
    if (hours < 48) {
        const remMins = mins % 60
        const span = remMins > 0 ? `${hours}h ${remMins}m` : `${hours}h`
        return diffSec <= 0 ? `${span} ago · ${shortDate}` : `in ${span} · ${shortDate}`
    }
    const days = Math.floor(hours / 24)
    return diffSec <= 0 ? `${days}d ago · ${shortDate}` : `in ${days}d · ${shortDate}`
}

function summarizeError(err: string | null | undefined): string {
    if (!err) return ''
    const firstLine = err.split('\n')[0].trim()
    return firstLine.length > 96 ? `${firstLine.slice(0, 93)}…` : firstLine
}

interface UpNextRow extends PollerUpNextItem {
    site: string
}

function SiteOverviewCard({
    site,
    status,
    nowMs,
}: {
    site: string
    status: SitePollerStatus
    nowMs: number
}) {
    const siteInfo = getSiteBadgeInfo(site)
    const budgetPct =
        status.max_checks_per_day > 0
            ? Math.min(100, Math.round((status.checks_last_24h / status.max_checks_per_day) * 100))
            : 0
    const barColor =
        budgetPct >= 100
            ? 'var(--error)'
            : budgetPct >= 80
              ? 'var(--warning)'
              : 'var(--accent)'

    const tierRules = status.tiers ?? DEFAULT_TIER_CONFIG
    const coolCutoff = tierRules.cool?.max_age_days ?? DEFAULT_TIER_CONFIG.cool.max_age_days ?? 365

    const tiers: { key: PollerTier; count: number; ageLabel: string; intervalLabel: string }[] = [
        {
            key: 'hot',
            count: status.tier_counts?.hot ?? 0,
            ageLabel: `≤${formatDays(tierRules.hot?.max_age_days ?? 14)}`,
            intervalLabel: `every ${formatDays(tierRules.hot?.interval_days ?? 1.5)}`,
        },
        {
            key: 'warm',
            count: status.tier_counts?.warm ?? 0,
            ageLabel: `≤${formatDays(tierRules.warm?.max_age_days ?? 90)}`,
            intervalLabel: `every ${formatDays(tierRules.warm?.interval_days ?? 7)}`,
        },
        {
            key: 'cool',
            count: status.tier_counts?.cool ?? 0,
            ageLabel: `≤${formatDays(coolCutoff)}`,
            intervalLabel: `every ${formatDays(tierRules.cool?.interval_days ?? 21)}`,
        },
        {
            key: 'dormant',
            count: status.tier_counts?.dormant ?? 0,
            ageLabel: `>${formatDays(coolCutoff)}`,
            intervalLabel: `every ${formatDays(tierRules.dormant?.interval_days ?? 60)}`,
        },
    ]

    return (
        <div
            className="card"
            style={{
                marginBottom: 0,
                display: 'flex',
                flexDirection: 'column',
                gap: '0.85rem',
            }}
        >
            {/* Card Header: Site name + Enabled badge */}
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '0.5rem',
                    flexWrap: 'wrap',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span
                        className="site-dot"
                        style={{ background: siteInfo.color, width: 9, height: 9 }}
                    />
                    <span style={{ fontWeight: 700, fontSize: '0.98rem' }}>{siteInfo.name}</span>
                    <span
                        style={{
                            fontSize: '0.74rem',
                            color: 'var(--text-faint)',
                            fontFamily: 'var(--font-mono)',
                        }}
                    >
                        ({status.tracked_count} tracked)
                    </span>
                </div>
                <span className={`badge ${status.enabled ? 'badge-success' : 'badge-error'}`}>
                    {status.enabled ? 'Enabled' : 'Disabled'}
                </span>
            </div>

            {/* Active Poll Banner */}
            {status.active_poll && (
                <div
                    style={{
                        padding: '0.6rem 0.75rem',
                        borderRadius: 'var(--radius-md)',
                        background: 'rgba(245, 158, 11, 0.1)',
                        border: '1px solid rgba(245, 158, 11, 0.3)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.3rem',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '0.5rem',
                            fontSize: '0.75rem',
                            color: '#fbbf24',
                            fontWeight: 600,
                        }}
                    >
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                            <Activity size={13} />
                            Currently Checking
                        </span>
                        {status.active_poll.started_at && (
                            <span
                                className="tabular-nums"
                                style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}
                            >
                                Started {formatDateTime(status.active_poll.started_at)}
                            </span>
                        )}
                    </div>
                    <a
                        href={ensureExternalUrl(status.active_poll.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                            color: 'var(--text)',
                            fontWeight: 600,
                            fontSize: '0.84rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                        }}
                        title={status.active_poll.url}
                    >
                        <span
                            style={{
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {status.active_poll.title || status.active_poll.url}
                        </span>
                        <ExternalLink size={11} style={{ flexShrink: 0 }} />
                    </a>
                    <div className="indeterminate-bar" style={{ maxWidth: '100%' }} />
                </div>
            )}

            {/* Daily Check Budget Progress Bar */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.78rem',
                    }}
                >
                    <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>
                        Daily Check Budget (24h)
                    </span>
                    <span
                        className="tabular-nums"
                        style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}
                    >
                        {status.checks_last_24h} / {status.max_checks_per_day}
                        <span style={{ color: 'var(--text-faint)', marginLeft: '0.35rem' }}>
                            ({budgetPct}%)
                        </span>
                    </span>
                </div>
                <div
                    style={{
                        height: 8,
                        width: '100%',
                        borderRadius: 999,
                        background: 'var(--surface2)',
                        border: '1px solid var(--border)',
                        overflow: 'hidden',
                    }}
                    role="progressbar"
                    aria-valuenow={status.checks_last_24h}
                    aria-valuemin={0}
                    aria-valuemax={status.max_checks_per_day}
                    aria-label={`${siteInfo.name} daily check budget`}
                >
                    <div
                        style={{
                            height: '100%',
                            width: `${budgetPct}%`,
                            background: barColor,
                            borderRadius: 999,
                            transition: 'width 0.3s ease',
                        }}
                    />
                </div>
            </div>

            {/* Tier Breakdown */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                <div
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                        gap: '0.45rem',
                    }}
                >
                    {tiers.map(({ key, count, ageLabel, intervalLabel }) => {
                        const st = TIER_STYLES[key]
                        return (
                            <div
                                key={key}
                                style={{
                                    padding: '0.45rem 0.6rem',
                                    borderRadius: 'var(--radius-sm)',
                                    background: st.bg,
                                    border: `1px solid ${st.border}`,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.15rem',
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'baseline',
                                        justifyContent: 'space-between',
                                        gap: '0.35rem',
                                    }}
                                >
                                    <span
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'baseline',
                                            gap: '0.35rem',
                                        }}
                                    >
                                        <span
                                            className="tabular-nums"
                                            style={{
                                                fontSize: '1.02rem',
                                                fontWeight: 700,
                                                color: st.color,
                                                lineHeight: 1.15,
                                            }}
                                        >
                                            {count}
                                        </span>
                                        <span
                                            style={{
                                                fontSize: '0.74rem',
                                                color: st.color,
                                                fontWeight: 700,
                                            }}
                                        >
                                            {st.label}
                                        </span>
                                    </span>
                                    <span
                                        className="tabular-nums"
                                        style={{
                                            fontSize: '0.7rem',
                                            fontFamily: 'var(--font-mono)',
                                            color: 'var(--text-muted)',
                                        }}
                                    >
                                        {ageLabel}
                                    </span>
                                </div>
                                <span
                                    className="tabular-nums"
                                    style={{
                                        fontSize: '0.69rem',
                                        fontFamily: 'var(--font-mono)',
                                        color: 'var(--text-muted)',
                                    }}
                                >
                                    ({intervalLabel})
                                </span>
                            </div>
                        )
                    })}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-faint)', lineHeight: 1.35 }}>
                    Tiers group stories by last update age; stories with regular update history automatically use their detected schedule.
                </div>
            </div>

            {/* Footer: Last Sync & Min Interval */}
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.4rem',
                    paddingTop: '0.55rem',
                    borderTop: '1px solid var(--border)',
                    fontSize: '0.74rem',
                    color: 'var(--text-muted)',
                }}
            >
                <span
                    className="tabular-nums"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
                    title={status.last_sync_at || 'Not yet synced'}
                >
                    <Clock size={12} />
                    Last sync: {formatRelativeTime(status.last_sync_at, nowMs)}
                </span>
                <span
                    className="tabular-nums"
                    style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-faint)' }}
                >
                    Min interval: {status.min_interval_minutes}m
                </span>
            </div>
        </div>
    )
}

export default function Poller() {
    const [status, setStatus] = useState<PollerStatusResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [syncing, setSyncing] = useState(false)
    const [syncFeedback, setSyncFeedback] = useState<{ ok: boolean; text: string } | null>(null)
    const [siteFilter, setSiteFilter] = useState('')
    const [nowMs, setNowMs] = useState(() => Date.now())

    const loadStatus = useCallback(async (showSpinner = false) => {
        if (showSpinner) setLoading(true)
        try {
            const res = await fetchPollerStatus()
            setStatus(res)
            setError(null)
            setNowMs(Date.now())
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Failed to fetch poller status')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        loadStatus(true)
        const refreshId = setInterval(() => {
            loadStatus(false)
        }, AUTO_REFRESH_MS)
        return () => clearInterval(refreshId)
    }, [loadStatus])

    const handleSyncNow = async () => {
        if (syncing) return
        setSyncing(true)
        setSyncFeedback(null)
        try {
            const res = await triggerPollerSync()
            setSyncFeedback({ ok: res.ok, text: res.message })
            // Refresh status shortly after triggering sync
            setTimeout(() => {
                loadStatus(false)
            }, 1000)
        } catch (err: unknown) {
            setSyncFeedback({
                ok: false,
                text: err instanceof Error ? err.message : 'Failed to trigger library sync',
            })
        } finally {
            setSyncing(false)
            setTimeout(() => {
                setSyncFeedback(null)
            }, 5000)
        }
    }

    const siteEntries = useMemo(() => {
        if (!status?.sites) return []
        return Object.entries(status.sites).sort(([a], [b]) => a.localeCompare(b))
    }, [status?.sites])

    const upNextRows = useMemo<UpNextRow[]>(() => {
        const rows: UpNextRow[] = []
        for (const [siteName, siteStatus] of siteEntries) {
            if (siteFilter && siteName !== siteFilter) continue
            for (const item of siteStatus.up_next || []) {
                rows.push({ ...item, site: siteName })
            }
        }
        return rows.sort((a, b) => a.next_check_at.localeCompare(b.next_check_at))
    }, [siteEntries, siteFilter])

    const recentEventRows = useMemo<PollEventItem[]>(() => {
        const rows: PollEventItem[] = []
        for (const [siteName, siteStatus] of siteEntries) {
            if (siteFilter && siteName !== siteFilter) continue
            for (const ev of siteStatus.recent_events || []) {
                rows.push(ev)
            }
        }
        return rows.sort((a, b) => b.checked_at.localeCompare(a.checked_at))
    }, [siteEntries, siteFilter])

    return (
        <div>
            {/* Page Header */}
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
                    <h1
                        style={{
                            fontSize: '1.4rem',
                            fontWeight: 700,
                            letterSpacing: '-0.02em',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}
                    >
                        <Radar size={22} style={{ color: 'var(--accent)' }} />
                        Library Update Poller
                    </h1>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        Adaptive background update checks for Calibre library stories without email alerts
                        {status && (
                            <span style={{ color: 'var(--text-faint)' }}>
                                {' '}
                                · Sync every {status.library_sync_interval_hours}h · Auto-refreshes every 15s
                            </span>
                        )}
                    </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {siteEntries.length > 1 && (
                        <select
                            value={siteFilter}
                            onChange={(e) => setSiteFilter(e.target.value)}
                            aria-label="Filter tables by site"
                            style={{ width: 'auto', minWidth: 150, background: 'var(--surface)' }}
                        >
                            <option value="">All Polled Sites</option>
                            {siteEntries.map(([siteName]) => (
                                <option key={siteName} value={siteName}>
                                    {getSiteBadgeInfo(siteName).name}
                                </option>
                            ))}
                        </select>
                    )}
                    <Link
                        to="/config?section=library_poller"
                        className="btn-link secondary"
                        title="Configure Library Poller settings and per-site budgets"
                    >
                        <Settings size={14} />
                        Configure
                    </Link>
                    <button
                        type="button"
                        onClick={handleSyncNow}
                        disabled={syncing || !status?.enabled}
                        title={
                            status?.enabled
                                ? 'Trigger an immediate Calibre library sync scan'
                                : 'Enable [library_poller] in config.toml to sync'
                        }
                    >
                        <RefreshCw size={14} />
                        {syncing ? 'Syncing…' : 'Sync Now'}
                    </button>
                </div>
            </div>

            {/* Inline Feedback Banner for Sync Now */}
            {syncFeedback && (
                <div
                    style={{
                        marginBottom: '1rem',
                        padding: '0.6rem 0.85rem',
                        borderRadius: 'var(--radius-md)',
                        background: syncFeedback.ok
                            ? 'rgba(16, 185, 129, 0.12)'
                            : 'rgba(239, 68, 68, 0.12)',
                        border: `1px solid ${
                            syncFeedback.ok
                                ? 'rgba(16, 185, 129, 0.35)'
                                : 'rgba(239, 68, 68, 0.35)'
                        }`,
                        color: syncFeedback.ok ? 'var(--success)' : 'var(--error)',
                        fontSize: '0.82rem',
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                    }}
                >
                    {syncFeedback.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                    <span>{syncFeedback.text}</span>
                </div>
            )}

            {/* Error State */}
            {error && (
                <div
                    className="card"
                    style={{
                        borderColor: 'rgba(239, 68, 68, 0.35)',
                        background: 'rgba(239, 68, 68, 0.08)',
                        color: '#fca5a5',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '0.75rem',
                        flexWrap: 'wrap',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <AlertTriangle size={16} style={{ color: 'var(--error)', flexShrink: 0 }} />
                        <span>{error}</span>
                    </div>
                    <button type="button" className="secondary btn-sm" onClick={() => loadStatus(true)}>
                        <RefreshCw size={12} /> Retry
                    </button>
                </div>
            )}

            {loading && !status ? (
                <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                    Loading poller status…
                </div>
            ) : status ? (
                <>
                    {/* Disabled-State Banner */}
                    {!status.enabled && (
                        <div
                            className="card"
                            style={{
                                borderColor: 'rgba(99, 102, 241, 0.35)',
                                background: 'rgba(99, 102, 241, 0.08)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.6rem',
                            }}
                        >
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    fontWeight: 600,
                                    color: '#a5b4fc',
                                    fontSize: '0.92rem',
                                }}
                            >
                                <Info size={17} />
                                <span>Library Update Poller is currently disabled</span>
                            </div>
                            <p style={{ fontSize: '0.83rem', color: 'var(--text-muted)', lineHeight: 1.55 }}>
                                Enable <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>[library_poller]</code> in your{' '}
                                <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>config.toml</code> to automatically check
                                in-progress Calibre stories for new chapters with polite daily check budgets:
                            </p>
                            <pre
                                style={{
                                    margin: 0,
                                    padding: '0.7rem 0.9rem',
                                    borderRadius: 'var(--radius-sm)',
                                    background: 'var(--bg)',
                                    border: '1px solid var(--border)',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '0.76rem',
                                    color: 'var(--text)',
                                    overflowX: 'auto',
                                }}
                            >
{`[library_poller]
enabled = true

[library_poller.sites.fanfiction]
enabled = true
max_checks_per_day = 24
min_interval_minutes = 30`}
                            </pre>
                        </div>
                    )}

                    {/* Per-Site Overview Cards */}
                    {siteEntries.length > 0 ? (
                        <div
                            className="grid grid-2"
                            style={{ marginBottom: '1.5rem' }}
                        >
                            {siteEntries.map(([siteName, siteStatus]) => (
                                <SiteOverviewCard
                                    key={siteName}
                                    site={siteName}
                                    status={siteStatus}
                                    nowMs={nowMs}
                                />
                            ))}
                        </div>
                    ) : (
                        <div
                            className="card"
                            style={{
                                color: 'var(--text-muted)',
                                fontSize: '0.85rem',
                                marginBottom: '1.5rem',
                            }}
                        >
                            No sites are configured under{' '}
                            <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
                                [library_poller.sites.*]
                            </code>{' '}
                            yet.
                        </div>
                    )}

                    {/* Up Next Table */}
                    <div style={{ marginBottom: '1.5rem' }}>
                        <div
                            style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                marginBottom: '0.65rem',
                                gap: '0.5rem',
                                flexWrap: 'wrap',
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
                                <Calendar size={17} style={{ color: 'var(--accent)' }} />
                                Up Next ({upNextRows.length})
                            </h2>
                            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                                Scheduled stories ordered by next check time
                            </span>
                        </div>

                        {upNextRows.length === 0 ? (
                            <div
                                className="card"
                                style={{
                                    padding: '1rem 1.25rem',
                                    color: 'var(--text-muted)',
                                    fontSize: '0.85rem',
                                    marginBottom: 0,
                                }}
                            >
                                No stories scheduled in the poll queue yet.
                            </div>
                        ) : (
                            <>
                                <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>Story</th>
                                                <th>Site</th>
                                                <th>Tier</th>
                                                <th>Last Update</th>
                                                <th>Next Check</th>
                                                <th style={{ textAlign: 'right' }}>Chapters</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {upNextRows.map((item) => (
                                                <tr key={`${item.site}-${item.url}`}>
                                                    <td style={{ maxWidth: 340 }}>
                                                        <div style={{ fontWeight: 600 }}>
                                                            <a
                                                                href={ensureExternalUrl(item.url)}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                style={{ color: 'var(--text)' }}
                                                            >
                                                                {item.title || 'Untitled Story'}
                                                            </a>
                                                        </div>
                                                        <StoryUrlLink url={item.url} />
                                                    </td>
                                                    <td>
                                                        <SiteBadge site={item.site} />
                                                    </td>
                                                    <td>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                                                            <TierBadge tier={item.tier} />
                                                            <CadenceBadge cadenceDays={item.cadence_days} />
                                                        </div>
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
                                                        {formatDateOnly(item.last_update_date)}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.78rem',
                                                            color: 'var(--text-muted)',
                                                            whiteSpace: 'nowrap',
                                                        }}
                                                        title={item.next_check_at}
                                                    >
                                                        {formatRelativeTime(item.next_check_at, nowMs)}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            textAlign: 'right',
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.8rem',
                                                            color: 'var(--text-muted)',
                                                        }}
                                                    >
                                                        {item.known_chapters ?? '—'}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>

                                <div className="mobile-card-list">
                                    {upNextRows.map((item) => (
                                        <div key={`mob-next-${item.site}-${item.url}`} className="mobile-data-card">
                                            <div className="mobile-data-card-header">
                                                <div style={{ minWidth: 0, flex: 1 }}>
                                                    <div style={{ fontWeight: 600 }}>
                                                        <a
                                                            href={ensureExternalUrl(item.url)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            style={{ color: 'var(--text)' }}
                                                        >
                                                            {item.title || 'Untitled Story'}
                                                        </a>
                                                    </div>
                                                    <StoryUrlLink url={item.url} />
                                                </div>
                                                <div
                                                    style={{
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.35rem',
                                                        flexWrap: 'wrap',
                                                        justifyContent: 'flex-end',
                                                        flexShrink: 0,
                                                    }}
                                                >
                                                    <TierBadge tier={item.tier} />
                                                    <CadenceBadge cadenceDays={item.cadence_days} />
                                                </div>
                                            </div>
                                            <div
                                                style={{
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    fontSize: '0.75rem',
                                                    gap: '0.5rem',
                                                    flexWrap: 'wrap',
                                                }}
                                            >
                                                <SiteBadge site={item.site} />
                                                <span
                                                    className="tabular-nums"
                                                    style={{
                                                        color: 'var(--text-muted)',
                                                        fontFamily: 'var(--font-mono)',
                                                    }}
                                                >
                                                    Ch. {item.known_chapters ?? '—'} · Updated {formatDateOnly(item.last_update_date)}
                                                </span>
                                            </div>
                                            <div
                                                className="tabular-nums"
                                                style={{
                                                    fontSize: '0.74rem',
                                                    color: 'var(--text-faint)',
                                                    fontFamily: 'var(--font-mono)',
                                                }}
                                            >
                                                Next check: {formatRelativeTime(item.next_check_at, nowMs)}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>

                    {/* Recently Checked Table */}
                    <div>
                        <div
                            style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                marginBottom: '0.65rem',
                                gap: '0.5rem',
                                flexWrap: 'wrap',
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
                                <Clock size={17} style={{ color: 'var(--accent)' }} />
                                Recently Checked ({recentEventRows.length})
                            </h2>
                            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                                Recent lightweight metadata probe outcomes
                            </span>
                        </div>

                        {recentEventRows.length === 0 ? (
                            <div
                                className="card"
                                style={{
                                    padding: '1rem 1.25rem',
                                    color: 'var(--text-muted)',
                                    fontSize: '0.85rem',
                                    marginBottom: 0,
                                }}
                            >
                                No poll checks have been recorded yet.
                            </div>
                        ) : (
                            <>
                                <div className="table-container table-desktop-only" style={{ background: 'var(--surface)' }}>
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>Story</th>
                                                <th>Site</th>
                                                <th>Outcome</th>
                                                <th style={{ textAlign: 'right' }}>Chapters</th>
                                                <th>Checked At</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {recentEventRows.map((ev) => (
                                                <tr key={ev.id}>
                                                    <td style={{ maxWidth: 340 }}>
                                                        <div style={{ fontWeight: 600 }}>
                                                            <a
                                                                href={ensureExternalUrl(ev.url)}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                style={{ color: 'var(--text)' }}
                                                            >
                                                                {ev.title || 'Untitled Story'}
                                                            </a>
                                                        </div>
                                                        <StoryUrlLink url={ev.url} />
                                                    </td>
                                                    <td>
                                                        <SiteBadge site={ev.site} />
                                                    </td>
                                                    <td style={{ maxWidth: 280 }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                                                            <OutcomeBadge outcome={ev.outcome} />
                                                        </div>
                                                        {ev.error_message && (
                                                            <div
                                                                title={ev.error_message}
                                                                style={{
                                                                    marginTop: '0.2rem',
                                                                    fontSize: '0.72rem',
                                                                    color: '#fca5a5',
                                                                    whiteSpace: 'nowrap',
                                                                    overflow: 'hidden',
                                                                    textOverflow: 'ellipsis',
                                                                    maxWidth: 260,
                                                                }}
                                                            >
                                                                {summarizeError(ev.error_message)}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            textAlign: 'right',
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.8rem',
                                                            color: 'var(--text-muted)',
                                                        }}
                                                    >
                                                        {ev.remote_chapters ?? '—'}
                                                    </td>
                                                    <td
                                                        className="tabular-nums"
                                                        style={{
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.78rem',
                                                            color: 'var(--text-muted)',
                                                            whiteSpace: 'nowrap',
                                                        }}
                                                        title={ev.checked_at}
                                                    >
                                                        {formatRelativeTime(ev.checked_at, nowMs)}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>

                                <div className="mobile-card-list">
                                    {recentEventRows.map((ev) => (
                                        <div key={`mob-ev-${ev.id}`} className="mobile-data-card">
                                            <div className="mobile-data-card-header">
                                                <div style={{ minWidth: 0, flex: 1 }}>
                                                    <div style={{ fontWeight: 600 }}>
                                                        <a
                                                            href={ensureExternalUrl(ev.url)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            style={{ color: 'var(--text)' }}
                                                        >
                                                            {ev.title || 'Untitled Story'}
                                                        </a>
                                                    </div>
                                                    <StoryUrlLink url={ev.url} />
                                                </div>
                                                <OutcomeBadge outcome={ev.outcome} />
                                            </div>
                                            {ev.error_message && (
                                                <div
                                                    title={ev.error_message}
                                                    style={{
                                                        padding: '0.35rem 0.55rem',
                                                        borderRadius: 'var(--radius-sm)',
                                                        background: 'rgba(239, 68, 68, 0.08)',
                                                        border: '1px solid rgba(239, 68, 68, 0.22)',
                                                        color: '#fca5a5',
                                                        fontSize: '0.74rem',
                                                    }}
                                                >
                                                    {summarizeError(ev.error_message)}
                                                </div>
                                            )}
                                            <div
                                                style={{
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    fontSize: '0.75rem',
                                                    gap: '0.5rem',
                                                    flexWrap: 'wrap',
                                                }}
                                            >
                                                <SiteBadge site={ev.site} />
                                                <span
                                                    className="tabular-nums"
                                                    style={{
                                                        color: 'var(--text-muted)',
                                                        fontFamily: 'var(--font-mono)',
                                                    }}
                                                >
                                                    Ch. {ev.remote_chapters ?? '—'} · {formatRelativeTime(ev.checked_at, nowMs)}
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>
                </>
            ) : null}
        </div>
    )
}
