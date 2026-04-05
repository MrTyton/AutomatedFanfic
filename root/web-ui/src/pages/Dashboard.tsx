import type { DashboardSnapshot } from '../hooks/useWebSocket'

interface Props {
  data: DashboardSnapshot | null
}

export default function Dashboard({ data }: Props) {
  if (!data) return <p>Waiting for data…</p>

  const activeCount = data.active_downloads.count
  const ingressDepth = typeof data.queues.ingress === 'number' ? data.queues.ingress : 0
  const waitingDepth = typeof data.queues.waiting === 'number' ? data.queues.waiting : 0
  const processEntries = Object.entries(data.processes)

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

      {/* Active downloads */}
      {activeCount > 0 && (
        <div className="card">
          <h2>Currently Processing</h2>
          <table>
            <thead><tr><th>URL</th></tr></thead>
            <tbody>
              {data.active_downloads.items.map((url) => (
                <tr key={url}><td>{url}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Processes */}
      {processEntries.length > 0 && (
        <div className="card">
          <h2>Processes</h2>
          <table>
            <thead><tr><th>Name</th><th>Status</th></tr></thead>
            <tbody>
              {processEntries.map(([name, status]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td><span className="badge badge-success">{status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent events */}
      {data.recent_events.length > 0 && (
        <div className="card">
          <h2>Recent Activity</h2>
          <table>
            <thead><tr><th>Event</th></tr></thead>
            <tbody>
              {data.recent_events.map((evt, i) => (
                <tr key={i}><td><pre style={{ margin: 0, fontSize: '0.8rem' }}>{JSON.stringify(evt, null, 2)}</pre></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
