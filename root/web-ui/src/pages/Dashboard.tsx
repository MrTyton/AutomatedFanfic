import { useState } from 'react'
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
    action?: string
    attempt_number?: number
    timestamp?: string
}

function extractSite(url: string): string {
    try {
        const host = new URL(url).hostname.replace('www.', '')
        return host.split('.')[0]
    } catch {
        return '—'
    }
}

function formatEvent(evt: RecentEvent): { icon: string; text: string; time: string } {
    const time = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ''

    if (evt.event_type === 'download') {
        const title = evt.title || evt.url || 'Unknown'
        const site = evt.site || '—'
        if (evt.status === 'success') return { icon: '✓', text: `(${site}) ${title}`, time }
        if (evt.status === 'failed') return { icon: '✗', text: `(${site}) Failed: ${title}`, time }
        return { icon: '↓', text: `(${site}) Processing ${title}`, time }
    }
    if (evt.event_type === 'retry') {
        const site = evt.site || '—'
        return { icon: '↻', text: `(${site}) Retry #${evt.attempt_number ?? '?'} — ${evt.action ?? 'requeue'}`, time }
    }
    // Skip email_check events — not useful in the feed
    return { icon: '', text: '', time: '' }
}

export default function Dashboard({ data }: Props) {
    const [urlText, setUrlText] = useState('')
    const [results, setResults] = useState<AddUrlResult[]>([])
    const [loading, setLoading] = useState(false)

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

    const activeCount = data.active_downloads.count
    const ingressDepth = typeof data.queues.ingress === 'number' ? data.queues.ingress : 0
    const waitingDepth = typeof data.queues.waiting === 'number' ? data.queues.waiting : 0

    // Filter recent events to only meaningful ones (downloads, retries)
    const meaningfulEvents = (data.recent_events as RecentEvent[])
        .map(formatEvent)
        .filter(e => e.text !== '')

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
                    <div className="stat">{waitingDepth}</div>
                </div>
            </div>

            {/* Add URLs */}
            <div className="card">
                <h2>Add URLs</h2>
                <form onSubmit={handleAddUrls}>
                    <textarea
                        value={urlText}
                        onChange={e => setUrlText(e.target.value)}
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

            {/* Currently Processing */}
            {activeCount > 0 && (
                <div className="card">
                    <h2>Currently Processing</h2>
                    <table>
                        <thead><tr><th>Site</th><th>URL</th></tr></thead>
                        <tbody>
                            {data.active_downloads.items.map((url) => (
                                <tr key={url}>
                                    <td><span className="badge badge-warning">{extractSite(url)}</span></td>
                                    <td>
                                        <a href={url.startsWith('http') ? url : `https://${url}`} target="_blank" rel="noreferrer">
                                            {url}
                                        </a>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Recent Activity */}
            {meaningfulEvents.length > 0 && (
                <div className="card">
                    <h2>Recent Activity</h2>
                    <table>
                        <thead><tr><th style={{ width: 30 }}></th><th>Event</th><th style={{ width: 90 }}>Time</th></tr></thead>
                        <tbody>
                            {meaningfulEvents.map((evt, i) => (
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
