import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
    formatAttemptBlockAsText,
    diagnoseErrorSignature,
    type LogAttemptBlock,
} from '../utils/dashboardLogic'
import { getSiteBadgeInfo, statusBadgeClass } from '../statusColors'
import GitHubIssueModal from './GitHubIssueModal'
import { Copy, Check, ChevronDown, ChevronRight, AlertTriangle, Bug, Wrench, Settings } from 'lucide-react'

interface AttemptBlockCardProps {
    block: LogAttemptBlock
    defaultExpanded?: boolean
    forceExpanded?: boolean | null
    searchQuery?: string
    isHighlighted?: boolean
    domId?: string
    onFilterSite?: (site: string) => void
    onReportIssue?: (block: LogAttemptBlock) => void
}

const URL_SPLIT_RE = /(https?:\/\/[^\s<>"')]+?)(?=[.,;:]?(?:\s|$))/g

function highlightText(text: string, query?: string) {
    if (!query || !query.trim()) return text
    const escaped = query.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = new RegExp(`(${escaped})`, 'gi')
    const parts = text.split(re)
    if (parts.length === 1) return text
    return parts.map((part, idx) =>
        idx % 2 === 1 ? (
            <mark
                key={idx}
                style={{
                    background: 'rgba(250, 204, 21, 0.3)',
                    color: '#fef08a',
                    padding: '0 2px',
                    borderRadius: 3,
                }}
            >
                {part}
            </mark>
        ) : (
            <span key={idx}>{part}</span>
        )
    )
}

function renderMessageWithLinks(message: string, searchQuery?: string) {
    const parts = message.split(URL_SPLIT_RE)
    if (parts.length === 1) return highlightText(message, searchQuery)
    return parts.map((part, i) =>
        i % 2 === 1 ? (
            <a
                key={i}
                href={part}
                target="_blank"
                rel="noopener noreferrer"
                onClick={e => e.stopPropagation()}
                style={{
                    color: '#818cf8',
                    textDecoration: 'underline',
                    wordBreak: 'break-all',
                }}
            >
                {highlightText(part, searchQuery)}
            </a>
        ) : (
            <span key={i}>{highlightText(part, searchQuery)}</span>
        )
    )
}

const LEVEL_COLORS: Record<string, string> = {
    debug: '#64748b',
    info: '#38bdf8',
    warning: '#f59e0b',
    error: '#ef4444',
    critical: '#f87171',
}

function getActiveStageLabel(stage?: LogAttemptBlock['activeStage']): string {
    if (stage === 'downloading') return 'Active • Downloading'
    if (stage === 'queued') return 'Active • Queued'
    if (stage === 'waiting_retry') return 'Active • Waiting Retry'
    return 'Active • In Progress'
}

export default function AttemptBlockCard({
    block,
    defaultExpanded = true,
    forceExpanded = null,
    searchQuery,
    isHighlighted = false,
    domId,
    onFilterSite,
    onReportIssue,
}: AttemptBlockCardProps) {
    const navigate = useNavigate()
    const [expanded, setExpanded] = useState(defaultExpanded)
    const [copied, setCopied] = useState(false)
    const [showIssueModal, setShowIssueModal] = useState(false)

    useEffect(() => {
        if (forceExpanded !== null && forceExpanded !== undefined) {
            setExpanded(forceExpanded)
        }
    }, [forceExpanded])

    const siteInfo = block.site ? getSiteBadgeInfo(block.site) : null
    const errorContextText =
        block.traceback ||
        block.lines.find((l) => l.level.toLowerCase() === 'error' || l.level.toLowerCase() === 'critical')?.message ||
        null
    const diagnosticHint = block.status === 'failed' ? diagnoseErrorSignature(errorContextText) : null

    const borderColor = isHighlighted
        ? 'var(--accent)'
        : block.status === 'failed'
          ? 'rgba(239, 68, 68, 0.38)'
          : block.status === 'success'
            ? 'rgba(16, 185, 129, 0.28)'
            : block.status === 'processing'
              ? 'rgba(56, 189, 248, 0.35)'
              : 'var(--border)'

    const headerBg =
        block.status === 'failed'
            ? 'rgba(239, 68, 68, 0.08)'
            : block.status === 'success'
              ? 'rgba(16, 185, 129, 0.05)'
              : 'var(--surface2)'

    const handleCopy = (e: React.MouseEvent) => {
        e.stopPropagation()
        navigator.clipboard?.writeText(formatAttemptBlockAsText(block))
        setCopied(true)
        setTimeout(() => setCopied(false), 1800)
    }

    const handleReportIssue = (e: React.MouseEvent) => {
        e.stopPropagation()
        if (onReportIssue) {
            onReportIssue(block)
        } else {
            setShowIssueModal(true)
        }
    }

    const startShort = block.startedAt.includes(' ')
        ? block.startedAt.split(' ')[1]
        : block.startedAt
    const endShort = block.endedAt.includes(' ')
        ? block.endedAt.split(' ')[1]
        : block.endedAt

    return (
        <div
            id={domId}
            data-testid="attempt-block-card"
            data-block-url={block.url || ''}
            style={{
                borderRadius: 'var(--radius-md)',
                border: `${isHighlighted ? '2px' : '1px'} solid ${borderColor}`,
                boxShadow: isHighlighted ? '0 0 0 3px rgba(99, 102, 241, 0.22)' : undefined,
                background: 'var(--surface)',
                overflow: 'hidden',
                marginBottom: '0.75rem',
            }}
        >
            {/* Block Header */}
            <div
                onClick={() => setExpanded(prev => !prev)}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '0.6rem',
                    padding: '0.65rem 0.9rem',
                    background: headerBg,
                    borderBottom: expanded ? `1px solid ${borderColor}` : 'none',
                    cursor: 'pointer',
                    userSelect: 'none',
                }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        flexWrap: 'wrap',
                        minWidth: 0,
                        flex: '1 1 260px',
                    }}
                >
                    <span style={{ color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center' }}>
                        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                    </span>

                    {block.isActive && (
                        <span
                            style={{
                                padding: '0.15rem 0.5rem',
                                borderRadius: 6,
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.03em',
                                background: 'rgba(6, 182, 212, 0.16)',
                                color: '#22d3ee',
                                border: '1px solid rgba(6, 182, 212, 0.35)',
                            }}
                        >
                            {getActiveStageLabel(block.activeStage)}
                        </span>
                    )}

                    {siteInfo && (
                        <span
                            onClick={e => {
                                if (onFilterSite && block.site) {
                                    e.stopPropagation()
                                    onFilterSite(block.site)
                                }
                            }}
                            className="site-badge"
                            style={{
                                cursor: onFilterSite ? 'pointer' : 'default',
                                padding: '0.15rem 0.5rem',
                                borderRadius: 6,
                                background: siteInfo.bg,
                                border: `1px solid ${siteInfo.border}`,
                                fontSize: '0.74rem',
                            }}
                            title={onFilterSite ? `Filter by ${siteInfo.name}` : siteInfo.name}
                        >
                            <span className="site-dot" style={{ background: siteInfo.color }} />
                            <span>{siteInfo.name}</span>
                        </span>
                    )}

                    {block.kind === 'story_attempt' ? (
                        <span
                            className="tabular-nums"
                            style={{
                                padding: '0.15rem 0.5rem',
                                borderRadius: 6,
                                fontSize: '0.72rem',
                                fontFamily: 'var(--font-mono)',
                                fontWeight: 600,
                                background: 'var(--bg)',
                                color: 'var(--text)',
                                border: '1px solid var(--border)',
                            }}
                        >
                            {block.attemptNumber > 1
                                ? `Attempt #${block.attemptNumber} (Retry #${block.attemptNumber - 1})`
                                : 'Attempt #1'}
                        </span>
                    ) : (
                        <span
                            style={{
                                padding: '0.15rem 0.5rem',
                                borderRadius: 6,
                                fontSize: '0.72rem',
                                fontFamily: 'var(--font-mono)',
                                color: 'var(--text-muted)',
                                background: 'var(--bg)',
                                border: '1px solid var(--border)',
                            }}
                        >
                            System Event
                        </span>
                    )}

                    <span className={statusBadgeClass(block.status === 'system' ? 'queued' : block.status)}>
                        {block.status}
                    </span>

                    <div
                        style={{
                            minWidth: 0,
                            flex: 1,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                        }}
                    >
                        {block.url ? (
                            <a
                                href={block.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={e => e.stopPropagation()}
                                style={{
                                    fontWeight: 600,
                                    fontSize: '0.86rem',
                                    color: 'var(--text)',
                                }}
                                title={block.url}
                            >
                                {block.title}
                            </a>
                        ) : (
                            <span style={{ fontWeight: 600, fontSize: '0.86rem', color: 'var(--text)' }}>
                                {block.title}
                            </span>
                        )}
                    </div>
                </div>

                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.6rem',
                        flexShrink: 0,
                    }}
                >
                    <span
                        className="tabular-nums"
                        style={{
                            fontSize: '0.74rem',
                            fontFamily: 'var(--font-mono)',
                            color: 'var(--text-muted)',
                        }}
                        title={`Started ${block.startedAt} • Latest update ${block.endedAt}`}
                    >
                        {startShort === endShort ? `Updated ${endShort}` : `${startShort} → ${endShort}`}
                    </span>
                    <span
                        className="tabular-nums"
                        style={{
                            fontSize: '0.72rem',
                            fontFamily: 'var(--font-mono)',
                            color: 'var(--text-faint)',
                        }}
                    >
                        {block.lines.length} {block.lines.length === 1 ? 'step' : 'steps'}
                    </span>
                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={handleCopy}
                        style={{ padding: '0.2rem 0.55rem', minHeight: 26, fontSize: '0.73rem' }}
                        title="Copy complete attempt block and stack trace"
                    >
                        {copied ? <Check size={12} /> : <Copy size={12} />}
                        {copied ? 'Copied' : 'Copy Block'}
                    </button>
                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={handleReportIssue}
                        style={{ padding: '0.2rem 0.55rem', minHeight: 26, fontSize: '0.73rem' }}
                        title="Create a GitHub issue pre-filled with this attempt block's logs and stack trace"
                    >
                        <Bug size={12} /> Report Issue
                    </button>
                </div>
            </div>

            {/* Block Body */}
            {expanded && (
                <div>
                    {block.url && (
                        <div
                            style={{
                                padding: '0.35rem 0.9rem',
                                background: '#060911',
                                borderBottom: '1px solid var(--border-subtle)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '0.5rem',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '0.73rem',
                                color: 'var(--text-muted)',
                            }}
                        >
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {block.url}
                            </span>
                            <span className="tabular-nums" style={{ color: 'var(--text-faint)', flexShrink: 0 }}>
                                Latest update: {block.endedAt}
                            </span>
                        </div>
                    )}

                    {/* Chronological Step-by-Step Worker Log Lines */}
                    <div
                        style={{
                            padding: '0.5rem 0.75rem',
                            background: '#070a12',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.77rem',
                        }}
                    >
                        {block.lines.map((line, idx) => {
                            const lvl = line.level.toLowerCase()
                            const isErr = lvl === 'error' || lvl === 'critical'
                            return (
                                <div
                                    key={`${line.timestamp}-${idx}`}
                                    className={`log-entry-row ${isErr ? 'log-error' : ''}`}
                                >
                                    <div className="log-entry-meta">
                                        <span
                                            className="tabular-nums"
                                            style={{ color: '#64748b', fontSize: '0.72rem' }}
                                        >
                                            {line.timestamp}
                                        </span>
                                        <span
                                            style={{
                                                color: LEVEL_COLORS[lvl] || '#94a3b8',
                                                fontWeight: 700,
                                                fontSize: '0.72rem',
                                                minWidth: '4.6em',
                                            }}
                                        >
                                            [{line.level.toUpperCase()}]
                                        </span>
                                    </div>
                                    <div
                                        className="log-entry-msg"
                                        style={{ color: isErr ? '#fca5a5' : '#e2e8f0' }}
                                    >
                                        {renderMessageWithLinks(line.message, searchQuery)}
                                    </div>
                                </div>
                            )
                        })}
                    </div>

                    {/* Contextual Remediation Hint */}
                    {diagnosticHint && (
                        <div
                            data-testid="diagnostic-remediation-hint"
                            style={{
                                padding: '0.65rem 0.9rem',
                                background: 'rgba(245, 158, 11, 0.08)',
                                borderTop: '1px solid rgba(245, 158, 11, 0.25)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '0.75rem',
                                flexWrap: 'wrap',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.55rem', flex: '1 1 320px' }}>
                                <Wrench size={15} style={{ color: '#fbbf24', flexShrink: 0, marginTop: '0.12rem' }} />
                                <div>
                                    <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#fde68a' }}>
                                        Diagnostic Hint: {diagnosticHint.summary}
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: '#fef3c7', marginTop: '0.1rem', lineHeight: 1.4 }}>
                                        {diagnosticHint.hint}
                                    </div>
                                </div>
                            </div>
                            {diagnosticHint.configTab && (
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        navigate(`/config?tab=${encodeURIComponent(diagnosticHint.configTab!)}`)
                                    }}
                                    style={{
                                        padding: '0.2rem 0.6rem',
                                        minHeight: 26,
                                        fontSize: '0.73rem',
                                        borderColor: 'rgba(245, 158, 11, 0.4)',
                                        color: '#fde68a',
                                    }}
                                >
                                    <Settings size={12} /> {diagnosticHint.configLabel || 'Open Config'}
                                </button>
                            )}
                        </div>
                    )}

                    {/* Stack Trace / Diagnostic Exception Section */}
                    {block.traceback && (
                        <div
                            style={{
                                padding: '0.75rem 0.9rem',
                                background: 'rgba(239, 68, 68, 0.06)',
                                borderTop: '1px solid rgba(239, 68, 68, 0.25)',
                            }}
                        >
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    marginBottom: '0.45rem',
                                    gap: '0.5rem',
                                    flexWrap: 'wrap',
                                }}
                            >
                                <span
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.35rem',
                                        fontSize: '0.72rem',
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                        color: '#fca5a5',
                                        fontFamily: 'var(--font-mono)',
                                    }}
                                >
                                    <AlertTriangle size={13} /> Exception / Stack Trace Output
                                </span>
                                <span
                                    style={{
                                        fontSize: '0.71rem',
                                        color: 'var(--text-muted)',
                                        fontFamily: 'var(--font-mono)',
                                    }}
                                >
                                    Captured from worker stderr
                                </span>
                            </div>
                            <pre
                                style={{
                                    padding: '0.75rem 0.85rem',
                                    margin: 0,
                                    borderRadius: 'var(--radius-sm)',
                                    background: '#05070c',
                                    border: '1px solid rgba(239, 68, 68, 0.3)',
                                    color: '#fecaca',
                                    fontSize: '0.76rem',
                                    fontFamily: 'var(--font-mono)',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                    lineHeight: 1.55,
                                    overflowX: 'auto',
                                }}
                            >
                                {block.traceback}
                            </pre>
                        </div>
                    )}
                </div>
            )}

            {showIssueModal && (
                <GitHubIssueModal block={block} onClose={() => setShowIssueModal(false)} />
            )}
        </div>
    )
}
