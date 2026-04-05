import { useEffect, useRef, useState, useCallback } from 'react'

export interface DashboardSnapshot {
    timestamp: number
    active_downloads: { items: string[]; count: number }
    queues: Record<string, number | Record<string, number>>
    processes: Record<string, string>
    recent_downloads: unknown[]
    recent_activity: unknown[]
}

export function useDashboardSocket() {
    const [data, setData] = useState<DashboardSnapshot | null>(null)
    const [connected, setConnected] = useState(false)
    const wsRef = useRef<WebSocket | null>(null)
    const reconnectTimer = useRef<number>(0)

    const connect = useCallback(() => {
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard`)

        ws.onopen = () => setConnected(true)
        ws.onclose = () => {
            setConnected(false)
            // Auto-reconnect after 3 s
            reconnectTimer.current = window.setTimeout(connect, 3000)
        }
        ws.onmessage = (ev) => {
            try { setData(JSON.parse(ev.data)) } catch { /* ignore bad frames */ }
        }

        wsRef.current = ws
    }, [])

    useEffect(() => {
        connect()
        return () => {
            clearTimeout(reconnectTimer.current)
            wsRef.current?.close()
        }
    }, [connect])

    return { data, connected }
}
