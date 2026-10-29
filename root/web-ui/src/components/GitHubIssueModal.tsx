import { useState, useEffect, useMemo } from 'react'
import {
    buildGitHubIssueDraft,
    buildGitHubIssueUrl,
    scrubPiiFromLogText,
    type LogAttemptBlock,
} from '../utils/dashboardLogic'
import { getStartupLogs, getSystemVersion, type LogEntry, type SystemVersionInfo } from '../api'
import {
    AlertTriangle,
    ShieldAlert,
    ShieldCheck,
    Copy,
    Check,
    ExternalLink,
    X,
    Bug,
    RotateCcw,
} from 'lucide-react'

const STORAGE_REPO_KEY = 'ff_github_issue_repo_v1'
const DEFAULT_REPO = 'AutomatedFanfic/AutomatedFanfic'

export interface GitHubIssueModalProps {
    block?: LogAttemptBlock | null
    rawLogsText?: string
    mode?: 'runtime' | 'startup'
    onClose: () => void
}

export default function GitHubIssueModal({
    block,
    rawLogsText,
    mode = 'runtime',
    onClose,
}: GitHubIssueModalProps) {
    const [repo, setRepo] = useState<string>(() => {
        try {
            return localStorage.getItem(STORAGE_REPO_KEY) || DEFAULT_REPO
        } catch {
            return DEFAULT_REPO
        }
    })
    const [autoScrub, setAutoScrub] = useState<boolean>(true)
    const [redactStoryUrls, setRedactStoryUrls] = useState<boolean>(false)
    const [startupLogs, setStartupLogs] = useState<LogEntry[]>([])
    const [systemVersions, setSystemVersions] = useState<SystemVersionInfo | null>(null)

    useEffect(() => {
        getStartupLogs(100)
            .then((res) => setStartupLogs(res.items || []))
            .catch(() => {})
        getSystemVersion()
            .then((v) => setSystemVersions(v))
            .catch(() => {})
    }, [])

    const initialDraft = useMemo(
        () =>
            buildGitHubIssueDraft({
                block,
                rawLogsText,
                startupLogs,
                systemVersions,
                mode,
                scrubPii: autoScrub,
                redactStoryUrls,
            }),
        [block, rawLogsText, startupLogs, systemVersions, mode, autoScrub, redactStoryUrls]
    )

    const [title, setTitle] = useState(initialDraft.title)
    const [body, setBody] = useState(initialDraft.body)
    const [copied, setCopied] = useState(false)
    const [scrubNotice, setScrubNotice] = useState<string | null>(null)

    useEffect(() => {
        setTitle(initialDraft.title)
        setBody(initialDraft.body)
    }, [initialDraft])

    const handleRepoChange = (val: string) => {
        setRepo(val)
        try {
            localStorage.setItem(STORAGE_REPO_KEY, val)
        } catch {
            // ignore storage errors
        }
    }

    const handleManualScrub = () => {
        const scrubOpts = { redactStoryUrls, storyTitle: block?.title }
        const titleScrubbed = scrubPiiFromLogText(title, scrubOpts)
        const bodyScrubbed = scrubPiiFromLogText(body, scrubOpts)
        const total = titleScrubbed.redactionCount + bodyScrubbed.redactionCount
        setTitle(titleScrubbed.text)
        setBody(bodyScrubbed.text)
        setScrubNotice(
            total > 0
                ? `Redacted ${total} sensitive item${total === 1 ? '' : 's'} (${Array.from(
                      new Set([...titleScrubbed.detectedTypes, ...bodyScrubbed.detectedTypes])
                  ).join(', ')})`
                : 'No additional emails, tokens, cookies, IPs, or local user paths detected'
        )
        setTimeout(() => setScrubNotice(null), 4000)
    }

    const handleResetTemplate = () => {
        setTitle(initialDraft.title)
        setBody(initialDraft.body)
    }

    const handleCopyMarkdown = () => {
        const fullText = `# ${title}\n\n${body}`
        navigator.clipboard?.writeText(fullText)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }

    const { url: githubIssueUrl, isTruncated } = useMemo(
        () =>
            buildGitHubIssueUrl({
                repo,
                title,
                body,
                labels: ['bug'],
            }),
        [repo, title, body]
    )

    // Live check if any unredacted PII still exists in current edited text
    const remainingPiiCheck = useMemo(() => {
        const t = scrubPiiFromLogText(title)
        const b = scrubPiiFromLogText(body)
        return {
            count: t.redactionCount + b.redactionCount,
            types: Array.from(new Set([...t.detectedTypes, ...b.detectedTypes])),
        }
    }, [title, body])

    return (
        <div
            className="modal-overlay"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
            aria-label="Create GitHub Issue from Logs"
        >
            <div
                className="modal-card"
                onClick={(e) => e.stopPropagation()}
                style={{ maxWidth: 820, width: '100%' }}
            >
                <div className="modal-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
                        <span
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                width: 32,
                                height: 32,
                                borderRadius: 8,
                                background: 'rgba(99, 102, 241, 0.14)',
                                color: '#818cf8',
                                border: '1px solid rgba(99, 102, 241, 0.3)',
                            }}
                        >
                            <Bug size={17} />
                        </span>
                        <div>
                            <h3 style={{ fontSize: '1.02rem', fontWeight: 700, margin: 0 }}>
                                Create GitHub Issue with Logs
                            </h3>
                            <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                                {block
                                    ? `Pre-filled from Attempt #${block.attemptNumber} (${block.site || 'system'} • ${block.title})`
                                    : `Pre-filled from ${mode} log buffer`}
                            </div>
                        </div>
                    </div>
                    <button
                        type="button"
                        className="secondary btn-sm"
                        onClick={onClose}
                        aria-label="Close GitHub Issue modal"
                    >
                        <X size={15} /> Close
                    </button>
                </div>

                <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
                    {/* Prominent PII & Privacy Warning Banner */}
                    <div
                        data-testid="pii-warning-banner"
                        style={{
                            padding: '0.8rem 0.95rem',
                            borderRadius: 'var(--radius-md)',
                            background: 'rgba(245, 158, 11, 0.1)',
                            border: '1px solid rgba(245, 158, 11, 0.38)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.55rem',
                        }}
                    >
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'flex-start',
                                justifyContent: 'space-between',
                                gap: '0.75rem',
                                flexWrap: 'wrap',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.55rem', flex: '1 1 380px' }}>
                                <ShieldAlert
                                    size={18}
                                    style={{ color: '#fbbf24', flexShrink: 0, marginTop: '0.1rem' }}
                                />
                                <div>
                                    <div
                                        style={{
                                            fontSize: '0.83rem',
                                            fontWeight: 700,
                                            color: '#fde68a',
                                            marginBottom: '0.2rem',
                                        }}
                                    >
                                        Review & Clean Up Any PII Before Submitting Publicly
                                    </div>
                                    <div style={{ fontSize: '0.77rem', color: '#fef3c7', lineHeight: 1.45 }}>
                                        Logs and stack traces can contain personal email addresses, IMAP usernames,
                                        session cookies (<code>cf_clearance</code>), API tokens (Pushbullet / Apprise),
                                        local filesystem paths, or private story URLs. Verify the markdown body below
                                        before posting to GitHub.
                                    </div>
                                </div>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexShrink: 0 }}>
                                <button
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={handleManualScrub}
                                    style={{
                                        borderColor: 'rgba(245, 158, 11, 0.45)',
                                        color: '#fde68a',
                                        background: 'rgba(245, 158, 11, 0.14)',
                                    }}
                                    title="Scan and redact emails, tokens, cookies, IPs, and user home paths in the issue draft"
                                >
                                    <ShieldCheck size={14} /> Scrub PII Now
                                </button>
                            </div>
                        </div>

                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                flexWrap: 'wrap',
                                gap: '0.5rem',
                                paddingTop: '0.45rem',
                                borderTop: '1px solid rgba(245, 158, 11, 0.22)',
                                fontSize: '0.75rem',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                                <label
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                        cursor: 'pointer',
                                        color: '#fde68a',
                                        fontWeight: 500,
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={autoScrub}
                                        onChange={(e) => setAutoScrub(e.target.checked)}
                                        style={{ width: 'auto', margin: 0, flexShrink: 0 }}
                                    />
                                    <span>Auto-redact common PII patterns (emails, tokens, cookies, local user paths, IPs)</span>
                                </label>

                                <label
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                        cursor: 'pointer',
                                        color: '#fde68a',
                                        fontWeight: 500,
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={redactStoryUrls}
                                        onChange={(e) => setRedactStoryUrls(e.target.checked)}
                                        style={{ width: 'auto', margin: 0, flexShrink: 0 }}
                                    />
                                    <span>Also redact story URLs & title</span>
                                </label>
                            </div>

                            <span style={{ color: '#fcd34d', fontFamily: 'var(--font-mono)', fontSize: '0.73rem' }}>
                                {scrubNotice
                                    ? scrubNotice
                                    : remainingPiiCheck.count > 0
                                      ? `⚠️ ${remainingPiiCheck.count} potential PII item(s) detected (${remainingPiiCheck.types.join(', ')})`
                                      : initialDraft.detectedPiiCount > 0 && autoScrub
                                        ? `✓ Auto-redacted ${initialDraft.detectedPiiCount} item(s)`
                                        : '✓ No obvious tokens or emails detected'}
                            </span>
                        </div>
                    </div>

                    {/* Component Versions Badge Bar */}
                    {systemVersions && (
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.45rem',
                                flexWrap: 'wrap',
                                padding: '0.4rem 0.65rem',
                                background: 'rgba(255, 255, 255, 0.03)',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--border)',
                                fontSize: '0.74rem',
                            }}
                        >
                            <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>Detected Versions:</span>
                            <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                AF v{systemVersions.automatedfanfic}
                            </span>
                            <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(16, 185, 129, 0.15)', color: '#6ee7b7', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                Python {systemVersions.python}
                            </span>
                            <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(6, 182, 212, 0.15)', color: '#67e8f9', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                FFF {systemVersions.fanficfare}
                            </span>
                            <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(245, 158, 11, 0.15)', color: '#fcd34d', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                Calibre {systemVersions.calibre}
                            </span>
                            {systemVersions.apprise && systemVersions.apprise !== 'unknown' && (
                                <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(168, 85, 247, 0.15)', color: '#d8b4fe', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                    Apprise {systemVersions.apprise}
                                </span>
                            )}
                            {systemVersions.is_docker && (
                                <span style={{ fontFamily: 'var(--font-mono)', background: 'rgba(59, 130, 246, 0.15)', color: '#93c5fd', padding: '0.1rem 0.4rem', borderRadius: 4 }}>
                                    Docker
                                </span>
                            )}
                        </div>
                    )}

                    {/* Repository & Issue Title Inputs */}
                    <div
                        style={{
                            display: 'grid',
                            gridTemplateColumns: 'minmax(200px, 1fr) minmax(280px, 2fr)',
                            gap: '0.75rem',
                        }}
                    >
                        <div>
                            <label
                                htmlFor="gh-issue-repo"
                                style={{
                                    display: 'block',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    color: 'var(--text-muted)',
                                    marginBottom: '0.3rem',
                                }}
                            >
                                Target GitHub Repository
                            </label>
                            <input
                                id="gh-issue-repo"
                                type="text"
                                value={repo}
                                onChange={(e) => handleRepoChange(e.target.value)}
                                placeholder="owner/repo"
                                style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}
                            />
                        </div>

                        <div>
                            <label
                                htmlFor="gh-issue-title"
                                style={{
                                    display: 'block',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    color: 'var(--text-muted)',
                                    marginBottom: '0.3rem',
                                }}
                            >
                                Issue Title
                            </label>
                            <input
                                id="gh-issue-title"
                                type="text"
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                placeholder="[Bug] Brief summary of the issue"
                                style={{ fontSize: '0.82rem' }}
                            />
                        </div>
                    </div>

                    {/* Editable Issue Markdown Body */}
                    <div>
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                marginBottom: '0.35rem',
                                gap: '0.5rem',
                            }}
                        >
                            <label
                                htmlFor="gh-issue-body"
                                style={{
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                Issue Body Markdown (Editable — logs copied in below)
                            </label>
                            <button
                                type="button"
                                className="secondary btn-sm"
                                onClick={handleResetTemplate}
                                style={{ padding: '0.15rem 0.5rem', minHeight: 24, fontSize: '0.72rem' }}
                                title="Reset issue title and markdown body to generated template"
                            >
                                <RotateCcw size={11} /> Reset Draft
                            </button>
                        </div>
                        <textarea
                            id="gh-issue-body"
                            value={body}
                            onChange={(e) => setBody(e.target.value)}
                            rows={13}
                            style={{
                                width: '100%',
                                fontFamily: 'var(--font-mono)',
                                fontSize: '0.76rem',
                                lineHeight: 1.5,
                                background: '#05070c',
                                color: '#e2e8f0',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius-md)',
                                padding: '0.75rem',
                                resize: 'vertical',
                            }}
                        />
                    </div>

                    {isTruncated && (
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                fontSize: '0.76rem',
                                color: '#fbbf24',
                                background: 'rgba(245, 158, 11, 0.08)',
                                border: '1px solid rgba(245, 158, 11, 0.25)',
                                padding: '0.5rem 0.75rem',
                                borderRadius: 'var(--radius-sm)',
                            }}
                        >
                            <AlertTriangle size={14} style={{ flexShrink: 0 }} />
                            <span>
                                This log snippet is long ({body.length.toLocaleString()} chars). GitHub URL parameters
                                are capped to prevent browser URL errors, so click <strong>Copy Issue Markdown</strong>{' '}
                                as well if you want to paste the full untruncated log on GitHub.
                            </span>
                        </div>
                    )}

                    {/* Modal Footer Actions */}
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '0.6rem',
                            flexWrap: 'wrap',
                            paddingTop: '0.35rem',
                            borderTop: '1px solid var(--border)',
                        }}
                    >
                        <button type="button" className="secondary btn-sm" onClick={handleCopyMarkdown}>
                            {copied ? <Check size={14} /> : <Copy size={14} />}
                            {copied ? 'Copied Issue Markdown' : 'Copy Issue Markdown'}
                        </button>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
                            <button type="button" className="secondary btn-sm" onClick={onClose}>
                                Cancel
                            </button>
                            <a
                                href={githubIssueUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                data-testid="open-github-issue-link"
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.45rem',
                                    padding: '0.45rem 0.9rem',
                                    borderRadius: 'var(--radius-sm)',
                                    background: 'var(--accent)',
                                    color: '#fff',
                                    fontWeight: 600,
                                    fontSize: '0.81rem',
                                    textDecoration: 'none',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                }}
                            >
                                <Bug size={14} />
                                <span>Open New GitHub Issue</span>
                                <ExternalLink size={13} />
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
