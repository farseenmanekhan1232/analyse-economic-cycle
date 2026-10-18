'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { AppNav } from '@/components/app-nav'
import { api } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

type ApproachMeta = { id: string; label: string; summary: string }

type ApproachStat = {
  num_trades: number
  win_rate: number
  expectancy_r: number
  total_pnl: number
}

type BacktestSummary = {
  total_return_pct: number
  win_rate: number
  expectancy_r: number
  max_drawdown_pct: number
  num_trades: number
  ending_capital: number
  approach_stats?: Record<string, ApproachStat>
  equity_curve: Array<{ date: string; equity: number; drawdown_pct: number }>
  recent_trades: Array<{
    symbol: string
    sector: string
    setup: string
    entry_date: string
    exit_date: string | null
    pnl: number
    r_multiple: number
    exit_reason: string | null
  }>
}

type SwingStatus = {
  groww_configured: boolean
  dry_run_default: boolean
  enabled_approaches?: string[]
  approaches?: ApproachMeta[]
  cache_ready?: boolean
  cache_history?: {
    n_symbols?: number
    manifest?: {
      history_start?: string
      history_end?: string
      full_history?: boolean
      interval?: string
      min_bars?: number
    }
  }
  cache_job?: {
    status?: string
    message?: string
    current?: number
    total?: number
    symbol?: string
    full_history?: boolean
  }
  eval_job?: {
    status?: string
    message?: string
    result?: {
      cycle_edge_return_pct?: number
      with_cycle_filter?: BacktestSummary
      baseline_technicals_only?: BacktestSummary
      recommended_disable?: Array<{
        approach: string
        num_trades: number
        expectancy_r: number
      }>
      cache?: { manifest?: { history_start?: string; history_end?: string } }
    }
  }
  calibration?: {
    total_return_pct?: number
    win_rate?: number
    expectancy_r?: number
    max_drawdown_pct?: number
    num_trades?: number
  }
  cloud_hint?: string
}

type BacktestResponse = {
  mode: string
  note?: string
  baseline_note?: string
  elapsed_s?: number
  with_cycle_filter: BacktestSummary
  baseline_technicals_only: BacktestSummary
  cycle_edge_return_pct: number
  cycle_edge_expectancy_r: number
}

type ScanResponse = {
  mode: string
  message?: string
  groww_error?: string
  dry_run?: boolean
  capital?: number
  router?: {
    enabled?: string[]
    eligible_today?: string[]
    phase?: string
    risk_off?: boolean
  }
  regime_hmm?: {
    p_expansion?: number
    p_contraction?: number
    size_multiplier?: number
  }
  bias?: {
    phase?: string
    sub_phase?: string
    score?: number
    progress?: number
    allowed_sectors?: string[]
    risk_off?: boolean
    reason?: string
  }
  setups?: Array<{
    symbol: string
    sector: string
    setup: string
    entry: number
    stop: number
    target: number
    rationale?: string
  }>
  sized?: Array<{
    symbol: string
    sector: string
    setup: string
    entry: number
    stop: number
    target: number
    quantity: number
    notional: number
    risk_rupees: number
    rationale?: string
  }>
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function EquitySpark({ points }: { points: Array<{ equity: number }> }) {
  if (!points.length) return null
  const vals = points.map((p) => p.equity)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const w = 280
  const h = 56
  const d = vals
    .map((v, i) => {
      const x = (i / Math.max(vals.length - 1, 1)) * w
      const y = h - ((v - min) / span) * (h - 4) - 2
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full text-primary" aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

export default function SwingPage() {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [enabled, setEnabled] = useState<string[]>([])

  const { data: status } = useQuery({
    queryKey: ['swing-status'],
    queryFn: () => api<SwingStatus>('/api/swing/status'),
    refetchInterval: (q) => {
      const s = q.state.data
      if (s?.cache_job?.status === 'running' || s?.eval_job?.status === 'running') {
        return 2000
      }
      return false
    },
  })

  useEffect(() => {
    if (status?.enabled_approaches?.length) {
      setEnabled(status.enabled_approaches)
    }
  }, [status?.enabled_approaches])

  const saveApproaches = useMutation({
    mutationFn: (ids: string[]) =>
      api('/api/swing/params', {
        method: 'PATCH',
        body: JSON.stringify({ enabled_approaches: ids }),
      }),
    onSuccess: () => {
      setErr('')
      qc.invalidateQueries({ queryKey: ['swing-status'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  const backtest = useMutation({
    mutationFn: () =>
      api<BacktestResponse>('/api/swing/backtest', {
        method: 'POST',
        body: JSON.stringify({
          capital: 100000,
          quick: true,
          n_days: 220,
          enabled_approaches: enabled,
          demo: !status?.groww_configured && !status?.cache_ready,
        }),
      }),
    onError: (e: Error) => setErr(e.message),
    onSuccess: () => setErr(''),
  })

  const refreshCache = useMutation({
    mutationFn: () =>
      api<{ started: boolean; message: string }>(
        '/api/swing/cache/refresh?full_history=true',
        { method: 'POST' }
      ),
    onSuccess: () => {
      setErr('')
      qc.invalidateQueries({ queryKey: ['swing-status'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  const fullEval = useMutation({
    mutationFn: () =>
      api<{ started: boolean; message: string }>('/api/swing/eval?rebalance=2', {
        method: 'POST',
      }),
    onSuccess: () => {
      setErr('')
      qc.invalidateQueries({ queryKey: ['swing-status'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  const scan = useMutation({
    mutationFn: () => api<ScanResponse>('/api/swing/scan', { method: 'POST' }),
    onError: (e: Error) => setErr(e.message),
    onSuccess: () => setErr(''),
  })

  const bt = backtest.data
  const sc = scan.data
  const cal = status?.calibration
  const approaches = status?.approaches || []

  function toggleApproach(id: string) {
    setEnabled((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <AppNav active="/swing" />
      <main
        id="main-content"
        className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10"
      >
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Research
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">Research</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Strategy experiments and backtests. Research stays separate from the decisions you
            make from your portfolio.
          </p>
        </div>

        {err && (
          <Alert variant="destructive">
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{err}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Status</CardTitle>
            <CardDescription>{status?.cloud_hint}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            <Badge variant={status?.groww_configured ? 'default' : 'secondary'}>
              {status?.groww_configured ? 'Groww env configured' : 'Groww env not set'}
            </Badge>
            <Badge variant={status?.cache_ready ? 'default' : 'outline'}>
              {status?.cache_ready ? 'History cache ready' : 'No Groww cache yet'}
            </Badge>
            {status?.cache_history?.manifest?.history_start && (
              <Badge variant="outline">
                {status.cache_history.manifest.history_start} →{' '}
                {status.cache_history.manifest.history_end} daily
              </Badge>
            )}
            {status?.cache_job?.status === 'running' && (
              <Badge variant="secondary">
                Caching {status.cache_job.symbol || '…'}{' '}
                {status.cache_job.current}/{status.cache_job.total}
              </Badge>
            )}
            {status?.eval_job?.status === 'running' && (
              <Badge variant="secondary">Full eval running…</Badge>
            )}
            <Badge variant="outline">UI dry-run only</Badge>
            {cal?.num_trades != null && (
              <span className="text-xs text-muted-foreground">
                Last Groww calibration: {cal.num_trades} trades · {cal.win_rate}% win ·{' '}
                {cal.total_return_pct}% ret
              </span>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Approaches</CardTitle>
            <CardDescription>
              Saved to params.json — Cloud and scan both read this list. Router still
              gates by cycle phase.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {approaches.map((a) => {
                const on = enabled.includes(a.id)
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => toggleApproach(a.id)}
                    className={`rounded-lg border px-3 py-2 text-left transition ${
                      on ? 'border-primary bg-primary/5' : 'opacity-60'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{a.label}</span>
                      <Badge variant={on ? 'default' : 'outline'}>{on ? 'on' : 'off'}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{a.summary}</p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">{a.id}</p>
                  </button>
                )
              })}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => saveApproaches.mutate(enabled)}
                disabled={saveApproaches.isPending || enabled.length === 0}
              >
                {saveApproaches.isPending ? 'Saving…' : 'Save approaches'}
              </Button>
              {status?.groww_configured && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => refreshCache.mutate()}
                  disabled={
                    refreshCache.isPending || status?.cache_job?.status === 'running'
                  }
                >
                  {status?.cache_job?.status === 'running'
                    ? `Caching ${status.cache_job.current}/${status.cache_job.total}…`
                    : refreshCache.isPending
                      ? 'Starting…'
                      : 'Refresh full Groww history (~2020→now)'}
                </Button>
              )}
              {status?.cache_ready && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => fullEval.mutate()}
                  disabled={
                    fullEval.isPending || status?.eval_job?.status === 'running'
                  }
                >
                  {status?.eval_job?.status === 'running'
                    ? 'Full eval running…'
                    : fullEval.isPending
                      ? 'Starting…'
                      : 'Full eval (baseline + approaches)'}
                </Button>
              )}
            </div>
            {status?.eval_job?.status === 'done' && status.eval_job.result && (
              <div className="rounded-lg border p-3 text-sm">
                <p className="font-medium">Last full eval</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {status.eval_job.message}
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Metric
                    label="Cycle ret"
                    value={`${status.eval_job.result.with_cycle_filter?.total_return_pct ?? '—'}%`}
                  />
                  <Metric
                    label="Baseline"
                    value={`${status.eval_job.result.baseline_technicals_only?.total_return_pct ?? '—'}%`}
                  />
                  <Metric
                    label="Edge"
                    value={`${status.eval_job.result.cycle_edge_return_pct ?? '—'}%`}
                  />
                  <Metric
                    label="Trades"
                    value={`${status.eval_job.result.with_cycle_filter?.num_trades ?? '—'}`}
                  />
                </div>
                {!!status.eval_job.result.recommended_disable?.length && (
                  <p className="mt-2 text-xs text-destructive">
                    Consider disabling:{' '}
                    {status.eval_job.result.recommended_disable
                      .map((d) => `${d.approach} (E[R]=${d.expectancy_r})`)
                      .join(', ')}
                  </p>
                )}
              </div>
            )}
            {status?.eval_job?.status === 'error' && (
              <p className="text-xs text-destructive">{status.eval_job.message}</p>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Backtest (quick smoke)</CardTitle>
              <CardDescription>
                Fast trimmed sample — not promotion. Use Full eval after cache spans
                ~2020→now daily.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Button onClick={() => backtest.mutate()} disabled={backtest.isPending}>
                {backtest.isPending ? 'Running…' : 'Run backtest'}
              </Button>
              {bt && (
                <>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="outline">mode: {bt.mode}</Badge>
                    {bt.elapsed_s != null && (
                      <Badge variant="outline">{bt.elapsed_s}s</Badge>
                    )}
                    {bt.note && (
                      <span className="text-muted-foreground">{bt.note}</span>
                    )}
                  </div>
                  {bt.baseline_note && (
                    <p className="text-[11px] text-muted-foreground">{bt.baseline_note}</p>
                  )}
                  <div className="grid grid-cols-2 gap-2">
                    <Metric
                      label="Cycle return"
                      value={`${bt.with_cycle_filter.total_return_pct}%`}
                    />
                    <Metric
                      label="Baseline return"
                      value={`${bt.baseline_technicals_only.total_return_pct}%`}
                    />
                    <Metric label="Cycle edge" value={`${bt.cycle_edge_return_pct}%`} />
                    <Metric
                      label="Expectancy edge"
                      value={`${bt.cycle_edge_expectancy_r}R`}
                    />
                  </div>
                  <EquitySpark points={bt.with_cycle_filter.equity_curve} />
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    <div>
                      <p className="text-muted-foreground">Win</p>
                      <p className="font-medium tabular-nums">
                        {bt.with_cycle_filter.win_rate}%
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Trades</p>
                      <p className="font-medium tabular-nums">
                        {bt.with_cycle_filter.num_trades}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Max DD</p>
                      <p className="font-medium tabular-nums">
                        {bt.with_cycle_filter.max_drawdown_pct}%
                      </p>
                    </div>
                  </div>
                  {bt.with_cycle_filter.approach_stats &&
                    Object.keys(bt.with_cycle_filter.approach_stats).length > 0 && (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Approach</TableHead>
                            <TableHead className="text-right">N</TableHead>
                            <TableHead className="text-right">Win%</TableHead>
                            <TableHead className="text-right">E[R]</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {Object.entries(bt.with_cycle_filter.approach_stats).map(
                            ([id, s]) => (
                              <TableRow key={id}>
                                <TableCell className="font-mono text-xs">{id}</TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {s.num_trades}
                                </TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {s.win_rate}
                                </TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {s.expectancy_r}
                                </TableCell>
                              </TableRow>
                            )
                          )}
                        </TableBody>
                      </Table>
                    )}
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Scan setups</CardTitle>
              <CardDescription>
                {status?.groww_configured
                  ? 'Live Groww candles + regime router (dry-run).'
                  : 'Demo scan until Groww env is set.'}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Button
                variant="secondary"
                onClick={() => scan.mutate()}
                disabled={scan.isPending}
              >
                {scan.isPending ? 'Scanning…' : 'Scan now'}
              </Button>
              {sc?.message && (
                <p className="text-xs text-muted-foreground">{sc.message}</p>
              )}
              {sc?.groww_error && (
                <p className="text-xs text-destructive">Groww: {sc.groww_error}</p>
              )}
              {sc?.bias && (
                <div className="space-y-2 rounded-lg border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{sc.bias.phase}</Badge>
                    <Badge variant="outline">{sc.bias.sub_phase}</Badge>
                    {sc.bias.risk_off && <Badge variant="destructive">risk-off</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Allowed: {(sc.bias.allowed_sectors || []).join(', ') || 'none'}
                  </p>
                  {sc.router?.eligible_today && (
                    <p className="text-xs text-muted-foreground">
                      Eligible approaches:{' '}
                      {sc.router.eligible_today.length
                        ? sc.router.eligible_today.join(', ')
                        : 'none'}
                    </p>
                  )}
                </div>
              )}
              {sc?.regime_hmm && (
                <p className="text-[11px] text-muted-foreground">
                  HMM diagnostic: P(exp){' '}
                  {((sc.regime_hmm.p_expansion ?? 0) * 100).toFixed(1)}% · size mult{' '}
                  {sc.regime_hmm.size_multiplier}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {sc?.sized && sc.sized.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Sized entries (dry-run)</CardTitle>
              <CardDescription>
                Approach ID is in the Setup column — same payload Groww Cloud would use.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Approach</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Stop</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead className="text-right">Risk</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sc.sized.map((t) => (
                    <TableRow key={`${t.symbol}-${t.setup}`}>
                      <TableCell>
                        <div className="font-medium">{t.symbol}</div>
                        <div className="text-xs text-muted-foreground">{t.sector}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{t.setup}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.entry}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.stop}</TableCell>
                      <TableCell className="text-right tabular-nums">{t.target}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        ₹{Math.round(t.risk_rupees)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {bt?.with_cycle_filter.recent_trades?.length ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Recent backtest trades</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Approach</TableHead>
                    <TableHead>In</TableHead>
                    <TableHead>Out</TableHead>
                    <TableHead className="text-right">PnL</TableHead>
                    <TableHead className="text-right">R</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bt.with_cycle_filter.recent_trades.map((t, i) => (
                    <TableRow key={`${t.symbol}-${t.entry_date}-${i}`}>
                      <TableCell>
                        <div className="font-medium">{t.symbol}</div>
                        <div className="text-xs text-muted-foreground">{t.sector}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{t.setup}</TableCell>
                      <TableCell className="text-xs">{t.entry_date}</TableCell>
                      <TableCell className="text-xs">
                        {t.exit_date}
                        {t.exit_reason ? ` (${t.exit_reason})` : ''}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${
                          t.pnl >= 0 ? 'text-emerald-700' : 'text-destructive'
                        }`}
                      >
                        {t.pnl}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{t.r_multiple}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ) : null}

        <p className="text-xs text-muted-foreground">
          Cloud deploy: <code className="rounded bg-muted px-1">strategies/groww_swing</code>{' '}
          — see <code className="rounded bg-muted px-1">DEPLOY.md</code>. Flip live with{' '}
          <code className="rounded bg-muted px-1">SWING_LIVE=1</code> only after dry-run
          looks sane.
        </p>
      </main>
    </div>
  )
}
