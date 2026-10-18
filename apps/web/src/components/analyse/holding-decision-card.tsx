'use client'

import { useState, type Dispatch, type SetStateAction } from 'react'
import { Badge } from '@/components/ui/badge'
import { TradeRange } from '@/components/analyse/trade-range'
import { InstrumentLabel } from '@/components/instrument-label'
import { inr, pct, type DiffResponse } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { exitHorizonForRow } from '@/lib/exit-horizon'

export type ActionChoice = 'keep' | 'sell' | 'buy' | 'extend' | 'review'
type DiffRow = DiffResponse['rows'][number]

function levelsBadge(action: string | undefined) {
  if (action === 'exit') return { label: 'Exit', variant: 'destructive' as const }
  if (action === 'tighten') return { label: 'Tighten', variant: 'default' as const }
  if (action === 'review') return { label: 'Review', variant: 'outline' as const }
  if (action === 'hold') return { label: 'Hold', variant: 'secondary' as const }
  return null
}

export function HoldingDecisionCard({
  row,
  action,
  setActions,
  allowReview,
  muted,
}: {
  row: DiffRow
  action: ActionChoice
  setActions: Dispatch<SetStateAction<Record<string, ActionChoice>>>
  allowReview?: boolean
  muted?: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const id = row.holding.id
  const proposed = row.proposal.proposed_hold_until
  const badge = levelsBadge(row.trade_levels?.action)
  const horizon = exitHorizonForRow(row)
  const rationale = row.proposal.rationale || ''

  return (
    <article
      id={`holding-${id}`}
      className={`scroll-mt-24 rounded-lg border px-4 py-3 ${muted ? 'opacity-80' : 'bg-card'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-medium leading-snug">
              <InstrumentLabel name={row.holding.instrument} symbol={row.holding.symbol} />
            </h3>
            {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
            {row.plan_stale && <Badge variant="outline">date outdated</Badge>}
            {row.trade_levels?.price_stale && (
              <Badge variant="outline">price may be stale</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {(row.holding.sector || '—').replace(/_/g, ' ')} · {pct(row.holding.pnl_pct)} ·{' '}
            {inr(row.holding.market_value)} · act {horizon.label}
          </p>
          <p className="text-sm">{row.proposal.label}</p>
          {rationale && (
            <p className={`text-xs leading-relaxed text-muted-foreground ${expanded ? '' : 'line-clamp-2'}`}>
              {rationale}
            </p>
          )}
          {rationale.length > 120 && (
            <button
              type="button"
              className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Less' : 'More'}
            </button>
          )}
        </div>
        <div className="flex w-full flex-col gap-1.5 sm:w-44">
          <label className="text-[11px] font-medium text-muted-foreground">Your call</label>
          <select
            className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            value={action}
            onChange={(e) =>
              setActions((a) => ({ ...a, [id]: e.target.value as ActionChoice }))
            }
          >
            {allowReview && <option value="review">Fix sector first</option>}
            <option value="keep">Keep as-is</option>
            <option value="extend">Update hold-until date</option>
            <option value="sell">Sell on Groww</option>
          </select>
          {(action === 'extend' ||
            (action === 'keep' && proposed && proposed !== row.holding.hold_until)) &&
            proposed && (
              <span className="text-xs text-muted-foreground">
                New date: {formatDate(proposed)}
              </span>
            )}
          <span className="text-[11px] text-muted-foreground">
            Until {formatDate(row.holding.hold_until)}
          </span>
        </div>
      </div>
      {row.trade_levels && (
        <div className="mt-3 border-t pt-3">
          <TradeRange levels={row.trade_levels} />
        </div>
      )}
    </article>
  )
}
