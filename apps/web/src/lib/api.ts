export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail || JSON.stringify(j)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export function inr(n: number) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(n)
}

export function pct(n: number) {
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

export type Holding = {
  id: string
  instrument: string
  /** NSE ticker, AMFI code, or short search id when known */
  symbol?: string | null
  asset_class: string
  sector: string
  sector_id?: string | null
  units: number
  invested_amount: number
  market_value: number
  hold_until: string | null
  reason: string
  status: string
  pnl: number
  pnl_pct: number
  needs_plan: boolean
  needs_id_review?: boolean
  missing_from_sync: boolean
  instrument_id?: string | null
  scheme_code?: string | null
  external_key?: string | null
  opened_by_run_id?: string | null
  last_reviewed_run_id?: string | null
}

export type SectorRow = {
  sector: string
  sector_id?: string
  score: number
  rating: string
  hold_months_lo: number
  hold_months_hi: number
  hold_for?: string
  stop_loss_pct?: number
  exit_triggers?: string
  rank?: number
  why?: string
  recommended: boolean
  recent?: number
}

export type FundPick = {
  instrument_id?: string
  symbol?: string
  name: string
  ltp?: number
  change_pct?: number
  nav?: number
  amc?: string
  kind?: 'new' | 'previously_sold'
}

export type SectorPicks = {
  etfs?: FundPick[]
  mfs?: FundPick[]
  stocks?: FundPick[]
}

export type BuyIdea = {
  instrument_id?: string
  instrument: string
  asset_class: string
  sector: string
  sector_id?: string | null
  symbol?: string | null
  kind: 'new' | 'previously_sold'
  score: number
  prev_score?: number | null
  rating?: string
  hold_months_lo?: number
  hold_months_hi?: number
  proposed_hold_until: string
  suggested: string
  label: string
  rationale?: string
  closed_at?: string | null
  holding_id?: string
  ltp?: number
  nav?: number
  overweight_warning?: boolean
  sector_weight?: number
  sector_open_count?: number
}

export type AnalysisRun = {
  id: string
  ran_at: string | null
  phase: string
  sub_phase: string
  sub_phase_desc?: string
  progress?: number
  market_story: string
  methodology_note?: string
  risk_label?: string
  sectors: SectorRow[]
  fund_picks?: Record<string, SectorPicks>
  recommendations?: string[]
  top_sectors?: Array<{ sector: string; final_weight?: number }>
  investments?: Array<{ sector: string; pct: number }>
  exit_watch?: Array<{
    sector: string
    hold_for?: string
    exit_trigger?: string
    stop_loss_pct?: number
  }>
  last_run?: string
}

export type MatchInfo = {
  holding_sector_id: string | null
  matched_score_sector_id: string | null
  matched_score: number | null
  match_confidence: 'exact' | 'alias' | 'none' | string
}

export type Calibration = {
  caveat: string
  n_calls: number
  hit_rate: number | null
  avg_return: number | null
  by_band: Record<string, { n: number; hits: number; avg_return: number; hit_rate: number | null }>
  windows: Record<string, { n: number; hit_rate: number | null; avg_return: number | null }>
  recent_calls: Array<{
    run_id: string
    ran_at: string
    sector: string
    score: number
    rating: string
    return_pct: number
    window_days: number
    hit: boolean
  }>
  data_available: boolean
}

export type SyncFreshness = {
  last_stocks_sync_at: string | null
  last_mf_sync_at: string | null
  stocks_stale: boolean
  mf_stale: boolean
  stocks_age_days: number | null
  mf_age_days: number | null
}

export type PortfolioSummary = {
  position_count: number
  total_invested: number
  total_value: number
  pnl: number
  pnl_pct: number
  due_count: number
  needs_plan_count: number
  sync: {
    last_stocks_sync_at: string | null
    last_mf_sync_at: string | null
    notes?: string
  }
}

export type HoldingsResponse = {
  holdings: Holding[]
  summary: PortfolioSummary
}

export type TradeLevels = {
  entry: number | null
  current: number | null
  stop_price: number | null
  target_price: number | null
  stop_pct: number
  target_pct: number
  pnl_pct: number | null
  cushion_pct: number | null
  r_remaining: number | null
  time_used_pct: number | null
  price_stale: boolean
  price_as_of: string | null
  action: 'exit' | 'tighten' | 'hold' | 'review' | string
  label: string
  rationale: string
  hold_for_context?: string | null
}

export type DiffResponse = {
  run: AnalysisRun | null
  rows: Array<{
    holding: Holding
    sector_score: {
      sector: string
      sector_id?: string | null
      score: number
      rating: string
      hold_months_lo: number
      hold_months_hi: number
      stop_loss_pct?: number
      exit_triggers: string
      prev_score?: number | null
    } | null
    match?: MatchInfo
    plan_stale?: boolean
    trade_levels?: TradeLevels
    proposal: {
      suggested: string
      label: string
      rationale: string
      proposed_hold_until: string | null
    }
  }>
  buy_ideas: BuyIdea[]
  fund_picks_filtered?: Record<string, SectorPicks>
  due_count: number
  unmapped_count?: number
  sync_freshness?: SyncFreshness
  calibration?: Calibration | null
  join_debug?: Array<Record<string, unknown>>
  sector_registry?: Array<{
    id: string
    display_name: string
    aliases: string[]
    kite_index?: string | null
    equivalents: string[]
  }>
}

export type PipelineStatus = {
  done: boolean
  step: string
  progress: number
  error: string | null
}

export type KiteStatus = {
  connected: boolean
  login_url: string
}
