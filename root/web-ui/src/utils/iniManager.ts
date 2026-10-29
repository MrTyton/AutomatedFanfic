/**
 * Utility functions for parsing, serializing, and managing INI sections
 * and FlareSolverr configuration for FanFicFare personal.ini / defaults.ini.
 */

export interface IniField {
    id: string
    key: string
    value: string
    rawLine: string
    isCommentedOut?: boolean
}

export interface IniSection {
    id: string
    name: string
    lines: string[]
    fields: IniField[]
    customDirectives: string // multiline continuations, comments, and unparsed directives
    lineStart: number
}

export interface ParsedIniDocument {
    preamble: string
    sections: IniSection[]
}

export interface FlareSolverrInfo {
    isConfigured: boolean
    isEnabled: boolean
    address: string
    section: string
}

/**
 * Checks if a line is a section header, e.g. [defaults] or [www.fanfiction.net]
 */
export function isSectionHeader(line: string): string | null {
    const trimmed = line.trim()
    const match = trimmed.match(/^\[([^\]]+)\]$/)
    return match ? match[1].trim() : null
}

function trimTrailingEmptyLines(lines: string[]): string[] {
    const copy = [...lines]
    while (copy.length > 0 && copy[copy.length - 1].trim() === '') {
        copy.pop()
    }
    return copy
}

/**
 * Parses INI content into preamble and structured sections.
 */
export function parseIniDocument(content: string): ParsedIniDocument {
    const rawLines = content.split('\n')
    const sections: IniSection[] = []
    let preambleLines: string[] = []
    let currentSection: { name: string; lines: string[]; lineStart: number } | null = null

    for (let i = 0; i < rawLines.length; i++) {
        const line = rawLines[i]
        const secName = isSectionHeader(line)

        if (secName !== null) {
            if (currentSection) {
                sections.push(
                    buildSectionObject(
                        currentSection.name,
                        trimTrailingEmptyLines(currentSection.lines),
                        currentSection.lineStart
                    )
                )
            } else {
                preambleLines = trimTrailingEmptyLines(rawLines.slice(0, i))
            }
            currentSection = { name: secName, lines: [], lineStart: i + 1 }
        } else if (currentSection) {
            currentSection.lines.push(line)
        } else {
            preambleLines.push(line)
        }
    }

    if (currentSection) {
        sections.push(
            buildSectionObject(
                currentSection.name,
                trimTrailingEmptyLines(currentSection.lines),
                currentSection.lineStart
            )
        )
    }

    return {
        preamble: preambleLines.join('\n'),
        sections,
    }
}

/**
 * Analyzes section lines into parsed key-value fields and remaining directives/comments.
 */
function buildSectionObject(name: string, lines: string[], lineStart: number): IniSection {
    const fields: IniField[] = []
    const customDirectivesList: string[] = []

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i]

        // Match key: value or key = value
        // Note: FanFicFare keys are letters, numbers, underscores, dashes, dots
        const kvMatch = line.match(/^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$/)

        if (kvMatch) {
            const key = kvMatch[1].trim()
            const value = kvMatch[2].trim()
            fields.push({
                id: `${name}-${key}-${i}`,
                key,
                value,
                rawLine: line,
                isCommentedOut: false,
            })
        } else {
            customDirectivesList.push(line)
        }
    }

    return {
        id: `sec-${name.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`,
        name,
        lines,
        fields,
        customDirectives: customDirectivesList.join('\n'),
        lineStart,
    }
}

/**
 * Serializes a parsed INI document back to an INI formatted string.
 */
export function serializeIniDocument(doc: ParsedIniDocument): string {
    const parts: string[] = []

    const cleanPreamble = doc.preamble.trim()
    if (cleanPreamble) {
        parts.push(cleanPreamble)
    }

    for (const sec of doc.sections) {
        const secContent = sec.lines.join('\n').trim()
        if (secContent) {
            parts.push(`[${sec.name}]\n${secContent}`)
        } else {
            parts.push(`[${sec.name}]`)
        }
    }

    return parts.join('\n\n') + (parts.length > 0 ? '\n' : '')
}

/**
 * Updates a single field value in a section's lines.
 * If the field already exists, updates it in-place.
 * If it does not exist, appends it.
 */
export function updateSectionField(
    sectionLines: string[],
    key: string,
    newValue: string
): string[] {
    const newLines = [...sectionLines]
    const keyLower = key.toLowerCase()
    let foundIndex = -1

    for (let i = 0; i < newLines.length; i++) {
        const m = newLines[i].match(/^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$/)
        if (m && m[1].toLowerCase() === keyLower) {
            foundIndex = i
            break
        }
    }

    if (foundIndex >= 0) {
        newLines[foundIndex] = `${key}:${newValue}`
    } else {
        newLines.push(`${key}:${newValue}`)
    }

    return newLines
}

/**
 * Removes a field by key from a section's lines.
 */
export function removeSectionField(sectionLines: string[], key: string): string[] {
    const keyLower = key.toLowerCase()
    return sectionLines.filter((l) => {
        const m = l.match(/^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$/)
        return !m || m[1].toLowerCase() !== keyLower
    })
}

/**
 * Checks FlareSolverr status for a specific section's lines.
 */
export function getSectionFlareSolverr(
    lines: string[],
    sectionName: string
): FlareSolverrInfo {
    const defaultAddress = 'http://localhost:8191/v1'
    let isConfigured = false
    let isEnabled = false
    let address = defaultAddress

    for (const line of lines) {
        const trimmed = line.trim()
        const proxyMatch = trimmed.match(/^use_flaresolverr_proxy\s*[:=]\s*(true|false)/i)
        if (proxyMatch) {
            isConfigured = true
            if (proxyMatch[1].toLowerCase() === 'true') {
                isEnabled = true
            }
        }
        const addrMatch = trimmed.match(/^flaresolverr_proxy_address\s*[:=]\s*(\S+)/i)
        if (addrMatch) {
            isConfigured = true
            address = addrMatch[1].trim()
        }
    }

    return {
        section: sectionName,
        isConfigured,
        isEnabled,
        address,
    }
}

/**
 * Returns all sections in the INI document that have FlareSolverr configured.
 */
export function getAllFlareSolverrSites(iniContent: string): FlareSolverrInfo[] {
    const doc = parseIniDocument(iniContent)
    const results: FlareSolverrInfo[] = []
    for (const sec of doc.sections) {
        const status = getSectionFlareSolverr(sec.lines, sec.name)
        if (status.isConfigured) {
            results.push(status)
        }
    }
    return results
}

/**
 * Detects whether FlareSolverr proxy is configured in an INI string.
 */
export function detectFlareSolverr(iniContent: string): FlareSolverrInfo {
    const sites = getAllFlareSolverrSites(iniContent)
    // Return first active site, or first configured site, or unconfigured defaults
    const active = sites.find((s) => s.isEnabled)
    if (active) return active
    if (sites.length > 0) return sites[0]

    return {
        isConfigured: false,
        isEnabled: false,
        address: 'http://localhost:8191/v1',
        section: 'defaults',
    }
}

/**
 * Toggles or updates FlareSolverr proxy configuration for a specific site section.
 * If sectionName is specified, operates on THAT site section, NOT [defaults].
 */
export function setSiteFlareSolverrConfig(
    iniContent: string,
    sectionName: string,
    enable: boolean,
    proxyAddress = 'http://localhost:8191/v1',
    removeCompletely = false
): string {
    const cleanName = sectionName.replace(/[\[\]]/g, '').trim()
    if (!cleanName) return iniContent

    const doc = parseIniDocument(iniContent)
    let targetSec = doc.sections.find((s) => s.name.toLowerCase() === cleanName.toLowerCase())

    if (!targetSec) {
        targetSec = {
            id: `sec-${cleanName.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`,
            name: cleanName,
            lines: [],
            fields: [],
            customDirectives: '',
            lineStart: 0,
        }
        doc.sections.push(targetSec)
    }

    if (enable) {
        targetSec.lines = updateSectionField(targetSec.lines, 'use_flaresolverr_proxy', 'true')
        targetSec.lines = updateSectionField(
            targetSec.lines,
            'flaresolverr_proxy_address',
            proxyAddress || 'http://localhost:8191/v1'
        )
    } else if (removeCompletely) {
        targetSec.lines = removeSectionField(targetSec.lines, 'use_flaresolverr_proxy')
        targetSec.lines = removeSectionField(targetSec.lines, 'flaresolverr_proxy_address')
    } else {
        targetSec.lines = updateSectionField(targetSec.lines, 'use_flaresolverr_proxy', 'false')
        if (proxyAddress) {
            targetSec.lines = updateSectionField(targetSec.lines, 'flaresolverr_proxy_address', proxyAddress)
        }
    }

    return serializeIniDocument(doc)
}

/**
 * Legacy proxy configuration wrapper; delegates to setSiteFlareSolverrConfig.
 */
export function setFlareSolverrConfig(
    iniContent: string,
    enable: boolean,
    proxyAddress = 'http://localhost:8191/v1',
    removeCompletely = false,
    sectionName = 'defaults'
): string {
    return setSiteFlareSolverrConfig(
        iniContent,
        sectionName,
        enable,
        proxyAddress,
        removeCompletely
    )
}

/**
 * Adds a new section to an INI string.
 */
export function addIniSection(iniContent: string, sectionName: string, initialContent = ''): string {
    const cleanName = sectionName.replace(/[\[\]]/g, '').trim()
    if (!cleanName) return iniContent

    const doc = parseIniDocument(iniContent)
    const exists = doc.sections.some((s) => s.name.toLowerCase() === cleanName.toLowerCase())
    if (exists) return iniContent

    const newSec: IniSection = {
        id: `sec-${cleanName.toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`,
        name: cleanName,
        lines: initialContent ? initialContent.split('\n') : [],
        fields: [],
        customDirectives: '',
        lineStart: 0,
    }

    doc.sections.push(newSec)
    return serializeIniDocument(doc)
}

/**
 * Removes a section by name from an INI string.
 */
export function removeIniSection(iniContent: string, sectionName: string): string {
    const cleanName = sectionName.replace(/[\[\]]/g, '').trim().toLowerCase()
    const doc = parseIniDocument(iniContent)
    doc.sections = doc.sections.filter((s) => s.name.toLowerCase() !== cleanName)
    return serializeIniDocument(doc)
}

/**
 * Updates an entire section's content (e.g. from a scoped section code editor).
 */
export function updateSectionContent(
    iniContent: string,
    sectionName: string,
    newContent: string
): string {
    const cleanName = sectionName.replace(/[\[\]]/g, '').trim().toLowerCase()
    const doc = parseIniDocument(iniContent)
    const sec = doc.sections.find((s) => s.name.toLowerCase() === cleanName)

    if (sec) {
        sec.lines = newContent.split('\n')
    } else {
        doc.sections.push({
            id: `sec-${cleanName}`,
            name: sectionName.replace(/[\[\]]/g, '').trim(),
            lines: newContent.split('\n'),
            fields: [],
            customDirectives: '',
            lineStart: 0,
        })
    }

    return serializeIniDocument(doc)
}

/**
 * Formats section category and badge information for display algorithmically
 * using domain patterns, base adapter prefixes, and format descriptors.
 */
export function categorizeIniSection(name: string): {
    category: 'defaults' | 'format' | 'site' | 'adapter' | 'custom'
    label: string
    color: string
} {
    const lower = name.toLowerCase().trim()
    if (lower === 'defaults') {
        return { category: 'defaults', label: 'Core Defaults', color: 'var(--accent)' }
    }
    if (lower.startsWith('base_')) {
        return { category: 'adapter', label: 'Base Adapter', color: 'var(--warning)' }
    }
    // Algorithmic domain detection (contains dot and valid tld/host format)
    if (/[a-z0-9-]+\.[a-z]{2,}/i.test(lower)) {
        return { category: 'site', label: 'Site Override', color: 'var(--success)' }
    }
    // Short alphanumeric identifiers without dot are output formats (e.g. epub, mobi)
    if (/^[a-z0-9_]+$/i.test(lower)) {
        return { category: 'format', label: `Format (${name.toUpperCase()})`, color: 'var(--info)' }
    }
    return { category: 'custom', label: 'Custom Section', color: 'var(--text-muted)' }
}

/**
 * Algorithmically extracts all unique section names from a reference INI file (such as defaults.ini).
 */
export function extractReferenceSections(referenceIni: string): string[] {
    if (!referenceIni.trim()) return []
    const doc = parseIniDocument(referenceIni)
    return doc.sections.map((s) => s.name)
}

/**
 * Algorithmically extracts setting descriptions from documentation comments immediately preceding
 * key-value pairs in a reference INI file (such as defaults.ini).
 */
export function extractReferenceKeyComments(referenceIni: string): Record<string, string> {
    const keyComments: Record<string, string> = {}
    if (!referenceIni.trim()) return keyComments

    const lines = referenceIni.split('\n')
    let commentBuffer: string[] = []

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim()

        if (line.startsWith('#') || line.startsWith(';')) {
            const clean = line.replace(/^[#;]+\s*/, '').trim()
            if (clean) {
                commentBuffer.push(clean)
            }
        } else if (line.length === 0) {
            commentBuffer = []
        } else {
            const kvMatch = line.match(/^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$/)
            if (kvMatch) {
                const key = kvMatch[1].trim().toLowerCase()
                if (commentBuffer.length > 0 && !keyComments[key]) {
                    keyComments[key] = commentBuffer.slice(-3).join(' ')
                }
            }
            commentBuffer = []
        }
    }

    return keyComments
}
