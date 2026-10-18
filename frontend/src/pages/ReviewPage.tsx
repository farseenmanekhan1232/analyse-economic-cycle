import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, inr, pct } from '../api'
import type { PortfolioSummary, Position, ReviewSession } from '../types'
import { TrafficDot } from '../components/TrafficDot'

type DecisionMap = Record<string, { decision: string; reason: string }>

export function ReviewPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [reviews, setReviews] = useState<ReviewSession[]>([])
  const [cycle, setCycle] = useState({ current_phase: '', current_sub_phase: '' })
  const [lastReview, setLastReview] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<DecisionMap>({})
  const [notes, setNotes] = useState('')
  const [result, setResult] = useState<ReviewSession | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<{
        reviews: ReviewSession[]
        positions: Position[]
        summary: PortfolioSummary
        last_review: string | null
        cycle: { current_phase: string; current_sub_phase: string }
      }>('/api/os/reviews')
      .then((d) => {
        setReviews(d.reviews)
        setPositions(d.positions)
        setSummary(d.summary)
        setLastReview(d.last_review)
        setCycle(d.cycle)
        const map: DecisionMap = {}
        d.positions.forEach((p) => {
          map[p.id] = { decision: 'keep', reason: '' }
        })
        setDecisions(map)
      })
      .catch((e) => setError(e.message))
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const body = {
        notes,
        decisions: positions.map((p) => ({
          position_id: p.id,
          decision: decisions[p.id]?.decision || 'keep',
          reason: decisions[p.id]?.reason || '',
        })),
      }
      const review = await api.post<ReviewSession>('/api/os/reviews', body)
      setResult(review)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Review failed')
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Monthly ritual</p>
          <h1 className="page-title">Review wizard</h1>
          <p className="page-lead">Keep / trim / exit each open position. Leave with a Groww checklist.</p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {result && (
        <section className="panel" style={{ borderColor: 'var(--accent)', marginBottom: '1rem' }}>
          <p className="panel-label">Saved · Do this on Groww today</p>
          {result.action_checklist?.length ? (
            <ul className="alert-list">
              {result.action_checklist.map((c, i) => (
                <li key={i} className="alert-item" style={{ background: 'var(--accent-soft)', color: 'hsl(152 45% 22%)' }}>
                  <strong>{c.action}</strong> {c.instrument}
                  {c.note ? ` — ${c.note}` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No Groww actions — all keeps / extends.</p>
          )}
        </section>
      )}

      <section className="panel">
        <p className="panel-label">1 · Snapshot</p>
        {summary && (
          <p style={{ margin: 0 }}>
            Book value {inr(summary.total_value)} · P&amp;L {pct(summary.pnl_pct)} · Satellite{' '}
            {summary.satellite_pct}%
          </p>
        )}
        {lastReview && <p className="muted">Last review: {lastReview}</p>}
      </section>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">2 · Cycle</p>
        <p style={{ margin: 0 }}>
          {cycle.current_phase ? (
            <>
              Phase <strong>{cycle.current_phase}</strong> / {cycle.current_sub_phase || '—'}
            </>
          ) : (
            <>
              No cached cycle — <a href="http://127.0.0.1:8000/dashboard">run analysis</a> if you want
              phase context.
            </>
          )}
        </p>
      </section>

      {positions.length === 0 ? (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <div className="empty">
            No open positions. <Link to="/positions/new">Add some</Link> first.
          </div>
        </section>
      ) : (
        <form className="panel" style={{ marginTop: '1rem' }} onSubmit={onSubmit}>
          <p className="panel-label">3 · Each position</p>
          {positions.map((p) => (
            <div
              key={p.id}
              style={{
                padding: '1rem 0',
                borderBottom: '1px solid var(--border)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <Link to={`/positions/${p.id}`} style={{ fontWeight: 500 }}>
                    {p.instrument}
                  </Link>
                  <div className="muted">
                    {pct(p.pnl_pct)} · day {p.days_held} · exit {p.exit_by_date?.slice(0, 10) || '—'}{' '}
                    · <TrafficDot value={p.traffic} label={p.status} />
                  </div>
                </div>
                <select
                  value={decisions[p.id]?.decision || 'keep'}
                  onChange={(e) =>
                    setDecisions({
                      ...decisions,
                      [p.id]: { ...decisions[p.id], decision: e.target.value },
                    })
                  }
                >
                  <option value="keep">Keep</option>
                  <option value="trim">Trim</option>
                  <option value="exit">Exit</option>
                  <option value="extend">Extend horizon</option>
                </select>
              </div>
              <input
                style={{ marginTop: '0.5rem', width: '100%' }}
                placeholder="One-line reason"
                value={decisions[p.id]?.reason || ''}
                onChange={(e) =>
                  setDecisions({
                    ...decisions,
                    [p.id]: { ...decisions[p.id], reason: e.target.value },
                  })
                }
              />
            </div>
          ))}

          <p className="panel-label" style={{ marginTop: '1.5rem' }}>
            4 · Notes
          </p>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional journal note" />

          <button className="btn" type="submit" style={{ marginTop: '1.5rem' }}>
            5 · Save review &amp; Groww checklist
          </button>
        </form>
      )}

      {reviews.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Past reviews</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Phase</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.review_date}</td>
                    <td>{r.cycle_sub_phase || r.cycle_phase || '—'}</td>
                    <td className="muted">{(r.notes || '').slice(0, 80)}</td>
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
