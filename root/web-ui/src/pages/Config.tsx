import { useEffect, useState } from 'react'
import { getConfig, updateConfigSection, type ConfigResponse, type ConfigUpdateResult } from '../api'

type SectionData = Record<string, unknown>

export default function Config() {
  const [configData, setConfigData] = useState<Record<string, SectionData>>({})
  const [reloadMap, setReloadMap] = useState<Record<string, Record<string, { value: unknown; reload_behavior: string }>>>({})
  const [editSection, setEditSection] = useState<string | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [saveResult, setSaveResult] = useState<ConfigUpdateResult | null>(null)
  const [loading, setLoading] = useState(true)

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
        if (res.reload_map) {
          const typed: Record<string, Record<string, { value: unknown; reload_behavior: string }>> = {}
          for (const [k, v] of Object.entries(res.reload_map)) {
            if (typeof v === 'object' && v !== null) {
              typed[k] = v as Record<string, { value: unknown; reload_behavior: string }>
            }
          }
          setReloadMap(typed)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
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
      // Parse values back to their likely types
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
        // Refresh
        getConfig().then(r => {
          const sections: Record<string, SectionData> = {}
          for (const [k2, v2] of Object.entries(r.config)) {
            if (typeof v2 === 'object' && v2 !== null) sections[k2] = v2 as SectionData
          }
          setConfigData(sections)
        }).catch(() => {})
        setEditSection(null)
      }
    } catch (err) {
      setSaveResult({ applied: false, error: String(err) })
    } finally {
      setLoading(false)
    }
  }

  const badgeFor = (behavior: string) => {
    switch (behavior) {
      case 'hot': return <span className="badge badge-hot" title="Applied instantly">hot</span>
      case 'service_restart': return <span className="badge badge-restart" title="Requires service restart">restart</span>
      case 'app_restart': return <span className="badge badge-app" title="Requires app restart">app restart</span>
      default: return null
    }
  }

  if (loading && Object.keys(configData).length === 0) return <p>Loading config…</p>

  const sections = Object.entries(configData)

  return (
    <>
      <h1 style={{ marginBottom: '1rem' }}>Configuration</h1>

      {/* Save result banner */}
      {saveResult && (
        <div className="card" style={{ borderLeft: `3px solid ${saveResult.applied ? 'var(--success)' : 'var(--error)'}` }}>
          {saveResult.applied ? (
            <>
              <p style={{ color: 'var(--success)' }}>Changes applied.</p>
              {saveResult.needs_service_restart && <p style={{ color: 'var(--warning)' }}>Some changes require a service restart to take effect.</p>}
              {saveResult.needs_app_restart && <p style={{ color: 'var(--error)' }}>Some changes require an app restart to take effect.</p>}
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
                  {Object.entries(editValues).map(([field, val]) => {
                    const meta = reloadMap[section]?.[field]
                    return (
                      <tr key={field}>
                        <td style={{ width: '30%' }}>
                          {field} {meta && badgeFor(meta.reload_behavior)}
                        </td>
                        <td>
                          <input
                            value={val}
                            onChange={e => setEditValues(prev => ({ ...prev, [field]: e.target.value }))}
                          />
                        </td>
                      </tr>
                    )
                  })}
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
                {Object.entries(fields).map(([field, value]) => {
                  const meta = reloadMap[section]?.[field]
                  return (
                    <tr key={field}>
                      <td style={{ width: '30%' }}>
                        {field} {meta && badgeFor(meta.reload_behavior)}
                      </td>
                      <td>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </>
  )
}
