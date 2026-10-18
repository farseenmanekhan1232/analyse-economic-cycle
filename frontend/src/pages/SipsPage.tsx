import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, inr } from '../api'
import type { Position, Sip } from '../types'

export function SipsPage() {
  const [sips, setSips] = useState<Sip[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    position_id: '',
    amount: '5000',
    sip_day: '5',
    start_date: '',
  })

  function load() {
    api
      .get<{ sips: Sip[]; positions: Position[] }>('/api/os/sips')
      .then((d) => {
        setSips(d.sips)
        setPositions(d.positions.filter((p) => p.asset_class === 'mf'))
        if (!form.position_id && d.positions[0]) {
          const mf = d.positions.find((p) => p.asset_class === 'mf')
          if (mf) setForm((f) => ({ ...f, position_id: mf.id }))
        }
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await api.post('/api/os/sips', {
        position_id: form.position_id,
        amount: Number(form.amount),
        sip_day: Number(form.sip_day),
        start_date: form.start_date,
      })
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">SIP registry</p>
          <h1 className="page-title">Configure once</h1>
          <p className="page-lead">
            Each month the OS credits units from public NAV. No Groww XLSX export.
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <form className="panel" onSubmit={onCreate}>
        <p className="panel-label">Add SIP</p>
        <div className="form-grid">
          <label className="field">
            Position
            <select
              required
              value={form.position_id}
              onChange={(e) => setForm({ ...form, position_id: e.target.value })}
            >
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.instrument}
                  {!p.scheme_code ? ' (add scheme code!)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Amount ₹
            <input
              type="number"
              required
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
            />
          </label>
          <label className="field">
            SIP day (1–28)
            <input
              type="number"
              min={1}
              max={28}
              required
              value={form.sip_day}
              onChange={(e) => setForm({ ...form, sip_day: e.target.value })}
            />
          </label>
          <label className="field">
            Start date
            <input
              type="date"
              required
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            />
          </label>
        </div>
        <button className="btn btn-sm" type="submit" style={{ marginTop: '1rem' }} disabled={!positions.length}>
          Save SIP
        </button>
      </form>

      <section className="panel" style={{ marginTop: '1rem' }}>
        <p className="panel-label">Active SIPs</p>
        {sips.length === 0 ? (
          <div className="empty">No SIPs yet. Create MF positions first, then register each SIP once.</div>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Fund</th>
                  <th>Amount</th>
                  <th>Day</th>
                  <th>Start</th>
                  <th>Last credited</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sips.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {s.instrument}
                      <div className="muted">{s.scheme_code || 'missing scheme code'}</div>
                    </td>
                    <td className="mono">{inr(s.amount)}</td>
                    <td className="mono">{s.sip_day}</td>
                    <td className="mono">{s.start_date}</td>
                    <td className="mono">{s.last_credited_date || '—'}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-ghost"
                        style={{ color: 'var(--danger)' }}
                        onClick={async () => {
                          await api.post(`/api/os/sips/${s.id}/deactivate`)
                          load()
                        }}
                      >
                        Stop
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
