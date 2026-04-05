import { useState } from 'react'
import { addUrl, type AddUrlResponse } from '../api'

export default function Controls() {
  const [url, setUrl] = useState('')
  const [result, setResult] = useState<AddUrlResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setLoading(true)
    setResult(null)
    try {
      const res = await addUrl(url.trim())
      setResult(res)
      if (res.accepted) setUrl('')
    } catch (err) {
      setResult({ accepted: false, message: String(err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <h1 style={{ marginBottom: '1rem' }}>Controls</h1>

      <div className="card">
        <h2>Add URL</h2>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://archiveofourown.org/works/12345"
            required
            style={{ flex: 1 }}
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Adding…' : 'Add'}
          </button>
        </form>

        {result && (
          <p style={{ marginTop: '0.75rem', color: result.accepted ? 'var(--success)' : 'var(--error)' }}>
            {result.message}
          </p>
        )}
      </div>
    </>
  )
}
