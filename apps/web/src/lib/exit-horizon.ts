import { formatDate } from '@/lib/utils'
import type { DiffResponse, TradeLevels } from '@/lib/api'

export type ExitHorizon = {
  holdingId: string
  name: string
  shortName: string
  action: string
  days: number
  label: string
  sector: string
}

type DiffRow = DiffResponse['rows'][number]

const ACTION_ORDER: Record<string, number> = {
  exit: 0,
  tighten: 1,
  review: 2,
  hold: 3,
}

function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null
  const end = new Date(`${iso.slice(0, 10)}T12:00:00`)
  if (Number.isNaN(end.getTime())) return null
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  return Math.max(0, Math.round((end.getTime() - today.getTime()) / 86400000))
}

function shortName(instrument: string): string {
  const s = (instrument || '').trim()
  if (s.length <= 28) return s
  return `${s.slice(0, 26)}…`
}

/** Prefer ticker for chart axis; keep full name for tooltips. */
export function exitHorizonForRow(row: DiffRow): ExitHorizon {
  const levels: TradeLevels | undefined = row.trade_levels
  const action = (levels?.action || 'hold').toLowerCase()
  // Prefer book date; fall back to this run's proposed review date (new syncs often lack hold_until)
  const reviewIso = row.holding.hold_until || row.proposal?.proposed_hold_until || null
  const untilDays = daysUntil(reviewIso)
  const cushion = levels?.cushion_pct
  const fromProposalOnly = !row.holding.hold_until && !!row.proposal?.proposed_hold_until

  let days = 90
  let label = 'Review later'

  if (action === 'exit') {
    days = 0
    label = 'Now'
  } else if (action === 'tighten') {
    days = untilDays != null ? Math.min(14, untilDays) : 14
    label = days <= 1 ? 'Now' : days <= 14 ? '~2 weeks' : `by ${formatDate(reviewIso)}`
  } else if (action === 'review') {
    days = untilDays != null ? Math.min(7, untilDays) : 7
    label = days <= 1 ? 'Soon' : `within ~${days}d`
  } else {
    // hold
    days = untilDays != null ? untilDays : 90
    if (cushion != null && cushion < 10) {
      days = Math.min(days, 30)
    }
    if (untilDays != null) {
      label = fromProposalOnly
        ? `review by ${formatDate(reviewIso)}`
        : `by ${formatDate(reviewIso)}`
    } else if (cushion != null && cushion < 10) {
      label = 'within ~30d'
    } else {
      label = `~${days}d`
    }
  }

  const ticker = (row.holding.symbol || '').trim()
  const fullName = row.holding.instrument
  const axis = ticker || fullName

  return {
    holdingId: row.holding.id,
    name: ticker && ticker.toUpperCase() !== fullName.toUpperCase()
      ? `${ticker} · ${fullName}`
      : fullName,
    shortName: shortName(axis),
    action,
    days,
    label,
    sector: (row.holding.sector || '').replace(/_/g, ' '),
  }
}

export function exitHorizonsForRows(rows: DiffRow[]): ExitHorizon[] {
  return rows
    .map(exitHorizonForRow)
    .sort((a, b) => {
      const ao = ACTION_ORDER[a.action] ?? 9
      const bo = ACTION_ORDER[b.action] ?? 9
      if (ao !== bo) return ao - bo
      return a.days - b.days
    })
}

export function actionBarColor(action: string): string {
  switch (action) {
    case 'exit':
      return 'hsl(0 72% 51%)'
    case 'tighten':
      return 'hsl(32 95% 44%)'
    case 'review':
      return 'hsl(215 16% 47%)'
    default:
      return 'hsl(142 46% 36%)'
  }
}
