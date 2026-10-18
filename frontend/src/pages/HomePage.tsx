import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, inr, pct } from '../api'
import type { HomeResponse } from '../types'
import { TrafficDot } from '../components/TrafficDot'

export function HomePage() {
  const [data, setData] = useState<HomeResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<HomeResponse>('/api/os/home')
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="error-banner">{error}</div>
  if (!data) {
    return (
      <div className="stack">
        <div className="skeleton" style={{ width: '40%', height: 28 }} />
        <div className="skeleton" style={{ width: '60%', height: 16, marginTop: 12 }} />
      </div>
    )
  }

  const { summary, attention, alerts, calibration, cycle } = data

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Pulse OS</p>
          <h1 className="page-title">What needs me today?</h1>
          <p className="page-lead">
            Open book first. Cycle scores second.
            {cycle.current_sub_phase ? (
              <>
                {' '}
                Pulse now: <span className="mono">{cycle.current_sub_phase.replace(/_/g, ' ')}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="btn-row">
          <Link className="btn" to="/review">
            Monthly review
          </Link>
          <Link className="btn btn-ghost" to="/positions/new">
            Add position
          </Link>
        </div>
      </header>

      {alerts.length > 0 && (
        <ul className="alert-list" style={{ marginBottom: '1.5rem' }}>
          {alerts.map((a) => (
            <li key={a} className="alert-item">
              {a}
            </li>
          ))}
        </ul>
      )}

      <div className="grid-2">
        <section className="panel">
          <p className="panel-label">Portfolio</p>
          <div className="metric mono">{inr(summary.total_value)}</div>
          <p className={summary.pnl >= 0 ? 'pos' : 'neg'} style={{ margin: '0.35rem 0 0' }}>
            {pct(summary.pnl_pct)} · invested {inr(summary.total_invested)}
          </p>
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            Core {summary.core_pct}% · Satellite {summary.satellite_pct}%
          </p>
        </section>
        <section className="panel">
          <p className="panel-label">Open positions</p>
          <div className="metric mono">{summary.position_count}</div>
          <p className="muted" style={{ marginTop: '0.35rem' }}>
            {attention.length} need attention
          </p>
        </section>
      </div>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">Needs attention</p>
        {attention.length === 0 ? (
          <div className="empty">
            {summary.position_count === 0 ? (
              <>
                No open positions yet.{' '}
                <Link to="/positions/new">Seed last month’s Pulse buys</Link> so the OS owns your
                book.
              </>
            ) : (
              'Nothing urgent. All open positions are within plan.'
            )}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Status</th>
                  <th>P&amp;L</th>
                  <th>Exit by</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {attention.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/positions/${p.id}`}>{p.instrument}</Link>
                      <div className="muted">
                        {p.sector || '—'} · {p.sleeve}
                      </div>
                    </td>
                    <td>
                      <TrafficDot value={p.traffic} label={p.status} />
                    </td>
                    <td className={p.pnl_pct >= 0 ? 'pos' : 'neg'}>{pct(p.pnl_pct)}</td>
                    <td className="mono">{p.exit_by_date?.slice(0, 10) || '—'}</td>
                    <td className="muted">{p.next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {calibration.total_closed > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Calibration</p>
          <p className="muted" style={{ margin: 0 }}>
            {calibration.total_closed} closed
            {Object.entries(calibration.tags).map(([tag, n]) => (
              <span key={tag}>
                {' '}
                · {tag}: {n}
              </span>
            ))}
            {calibration.exited_late ? ` · exited late: ${calibration.exited_late}` : null}
          </p>
        </section>
      )}
    </>
  )
}
