export type Traffic = 'green' | 'amber' | 'red' | 'neutral'

export interface Position {
  id: string
  instrument: string
  asset_class: string
  scheme_code?: string | null
  sector: string
  sleeve: string
  units: number
  avg_cost: number
  invested_amount: number
  entry_date?: string | null
  thesis: string
  horizon_months_lo: number
  horizon_months_hi: number
  target_return_pct?: number | null
  benchmark?: string
  review_date?: string | null
  exit_by_date?: string | null
  stop_loss_pct: number
  take_profit_pct?: number | null
  thesis_invalid_if?: string
  status: string
  last_nav?: number | null
  last_nav_date?: string | null
  market_value: number
  notes?: string
  outcome_tags?: string
  closed_at?: string | null
  pnl: number
  pnl_pct: number
  days_held: number
  horizon_progress: number
  traffic: Traffic
  next_action: string
}

export interface PortfolioSummary {
  total_invested: number
  total_value: number
  pnl: number
  pnl_pct: number
  core_value: number
  satellite_value: number
  core_pct: number
  satellite_pct: number
  by_sector: Record<string, number>
  position_count: number
}

export interface HomeResponse {
  summary: PortfolioSummary
  attention: Position[]
  alerts: string[]
  calibration: {
    total_closed: number
    tags: Record<string, number>
    exited_late: number
  }
  cycle: { current_phase: string; current_sub_phase: string }
  last_review: string | null
}

export interface Sip {
  id: string
  position_id: string
  amount: number
  sip_day: number
  start_date: string
  last_credited_date?: string | null
  active: number
  instrument?: string
  scheme_code?: string
  sector?: string
}

export interface ReviewSession {
  id: string
  review_date: string
  cycle_phase: string
  cycle_sub_phase: string
  notes: string
  action_checklist: Array<{ action: string; instrument: string; note?: string }>
  decisions?: Array<{
    position_id: string
    decision: string
    reason: string
    instrument?: string
  }>
}

export interface Snapshot {
  id: string
  snapshot_date: string
  total_value: number
  total_invested: number
  core_value: number
  satellite_value: number
}

export interface Transaction {
  id: string
  position_id: string
  tx_type: string
  tx_date: string
  amount?: number
  units?: number
  nav?: number
  note?: string
}
