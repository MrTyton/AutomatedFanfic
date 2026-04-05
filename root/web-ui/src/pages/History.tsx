import { useEffect, useState } from 'react'
import { getDownloads, getEmails, getNotifications, type DownloadRow, type EmailRow, type NotificationRow } from '../api'

export default function History() {
    const [tab, setTab] = useState<'downloads' | 'emails' | 'notifications'>('downloads')
    const [page, setPage] = useState(1)

    // Downloads
    const [downloads, setDownloads] = useState<DownloadRow[]>([])
    const [downloadTotal, setDownloadTotal] = useState(0)

    // Emails
    const [emails, setEmails] = useState<EmailRow[]>([])

    // Notifications
    const [notifications, setNotifications] = useState<NotificationRow[]>([])

    useEffect(() => {
        if (tab === 'downloads') {
            getDownloads(page).then(d => { setDownloads(d.items); setDownloadTotal(d.total) }).catch(() => { })
        } else if (tab === 'emails') {
            getEmails(page).then(d => setEmails(d.items)).catch(() => { })
        } else if (tab === 'notifications') {
            getNotifications(page).then(d => setNotifications(d.items)).catch(() => { })
        }
    }, [page, tab])

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>History</h1>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                {(['downloads', 'emails', 'notifications'] as const).map(t => (
                    <button
                        key={t}
                        className={tab === t ? '' : 'secondary'}
                        onClick={() => { setTab(t); setPage(1) }}
                    >
                        {t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                ))}
            </div>

            {tab === 'downloads' && (
                <div className="card">
                    <table>
                        <thead>
                            <tr>
                                <th>URL</th>
                                <th>Site</th>
                                <th>Title</th>
                                <th>Status</th>
                                <th>Started</th>
                            </tr>
                        </thead>
                        <tbody>
                            {downloads.length === 0 ? (
                                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No downloads recorded yet</td></tr>
                            ) : downloads.map((r, i) => (
                                <tr key={i}>
                                    <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        <a href={r.url} target="_blank" rel="noreferrer">{r.url}</a>
                                    </td>
                                    <td>{r.site}</td>
                                    <td>{r.title ?? '—'}</td>
                                    <td>
                                        <span className={`badge ${r.status === 'success' ? 'badge-success' : r.status === 'failed' ? 'badge-error' : 'badge-warning'}`}>
                                            {r.status}
                                        </span>
                                    </td>
                                    <td>{new Date(r.started_at).toLocaleString()}</td>
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
                                <th>Site</th>
                                <th>Provider</th>
                            </tr>
                        </thead>
                        <tbody>
                            {notifications.length === 0 ? (
                                <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No notifications recorded yet</td></tr>
                            ) : notifications.map(n => (
                                <tr key={n.id}>
                                    <td>{new Date(n.sent_at).toLocaleString()}</td>
                                    <td>{n.title}</td>
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
