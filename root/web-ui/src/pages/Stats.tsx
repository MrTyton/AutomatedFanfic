import { useState, useEffect } from 'react'
import {
    BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
    type PieLabelRenderProps
} from 'recharts'
import { getStats, type StatsResponse } from '../api'
import { STATUS_COLORS as COLORS, PIE_COLORS } from '../statusColors'

type Period = '24h' | '7d' | '30d'
type DistView = 'hourly' | 'weekly' | 'monthly'

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function formatPct(num: number, denom: number): string {
    if (denom === 0) return '—'
    return `${((num / denom) * 100).toFixed(1)}%`
}

function fillDays(data: { date: string; total: number; success: number; failed: number }[], period: Period) {
    if (data.length === 0) return data
    const days = period === '24h' ? 1 : period === '7d' ? 7 : 30
    const end = new Date()
    const map = new Map(data.map(d => [d.date, d]))
    const filled: typeof data = []
    for (let i = days - 1; i >= 0; i--) {
        const d = new Date(end)
        d.setDate(d.getDate() - i)
        const key = d.toISOString().slice(0, 10)
        filled.push(map.get(key) ?? { date: key, total: 0, success: 0, failed: 0 })
    }
    return filled
}

function loadPeriod(): Period {
    const saved = localStorage.getItem('stats-period')
    return saved === '24h' || saved === '7d' || saved === '30d' ? saved : '24h'
}

export default function Stats() {
    const [period, _setPeriod] = useState<Period>(loadPeriod)
    const setPeriod = (p: Period) => { localStorage.setItem('stats-period', p); _setPeriod(p) }
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

    if (loading) return <p>Loading stats…</p>
    if (!stats || stats.error) return <p>Failed to load stats.</p>

    const timeData = fillDays(stats.downloads_over_time, period)
    const siteAxisWidth = Math.min(200, Math.max(120, ...(stats.downloads_by_site.map(s => s.site.length * 7.5))))

    return (
        <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                <h1>Stats</h1>
                <div className="period-toggle">
                    {(['24h', '7d', '30d'] as Period[]).map(p => (
                        <button
                            key={p}
                            className={p === period ? '' : 'secondary'}
                            onClick={() => setPeriod(p)}
                        >
                            {p}
                        </button>
                    ))}
                </div>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-4">
                <div className="card">
                    <h2>Total Downloads</h2>
                    <div className="stat">{stats.total_downloads.toLocaleString()}</div>
                    <div className="stat-label">
                        {formatPct(stats.total_success, stats.total_downloads)} success rate
                    </div>
                </div>
                <div className="card">
                    <h2>Downloads ({period})</h2>
                    <div className="stat">{stats.period_downloads.toLocaleString()}</div>
                    <div className="stat-label">
                        {stats.period_success} success · {stats.period_failed} failed
                    </div>
                </div>
                <div className="card">
                    <h2>Retry Rate</h2>
                    <div className="stat">
                        {formatPct(stats.downloads_with_retries, stats.total_downloads)}
                    </div>
                    <div className="stat-label">
                        {stats.total_retries.toLocaleString()} total retries
                    </div>
                </div>
                <div className="card">
                    <h2>Avg Retries to Success</h2>
                    <div className="stat">{stats.avg_retries_to_success}</div>
                    <div className="stat-label">per successful download</div>
                </div>
            </div>

            {/* Downloads Over Time */}
            <div className="card">
                <h2>Downloads Over Time</h2>
                {timeData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={timeData}>
                            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                            <XAxis
                                dataKey="date"
                                stroke={COLORS.muted}
                                tick={{ fill: COLORS.muted, fontSize: 12 }}
                                tickFormatter={d => new Date(d + 'T00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                            />
                            <YAxis stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                            <Tooltip
                                contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                labelStyle={{ color: '#eee' }}
                            />
                            <Legend />
                            <Bar dataKey="success" stackId="a" fill={COLORS.success} name="Success" />
                            <Bar dataKey="failed" stackId="a" fill={COLORS.failed} name="Failed" />
                        </BarChart>
                    </ResponsiveContainer>
                ) : (
                    <p style={{ color: COLORS.muted }}>No data for this period.</p>
                )}
            </div>

            {/* Two-column: Site Breakdown + Status Pie */}
            <div className="grid grid-2">
                <div className="card">
                    <h2>Downloads by Site</h2>
                    {stats.downloads_by_site.length > 0 ? (
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={stats.downloads_by_site} layout="vertical">
                                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                                <XAxis type="number" stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                                <YAxis type="category" dataKey="site" stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} width={siteAxisWidth} />
                                <Tooltip
                                    contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                    labelStyle={{ color: '#eee' }}
                                />
                                <Legend />
                                <Bar dataKey="success" stackId="a" fill={COLORS.success} name="Success" />
                                <Bar dataKey="failed" stackId="a" fill={COLORS.failed} name="Failed" />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <p style={{ color: COLORS.muted }}>No site data available.</p>
                    )}
                </div>
                <div className="card">
                    <h2>Status Breakdown</h2>
                    {stats.status_breakdown.length > 0 ? (
                        <ResponsiveContainer width="100%" height={300}>
                            <PieChart>
                                <Pie
                                    data={stats.status_breakdown}
                                    dataKey="count"
                                    nameKey="status"
                                    cx="50%"
                                    cy="50%"
                                    outerRadius={100}
                                    label={(props: PieLabelRenderProps) => `${props.name ?? ''}: ${props.value ?? 0}`}
                                >
                                    {stats.status_breakdown.map((_, i) => (
                                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip
                                    contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                    labelStyle={{ color: '#eee' }}
                                />
                            </PieChart>
                        </ResponsiveContainer>
                    ) : (
                        <p style={{ color: COLORS.muted }}>No status data available.</p>
                    )}
                </div>
            </div>

            {/* Two-column: Time Distribution (toggled) + Retry Distribution */}
            <div className="grid grid-2">
                <div className="card">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                        <h2 style={{ margin: 0 }}>
                            {distView === 'hourly' ? 'Hourly' : distView === 'weekly' ? 'Day of Week' : 'Day of Month'} Distribution (All Time)
                        </h2>
                        <div className="period-toggle">
                            {(['hourly', 'weekly', 'monthly'] as DistView[]).map(v => (
                                <button
                                    key={v}
                                    className={v === distView ? '' : 'secondary'}
                                    onClick={() => setDistView(v)}
                                    style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
                                >
                                    {v === 'hourly' ? 'Hour' : v === 'weekly' ? 'Weekday' : 'Month Day'}
                                </button>
                            ))}
                        </div>
                    </div>

                    {distView === 'hourly' && (
                        stats.hourly_distribution.length > 0 ? (
                            <ResponsiveContainer width="100%" height={250}>
                                <BarChart data={stats.hourly_distribution}>
                                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                                    <XAxis
                                        dataKey="hour"
                                        stroke={COLORS.muted}
                                        tick={{ fill: COLORS.muted, fontSize: 12 }}
                                        tickFormatter={h => `${h}:00`}
                                    />
                                    <YAxis stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                                    <Tooltip
                                        contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                        labelStyle={{ color: '#eee' }}
                                        labelFormatter={h => `${h}:00 – ${h}:59`}
                                    />
                                    <Bar dataKey="count" fill={COLORS.accent} name="Downloads" />
                                </BarChart>
                            </ResponsiveContainer>
                        ) : (
                            <p style={{ color: COLORS.muted }}>No hourly data available.</p>
                        )
                    )}

                    {distView === 'weekly' && (
                        stats.weekly_distribution.length > 0 ? (
                            <ResponsiveContainer width="100%" height={250}>
                                <BarChart data={stats.weekly_distribution}>
                                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                                    <XAxis
                                        dataKey="day_of_week"
                                        stroke={COLORS.muted}
                                        tick={{ fill: COLORS.muted, fontSize: 12 }}
                                        tickFormatter={d => DAY_NAMES[d] ?? String(d)}
                                    />
                                    <YAxis stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                                    <Tooltip
                                        contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                        labelStyle={{ color: '#eee' }}
                                        labelFormatter={d => DAY_NAMES[d as number] ?? String(d)}
                                    />
                                    <Bar dataKey="count" fill={COLORS.accent} name="Downloads" />
                                </BarChart>
                            </ResponsiveContainer>
                        ) : (
                            <p style={{ color: COLORS.muted }}>No weekly data available.</p>
                        )
                    )}

                    {distView === 'monthly' && (
                        stats.monthly_distribution.length > 0 ? (
                            <ResponsiveContainer width="100%" height={250}>
                                <BarChart data={stats.monthly_distribution}>
                                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                                    <XAxis
                                        dataKey="day_of_month"
                                        stroke={COLORS.muted}
                                        tick={{ fill: COLORS.muted, fontSize: 12 }}
                                    />
                                    <YAxis stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                                    <Tooltip
                                        contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                        labelStyle={{ color: '#eee' }}
                                        labelFormatter={d => `Day ${d}`}
                                    />
                                    <Bar dataKey="count" fill={COLORS.accent} name="Downloads" />
                                </BarChart>
                            </ResponsiveContainer>
                        ) : (
                            <p style={{ color: COLORS.muted }}>No monthly data available.</p>
                        )
                    )}
                </div>
                <div className="card">
                    <h2>Retry Distribution</h2>
                    {stats.retry_distribution.length > 0 ? (
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={stats.retry_distribution}>
                                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.surface2} />
                                <XAxis
                                    dataKey="attempt_number"
                                    stroke={COLORS.muted}
                                    tick={{ fill: COLORS.muted, fontSize: 12 }}
                                    label={{ value: 'Attempt #', fill: COLORS.muted, position: 'insideBottom', offset: -5 }}
                                />
                                <YAxis stroke={COLORS.muted} tick={{ fill: COLORS.muted, fontSize: 12 }} allowDecimals={false} />
                                <Tooltip
                                    contentStyle={{ background: '#16213e', border: '1px solid #0f3460', borderRadius: 6 }}
                                    labelStyle={{ color: '#eee' }}
                                    labelFormatter={n => `Attempt #${n}`}
                                />
                                <Line type="monotone" dataKey="count" stroke={COLORS.accent} strokeWidth={2} dot={{ fill: COLORS.accent }} name="Retries" />
                            </LineChart>
                        </ResponsiveContainer>
                    ) : (
                        <p style={{ color: COLORS.muted }}>No retry data available.</p>
                    )}
                </div>
            </div>

            {/* Site Details Table */}
            {stats.downloads_by_site.length > 0 && (
                <div className="card">
                    <h2>Site Details</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Site</th>
                                <th>Total</th>
                                <th>Success</th>
                                <th>Failed</th>
                                <th>Success Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                            {stats.downloads_by_site.map(s => (
                                <tr key={s.site}>
                                    <td>{s.site}</td>
                                    <td>{s.total}</td>
                                    <td style={{ color: COLORS.success }}>{s.success}</td>
                                    <td style={{ color: COLORS.failed }}>{s.failed}</td>
                                    <td>{formatPct(s.success, s.total)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    )
}
