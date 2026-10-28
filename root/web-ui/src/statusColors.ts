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
 * Decoupled from semantic status badges so AO3 never looks like a red "failed" alert badge.
 */
export function getSiteBadgeInfo(siteName?: string): { name: string; key: string; color: string; bg: string; border: string } {
    const s = (siteName || '').toLowerCase()
    if (s.includes('archive') || s.includes('ao3')) {
        return {
            name: 'AO3',
            key: 'archiveofourown',
            color: '#f472b6',
            bg: 'rgba(244, 114, 182, 0.1)',
            border: 'rgba(244, 114, 182, 0.24)',
        }
    }
    if (s.includes('royal')) {
        return {
            name: 'RoyalRoad',
            key: 'royalroad',
            color: '#fbbf24',
            bg: 'rgba(245, 158, 11, 0.1)',
            border: 'rgba(245, 158, 11, 0.24)',
        }
    }
    if (s.includes('fanfiction') || s.includes('ffnet')) {
        return {
            name: 'FF.net',
            key: 'fanfiction',
            color: '#60a5fa',
            bg: 'rgba(59, 130, 246, 0.1)',
            border: 'rgba(59, 130, 246, 0.24)',
        }
    }
    if (s.includes('wattpad')) {
        return {
            name: 'Wattpad',
            key: 'wattpad',
            color: '#fb923c',
            bg: 'rgba(249, 115, 22, 0.1)',
            border: 'rgba(249, 115, 22, 0.24)',
        }
    }
    if (s.includes('spacebattles')) {
        return {
            name: 'SpaceBattles',
            key: 'spacebattles',
            color: '#38bdf8',
            bg: 'rgba(14, 165, 233, 0.1)',
            border: 'rgba(14, 165, 233, 0.24)',
        }
    }
    return {
        name: siteName || 'Web',
        key: s || 'web',
        color: '#a78bfa',
        bg: 'rgba(139, 92, 246, 0.1)',
        border: 'rgba(139, 92, 246, 0.24)',
    }
}
