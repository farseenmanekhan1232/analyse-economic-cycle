import type { Holding, SyncFreshness } from './api'

const PHARMA = new Set(['PHARMA', 'HEALTHCARE'])
const ENERGY = new Set(['ENERGY', 'OIL_GAS'])
const BANKS = new Set(['BANK', 'PVT_BANK', 'PSU_BANK'])
const CONSUMER = new Set(['AUTO', 'FMCG', 'CONSUMER_DURABLES'])
const IT_MEDIA = new Set(['IT', 'MEDIA'])

export type ExposureCluster = {
  label: string
  value: number
  weight: number
  count: number
}

export function displayFundName(name: string): string {
  return name
    .replace(/\s+(Direct|Regular)( Plan)?( -)? Growth$/i, '')
    .replace(/\s+Direct Plan Growth$/i, '')
    .trim()
}

export function isSystemNote(value: string | null | undefined): boolean {
  const note = (value || '').trim().toLowerCase()
  if (!note) return false
  return (
    note === 'keep' ||
    note === 'saved hold date is out of date' ||
    note.startsWith('thesis weak') ||
    note.startsWith('score looks weak') ||
    note.startsWith('hold — levels still work') ||
    note.startsWith('hold - levels still work') ||
    note.startsWith('held — levels still work')
  )
}

function normalizeSector(value: string | null | undefined): string {
  return (value || '').trim().toUpperCase().replace(/[\s-]+/g, '_')
}

export function clusterLabel(holding: Holding): string {
  const sector = normalizeSector(holding.sector_id || holding.sector)
  const name = holding.instrument.toLowerCase()

  if (PHARMA.has(sector)) return 'Pharma'
  if (ENERGY.has(sector)) return 'Energy'
  if (BANKS.has(sector)) return 'Banks'
  if (CONSUMER.has(sector)) return 'Consumer'
  if (IT_MEDIA.has(sector)) return 'IT & Media'
  if (sector === 'METAL') return 'Metals'
  if (sector === 'REALTY') return 'Realty'
  if (sector === 'INFRA') return 'Infra'
  if (name.includes('flexi cap')) return 'Flexi Cap'
  return 'Other'
}

export function exposureClusters(holdings: Holding[]): ExposureCluster[] {
  const total = holdings.reduce((sum, holding) => sum + Math.max(0, holding.market_value), 0)
  const byLabel = new Map<string, ExposureCluster>()

  for (const holding of holdings) {
    const label = clusterLabel(holding)
    const current = byLabel.get(label) || { label, value: 0, weight: 0, count: 0 }
    current.value += Math.max(0, holding.market_value)
    current.count += 1
    byLabel.set(label, current)
  }

  return [...byLabel.values()]
    .map((cluster) => ({
      ...cluster,
      weight: total > 0 ? cluster.value / total : 0,
    }))
    .sort((a, b) => b.value - a.value)
}

export function nextReviewDate(holdings: Holding[]): string | null {
  const dates = holdings
    .map((holding) => holding.hold_until)
    .filter((value): value is string => Boolean(value))
    .sort()
  return dates[0] || null
}

export function holdingWeight(holding: Holding, holdings: Holding[]): number {
  const total = holdings.reduce((sum, row) => sum + Math.max(0, row.market_value), 0)
  return total > 0 ? Math.max(0, holding.market_value) / total : 0
}

export function needsPlan(holding: Holding): boolean {
  return Boolean(holding.needs_plan || !holding.hold_until)
}

export function isBroadMarketFund(holding: Holding): boolean {
  const text = `${holding.sector || ''} ${holding.instrument || ''}`.toLowerCase()
  return /flexi cap|multi cap|large cap|mid cap|small cap|balanced advantage|nifty 50|index fund/.test(
    text,
  )
}

export function daysSince(value: string | null | undefined, now = new Date()): number {
  if (!value) return Number.POSITIVE_INFINITY
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return Number.POSITIVE_INFINITY
  const from = new Date(then.getFullYear(), then.getMonth(), then.getDate())
  const to = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.max(0, Math.round((to.getTime() - from.getTime()) / 86_400_000))
}

export function tradingDaysSince(value: string | null | undefined, now = new Date()): number {
  if (!value) return Number.POSITIVE_INFINITY
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return Number.POSITIVE_INFINITY

  const cursor = new Date(then.getFullYear(), then.getMonth(), then.getDate())
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  let days = 0

  while (cursor < end) {
    cursor.setDate(cursor.getDate() + 1)
    const weekday = cursor.getDay()
    if (weekday !== 0 && weekday !== 6) days += 1
  }

  return days
}

export function isAnalysisStale(ranAt: string | null | undefined, now = new Date()): boolean {
  return tradingDaysSince(ranAt, now) > 1
}

export function bookIsFresh(sync: SyncFreshness | null | undefined): boolean {
  if (!sync) return false
  return !sync.stocks_stale && !sync.mf_stale
}

export function ageCopy(days: number): string {
  if (!Number.isFinite(days)) return 'No analysis yet'
  if (days <= 0) return 'Updated today'
  if (days === 1) return '1 day old'
  return `${days} days old`
}

export function decisionRank(action: string): number {
  switch (action.toLowerCase()) {
    case 'sell':
      return 0
    case 'review':
      return 1
    case 'extend':
      return 2
    default:
      return 3
  }
}
