import { Mail, Radar, User } from 'lucide-react'
import type { DownloadSource } from '../api'

const SOURCE_CONFIG: Record<
    Exclude<DownloadSource, 'unknown'>,
    {
        label: string
        title: string
        color: string
        bg: string
        border: string
        Icon: typeof Mail
    }
> = {
    email: {
        label: 'Email',
        title: 'Triggered by email notification',
        color: '#60a5fa',
        bg: 'rgba(59, 130, 246, 0.14)',
        border: 'rgba(59, 130, 246, 0.3)',
        Icon: Mail,
    },
    poller: {
        label: 'Poller',
        title: 'Triggered by Library Update Poller',
        color: '#2dd4bf',
        bg: 'rgba(20, 184, 166, 0.14)',
        border: 'rgba(20, 184, 166, 0.3)',
        Icon: Radar,
    },
    manual: {
        label: 'Manual',
        title: 'Added manually via Web UI or MCP',
        color: '#c084fc',
        bg: 'rgba(168, 85, 247, 0.14)',
        border: 'rgba(168, 85, 247, 0.3)',
        Icon: User,
    },
}

export function SourceBadge({ source }: { source?: DownloadSource | string | null }) {
    if (!source || source === 'unknown') return null
    if (source !== 'email' && source !== 'poller' && source !== 'manual') return null

    const cfg = SOURCE_CONFIG[source]
    const { Icon } = cfg

    return (
        <span
            className="badge"
            title={cfg.title}
            style={{
                background: cfg.bg,
                color: cfg.color,
                border: `1px solid ${cfg.border}`,
                fontSize: '0.68rem',
                padding: '0.1rem 0.42rem',
                gap: '0.25rem',
            }}
        >
            <Icon size={10} />
            <span>{cfg.label}</span>
        </span>
    )
}
