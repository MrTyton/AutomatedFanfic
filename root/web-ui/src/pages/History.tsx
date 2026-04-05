import { useCallback, useEffect, useState } from 'react'
import { getDownloads, getEmails, getNotifications, getRetries, type DownloadRow, type EmailRow, type NotificationRow, type RetryRow } from '../api'

function ExpandableError({ text }: { text: string }) {
    const [expanded, setExpanded] = useState(false)
    return (
        <span
            onClick={() => setExpanded(!expanded)}
            title={expanded ? 'Click to collapse' : 'Click to see full error'}
            style={{
                color: 'var(--error)',
                cursor: 'pointer',
                ...(expanded ? { whiteSpace: 'pre-wrap', wordBreak: 'break-word' } : { display: 'block', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }),
            }}
        >
            {text}
        </span>
    )
}

export default function History() {
    const [tab, setTab] = useState<'downloads' | 'retries' | 'emails' | 'notifications'>('downloads')
    const [page, setPage] = useState(1)
    const [search, setSearch] = useState('')
    const [debouncedSearch, setDebouncedSearch] = useState('')

    const [downloads, setDownloads] = useState<DownloadRow[]>([])
    const [downloadTotal, setDownloadTotal] = useState(0)
    const [retries, setRetries] = useState<RetryRow[]>([])
    const [retryTotal, setRetryTotal] = useState(0)
    const [emails, setEmails] = useState<EmailRow[]>([])
    const [notifications, setNotifications] = useState<NotificationRow[]>([])

    // Debounce search input
    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedSearch(search)
            setPage(1)
        }, 300)
        return () => clearTimeout(timer)
    }, [search])

    const fetchData = useCallback(() => {
        if (tab === 'downloads') {
            getDownloads(page, 25, debouncedSearch).then(d => { setDownloads(d.items); setDownloadTotal(d.total) }).catch(() => { })
        } else if (tab === 'retries') {
            getRetries(page).then(d => { setRetries(d.items); setRetryTotal(d.total) }).catch(() => { })
        } else if (tab === 'emails') {
            getEmails(page).then(d => setEmails(d.items)).catch(() => { })
        } else if (tab === 'notifications') {
            getNotifications(page).then(d => setNotifications(d.items)).catch(() => { })
        }
    }, [page, tab, debouncedSearch])

    // Initial fetch + auto-refresh every 10s
    useEffect(() => {
        fetchData()
        const interval = setInterval(fetchData, 1000)
        return () => clearInterval(interval)
    }, [fetchData])

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>History</h1>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' }}>
                {(['downloads', 'retries', 'emails', 'notifications'] as const).map(t => (
                    <button
                        key={t}
                        className={tab === t ? '' : 'secondary'}
                        onClick={() => { setTab(t); setPage(1) }}
                    >
                        {t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                ))}
                {tab === 'downloads' && (
                    <input
                        type="text"
                        placeholder="Search by site, URL, or title…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        style={{ marginLeft: 'auto', width: 260 }}
                    />
                )}
            </div>

            {tab === 'downloads' && (
                <div className="card">
                    <table>
                        <thead>
                            <tr>
                                <th>Status</th>
                                <th>Site</th>
                                <th>Title</th>
                                <th>URL</th>
                                <th>Story ID</th>
                                <th>Error</th>
                                <th>Started</th>
                                <th>Completed</th>
                            </tr>
                        </thead>
                        <tbody>
                            {downloads.length === 0 ? (
                                <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No downloads recorded yet</td></tr>
                            ) : downloads.map((r, i) => (
                                <tr key={i}>
                                    <td>
                                        <span className={`badge ${r.status === 'success' ? 'badge-success' : r.status === 'failed' ? 'badge-error' : 'badge-warning'}`}>
                                            {r.status}
                                        </span>
                                    </td>
                                    <td>{r.site}</td>
                                    <td>{r.title ?? '—'}</td>
                                    <td style={{ maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        <a href={r.url.startsWith('http') ? r.url : `https://${r.url}`} target="_blank" rel="noreferrer">{r.url}</a>
                                    </td>
                                    <td>{r.calibre_id ?? '—'}</td>
                                    <td>{r.error_message ? <ExpandableError text={r.error_message} /> : '—'}</td>
                                    <td style={{ fontSize: '0.85rem' }}>{new Date(r.started_at).toLocaleString()}</td>
                                    <td style={{ fontSize: '0.85rem' }}>{r.completed_at ? new Date(r.completed_at).toLocaleString() : '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {downloadTotal > 25 && (
                        <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                            <button className="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
                            <span style={{ lineHeight: '2rem' }}>Page {page} of {Math.ceil(downloadTotal / 25)}</span>
                            <button className="secondary" disabled={page * 25 >= downloadTotal} onClick={() => setPage(p => p + 1)}>Next →</button>
                        </div>
                    )}
                </div>
            )}

            {tab === 'retries' && (
                <div className="card">
                    <table>
                        <thead>
                            <tr>
                                <th>Action</th>
                                <th>Site</th>
                                <th>URL</th>
                                <th>Attempt</th>
                                <th>Delay</th>
                                <th>Error</th>
                                <th>Scheduled</th>
                                <th>Fired</th>
                            </tr>
                        </thead>
                        <tbody>
                            {retries.length === 0 ? (
                                <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No retry events recorded yet</td></tr>
                            ) : retries.map(r => (
                                <tr key={r.id}>
                                    <td>
                                        <span className={`badge ${r.action === 'retry' ? 'badge-warning' : r.action === 'hail_mary' ? 'badge-error' : 'badge-error'}`}>
                                            {r.action === 'hail_mary' ? 'hail mary' : r.action}
                                        </span>
                                    </td>
                                    <td>{r.site}</td>
                                    <td style={{ maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        <a href={r.url.startsWith('http') ? r.url : `https://${r.url}`} target="_blank" rel="noreferrer">{r.url}</a>
                                    </td>
                                    <td>{r.attempt_number}</td>
                                    <td>{r.delay_minutes > 0 ? `${r.delay_minutes}m` : '—'}</td>
                                    <td>{r.error_message ? <ExpandableError text={r.error_message} /> : '—'}</td>
                                    <td style={{ fontSize: '0.85rem' }}>{new Date(r.scheduled_at).toLocaleString()}</td>
                                    <td style={{ fontSize: '0.85rem' }}>{r.fired_at ? new Date(r.fired_at).toLocaleString() : '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {retryTotal > 25 && (
                        <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                            <button className="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
                            <span style={{ lineHeight: '2rem' }}>Page {page} of {Math.ceil(retryTotal / 25)}</span>
                            <button className="secondary" disabled={page * 25 >= retryTotal} onClick={() => setPage(p => p + 1)}>Next →</button>
                        </div>
                    )}
                </div>
            )}

            {tab === 'emails' && (
                <div className="card">
                    <table>
                        <thead>
                            <tr>
                                <th>Checked At</th>
                                <th>URLs Found</th>
                                <th>New</th>
                                <th>Duplicate</th>
                                <th>Disabled Site</th>
                            </tr>
                        </thead>
                        <tbody>
                            {emails.length === 0 ? (
                                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No email checks recorded yet</td></tr>
                            ) : emails.map(e => (
                                <tr key={e.id}>
                                    <td>{new Date(e.checked_at).toLocaleString()}</td>
                                    <td>{e.urls_found}</td>
                                    <td>{e.urls_new}</td>
                                    <td>{e.urls_duplicate}</td>
                                    <td>{e.urls_disabled_site}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {tab === 'notifications' && (
                <div className="card">
                    <table>
                        <thead>
                            <tr>
                                <th>Sent At</th>
                                <th>Title</th>
                                <th>Body</th>
                                <th>Site</th>
                                <th>Provider</th>
                            </tr>
                        </thead>
                        <tbody>
                            {notifications.length === 0 ? (
                                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No notifications recorded yet</td></tr>
                            ) : notifications.map(n => (
                                <tr key={n.id}>
                                    <td>{new Date(n.sent_at).toLocaleString()}</td>
                                    <td>{n.title}</td>
                                    <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.body}</td>
                                    <td>{n.site ?? '—'}</td>
                                    <td>{n.provider ?? '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    )
}
