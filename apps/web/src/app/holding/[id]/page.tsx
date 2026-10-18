'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, CalendarDays, CircleAlert } from 'lucide-react'
import { AppNav } from '@/components/app-nav'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  api,
  inr,
  pct,
  type AnalysisRun,
  type DiffResponse,
  type HoldingsResponse,
} from '@/lib/api'
import {
  clusterLabel,
  displayFundName,
  holdingWeight,
  isBroadMarketFund,
  isAnalysisStale,
  isSystemNote,
  needsPlan,
} from '@/lib/decision'
import { cn, formatDate, formatDateTime } from '@/lib/utils'

type ChecklistItem = {
  action: string
  instrument: string
  note?: string
}

export default function HoldingDetailPage() {
  const params = useParams<{ id: string }>()
  const holdingId = Array.isArray(params.id) ? params.id[0] : params.id
  const qc = useQueryClient()

  const holdingsQuery = useQuery({
    queryKey: ['holdings'],
    queryFn: () => api<HoldingsResponse>('/api/decide/holdings'),
  })
  const latestQuery = useQuery({
    queryKey: ['decide-latest'],
    queryFn: () => api<DiffResponse>('/api/decide/latest'),
  })

  const holding = holdingsQuery.data?.holdings.find((row) => row.id === holdingId)
  const originRunId = holding?.opened_by_run_id || null
  const originRunQuery = useQuery({
    queryKey: ['analysis-run', originRunId],
    queryFn: () => api<{ run: AnalysisRun }>(`/api/decide/runs/${originRunId}`),
    enabled: Boolean(originRunId),
  })
  const allHoldings = holdingsQuery.data?.holdings ?? []
  const run = latestQuery.data?.run ?? null
  const row = latestQuery.data?.rows.find((entry) => entry.holding.id === holdingId)
  const stale = !run || isAnalysisStale(run.ran_at)
  const missingPlan = Boolean(holding && needsPlan(holding))
  const broadMarketFund = Boolean(holding && isBroadMarketFund(holding))
  const score = row?.sector_score
  const levels = row?.trade_levels
  const proposal = row?.proposal

  const accept = useMutation({
    mutationFn: async (action: 'keep' | 'sell' | 'extend') => {
      if (!run || !holding) throw new Error('No analysis is available for this holding')
      const holdUntil =
        action === 'extend' ? proposal?.proposed_hold_until : holding.hold_until
      return api<{ checklist: ChecklistItem[] }>('/api/decide/accept', {
        method: 'POST',
        body: JSON.stringify({
          run_id: run.id,
          decisions: [
            {
              holding_id: holding.id,
              sector: holding.sector,
              instrument: holding.instrument,
              action,
              hold_until: holdUntil,
              note:
                action === 'sell'
                  ? 'Added to the Groww checklist from the holding detail.'
                  : 'Reviewed from the holding detail.',
            },
          ],
        }),
      })
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['decide-latest'] })
      await qc.invalidateQueries({ queryKey: ['holdings'] })
    },
  })

  const isLoading = holdingsQuery.isLoading || latestQuery.isLoading
  const error = holdingsQuery.error || latestQuery.error

  return (
    <div className="min-h-screen bg-background">
      <AppNav active="/" />
      <main
        id="main-content"
        className="mx-auto flex max-w-3xl flex-col gap-9 px-4 py-10 sm:px-6 sm:py-14"
      >
        <div>
          <Link
            href="/"
            className="inline-flex h-10 items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            <ArrowLeft aria-hidden className="size-4" />
            Back to Today
          </Link>
        </div>

        {isLoading ? (
          <HoldingSkeleton />
        ) : error ? (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Could not load this holding</AlertTitle>
            <AlertDescription>{(error as Error).message}</AlertDescription>
          </Alert>
        ) : !holding ? (
          <Alert>
            <AlertTitle>Holding not found</AlertTitle>
            <AlertDescription>
              It may have been closed. <Link href="/">Return to Today</Link>.
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <section className="space-y-3 border-b pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{clusterLabel(holding)}</Badge>
                <Badge variant="outline">{holding.asset_class.toUpperCase()}</Badge>
                {missingPlan && <Badge variant="outline">Needs plan</Badge>}
              </div>
              <h1 className="text-3xl font-semibold leading-[1.08] tracking-[-0.04em] sm:text-4xl">
                {displayFundName(holding.instrument)}
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                {inr(holding.market_value)} ·{' '}
                <span className={holding.pnl_pct < 0 ? 'text-destructive' : undefined}>
                  {inr(holding.pnl)} / {pct(holding.pnl_pct)}
                </span>{' '}
                · {Math.round(holdingWeight(holding, allHoldings) * 100)}% of the book
              </p>
            </section>

            {stale ? (
              <Alert>
                <CircleAlert />
                <AlertTitle>The analysis is out of date</AlertTitle>
                <AlertDescription>
                  Pulse will not judge this holding against stale market data.{' '}
                  <Link href="/">Update the analysis from Today.</Link>
                </AlertDescription>
              </Alert>
            ) : missingPlan ? (
              <Alert>
                <CircleAlert />
                <AlertTitle>
                  {broadMarketFund ? 'This fund has no review date' : 'This fund has no plan'}
                </AlertTitle>
                <AlertDescription>
                  {broadMarketFund
                    ? 'It is a broad-market fund, so Pulse does not force a sector score. Set a review date and a reason for owning it before choosing Keep or Sell.'
                    : 'Pulse cannot score this holding against a sector. Set a review date and a reason for owning it before choosing Keep or Sell.'}
                </AlertDescription>
                <div className="mt-4">
                  <Link
                    href={`/holdings#holding-${holding.id}`}
                    className={cn(buttonVariants(), 'h-10 px-4')}
                  >
                    Set the plan
                  </Link>
                </div>
              </Alert>
            ) : proposal ? (
              <section aria-labelledby="call-heading" className="space-y-5">
                <div className="space-y-2">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                    The call
                  </p>
                  <h2 id="call-heading" className="text-2xl font-semibold tracking-[-0.03em]">
                    {proposal.label}
                  </h2>
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    {proposal.suggested === 'sell'
                      ? 'This is a ranking-driven suggestion, not a forced exit. No price stop has been triggered.'
                      : proposal.suggested === 'extend'
                        ? 'The model suggests checking sooner. Your saved review date is still yours to keep.'
                        : proposal.rationale}
                  </p>
                </div>

                {proposal.suggested === 'sell' ? (
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Button
                      variant="destructive"
                      className="h-11 px-4"
                      onClick={() => accept.mutate('sell')}
                      disabled={accept.isPending}
                    >
                      {accept.isPending ? 'Saving…' : 'Add sell to Groww checklist'}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-11 px-4"
                      onClick={() => accept.mutate('keep')}
                      disabled={accept.isPending}
                    >
                      Keep the position
                    </Button>
                  </div>
                ) : proposal.suggested === 'extend' ? (
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Button
                      className="h-11 px-4"
                      onClick={() => accept.mutate('extend')}
                      disabled={accept.isPending}
                    >
                      Use {formatDate(proposal.proposed_hold_until)}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-11 px-4"
                      onClick={() => accept.mutate('keep')}
                      disabled={accept.isPending}
                    >
                      Keep {formatDate(holding.hold_until)}
                    </Button>
                  </div>
                ) : proposal.suggested === 'review' ? (
                  <Link
                    href="/sync"
                    className={cn(buttonVariants({ variant: 'outline' }), 'h-11 w-fit px-4')}
                  >
                    Check the data
                  </Link>
                ) : (
                  <Button
                    className="h-11 px-4"
                    onClick={() => accept.mutate('keep')}
                    disabled={accept.isPending}
                  >
                    Mark reviewed
                  </Button>
                )}

                {accept.data && (
                  <Alert>
                    <AlertTitle>
                      {accept.data.checklist.length ? 'Added to your checklist' : 'Decision saved'}
                    </AlertTitle>
                    <AlertDescription>
                      {accept.data.checklist.length ? (
                        <ul className="flex flex-col gap-1">
                          {accept.data.checklist.map((item, index) => (
                            <li key={`${item.action}-${index}`}>
                              {item.action} · {item.instrument}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        'No Groww action is required.'
                      )}
                    </AlertDescription>
                  </Alert>
                )}
                {accept.error && (
                  <p className="text-sm text-destructive" role="alert">
                    {(accept.error as Error).message}
                  </p>
                )}
              </section>
            ) : null}

            <section aria-labelledby="plan-heading" className="space-y-3 border-t pt-7">
              <div className="flex items-center justify-between gap-4">
                <h2 id="plan-heading" className="text-base font-semibold tracking-[-0.02em]">
                  Your plan
                </h2>
                <Link
                  href={`/holdings#holding-${holding.id}`}
                  className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  Edit plan
                </Link>
              </div>
              <dl className="grid gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">Review by</dt>
                  <dd className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                    <CalendarDays aria-hidden className="size-3.5 text-muted-foreground" />
                    {formatDate(holding.hold_until)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Sector</dt>
                  <dd className="mt-1 text-sm font-medium">
                    {holding.sector || 'Not set'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Opened from</dt>
                  <dd className="mt-1 text-sm font-medium">
                    {originRunQuery.data?.run?.ran_at
                      ? `Pulse analysis · ${formatDate(originRunQuery.data.run.ran_at)}`
                      : originRunId
                        ? 'Pulse analysis'
                        : 'No recorded analysis origin'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Last reviewed</dt>
                  <dd className="mt-1 text-sm font-medium">
                    {holding.last_reviewed_run_id ? 'Recorded in Pulse' : 'Not reviewed yet'}
                  </dd>
                </div>
              </dl>
              <div>
                <p className="text-xs text-muted-foreground">Why you own it</p>
                <p className="mt-1 text-sm leading-6">
                  {holding.reason && !isSystemNote(holding.reason)
                    ? holding.reason
                    : 'No reason has been saved yet.'}
                </p>
              </div>
            </section>

            {levels && score && proposal?.suggested !== 'review' && (
              <section aria-labelledby="levels-heading" className="space-y-4 border-t pt-7">
                <div>
                  <h2 id="levels-heading" className="text-base font-semibold tracking-[-0.02em]">
                    Price levels
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Entry and current value are real. Stop and target are model references, not
                    guarantees.
                  </p>
                </div>
                <dl className="grid grid-cols-2 gap-5 sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-muted-foreground">Entry</dt>
                    <dd className="mt-1 text-sm tabular-nums">
                      {levels.entry != null ? `₹${Number(levels.entry).toFixed(2)}` : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Now</dt>
                    <dd className="mt-1 text-sm tabular-nums">
                      {levels.current != null ? `₹${Number(levels.current).toFixed(2)}` : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Stop</dt>
                    <dd className="mt-1 text-sm tabular-nums">
                      {levels.stop_price != null ? `₹${Number(levels.stop_price).toFixed(2)}` : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Target</dt>
                    <dd className="mt-1 text-sm tabular-nums">
                      {levels.target_price != null
                        ? `₹${Number(levels.target_price).toFixed(2)}`
                        : '—'}
                    </dd>
                  </div>
                </dl>
              </section>
            )}

            {proposal && (
              <details className="border-t pt-7 text-sm">
                <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                  Why the model says this
                </summary>
                <div className="mt-4 flex flex-col gap-3 text-muted-foreground">
                  <p>{proposal.rationale}</p>
                  {score && (
                    <p>
                      {score.sector.replace(/_/g, ' ')} score {score.score}, rated {score.rating}.
                    </p>
                  )}
                  {score?.exit_triggers && <p>{score.exit_triggers}</p>}
                  {run?.ran_at && <p>Analysis run {formatDateTime(run.ran_at)}.</p>}
                </div>
              </details>
            )}
          </>
        )}
      </main>
    </div>
  )
}

function HoldingSkeleton() {
  return (
    <div className="flex flex-col gap-8" aria-label="Loading holding">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-5 w-28" />
        <Skeleton className="h-11 w-full max-w-xl" />
        <Skeleton className="h-5 w-64" />
      </div>
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}
