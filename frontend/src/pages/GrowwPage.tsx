import { useEffect, useState } from 'react'
import { api } from '../api'

interface GrowwStatus {
  configured: boolean
  has_api_key: boolean
  has_api_secret: boolean
  has_access_token: boolean
  last_sync_at?: string | null
  token_expiry?: string | null
}

export function GrowwPage() {
  const [status, setStatus] = useState<GrowwStatus | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [synced, setSynced] = useState<Array<{ instrument: string; units: number; action: string }>>(
    [],
  )
  const [busy, setBusy] = useState(false)

  function load() {
    api
      .get<GrowwStatus>('/api/os/groww/status')
      .then(setStatus)
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
  }, [])

  async function sync() {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const res = await api.post<{ synced: typeof synced; count: number }>('/api/os/groww/sync')
      setSynced(res.synced)
      setMessage(`Synced ${res.count} equity/ETF holdings. Mutual funds stay on SIP + NAV.`)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Optional</p>
          <h1 className="page-title">Groww sync</h1>
          <p className="page-lead">
            Stocks &amp; ETFs only. Mutual funds stay on SIP ledger + public NAV.
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {message && (
        <div className="banner">
          <span>{message}</span>
        </div>
      )}

      <section className="panel">
        <p className="panel-label">Status</p>
        {status ? (
          <p className="muted" style={{ margin: 0 }}>
            {status.configured
              ? `Credentials present${status.last_sync_at ? ` · last sync ${status.last_sync_at}` : ''}.`
              : 'Not configured. Set GROWW_API_KEY and GROWW_API_SECRET in .env.'}
            <br />
            Key: {status.has_api_key ? 'yes' : 'no'} · Secret: {status.has_api_secret ? 'yes' : 'no'} ·
            Token: {status.has_access_token ? 'yes' : 'no'}
          </p>
        ) : (
          <div className="skeleton" style={{ width: '60%' }} />
        )}
      </section>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">Sync equity holdings</p>
        <p className="muted">
          Creates or updates stock/ETF positions from Groww. Does not touch MF SIPs. Requires daily
          approval of your API key on Groww Cloud if using key+secret exchange.
        </p>
        <button className="btn" disabled={!status?.configured || busy} onClick={sync}>
          {busy ? 'Syncing…' : 'Sync holdings'}
        </button>
      </section>

      {synced.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Synced this run</p>
          <ul className="alert-list">
            {synced.map((h, i) => (
              <li key={i} className="alert-item" style={{ background: 'var(--bg-muted)', color: 'var(--fg)' }}>
                {h.action}: {h.instrument} · {h.units} units
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
