import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
    BarChart,
    Bar,
    LineChart,
    Line,
    PieChart,
    Pie,
    Cell,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    Legend,
} from 'recharts'
import {
    TrendingUp,
    CheckCircle2,
    RotateCw,
    Percent,
    Calendar,
    Globe,
    Clock,
} from 'lucide-react'
import { getStats, type StatsResponse } from '../api'
import { getStatusColor } from '../utils/dashboardLogic'
import { getSiteBadgeInfo } from '../statusColors'

type Period = '24h' | '7d' | '30d'
type DistView = 'hourly' | 'weekly' | 'monthly'

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function formatPct(num: number, denom: number): string {
    if (denom === 0) return '—'
    return `${((num / denom) * 100).toFixed(1)}%`
}

function loadPeriod(): Period {
    const saved = localStorage.getItem('stats-period-v2')
    return saved === '24h' || saved === '7d' || saved === '30d' ? saved : '7d'
}

function formatTimelineTick(val: string): string {
    if (val.includes(':')) return val
    const date = new Date(val + 'T00:00')
    if (isNaN(date.getTime())) return val
    return date.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' })
}

function formatStatusLabel(status: string): string {
    if (!status) return 'Unknown'
    return status.charAt(0).toUpperCase() + status.slice(1)
}

export default function Stats() {
    const navigate = useNavigate()
    const [period, _setPeriod] = useState<Period>(loadPeriod)
    const setPeriod = (p: Period) => {
        localStorage.setItem('stats-period-v2', p)
        _setPeriod(p)
    }
    const [distView, setDistView] = useState<DistView>('hourly')
    const [stats, setStats] = useState<StatsResponse | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        setLoading(true)
        getStats(period)
            .then(setStats)
            .catch(() => setStats(null))
            .finally(() => setLoading(false))
    }, [period])

    if (loading) {
        return (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                Loading performance metrics…
            </div>
        )
    }

    if (!stats || stats.error) {
        return (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--error)' }}>
                Failed to load statistics.
            </div>
        )
    }

    const timeData = stats.downloads_over_time

    return (
        <>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '1.25rem',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                }}
            >
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                        Download Performance & Analytics
                    </h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.84rem' }}>
                        Ingestion rates, site breakdowns, and retry efficiency trends ({period.toUpperCase()} window)
                    </p>
                </div>

                <div className="segmented-control" style={{ width: 'auto' }}>
                    {(['24h', '7d', '30d'] as Period[]).map((p) => (
                        <button
                            key={p}
                            type="button"
                            className={`segmented-btn ${p === period ? 'active' : ''}`}
                            onClick={() => setPeriod(p)}
                        >
                            {p.toUpperCase()}
                        </button>
                    ))}
                </div>
            </div>

            {/* KPI Stat Cards Grid */}
            <div className="grid grid-4" style={{ marginBottom: '1.25rem' }}>
                <div className="stat-card">
                    <div className="stat-header">
                        <span>Total Processed</span>
                        <TrendingUp size={16} color="var(--accent)" />
                    </div>
                    <div className="stat-value">{stats.total_downloads}</div>
                    <div className="stat-footer">
                        <span>{formatPct(stats.total_success, stats.total_downloads)} all-time success</span>
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-header">
                        <span>Downloads ({period.toUpperCase()})</span>
                        <CheckCircle2 size={16} color="var(--success)" />
                    </div>
                    <div className="stat-value">{stats.period_downloads}</div>
                    <div className="stat-footer">
                        <span style={{ color: 'var(--success)' }}>{stats.period_success} ok</span>
                        <span>·</span>
                        <span style={{ color: 'var(--error)' }}>{stats.period_failed} failed</span>
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-header">
                        <span>Retries ({period.toUpperCase()})</span>
                        <RotateCw size={16} color="var(--warning)" />
                    </div>
                    <div className="stat-value">{stats.total_retries}</div>
                    <div className="stat-footer">
                        <span>{stats.downloads_with_retries} stories required backoff</span>
                    </div>
                </div>

                <div className="stat-card">
                    <div className="stat-header">
                        <span>Avg Retries / Story</span>
                        <Percent size={16} color="var(--info)" />
                    </div>
                    <div className="stat-value">{stats.avg_retries_to_success}</div>
                    <div className="stat-footer">
                        <span>Attempts per retried story</span>
                    </div>
                </div>
            </div>

            {/* Downloads Over Time Chart */}
            <div className="card" style={{ minWidth: 0 }}>
                <div className="card-header">
                    <h2>
                        <Calendar size={18} color="var(--accent)" />
                        <span>
                            Downloads Timeline ({period === '24h' ? 'Hourly — Past 24h' : `Daily — Past ${period.toUpperCase()}`})
                        </span>
                    </h2>
                </div>
                <div style={{ height: 260, width: '100%', minWidth: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={timeData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                            <XAxis
                                dataKey="date"
                                stroke="var(--text-faint)"
                                tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                                tickFormatter={formatTimelineTick}
                            />
                            <YAxis
                                stroke="var(--text-faint)"
                                tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                                allowDecimals={false}
                            />
                            <Tooltip
                                contentStyle={{
                                    background: '#111827',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    borderRadius: 8,
                                    color: '#f8fafc',
                                }}
                            />
                            <Legend wrapperStyle={{ paddingTop: 8, fontSize: 12 }} />
                            <Bar dataKey="success" stackId="a" fill="var(--success)" radius={[0, 0, 0, 0]} name="Successful" />
                            <Bar dataKey="failed" stackId="a" fill="var(--error)" radius={[4, 4, 0, 0]} name="Failed" />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* Two Column Grid */}
            <div className="grid grid-2" style={{ marginBottom: '1.25rem' }}>
                {/* Downloads by Site */}
                <div className="card" style={{ minWidth: 0 }}>
                    <div className="card-header">
                        <h2>
                            <Globe size={18} color="var(--info)" />
                            <span>Site Breakdown ({period.toUpperCase()})</span>
                        </h2>
                        <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                            Click a bar to view site history
                        </span>
                    </div>
                    <div style={{ height: 260, width: '100%', minWidth: 0 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                                data={stats.downloads_by_site}
                                layout="vertical"
                                margin={{ top: 10, right: 15, left: 10, bottom: 0 }}
                            >
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                                <XAxis
                                    type="number"
                                    stroke="var(--text-faint)"
                                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                                    allowDecimals={false}
                                />
                                <YAxis
                                    type="category"
                                    dataKey="site"
                                    stroke="var(--text-faint)"
                                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                                    width={100}
                                />
                                <Tooltip
                                    contentStyle={{
                                        background: '#111827',
                                        border: '1px solid rgba(255,255,255,0.1)',
                                        borderRadius: 8,
                                        color: '#f8fafc',
                                    }}
                                />
                                <Legend wrapperStyle={{ paddingTop: 8, fontSize: 12 }} />
                                <Bar
                                    dataKey="success"
                                    stackId="a"
                                    fill="var(--success)"
                                    name="Success"
                                    style={{ cursor: 'pointer' }}
                                    onClick={(entry: unknown) => {
                                        const item = entry as { site?: string; payload?: { site?: string } } | undefined
                                        const site = item?.site || item?.payload?.site
                                        if (site) {
                                            navigate(`/history?site=${encodeURIComponent(String(site))}`)
                                        }
                                    }}
                                />
                                <Bar
                                    dataKey="failed"
                                    stackId="a"
                                    fill="var(--error)"
                                    name="Failed"
                                    style={{ cursor: 'pointer' }}
                                    onClick={(entry: unknown) => {
                                        const item = entry as { site?: string; payload?: { site?: string } } | undefined
                                        const site = item?.site || item?.payload?.site
                                        if (site) {
                                            navigate(`/history?site=${encodeURIComponent(String(site))}&status=failed`)
                                        }
                                    }}
                                />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Status Breakdown Pie */}
                <div className="card" style={{ minWidth: 0 }}>
                    <div className="card-header">
                        <h2>
                            <CheckCircle2 size={18} color="var(--success)" />
                            <span>Status Distribution ({period.toUpperCase()})</span>
                        </h2>
                        <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
                            Click slice to filter history
                        </span>
                    </div>
                    <div style={{ height: 260, width: '100%', minWidth: 0 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={stats.status_breakdown.map((s) => ({
                                        ...s,
                                        displayStatus: formatStatusLabel(s.status),
                                    }))}
                                    dataKey="count"
                                    nameKey="displayStatus"
                                    cx="50%"
                                    cy="46%"
                                    innerRadius={52}
                                    outerRadius={82}
                                    paddingAngle={3}
                                    style={{ cursor: 'pointer' }}
                                    onClick={(entry: unknown) => {
                                        const item = entry as { status?: string; payload?: { status?: string } } | undefined
                                        const status = item?.status || item?.payload?.status
                                        if (status) {
                                            navigate(`/history?status=${encodeURIComponent(String(status))}`)
                                        }
                                    }}
                                    label={(props: { name?: string; value?: number }) =>
                                        `${props.name || ''}: ${props.value ?? 0}`
                                    }
                                >
                                    {stats.status_breakdown.map((entry, i) => (
                                        <Cell key={`${entry.status}-${i}`} fill={getStatusColor(entry.status)} />
                                    ))}
                                </Pie>
                                <Tooltip
                                    contentStyle={{
                                        background: '#111827',
                                        border: '1px solid rgba(255,255,255,0.1)',
                                        borderRadius: 8,
                                        color: '#f8fafc',
                                    }}
                                />
                                <Legend wrapperStyle={{ fontSize: 12 }} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* Time Distribution and Retries */}
            <div className="grid grid-2">
                {/* Time Distribution */}
                <div className="card" style={{ minWidth: 0 }}>
                    <div className="card-header">
                        <h2>
                            <Clock size={18} color="var(--warning)" />
                            <span>Hourly & Daily Patterns</span>
                        </h2>
                        <div className="segmented-control" style={{ width: 'auto' }}>
                            {(['hourly', 'weekly', 'monthly'] as DistView[]).map((v) => (
                                <button
                                    key={v}
                                    type="button"
                                    className={`segmented-btn ${distView === v ? 'active' : ''}`}
                                    onClick={() => setDistView(v)}
                                    style={{ padding: '0.2rem 0.55rem', fontSize: '0.73rem', minHeight: 28 }}
                                >
                                    {v === 'hourly' ? 'Hour' : v === 'weekly' ? 'Weekday' : 'Month'}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div style={{ height: 230, width: '100%', minWidth: 0 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            {distView === 'hourly' ? (
                                <BarChart data={stats.hourly_distribution} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                                    <XAxis
                                        dataKey="hour"
                                        stroke="var(--text-faint)"
                                        tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                                        tickFormatter={(h) => `${h}:00`}
                                    />
                                    <YAxis stroke="var(--text-faint)" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }} />
                                    <Bar dataKey="count" fill="var(--accent)" name="Downloads" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            ) : distView === 'weekly' ? (
                                <BarChart data={stats.weekly_distribution} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                                    <XAxis
                                        dataKey="day_of_week"
                                        stroke="var(--text-faint)"
                                        tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                                        tickFormatter={(d) => DAY_NAMES[d] ?? String(d)}
                                    />
                                    <YAxis stroke="var(--text-faint)" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }} />
                                    <Bar dataKey="count" fill="var(--accent)" name="Downloads" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            ) : (
                                <BarChart data={stats.monthly_distribution} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                                    <XAxis dataKey="day_of_month" stroke="var(--text-faint)" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                                    <YAxis stroke="var(--text-faint)" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} allowDecimals={false} />
                                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }} />
                                    <Bar dataKey="count" fill="var(--accent)" name="Downloads" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            )}
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Retry Distribution */}
                <div className="card" style={{ minWidth: 0 }}>
                    <div className="card-header">
                        <h2>
                            <RotateCw size={18} color="var(--info)" />
                            <span>Retry Attempts Distribution ({period.toUpperCase()})</span>
                        </h2>
                    </div>

                    <div style={{ height: 230, width: '100%', minWidth: 0 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={stats.retry_distribution} margin={{ top: 10, right: 15, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
                                <XAxis
                                    dataKey="attempt_number"
                                    stroke="var(--text-faint)"
                                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                                    label={{ value: 'Attempt #', fill: 'var(--text-muted)', position: 'insideBottom', offset: -4 }}
                                />
                                <YAxis stroke="var(--text-faint)" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} allowDecimals={false} />
                                <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }} />
                                <Line
                                    type="monotone"
                                    dataKey="count"
                                    stroke="var(--accent)"
                                    strokeWidth={2.5}
                                    dot={{ fill: 'var(--accent)', r: 4 }}
                                    name="Retries"
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* Site Performance & Failure Breakdown Table */}
            <div className="card" style={{ marginTop: '1.25rem' }}>
                <div className="card-header">
                    <h2>
                        <Globe size={18} color="var(--accent)" />
                        <span>Site Adapter Performance & Failure Diagnostics ({period.toUpperCase()})</span>
                    </h2>
                </div>
                <div className="table-container" style={{ border: 'none' }}>
                    <table>
                        <thead>
                            <tr>
                                <th>Site Adapter</th>
                                <th>Total</th>
                                <th>Success Rate</th>
                                <th>Avg Duration</th>
                                <th>Primary Failure Reason</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stats.downloads_by_site.map((row) => {
                                const info = getSiteBadgeInfo(row.site)
                                return (
                                    <tr
                                        key={row.site}
                                        onClick={() => navigate(`/history?site=${encodeURIComponent(row.site)}`)}
                                        style={{ cursor: 'pointer' }}
                                        title={`Click to filter History by ${info.name}`}
                                    >
                                        <td>
                                            <span className="site-badge" style={{ color: 'var(--text)' }}>
                                                <span className="site-dot" style={{ background: info.color }} />
                                                <span>{info.name}</span>
                                            </span>
                                        </td>
                                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{row.total}</td>
                                        <td style={{ fontFamily: 'var(--font-mono)', color: row.failed > 0 ? 'var(--warning)' : 'var(--success)' }}>
                                            {formatPct(row.success, row.total)} ({row.success}/{row.total})
                                        </td>
                                        <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                                            {row.avg_duration_sec ? `${row.avg_duration_sec}s` : '—'}
                                        </td>
                                        <td style={{ fontSize: '0.76rem', color: row.top_error ? '#fca5a5' : 'var(--text-faint)' }}>
                                            {row.top_error || 'No failures in window'}
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </>
    )
}
