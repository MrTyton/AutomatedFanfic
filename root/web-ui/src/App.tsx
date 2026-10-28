import { useState } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import {
    LayoutDashboard,
    History as HistoryIcon,
    Terminal,
    BarChart3,
    Settings,
    BookOpen,
    RotateCcw,
    Pause,
    Play,
    Cpu,
    X,
} from 'lucide-react'
import { useDashboardSocket } from './hooks/useWebSocket'
import { restartDaemon, toggleCoordinatorPause } from './api'
import Dashboard from './pages/Dashboard'
import History from './pages/History'
import Logs from './pages/Logs'
import Stats from './pages/Stats'
import Config from './pages/Config'

function formatUptime(sec: number): string {
    if (sec < 60) return `${sec}s`
    const m = Math.floor(sec / 60)
    if (m < 60) return `${m}m`
    const h = Math.floor(m / 60)
    const remM = m % 60
    return `${h}h ${remM}m`
}

export default function App() {
    const { data, connected, connectionMode } = useDashboardSocket()
    const location = useLocation()
    const [showDaemonModal, setShowDaemonModal] = useState(false)
    const [daemonFeedback, setDaemonFeedback] = useState<string | null>(null)

    const activeCount = data?.active_downloads?.count ?? 0
    const queuedCount = data?.queued_downloads?.count ?? 0
    const waitingCount = data?.waiting_downloads?.count ?? 0
    const inFlightTotal = activeCount + queuedCount + waitingCount

    const processes =
        data?.processes && Object.keys(data.processes).length > 0
            ? data.processes
            : data?.daemon_details && Object.keys(data.daemon_details).length > 0
              ? Object.fromEntries(
                    Object.entries(data.daemon_details).map(([k, v]) => [
                        k,
                        typeof v === 'object' && v && 'status' in v ? String((v as { status: unknown }).status) : 'running',
                    ])
                )
              : {
                    Coordinator: 'running',
                    EmailWatcher: 'running',
                    FFWaiter: 'running',
                    WorkerPool: 'running',
                    WebServer: 'running',
                }
    const daemonDetails = data?.daemon_details || {}
    const coordinatorPaused = !!data?.coordinator_paused
    const processEntries = Object.entries(processes)
    const allDaemonsRunning = processEntries.every(([, st]) => st === 'running' || st === 'paused')

    const navLinks = [
        { path: '/', label: 'Dashboard', icon: LayoutDashboard, badge: inFlightTotal > 0 ? inFlightTotal : undefined },
        { path: '/history', label: 'History', icon: HistoryIcon },
        { path: '/logs', label: 'Logs', icon: Terminal },
        { path: '/stats', label: 'Stats', icon: BarChart3 },
        { path: '/config', label: 'Config', icon: Settings },
    ]

    const statusLabel =
        connectionMode === 'live'
            ? 'Live WebSocket'
            : connectionMode === 'reconnecting'
              ? 'Reconnecting…'
              : 'Connected (Sync)'

    const handleRestartDaemon = async (name: string) => {
        const res = await restartDaemon(name)
        setDaemonFeedback(res.message)
        setTimeout(() => setDaemonFeedback(null), 3000)
    }

    const handleToggleCoordinator = async () => {
        const res = await toggleCoordinatorPause()
        setDaemonFeedback(res.message)
        setTimeout(() => setDaemonFeedback(null), 3000)
    }

    return (
        <div className="app">
            {/* Desktop Navigation Sidebar */}
            <nav className="sidebar" aria-label="Primary Navigation">
                <div className="brand-header">
                    <div className="brand-icon">
                        <BookOpen size={20} />
                    </div>
                    <div>
                        <div className="brand-title">FanficDL</div>
                        <div className="brand-subtitle">Automated Fanfiction</div>
                    </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    {navLinks.map((item) => {
                        const Icon = item.icon
                        return (
                            <NavLink
                                key={item.path}
                                to={item.path}
                                end={item.path === '/'}
                                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                            >
                                <Icon size={18} />
                                <span>{item.label}</span>
                                {item.badge !== undefined && (
                                    <span className="nav-link-badge">{item.badge}</span>
                                )}
                            </NavLink>
                        )
                    })}
                </div>

                <div className="sidebar-footer">
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '0 0.2rem',
                        }}
                    >
                        <span style={{ fontSize: '0.68rem', fontWeight: 600, color: 'var(--text-faint)' }}>
                            Supervisor Daemons ({processEntries.filter(([, s]) => s === 'running').length}/{processEntries.length})
                        </span>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => setShowDaemonModal(true)}
                            style={{
                                padding: '0.1rem 0.4rem',
                                minHeight: 20,
                                fontSize: '0.66rem',
                            }}
                            title="Inspect PIDs, uptime, pause queue dispatch, or restart individual daemons"
                        >
                            Manage
                        </button>
                    </div>
                    <div
                        className="daemon-grid"
                        onClick={() => setShowDaemonModal(true)}
                        style={{ cursor: 'pointer' }}
                        title="Click to manage background supervisor daemons"
                    >
                        {processEntries.map(([name, status]) => {
                            const isUp = status === 'running'
                            const isPaused = status === 'paused'
                            return (
                                <div key={name} className="daemon-item" title={`${name}: ${status} (click to manage)`}>
                                    <span
                                        className={`daemon-dot ${isUp ? 'running' : 'stopped'}`}
                                        style={isPaused ? { background: 'var(--warning)', boxShadow: '0 0 6px var(--warning)' } : undefined}
                                    />
                                    <span>{name}</span>
                                </div>
                            )
                        })}
                    </div>

                    <div className="connection-status">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                            <span className={`connection-dot ${connected && allDaemonsRunning ? 'connected' : 'disconnected'}`} />
                            <span>{statusLabel}</span>
                        </div>
                    </div>
                </div>
            </nav>

            {/* Slim Mobile Header Bar */}
            <header className="mobile-topbar">
                <div className="mobile-brand">
                    <div className="brand-icon" style={{ width: 28, height: 28, fontSize: '0.9rem' }}>
                        <BookOpen size={16} />
                    </div>
                    <span>FanficDL</span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={() => setShowDaemonModal(true)}
                        style={{ padding: '0.15rem 0.45rem', minHeight: 24, fontSize: '0.72rem', fontFamily: 'var(--font-mono)' }}
                    >
                        {processEntries.filter(([, s]) => s === 'running').length}/{processEntries.length} daemons
                    </button>
                    <span aria-hidden="true">·</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                        <span className={`connection-dot ${connected ? 'connected' : 'disconnected'}`} />
                        <span>{connected ? 'Live' : 'Offline'}</span>
                    </div>
                </div>
            </header>

            {/* Mobile Fixed Bottom Thumb Bar */}
            <nav className="mobile-bottom-nav" aria-label="Mobile Navigation">
                {navLinks.map((item) => {
                    const Icon = item.icon
                    const isActive = item.path === '/'
                        ? location.pathname === '/'
                        : location.pathname.startsWith(item.path)
                    return (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            end={item.path === '/'}
                            className={`mobile-nav-item ${isActive ? 'active' : ''}`}
                        >
                            <Icon size={20} />
                            <span>{item.label}</span>
                            {item.badge !== undefined && (
                                <span className="mobile-nav-badge">{item.badge}</span>
                            )}
                        </NavLink>
                    )
                })}
            </nav>

            {/* Main Viewport Content */}
            <main className="content">
                <Routes>
                    <Route path="/" element={<Dashboard data={data} />} />
                    <Route path="/history" element={<History data={data} />} />
                    <Route path="/logs" element={<Logs />} />
                    <Route path="/stats" element={<Stats />} />
                    <Route path="/config" element={<Config />} />
                </Routes>
            </main>

            {/* Supervisor & Daemon Control Modal */}
            {showDaemonModal && (
                <div
                    className="modal-overlay"
                    onClick={() => setShowDaemonModal(false)}
                    role="dialog"
                    aria-modal="true"
                    aria-label="Supervisor Daemon Controls"
                >
                    <div
                        className="modal-card"
                        style={{ maxWidth: 640, width: '100%' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="modal-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
                                <Cpu size={18} style={{ color: 'var(--accent)' }} />
                                <h3 style={{ margin: 0, fontSize: '1rem' }}>Supervisor & Process Tree Controls</h3>
                            </div>
                            <button
                                type="button"
                                className="secondary btn-sm"
                                onClick={() => setShowDaemonModal(false)}
                            >
                                <X size={14} /> Close
                            </button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                            {daemonFeedback && (
                                <div
                                    style={{
                                        padding: '0.5rem 0.75rem',
                                        borderRadius: 'var(--radius-sm)',
                                        background: 'rgba(16, 185, 129, 0.12)',
                                        border: '1px solid rgba(16, 185, 129, 0.35)',
                                        color: 'var(--success)',
                                        fontSize: '0.8rem',
                                        fontWeight: 600,
                                    }}
                                >
                                    {daemonFeedback}
                                </div>
                            )}

                            {processEntries.map(([name, status]) => {
                                const detail = daemonDetails[name]
                                const isPaused = status === 'paused'
                                const isUp = status === 'running'
                                return (
                                    <div
                                        key={name}
                                        style={{
                                            padding: '0.8rem 0.95rem',
                                            borderRadius: 'var(--radius-md)',
                                            background: 'var(--surface2)',
                                            border: '1px solid var(--border)',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            gap: '0.75rem',
                                            flexWrap: 'wrap',
                                        }}
                                    >
                                        <div style={{ minWidth: 0, flex: '1 1 240px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                                <span
                                                    className={`daemon-dot ${isUp ? 'running' : 'stopped'}`}
                                                    style={isPaused ? { background: 'var(--warning)', boxShadow: '0 0 6px var(--warning)' } : undefined}
                                                />
                                                <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.88rem' }}>
                                                    {name}
                                                </span>
                                                <span className={`badge ${isPaused ? 'badge-warning' : isUp ? 'badge-success' : 'badge-error'}`}>
                                                    {status}
                                                </span>
                                                {detail && (
                                                    <span
                                                        className="tabular-nums"
                                                        style={{ fontSize: '0.73rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}
                                                    >
                                                        PID {detail.pid} · Uptime {formatUptime(detail.uptime_sec)}
                                                        {detail.restarts > 0 ? ` · ${detail.restarts} restart(s)` : ''}
                                                    </span>
                                                )}
                                            </div>
                                            {detail?.role && (
                                                <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '0.22rem' }}>
                                                    {detail.role}
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexShrink: 0 }}>
                                            {name === 'Coordinator' && (
                                                <button
                                                    type="button"
                                                    className={coordinatorPaused ? 'btn-sm' : 'secondary btn-sm'}
                                                    onClick={handleToggleCoordinator}
                                                    title={
                                                        coordinatorPaused
                                                            ? 'Resume dispatching queued story URLs to site workers'
                                                            : 'Pause dispatching new story URLs to site workers'
                                                    }
                                                >
                                                    {coordinatorPaused ? <Play size={13} /> : <Pause size={13} />}
                                                    {coordinatorPaused ? 'Resume Queue' : 'Pause Queue'}
                                                </button>
                                            )}
                                            <button
                                                type="button"
                                                className="secondary btn-sm"
                                                onClick={() => handleRestartDaemon(name)}
                                                title={`Restart ${name} subprocess`}
                                            >
                                                <RotateCcw size={13} /> Restart
                                            </button>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
