import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, inr, pct } from '../api'
import type { PortfolioSummary, Position, Snapshot } from '../types'

export function PortfolioPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [reconcile, setReconcile] = useState({
    position_id: '',
    units: '',
    nav: '',
    invested_amount: '',
  })

  function load() {
    api
      .get<{ summary: PortfolioSummary; positions: Position[]; snapshots: Snapshot[] }>(
        '/api/os/portfolio',
      )
      .then((d) => {
        setSummary(d.summary)
        setPositions(d.positions)
        setSnapshots(d.snapshots)
        if (!reconcile.position_id && d.positions[0]) {
          setReconcile((r) => ({ ...r, position_id: d.positions[0].id }))
        }
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run(path: string, label: string) {
    setBusy(label)
    setError('')
    try {
      await api.post(path)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy('')
    }
  }

  async function onReconcile(e: FormEvent) {
    e.preventDefault()
    setBusy('reconcile')
    setError('')
    try {
      await api.post('/api/os/portfolio/reconcile', {
        position_id: reconcile.position_id,
        units: Number(reconcile.units),
        nav: Number(reconcile.nav),
        invested_amount: reconcile.invested_amount
          ? Number(reconcile.invested_amount)
          : undefined,
      })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconcile failed')
    } finally {
      setBusy('')
    }
  }

  if (!summary && !error) return <div className="skeleton" style={{ height: 28, width: '40%' }} />

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Portfolio</p>
          <h1 className="page-title">Your book</h1>
          <p className="page-lead">
            Mark-to-market from SIP ledger + public NAV. Groww is where you click buy/sell.
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {summary && (
        <div className="grid-2">
          <section className="panel">
            <p className="panel-label">Total value</p>
            <div className="metric mono">{inr(summary.total_value)}</div>
            <p className={summary.pnl >= 0 ? 'pos' : 'neg'} style={{ margin: '0.35rem 0 0' }}>
              {pct(summary.pnl_pct)} · {inr(summary.pnl)}
            </p>
          </section>
          <section className="panel">
            <p className="panel-label">Core / satellite</p>
            <p style={{ margin: '0.5rem 0 0' }}>
              Core <strong>{summary.core_pct}%</strong> ({inr(summary.core_value)})
            </p>
            <p style={{ margin: '0.25rem 0 0' }}>
              Satellite <strong>{summary.satellite_pct}%</strong> ({inr(summary.satellite_value)})
            </p>
            {summary.satellite_pct > 30 && (
              <p className="muted" style={{ color: 'var(--warning)', marginTop: '0.75rem' }}>
                Satellite above ~30% — consider trimming tactical tilts.
              </p>
            )}
          </section>
        </div>
      )}

      <div className="btn-row" style={{ margin: '1rem 0' }}>
        <button
          className="btn btn-sm"
          disabled={!!busy}
          onClick={() => run('/api/os/portfolio/refresh-nav', 'nav')}
        >
          {busy === 'nav' ? 'Refreshing…' : 'Refresh MF NAVs'}
        </button>
        <button
          className="btn btn-sm btn-ghost"
          disabled={!!busy}
          onClick={() => run('/api/os/portfolio/process-sips', 'sips')}
        >
          {busy === 'sips' ? 'Crediting…' : 'Credit due SIPs'}
        </button>
        <button
          className="btn btn-sm btn-ghost"
          disabled={!!busy}
          onClick={() => run('/api/os/portfolio/snapshot', 'snap')}
        >
          {busy === 'snap' ? 'Saving…' : 'Take snapshot'}
        </button>
      </div>

      {summary && Object.keys(summary.by_sector).length > 0 && (
        <section className="panel">
          <p className="panel-label">By sector</p>
          {Object.entries(summary.by_sector).map(([sec, val]) => {
            const w = summary.total_value ? (val / summary.total_value) * 100 : 0
            return (
              <div
                key={sec}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '100px 1fr 80px',
                  gap: '0.75rem',
                  alignItems: 'center',
                  marginBottom: '0.5rem',
                }}
              >
                <span style={{ fontSize: 13, textAlign: 'right' }}>{sec}</span>
                <div
                  style={{
                    height: 22,
                    background: 'var(--bg-muted)',
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${w}%`,
                      height: '100%',
                      background: 'var(--accent)',
                      color: 'white',
                      fontSize: 10,
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      paddingLeft: 8,
                    }}
                  >
                    {w.toFixed(1)}%
                  </div>
                </div>
                <span className="mono muted">{inr(val)}</span>
              </div>
            )
          })}
        </section>
      )}

      {positions.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Holdings</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Sleeve</th>
                  <th>Invested</th>
                  <th>Value</th>
                  <th>P&amp;L</th>
                  <th>Weight</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/positions/${p.id}`}>{p.instrument}</Link>
                    </td>
                    <td>{p.sleeve}</td>
                    <td className="mono">{inr(p.invested_amount)}</td>
                    <td className="mono">{inr(p.market_value)}</td>
                    <td className={p.pnl_pct >= 0 ? 'pos' : 'neg'}>{pct(p.pnl_pct)}</td>
                    <td className="mono">
                      {summary?.total_value
                        ? `${((p.market_value / summary.total_value) * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {snapshots.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Growth</p>
          <div style={{ width: '100%', height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={snapshots}>
                <XAxis dataKey="snapshot_date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={70} />
                <Tooltip formatter={(v) => inr(Number(v))} />
                <Line
                  type="monotone"
                  dataKey="total_value"
                  stroke="hsl(152 45% 32%)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">CAS reconcile (quarterly)</p>
        <p className="muted">
          Download one CAS from{' '}
          <a href="https://www.mfcentral.com" target="_blank" rel="noreferrer">
            MF Central
          </a>
          , then set true units + NAV per fund.
        </p>
        <form className="form-grid" onSubmit={onReconcile} style={{ marginTop: '1rem' }}>
          <label className="field">
            Position
            <select
              value={reconcile.position_id}
              onChange={(e) => setReconcile({ ...reconcile, position_id: e.target.value })}
              required
            >
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.instrument}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            True units
            <input
              type="number"
              step="any"
              required
              value={reconcile.units}
              onChange={(e) => setReconcile({ ...reconcile, units: e.target.value })}
            />
          </label>
          <label className="field">
            NAV
            <input
              type="number"
              step="any"
              required
              value={reconcile.nav}
              onChange={(e) => setReconcile({ ...reconcile, nav: e.target.value })}
            />
          </label>
          <label className="field">
            Invested ₹ (optional)
            <input
              type="number"
              step="any"
              value={reconcile.invested_amount}
              onChange={(e) => setReconcile({ ...reconcile, invested_amount: e.target.value })}
            />
          </label>
          <button className="btn btn-sm" type="submit" disabled={!!busy || !positions.length}>
            Reconcile
          </button>
        </form>
      </section>
    </>
  )
}
