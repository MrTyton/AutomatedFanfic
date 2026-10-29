import React, { useState, useMemo, useRef, useEffect } from 'react'
import {
    parseIniDocument,
    serializeIniDocument,
    updateSectionField,
    removeSectionField,
    getSectionFlareSolverr,
    getAllFlareSolverrSites,
    setSiteFlareSolverrConfig,
    addIniSection,
    removeIniSection,
    updateSectionContent,
    categorizeIniSection,
    extractReferenceSections,
    extractReferenceKeyComments,
    extractReferenceKeyDefinitions,
    getSettingSuggestions,
    type ReferenceKeyDefinition,
} from '../utils/iniManager.ts'
import { computeIniLineDiff } from '../utils/dashboardLogic.ts'
import {
    Zap,
    Plus,
    Trash2,
    Code,
    Sliders,
    Search,
    RotateCcw,
    Eye,
    EyeOff,
    Check,
    X,
    ChevronDown,
    ChevronRight,
} from 'lucide-react'

interface IniEditorProps {
    iniText: string
    onChange: (newIni: string) => void
    initialIniText?: string
    referenceIni?: string
    readOnly?: boolean
    onDiscard?: () => void
    onSave?: () => void
    saving?: boolean
    saved?: boolean
    isDirty?: boolean
}

export const IniEditor: React.FC<IniEditorProps> = ({
    iniText,
    onChange,
    initialIniText = '',
    referenceIni = '',
    readOnly = false,
    onDiscard,
    onSave,
    saving = false,
    saved = false,
    isDirty = false,
}) => {
    const [viewMode, setViewMode] = useState<'bubbles' | 'raw' | 'diff'>('bubbles')
    const [searchQuery, setSearchQuery] = useState('')
    const [sectionCodeModes, setSectionCodeModes] = useState<Record<string, boolean>>({})
    const [revealedSecrets, setRevealedSecrets] = useState<Record<string, boolean>>({})
    const [expandedDirectives, setExpandedDirectives] = useState<Record<string, boolean>>({})
    const [showAddSectionModal, setShowAddSectionModal] = useState(false)
    const [newSectionCustomName, setNewSectionCustomName] = useState('')
    const [activeAddSettingSection, setActiveAddSettingSection] = useState<string | null>(null)
    const [newSettingKey, setNewSettingKey] = useState('')
    const [newSettingValue, setNewSettingValue] = useState('')
    const [showKeyDropdown, setShowKeyDropdown] = useState(false)
    const [selectedSuggestionIndex, setSelectedSuggestionIndex] = useState(-1)
    const [showFlareModal, setShowFlareModal] = useState(false)
    const [targetFlareSection, setTargetFlareSection] = useState<string>('')
    const [customFlareAddress, setCustomFlareAddress] = useState('http://localhost:8191/v1')

    const rawTextareaRef = useRef<HTMLTextAreaElement>(null)
    const keyInputRef = useRef<HTMLInputElement>(null)
    const valueInputRef = useRef<HTMLInputElement>(null)
    const dropdownRef = useRef<HTMLDivElement>(null)

    // Parse INI structure
    const parsedDoc = useMemo(() => parseIniDocument(iniText), [iniText])
    const allFlareSites = useMemo(() => getAllFlareSolverrSites(iniText), [iniText])
    const activeFlareSites = useMemo(() => allFlareSites.filter((s) => s.isEnabled), [allFlareSites])

    // Algorithmically extract available sections and key comments from referenceIni (e.g. defaults.ini)
    const discoveredSections = useMemo(() => {
        if (!referenceIni) return []
        const allRef = extractReferenceSections(referenceIni)
        const currentNames = new Set(parsedDoc.sections.map((s) => s.name.toLowerCase()))
        return allRef.filter((name) => !currentNames.has(name.toLowerCase()))
    }, [referenceIni, parsedDoc.sections])

    const filteredDiscoveredSections = useMemo(() => {
        if (!newSectionCustomName.trim()) {
            return discoveredSections.slice(0, 10)
        }
        const q = newSectionCustomName.toLowerCase().replace(/[\[\]]/g, '').trim()
        return discoveredSections.filter((name) => name.toLowerCase().includes(q)).slice(0, 12)
    }, [discoveredSections, newSectionCustomName])

    const referenceKeyComments = useMemo(
        () => extractReferenceKeyComments(referenceIni || ''),
        [referenceIni]
    )

    const referenceKeyDefinitions = useMemo(
        () => extractReferenceKeyDefinitions(referenceIni || ''),
        [referenceIni]
    )

    const existingKeysForActiveSec = useMemo(() => {
        if (!activeAddSettingSection) return new Set<string>()
        const target = parsedDoc.sections.find((s) => s.name === activeAddSettingSection)
        if (!target) return new Set<string>()
        return new Set(target.fields.map((f) => f.key.toLowerCase()))
    }, [parsedDoc.sections, activeAddSettingSection])

    const keySuggestions = useMemo(() => {
        if (!activeAddSettingSection) return []
        return getSettingSuggestions(
            referenceKeyDefinitions,
            activeAddSettingSection,
            existingKeysForActiveSec,
            newSettingKey,
            25
        )
    }, [referenceKeyDefinitions, activeAddSettingSection, existingKeysForActiveSec, newSettingKey])

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(e.target as Node) &&
                keyInputRef.current &&
                !keyInputRef.current.contains(e.target as Node)
            ) {
                setShowKeyDropdown(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const handleSelectSuggestion = (suggestion: ReferenceKeyDefinition) => {
        setNewSettingKey(suggestion.key)
        if (suggestion.defaultValue && !newSettingValue) {
            setNewSettingValue(suggestion.defaultValue)
        }
        setShowKeyDropdown(false)
        setSelectedSuggestionIndex(-1)
        setTimeout(() => {
            valueInputRef.current?.focus()
        }, 50)
    }

    // Filter sections based on search query
    const filteredSections = useMemo(() => {
        if (!searchQuery.trim()) return parsedDoc.sections
        const q = searchQuery.toLowerCase()
        return parsedDoc.sections.filter((sec) => {
            if (sec.name.toLowerCase().includes(q)) return true
            return sec.lines.some((l) => l.toLowerCase().includes(q))
        })
    }, [parsedDoc.sections, searchQuery])

    // Per-site FlareSolverr handlers
    const handleToggleSiteFlare = (secName: string, enable: boolean) => {
        if (readOnly) return
        const updated = setSiteFlareSolverrConfig(
            iniText,
            secName,
            enable,
            customFlareAddress || 'http://localhost:8191/v1'
        )
        onChange(updated)
    }

    const handleSaveFlareSolverrAddress = () => {
        if (readOnly || !targetFlareSection) return
        const updated = setSiteFlareSolverrConfig(
            iniText,
            targetFlareSection,
            true,
            customFlareAddress || 'http://localhost:8191/v1'
        )
        onChange(updated)
        setShowFlareModal(false)
    }

    const handleRemoveFlareSolverrCompletely = () => {
        if (readOnly || !targetFlareSection) return
        const updated = setSiteFlareSolverrConfig(
            iniText,
            targetFlareSection,
            false,
            undefined,
            true
        )
        onChange(updated)
        setShowFlareModal(false)
    }

    // Toggle section view mode (form vs scoped code)
    const toggleSectionCodeMode = (secName: string) => {
        setSectionCodeModes((prev) => ({
            ...prev,
            [secName]: !prev[secName],
        }))
    }

    // Handle single field change in a section
    const handleFieldChange = (secName: string, key: string, newValue: string) => {
        if (readOnly) return
        const targetSec = parsedDoc.sections.find((s) => s.name.toLowerCase() === secName.toLowerCase())
        if (!targetSec) return

        const updatedLines = updateSectionField(targetSec.lines, key, newValue)
        const updatedDoc = {
            ...parsedDoc,
            sections: parsedDoc.sections.map((s) =>
                s.name.toLowerCase() === secName.toLowerCase() ? { ...s, lines: updatedLines } : s
            ),
        }
        onChange(serializeIniDocument(updatedDoc))
    }

    // Handle field removal
    const handleRemoveField = (secName: string, key: string) => {
        if (readOnly) return
        const targetSec = parsedDoc.sections.find((s) => s.name.toLowerCase() === secName.toLowerCase())
        if (!targetSec) return

        const updatedLines = removeSectionField(targetSec.lines, key)
        const updatedDoc = {
            ...parsedDoc,
            sections: parsedDoc.sections.map((s) =>
                s.name.toLowerCase() === secName.toLowerCase() ? { ...s, lines: updatedLines } : s
            ),
        }
        onChange(serializeIniDocument(updatedDoc))
    }

    // Add new setting to section
    const handleAddNewSetting = (secName: string) => {
        if (readOnly || !newSettingKey.trim()) return
        handleFieldChange(secName, newSettingKey.trim(), newSettingValue.trim())
        setNewSettingKey('')
        setNewSettingValue('')
        setShowKeyDropdown(false)
        setSelectedSuggestionIndex(-1)
        setActiveAddSettingSection(null)
    }

    // Handle raw section code edit
    const handleSectionContentChange = (secName: string, newContent: string) => {
        if (readOnly) return
        const updated = updateSectionContent(iniText, secName, newContent)
        onChange(updated)
    }

    // Delete section
    const handleDeleteSection = (secName: string) => {
        if (readOnly) return
        if (window.confirm(`Are you sure you want to delete section [${secName}]?`)) {
            const updated = removeIniSection(iniText, secName)
            onChange(updated)
        }
    }

    // Add new section
    const handleAddSection = (name: string) => {
        if (readOnly) return
        const cleanName = name.replace(/[\[\]]/g, '').trim()
        if (!cleanName) return

        const updated = addIniSection(iniText, cleanName)
        onChange(updated)
        setShowAddSectionModal(false)
        setNewSectionCustomName('')

        // Scroll to new section
        setTimeout(() => {
            const id = `ini-sec-${cleanName.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`
            document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
        }, 100)
    }

    // Secret toggles
    const toggleSecret = (fieldId: string) => {
        setRevealedSecrets((prev) => ({ ...prev, [fieldId]: !prev[fieldId] }))
    }

    return (
        <div className="ini-section-pane" style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
            {/* Top Toolbar */}
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    paddingBottom: '0.75rem',
                    borderBottom: '1px solid var(--border)',
                }}
            >
                {/* Left: Per-Site FlareSolverr Overview */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                    <span
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            fontSize: '0.76rem',
                            color: 'var(--text-muted)',
                            fontWeight: 600,
                        }}
                    >
                        <Zap size={13} style={{ color: '#f59e0b' }} />
                        <span>Per-Site FlareSolverr:</span>
                    </span>

                    {activeFlareSites.length > 0 ? (
                        activeFlareSites.map((site) => (
                            <button
                                key={site.section}
                                type="button"
                                className="secondary btn-sm"
                                onClick={() => {
                                    const id = `ini-sec-${site.section.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`
                                    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
                                }}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.3rem',
                                    padding: '0.12rem 0.45rem',
                                    minHeight: 22,
                                    fontSize: '0.72rem',
                                    borderRadius: 6,
                                    background: 'rgba(16, 185, 129, 0.12)',
                                    borderColor: 'rgba(16, 185, 129, 0.35)',
                                    color: '#10b981',
                                    fontFamily: 'var(--font-mono)',
                                }}
                                title={`Jump to [${site.section}] (${site.address})`}
                            >
                                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} />
                                <span>[{site.section}]</span>
                            </button>
                        ))
                    ) : (
                        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                            (Not enabled on any site yet — click "+ FlareSolverr" on any site card below)
                        </span>
                    )}
                </div>

                {/* Right: View Mode Toggle & Save/Discard Controls */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {/* View Mode Segmented Controls */}
                    <div
                        style={{
                            display: 'inline-flex',
                            background: 'var(--surface2)',
                            borderRadius: 'var(--radius-md)',
                            padding: '2px',
                            border: '1px solid var(--border)',
                        }}
                    >
                        <button
                            type="button"
                            className={`segmented-btn ${viewMode === 'bubbles' ? 'active' : ''}`}
                            onClick={() => setViewMode('bubbles')}
                            style={{ minHeight: 28, fontSize: '0.75rem', padding: '0.2rem 0.65rem' }}
                        >
                            <Sliders size={13} /> Section Cards
                        </button>
                        <button
                            type="button"
                            className={`segmented-btn ${viewMode === 'raw' ? 'active' : ''}`}
                            onClick={() => setViewMode('raw')}
                            style={{ minHeight: 28, fontSize: '0.75rem', padding: '0.2rem 0.65rem' }}
                        >
                            <Code size={13} /> Raw Editor
                        </button>
                        {isDirty && (
                            <button
                                type="button"
                                className={`segmented-btn ${viewMode === 'diff' ? 'active' : ''}`}
                                onClick={() => setViewMode('diff')}
                                style={{ minHeight: 28, fontSize: '0.75rem', padding: '0.2rem 0.65rem' }}
                            >
                                Diff
                            </button>
                        )}
                    </div>

                    {/* Discard & Save */}
                    {!readOnly && isDirty && onDiscard && (
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={onDiscard}
                            title="Revert all unsaved INI changes"
                        >
                            <RotateCcw size={14} /> Discard
                        </button>
                    )}
                    {!readOnly && onSave && (
                        <button
                            type="button"
                            className="btn-sm"
                            onClick={onSave}
                            disabled={saving || !isDirty}
                        >
                            <Check size={14} />
                            {saving ? 'Saving…' : saved ? 'Saved!' : isDirty ? 'Save personal.ini' : 'Saved'}
                        </button>
                    )}
                </div>
            </div>

            {/* FlareSolverr Modal / Popover */}
            {showFlareModal && (
                <div
                    className="card"
                    style={{
                        background: 'var(--surface2)',
                        borderColor: 'rgba(99, 102, 241, 0.4)',
                        padding: '0.85rem',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.6rem',
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <Zap size={15} style={{ color: '#f59e0b' }} /> FlareSolverr Proxy for [{targetFlareSection}]
                        </span>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => setShowFlareModal(false)}
                            style={{ minHeight: 20, padding: '0.1rem 0.35rem' }}
                        >
                            <X size={13} />
                        </button>
                    </div>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        FanFicFare routes requests for stories from <code>[{targetFlareSection}]</code> through this FlareSolverr v1 endpoint to solve Cloudflare anti-bot captchas automatically.
                    </p>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <label htmlFor="flaresolverr-url" style={{ fontSize: '0.78rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                            Endpoint URL:
                        </label>
                        <input
                            id="flaresolverr-url"
                            type="text"
                            value={customFlareAddress}
                            onChange={(e) => setCustomFlareAddress(e.target.value)}
                            placeholder="http://localhost:8191/v1"
                            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem', flex: 1 }}
                        />
                        <button
                            type="button"
                            className="btn-sm"
                            onClick={handleSaveFlareSolverrAddress}
                        >
                            Save for [{targetFlareSection}]
                        </button>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={handleRemoveFlareSolverrCompletely}
                            style={{ color: 'var(--error)' }}
                            title={`Delete FlareSolverr directives from [${targetFlareSection}]`}
                        >
                            Remove
                        </button>
                    </div>
                </div>
            )}

            {/* Section Quick Jump Bar & Filter (only shown in Bubbles view) */}
            {viewMode === 'bubbles' && (
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '0.6rem',
                        flexWrap: 'wrap',
                    }}
                >
                    {/* Section pills for fast scrolling */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap', flex: 1, minWidth: 200 }}>
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                            Sections:
                        </span>
                        {parsedDoc.sections.map((sec) => (
                            <button
                                key={sec.name}
                                type="button"
                                className="secondary btn-sm"
                                onClick={() => {
                                    const id = `ini-sec-${sec.name.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`
                                    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
                                }}
                                style={{
                                    padding: '0.12rem 0.45rem',
                                    minHeight: 22,
                                    fontSize: '0.72rem',
                                    fontFamily: 'var(--font-mono)',
                                }}
                                title={`Jump to [${sec.name}]`}
                            >
                                [{sec.name}]
                            </button>
                        ))}
                    </div>

                    {/* Search and Add Section */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <div style={{ position: 'relative', width: 170 }}>
                            <Search
                                size={13}
                                style={{
                                    position: 'absolute',
                                    left: 8,
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    color: 'var(--text-muted)',
                                    pointerEvents: 'none',
                                }}
                            />
                            <input
                                type="text"
                                placeholder="Filter sections..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                style={{
                                    paddingLeft: '1.7rem',
                                    fontSize: '0.78rem',
                                    minHeight: 28,
                                    paddingTop: '0.2rem',
                                    paddingBottom: '0.2rem',
                                }}
                            />
                        </div>

                        {!readOnly && (
                            <button
                                type="button"
                                className="btn-sm"
                                onClick={() => setShowAddSectionModal((prev) => !prev)}
                                style={{ minHeight: 28, fontSize: '0.78rem' }}
                                title="Add a new section to personal.ini"
                            >
                                <Plus size={13} /> Add Section
                            </button>
                        )}
                    </div>
                </div>
            )}

            {/* Add Section Modal */}
            {showAddSectionModal && !readOnly && (
                <div
                    className="card"
                    style={{
                        background: 'var(--surface2)',
                        padding: '0.85rem',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.65rem',
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>Add INI Section</span>
                        <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() => setShowAddSectionModal(false)}
                            style={{ minHeight: 20, padding: '0.1rem 0.35rem' }}
                        >
                            <X size={13} />
                        </button>
                    </div>

                    <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                        <input
                            type="text"
                            placeholder="Section name, e.g. [defaults] or [domain.tld]"
                            value={newSectionCustomName}
                            onChange={(e) => setNewSectionCustomName(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    handleAddSection(newSectionCustomName)
                                }
                            }}
                            style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', flex: 1 }}
                        />
                        <button
                            type="button"
                            className="btn-sm"
                            onClick={() => handleAddSection(newSectionCustomName)}
                            disabled={!newSectionCustomName.trim()}
                        >
                            Create
                        </button>
                    </div>

                    {filteredDiscoveredSections.length > 0 && (
                        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Discovered in defaults.ini:</span>
                            {filteredDiscoveredSections.map((secName) => (
                                <button
                                    key={secName}
                                    type="button"
                                    className="secondary btn-sm"
                                    onClick={() => handleAddSection(secName)}
                                    style={{ fontSize: '0.72rem', padding: '0.12rem 0.45rem', fontFamily: 'var(--font-mono)' }}
                                >
                                    + [{secName}]
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* VIEW MODE 1: SECTION BUBBLES */}
            {viewMode === 'bubbles' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
                    {/* Top Preamble Notes Banner (if any) */}
                    {parsedDoc.preamble.trim() && (
                        <div
                            style={{
                                padding: '0.5rem 0.75rem',
                                background: 'rgba(255, 255, 255, 0.02)',
                                border: '1px dashed var(--border)',
                                borderRadius: 'var(--radius-md)',
                                fontSize: '0.75rem',
                                color: 'var(--text-muted)',
                                fontFamily: 'var(--font-mono)',
                                whiteSpace: 'pre-wrap',
                            }}
                        >
                            {parsedDoc.preamble.trim()}
                        </div>
                    )}

                    {filteredSections.map((sec) => {
                        const isCodeView = !!sectionCodeModes[sec.name]
                        const meta = categorizeIniSection(sec.name)
                        const secId = `ini-sec-${sec.name.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`
                        const isAddingSetting = activeAddSettingSection === sec.name
                        const isExpandedDirectives = !!expandedDirectives[sec.name]

                        return (
                            <div
                                key={sec.name}
                                id={secId}
                                className="card ini-section-bubble"
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '0.75rem',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius-lg)',
                                    background: 'var(--surface)',
                                    transition: 'border-color 0.15s ease',
                                }}
                            >
                                {/* Bubble Header */}
                                <div
                                    style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        alignItems: 'center',
                                        flexWrap: 'wrap',
                                        gap: '0.5rem',
                                        borderBottom: '1px solid var(--border)',
                                        paddingBottom: '0.65rem',
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
                                        <span
                                            style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontWeight: 700,
                                                fontSize: '0.95rem',
                                                color: 'var(--text)',
                                            }}
                                        >
                                            [{sec.name}]
                                        </span>
                                        <span
                                            style={{
                                                fontSize: '0.7rem',
                                                padding: '0.12rem 0.5rem',
                                                borderRadius: 6,
                                                background: 'rgba(255, 255, 255, 0.05)',
                                                border: `1px solid ${meta.color}`,
                                                color: meta.color,
                                                fontWeight: 600,
                                            }}
                                        >
                                            {meta.label}
                                        </span>
                                        <span
                                            style={{
                                                fontSize: '0.72rem',
                                                color: 'var(--text-muted)',
                                                fontFamily: 'var(--font-mono)',
                                            }}
                                        >
                                            {sec.fields.length} setting{sec.fields.length === 1 ? '' : 's'}
                                        </span>
                                    </div>

                                    {/* Bubble Actions */}
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                        {/* Per-Site FlareSolverr Toggle Button */}
                                        {(() => {
                                            const secFlare = getSectionFlareSolverr(sec.lines, sec.name)
                                            return secFlare.isEnabled ? (
                                                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                                                    <span
                                                        style={{
                                                            display: 'inline-flex',
                                                            alignItems: 'center',
                                                            gap: '0.25rem',
                                                            fontSize: '0.7rem',
                                                            padding: '0.12rem 0.45rem',
                                                            borderRadius: 6,
                                                            background: 'rgba(16, 185, 129, 0.15)',
                                                            border: '1px solid rgba(16, 185, 129, 0.35)',
                                                            color: '#10b981',
                                                            fontWeight: 600,
                                                        }}
                                                    >
                                                        <Zap size={11} className="fill-current" /> FlareSolverr
                                                    </span>
                                                    {!readOnly && (
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            onClick={() => {
                                                                setTargetFlareSection(sec.name)
                                                                setCustomFlareAddress(secFlare.address)
                                                                setShowFlareModal(true)
                                                            }}
                                                            style={{ minHeight: 22, padding: '0.08rem 0.35rem', fontSize: '0.68rem' }}
                                                            title={`Configure FlareSolverr endpoint for [${sec.name}]`}
                                                        >
                                                            ⚙️
                                                        </button>
                                                    )}
                                                    {!readOnly && (
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            onClick={() => handleToggleSiteFlare(sec.name, false)}
                                                            style={{ minHeight: 22, padding: '0.08rem 0.4rem', fontSize: '0.68rem', color: 'var(--error)' }}
                                                            title={`Disable FlareSolverr on [${sec.name}]`}
                                                        >
                                                            Disable
                                                        </button>
                                                    )}
                                                </div>
                                            ) : (
                                                !readOnly && (
                                                    <button
                                                        type="button"
                                                        className="secondary btn-sm"
                                                        onClick={() => handleToggleSiteFlare(sec.name, true)}
                                                        style={{
                                                            minHeight: 24,
                                                            fontSize: '0.7rem',
                                                            padding: '0.12rem 0.45rem',
                                                            color: '#f59e0b',
                                                            borderColor: 'rgba(245, 158, 11, 0.3)',
                                                        }}
                                                        title={`Enable FlareSolverr proxy for [${sec.name}] in 1 click`}
                                                    >
                                                        <Zap size={11} /> + FlareSolverr
                                                    </button>
                                                )
                                            )
                                        })()}

                                        {/* Toggle Form / Scoped Code Mode */}
                                        <button
                                            type="button"
                                            className="secondary btn-sm"
                                            onClick={() => toggleSectionCodeMode(sec.name)}
                                            style={{ minHeight: 24, fontSize: '0.72rem', padding: '0.15rem 0.45rem' }}
                                            title={isCodeView ? 'Switch to Form View' : 'Edit raw section text'}
                                        >
                                            {isCodeView ? <Sliders size={12} /> : <Code size={12} />}
                                            <span>{isCodeView ? 'Form View' : 'Code'}</span>
                                        </button>

                                        {/* Delete section */}
                                        {!readOnly && (
                                            <button
                                                type="button"
                                                className="secondary btn-sm"
                                                onClick={() => handleDeleteSection(sec.name)}
                                                style={{
                                                    minHeight: 24,
                                                    fontSize: '0.72rem',
                                                    padding: '0.15rem 0.45rem',
                                                    color: 'var(--error)',
                                                }}
                                                title={`Delete section [${sec.name}]`}
                                            >
                                                <Trash2 size={12} />
                                            </button>
                                        )}
                                    </div>
                                </div>

                                {/* Bubble Body: Scoped Raw Code View */}
                                {isCodeView ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                        <textarea
                                            rows={Math.max(4, Math.min(20, sec.lines.length + 2))}
                                            readOnly={readOnly}
                                            value={sec.lines.join('\n')}
                                            onChange={(e) => handleSectionContentChange(sec.name, e.target.value)}
                                            style={{
                                                fontFamily: 'var(--font-mono)',
                                                fontSize: '0.82rem',
                                                lineHeight: 1.55,
                                                background: '#070a12',
                                                resize: 'vertical',
                                            }}
                                        />
                                    </div>
                                ) : (
                                    /* Bubble Body: Form View */
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                                        {/* Key-Value Fields */}
                                        {sec.fields.length === 0 && (
                                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontStyle: 'italic', padding: '0.2rem 0' }}>
                                                No key-value directives in this section yet.
                                            </div>
                                        )}

                                        {sec.fields.map((field) => {
                                            const lowerKey = field.key.toLowerCase()
                                            const isBool = field.value.toLowerCase() === 'true' || field.value.toLowerCase() === 'false'
                                            const isSecret = lowerKey.includes('password') || lowerKey.includes('secret') || lowerKey.includes('token')
                                            const isRevealed = !!revealedSecrets[field.id]
                                            const description = referenceKeyComments[lowerKey]

                                            return (
                                                <div
                                                    key={field.id}
                                                    style={{
                                                        display: 'flex',
                                                        justifyContent: 'space-between',
                                                        alignItems: 'flex-start',
                                                        gap: '0.75rem',
                                                        padding: '0.45rem 0.6rem',
                                                        borderRadius: 'var(--radius-sm)',
                                                        background: 'rgba(255, 255, 255, 0.02)',
                                                        border: '1px solid rgba(255, 255, 255, 0.04)',
                                                    }}
                                                >
                                                    {/* Key & Description */}
                                                    <div style={{ flex: '1 1 35%', minWidth: 160 }}>
                                                        <span
                                                            style={{
                                                                fontFamily: 'var(--font-mono)',
                                                                fontWeight: 600,
                                                                fontSize: '0.84rem',
                                                                color: 'var(--text)',
                                                            }}
                                                        >
                                                            {field.key}
                                                        </span>
                                                        {description && (
                                                            <div
                                                                style={{
                                                                    fontSize: '0.74rem',
                                                                    color: 'var(--text-muted)',
                                                                    marginTop: '0.15rem',
                                                                    lineHeight: 1.35,
                                                                }}
                                                            >
                                                                {description}
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Value Input / Control */}
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flex: '1 1 55%', minWidth: 160 }}>
                                                        {isBool ? (
                                                            /* Boolean Pill Toggle */
                                                            <div style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                                                                <div
                                                                    style={{
                                                                        display: 'inline-flex',
                                                                        background: 'var(--surface2)',
                                                                        borderRadius: 'var(--radius-sm)',
                                                                        padding: '2px',
                                                                        border: '1px solid var(--border)',
                                                                    }}
                                                                >
                                                                    <button
                                                                        type="button"
                                                                        className={`segmented-btn ${field.value.toLowerCase() === 'true' ? 'active' : ''}`}
                                                                        onClick={() => handleFieldChange(sec.name, field.key, 'true')}
                                                                        disabled={readOnly}
                                                                        style={{
                                                                            minHeight: 24,
                                                                            fontSize: '0.72rem',
                                                                            padding: '0.1rem 0.55rem',
                                                                            background: field.value.toLowerCase() === 'true' ? 'var(--success)' : 'transparent',
                                                                            color: '#fff',
                                                                        }}
                                                                    >
                                                                        true
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className={`segmented-btn ${field.value.toLowerCase() === 'false' ? 'active' : ''}`}
                                                                        onClick={() => handleFieldChange(sec.name, field.key, 'false')}
                                                                        disabled={readOnly}
                                                                        style={{
                                                                            minHeight: 24,
                                                                            fontSize: '0.72rem',
                                                                            padding: '0.1rem 0.55rem',
                                                                            background: field.value.toLowerCase() === 'false' ? 'rgba(239, 68, 68, 0.4)' : 'transparent',
                                                                            color: '#fff',
                                                                        }}
                                                                    >
                                                                        false
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        ) : (
                                                            /* Text / Password Input */
                                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flex: 1, minWidth: 0 }}>
                                                                <input
                                                                    type={isSecret && !isRevealed ? 'password' : 'text'}
                                                                    value={field.value}
                                                                    readOnly={readOnly}
                                                                    onChange={(e) => handleFieldChange(sec.name, field.key, e.target.value)}
                                                                    style={{
                                                                        fontFamily: 'var(--font-mono)',
                                                                        fontSize: '0.82rem',
                                                                        minHeight: 30,
                                                                        padding: '0.25rem 0.5rem',
                                                                        flex: 1,
                                                                        minWidth: 0,
                                                                    }}
                                                                />
                                                                {isSecret && (
                                                                    <button
                                                                        type="button"
                                                                        className="secondary btn-sm"
                                                                        onClick={() => toggleSecret(field.id)}
                                                                        style={{ minHeight: 26, padding: '0.15rem 0.35rem', flexShrink: 0 }}
                                                                        title={isRevealed ? 'Hide secret' : 'Show secret'}
                                                                    >
                                                                        {isRevealed ? <EyeOff size={13} /> : <Eye size={13} />}
                                                                    </button>
                                                                )}
                                                            </div>
                                                        )}

                                                        {/* Delete Field */}
                                                        {!readOnly && (
                                                            <button
                                                                type="button"
                                                                className="secondary btn-sm"
                                                                onClick={() => handleRemoveField(sec.name, field.key)}
                                                                style={{
                                                                    minHeight: 26,
                                                                    padding: '0.15rem 0.35rem',
                                                                    color: 'var(--text-muted)',
                                                                    marginLeft: 'auto',
                                                                    flexShrink: 0,
                                                                }}
                                                                title={`Remove ${field.key}`}
                                                            >
                                                                <X size={13} />
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            )
                                        })}

                                        {/* Add Setting Row / Button */}
                                        {!readOnly && (
                                            <div>
                                                {isAddingSetting ? (
                                                    <div
                                                        style={{
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            gap: '0.4rem',
                                                            padding: '0.45rem',
                                                            background: 'var(--surface2)',
                                                            borderRadius: 'var(--radius-sm)',
                                                            flexWrap: 'wrap',
                                                        }}
                                                    >
                                                        {/* Autocomplete Key Input Container */}
                                                        <div style={{ position: 'relative', flex: '1 1 200px', minWidth: 160 }}>
                                                            <input
                                                                ref={keyInputRef}
                                                                type="text"
                                                                placeholder="Key (e.g. is_adult or username)"
                                                                value={newSettingKey}
                                                                onFocus={() => setShowKeyDropdown(true)}
                                                                onChange={(e) => {
                                                                    setNewSettingKey(e.target.value)
                                                                    setShowKeyDropdown(true)
                                                                    setSelectedSuggestionIndex(-1)
                                                                }}
                                                                onKeyDown={(e) => {
                                                                    if (e.key === 'ArrowDown') {
                                                                        e.preventDefault()
                                                                        setShowKeyDropdown(true)
                                                                        setSelectedSuggestionIndex((prev) =>
                                                                            Math.min(prev + 1, keySuggestions.length - 1)
                                                                        )
                                                                    } else if (e.key === 'ArrowUp') {
                                                                        e.preventDefault()
                                                                        setSelectedSuggestionIndex((prev) => Math.max(prev - 1, -1))
                                                                    } else if (e.key === 'Enter') {
                                                                        if (
                                                                            showKeyDropdown &&
                                                                            selectedSuggestionIndex >= 0 &&
                                                                            keySuggestions[selectedSuggestionIndex]
                                                                        ) {
                                                                            e.preventDefault()
                                                                            handleSelectSuggestion(keySuggestions[selectedSuggestionIndex])
                                                                        } else if (newSettingKey.trim()) {
                                                                            e.preventDefault()
                                                                            valueInputRef.current?.focus()
                                                                        }
                                                                    } else if (e.key === 'Escape') {
                                                                        setShowKeyDropdown(false)
                                                                    }
                                                                }}
                                                                style={{
                                                                    fontFamily: 'var(--font-mono)',
                                                                    fontSize: '0.8rem',
                                                                    minHeight: 28,
                                                                    width: '100%',
                                                                }}
                                                            />

                                                            {/* Dropdown Suggestions */}
                                                            {showKeyDropdown && keySuggestions.length > 0 && (
                                                                <div
                                                                    ref={dropdownRef}
                                                                    style={{
                                                                        position: 'absolute',
                                                                        top: 'calc(100% + 4px)',
                                                                        left: 0,
                                                                        minWidth: '100%',
                                                                        width: 'max-content',
                                                                        maxWidth: 400,
                                                                        background: '#0a0e17',
                                                                        border: '1px solid var(--border)',
                                                                        borderRadius: 'var(--radius-sm)',
                                                                        boxShadow: '0 12px 28px rgba(0, 0, 0, 0.7)',
                                                                        maxHeight: 220,
                                                                        overflowY: 'auto',
                                                                        zIndex: 100,
                                                                    }}
                                                                >
                                                                    <div
                                                                        style={{
                                                                            padding: '0.3rem 0.55rem',
                                                                            fontSize: '0.66rem',
                                                                            fontWeight: 700,
                                                                            textTransform: 'uppercase',
                                                                            color: 'var(--text-faint)',
                                                                            borderBottom: '1px solid var(--border-subtle)',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            justifyContent: 'space-between',
                                                                        }}
                                                                    >
                                                                        <span>Directives from defaults.ini</span>
                                                                        <span>{keySuggestions.length} choices</span>
                                                                    </div>
                                                                    {keySuggestions.map((item, idx) => {
                                                                        const isSelected = idx === selectedSuggestionIndex
                                                                        const isSecSpecific =
                                                                            item.section.toLowerCase() ===
                                                                            sec.name.toLowerCase().replace(/^[\[\]]+|[\[\]]+$/g, '')
                                                                        return (
                                                                            <div
                                                                                key={`${item.section}-${item.key}`}
                                                                                onMouseDown={(e) => {
                                                                                    e.preventDefault()
                                                                                    handleSelectSuggestion(item)
                                                                                }}
                                                                                onMouseEnter={() => setSelectedSuggestionIndex(idx)}
                                                                                style={{
                                                                                    padding: '0.35rem 0.6rem',
                                                                                    cursor: 'pointer',
                                                                                    background: isSelected
                                                                                        ? 'rgba(99, 102, 241, 0.22)'
                                                                                        : 'transparent',
                                                                                    borderLeft: isSelected
                                                                                        ? '3px solid #6366f1'
                                                                                        : '3px solid transparent',
                                                                                    borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                                                                                }}
                                                                            >
                                                                                <div
                                                                                    style={{
                                                                                        display: 'flex',
                                                                                        alignItems: 'center',
                                                                                        justifyContent: 'space-between',
                                                                                        gap: '0.35rem',
                                                                                    }}
                                                                                >
                                                                                    <span
                                                                                        style={{
                                                                                            fontFamily: 'var(--font-mono)',
                                                                                            fontWeight: 700,
                                                                                            fontSize: '0.78rem',
                                                                                            color: isSelected ? '#a5b4fc' : '#818cf8',
                                                                                        }}
                                                                                    >
                                                                                        {item.key}
                                                                                    </span>
                                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                                                                        {isSecSpecific && (
                                                                                            <span
                                                                                                style={{
                                                                                                    fontSize: '0.62rem',
                                                                                                    padding: '0.05rem 0.3rem',
                                                                                                    borderRadius: 4,
                                                                                                    background: 'rgba(245, 158, 11, 0.18)',
                                                                                                    color: '#f59e0b',
                                                                                                    border: '1px solid rgba(245, 158, 11, 0.35)',
                                                                                                    fontWeight: 600,
                                                                                                }}
                                                                                            >
                                                                                                [{item.section}]
                                                                                            </span>
                                                                                        )}
                                                                                        {item.defaultValue && (
                                                                                            <span
                                                                                                style={{
                                                                                                    fontSize: '0.67rem',
                                                                                                    fontFamily: 'var(--font-mono)',
                                                                                                    color: 'var(--text-muted)',
                                                                                                }}
                                                                                            >
                                                                                                default:{' '}
                                                                                                <code
                                                                                                    style={{
                                                                                                        color: '#10b981',
                                                                                                        background: 'rgba(16, 185, 129, 0.1)',
                                                                                                        padding: '0.05rem 0.2rem',
                                                                                                        borderRadius: 3,
                                                                                                    }}
                                                                                                >
                                                                                                    {item.defaultValue.length > 20
                                                                                                        ? item.defaultValue.slice(0, 18) + '…'
                                                                                                        : item.defaultValue}
                                                                                                </code>
                                                                                            </span>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                                {item.description && (
                                                                                    <div
                                                                                        style={{
                                                                                            fontSize: '0.68rem',
                                                                                            color: 'var(--text-faint)',
                                                                                            marginTop: '0.12rem',
                                                                                            overflow: 'hidden',
                                                                                            textOverflow: 'ellipsis',
                                                                                            whiteSpace: 'nowrap',
                                                                                        }}
                                                                                        title={item.description}
                                                                                    >
                                                                                        {item.description}
                                                                                    </div>
                                                                                )}
                                                                            </div>
                                                                        )
                                                                    })}
                                                                </div>
                                                            )}
                                                        </div>

                                                        {/* Value Input */}
                                                        <input
                                                            ref={valueInputRef}
                                                            type="text"
                                                            placeholder="Value"
                                                            value={newSettingValue}
                                                            onChange={(e) => setNewSettingValue(e.target.value)}
                                                            onKeyDown={(e) => {
                                                                if (e.key === 'Enter') {
                                                                    handleAddNewSetting(sec.name)
                                                                }
                                                            }}
                                                            style={{
                                                                fontFamily: 'var(--font-mono)',
                                                                fontSize: '0.8rem',
                                                                minHeight: 28,
                                                                flex: '1 1 180px',
                                                            }}
                                                        />
                                                        <button
                                                            type="button"
                                                            className="btn-sm"
                                                            onClick={() => handleAddNewSetting(sec.name)}
                                                            disabled={!newSettingKey.trim()}
                                                            style={{ minHeight: 28, fontSize: '0.75rem' }}
                                                        >
                                                            Add
                                                        </button>
                                                        <button
                                                            type="button"
                                                            className="secondary btn-sm"
                                                            onClick={() => {
                                                                setActiveAddSettingSection(null)
                                                                setNewSettingKey('')
                                                                setNewSettingValue('')
                                                                setShowKeyDropdown(false)
                                                                setSelectedSuggestionIndex(-1)
                                                            }}
                                                            style={{ minHeight: 28, fontSize: '0.75rem' }}
                                                        >
                                                            Cancel
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        className="secondary btn-sm"
                                                        onClick={() => {
                                                            setActiveAddSettingSection(sec.name)
                                                            setNewSettingKey('')
                                                            setNewSettingValue('')
                                                            setShowKeyDropdown(true)
                                                            setSelectedSuggestionIndex(-1)
                                                            setTimeout(() => keyInputRef.current?.focus(), 50)
                                                        }}
                                                        style={{
                                                            fontSize: '0.74rem',
                                                            padding: '0.2rem 0.55rem',
                                                            marginTop: '0.2rem',
                                                        }}
                                                    >
                                                        <Plus size={12} /> Add Setting
                                                    </button>
                                                )}
                                            </div>
                                        )}

                                        {/* Expandable Advanced Directives / Comments (for multiline replacement rules) */}
                                        {sec.customDirectives.trim() && (
                                            <div
                                                style={{
                                                    marginTop: '0.4rem',
                                                    borderTop: '1px dashed var(--border)',
                                                    paddingTop: '0.45rem',
                                                }}
                                            >
                                                <button
                                                    type="button"
                                                    className="secondary btn-sm"
                                                    onClick={() =>
                                                        setExpandedDirectives((prev) => ({
                                                            ...prev,
                                                            [sec.name]: !prev[sec.name],
                                                        }))
                                                    }
                                                    style={{
                                                        padding: '0.1rem 0.4rem',
                                                        minHeight: 22,
                                                        fontSize: '0.72rem',
                                                        color: 'var(--text-muted)',
                                                    }}
                                                >
                                                    {isExpandedDirectives ? (
                                                        <ChevronDown size={13} />
                                                    ) : (
                                                        <ChevronRight size={13} />
                                                    )}
                                                    <span>
                                                        {isExpandedDirectives ? 'Hide' : 'Show'} Custom Directives & Comments
                                                    </span>
                                                </button>

                                                {isExpandedDirectives && (
                                                    <div
                                                        style={{
                                                            marginTop: '0.4rem',
                                                            padding: '0.5rem',
                                                            background: '#06080e',
                                                            borderRadius: 'var(--radius-sm)',
                                                            fontFamily: 'var(--font-mono)',
                                                            fontSize: '0.75rem',
                                                            color: 'var(--text-muted)',
                                                            whiteSpace: 'pre-wrap',
                                                            lineHeight: 1.45,
                                                        }}
                                                    >
                                                        {sec.customDirectives.trim()}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            )}

            {/* VIEW MODE 2: MONOLITHIC RAW EDITOR */}
            {viewMode === 'raw' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <textarea
                        ref={rawTextareaRef}
                        rows={32}
                        readOnly={readOnly}
                        value={iniText}
                        onChange={(e) => onChange(e.target.value)}
                        style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.84rem',
                            lineHeight: 1.6,
                            minHeight: 'calc(100vh - 280px)',
                            resize: 'vertical',
                            background: '#05070c',
                        }}
                    />
                </div>
            )}

            {/* VIEW MODE 3: LINE DIFF */}
            {viewMode === 'diff' && (
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
                    {computeIniLineDiff(initialIniText, iniText).map((d, idx) => (
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
            )}
        </div>
    )
}
