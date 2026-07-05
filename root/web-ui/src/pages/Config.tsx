import { useEffect, useState } from 'react'
import { getConfig, updateConfigSection, getIniFile, updateIniFile, type ConfigResponse, type ConfigUpdateResult, type IniFileResponse, type IniUpdateResult } from '../api'

type SectionData = Record<string, unknown>

type IniType = 'personal' | 'defaults'

interface IniState {
    content: string
    path: string | null
    error: string | null
    loading: boolean
    editing: boolean
    editContent: string
    saveResult: IniUpdateResult | null
}

const INI_LABELS: Record<IniType, string> = {
    personal: 'personal.ini',
    defaults: 'defaults.ini',
}

export default function Config() {
    const [configData, setConfigData] = useState<Record<string, SectionData>>({})
    const [editSection, setEditSection] = useState<string | null>(null)
    const [editValues, setEditValues] = useState<Record<string, string>>({})
    const [saveResult, setSaveResult] = useState<ConfigUpdateResult | null>(null)
    const [loading, setLoading] = useState(true)

    const [iniStates, setIniStates] = useState<Record<IniType, IniState>>({
        personal: { content: '', path: null, error: null, loading: true, editing: false, editContent: '', saveResult: null },
        defaults: { content: '', path: null, error: null, loading: true, editing: false, editContent: '', saveResult: null },
    })

    useEffect(() => {
        getConfig()
            .then((res: ConfigResponse) => {
                const sections: Record<string, SectionData> = {}
                for (const [k, v] of Object.entries(res.config)) {
                    if (typeof v === 'object' && v !== null) {
                        sections[k] = v as SectionData
                    }
                }
                setConfigData(sections)
            })
            .catch(() => { })
            .finally(() => setLoading(false))

        for (const t of ['personal', 'defaults'] as IniType[]) {
            getIniFile(t)
                .then((res: IniFileResponse) => {
                    setIniStates(prev => ({
                        ...prev,
                        [t]: { ...prev[t], content: res.content ?? '', path: res.path ?? null, error: res.error ?? null, loading: false },
                    }))
                })
                .catch(() => {
                    setIniStates(prev => ({
                        ...prev,
                        [t]: { ...prev[t], error: 'Failed to load', loading: false },
                    }))
                })
        }
    }, [])

    const startEdit = (section: string) => {
        const current = configData[section] ?? {}
        const vals: Record<string, string> = {}
        for (const [k, v] of Object.entries(current)) {
            vals[k] = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')
        }
        setEditValues(vals)
        setEditSection(section)
        setSaveResult(null)
    }

    const handleSave = async () => {
        if (!editSection) return
        setLoading(true)
        try {
            const parsed: Record<string, unknown> = {}
            for (const [k, v] of Object.entries(editValues)) {
                if (v === 'true') parsed[k] = true
                else if (v === 'false') parsed[k] = false
                else if (/^\d+$/.test(v)) parsed[k] = parseInt(v, 10)
                else if (/^\d+\.\d+$/.test(v)) parsed[k] = parseFloat(v)
                else if (v.startsWith('[') || v.startsWith('{')) {
                    try { parsed[k] = JSON.parse(v) } catch { parsed[k] = v }
                }
                else parsed[k] = v
            }
            const res = await updateConfigSection(editSection, parsed)
            setSaveResult(res)
            if (res.applied) {
                getConfig().then(r => {
                    const sections: Record<string, SectionData> = {}
                    for (const [k2, v2] of Object.entries(r.config)) {
                        if (typeof v2 === 'object' && v2 !== null) sections[k2] = v2 as SectionData
                    }
                    setConfigData(sections)
                }).catch(() => { })
                setEditSection(null)
            }
        } catch (err) {
            setSaveResult({ applied: false, error: String(err) })
        } finally {
            setLoading(false)
        }
    }

    const startIniEdit = (t: IniType) => {
        setIniStates(prev => ({
            ...prev,
            [t]: { ...prev[t], editing: true, editContent: prev[t].content, saveResult: null },
        }))
    }

    const cancelIniEdit = (t: IniType) => {
        setIniStates(prev => ({
            ...prev,
            [t]: { ...prev[t], editing: false, saveResult: null },
        }))
    }

    const saveIni = async (t: IniType) => {
        const editContent = iniStates[t].editContent
        setIniStates(prev => ({ ...prev, [t]: { ...prev[t], loading: true } }))
        try {
            const res = await updateIniFile(t, editContent)
            setIniStates(prev => ({
                ...prev,
                [t]: { ...prev[t], loading: false, saveResult: res, editing: !res.applied, content: res.applied ? editContent : prev[t].content },
            }))
        } catch (err) {
            setIniStates(prev => ({
                ...prev,
                [t]: { ...prev[t], loading: false, saveResult: { applied: false, error: String(err) } },
            }))
        }
    }

    if (loading && Object.keys(configData).length === 0) return <p>Loading config…</p>

    const sections = Object.entries(configData)

    return (
        <>
            <h1 style={{ marginBottom: '1rem' }}>Configuration</h1>

            {saveResult && (
                <div className="card" style={{ borderLeft: `3px solid ${saveResult.applied ? 'var(--success)' : 'var(--error)'}` }}>
                    {saveResult.applied ? (
                        <>
                            <p style={{ color: 'var(--success)' }}>Changes saved.</p>
                            {(saveResult.needs_service_restart || saveResult.needs_app_restart) && (
                                <p style={{ color: 'var(--warning)' }}>⚠ Some changes require an app restart to take effect.</p>
                            )}
                        </>
                    ) : (
                        <p style={{ color: 'var(--error)' }}>Error: {saveResult.error}</p>
                    )}
                </div>
            )}

            {sections.map(([section, fields]) => (
                <div className="card" key={section}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2>{section}</h2>
                        {editSection !== section && (
                            <button className="secondary" onClick={() => startEdit(section)}>Edit</button>
                        )}
                    </div>

                    {editSection === section ? (
                        <div>
                            <table>
                                <tbody>
                                    {Object.entries(editValues).map(([field, val]) => (
                                        <tr key={field}>
                                            <td style={{ width: '30%' }}>{field}</td>
                                            <td>
                                                <input
                                                    value={val}
                                                    onChange={e => setEditValues(prev => ({ ...prev, [field]: e.target.value }))}
                                                />
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                                <button onClick={handleSave} disabled={loading}>Save</button>
                                <button className="secondary" onClick={() => setEditSection(null)}>Cancel</button>
                            </div>
                        </div>
                    ) : (
                        <table>
                            <tbody>
                                {Object.entries(fields).map(([field, value]) => (
                                    <tr key={field}>
                                        <td style={{ width: '30%' }}>{field}</td>
                                        <td>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            ))}

            <h2 style={{ margin: '1.5rem 0 0.75rem' }}>FanFicFare Configuration Files</h2>

            {(['personal', 'defaults'] as IniType[]).map(t => {
                const ini = iniStates[t]
                const label = INI_LABELS[t]
                return (
                    <div className="card" key={t}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h2>{label}{ini.path && <span style={{ fontSize: '0.75rem', fontWeight: 'normal', marginLeft: '0.5rem', opacity: 0.6 }}>{ini.path}</span>}</h2>
                            {!ini.editing && !ini.error && (
                                <button className="secondary" onClick={() => startIniEdit(t)} disabled={ini.loading}>Edit</button>
                            )}
                        </div>

                        {ini.saveResult && (
                            <p style={{ color: ini.saveResult.applied ? 'var(--success)' : 'var(--error)' }}>
                                {ini.saveResult.applied ? 'Changes saved.' : `Error: ${ini.saveResult.error}`}
                            </p>
                        )}

                        {ini.error && !ini.editing ? (
                            <p style={{ color: 'var(--error)', fontStyle: 'italic' }}>{ini.error}</p>
                        ) : ini.editing ? (
                            <div>
                                <textarea
                                    value={ini.editContent}
                                    onChange={e => setIniStates(prev => ({ ...prev, [t]: { ...prev[t], editContent: e.target.value } }))}
                                    rows={20}
                                    style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.85rem', resize: 'vertical', boxSizing: 'border-box' }}
                                />
                                <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                                    <button onClick={() => saveIni(t)} disabled={ini.loading}>Save</button>
                                    <button className="secondary" onClick={() => cancelIniEdit(t)}>Cancel</button>
                                </div>
                            </div>
                        ) : (
                            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'monospace', fontSize: '0.85rem', margin: 0 }}>
                                {ini.content || <em style={{ opacity: 0.5 }}>File is empty</em>}
                            </pre>
                        )}
                    </div>
                )
            })}
        </>
    )
}
