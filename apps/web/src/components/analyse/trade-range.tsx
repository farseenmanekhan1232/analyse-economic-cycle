'use client'

import type { TradeLevels } from '@/lib/api'

function inrPrice(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(n)
}

/** CSS track: stop · entry · now · target */
export function TradeRange({ levels }: { levels: TradeLevels }) {
  const { entry, current, stop_price: stop, target_price: target } = levels
  if (entry == null || current == null || stop == null || target == null) {
    return (
      <p className="text-xs text-muted-foreground">
        Entry {inrPrice(entry)} · Now {inrPrice(current)} · Stop {inrPrice(stop)} · Target{' '}
        {inrPrice(target)}
      </p>
    )
  }

  const lo = Math.min(stop, entry, current, target)
  const hi = Math.max(stop, entry, current, target)
  const span = hi - lo || 1
  const pct = (v: number) => `${((v - lo) / span) * 100}%`

  return (
    <div className="space-y-2">
      <div className="relative h-3 w-full rounded-full bg-muted">
        <div
          className="absolute inset-y-0 rounded-full bg-primary/15"
          style={{ left: pct(stop), width: `calc(${pct(target)} - ${pct(stop)})` }}
        />
        {/* stop */}
        <span
          className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-destructive"
          style={{ left: pct(stop) }}
          title={`Stop ${inrPrice(stop)}`}
        />
        {/* entry */}
        <span
          className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-foreground bg-background"
          style={{ left: pct(entry) }}
          title={`Entry ${inrPrice(entry)}`}
        />
        {/* now */}
        <span
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-background"
          style={{ left: pct(current) }}
          title={`Now ${inrPrice(current)}`}
        />
        {/* target */}
        <span
          className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-600"
          style={{ left: pct(target) }}
          title={`Target ${inrPrice(target)}`}
        />
      </div>
      <div className="flex justify-between gap-2 text-[10px] text-muted-foreground">
        <span>Stop {inrPrice(stop)}</span>
        <span>Now {inrPrice(current)}</span>
        <span>Target {inrPrice(target)}</span>
      </div>
    </div>
  )
}
