import { lazy, Suspense } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import { useDashboardSocket } from './hooks/useWebSocket'
import Dashboard from './pages/Dashboard'

const History = lazy(() => import('./pages/History'))
const Logs = lazy(() => import('./pages/Logs'))
const Stats = lazy(() => import('./pages/Stats'))
const Config = lazy(() => import('./pages/Config'))

export default function App() {
    const { data, connected } = useDashboardSocket()

    return (
        <div className="app">
            <nav className="sidebar">
                <h1>📚 FanficDL</h1>
                <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
                    Dashboard
                </NavLink>
                <NavLink to="/history" className={({ isActive }) => isActive ? 'active' : ''}>
                    History
                </NavLink>
                <NavLink to="/logs" className={({ isActive }) => isActive ? 'active' : ''}>
                    Logs
                </NavLink>
                <NavLink to="/stats" className={({ isActive }) => isActive ? 'active' : ''}>
                    Stats
                </NavLink>
                <NavLink to="/config" className={({ isActive }) => isActive ? 'active' : ''}>
                    Config
                </NavLink>
                <div style={{ marginTop: 'auto', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <span className={`connection-dot ${connected ? 'connected' : 'disconnected'}`} />
                    {connected ? 'Connected' : 'Disconnected'}
                </div>
            </nav>
            <main className="content">
                <Suspense fallback={<div style={{ padding: '2rem', color: 'var(--text-muted)' }}>Loading…</div>}>
                    <Routes>
                        <Route path="/" element={<Dashboard data={data} />} />
                        <Route path="/history" element={<History />} />
                        <Route path="/logs" element={<Logs />} />
                        <Route path="/stats" element={<Stats />} />
                        <Route path="/config" element={<Config />} />
                    </Routes>
                </Suspense>
            </main>
        </div>
    )
}
