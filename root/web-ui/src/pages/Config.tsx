import { useEffect, useState, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
    getConfig,
    updateConfigSection,
    testConfigSection,
    getIniFile,
    updateIniFile,
    ReloadBehavior,
    ConfigUpdateResult,
    ConfigTestResult,
} from '../api'
import {
    computeDirtySections,
    computeIniLineDiff,
    extractIniSections,
} from '../utils/dashboardLogic'
import {
    Settings,
    Save,
    RotateCcw,
    CheckCircle2,
    AlertTriangle,
    Eye,
    EyeOff,
    FileCode,
    PlugZap,
    Plus,
    X,
} from 'lucide-react'

const SECTION_META: Record<string, { label: string; description: string; testable?: boolean }> = {
    email: {
        label: 'IMAP Mailbox Watcher',
        description: 'Polls an email inbox for incoming fanfiction update notifications.',
        testable: true,
    },
    calibre: {
        label: 'Calibre Library',
        description: 'Configures the local path or Calibre Content Server URL and update strategy.',
        testable: true,
    },
    pushbullet: {
        label: 'Pushbullet Alerts',
        description: 'Push notification delivery via Pushbullet API key and device.',
        testable: true,
    },
    apprise: {
        label: 'Apprise Targets',
        description: 'Universal notification URLs (Discord, Telegram, Slack, Gotify, Ntfy).',
        testable: true,
    },
    retry: {
        label: 'Retry & Hail-Mary',
        description: 'Controls exponential retry attempts and final Hail-Mary protocol wait hours.',
    },
    process: {
        label: 'Process Supervisor',
        description: 'Controls daemon healthchecks, auto-restart policies, and shutdown timeouts.',
    },
    web: {
        label: 'Web Server & DB',
        description: 'FastAPI server host, port, and SQLite history database path.',
    },
}

const FIELD_DESCRIPTIONS: Record<string, Record<string, string>> = {
    email: {
        email: 'IMAP account username or email address used to receive story update notifications.',
        password: 'IMAP password or app-specific password (stored encrypted/masked).',
        server: 'IMAP server hostname (e.g., imap.gmail.com or mail.example.com).',
        mailbox: 'Folder/mailbox name to monitor for unread fanfiction update emails (default: INBOX).',
        sleep_time: 'Fallback polling interval in seconds when IMAP IDLE push is unavailable.',
        disabled_sites: 'List of site identifiers to ignore even if matching URLs arrive in email.',
    },
    calibre: {
        path: 'Local filesystem path to your Calibre library or HTTP(S) URL to a Calibre Content Server.',
        username: 'Optional username for authenticating with a password-protected Calibre Content Server.',
        password: 'Optional password for authenticating with a Calibre Content Server.',
        personal_ini: 'Path to your custom FanFicFare personal.ini configuration file.',
        update_method:
            'FanFicFare mode: "update" (append new chapters), "update_always" (update metadata even if no new chapters), or "force" (overwrite from Chapter 1).',
        update_only: 'If enabled, only updates stories that already exist in your Calibre library and skips brand-new stories.',
        metadata_preservation_mode:
            'How Calibre updates existing books: "remove_add" (re-imports updated EPUB while preserving custom columns/series) or "in_place".',
    },
    pushbullet: {
        enabled: 'Enable or disable sending push notifications through Pushbullet.',
        api_key: 'Your Pushbullet Access Token from Account Settings.',
        device: 'Optional specific device nickname to target (leave blank to notify all devices).',
    },
    apprise: {
        urls: 'List of Apprise notification service URLs (e.g., discord://, tgram://, slack://, ntfys://) notified on story updates and failures.',
    },
    retry: {
        hail_mary_enabled:
            'After all normal retries are exhausted, schedule one final "Hail-Mary" attempt after a long cooldown before abandoning.',
        hail_mary_wait_hours: 'Number of hours to wait before firing the final Hail-Mary retry attempt (default: 12 hours).',
        max_normal_retries:
            'Maximum number of exponential backoff retry attempts (1 min up to 45 min) before triggering Hail-Mary or abandoning.',
        resume_uncompleted_on_startup:
            'On container startup, query SQLite history and automatically re-queue any downloads or retries that were interrupted.',
    },
    process: {
        shutdown_timeout: 'Maximum seconds to wait for active worker processes to finish cleanly on SIGTERM before force-killing.',
        health_check_interval: 'Interval in seconds between supervisor health checks of background worker processes.',
        auto_restart: 'Automatically restart any background daemon process (UrlIngester, Coordinator, FFWaiter) if it crashes.',
        max_restart_attempts: 'Maximum consecutive crash restarts allowed before marking a daemon process as failed.',
        restart_delay: 'Cooldown delay in seconds before restarting a crashed background process.',
        enable_monitoring: 'Enable internal process state and queue telemetry collection.',
        signal_timeout: 'Timeout in seconds when propagating stop signals to child subprocesses.',
    },
    web: {
        enabled: 'Enable the built-in FastAPI web dashboard and WebSocket telemetry server.',
        host: 'Network interface IP address to bind the web server to (0.0.0.0 listens on all interfaces).',
        port: 'TCP port for the web dashboard and API server (default: 8080).',
        history_db_path: 'Filesystem path to the SQLite database file storing download, retry, and notification history.',
    },
}

const ENUM_OPTIONS: Record<string, string[]> = {
    'calibre.update_method': ['update', 'update_always', 'force'],
    'calibre.metadata_preservation_mode': ['remove_add', 'in_place'],
}

function ReloadBadge({ tier }: { tier?: ReloadBehavior }) {
    if (tier === 'app_restart') {
        return <span className="badge badge-app">Requires App Restart</span>
    }
    return null
}

export default function Config() {
    const [searchParams] = useSearchParams()
    const [config, setConfig] = useState<Record<string, unknown> | null>(null)
    const [initialConfig, setInitialConfig] = useState<Record<string, unknown> | null>(null)
    const [reloadMap, setReloadMap] = useState<Record<string, Record<string, ReloadBehavior>>>({})
    const [activeTab, setActiveTab] = useState<string>(() => searchParams.get('tab') || 'email')
    const [personalIni, setPersonalIni] = useState<string>('')
    const [initialPersonalIni, setInitialPersonalIni] = useState<string>('')
    const [defaultsIni, setDefaultsIni] = useState<string>('')
    const [saving, setSaving] = useState(false)
    const [testing, setTesting] = useState(false)
    const [testResult, setTestResult] = useState<ConfigTestResult | null>(null)
    const [result, setResult] = useState<ConfigUpdateResult | null>(null)
    const [iniSaved, setIniSaved] = useState(false)
    const [showIniDiff, setShowIniDiff] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [revealed, setRevealed] = useState<Record<string, boolean>>({})
    const [arrayDrafts, setArrayDrafts] = useState<Record<string, string>>({})
    const iniTextareaRef = useRef<HTMLTextAreaElement | null>(null)

    useEffect(() => {
        const paramTab = searchParams.get('tab')
        if (paramTab) {
            setActiveTab(paramTab)
        }
    }, [searchParams])

    useEffect(() => {
        getConfig()
            .then((res) => {
                setConfig(structuredClone(res.config))
                setInitialConfig(structuredClone(res.config))
                setReloadMap(res.reload_map || {})
            })
            .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load config'))

        getIniFile('personal')
            .then((res) => {
                const content = res.content || ''
                setPersonalIni(content)
                setInitialPersonalIni(content)
            })
            .catch(() => {})
        getIniFile('defaults')
            .then((res) => setDefaultsIni(res.content || ''))
            .catch(() => {})
    }, [])

    // Global dirty tracking across ALL sections + personal.ini
    const dirtyBySection = useMemo(
        () => computeDirtySections(config, initialConfig, personalIni, initialPersonalIni),
        [config, initialConfig, personalIni, initialPersonalIni]
    )

    const dirtySectionKeys = useMemo(() => {
        const list = dirtyBySection[activeTab] || []
        return new Set(list)
    }, [dirtyBySection, activeTab])

    const totalUnsavedSectionsCount = Object.keys(dirtyBySection).length

    const handleFieldChange = (section: string, key: string, val: unknown) => {
        if (!config) return
        setConfig({
            ...config,
            [section]: {
                ...(config[section] as Record<string, unknown>),
                [key]: val,
            },
        })
        setResult(null)
        setTestResult(null)
    }

    const handleSaveSection = async () => {
        if (!config || activeTab.endsWith('.ini')) return
        setSaving(true)
        setResult(null)
        setError(null)
        try {
            const values = (config[activeTab] || {}) as Record<string, unknown>
            const res = await updateConfigSection(activeTab, values)
            setResult(res)
            if (initialConfig) {
                setInitialConfig({
                    ...initialConfig,
                    [activeTab]: structuredClone(values),
                })
            }
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Save failed')
        } finally {
            setSaving(false)
        }
    }

    const handleTestSection = async () => {
        if (!config || activeTab.endsWith('.ini')) return
        setTesting(true)
        setTestResult(null)
        setError(null)
        try {
            const values = (config[activeTab] || {}) as Record<string, unknown>
            const res = await testConfigSection(activeTab, values)
            setTestResult(res)
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Connection test failed')
        } finally {
            setTesting(false)
        }
    }

    const handleSavePersonalIni = async () => {
        setSaving(true)
        setIniSaved(false)
        setError(null)
        try {
            const res = await updateIniFile('personal', personalIni)
            if (res.applied) {
                setIniSaved(true)
                setInitialPersonalIni(personalIni)
            } else {
                setError(res.error || 'Failed to save personal.ini')
            }
        } finally {
            setSaving(false)
        }
    }

    if (!config) {
        return (
            <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                Loading configuration…
            </div>
        )
    }

    const sections = Object.keys(config).filter(
        (k) => typeof config[k] === 'object' && config[k] !== null
    )

    const isIniTab = activeTab === 'personal.ini' || activeTab === 'defaults.ini'
    const currentFields = (!isIniTab ? config[activeTab] || {} : {}) as Record<string, unknown>
    const meta = SECTION_META[activeTab] || {
        label: activeTab,
        description: `Settings for [${activeTab}] in config.toml`,
    }

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    marginBottom: '1rem',
                }}
            >
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                        Configuration
                    </h1>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        Manage <code style={{ fontFamily: 'monospace' }}>config.toml</code> settings and{' '}
                        <code style={{ fontFamily: 'monospace' }}>personal.ini</code> rules
                        {totalUnsavedSectionsCount > 0 && (
                            <span style={{ color: 'var(--warning)', marginLeft: '0.5rem', fontWeight: 600 }}>
                                • {totalUnsavedSectionsCount} section{totalUnsavedSectionsCount > 1 ? 's' : ''} with unsaved changes
                            </span>
                        )}
                    </p>
                </div>

                {!isIniTab && (
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        {meta.testable && (
                            <button
                                type="button"
                                className="secondary"
                                onClick={handleTestSection}
                                disabled={testing}
                                title={`Verify [${activeTab}] connectivity and credentials`}
                            >
                                <PlugZap size={15} />
                                {testing ? 'Testing…' : `Test [${activeTab}]`}
                            </button>
                        )}
                        {dirtySectionKeys.size > 0 && initialConfig && (
                            <button
                                type="button"
                                className="secondary"
                                onClick={() => {
                                    setConfig({
                                        ...config,
                                        [activeTab]: structuredClone(initialConfig[activeTab]),
                                    })
                                    setResult(null)
                                    setTestResult(null)
                                }}
                            >
                                <RotateCcw size={15} /> Discard ({dirtySectionKeys.size})
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={handleSaveSection}
                            disabled={saving || dirtySectionKeys.size === 0}
                        >
                            <Save size={15} />
                            {saving
                                ? 'Saving…'
                                : dirtySectionKeys.size > 0
                                  ? `Save [${activeTab}] (${dirtySectionKeys.size})`
                                  : 'Saved'}
                        </button>
                    </div>
                )}
            </div>

            {testResult && (
                <div
                    className="card"
                    style={{
                        borderColor: testResult.ok
                            ? 'rgba(16, 185, 129, 0.35)'
                            : 'rgba(239, 68, 68, 0.4)',
                        background: testResult.ok
                            ? 'rgba(16, 185, 129, 0.08)'
                            : 'rgba(239, 68, 68, 0.08)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '0.75rem',
                        flexWrap: 'wrap',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: testResult.ok ? 'var(--success)' : 'var(--error)',
                            fontWeight: 600,
                            fontSize: '0.86rem',
                        }}
                    >
                        {testResult.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                        <span>{testResult.message}</span>
                    </div>
                    <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                        {testResult.latency_ms} ms
                    </span>
                </div>
            )}

            {result && (
                <div
                    className="card"
                    style={{
                        borderColor: result.needs_app_restart
                            ? 'rgba(245, 158, 11, 0.4)'
                            : 'rgba(16, 185, 129, 0.35)',
                        background: result.needs_app_restart
                            ? 'rgba(245, 158, 11, 0.08)'
                            : 'rgba(16, 185, 129, 0.08)',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: 'var(--success)',
                            fontWeight: 600,
                        }}
                    >
                        <CheckCircle2 size={16} />
                        <span>Saved [{activeTab}] settings. Background changes have been applied.</span>
                    </div>
                    {result.needs_service_restart && (
                        <div style={{ fontSize: '0.82rem', color: 'var(--info)', marginTop: '0.35rem' }}>
                            Supervisor restarted daemon worker for{' '}
                            <code>{result.results?.service_restart.join(', ')}</code>.
                        </div>
                    )}
                    {result.needs_app_restart && (
                        <div style={{ fontSize: '0.82rem', color: 'var(--warning)', marginTop: '0.35rem' }}>
                            Note: Restart the application/container for{' '}
                            <code>{result.results?.app_restart.join(', ')}</code> to take effect.
                        </div>
                    )}
                </div>
            )}

            {error && (
                <div
                    className="card"
                    style={{
                        borderColor: 'rgba(239, 68, 68, 0.4)',
                        color: 'var(--error)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                    }}
                >
                    <AlertTriangle size={16} />
                    <span>{error}</span>
                </div>
            )}

            {/* Mobile Section Selector Dropdown */}
            <div className="config-mobile-picker">
                <label
                    htmlFor="mobile-config-section-select"
                    style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--text-muted)',
                        marginBottom: '0.35rem',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                    }}
                >
                    Configuration Section
                </label>
                <select
                    id="mobile-config-section-select"
                    value={activeTab}
                    onChange={(e) => {
                        setActiveTab(e.target.value)
                        setResult(null)
                        setTestResult(null)
                    }}
                    style={{ background: 'var(--surface)', fontWeight: 600 }}
                >
                    <optgroup label="config.toml Sections">
                        {sections.map((sec) => {
                            const secDirty = dirtyBySection[sec]?.length || 0
                            return (
                                <option key={sec} value={sec}>
                                    {SECTION_META[sec]?.label || sec} ([{sec}])
                                    {secDirty > 0 ? ` • ${secDirty} unsaved` : ''}
                                </option>
                            )
                        })}
                    </optgroup>
                    <optgroup label="FanFicFare INI">
                        <option value="personal.ini">
                            personal.ini (Custom Rules)
                            {dirtyBySection['personal.ini'] ? ' • unsaved' : ''}
                        </option>
                        <option value="defaults.ini">defaults.ini (Read-Only)</option>
                    </optgroup>
                </select>
            </div>

            <div className="config-layout">
                {/* Desktop Left Section Navigation */}
                <div className="card config-desktop-nav" style={{ padding: '0.65rem' }}>
                    <div
                        style={{
                            fontSize: '0.72rem',
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            color: 'var(--text-muted)',
                            padding: '0.4rem 0.6rem',
                        }}
                    >
                        config.toml Sections
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                        {sections.map((sec) => {
                            const secDirtyCount = dirtyBySection[sec]?.length || 0
                            return (
                                <button
                                    key={sec}
                                    type="button"
                                    className={activeTab === sec ? '' : 'secondary'}
                                    style={{ justifyContent: 'space-between', width: '100%' }}
                                    onClick={() => {
                                        setActiveTab(sec)
                                        setResult(null)
                                        setTestResult(null)
                                    }}
                                >
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
                                        <Settings size={15} />
                                        <span>{SECTION_META[sec]?.label || sec}</span>
                                    </span>
                                    {secDirtyCount > 0 && (
                                        <span
                                            className="tabular-nums"
                                            style={{
                                                fontSize: '0.7rem',
                                                padding: '0.1rem 0.4rem',
                                                borderRadius: 6,
                                                background: 'rgba(245, 158, 11, 0.2)',
                                                color: 'var(--warning)',
                                                fontWeight: 700,
                                            }}
                                        >
                                            {secDirtyCount}
                                        </span>
                                    )}
                                </button>
                            )
                        })}

                        <div
                            style={{
                                fontSize: '0.72rem',
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.06em',
                                color: 'var(--text-muted)',
                                padding: '0.75rem 0.6rem 0.3rem 0.6rem',
                            }}
                        >
                            FanFicFare INI
                        </div>
                        <button
                            type="button"
                            className={activeTab === 'personal.ini' ? '' : 'secondary'}
                            style={{ justifyContent: 'space-between', width: '100%' }}
                            onClick={() => setActiveTab('personal.ini')}
                        >
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
                                <FileCode size={15} />
                                <span>personal.ini</span>
                            </span>
                            {dirtyBySection['personal.ini'] && (
                                <span
                                    style={{
                                        fontSize: '0.7rem',
                                        padding: '0.1rem 0.4rem',
                                        borderRadius: 6,
                                        background: 'rgba(245, 158, 11, 0.2)',
                                        color: 'var(--warning)',
                                        fontWeight: 700,
                                    }}
                                >
                                    •
                                </span>
                            )}
                        </button>
                        <button
                            type="button"
                            className={activeTab === 'defaults.ini' ? '' : 'secondary'}
                            style={{ justifyContent: 'flex-start', width: '100%' }}
                            onClick={() => setActiveTab('defaults.ini')}
                        >
                            <FileCode size={15} />
                            <span>defaults.ini (Read-Only)</span>
                        </button>
                    </div>
                </div>

                {/* Right Editor Surface */}
                <div className="card">
                    {!isIniTab ? (
                        <>
                            <div
                                style={{
                                    borderBottom: '1px solid var(--border)',
                                    paddingBottom: '0.85rem',
                                    marginBottom: '1rem',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'flex-start',
                                    gap: '0.5rem',
                                }}
                            >
                                <div style={{ minWidth: 0 }}>
                                    <h2 style={{ fontSize: '1.05rem' }}>{meta.label}</h2>
                                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                                        {meta.description}
                                    </p>
                                </div>
                                <span
                                    style={{
                                        fontFamily: 'monospace',
                                        fontSize: '0.78rem',
                                        color: 'var(--text-muted)',
                                        flexShrink: 0,
                                    }}
                                >
                                    [{activeTab}]
                                </span>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                                {Object.entries(currentFields).map(([key, val]) => {
                                    const tier = reloadMap[activeTab]?.[key]
                                    const isDirty = dirtySectionKeys.has(key)
                                    const description = FIELD_DESCRIPTIONS[activeTab]?.[key]
                                    const isSecret =
                                        key.toLowerCase().includes('password') ||
                                        key.toLowerCase().includes('api_key') ||
                                        key.toLowerCase().includes('token')
                                    const fieldId = `${activeTab}.${key}`
                                    const showSecret = !!revealed[fieldId]
                                    const enumChoices = ENUM_OPTIONS[fieldId]

                                    return (
                                        <div
                                            key={key}
                                            className={`config-field-row ${isDirty ? 'dirty' : ''}`}
                                        >
                                            <div style={{ minWidth: 0 }}>
                                                <div
                                                    style={{
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.5rem',
                                                        flexWrap: 'wrap',
                                                    }}
                                                >
                                                    <label
                                                        htmlFor={fieldId}
                                                        style={{
                                                            fontFamily: 'monospace',
                                                            fontWeight: 600,
                                                            fontSize: '0.86rem',
                                                            wordBreak: 'break-word',
                                                        }}
                                                    >
                                                        {key}
                                                    </label>
                                                    <ReloadBadge tier={tier} />
                                                    {isDirty && initialConfig && (
                                                        <span
                                                            style={{
                                                                display: 'inline-flex',
                                                                alignItems: 'center',
                                                                gap: '0.35rem',
                                                                fontSize: '0.72rem',
                                                                color: 'var(--warning)',
                                                                fontFamily: 'var(--font-mono)',
                                                            }}
                                                        >
                                                            <span>
                                                                (was:{' '}
                                                                {isSecret
                                                                    ? '••••••'
                                                                    : JSON.stringify(
                                                                          (initialConfig[activeTab] as Record<string, unknown>)?.[key]
                                                                      )}
                                                                )
                                                            </span>
                                                            <button
                                                                type="button"
                                                                className="secondary btn-sm"
                                                                onClick={() =>
                                                                    handleFieldChange(
                                                                        activeTab,
                                                                        key,
                                                                        structuredClone(
                                                                            (initialConfig[activeTab] as Record<string, unknown>)?.[key]
                                                                        )
                                                                    )
                                                                }
                                                                style={{
                                                                    padding: '0.08rem 0.38rem',
                                                                    minHeight: 20,
                                                                    fontSize: '0.68rem',
                                                                }}
                                                                title={`Reset ${key} to saved value`}
                                                            >
                                                                <RotateCcw size={10} /> Reset
                                                            </button>
                                                        </span>
                                                    )}
                                                </div>
                                                {description && (
                                                    <div
                                                        style={{
                                                            fontSize: '0.78rem',
                                                            color: 'var(--text-muted)',
                                                            marginTop: '0.25rem',
                                                            lineHeight: 1.4,
                                                        }}
                                                    >
                                                        {description}
                                                    </div>
                                                )}
                                            </div>

                                            <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', minWidth: 0, width: '100%' }}>
                                                {typeof val === 'boolean' ? (
                                                    <label
                                                        style={{
                                                            display: 'inline-flex',
                                                            alignItems: 'center',
                                                            gap: '0.5rem',
                                                            cursor: 'pointer',
                                                            fontSize: '0.85rem',
                                                        }}
                                                    >
                                                        <input
                                                            id={fieldId}
                                                            type="checkbox"
                                                            checked={val}
                                                            onChange={(e) =>
                                                                handleFieldChange(
                                                                    activeTab,
                                                                    key,
                                                                    e.target.checked
                                                                )
                                                            }
                                                            style={{ width: 18, height: 18 }}
                                                        />
                                                        <span>{val ? 'Enabled' : 'Disabled'}</span>
                                                    </label>
                                                ) : typeof val === 'number' ? (
                                                    <input
                                                        id={fieldId}
                                                        type="number"
                                                        step="any"
                                                        value={val}
                                                        onChange={(e) =>
                                                            handleFieldChange(
                                                                activeTab,
                                                                key,
                                                                Number(e.target.value)
                                                            )
                                                        }
                                                        style={{ fontFamily: 'monospace' }}
                                                    />
                                                ) : enumChoices ? (
                                                    <select
                                                        id={fieldId}
                                                        value={String(val ?? '')}
                                                        onChange={(e) =>
                                                            handleFieldChange(activeTab, key, e.target.value)
                                                        }
                                                        style={{ fontFamily: 'monospace' }}
                                                    >
                                                        {enumChoices.map((choice) => (
                                                            <option key={choice} value={choice}>
                                                                {choice}
                                                            </option>
                                                        ))}
                                                    </select>
                                                ) : Array.isArray(val) ? (
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', width: '100%' }}>
                                                        {val.length > 0 && (
                                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                                                                {val.map((item, idx) => (
                                                                    <span
                                                                        key={`${item}-${idx}`}
                                                                        style={{
                                                                            display: 'inline-flex',
                                                                            alignItems: 'center',
                                                                            gap: '0.35rem',
                                                                            padding: '0.2rem 0.5rem',
                                                                            borderRadius: 6,
                                                                            background: 'var(--bg)',
                                                                            border: '1px solid var(--border)',
                                                                            fontFamily: 'var(--font-mono)',
                                                                            fontSize: '0.76rem',
                                                                            maxWidth: '100%',
                                                                        }}
                                                                    >
                                                                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                                            {String(item)}
                                                                        </span>
                                                                        <button
                                                                            type="button"
                                                                            aria-label={`Remove ${String(item)}`}
                                                                            onClick={() =>
                                                                                handleFieldChange(
                                                                                    activeTab,
                                                                                    key,
                                                                                    val.filter((_, i) => i !== idx)
                                                                                )
                                                                            }
                                                                            style={{
                                                                                background: 'transparent',
                                                                                border: 'none',
                                                                                padding: 2,
                                                                                minHeight: 'auto',
                                                                                color: 'var(--text-muted)',
                                                                                cursor: 'pointer',
                                                                            }}
                                                                        >
                                                                            <X size={12} />
                                                                        </button>
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        )}
                                                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                                                            <input
                                                                id={fieldId}
                                                                type="text"
                                                                value={arrayDrafts[fieldId] || ''}
                                                                placeholder={
                                                                    key === 'urls'
                                                                        ? 'Add notification URL (e.g. discord://... or ntfys://...)'
                                                                        : 'Add item and press Enter or Add'
                                                                }
                                                                onChange={(e) =>
                                                                    setArrayDrafts((prev) => ({
                                                                        ...prev,
                                                                        [fieldId]: e.target.value,
                                                                    }))
                                                                }
                                                                onKeyDown={(e) => {
                                                                    if (e.key === 'Enter') {
                                                                        e.preventDefault()
                                                                        const raw = (arrayDrafts[fieldId] || '').trim()
                                                                        if (!raw) return
                                                                        const newItems = raw
                                                                            .split(',')
                                                                            .map((s) => s.trim())
                                                                            .filter(Boolean)
                                                                        handleFieldChange(activeTab, key, [...val, ...newItems])
                                                                        setArrayDrafts((prev) => ({ ...prev, [fieldId]: '' }))
                                                                    }
                                                                }}
                                                                style={{ fontFamily: 'monospace', flex: 1 }}
                                                            />
                                                            <button
                                                                type="button"
                                                                className="secondary btn-sm"
                                                                onClick={() => {
                                                                    const raw = (arrayDrafts[fieldId] || '').trim()
                                                                    if (!raw) return
                                                                    const newItems = raw
                                                                        .split(',')
                                                                        .map((s) => s.trim())
                                                                        .filter(Boolean)
                                                                    handleFieldChange(activeTab, key, [...val, ...newItems])
                                                                    setArrayDrafts((prev) => ({ ...prev, [fieldId]: '' }))
                                                                }}
                                                            >
                                                                <Plus size={14} /> Add
                                                            </button>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <>
                                                        <input
                                                            id={fieldId}
                                                            type={
                                                                isSecret && !showSecret
                                                                    ? 'password'
                                                                    : 'text'
                                                            }
                                                            value={String(val ?? '')}
                                                            onChange={(e) =>
                                                                handleFieldChange(
                                                                    activeTab,
                                                                    key,
                                                                    e.target.value
                                                                )
                                                            }
                                                            style={{ fontFamily: 'monospace', flex: 1, minWidth: 0 }}
                                                        />
                                                        {isSecret && (
                                                            <button
                                                                type="button"
                                                                className="secondary btn-sm"
                                                                aria-label={showSecret ? 'Hide secret' : 'Show secret'}
                                                                onClick={() =>
                                                                    setRevealed((r) => ({
                                                                        ...r,
                                                                        [fieldId]: !r[fieldId],
                                                                    }))
                                                                }
                                                            >
                                                                {showSecret ? (
                                                                    <EyeOff size={14} />
                                                                ) : (
                                                                    <Eye size={14} />
                                                                )}
                                                            </button>
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </>
                    ) : (
                        <>
                            <div
                                style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    flexWrap: 'wrap',
                                    gap: '0.75rem',
                                    marginBottom: '1rem',
                                }}
                            >
                                <div>
                                    <h2>{activeTab}</h2>
                                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                                        {activeTab === 'personal.ini'
                                            ? 'Custom FanFicFare rules, metadata replacements, and site overrides'
                                            : 'Built-in FanFicFare defaults (read-only reference)'}
                                    </p>
                                </div>
                                {activeTab === 'personal.ini' && (
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {dirtyBySection['personal.ini'] && (
                                            <button
                                                type="button"
                                                className={showIniDiff ? '' : 'secondary'}
                                                onClick={() => setShowIniDiff((prev) => !prev)}
                                            >
                                                {showIniDiff ? 'Edit INI' : 'View Diff'}
                                            </button>
                                        )}
                                        {dirtyBySection['personal.ini'] && (
                                            <button
                                                type="button"
                                                className="secondary"
                                                onClick={() => {
                                                    setPersonalIni(initialPersonalIni)
                                                    setIniSaved(false)
                                                    setShowIniDiff(false)
                                                }}
                                            >
                                                <RotateCcw size={15} /> Discard
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={handleSavePersonalIni}
                                            disabled={saving || !dirtyBySection['personal.ini']}
                                        >
                                            <Save size={15} />{' '}
                                            {iniSaved
                                                ? 'Saved!'
                                                : dirtyBySection['personal.ini']
                                                  ? 'Save personal.ini'
                                                  : 'Saved'}
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* INI Section Jump Bar */}
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    flexWrap: 'wrap',
                                    marginBottom: '0.65rem',
                                }}
                            >
                                <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                                    Sections:
                                </span>
                                {extractIniSections(activeTab === 'personal.ini' ? personalIni : defaultsIni).map((sec) => (
                                    <button
                                        key={`${sec.name}-${sec.line}`}
                                        type="button"
                                        className="secondary btn-sm"
                                        onClick={() => {
                                            setShowIniDiff(false)
                                            const el = iniTextareaRef.current
                                            if (el) {
                                                const lines = el.value.split('\n')
                                                const charOffset = lines
                                                    .slice(0, sec.line - 1)
                                                    .reduce((acc, l) => acc + l.length + 1, 0)
                                                el.focus()
                                                el.setSelectionRange(charOffset, charOffset + sec.name.length + 2)
                                            }
                                        }}
                                        style={{
                                            padding: '0.14rem 0.45rem',
                                            minHeight: 22,
                                            fontSize: '0.72rem',
                                            fontFamily: 'var(--font-mono)',
                                        }}
                                        title={`Jump to [${sec.name}] (line ${sec.line})`}
                                    >
                                        [{sec.name}] :L{sec.line}
                                    </button>
                                ))}
                            </div>

                            {activeTab === 'personal.ini' && showIniDiff && dirtyBySection['personal.ini'] ? (
                                <div
                                    style={{
                                        background: '#05070c',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius-md)',
                                        padding: '0.75rem',
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '0.78rem',
                                        lineHeight: 1.55,
                                        maxHeight: 'calc(100vh - 260px)',
                                        overflowY: 'auto',
                                    }}
                                >
                                    {computeIniLineDiff(initialPersonalIni, personalIni).map((d, idx) => (
                                        <div
                                            key={idx}
                                            style={{
                                                padding: '0.1rem 0.45rem',
                                                background:
                                                    d.type === 'add'
                                                        ? 'rgba(16, 185, 129, 0.14)'
                                                        : d.type === 'remove'
                                                          ? 'rgba(239, 68, 68, 0.14)'
                                                          : 'transparent',
                                                color:
                                                    d.type === 'add'
                                                        ? '#6ee7b7'
                                                        : d.type === 'remove'
                                                          ? '#fca5a5'
                                                          : 'var(--text-muted)',
                                                whiteSpace: 'pre-wrap',
                                            }}
                                        >
                                            <span style={{ display: 'inline-block', width: 22, userSelect: 'none' }}>
                                                {d.type === 'add' ? '+' : d.type === 'remove' ? '-' : ' '}
                                            </span>
                                            {d.text}
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <textarea
                                    ref={iniTextareaRef}
                                    rows={34}
                                    readOnly={activeTab === 'defaults.ini'}
                                    value={activeTab === 'personal.ini' ? personalIni : defaultsIni}
                                    onChange={(e) => {
                                        if (activeTab === 'personal.ini') {
                                            setPersonalIni(e.target.value)
                                            setIniSaved(false)
                                        }
                                    }}
                                    style={{
                                        fontFamily: 'monospace',
                                        fontSize: '0.84rem',
                                        lineHeight: 1.65,
                                        minHeight: 'calc(100vh - 230px)',
                                        resize: 'vertical',
                                    }}
                                />
                            )}
                        </>
                    )}
                </div>
            </div>

            {/* Sticky Bottom Save Bar on Mobile when section has unsaved changes */}
            {!isIniTab && dirtySectionKeys.size > 0 && initialConfig && (
                <div className="mobile-sticky-savebar">
                    <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                        {dirtySectionKeys.size} unsaved change{dirtySectionKeys.size > 1 ? 's' : ''}
                    </span>
                    <div style={{ display: 'flex', gap: '0.4rem' }}>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => {
                                setConfig({
                                    ...config,
                                    [activeTab]: structuredClone(initialConfig[activeTab]),
                                })
                                setResult(null)
                            }}
                        >
                            Discard
                        </button>
                        <button type="button" className="btn-sm" onClick={handleSaveSection} disabled={saving}>
                            {saving ? 'Saving…' : 'Save'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}
