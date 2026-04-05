import { Routes, Route, NavLink } from 'react-router-dom'
import { useDashboardSocket } from './hooks/useWebSocket'
import Dashboard from './pages/Dashboard'
import History from './pages/History'
import Config from './pages/Config'

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
                <NavLink to="/config" className={({ isActive }) => isActive ? 'active' : ''}>
                    Config
                </NavLink>
                <div style={{ marginTop: 'auto', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <span className={`connection-dot ${connected ? 'connected' : 'disconnected'}`} />
                    {connected ? 'Connected' : 'Disconnected'}
                </div>
            </nav>
            <main className="content">
                <Routes>
                    <Route path="/" element={<Dashboard data={data} />} />
                    <Route path="/history" element={<History />} />
                    <Route path="/config" element={<Config />} />
                </Routes>
            </main>
        </div>
    )
}
