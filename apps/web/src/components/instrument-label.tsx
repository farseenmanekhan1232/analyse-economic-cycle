import { cn } from '@/lib/utils'

/** Prefer NSE ticker / AMFI code for Groww search; name as secondary. */
export function instrumentLabelText(
  name: string | null | undefined,
  symbol?: string | null,
): string {
  const n = (name || '').trim()
  const s = (symbol || '').trim()
  if (s && n && s.toUpperCase() !== n.toUpperCase()) return `${s} · ${n}`
  return s || n || '—'
}

export function InstrumentLabel({
  name,
  symbol,
  className,
  nameClassName,
  mono = true,
}: {
  name?: string | null
  symbol?: string | null
  className?: string
  nameClassName?: string
  /** Monospace ticker (default). */
  mono?: boolean
}) {
  const s = (symbol || '').trim()
  const n = (name || '').trim()
  if (!s && !n) return <span className={className}>—</span>
  if (!s || s.toUpperCase() === n.toUpperCase()) {
    return (
      <span className={cn(mono && s ? 'font-mono tracking-tight' : undefined, className)}>
        {s || n}
      </span>
    )
  }
  return (
    <span className={className}>
      <span className={cn(mono && 'font-mono tracking-tight', 'font-medium')}>{s}</span>
      <span className={cn('font-normal text-muted-foreground', nameClassName)}> · {n}</span>
    </span>
  )
}
