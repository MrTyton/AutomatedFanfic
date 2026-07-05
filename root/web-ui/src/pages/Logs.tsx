import { useState, useEffect, useRef } from 'react'
import { getLogs, type LogEntry } from '../api'

export default function Logs() {
    const [logs, setLogs] = useState<LogEntry[]>([])
    const [autoRefresh, setAutoRefresh] = useState(true)
    const [filter, setFilter] = useState('')
    const [levelFilter, setLevelFilter] = useState<string>('all')
    const bottomRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const [isAtBottom, setIsAtBottom] = useState(true)

    useEffect(() => {
        let interval: number | undefined

        const fetchLogs = async () => {
            try {
                const data = await getLogs(2000)
                setLogs(data.items)
            } catch {
                // ignore fetch errors
            }
        }

        fetchLogs()
        if (autoRefresh) {
            interval = window.setInterval(fetchLogs, 2000)
        }
        return () => { if (interval) clearInterval(interval) }
    }, [autoRefresh])

    // Auto-scroll to bottom when new logs arrive (if user was already at bottom)
    useEffect(() => {
        if (isAtBottom && bottomRef.current) {
            bottomRef.current.scrollIntoView({ behavior: 'smooth' })
        }
    }, [logs, isAtBottom])

    const handleScroll = () => {
        const el = containerRef.current
        if (!el) return
        const threshold = 50
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
        setIsAtBottom(atBottom)
    }

    const filteredLogs = logs.filter(entry => {
        if (levelFilter !== 'all' && entry.level !== levelFilter) return false
        if (filter && !entry.message.toLowerCase().includes(filter.toLowerCase())) return false
        return true
    })

    const levelColor = (level: string): string => {
        switch (level) {
            case 'error': return 'var(--error, #f44336)'
            case 'warning': return 'var(--warning, #ff9800)'
            case 'debug': return 'var(--text-muted, #888)'
            default: return 'var(--text, #e0e0e0)'
        }
    }

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>Logs</h1>

            {/* Controls */}
            <div className="card" style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                        type="checkbox"
                        checked={autoRefresh}
                        onChange={e => setAutoRefresh(e.target.checked)}
                    />
                    Auto-refresh
                </label>
                <select
                    value={levelFilter}
                    onChange={e => setLevelFilter(e.target.value)}
                    style={{ padding: '0.3rem 0.5rem' }}
                >
                    <option value="all">All levels</option>
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="error">Error</option>
                    <option value="debug">Debug</option>
                </select>
                <input
                    type="text"
                    placeholder="Filter logs…"
                    value={filter}
                    onChange={e => setFilter(e.target.value)}
                    style={{ flex: 1, minWidth: '200px', padding: '0.3rem 0.5rem' }}
                />
                <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                    {filteredLogs.length} entries
                </span>
            </div>

            {/* Log output */}
            <div
                className="card"
                ref={containerRef}
                onScroll={handleScroll}
                style={{
                    fontFamily: 'monospace',
                    fontSize: '0.82rem',
                    maxHeight: '70vh',
                    overflow: 'auto',
                    padding: '0.75rem',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    lineHeight: '1.5',
                }}
            >
                {filteredLogs.length === 0 && (
                    <p style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                        No log entries{filter || levelFilter !== 'all' ? ' matching filter' : ''}
                    </p>
                )}
                {/* Render in reverse (oldest first, newest at bottom) */}
                {[...filteredLogs].reverse().map((entry, i) => (
                    <div key={`${entry.timestamp}-${entry.level}-${i}`} style={{ color: levelColor(entry.level), marginBottom: '2px' }}>
                        <span style={{ color: 'var(--text-muted)', marginRight: '0.5rem' }}>
                            {entry.timestamp}
                        </span>
                        {entry.level !== 'info' && (
                            <span style={{ fontWeight: 'bold', marginRight: '0.5rem' }}>
                                [{entry.level.toUpperCase()}]
                            </span>
                        )}
                        {entry.message}
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>
        </>
    )
}
