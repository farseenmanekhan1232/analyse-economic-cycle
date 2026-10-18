import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, pct } from '../api'
import type { Position } from '../types'
import { TrafficDot } from '../components/TrafficDot'

export function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [closed, setClosed] = useState<Position[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<{ positions: Position[]; closed: Position[] }>('/api/os/positions?include_closed=true')
      .then((d) => {
        setPositions(d.positions)
        setClosed(d.closed)
      })
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="error-banner">{error}</div>

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Position book</p>
          <h1 className="page-title">Open positions</h1>
          <p className="page-lead">Thesis, exits, and review dates — living objects, not tips.</p>
        </div>
        <Link className="btn" to="/positions/new">
          Add position
        </Link>
      </header>

      <section className="panel">
        {positions.length === 0 ? (
          <div className="empty">
            Empty book. <Link to="/positions/new">Seed the funds/ETFs</Link> you bought from last
            month’s Pulse run.
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Sleeve</th>
                  <th>P&amp;L</th>
                  <th>Days</th>
                  <th>Exit by</th>
                  <th>Status</th>
                  <th>Next</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/positions/${p.id}`}>{p.instrument}</Link>
                      <div className="muted">{p.sector || '—'}</div>
                    </td>
                    <td>{p.sleeve}</td>
                    <td className={p.pnl_pct >= 0 ? 'pos' : 'neg'}>{pct(p.pnl_pct)}</td>
                    <td className="mono">{p.days_held}</td>
                    <td className="mono">{p.exit_by_date?.slice(0, 10) || '—'}</td>
                    <td>
                      <TrafficDot value={p.traffic} label={p.status} />
                    </td>
                    <td className="muted">{p.next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {closed.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Closed</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th>Outcome</th>
                  <th>Closed</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/positions/${p.id}`}>{p.instrument}</Link>
                    </td>
                    <td className="muted">{p.outcome_tags || '—'}</td>
                    <td className="mono">{p.closed_at?.slice(0, 10) || '—'}</td>
                    <td className={p.pnl_pct >= 0 ? 'pos' : 'neg'}>{pct(p.pnl_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
