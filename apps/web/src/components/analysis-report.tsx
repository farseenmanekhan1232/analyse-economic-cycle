'use client'

import { useQuery } from '@tanstack/react-query'
import { api, type AnalysisRun, type Calibration, type KiteStatus } from '@/lib/api'
import { cn, formatDate, formatDateTime } from '@/lib/utils'
import { SectorScoreChart } from '@/components/analyse/sector-score-chart'
import { InstrumentLabel } from '@/components/instrument-label'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function KiteConnectBar() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['kite-status'],
    queryFn: () => api<KiteStatus>('/api/kite/status'),
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return <p className="text-xs text-muted-foreground">Checking Kite…</p>
  }

  if (data?.connected) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="inline-block size-1.5 rounded-full bg-emerald-500" />
        <span className="text-muted-foreground">Kite connected</span>
        <button
          type="button"
          className="text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => refetch()}
        >
          refresh
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-amber-700 dark:text-amber-400">Kite not connected</span>
      <a
        href={data?.login_url || 'http://127.0.0.1:8000/login'}
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
      >
        Connect Kite
      </a>
    </div>
  )
}

export function AnalysisReport({
  run,
  calibration,
}: {
  run: AnalysisRun
  calibration?: Calibration | null
}) {
  const fundEntries = Object.entries(run.fund_picks || {}).filter(
    ([, picks]) => (picks.etfs?.length || 0) > 0 || (picks.mfs?.length || 0) > 0,
  )

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">
                Cycle · {run.phase || '—'}
                {run.sub_phase ? ` / ${run.sub_phase.replace(/_/g, ' ')}` : ''}
              </CardTitle>
              <CardDescription className="mt-1.5 max-w-2xl">
                {run.market_story || 'No market story for this run.'}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-1 text-right">
              <Badge variant="secondary">{run.risk_label || 'Risk n/a'}</Badge>
              <span className="text-xs text-muted-foreground">
                {run.id}
                {run.ran_at ? ` · ${formatDateTime(run.ran_at)}` : ''}
              </span>
            </div>
          </div>
          {run.sub_phase_desc && (
            <p className="mt-2 text-sm text-muted-foreground">{run.sub_phase_desc}</p>
          )}
        </CardHeader>
      </Card>

      {calibration && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Track record (sector indices)</CardTitle>
            <CardDescription>{calibration.caveat}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!calibration.data_available ? (
              <p className="text-sm text-muted-foreground">
                Not enough aged Buy/Top Pick calls with index data yet.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Calls </span>
                    <span className="tabular-nums">{calibration.n_calls}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Hit rate </span>
                    <span className="tabular-nums">
                      {calibration.hit_rate != null
                        ? `${Math.round(calibration.hit_rate * 100)}%`
                        : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Avg return </span>
                    <span className="tabular-nums">
                      {calibration.avg_return != null ? `${calibration.avg_return}%` : '—'}
                    </span>
                  </div>
                </div>
                {!!calibration.recent_calls?.length && (
                  <ul className="space-y-1.5 text-xs text-muted-foreground">
                    {calibration.recent_calls.slice(0, 5).map((c) => (
                      <li key={`${c.run_id}-${c.sector}`}>
                        {formatDate(c.ran_at)} · {c.sector} score {Math.round(c.score)} →{' '}
                        <span className={c.hit ? 'text-emerald-700' : 'text-red-700'}>
                          {c.return_pct > 0 ? '+' : ''}
                          {c.return_pct}%
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sector scores</CardTitle>
          <CardDescription>
            Stronger bars are higher conviction this run. Hold ranges are cycle dwell context only —
            square-off uses stop/target on each holding.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SectorScoreChart sectors={run.sectors} />
          <ul className="mt-4 space-y-1.5 text-xs text-muted-foreground">
            {run.sectors
              .filter((s) => s.recommended)
              .slice(0, 5)
              .map((s) => (
                <li key={s.sector}>
                  <span className="font-medium text-foreground">
                    {s.sector.replace(/_/g, ' ')}
                  </span>
                  {s.hold_for ? ` · typical dwell ${s.hold_for}` : ''}
                  {s.why ? ` · ${s.why}` : ''}
                </li>
              ))}
          </ul>
        </CardContent>
      </Card>

      {!!run.exit_watch?.length && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Exit watch (sector context)</CardTitle>
            <CardDescription>
              Invalidation ≈ % from your entry — not a live Groww order. Use the holding trade cards
              above for square-off.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {run.exit_watch.map((e) => (
              <div
                key={e.sector}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b py-2 text-sm last:border-0"
              >
                <span className="font-medium">{e.sector.replace(/_/g, ' ')}</span>
                <span className="max-w-md text-right text-xs text-muted-foreground">
                  {e.hold_for ? `Typical dwell ${e.hold_for}` : ''}
                  {e.stop_loss_pct != null
                    ? ` · invalidation ≈ −${e.stop_loss_pct}% from entry`
                    : ''}
                  {e.exit_trigger ? ` · ${e.exit_trigger}` : ''}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {!!run.investments?.length && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Suggested sector weights</CardTitle>
            <CardDescription>Score-weighted split for new money.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {run.investments.map((inv) => (
              <div key={inv.sector} className="flex items-center gap-3 text-sm">
                <span className="w-28 shrink-0 text-right text-xs">
                  {inv.sector.replace(/_/g, ' ')}
                </span>
                <div className="h-5 flex-1 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full rounded bg-primary/80"
                    style={{ width: `${Math.min(100, Math.round(inv.pct * 100))}%` }}
                  />
                </div>
                <span className="w-12 text-xs tabular-nums">{(inv.pct * 100).toFixed(0)}%</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Suggested ETFs &amp; mutual funds</CardTitle>
          <CardDescription>Catalog gaps vs your open book.</CardDescription>
        </CardHeader>
        <CardContent>
          {!fundEntries.length ? (
            <p className="text-sm text-muted-foreground">No catalog gaps for recommended sectors.</p>
          ) : (
            <div className="grid gap-6 sm:grid-cols-2">
              {fundEntries.map(([sector, picks]) => (
                <div key={sector} className="space-y-2">
                  <h3 className="text-sm font-semibold">{sector.replace(/_/g, ' ')}</h3>
                  <ul className="space-y-1.5">
                    {(picks.etfs || []).map((e) => (
                      <li
                        key={e.instrument_id || `etf-${e.symbol || e.name}`}
                        className="flex items-center justify-between gap-2 text-sm"
                      >
                        <span className="min-w-0 truncate">
                          <Badge variant="outline" className="mr-2">
                            ETF
                          </Badge>
                          {e.symbol || e.name ? (
                            <InstrumentLabel name={e.name} symbol={e.symbol} />
                          ) : (
                            '—'
                          )}
                        </span>
                        <span className="shrink-0 text-xs tabular-nums">
                          {e.ltp != null ? `₹${Number(e.ltp).toFixed(2)}` : '—'}
                        </span>
                      </li>
                    ))}
                    {(picks.mfs || []).map((m) => (
                      <li
                        key={m.instrument_id || `mf-${m.symbol || m.name}`}
                        className="flex items-center justify-between gap-2 text-sm"
                      >
                        <span className="min-w-0 truncate">
                          <Badge variant="secondary" className="mr-2">
                            MF
                          </Badge>
                          {m.symbol || m.name ? (
                            <InstrumentLabel name={m.name} symbol={m.symbol} />
                          ) : (
                            '—'
                          )}
                        </span>
                        <span className="shrink-0 text-xs tabular-nums">
                          {m.nav != null && Number(m.nav) > 0 ? `₹${Number(m.nav).toFixed(2)}` : '—'}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
