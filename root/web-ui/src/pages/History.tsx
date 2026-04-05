import { useEffect, useState } from 'react'
import { getDownloads, type DownloadRow } from '../api'

export default function History() {
  const [rows, setRows] = useState<DownloadRow[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [tab, setTab] = useState<'downloads' | 'emails' | 'notifications'>('downloads')

  useEffect(() => {
    if (tab === 'downloads') {
      getDownloads(page).then(d => { setRows(d.items); setTotal(d.total) }).catch(() => {})
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
              {rows.length === 0 ? (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No downloads recorded yet</td></tr>
              ) : rows.map((r, i) => (
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
          {total > 25 && (
            <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
              <button className="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span style={{ lineHeight: '2rem' }}>Page {page} of {Math.ceil(total / 25)}</span>
              <button className="secondary" disabled={page * 25 >= total} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          )}
        </div>
      )}

      {tab === 'emails' && (
        <div className="card">
          <p style={{ color: 'var(--text-muted)' }}>Email check history — coming soon</p>
        </div>
      )}

      {tab === 'notifications' && (
        <div className="card">
          <p style={{ color: 'var(--text-muted)' }}>Notification history — coming soon</p>
        </div>
      )}
    </>
  )
}
