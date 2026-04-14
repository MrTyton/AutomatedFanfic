/** Canonical status → badge CSS class mapping. Single source of truth for status styling. */
export function statusBadgeClass(status: string | undefined): string {
    switch (status) {
        case 'success': return 'badge badge-success'
        case 'failed': return 'badge badge-error'
        case 'abandoned': return 'badge badge-abandoned'
        case 'pending':
        case 'processing': return 'badge badge-warning'
        case 'waiting': return 'badge badge-info'
        case 'retry': return 'badge badge-warning'
        case 'hail_mary': return 'badge badge-error'
        default: return 'badge badge-warning'
    }
}

/** Canonical status → hex color for charts (Recharts needs raw hex, not CSS vars). */
export const STATUS_COLORS = {
    success: '#4caf50',
    failed: '#f44336',
    pending: '#ff9800',
    waiting: '#2196f3',
    abandoned: '#f44336',
    accent: '#e94560',
    muted: '#aaa',
    surface2: '#0f3460',
} as const

export const PIE_COLORS = [
    STATUS_COLORS.success,
    STATUS_COLORS.failed,
    STATUS_COLORS.pending,
    STATUS_COLORS.waiting,
    STATUS_COLORS.abandoned,
    '#00bcd4',
    '#ff5722',
]
