import { useState, useEffect, useRef, type ReactNode } from 'react'
import type { DashboardSnapshot } from '../hooks/useWebSocket'
import { addUrls, type AddUrlResult } from '../api'

interface Props {
    data: DashboardSnapshot | null
}

interface RecentEvent {
    event_type?: string
    url?: string
    site?: string
    title?: string
    status?: string
    calibre_id?: string
    completed_at?: string
    action?: string
    attempt_number?: number
    timestamp?: string
    body?: string
    provider?: string
}

interface WaitingUrl {
    url: string
    updated_at?: string
}

function extractSite(url: string): string {
    try {
        const u = url.startsWith('http') ? url : `https://${url}`
        const host = new URL(u).hostname.replace('www.', '')
        return host.split('.')[0]
    } catch {
        return '—'
    }
}

function urlLink(url: string): ReactNode {
    const href = url.startsWith('http') ? url : `https://${url}`
    return <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--text-muted)' }}>{url}</a>
}

function formatEvent(evt: RecentEvent): { icon: string; text: ReactNode; time: string } | null {
    const time = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ''

    if (evt.event_type === 'download') {
        const title = evt.title || evt.url || 'Unknown'
        const site = evt.site || '—'
        if (evt.status === 'success') return { icon: '✓', text: <>({site}) {title}</>, time }
        if (evt.status === 'failed') return { icon: '✗', text: <>({site}) Failed: {title}</>, time }
        if (evt.status === 'pending') return { icon: '↓', text: <>({site}) Processing {evt.url ? urlLink(evt.url) : title}</>, time }
        return { icon: '↓', text: <>({site}) {title}</>, time }
    }
    if (evt.event_type === 'retry') {
        const site = evt.site || '—'
        return { icon: '↻', text: <>({site}) Retry #{evt.attempt_number ?? '?'} — {evt.action ?? 'requeue'} — {evt.url ? urlLink(evt.url) : site}</>, time }
    }
    if (evt.event_type === 'notification') {
        return { icon: '🔔', text: <>{evt.title}: {evt.body || ''}</>, time }
    }
    return null
}

export default function Dashboard({ data }: Props) {
    const [urlText, setUrlText] = useState('')
    const [results, setResults] = useState<AddUrlResult[]>([])
    const [loading, setLoading] = useState(false)
    const resultTimer = useRef<number>(0)

    // Clear results after 5 seconds
    useEffect(() => {
        if (results.length > 0) {
            clearTimeout(resultTimer.current)
            resultTimer.current = window.setTimeout(() => setResults([]), 5000)
        }
        return () => clearTimeout(resultTimer.current)
    }, [results])

    const handleAddUrls = async (e: React.FormEvent) => {
        e.preventDefault()
        const urls = urlText.split('\n').map(u => u.trim()).filter(Boolean)
        if (urls.length === 0) return
        setLoading(true)
        setResults([])
        try {
            const res = await addUrls(urls)
            setResults(res.results)
            const allAccepted = res.results.every(r => r.accepted)
            if (allAccepted) setUrlText('')
        } catch (err) {
            setResults([{ accepted: false, message: String(err) }])
        } finally {
            setLoading(false)
        }
    }

    if (!data) return <p>Waiting for data…</p>

    const activeUrls = data.active_downloads.items
    const activeCount = data.active_downloads.count
    const ingressDepth = typeof data.queues.ingress === 'number' ? data.queues.ingress : 0
    const waitingData = data.waiting_downloads ?? { items: [], count: 0 }
    const waitingItems: WaitingUrl[] = typeof waitingData === 'object' && waitingData !== null
        ? (waitingData as { items: WaitingUrl[]; count: number }).items ?? []
        : []
    const waitingCount = typeof waitingData === 'object' && waitingData !== null
        ? (waitingData as { items: WaitingUrl[]; count: number }).count ?? 0
        : 0

    // Recent completed downloads (separate feed, not diluted by other events)
    const recentDownloads = (data.recent_downloads as RecentEvent[])
        .filter(e => e.status !== 'pending' && e.status !== 'waiting')

    // Build activity feed from activity events only (retries, email checks).
    // Downloads have their own table above; notifications are excluded to
    // prevent them from drowning out other event types.
    const activityEvents = (data.recent_activity as RecentEvent[])
        .map(formatEvent)
        .filter((e): e is { icon: string; text: ReactNode; time: string } =>
            e !== null && e.text != null)
        .sort((a, b) => b.time.localeCompare(a.time))
        .slice(0, 20)

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>Dashboard</h1>

            {/* Stat cards */}
            <div className="grid grid-3">
                <div className="card">
                    <h2>Active Downloads</h2>
                    <div className="stat">{activeCount}</div>
                </div>
                <div className="card">
                    <h2>Ingress Queue</h2>
                    <div className="stat">{ingressDepth}</div>
                </div>
                <div className="card">
                    <h2>Waiting Queue</h2>
                    <div className="stat">{waitingCount}</div>
                </div>
            </div>

            {/* Add URLs */}
            <div className="card">
                <h2>Add URLs</h2>
                <form onSubmit={handleAddUrls}>
                    <textarea
                        value={urlText}
                        onChange={e => setUrlText(e.target.value)}
                        onKeyDown={e => {
                            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                e.preventDefault()
                                handleAddUrls(e as unknown as React.FormEvent)
                            }
                        }}
                        placeholder={"Paste one or more URLs, one per line\nhttps://archiveofourown.org/works/12345\nhttps://www.royalroad.com/fiction/12345"}
                        rows={3}
                        style={{ resize: 'vertical', marginBottom: '0.5rem' }}
                    />
                    <button type="submit" disabled={loading}>
                        {loading ? 'Adding…' : 'Add to Queue'}
                    </button>
                </form>
                {results.length > 0 && (
                    <div style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
                        {results.map((r, i) => (
                            <p key={i} style={{ color: r.accepted ? 'var(--success)' : 'var(--error)', margin: '0.2rem 0' }}>
                                {r.message}
                            </p>
                        ))}
                    </div>
                )}
            </div>

            {/* Combined Downloads: Currently Processing + Recent Completed */}
            <div className="card">
                <h2>Downloads</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>Site</th>
                            <th>Title / URL</th>
                            <th>Story ID</th>
                            <th>Time</th>
                        </tr>
                    </thead>
                    <tbody>
                        {/* Active downloads (truly processing) */}
                        {activeUrls.map((url) => (
                            <tr key={`active-${url}`}>
                                <td><span className="badge badge-warning">processing</span></td>
                                <td>{extractSite(url)}</td>
                                <td>
                                    <a href={url.startsWith('http') ? url : `https://${url}`} target="_blank" rel="noreferrer">
                                        {url}
                                    </a>
                                </td>
                                <td>—</td>
                                <td></td>
                            </tr>
                        ))}
                        {/* Waiting downloads (retry backoff) */}
                        {waitingItems.map((w) => (
                            <tr key={`waiting-${w.url}`}>
                                <td><span className="badge badge-info">waiting</span></td>
                                <td>{extractSite(w.url)}</td>
                                <td>
                                    <a href={w.url.startsWith('http') ? w.url : `https://${w.url}`} target="_blank" rel="noreferrer">
                                        {w.url}
                                    </a>
                                </td>
                                <td>—</td>
                                <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                                    {w.updated_at ? new Date(w.updated_at).toLocaleString() : '—'}
                                </td>
                            </tr>
                        ))}
                        {/* Recent completed downloads */}
                        {recentDownloads.map((dl, i) => (
                            <tr key={`dl-${i}`}>
                                <td>
                                    <span className={`badge ${dl.status === 'success' ? 'badge-success' : dl.status === 'failed' ? 'badge-error' : dl.status === 'waiting' ? 'badge-info' : dl.status === 'abandoned' ? 'badge-error' : 'badge-warning'}`}>
                                        {dl.status}
                                    </span>
                                </td>
                                <td>{dl.site || extractSite(dl.url || '')}</td>
                                <td>
                                    {dl.title ? (
                                        <><strong>{dl.title}</strong>{' '}
                                            <a href={(dl.url || '').startsWith('http') ? dl.url! : `https://${dl.url}`} target="_blank" rel="noreferrer" style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                                                {dl.url}
                                            </a>
                                        </>
                                    ) : (
                                        <a href={(dl.url || '').startsWith('http') ? dl.url! : `https://${dl.url}`} target="_blank" rel="noreferrer">
                                            {dl.url}
                                        </a>
                                    )}
                                </td>
                                <td>{dl.calibre_id ?? '—'}</td>
                                <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                                    {dl.completed_at ? new Date(dl.completed_at).toLocaleString() : dl.timestamp ? new Date(dl.timestamp).toLocaleString() : '—'}
                                </td>
                            </tr>
                        ))}
                        {activeUrls.length === 0 && waitingItems.length === 0 && recentDownloads.length === 0 && (
                            <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No downloads yet</td></tr>
                        )}
                    </tbody>
                </table>
            </div>

            {/* Recent Activity (retries, notifications, etc.) */}
            {activityEvents.length > 0 && (
                <div className="card">
                    <h2>Recent Activity</h2>
                    <table>
                        <thead><tr><th style={{ width: 30 }}></th><th>Event</th><th style={{ width: 90 }}>Time</th></tr></thead>
                        <tbody>
                            {activityEvents.map((evt, i) => (
                                <tr key={i}>
                                    <td>{evt.icon}</td>
                                    <td>{evt.text}</td>
                                    <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{evt.time}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    )
}
