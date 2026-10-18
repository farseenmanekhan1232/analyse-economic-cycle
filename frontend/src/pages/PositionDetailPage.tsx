import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, inr, pct } from '../api'
import type { Position, Transaction } from '../types'
import { TrafficDot } from '../components/TrafficDot'

export function PositionDetailPage() {
  const { id } = useParams()
  const [p, setP] = useState<Position | null>(null)
  const [txs, setTxs] = useState<Transaction[]>([])
  const [cycle, setCycle] = useState({ current_phase: '', current_sub_phase: '' })
  const [error, setError] = useState('')
  const [exitNav, setExitNav] = useState('')
  const [outcome, setOutcome] = useState('thesis_right')
  const [note, setNote] = useState('')
  const [nav, setNav] = useState('')

  const load = useCallback(() => {
    if (!id) return
    api
      .get<{ position: Position; transactions: Transaction[]; cycle: typeof cycle }>(
        `/api/os/positions/${id}`,
      )
      .then((d) => {
        setP(d.position)
        setTxs(d.transactions)
        setCycle(d.cycle)
      })
      .catch((e) => setError(e.message))
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  async function act(path: string, body?: unknown) {
    setError('')
    try {
      await api.post(path, body)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed')
    }
  }

  if (!p && !error) return <div className="skeleton" style={{ height: 32, width: '50%' }} />
  if (error && !p) return <div className="error-banner">{error}</div>
  if (!p) return null

  const trafficColor =
    p.traffic === 'green' ? 'var(--success)' : p.traffic === 'red' ? 'var(--danger)' : 'var(--warning)'

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">
            <Link to="/positions" className="muted">
              ← Positions
            </Link>
          </p>
          <h1 className="page-title">{p.instrument}</h1>
          <p className="page-lead">
            {p.sector || '—'} · {p.sleeve} · {p.asset_class} ·{' '}
            <TrafficDot value={p.traffic} label={p.status} />
          </p>
        </div>
        <Link className="btn btn-ghost" to={`/positions/${p.id}/edit`}>
          Edit
        </Link>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="grid-2">
        <section className="panel">
          <p className="panel-label">Am I on track?</p>
          <p style={{ margin: 0, fontSize: '1.15rem', fontWeight: 600, color: trafficColor }}>
            {p.next_action}
          </p>
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            {p.horizon_progress < 0.35
              ? `You are ${Math.round(p.horizon_progress * 100)}% through the planned horizon. Early underperformance is common for satellite tilts. Keep unless stop or thesis invalid.`
              : p.traffic === 'red'
                ? 'Past plan or risk rule. Decide: extend with a new thesis, trim, or square off on Groww.'
                : 'Within horizon. Compare plan vs actual before changing size.'}
          </p>
        </section>
        <section className="panel">
          <p className="panel-label">Mark-to-market</p>
          <div className="metric mono">{inr(p.market_value)}</div>
          <p className={p.pnl_pct >= 0 ? 'pos' : 'neg'} style={{ margin: '0.35rem 0 0' }}>
            {pct(p.pnl_pct)} ({inr(p.pnl)})
          </p>
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            {p.units.toFixed(4)} units · NAV {p.last_nav ?? '—'} · invested {inr(p.invested_amount)}
          </p>
        </section>
      </div>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">Expectation frame</p>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th></th>
                <th>Plan</th>
                <th>Actual</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Horizon</td>
                <td>
                  {p.horizon_months_lo}–{p.horizon_months_hi} months
                </td>
                <td>
                  Day {p.days_held} of ~{p.horizon_months_hi * 30} (
                  {Math.round(p.horizon_progress * 100)}%)
                </td>
              </tr>
              <tr>
                <td>Soft target</td>
                <td>{p.target_return_pct != null ? pct(p.target_return_pct, 0) : '—'}</td>
                <td className={p.pnl_pct >= 0 ? 'pos' : 'neg'}>{pct(p.pnl_pct)}</td>
              </tr>
              <tr>
                <td>Stop</td>
                <td>−{p.stop_loss_pct}%</td>
                <td>{pct(p.pnl_pct)} from entry</td>
              </tr>
              <tr>
                <td>Review / exit</td>
                <td className="mono">
                  {p.review_date?.slice(0, 10) || '—'} / {p.exit_by_date?.slice(0, 10) || '—'}
                </td>
                <td>{p.next_action}</td>
              </tr>
              <tr>
                <td>Thesis still valid?</td>
                <td colSpan={2}>
                  {p.thesis_invalid_if || '—'}
                  {cycle.current_sub_phase ? (
                    <>
                      {' '}
                      · Pulse now: <span className="mono">{cycle.current_sub_phase}</span>
                    </>
                  ) : null}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">Thesis</p>
        <p className="muted" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
          {p.thesis || '—'}
        </p>
      </section>

      {p.status !== 'closed' && (
        <>
          <div className="grid-2" style={{ marginTop: '1rem' }}>
            <section className="panel">
              <p className="panel-label">Mark reviewed</p>
              <p className="muted">Bumps next review +30 days.</p>
              <button className="btn btn-sm" type="button" onClick={() => act(`/api/os/positions/${p.id}/reviewed`)}>
                Mark reviewed
              </button>
            </section>
            <section className="panel">
              <p className="panel-label">Extend horizon</p>
              <p className="muted">Push exit_by +90 days.</p>
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                onClick={() => act(`/api/os/positions/${p.id}/extend`)}
              >
                Extend
              </button>
            </section>
          </div>

          <div className="grid-2" style={{ marginTop: '1rem' }}>
            <form
              className="panel"
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                act(`/api/os/positions/${p.id}/nav`, { nav: Number(nav) })
              }}
            >
              <p className="panel-label">Update NAV / price</p>
              <div className="btn-row" style={{ marginTop: '0.75rem' }}>
                <input
                  type="number"
                  step="any"
                  required
                  placeholder="NAV or LTP"
                  value={nav}
                  onChange={(e) => setNav(e.target.value)}
                  style={{ flex: 1 }}
                />
                <button className="btn btn-sm" type="submit">
                  Update
                </button>
              </div>
              {p.scheme_code && (
                <p className="muted" style={{ marginTop: '0.5rem' }}>
                  Or{' '}
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => act(`/api/os/positions/${p.id}/refresh-nav`)}
                  >
                    fetch public NAV
                  </button>
                </p>
              )}
            </form>

            <form
              className="panel"
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                act(`/api/os/positions/${p.id}/close`, {
                  exit_nav: Number(exitNav),
                  outcome_tags: outcome,
                  note,
                })
              }}
            >
              <p className="panel-label">Close position</p>
              <label className="field" style={{ marginTop: '0.5rem' }}>
                Exit NAV/price
                <input
                  type="number"
                  step="any"
                  required
                  value={exitNav}
                  onChange={(e) => setExitNav(e.target.value)}
                />
              </label>
              <label className="field" style={{ marginTop: '0.5rem' }}>
                Postmortem
                <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                  <option value="thesis_right">thesis_right</option>
                  <option value="thesis_early">thesis_early</option>
                  <option value="thesis_wrong">thesis_wrong</option>
                  <option value="exited_late">exited_late</option>
                  <option value="exited_early">exited_early</option>
                </select>
              </label>
              <label className="field" style={{ marginTop: '0.5rem' }}>
                Note
                <input value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
              <button className="btn btn-sm btn-danger" type="submit" style={{ marginTop: '0.75rem' }}>
                Close
              </button>
            </form>
          </div>
        </>
      )}

      {txs.length > 0 && (
        <section className="panel" style={{ marginTop: '1rem' }}>
          <p className="panel-label">Transactions</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Amount</th>
                  <th>Units</th>
                  <th>NAV</th>
                </tr>
              </thead>
              <tbody>
                {txs.map((t) => (
                  <tr key={t.id}>
                    <td className="mono">{t.tx_date}</td>
                    <td>{t.tx_type}</td>
                    <td>{inr(t.amount || 0)}</td>
                    <td className="mono">{(t.units || 0).toFixed(4)}</td>
                    <td className="mono">{t.nav ?? '—'}</td>
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
