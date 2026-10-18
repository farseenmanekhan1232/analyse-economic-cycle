import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import type { Position } from '../types'

const empty = {
  instrument: '',
  thesis: '',
  asset_class: 'mf',
  scheme_code: '',
  sector: '',
  sleeve: 'satellite',
  units: 0,
  invested_amount: 0,
  entry_date: '',
  horizon_months_lo: 6,
  horizon_months_hi: 9,
  target_return_pct: '' as number | '',
  stop_loss_pct: 12,
  take_profit_pct: '' as number | '',
  review_date: '',
  exit_by_date: '',
  thesis_invalid_if: '',
  notes: '',
}

export function PositionFormPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [form, setForm] = useState(empty)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const isEdit = Boolean(id && id !== 'new')

  useEffect(() => {
    if (!isEdit || !id) return
    api
      .get<{ position: Position }>(`/api/os/positions/${id}`)
      .then(({ position: p }) => {
        setForm({
          instrument: p.instrument,
          thesis: p.thesis || '',
          asset_class: p.asset_class,
          scheme_code: p.scheme_code || '',
          sector: p.sector || '',
          sleeve: p.sleeve,
          units: p.units,
          invested_amount: p.invested_amount,
          entry_date: p.entry_date?.slice(0, 10) || '',
          horizon_months_lo: p.horizon_months_lo,
          horizon_months_hi: p.horizon_months_hi,
          target_return_pct: p.target_return_pct ?? '',
          stop_loss_pct: p.stop_loss_pct,
          take_profit_pct: p.take_profit_pct ?? '',
          review_date: p.review_date?.slice(0, 10) || '',
          exit_by_date: p.exit_by_date?.slice(0, 10) || '',
          thesis_invalid_if: p.thesis_invalid_if || '',
          notes: p.notes || '',
        })
      })
      .catch((e) => setError(e.message))
  }, [id, isEdit])

  function set<K extends keyof typeof empty>(key: K, value: (typeof empty)[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    const payload = {
      ...form,
      target_return_pct: form.target_return_pct === '' ? null : Number(form.target_return_pct),
      take_profit_pct: form.take_profit_pct === '' ? null : Number(form.take_profit_pct),
      entry_date: form.entry_date || undefined,
      review_date: form.review_date || undefined,
      exit_by_date: form.exit_by_date || undefined,
      scheme_code: form.scheme_code || null,
    }
    try {
      if (isEdit && id) {
        await api.patch(`/api/os/positions/${id}`, payload)
        navigate(`/positions/${id}`)
      } else {
        const created = await api.post<Position>('/api/os/positions', payload)
        navigate(`/positions/${created.id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">
            <Link to="/positions" className="muted">
              ← Positions
            </Link>
          </p>
          <h1 className="page-title">{isEdit ? 'Edit position' : 'New position'}</h1>
          <p className="page-lead">No thesis → no trade. Fill the ticket before Groww.</p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <form className="panel" onSubmit={onSubmit}>
        <div className="form-grid">
          <label className="field full">
            Instrument *
            <input
              required
              value={form.instrument}
              onChange={(e) => set('instrument', e.target.value)}
              placeholder="Nippon India Small Cap — Direct Growth"
            />
          </label>
          <label className="field">
            Asset class
            <select value={form.asset_class} onChange={(e) => set('asset_class', e.target.value)}>
              <option value="mf">mf</option>
              <option value="etf">etf</option>
              <option value="stock">stock</option>
            </select>
          </label>
          <label className="field">
            AMFI / scheme code
            <input
              value={form.scheme_code}
              onChange={(e) => set('scheme_code', e.target.value)}
              placeholder="For public NAV"
            />
          </label>
          <label className="field">
            Sector
            <input value={form.sector} onChange={(e) => set('sector', e.target.value)} />
          </label>
          <label className="field">
            Sleeve
            <select value={form.sleeve} onChange={(e) => set('sleeve', e.target.value)}>
              <option value="satellite">satellite</option>
              <option value="core">core</option>
            </select>
          </label>
          <label className="field">
            Units
            <input
              type="number"
              step="any"
              value={form.units}
              onChange={(e) => set('units', Number(e.target.value))}
            />
          </label>
          <label className="field">
            Invested ₹
            <input
              type="number"
              step="any"
              value={form.invested_amount}
              onChange={(e) => set('invested_amount', Number(e.target.value))}
            />
          </label>
          <label className="field">
            Entry date
            <input
              type="date"
              value={form.entry_date}
              onChange={(e) => set('entry_date', e.target.value)}
            />
          </label>
          <label className="field">
            Horizon lo (months)
            <input
              type="number"
              value={form.horizon_months_lo}
              onChange={(e) => set('horizon_months_lo', Number(e.target.value))}
            />
          </label>
          <label className="field">
            Horizon hi (months)
            <input
              type="number"
              value={form.horizon_months_hi}
              onChange={(e) => set('horizon_months_hi', Number(e.target.value))}
            />
          </label>
          <label className="field">
            Soft target %
            <input
              type="number"
              step="any"
              value={form.target_return_pct}
              onChange={(e) =>
                set('target_return_pct', e.target.value === '' ? '' : Number(e.target.value))
              }
            />
          </label>
          <label className="field">
            Stop loss %
            <input
              type="number"
              step="any"
              value={form.stop_loss_pct}
              onChange={(e) => set('stop_loss_pct', Number(e.target.value))}
            />
          </label>
          <label className="field">
            Review date
            <input
              type="date"
              value={form.review_date}
              onChange={(e) => set('review_date', e.target.value)}
            />
          </label>
          <label className="field">
            Exit by
            <input
              type="date"
              value={form.exit_by_date}
              onChange={(e) => set('exit_by_date', e.target.value)}
            />
          </label>
          <label className="field full">
            Thesis invalid if
            <input
              value={form.thesis_invalid_if}
              onChange={(e) => set('thesis_invalid_if', e.target.value)}
              placeholder="e.g. contraction"
            />
          </label>
          <label className="field full">
            Thesis *
            <textarea
              required
              value={form.thesis}
              onChange={(e) => set('thesis', e.target.value)}
              placeholder="Why this bet, what success looks like, what kills it."
            />
          </label>
          <label className="field full">
            Notes
            <textarea value={form.notes} onChange={(e) => set('notes', e.target.value)} />
          </label>
        </div>
        <div className="btn-row" style={{ marginTop: '1.5rem' }}>
          <button className="btn" type="submit" disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save' : 'Create position'}
          </button>
        </div>
      </form>
    </>
  )
}
