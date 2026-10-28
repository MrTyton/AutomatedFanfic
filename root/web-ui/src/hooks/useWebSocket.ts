import { useEffect, useRef, useState, useCallback } from 'react'
import type { DashboardSnapshot, ActiveDownload } from '../api'

export type { DashboardSnapshot, ActiveDownload }

export function useDashboardSocket() {
    const [data, setData] = useState<DashboardSnapshot | null>(null)
    const [connected, setConnected] = useState(false)
    const [connectionMode, setConnectionMode] = useState<'live' | 'local' | 'reconnecting'>('reconnecting')
    const wsRef = useRef<WebSocket | null>(null)
    const reconnectTimer = useRef<number>(0)

    const connect = useCallback(() => {
        try {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
            const ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard`)

            ws.onopen = () => {
                setConnected(true)
                setConnectionMode('live')
            }
            ws.onmessage = (ev) => {
                try {
                    const parsed = JSON.parse(ev.data) as DashboardSnapshot
                    if (parsed && typeof parsed === 'object') {
                        setData(parsed)
                        setConnected(true)
                        setConnectionMode('live')
                    }
                } catch {
                    // ignore non-JSON frames
                }
            }
            ws.onclose = () => {
                setConnected(false)
                setConnectionMode('reconnecting')
                clearTimeout(reconnectTimer.current)
                reconnectTimer.current = window.setTimeout(connect, 3000)
            }
            ws.onerror = () => {
                ws.close()
            }

            wsRef.current = ws
        } catch {
            setConnected(false)
            setConnectionMode('reconnecting')
            clearTimeout(reconnectTimer.current)
            reconnectTimer.current = window.setTimeout(connect, 3000)
        }
    }, [])

    useEffect(() => {
        connect()
        return () => {
            clearTimeout(reconnectTimer.current)
            wsRef.current?.close()
        }
    }, [connect])

    return { data, connected, connectionMode }
}
