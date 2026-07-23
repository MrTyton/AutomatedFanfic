import { useState, useEffect, useRef } from 'react'
import { getLogs, getStartupLogs, type LogEntry } from '../api'

const DEFAULT_LEVEL_FILTER = 'error'
const UNKNOWN_LEVEL_FALLBACK = 40

export default function Logs() {
    const [logs, setLogs] = useState<LogEntry[]>([])
    const [startupLogs, setStartupLogs] = useState<LogEntry[]>([])
    const [autoRefresh, setAutoRefresh] = useState(true)
    const [filter, setFilter] = useState('')
    const [levelFilter, setLevelFilter] = useState<string>(DEFAULT_LEVEL_FILTER)
    const [activeView, setActiveView] = useState<'runtime' | 'startup'>('runtime')
    const [startupLoaded, setStartupLoaded] = useState(false)
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

    useEffect(() => {
        if (activeView !== 'startup' || startupLoaded) return
        getStartupLogs(2000)
            .then(data => {
                setStartupLogs(data.items)
                setStartupLoaded(true)
            })
            .catch(() => {
                setStartupLoaded(true)
            })
    }, [activeView, startupLoaded])

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

    const levelRank: Record<string, number> = {
        debug: 10,
        info: 20,
        warning: 30,
        error: 40,
    }

    const visibleLogs = activeView === 'startup' ? startupLogs : logs

    const filteredLogs = visibleLogs.filter(entry => {
        if (levelFilter !== 'all') {
            const minLevel = levelRank[levelFilter] ?? 0
            // Unknown levels are intentionally treated as high severity so they stay visible.
            const currentLevel = levelRank[entry.level] ?? UNKNOWN_LEVEL_FALLBACK
            if (currentLevel < minLevel) return false
        }
        if (filter && !entry.message.toLowerCase().includes(filter.toLowerCase())) return false
        return true
    })

    const ansiToCssColor = (ansi?: string): string | null => {
        if (!ansi) return null

        const xtermMatch = ansi.match(/\x1b\[38;5;(\d+)m/)
        if (xtermMatch) {
            const code = Number(xtermMatch[1])
            if (code >= 16 && code <= 231) {
                const index = code - 16
                const r = Math.floor(index / 36)
                const g = Math.floor((index % 36) / 6)
                const b = index % 6
                // Standard xterm 6x6x6 cube intensity mapping: 0, 95, 135, 175, 215, 255.
                const mapXtermCubeToRgbIntensity = (n: number) => (n === 0 ? 0 : 55 + n * 40)
                return `rgb(${mapXtermCubeToRgbIntensity(r)}, ${mapXtermCubeToRgbIntensity(g)}, ${mapXtermCubeToRgbIntensity(b)})`
            }
            if (code >= 232 && code <= 255) {
                // Standard xterm grayscale ramp: 24 levels (232-255), intensity 8..238.
                // Step size is total range (238 - 8 = 230) divided by 23 intervals.
                const v = Math.round(8 + (code - 232) * (230 / 23))
                return `rgb(${v}, ${v}, ${v})`
            }
        }

        const basicMatch = ansi.match(/\x1b\[(\d+)m/)
        if (basicMatch) {
            switch (Number(basicMatch[1])) {
                case 91: return '#f44336'
                case 92: return '#4caf50'
                case 93: return '#ff9800'
                case 94: return '#64b5f6'
                case 95: return '#ce93d8'
                default: return null
            }
        }

        return null
    }

    const levelColor = (level: string): string => {
        switch (level) {
            case 'error': return 'var(--error, #f44336)'
            case 'warning': return 'var(--warning, #ff9800)'
            case 'debug': return 'var(--text-muted, #888)'
            default: return 'var(--text, #e0e0e0)'
        }
    }

    const entryColor = (entry: LogEntry): string => {
        if (entry.level === 'error' || entry.level === 'warning') {
            return levelColor(entry.level)
        }
        const workerColor = ansiToCssColor(entry.thread_color)
        if (workerColor) return workerColor
        return levelColor(entry.level)
    }

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>Logs</h1>

            {/* Controls */}
            <div className="card" style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                        className={activeView === 'runtime' ? '' : 'secondary'}
                        onClick={() => setActiveView('runtime')}
                    >
                        Runtime
                    </button>
                    <button
                        className={activeView === 'startup' ? '' : 'secondary'}
                        onClick={() => setActiveView('startup')}
                    >
                        Startup
                    </button>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                        type="checkbox"
                        checked={autoRefresh}
                        onChange={e => setAutoRefresh(e.target.checked)}
                        disabled={activeView !== 'runtime'}
                    />
                    Auto-refresh
                </label>
                <select
                    value={levelFilter}
                    onChange={e => setLevelFilter(e.target.value)}
                    style={{ padding: '0.3rem 0.5rem' }}
                >
                    <option value="all">All levels</option>
                    <option value="debug">Debug and above</option>
                    <option value="info">Info and above</option>
                    <option value="warning">Warning and above</option>
                    <option value="error">Error only</option>
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
                    <div key={`${entry.timestamp}-${entry.level}-${i}`} style={{ color: entryColor(entry), marginBottom: '2px' }}>
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
