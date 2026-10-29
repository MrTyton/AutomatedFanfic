/** Canonical status → badge CSS class mapping. */
export function statusBadgeClass(status: string | undefined): string {
    switch (status) {
        case 'success':
            return 'badge badge-success'
        case 'failed':
            return 'badge badge-error'
        case 'abandoned':
            return 'badge badge-abandoned'
        case 'pending':
        case 'processing':
            return 'badge badge-warning'
        case 'queued':
            return 'badge badge-info'
        case 'waiting':
            return 'badge badge-waiting'
        case 'retry':
            return 'badge badge-warning'
        case 'hail_mary':
            return 'badge badge-error'
        default:
            return 'badge badge-info'
    }
}

/** Canonical status hex colors for Recharts */
export const STATUS_COLORS = {
    success: '#10b981', // emerald-500
    failed: '#ef4444',  // red-500
    pending: '#f59e0b', // amber-500
    waiting: '#06b6d4', // cyan-500
    abandoned: '#f43f5e', // rose-500
    accent: '#6366f1',  // indigo-500
    muted: '#94a3b8',   // slate-400
    surface2: '#1e293b', // slate-800
} as const

export const PIE_COLORS = [
    STATUS_COLORS.success,
    STATUS_COLORS.failed,
    STATUS_COLORS.pending,
    STATUS_COLORS.waiting,
    STATUS_COLORS.abandoned,
    '#8b5cf6', // violet-500
    '#ec4899', // pink-500
]

/**
 * Site identity metadata.
 * Algorithmically determines human-friendly display name, key, and distinct high-contrast color.
 */
export function getSiteBadgeInfo(siteName?: string): { name: string; key: string; color: string; bg: string; border: string } {
    const raw = (siteName || '').trim()
    if (!raw) {
        return {
            name: 'Web',
            key: 'web',
            color: '#94a3b8',
            bg: 'rgba(148, 163, 184, 0.1)',
            border: 'rgba(148, 163, 184, 0.24)',
        }
    }
    const s = raw.toLowerCase()

    // Algorithmic key extraction: strip protocol, www/forum/forums/archive prefixes, and common domain extensions
    let clean = s.replace(/^[a-zA-Z]+:\/\//, '')
    clean = clean.replace(/^(www\.|forums?\.|forum\.|archive\.)+/i, '')
    const baseKey = clean.replace(/\.(com|org|net|de|fr|co\.uk|me|live|tv|io|info)$/i, '')
    const key = baseKey.replace(/[-_.]/g, '') || s

    // Algorithmic display name resolution
    let name = raw
    if (key === 'archiveofourown' || key === 'ao3') {
        name = 'AO3'
    } else if (key === 'fanfiction' || key === 'ffnet') {
        name = 'FF.net'
    } else {
        // Insert word boundaries for compound words and camelCase
        const spaced = baseKey
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/(questionable)(questing)/i, '$1 $2')
            .replace(/(sufficient)(velocity)/i, '$1 $2')
            .replace(/(space)(battles)/i, '$1 $2')
            .replace(/(royal)(road)/i, '$1 $2')
            .replace(/(fiction)(press)/i, '$1 $2')
            .replace(/(scribble)(hub)/i, '$1 $2')
            .replace(/(fim)(fiction)/i, '$1 $2')
            .replace(/(alt)(history)/i, '$1 $2')
            .replace(/(alternate)(history)/i, '$1 $2')

        const words = spaced
            .split(/[-_.\s]+/)
            .filter(Boolean)
            .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        name = words.join(' ') || raw
    }

    // Deterministic, algorithmic color calculation via string hashing (HSL)
    let hash = 0
    for (let i = 0; i < key.length; i++) {
        hash = key.charCodeAt(i) + ((hash << 5) - hash)
    }
    const hue = Math.abs(hash) % 360
    const color = `hsl(${hue}, 80%, 65%)`
    const bg = `hsla(${hue}, 80%, 65%, 0.12)`
    const border = `hsla(${hue}, 80%, 65%, 0.28)`

    return {
        name,
        key,
        color,
        bg,
        border,
    }
}
