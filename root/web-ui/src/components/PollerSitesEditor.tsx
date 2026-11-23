import { useState } from 'react'
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    Plus,
    Trash2,
    X,
} from 'lucide-react'
import type { SitePollerConfigValues } from '../api'
import { getSiteBadgeInfo } from '../statusColors'

const QUICK_ADD_SITES = ['fanfiction', 'royalroad', 'archiveofourown'] as const

const TIER_COLORS = {
    hot: { label: 'Hot', color: '#f87171', bg: 'rgba(239, 68, 68, 0.14)', border: 'rgba(239, 68, 68, 0.28)' },
    warm: { label: 'Warm', color: '#fbbf24', bg: 'rgba(245, 158, 11, 0.14)', border: 'rgba(245, 158, 11, 0.28)' },
    cool: { label: 'Cool', color: '#67e8f9', bg: 'rgba(6, 182, 212, 0.14)', border: 'rgba(6, 182, 212, 0.28)' },
    dormant: { label: 'Dormant', color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.12)', border: 'rgba(148, 163, 184, 0.26)' },
} as const

export function createDefaultSitePollerConfig(): SitePollerConfigValues {
    return {
        enabled: true,
        include_tags: [],
        exclude_tags: [],
        calibre_search_override: '',
        max_checks_per_day: 24,
        min_interval_minutes: 30,
        hot_max_age_days: 14,
        hot_interval_days: 1.5,
        warm_max_age_days: 90,
        warm_interval_days: 7,
        cool_max_age_days: 365,
        cool_interval_days: 21,
        dormant_interval_days: 60,
        jitter_ratio: 0.15,
        max_error_backoff_days: 30,
    }
}

function normalizeSiteConfig(raw: unknown): SitePollerConfigValues {
    const defaults = createDefaultSitePollerConfig()
    if (!raw || typeof raw !== 'object') return defaults
    const obj = raw as Record<string, unknown>
    return {
        enabled: typeof obj.enabled === 'boolean' ? obj.enabled : defaults.enabled,
        include_tags: Array.isArray(obj.include_tags) ? obj.include_tags.map(String) : defaults.include_tags,
        exclude_tags: Array.isArray(obj.exclude_tags) ? obj.exclude_tags.map(String) : defaults.exclude_tags,
        calibre_search_override:
            typeof obj.calibre_search_override === 'string'
                ? obj.calibre_search_override
                : defaults.calibre_search_override,
        max_checks_per_day:
            typeof obj.max_checks_per_day === 'number' ? obj.max_checks_per_day : defaults.max_checks_per_day,
        min_interval_minutes:
            typeof obj.min_interval_minutes === 'number' ? obj.min_interval_minutes : defaults.min_interval_minutes,
        hot_max_age_days:
            typeof obj.hot_max_age_days === 'number' ? obj.hot_max_age_days : defaults.hot_max_age_days,
        hot_interval_days:
            typeof obj.hot_interval_days === 'number' ? obj.hot_interval_days : defaults.hot_interval_days,
        warm_max_age_days:
            typeof obj.warm_max_age_days === 'number' ? obj.warm_max_age_days : defaults.warm_max_age_days,
        warm_interval_days:
            typeof obj.warm_interval_days === 'number' ? obj.warm_interval_days : defaults.warm_interval_days,
        cool_max_age_days:
            typeof obj.cool_max_age_days === 'number' ? obj.cool_max_age_days : defaults.cool_max_age_days,
        cool_interval_days:
            typeof obj.cool_interval_days === 'number' ? obj.cool_interval_days : defaults.cool_interval_days,
        dormant_interval_days:
            typeof obj.dormant_interval_days === 'number' ? obj.dormant_interval_days : defaults.dormant_interval_days,
        jitter_ratio: typeof obj.jitter_ratio === 'number' ? obj.jitter_ratio : defaults.jitter_ratio,
        max_error_backoff_days:
            typeof obj.max_error_backoff_days === 'number'
                ? obj.max_error_backoff_days
                : defaults.max_error_backoff_days,
    }
}

function TagChipInput({
    id,
    label,
    tags,
    placeholder,
    onChange,
}: {
    id: string
    label: string
    tags: string[]
    placeholder: string
    onChange: (next: string[]) => void
}) {
    const [draft, setDraft] = useState('')

    const commitDraft = () => {
        const raw = draft.trim()
        if (!raw) return
        const additions = raw
            .split(',')
            .map((s) => s.trim())
            .filter((s) => s.length > 0 && !tags.includes(s))
        if (additions.length > 0) {
            onChange([...tags, ...additions])
        }
        setDraft('')
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <label
                htmlFor={id}
                style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                }}
            >
                {label}
            </label>
            {tags.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                    {tags.map((tag, idx) => (
                        <span
                            key={`${tag}-${idx}`}
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.3rem',
                                padding: '0.16rem 0.45rem',
                                borderRadius: 6,
                                background: 'var(--surface2)',
                                border: '1px solid var(--border)',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '0.74rem',
                            }}
                        >
                            <span>{tag}</span>
                            <button
                                type="button"
                                aria-label={`Remove tag ${tag}`}
                                onClick={() => onChange(tags.filter((_, i) => i !== idx))}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    padding: 2,
                                    minHeight: 'auto',
                                    color: 'var(--text-muted)',
                                    cursor: 'pointer',
                                }}
                            >
                                <X size={11} />
                            </button>
                        </span>
                    ))}
                </div>
            )}
            <div style={{ display: 'flex', gap: '0.35rem' }}>
                <input
                    id={id}
                    type="text"
                    value={draft}
                    placeholder={placeholder}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={commitDraft}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault()
                            commitDraft()
                        }
                    }}
                    style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', padding: '0.4rem 0.6rem', flex: 1 }}
                />
                <button
                    type="button"
                    className="secondary btn-sm"
                    onClick={commitDraft}
                    disabled={!draft.trim()}
                >
                    <Plus size={12} /> Add
                </button>
            </div>
        </div>
    )
}

interface PollerSitesEditorProps {
    sites: Record<string, unknown>
    onChange: (nextSites: Record<string, SitePollerConfigValues>) => void
}

export function PollerSitesEditor({ sites, onChange }: PollerSitesEditorProps) {
    const [newSiteName, setNewSiteName] = useState('')
    const [expandedAdvanced, setExpandedAdvanced] = useState<Record<string, boolean>>({})

    const normalizedSites: Record<string, SitePollerConfigValues> = {}
    for (const [k, v] of Object.entries(sites || {})) {
        normalizedSites[k] = normalizeSiteConfig(v)
    }

    const siteKeys = Object.keys(normalizedSites)

    const updateSiteField = <K extends keyof SitePollerConfigValues>(
        siteKey: string,
        field: K,
        value: SitePollerConfigValues[K]
    ) => {
        onChange({
            ...normalizedSites,
            [siteKey]: {
                ...normalizedSites[siteKey],
                [field]: value,
            },
        })
    }

    const handleRemoveSite = (siteKey: string) => {
        const next = { ...normalizedSites }
        delete next[siteKey]
        onChange(next)
    }

    const handleAddSite = (rawKey: string) => {
        const key = rawKey.trim().toLowerCase()
        if (!key || key in normalizedSites) return
        onChange({
            ...normalizedSites,
            [key]: createDefaultSitePollerConfig(),
        })
        setNewSiteName('')
    }

    const parseNumber = (raw: string, fallback: number, isInt = false): number => {
        if (raw.trim() === '') return fallback
        const n = isInt ? parseInt(raw, 10) : parseFloat(raw)
        return Number.isFinite(n) ? n : fallback
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', width: '100%' }}>
            {siteKeys.length === 0 ? (
                <div
                    style={{
                        padding: '0.85rem 1rem',
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--bg)',
                        border: '1px dashed var(--border-light)',
                        color: 'var(--text-muted)',
                        fontSize: '0.82rem',
                    }}
                >
                    No sites configured yet. Add a site below to enable adaptive Calibre library polling.
                </div>
            ) : (
                siteKeys.map((siteKey) => {
                    const cfg = normalizedSites[siteKey]
                    const siteInfo = getSiteBadgeInfo(siteKey)
                    const isAdvancedOpen = !!expandedAdvanced[siteKey]
                    const hasCustomTags =
                        cfg.include_tags.length > 0 ||
                        cfg.exclude_tags.length > 0 ||
                        cfg.calibre_search_override.trim().length > 0
                    const tierOrderInvalid =
                        cfg.hot_max_age_days >= cfg.warm_max_age_days ||
                        cfg.warm_max_age_days >= cfg.cool_max_age_days

                    return (
                        <div
                            key={siteKey}
                            style={{
                                padding: '0.95rem 1rem',
                                borderRadius: 'var(--radius-md)',
                                background: 'var(--bg)',
                                border: '1px solid var(--border-light)',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.85rem',
                            }}
                        >
                            {/* Site Card Header */}
                            <div
                                style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    gap: '0.6rem',
                                    flexWrap: 'wrap',
                                    paddingBottom: '0.65rem',
                                    borderBottom: '1px solid var(--border)',
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <span
                                        className="site-dot"
                                        style={{ background: siteInfo.color, width: 9, height: 9 }}
                                    />
                                    <span style={{ fontWeight: 700, fontSize: '0.92rem' }}>{siteInfo.name}</span>
                                    <code
                                        style={{
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '0.73rem',
                                            color: 'var(--text-faint)',
                                        }}
                                    >
                                        [library_poller.sites.{siteKey}]
                                    </code>
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                    <label
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.4rem',
                                            cursor: 'pointer',
                                            fontSize: '0.8rem',
                                            fontWeight: 600,
                                        }}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={cfg.enabled}
                                            onChange={(e) => updateSiteField(siteKey, 'enabled', e.target.checked)}
                                            style={{ width: 16, height: 16 }}
                                        />
                                        <span>{cfg.enabled ? 'Enabled' : 'Disabled'}</span>
                                    </label>
                                    <button
                                        type="button"
                                        className="danger btn-sm"
                                        onClick={() => handleRemoveSite(siteKey)}
                                        title={`Remove ${siteKey} from library poller`}
                                    >
                                        <Trash2 size={13} /> Remove
                                    </button>
                                </div>
                            </div>

                            {/* Rate Budget Row */}
                            <div
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                                    gap: '0.75rem',
                                }}
                            >
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                    <label
                                        htmlFor={`poller-${siteKey}-max-checks`}
                                        style={{ fontSize: '0.76rem', fontWeight: 600, color: 'var(--text-muted)' }}
                                    >
                                        Max Checks / Day
                                    </label>
                                    <input
                                        id={`poller-${siteKey}-max-checks`}
                                        type="number"
                                        min={1}
                                        step={1}
                                        value={cfg.max_checks_per_day}
                                        onChange={(e) =>
                                            updateSiteField(
                                                siteKey,
                                                'max_checks_per_day',
                                                parseNumber(e.target.value, cfg.max_checks_per_day, true)
                                            )
                                        }
                                        style={{ fontFamily: 'var(--font-mono)', padding: '0.42rem 0.65rem' }}
                                    />
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                    <label
                                        htmlFor={`poller-${siteKey}-min-interval`}
                                        style={{ fontSize: '0.76rem', fontWeight: 600, color: 'var(--text-muted)' }}
                                    >
                                        Min Cooldown (min)
                                    </label>
                                    <input
                                        id={`poller-${siteKey}-min-interval`}
                                        type="number"
                                        min={0.5}
                                        step="any"
                                        value={cfg.min_interval_minutes}
                                        onChange={(e) =>
                                            updateSiteField(
                                                siteKey,
                                                'min_interval_minutes',
                                                parseNumber(e.target.value, cfg.min_interval_minutes)
                                            )
                                        }
                                        style={{ fontFamily: 'var(--font-mono)', padding: '0.42rem 0.65rem' }}
                                    />
                                </div>
                            </div>

                            {/* Adaptive Tiers Grid */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                                <div
                                    style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        alignItems: 'center',
                                        flexWrap: 'wrap',
                                        gap: '0.4rem',
                                    }}
                                >
                                    <span
                                        style={{
                                            fontSize: '0.75rem',
                                            fontWeight: 700,
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.04em',
                                            color: 'var(--text-muted)',
                                        }}
                                    >
                                        Adaptive Tiers
                                    </span>
                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-faint)' }}>
                                        Stories with regular history auto-use their detected cadence
                                    </span>
                                </div>

                                <div
                                    style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                                        gap: '0.5rem',
                                    }}
                                >
                                    {/* Hot Tier */}
                                    <div
                                        style={{
                                            padding: '0.55rem 0.7rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: TIER_COLORS.hot.bg,
                                            border: `1px solid ${TIER_COLORS.hot.border}`,
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.4rem',
                                        }}
                                    >
                                        <span style={{ fontSize: '0.76rem', fontWeight: 700, color: TIER_COLORS.hot.color }}>
                                            Hot
                                        </span>
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.35rem',
                                                flexWrap: 'wrap',
                                                fontSize: '0.76rem',
                                                color: 'var(--text-muted)',
                                            }}
                                        >
                                            <span>Updated within</span>
                                            <input
                                                aria-label={`${siteKey} hot max age days`}
                                                type="number"
                                                min={1}
                                                step={1}
                                                value={cfg.hot_max_age_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'hot_max_age_days',
                                                        parseNumber(e.target.value, cfg.hot_max_age_days, true)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d → every</span>
                                            <input
                                                aria-label={`${siteKey} hot interval days`}
                                                type="number"
                                                min={0.1}
                                                step="any"
                                                value={cfg.hot_interval_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'hot_interval_days',
                                                        parseNumber(e.target.value, cfg.hot_interval_days)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d</span>
                                        </div>
                                    </div>

                                    {/* Warm Tier */}
                                    <div
                                        style={{
                                            padding: '0.55rem 0.7rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: TIER_COLORS.warm.bg,
                                            border: `1px solid ${TIER_COLORS.warm.border}`,
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.4rem',
                                        }}
                                    >
                                        <span style={{ fontSize: '0.76rem', fontWeight: 700, color: TIER_COLORS.warm.color }}>
                                            Warm
                                        </span>
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.35rem',
                                                flexWrap: 'wrap',
                                                fontSize: '0.76rem',
                                                color: 'var(--text-muted)',
                                            }}
                                        >
                                            <span>Updated within</span>
                                            <input
                                                aria-label={`${siteKey} warm max age days`}
                                                type="number"
                                                min={2}
                                                step={1}
                                                value={cfg.warm_max_age_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'warm_max_age_days',
                                                        parseNumber(e.target.value, cfg.warm_max_age_days, true)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d → every</span>
                                            <input
                                                aria-label={`${siteKey} warm interval days`}
                                                type="number"
                                                min={0.1}
                                                step="any"
                                                value={cfg.warm_interval_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'warm_interval_days',
                                                        parseNumber(e.target.value, cfg.warm_interval_days)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d</span>
                                        </div>
                                    </div>

                                    {/* Cool Tier */}
                                    <div
                                        style={{
                                            padding: '0.55rem 0.7rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: TIER_COLORS.cool.bg,
                                            border: `1px solid ${TIER_COLORS.cool.border}`,
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.4rem',
                                        }}
                                    >
                                        <span style={{ fontSize: '0.76rem', fontWeight: 700, color: TIER_COLORS.cool.color }}>
                                            Cool
                                        </span>
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.35rem',
                                                flexWrap: 'wrap',
                                                fontSize: '0.76rem',
                                                color: 'var(--text-muted)',
                                            }}
                                        >
                                            <span>Updated within</span>
                                            <input
                                                aria-label={`${siteKey} cool max age days`}
                                                type="number"
                                                min={3}
                                                step={1}
                                                value={cfg.cool_max_age_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'cool_max_age_days',
                                                        parseNumber(e.target.value, cfg.cool_max_age_days, true)
                                                    )
                                                }
                                                style={{
                                                    width: 68,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d → every</span>
                                            <input
                                                aria-label={`${siteKey} cool interval days`}
                                                type="number"
                                                min={0.1}
                                                step="any"
                                                value={cfg.cool_interval_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'cool_interval_days',
                                                        parseNumber(e.target.value, cfg.cool_interval_days)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d</span>
                                        </div>
                                    </div>

                                    {/* Dormant Tier */}
                                    <div
                                        style={{
                                            padding: '0.55rem 0.7rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: TIER_COLORS.dormant.bg,
                                            border: `1px solid ${TIER_COLORS.dormant.border}`,
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.4rem',
                                        }}
                                    >
                                        <span
                                            style={{ fontSize: '0.76rem', fontWeight: 700, color: TIER_COLORS.dormant.color }}
                                        >
                                            Dormant
                                        </span>
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.35rem',
                                                flexWrap: 'wrap',
                                                fontSize: '0.76rem',
                                                color: 'var(--text-muted)',
                                            }}
                                        >
                                            <span>Older than {cfg.cool_max_age_days}d → every</span>
                                            <input
                                                aria-label={`${siteKey} dormant interval days`}
                                                type="number"
                                                min={0.1}
                                                step="any"
                                                value={cfg.dormant_interval_days}
                                                onChange={(e) =>
                                                    updateSiteField(
                                                        siteKey,
                                                        'dormant_interval_days',
                                                        parseNumber(e.target.value, cfg.dormant_interval_days)
                                                    )
                                                }
                                                style={{
                                                    width: 64,
                                                    padding: '0.22rem 0.4rem',
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                }}
                                            />
                                            <span>d</span>
                                        </div>
                                    </div>
                                </div>

                                {tierOrderInvalid && (
                                    <div
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.4rem',
                                            fontSize: '0.75rem',
                                            color: 'var(--warning)',
                                            marginTop: '0.15rem',
                                        }}
                                    >
                                        <AlertTriangle size={13} />
                                        <span>
                                            Tier age thresholds must strictly increase: Hot ({cfg.hot_max_age_days}d) &lt;
                                            Warm ({cfg.warm_max_age_days}d) &lt; Cool ({cfg.cool_max_age_days}d).
                                        </span>
                                    </div>
                                )}
                            </div>

                            {/* Collapsible Advanced / Tag Overrides */}
                            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.55rem' }}>
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={() =>
                                        setExpandedAdvanced((prev) => ({
                                            ...prev,
                                            [siteKey]: !prev[siteKey],
                                        }))
                                    }
                                    style={{
                                        background: 'transparent',
                                        border: 'none',
                                        padding: '0.2rem 0.1rem',
                                        minHeight: 'auto',
                                        color: 'var(--text-muted)',
                                        fontSize: '0.77rem',
                                    }}
                                >
                                    {isAdvancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                    <span>Advanced / Tag Overrides</span>
                                    {hasCustomTags && (
                                        <span
                                            className="badge badge-info"
                                            style={{ fontSize: '0.66rem', padding: '0.06rem 0.35rem' }}
                                        >
                                            Custom
                                        </span>
                                    )}
                                </button>

                                {isAdvancedOpen && (
                                    <div
                                        style={{
                                            marginTop: '0.65rem',
                                            padding: '0.75rem',
                                            borderRadius: 'var(--radius-sm)',
                                            background: 'var(--surface)',
                                            border: '1px solid var(--border)',
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.75rem',
                                        }}
                                    >
                                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                                            Leave empty to auto-detect status tags from{' '}
                                            <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
                                                personal.ini
                                            </code>{' '}
                                            /{' '}
                                            <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
                                                defaults.ini
                                            </code>
                                            .
                                        </p>

                                        <div
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                                                gap: '0.75rem',
                                            }}
                                        >
                                            <TagChipInput
                                                id={`poller-${siteKey}-include-tags`}
                                                label="include_tags"
                                                tags={cfg.include_tags}
                                                placeholder="e.g. In-Progress (auto-detect if empty)"
                                                onChange={(next) => updateSiteField(siteKey, 'include_tags', next)}
                                            />
                                            <TagChipInput
                                                id={`poller-${siteKey}-exclude-tags`}
                                                label="exclude_tags"
                                                tags={cfg.exclude_tags}
                                                placeholder="e.g. Completed, Abandoned (auto-detect if empty)"
                                                onChange={(next) => updateSiteField(siteKey, 'exclude_tags', next)}
                                            />
                                        </div>

                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                            <label
                                                htmlFor={`poller-${siteKey}-search-override`}
                                                style={{
                                                    fontSize: '0.75rem',
                                                    fontWeight: 600,
                                                    color: 'var(--text-muted)',
                                                    fontFamily: 'var(--font-mono)',
                                                }}
                                            >
                                                calibre_search_override
                                            </label>
                                            <input
                                                id={`poller-${siteKey}-search-override`}
                                                type="text"
                                                value={cfg.calibre_search_override}
                                                placeholder='Optional custom Calibre search (e.g. tags:"=In-Progress")'
                                                onChange={(e) =>
                                                    updateSiteField(siteKey, 'calibre_search_override', e.target.value)
                                                }
                                                style={{
                                                    fontFamily: 'var(--font-mono)',
                                                    fontSize: '0.78rem',
                                                    padding: '0.4rem 0.6rem',
                                                }}
                                            />
                                        </div>

                                        <div
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
                                                gap: '0.75rem',
                                            }}
                                        >
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                                <label
                                                    htmlFor={`poller-${siteKey}-jitter`}
                                                    style={{
                                                        fontSize: '0.75rem',
                                                        fontWeight: 600,
                                                        color: 'var(--text-muted)',
                                                        fontFamily: 'var(--font-mono)',
                                                    }}
                                                >
                                                    jitter_ratio (0–0.5)
                                                </label>
                                                <input
                                                    id={`poller-${siteKey}-jitter`}
                                                    type="number"
                                                    min={0}
                                                    max={0.5}
                                                    step={0.05}
                                                    value={cfg.jitter_ratio}
                                                    onChange={(e) =>
                                                        updateSiteField(
                                                            siteKey,
                                                            'jitter_ratio',
                                                            parseNumber(e.target.value, cfg.jitter_ratio)
                                                        )
                                                    }
                                                    style={{
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '0.78rem',
                                                        padding: '0.4rem 0.6rem',
                                                    }}
                                                />
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                                <label
                                                    htmlFor={`poller-${siteKey}-backoff`}
                                                    style={{
                                                        fontSize: '0.75rem',
                                                        fontWeight: 600,
                                                        color: 'var(--text-muted)',
                                                        fontFamily: 'var(--font-mono)',
                                                    }}
                                                >
                                                    max_error_backoff_days
                                                </label>
                                                <input
                                                    id={`poller-${siteKey}-backoff`}
                                                    type="number"
                                                    min={1}
                                                    step="any"
                                                    value={cfg.max_error_backoff_days}
                                                    onChange={(e) =>
                                                        updateSiteField(
                                                            siteKey,
                                                            'max_error_backoff_days',
                                                            parseNumber(e.target.value, cfg.max_error_backoff_days)
                                                        )
                                                    }
                                                    style={{
                                                        fontFamily: 'var(--font-mono)',
                                                        fontSize: '0.78rem',
                                                        padding: '0.4rem 0.6rem',
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )
                })
            )}

            {/* Add Site Row */}
            <div
                style={{
                    padding: '0.75rem 0.9rem',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.55rem',
                }}
            >
                <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
                    <input
                        type="text"
                        value={newSiteName}
                        placeholder="Add site identifier (e.g. fanfiction, royalroad, archiveofourown)"
                        onChange={(e) => setNewSiteName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault()
                                handleAddSite(newSiteName)
                            }
                        }}
                        style={{ fontFamily: 'var(--font-mono)', flex: 1, minWidth: 200 }}
                    />
                    <button
                        type="button"
                        className="secondary btn-sm"
                        disabled={!newSiteName.trim() || newSiteName.trim().toLowerCase() in normalizedSites}
                        onClick={() => handleAddSite(newSiteName)}
                    >
                        <Plus size={14} /> Add Site
                    </button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.73rem', color: 'var(--text-faint)' }}>Quick add:</span>
                    {QUICK_ADD_SITES.map((preset) => {
                        const alreadyAdded = preset in normalizedSites
                        const info = getSiteBadgeInfo(preset)
                        return (
                            <button
                                key={preset}
                                type="button"
                                className="secondary btn-sm"
                                disabled={alreadyAdded}
                                onClick={() => handleAddSite(preset)}
                                style={{
                                    padding: '0.18rem 0.55rem',
                                    minHeight: 26,
                                    fontSize: '0.73rem',
                                    fontFamily: 'var(--font-mono)',
                                }}
                                title={alreadyAdded ? `${preset} is already configured` : `Add ${info.name}`}
                            >
                                <span
                                    className="site-dot"
                                    style={{ background: info.color, width: 6, height: 6 }}
                                />
                                <span>{preset}</span>
                                {!alreadyAdded && <Plus size={11} />}
                            </button>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
